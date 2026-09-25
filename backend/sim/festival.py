"""Whole-day festival simulation on the coarse-grained social-force engine,
with finer-resolution reruns of the riskiest windows (the two-tier design)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numba
import numpy as np

from ..venue.loader import VenueGrid, rasterize_obstacles
from .behavior import ACTIVE, EXITED, Crowd, Layout, audience_spots
from .crowd_model import EGRESS_MAX_MIN, GATES_OPEN_BEFORE_MIN, arrival_fraction
from .micro import MAX_THREADS, HashGrid, PhysicsParams, advance, wall_fields
from .pathfinding import WalkableSnapper, distance_and_flow_fields
from .risk import DENSITY_ORANGE, RiskAccumulator
from .timeline import parse_setlist

log = logging.getLogger(__name__)

CHUNK_MIN = 0.25  # behaviour decisions run every 15 s of sim time
RISK_SAMPLE_MIN = 1.0
SNAPSHOT_EVERY_MIN = 5.0
DENSITY_FRAME_CELL_M = 4.0  # resolution of the density field sent with each frame
DENSITY_FRAME_MIN = 0.5  # p/m² below which cells are left out of frames
REFINE_WINDOW_MIN = 15.0
REFINE_LEAD_MIN = 10.0  # the window ends this long after the coarse peak
REFINE_MAX_AGENTS = 40_000


@dataclass
class _Context:
    venue: VenueGrid
    occupancy: np.ndarray
    layout: Layout
    flows: np.ndarray
    walls: tuple[np.ndarray, np.ndarray, np.ndarray]
    sets: list[dict]
    draw: dict[str, float]
    affinity: dict[str, dict[str, float]]
    gates_open: float
    music_end: float
    density_red: float
    density_orange: float


def _amenity_features(venue: VenueGrid, amenities: list[dict] | None) -> list[dict]:
    """Venue facilities, or the user's moved amenities (lon/lat) when given."""
    if not amenities:
        return [
            f
            for f in venue.facilities
            if f.get("facility_type") in ("restroom", "water", "bar")
        ]
    out = []
    for a in amenities:
        if a.get("facility_type") not in ("restroom", "water", "bar"):
            continue
        x, y = venue.to_utm(float(a["lon"]), float(a["lat"]))
        out.append({**a, "pos_m": [float(x), float(y)]})
    return out


def _build_layout(
    venue: VenueGrid,
    occupancy: np.ndarray,
    stage_ids: list[str],
    amenities: list[dict],
):
    snapper = WalkableSnapper(occupancy, venue.origin_m, venue.cell_m)
    stages = {s["id"]: s for s in venue.stages}

    if venue.gates:
        gate_raw = np.array([g["pos_m"] for g in venue.gates], dtype=np.float64)
        cap_pph = np.array(
            [float(g.get("capacity_pph") or np.inf) for g in venue.gates]
        )
    else:
        rows, cols = occupancy.shape
        centre = [
            venue.origin_m[0] + cols * venue.cell_m / 2,
            venue.origin_m[1] + rows * venue.cell_m / 2,
        ]
        gate_raw = np.array([centre])
        cap_pph = np.array([np.inf])
    weights = np.where(np.isfinite(cap_pph), cap_pph, 1.0)
    stage_raw = np.array(
        [stages[sid]["pos_m"] for sid in stage_ids], dtype=np.float64
    ).reshape(-1, 2)
    amen_raw = np.array([f["pos_m"] for f in amenities], dtype=np.float64).reshape(
        -1, 2
    )

    points = np.vstack([gate_raw, stage_raw, amen_raw])
    r, c = snapper.snap_rc(points)
    dists, flows = distance_and_flow_fields(
        occupancy, venue.cell_m, list(zip(r.tolist(), c.tolist(), strict=True))
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
        gate_capacity_ppm=cap_pph / 60.0,
        stage_ids=stage_ids,
        stage_pts=snapped[g : g + s],
        stage_spots=[(a[0], a[1]) for a in audience],
        stage_reach=np.array([a[2] for a in audience]),
        amenity_pts=snapped[g + s :],
        amenity_types=np.array([f["facility_type"] for f in amenities], dtype=object),
    )
    return layout, flows


class _DensityFrames:
    """Coarsened density field for playback: [lon, lat, ρ] per non-empty block."""

    def __init__(self, venue: VenueGrid, occupancy: np.ndarray):
        self.k = max(1, int(round(DENSITY_FRAME_CELL_M / venue.cell_m)))
        rows, cols = occupancy.shape
        self.rows, self.cols = rows // self.k, cols // self.k
        self.cell_m = self.k * venue.cell_m
        walk = occupancy[: self.rows * self.k, : self.cols * self.k]
        self.walk_frac = walk.reshape(self.rows, self.k, self.cols, self.k).mean(
            axis=(1, 3)
        )
        rr, cc = np.meshgrid(np.arange(self.rows), np.arange(self.cols), indexing="ij")
        lon, lat = venue.to_lonlat(
            venue.origin_m[0] + (cc + 0.5) * self.cell_m,
            venue.origin_m[1] + (rr + 0.5) * self.cell_m,
        )
        self.lon = np.round(np.asarray(lon), 6)
        self.lat = np.round(np.asarray(lat), 6)

    def encode(self, density: np.ndarray) -> list[list[float]]:
        d = density[: self.rows * self.k, : self.cols * self.k]
        block = d.reshape(self.rows, self.k, self.cols, self.k).sum(axis=(1, 3))
        with np.errstate(invalid="ignore", divide="ignore"):
            block = np.where(
                self.walk_frac > 0, block / (self.k**2 * self.walk_frac), 0.0
            )
        r, c = np.nonzero(block >= DENSITY_FRAME_MIN)
        return np.column_stack(
            [self.lon[r, c], self.lat[r, c], np.round(block[r, c], 1)]
        ).tolist()


