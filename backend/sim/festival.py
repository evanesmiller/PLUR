"""Whole-day festival simulation: arrival at the gates, set-to-set migration,
amenity visits and egress, on the coarse-grained social-force engine."""

from __future__ import annotations

import logging

import numba
import numpy as np

from ..venue.loader import VenueGrid, rasterize_obstacles
from .behavior import ACTIVE, EXITED, Crowd, Layout, audience_spots
from .micro import MAX_THREADS, HashGrid, PhysicsParams, advance, wall_fields
from .pathfinding import WalkableSnapper, distance_and_flow_fields
from .risk import DENSITY_ORANGE, RiskAccumulator
from .timeline import parse_setlist

log = logging.getLogger(__name__)

GATES_OPEN_BEFORE_MIN = 60
EGRESS_WINDOW_MIN = 120
CHUNK_MIN = 0.25  # behaviour decisions run every 15 s of sim time
RISK_SAMPLE_MIN = 1.0


def _arrival_fraction(t: float, gates_open: float, music_end: float) -> float:
    total = music_end - gates_open
    if total <= 0:
        return 1.0
    x = min(max((t - gates_open) / total, 0.0), 1.0)
    lo = 1.0 / (1.0 + np.exp(8.0 * 0.35))
    return (1.0 / (1.0 + np.exp(-8.0 * (x - 0.35))) - lo) / (
        1.0 / (1.0 + np.exp(-8.0 * 0.65)) - lo
    )


def _build_layout(venue: VenueGrid, occupancy: np.ndarray, stage_ids: list[str]):
    snapper = WalkableSnapper(occupancy, venue.origin_m, venue.cell_m)
    stages = {s["id"]: s for s in venue.stages}

    if venue.gates:
        gate_raw = np.array([g["pos_m"] for g in venue.gates], dtype=np.float64)
        weights = np.array([float(g.get("capacity_pph") or 1.0) for g in venue.gates])
    else:
        rows, cols = occupancy.shape
        gate_raw = np.array(
            [
                [
                    venue.origin_m[0] + cols * venue.cell_m / 2,
                    venue.origin_m[1] + rows * venue.cell_m / 2,
                ]
            ]
        )
        weights = np.ones(1)
    stage_raw = np.array(
        [stages[sid]["pos_m"] for sid in stage_ids], dtype=np.float64
    ).reshape(-1, 2)
    amenities = [
        f
        for f in venue.facilities
        if f.get("facility_type") in ("restroom", "water", "bar")
    ]
    amen_raw = np.array([f["pos_m"] for f in amenities], dtype=np.float64).reshape(
        -1, 2
    )

    points = np.vstack([gate_raw, stage_raw, amen_raw])
    r, c = snapper.snap_rc(points)
    dists, flows = distance_and_flow_fields(
        occupancy, venue.cell_m, list(zip(r.tolist(), c.tolist()))
    )
    snapped = snapper.center(r, c)
    g, s = len(gate_raw), len(stage_raw)

    audience = [
        audience_spots(
            snapped[g + i],
            stages[sid].get("orientation"),
            stages[sid].get("capacity_area_m2"),
            dists[g + i],
            snapper,
        )
        for i, sid in enumerate(stage_ids)
    ]
    layout = Layout(
        snapper=snapper,
        dists=dists,
        gate_pts=snapped[:g],
        gate_weights=weights / weights.sum(),
        stage_ids=stage_ids,
        stage_pts=snapped[g : g + s],
        stage_spots=[(a[0], a[1]) for a in audience],
        stage_reach=np.array([a[2] for a in audience]),
        amenity_pts=snapped[g + s :],
        amenity_types=np.array([f["facility_type"] for f in amenities], dtype=object),
    )
    return layout, flows


def _frame(t_min: float, crowd: Crowd, venue: VenueGrid, scale: float) -> dict:
    vis = crowd.status == ACTIVE
    agents: list[list[float]] = []
    if vis.any():
        lons, lats = venue.to_lonlat(crowd.pos[vis, 0], crowd.pos[vis, 1])
        v = crowd.vel[vis]
        agents = np.column_stack(
            [
                np.round(lons, 6),
                np.round(lats, 6),
                np.round(v[:, 0], 2),
                np.round(v[:, 1], 2),
            ]
        ).tolist()
    return {
        "t_min": float(t_min),
        "agents": agents,
        "n_active": int(vis.sum()),
        "n_arrived": int(crowd.n_arrived),
        "n_exited": int((crowd.status == EXITED).sum()),
        "scale": scale,
    }