def _frame(t_min: float, crowd: Crowd, ctx: _Context, density: list) -> dict:
    vis = crowd.status == ACTIVE
    agents: list[list[float]] = []
    if vis.any():
        lons, lats = ctx.venue.to_lonlat(crowd.pos[vis, 0], crowd.pos[vis, 1])
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
        "density": density,
        "n_active": int(vis.sum()),
        "n_arrived": int(crowd.n_arrived),
        "n_exited": int((crowd.status == EXITED).sum()),
        "gate_queue": crowd.gate_queue(),
        "scale": crowd.scale,
    }


def _run(
    ctx: _Context,
    crowd: Crowd,
    dt: float,
    t_from: float,
    t_to: float,
    risk: RiskAccumulator,
    risk_from: float,
    frame_every: float | None = None,
    frames: list | None = None,
    density_frames: _DensityFrames | None = None,
    snapshots: dict | None = None,
) -> None:
    """Advance `crowd` from t_from to t_to, or until everyone has left."""
    venue = ctx.venue
    params = PhysicsParams.for_scale(crowd.scale, dt)
    prm = params.vector()
    hgrid = HashGrid(ctx.occupancy.shape, venue.cell_m, params.cutoff, crowd.n)
    steps_per_chunk = max(1, int(round(CHUNK_MIN * 60.0 / dt)))
    ox, oy = venue.origin_m
    eps = 1e-9

    next_frame = t_from
    next_snapshot = t_from
    next_risk = t_from + RISK_SAMPLE_MIN
    t = t_from
    while t <= t_to + eps:
        target = int(arrival_fraction(t, ctx.gates_open, ctx.music_end) * crowd.n)
        crowd.spawn(target - crowd.n_arrived, t, CHUNK_MIN)
        crowd.update(t, CHUNK_MIN, ctx.music_end)

        if snapshots is not None and t >= next_snapshot - eps:
            snapshots[t] = crowd.snapshot()
            next_snapshot += SNAPSHOT_EVERY_MIN
        if frames is not None and t >= next_frame - eps:
            density = []
            if density_frames is not None:
                on = crowd.status == ACTIVE
                d, _ = risk.fields(crowd.pos[on], crowd.vel[on], crowd.scale)
                density = density_frames.encode(d)
            frames.append(_frame(t, crowd, ctx, density))
            next_frame += frame_every
        if crowd.n_arrived >= crowd.n and not (crowd.status == ACTIVE).any():
            if frames is not None and frames and frames[-1]["t_min"] != t:
                frames.append(_frame(t, crowd, ctx, []))
            break

        advance(
            steps_per_chunk,
            crowd.pos, crowd.vel, crowd.status, crowd.target, crowd.flow_id,
            crowd.v0, crowd.heading, crowd.exit_on_arrival, crowd.arrived,
            ctx.flows, ctx.layout.dists, *ctx.walls, ctx.occupancy,
            float(ox), float(oy), float(venue.cell_m),
            hgrid.cell, hgrid.rows, hgrid.cols, hgrid.head, hgrid.nxt,
            hgrid.agent_cell, hgrid.forces,
            prm,
        )  # fmt: skip
        t += CHUNK_MIN

        if t >= next_risk - eps:
            if t >= risk_from - eps:
                on = crowd.status == ACTIVE
                risk.add(crowd.pos[on], crowd.vel[on], crowd.scale, t, RISK_SAMPLE_MIN)
            next_risk += RISK_SAMPLE_MIN


def _pick_windows(timeline: list[dict], n: int) -> list[tuple[float, float]]:
    """Up to n non-overlapping windows around the minutes with the most people in red."""
    windows: list[tuple[float, float]] = []
    for e in sorted(timeline, key=lambda e: -e["people_in_red"]):
        if len(windows) >= n or e["people_in_red"] <= 0:
            break
        t0 = e["t_min"] - (REFINE_WINDOW_MIN - REFINE_LEAD_MIN)
        t1 = t0 + REFINE_WINDOW_MIN
        if all(t1 <= a or t0 >= b for a, b in windows):
            windows.append((t0, t1))
    return sorted(windows)