def run_festival(
    venue: VenueGrid,
    setlist: list[dict],
    draw: dict[str, float],
    tickets_sold: int,
    n_agents: int = 1500,
    dt: float = 0.1,
    sim_bin_minutes: float = 2.0,
    sample_every_bins: int = 1,
    extra_obstacles: list[list[list[float]]] | None = None,
    density_red: float = 6.0,
    affinity: dict[str, dict[str, float]] | None = None,
    density_orange: float = DENSITY_ORANGE,
    seed: int = 42,
) -> dict:
    rng = np.random.default_rng(seed)
    numba.set_num_threads(min(MAX_THREADS, numba.config.NUMBA_NUM_THREADS))
    empty = {"frames": [], "hotspots": [], "metrics": {}}

    stage_known = {s["id"] for s in venue.stages}
    sets = parse_setlist(setlist)
    dropped = [s["artist"] for s in sets if s["stage"] not in stage_known]
    if dropped:
        log.warning("Ignoring sets on stages missing from the venue: %s", dropped)
    sets = [s for s in sets if s["stage"] in stage_known]
    if not sets or n_agents <= 0:
        return empty

    occupancy = rasterize_obstacles(venue, extra_obstacles or [])
    stage_ids = sorted({s["stage"] for s in sets})
    layout, flows = _build_layout(venue, occupancy, stage_ids)

    scale = tickets_sold / n_agents
    params = PhysicsParams.for_scale(scale, dt)
    prm = params.vector()
    wall_dist, wall_gx, wall_gy = wall_fields(occupancy, venue.cell_m)
    hgrid = HashGrid(occupancy.shape, venue.cell_m, params.cutoff, n_agents)
    crowd = Crowd(n_agents, layout, sets, draw, affinity or {}, rng, venue.cell_m)
    risk = RiskAccumulator(
        occupancy,
        venue.origin_m,
        venue.cell_m,
        density_red=density_red,
        density_orange=density_orange,
    )

    music_start = min(s["start_min"] for s in sets)
    music_end = max(s["end_min"] for s in sets)
    gates_open = music_start - GATES_OPEN_BEFORE_MIN
    t_stop = music_end + EGRESS_WINDOW_MIN
    frame_every = sim_bin_minutes * max(1, sample_every_bins)
    steps_per_chunk = max(1, int(round(CHUNK_MIN * 60.0 / dt)))
    ox, oy = venue.origin_m

    frames: list[dict] = []
    next_frame = gates_open
    next_risk = gates_open + RISK_SAMPLE_MIN
    t = gates_open
    eps = 1e-9
    while t <= t_stop + eps:
        target_arrived = int(_arrival_fraction(t, gates_open, music_end) * n_agents)
        crowd.spawn(target_arrived - crowd.n_arrived, t)
        crowd.update(t, CHUNK_MIN, music_end)

        if t >= next_frame - eps:
            frames.append(_frame(t, crowd, venue, scale))
            next_frame += frame_every
        if crowd.n_arrived >= n_agents and not (crowd.status == ACTIVE).any():
            break

        advance(
            steps_per_chunk,
            crowd.pos,
            crowd.vel,
            crowd.status,
            crowd.target,
            crowd.flow_id,
            crowd.v0,
            crowd.heading,
            crowd.exit_on_arrival,
            crowd.arrived,
            flows,
            layout.dists,
            wall_dist,
            wall_gx,
            wall_gy,
            occupancy,
            float(ox),
            float(oy),
            float(venue.cell_m),
            hgrid.cell,
            hgrid.rows,
            hgrid.cols,
            hgrid.head,
            hgrid.nxt,
            hgrid.agent_cell,
            hgrid.forces,
            prm,
        )
        t += CHUNK_MIN

        if t >= next_risk - eps:
            on_site = crowd.status == ACTIVE
            risk.add(crowd.pos[on_site], crowd.vel[on_site], scale, t, RISK_SAMPLE_MIN)
            next_risk += RISK_SAMPLE_MIN

    result = risk.result(venue.to_lonlat)
    return {
        "frames": frames,
        "hotspots": result.hotspots,
        "metrics": {
            "peak_density": round(result.peak_density, 2),
            "peak_pressure": round(result.peak_pressure, 4),
            "red_exposure_person_min": round(result.red_exposure_person_min, 1),
            "density_red": density_red,
            "density_orange": density_orange,
            "people_per_agent": round(scale, 2),
            "timeline": result.timeline,
        },
    }