def _refine(
    ctx: _Context,
    windows: list[tuple[float, float]],
    snapshots: dict,
    coarse: Crowd,
    coarse_timeline: list[dict],
    people_per_agent: float,
    dt: float,
    seed: int,
) -> list[dict]:
    """Re-simulate each window from the preceding snapshot with every coarse agent
    split into k finer ones, so crowd physics runs closer to one agent per person."""
    k = int(round(coarse.scale / people_per_agent))
    k = min(k, REFINE_MAX_AGENTS // max(coarse.n, 1))
    if k < 2:
        return []
    spread = PhysicsParams.for_scale(coarse.scale, dt).radius
    results = []
    for i, (t0, t1) in enumerate(windows):
        starts = [t for t in snapshots if t <= t0 + 1e-9]
        if not starts:
            continue
        t_snap = max(starts)
        fine = Crowd(
            coarse.n * k,
            ctx.layout,
            ctx.sets,
            ctx.draw,
            ctx.affinity,
            np.random.default_rng(seed + 1 + i),
            ctx.venue.cell_m,
            coarse.scale / k,
        )
        fine.load_refined(snapshots[t_snap], k, spread)
        risk = RiskAccumulator(
            ctx.occupancy,
            ctx.venue.origin_m,
            ctx.venue.cell_m,
            density_red=ctx.density_red,
            density_orange=ctx.density_orange,
        )
        _run(ctx, fine, dt, t_snap, t1, risk, risk_from=t0)
        res = risk.result(ctx.venue.to_lonlat)
        coarse_red = sum(
            e["people_in_red"] for e in coarse_timeline if t0 < e["t_min"] <= t1
        )
        for h in res.hotspots:
            h["people_per_agent"] = round(fine.scale, 2)
            h["refined"] = True
        results.append(
            {
                "t_start": t0,
                "t_end": t1,
                "people_per_agent": round(fine.scale, 2),
                "peak_density": round(res.peak_density, 2),
                "peak_pressure": round(res.peak_pressure, 4),
                "red_exposure_person_min": round(res.red_exposure_person_min, 1),
                "coarse_red_exposure_person_min": round(
                    coarse_red * RISK_SAMPLE_MIN, 1
                ),
                "hotspots": res.hotspots,
            }
        )
    return results


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
    amenities: list[dict] | None = None,
    refine_windows: int = 0,
    refine_people_per_agent: float = 3.0,
    density_frames: bool = True,
) -> dict:
    """Simulate the festival day. With refine_windows > 0 the riskiest windows are
    re-simulated at ~refine_people_per_agent and their hotspots replace the coarse ones.
    """
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
    layout, flows = _build_layout(
        venue, occupancy, stage_ids, _amenity_features(venue, amenities)
    )
    music_start = min(s["start_min"] for s in sets)
    music_end = max(s["end_min"] for s in sets)
    ctx = _Context(
        venue=venue,
        occupancy=occupancy,
        layout=layout,
        flows=flows,
        walls=wall_fields(occupancy, venue.cell_m),
        sets=sets,
        draw=draw,
        affinity=affinity or {},
        gates_open=music_start - GATES_OPEN_BEFORE_MIN,
        music_end=music_end,
        density_red=density_red,
        density_orange=density_orange,
    )

    scale = tickets_sold / n_agents
    crowd = Crowd(n_agents, layout, sets, draw, ctx.affinity, rng, venue.cell_m, scale)
    risk = RiskAccumulator(
        occupancy,
        venue.origin_m,
        venue.cell_m,
        density_red=density_red,
        density_orange=density_orange,
    )
    frames: list[dict] = []
    snapshots: dict | None = {} if refine_windows > 0 else None
    _run(
        ctx,
        crowd,
        dt,
        ctx.gates_open,
        music_end + EGRESS_MAX_MIN,
        risk,
        risk_from=ctx.gates_open,
        frame_every=sim_bin_minutes * max(1, sample_every_bins),
        frames=frames,
        density_frames=_DensityFrames(venue, occupancy) if density_frames else None,
        snapshots=snapshots,
    )
    result = risk.result(venue.to_lonlat)
    for h in result.hotspots:
        h["people_per_agent"] = round(scale, 2)
        h["refined"] = False

    refined: list[dict] = []
    hotspots = result.hotspots
    if refine_windows > 0:
        windows = _pick_windows(result.timeline, refine_windows)
        refined = _refine(
            ctx,
            windows,
            snapshots,
            crowd,
            result.timeline,
            refine_people_per_agent,
            dt,
            seed,
        )
        spans = [(w["t_start"], w["t_end"]) for w in refined]
        hotspots = [
            h for h in hotspots if not any(a <= h["t_peak_min"] <= b for a, b in spans)
        ] + [h for w in refined for h in w["hotspots"]]
        hotspots.sort(key=lambda h: (-h["exposure_person_min"], -h["peak_density"]))

    return {
        "frames": frames,
        "hotspots": hotspots,
        "metrics": {
            "peak_density": round(result.peak_density, 2),
            "peak_pressure": round(result.peak_pressure, 4),
            "red_exposure_person_min": round(result.red_exposure_person_min, 1),
            "density_red": density_red,
            "density_orange": density_orange,
            "people_per_agent": round(scale, 2),
            "density_cell_m": DENSITY_FRAME_CELL_M,
            "timeline": result.timeline,
            "refined_windows": refined,
        },
    }
