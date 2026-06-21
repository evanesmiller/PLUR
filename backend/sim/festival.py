"""Full-festival simulation: agents enter at the gate, walk to stages via
flow-field pathfinding, migrate between sets, and exit at the end."""
from __future__ import annotations

import numpy as np
from ..venue.loader import VenueGrid, load_venue_from_geojson
from .pathfinding import FlowFieldCache, sample_flow
from .micro import _precompute_walls, _build_spatial_hash, _force_kernel
from .micro import (
    V0_MEAN, V0_STD, TAU, A_REP, B_REP, A_WALL, B_WALL,
    RADIUS, MASS, K_BODY, KAPPA, MAX_SPEED, HASH_CELL,
)


def _parse_time(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _arrival_curve(t_minutes: np.ndarray, gates_open_min: int, event_end_min: int) -> np.ndarray:
    total = event_end_min - gates_open_min
    if total <= 0:
        return np.ones_like(t_minutes, dtype=float)
    x = np.clip((t_minutes - gates_open_min) / total, 0.0, 1.0)
    return np.clip(1.0 / (1.0 + np.exp(-8.0 * (x - 0.35))), 0.0, 1.0)


def _concurrent_sets(setlist: list[dict], t_min: int) -> list[dict]:
    return [s for s in setlist if s["start_min"] <= t_min < s["end_min"]]


def _just_ended(setlist: list[dict], t_min: int, window: int = 5) -> list[dict]:
    return [s for s in setlist if 0 < t_min - s["end_min"] <= window]


def _upcoming_sets(setlist: list[dict], t_min: int, lookahead: int = 60) -> list[dict]:
    return [s for s in setlist if 0 < s["start_min"] - t_min <= lookahead]


def _find_walkable_near(occupancy, ox, oy, cell_m, target_x, target_y, radius=15):
    rows, cols = occupancy.shape
    tc = int((target_x - ox) / cell_m)
    tr = int((target_y - oy) / cell_m)
    search = int(radius / cell_m) + 1
    for dr in range(-search, search + 1):
        for dc in range(-search, search + 1):
            nr, nc = tr + dr, tc + dc
            if 0 <= nr < rows and 0 <= nc < cols and occupancy[nr, nc]:
                return ox + (nc + 0.5) * cell_m, oy + (nr + 0.5) * cell_m
    return target_x, target_y


def run_festival(
    venue: VenueGrid,
    setlist: list[dict],
    draw: dict[str, float],
    tickets_sold: int,
    n_agents: int = 1500,
    dt: float = 0.5,
    sim_bin_minutes: float = 2.0,
    sample_every_bins: int = 1,
    extra_obstacles: list[list[list[float]]] | None = None,
    density_red: float = 6.0,
    affinity: dict[str, dict[str, float]] | None = None,
    seed: int = 42,
) -> dict:
    rng = np.random.default_rng(seed)

    # --- rebuild occupancy if extra barriers ---
    occupancy = venue.occupancy.copy().astype(bool)
    if extra_obstacles:
        from shapely.geometry import Polygon, Point
        ox, oy = venue.origin_m
        for poly_coords in extra_obstacles:
            utm_coords = []
            for lon, lat in poly_coords:
                x, y = venue.to_utm(lon, lat)
                utm_coords.append((x, y))
            barrier_poly = Polygon(utm_coords)
            min_r = max(0, int((barrier_poly.bounds[1] - oy) / venue.cell_m) - 1)
            max_r = min(occupancy.shape[0], int((barrier_poly.bounds[3] - oy) / venue.cell_m) + 2)
            min_c = max(0, int((barrier_poly.bounds[0] - ox) / venue.cell_m) - 1)
            max_c = min(occupancy.shape[1], int((barrier_poly.bounds[2] - ox) / venue.cell_m) + 2)
            for r in range(min_r, max_r):
                for c in range(min_c, max_c):
                    cx = ox + (c + 0.5) * venue.cell_m
                    cy = oy + (r + 0.5) * venue.cell_m
                    if barrier_poly.contains(Point(cx, cy)):
                        occupancy[r, c] = False

    # --- precompute walls + flow fields ---
    wall_dist, wall_gx, wall_gy = _precompute_walls(occupancy, venue.cell_m)
    flow_cache = FlowFieldCache(occupancy, venue.cell_m, venue.origin_m)

    stage_map = {s["id"]: np.array(s["pos_m"]) for s in venue.stages}
    gate_pos = np.array(venue.gates[0]["pos_m"]) if venue.gates else np.array(venue.origin_m)

    for sid, spos in stage_map.items():
        flow_cache.get_flow(f"stage_{sid}", (spos[0], spos[1]))
    flow_cache.get_flow("gate", (gate_pos[0], gate_pos[1]))

    ox, oy = venue.origin_m
    rows, cols = occupancy.shape

    # --- parse setlist ---
    parsed = []
    for e in setlist:
        parsed.append({
            **e,
            "start_min": _parse_time(e["start"]),
            "end_min": _parse_time(e["end"]),
        })

    if not parsed:
        return {"frames": [], "hotspots": []}

    music_start = min(p["start_min"] for p in parsed)
    music_end = max(p["end_min"] for p in parsed)
    gates_open = music_start - 60

    scale = tickets_sold / max(n_agents, 1)

    # --- spawn positions: clamp to walkable cells near gate ---
    gate_x, gate_y = _find_walkable_near(occupancy, ox, oy, venue.cell_m, gate_pos[0], gate_pos[1])
    spawn_offsets = rng.normal(0, 5.0, (n_agents, 2))
    spawn_positions = np.zeros((n_agents, 2), dtype=np.float64)
    for i in range(n_agents):
        sx, sy = gate_x + spawn_offsets[i, 0], gate_y + spawn_offsets[i, 1]
        sx, sy = _find_walkable_near(occupancy, ox, oy, venue.cell_m, sx, sy, radius=20)
        spawn_positions[i] = [sx, sy]

    # --- pre-assign each agent to their first stage ---
    all_first_dest = []
    if parsed:
        first_sets = sorted(parsed, key=lambda p: p["start_min"])
        first_batch = [s for s in first_sets if s["start_min"] == first_sets[0]["start_min"]]
        if not first_batch:
            first_batch = first_sets[:max(1, len(stage_map))]
        first_draws = np.array([draw.get(s["artist"], 0.5) for s in first_batch])
        exp_d = np.exp(first_draws * 2.0)
        first_probs = exp_d / exp_d.sum()
        choices = rng.choice(len(first_batch), size=n_agents, p=first_probs)
        for i in range(n_agents):
            sid = first_batch[choices[i]]["stage"]
            all_first_dest.append(f"stage_{sid}")
    else:
        all_first_dest = ["gate"] * n_agents

    # --- agent state arrays ---
    all_pos = np.full((n_agents, 2), np.nan, dtype=np.float64)
    all_vel = np.zeros((n_agents, 2), dtype=np.float64)
    all_v0 = rng.normal(V0_MEAN, V0_STD, n_agents).clip(0.5, 2.5).astype(np.float64)
    all_dest_key = np.array(all_first_dest, dtype=object)
    all_active = np.zeros(n_agents, dtype=bool)
    all_exited = np.zeros(n_agents, dtype=bool)

    hash_cols = int(np.ceil(cols * venue.cell_m / HASH_CELL)) + 2
    hash_rows = int(np.ceil(rows * venue.cell_m / HASH_CELL)) + 2

    # --- sim loop: run until all agents exit ---
    frames: list[dict] = []
    steps_per_bin = max(1, int(sim_bin_minutes * 60 / dt))
    arrived_count = 0
    max_duration_min = (music_end - gates_open) + 120
    n_bins = int(np.ceil(max_duration_min / sim_bin_minutes)) + 1

    t_array = np.array([gates_open + b * sim_bin_minutes for b in range(n_bins)])
    arrival_frac = _arrival_curve(t_array, gates_open, music_end)

    # track peak instantaneous density per cell (people/m²) across all bins
    density_accum = np.zeros((rows, cols), dtype=np.float64)

    for b in range(n_bins):
        t_min = gates_open + b * sim_bin_minutes

        # early exit: all agents exited
        if arrived_count >= n_agents and all_exited.sum() >= n_agents:
            break

        # --- spawn new agents (assigned to first stage immediately) ---
        target_arrived = int(arrival_frac[min(b, len(arrival_frac) - 1)] * n_agents)
        new_count = max(0, target_arrived - arrived_count)
        if new_count > 0:
            spawn_indices = np.where(~all_active & ~all_exited)[0][:new_count]
            for idx in spawn_indices:
                all_pos[idx] = spawn_positions[idx]
                all_active[idx] = True
            arrived_count += len(spawn_indices)

        # --- assign destinations ---
        active_mask = all_active & ~all_exited
        concurrent = _concurrent_sets(parsed, int(t_min))
        ended = _just_ended(parsed, int(t_min))

        if t_min >= music_end:
            # EGRESS: everyone heads to gate aggressively
            active_indices = np.where(active_mask)[0]
            minutes_after = t_min - music_end
            for idx in active_indices:
                if all_dest_key[idx] != "gate":
                    # stagger: most leave immediately, stragglers within 15 min
                    if rng.random() < 0.4 + 0.6 * min(1.0, minutes_after / 15.0):
                        all_dest_key[idx] = "gate"
        elif concurrent:
            draws_arr = np.array([draw.get(s["artist"], 0.5) for s in concurrent])

            active_indices = np.where(active_mask)[0]
            if len(active_indices) > 0:
                needs_dest = np.zeros(len(active_indices), dtype=bool)
                agent_prev_stage: dict[int, str | None] = {}
                ended_stage_set = {e["stage"] for e in ended}

                for ai, idx in enumerate(active_indices):
                    dk = all_dest_key[idx]
                    if dk == "gate":
                        needs_dest[ai] = True
                        agent_prev_stage[ai] = None
                    elif ended and dk.startswith("stage_") and dk[6:] in ended_stage_set:
                        needs_dest[ai] = True
                        agent_prev_stage[ai] = dk[6:]

                reassign = active_indices[needs_dest]
                if len(reassign) > 0:
                    for ri, idx in enumerate(reassign):
                        ai = np.where(active_indices == idx)[0][0]
                        prev_stage = agent_prev_stage.get(ai)

                        if prev_stage and affinity:
                            # find which artist just ended at that stage
                            prev_artist = next(
                                (e["artist"] for e in ended if e["stage"] == prev_stage), None
                            )
                            if prev_artist:
                                # 60% draw + 40% affinity toward the act they just watched
                                aff_scores = np.array([
                                    affinity.get(prev_artist, {}).get(s["artist"], 0.0)
                                    for s in concurrent
                                ])
                                combined = 0.6 * draws_arr + 0.4 * aff_scores
                                exp_d = np.exp(combined * 2.0)
                                probs = exp_d / exp_d.sum()
                                choice = rng.choice(len(concurrent), p=probs)
                                all_dest_key[idx] = f"stage_{concurrent[choice]['stage']}"
                                continue

                        # fallback: pure draw-based probability
                        exp_d = np.exp(draws_arr * 2.0)
                        probs = exp_d / exp_d.sum()
                        choice = rng.choice(len(concurrent), p=probs)
                        all_dest_key[idx] = f"stage_{concurrent[choice]['stage']}"

        # --- physics steps ---
        active_indices = np.where(all_active & ~all_exited)[0]
        n_active = len(active_indices)

        if n_active > 0:
            a_pos = all_pos[active_indices].copy()
            a_vel = all_vel[active_indices].copy()
            a_v0 = all_v0[active_indices]

            # compute flow-based destinations with angular noise
            a_dest = np.zeros((n_active, 2), dtype=np.float64)
            for ai, idx in enumerate(active_indices):
                dk = all_dest_key[idx]
                if dk == "gate":
                    flow = flow_cache.get_flow("gate", (gate_pos[0], gate_pos[1]))
                else:
                    sid = dk[6:]
                    if sid in stage_map:
                        flow = flow_cache.get_flow(dk, (stage_map[sid][0], stage_map[sid][1]))
                    else:
                        flow = flow_cache.get_flow("gate", (gate_pos[0], gate_pos[1]))

                fx, fy = sample_flow(
                    flow, a_pos[ai, 0], a_pos[ai, 1],
                    ox, oy, venue.cell_m, rows, cols,
                )

                # fallback: if flow is zero, use direct vector to target
                if abs(fx) < 1e-9 and abs(fy) < 1e-9:
                    if dk == "gate":
                        target = gate_pos
                    elif dk.startswith("stage_") and dk[6:] in stage_map:
                        target = stage_map[dk[6:]]
                    else:
                        target = gate_pos
                    diff = target - a_pos[ai]
                    mag = np.linalg.norm(diff)
                    if mag > 1e-9:
                        fx, fy = diff[0] / mag, diff[1] / mag

                # add angular noise (±15°)
                noise_angle = rng.normal(0, 0.26)
                cos_n, sin_n = np.cos(noise_angle), np.sin(noise_angle)
                fx_r = fx * cos_n - fy * sin_n
                fy_r = fx * sin_n + fy * cos_n

                a_dest[ai] = a_pos[ai] + np.array([fx_r, fy_r]) * 50.0

            for step in range(steps_per_bin):
                sorted_agents, cell_offsets = _build_spatial_hash(
                    a_pos, HASH_CELL, ox, oy, hash_rows, hash_cols,
                )
                forces = _force_kernel(
                    a_pos, a_vel, a_dest, a_v0,
                    wall_dist, wall_gx, wall_gy,
                    float(ox), float(oy), float(venue.cell_m), rows, cols,
                    sorted_agents, cell_offsets,
                    float(ox), float(oy), float(HASH_CELL), hash_rows, hash_cols,
                    MASS, TAU, A_REP, B_REP, A_WALL, B_WALL, K_BODY, KAPPA, RADIUS,
                )
                new_vel = a_vel + (forces / MASS) * dt
                speed = np.linalg.norm(new_vel, axis=1, keepdims=True)
                mask = speed > MAX_SPEED
                new_vel = np.where(mask, new_vel / speed * MAX_SPEED, new_vel)
                new_pos = a_pos + new_vel * dt

                # wall handling: slide along wall instead of bounce
                gi = np.clip(((new_pos[:, 1] - oy) / venue.cell_m).astype(int), 0, rows - 1)
                gj = np.clip(((new_pos[:, 0] - ox) / venue.cell_m).astype(int), 0, cols - 1)
                blocked = ~occupancy[gi, gj]

                if blocked.any():
                    # try x-only move
                    test_x = np.column_stack([new_pos[blocked, 0], a_pos[blocked, 1]])
                    gi_x = np.clip(((test_x[:, 1] - oy) / venue.cell_m).astype(int), 0, rows - 1)
                    gj_x = np.clip(((test_x[:, 0] - ox) / venue.cell_m).astype(int), 0, cols - 1)
                    x_ok = occupancy[gi_x, gj_x]

                    # try y-only move
                    test_y = np.column_stack([a_pos[blocked, 0], new_pos[blocked, 1]])
                    gi_y = np.clip(((test_y[:, 1] - oy) / venue.cell_m).astype(int), 0, rows - 1)
                    gj_y = np.clip(((test_y[:, 0] - ox) / venue.cell_m).astype(int), 0, cols - 1)
                    y_ok = occupancy[gi_y, gj_y]

                    blocked_idx = np.where(blocked)[0]
                    for bi, orig_i in enumerate(blocked_idx):
                        if x_ok[bi]:
                            new_pos[orig_i] = test_x[bi]
                            new_vel[orig_i, 1] = 0.0
                        elif y_ok[bi]:
                            new_pos[orig_i] = test_y[bi]
                            new_vel[orig_i, 0] = 0.0
                        else:
                            new_pos[orig_i] = a_pos[orig_i]
                            new_vel[orig_i] *= 0.0

                a_pos = new_pos
                a_vel = new_vel

                # add small random wander impulse
                if step % 10 == 0:
                    wander = rng.normal(0, 0.15, a_vel.shape)
                    a_vel += wander

            all_pos[active_indices] = a_pos
            all_vel[active_indices] = a_vel

            # track peak instantaneous density per cell (people/m²)
            cell_area = venue.cell_m * venue.cell_m
            snap_density = np.zeros((rows, cols), dtype=np.float64)
            gi_all = np.clip(((a_pos[:, 1] - oy) / venue.cell_m).astype(int), 0, rows - 1)
            gj_all = np.clip(((a_pos[:, 0] - ox) / venue.cell_m).astype(int), 0, cols - 1)
            for ai in range(n_active):
                snap_density[gi_all[ai], gj_all[ai]] += scale
            snap_density /= cell_area
            np.maximum(density_accum, snap_density, out=density_accum)

            # --- check for agents reaching the gate (exit) ---
            for ai, idx in enumerate(active_indices):
                if all_dest_key[idx] == "gate":
                    dist_to_gate = np.linalg.norm(all_pos[idx] - gate_pos)
                    if dist_to_gate < 25.0:
                        all_active[idx] = False
                        all_exited[idx] = True

        # --- sample frame ---
        if b % sample_every_bins == 0:
            vis_mask = all_active & ~all_exited
            vis_pos = all_pos[vis_mask]
            vis_vel = all_vel[vis_mask]
            if len(vis_pos) > 0:
                lons, lats = venue.to_lonlat(vis_pos[:, 0], vis_pos[:, 1])
                agents_out = [
                    [round(float(lons[i]), 6), round(float(lats[i]), 6), round(float(vis_vel[i, 0]), 2), round(float(vis_vel[i, 1]), 2)]
                    for i in range(len(lons))
                ]
            else:
                agents_out = []

            frames.append({
                "t_min": float(t_min),
                "agents": agents_out,
                "n_active": int(vis_mask.sum()),
                "n_arrived": arrived_count,
                "n_exited": int(all_exited.sum()),
                "scale": scale,
            })

    # --- compute hotspots from peak density, with bottleneck weighting ---
    hotspots = []
    peak_density = density_accum  # already people/m², peak across all bins

    if peak_density.max() > 0:
        from scipy.ndimage import distance_transform_edt as _edt

        # wall distance in meters for exclusion + bottleneck scoring
        wall_dist_m = _edt(occupancy.astype(bool)).astype(np.float64) * venue.cell_m

        # --- exclusion masks ---
        # 1) cells within 5m of any wall (boundary artifacts)
        boundary_mask = wall_dist_m < 5.0

        # 2) cells within 60m of any stage (expected audience zones)
        # and within 30m of the gate
        destination_mask = np.zeros((rows, cols), dtype=bool)
        exclude_points = [(spos, 60.0) for spos in stage_map.values()]
        exclude_points.append((gate_pos, 30.0))
        for pos, radius_m in exclude_points:
            pr = int((pos[1] - oy) / venue.cell_m)
            pc = int((pos[0] - ox) / venue.cell_m)
            rc = int(radius_m / venue.cell_m)
            r_lo, r_hi = max(0, pr - rc), min(rows, pr + rc + 1)
            c_lo, c_hi = max(0, pc - rc), min(cols, pc + rc + 1)
            for r in range(r_lo, r_hi):
                for c in range(c_lo, c_hi):
                    if (r - pr) ** 2 + (c - pc) ** 2 <= rc * rc:
                        destination_mask[r, c] = True

        # 3) non-walkable cells
        exclude = boundary_mask | destination_mask | ~occupancy

        # --- bottleneck score: narrow corridors amplify danger ---
        # cells in 5m-wide corridor get 3x weight; 20m+ open space gets 1x
        bottleneck_weight = np.clip(3.0 - wall_dist_m / 10.0, 1.0, 3.0)

        # combined danger score = peak_density * bottleneck_weight
        danger_score = peak_density * bottleneck_weight
        danger_score[exclude] = 0.0

        # threshold: only flag cells above the red density threshold
        threshold = density_red
        hot_cells = np.argwhere(danger_score > threshold)

        if len(hot_cells) > 0:
            hot_cells = sorted(hot_cells, key=lambda rc: -danger_score[rc[0], rc[1]])

            # cluster nearby hotspots (within 30m) into single points
            cluster_radius_cells = int(30.0 / venue.cell_m)
            clustered = []
            used = set()
            for rc in hot_cells:
                key = (rc[0], rc[1])
                if key in used:
                    continue
                cluster_r = [rc[0]]
                cluster_c = [rc[1]]
                cluster_d = [danger_score[rc[0], rc[1]]]
                cluster_raw = [peak_density[rc[0], rc[1]]]
                used.add(key)
                for rc2 in hot_cells:
                    key2 = (rc2[0], rc2[1])
                    if key2 in used:
                        continue
                    if abs(rc2[0] - rc[0]) <= cluster_radius_cells and abs(rc2[1] - rc[1]) <= cluster_radius_cells:
                        dist_cells = np.sqrt((rc2[0] - rc[0]) ** 2 + (rc2[1] - rc[1]) ** 2)
                        if dist_cells <= cluster_radius_cells:
                            cluster_r.append(rc2[0])
                            cluster_c.append(rc2[1])
                            cluster_d.append(danger_score[rc2[0], rc2[1]])
                            cluster_raw.append(peak_density[rc2[0], rc2[1]])
                            used.add(key2)

                weights = np.array(cluster_d)
                avg_r = np.average(cluster_r, weights=weights)
                avg_c = np.average(cluster_c, weights=weights)
                peak_score = max(cluster_d)
                peak_raw_density = max(cluster_raw)
                clustered.append((avg_r, avg_c, peak_score, peak_raw_density))

                if len(clustered) >= 8:
                    break

            # iteratively merge centroids until none are close together
            min_sep_cells = int(100.0 / venue.cell_m)
            while True:
                merged = []
                merged_used = set()
                for i, (r1, c1, s1, d1) in enumerate(clustered):
                    if i in merged_used:
                        continue
                    mr, mc, ms, md = [r1], [c1], s1, d1
                    merged_used.add(i)
                    for j, (r2, c2, s2, d2) in enumerate(clustered):
                        if j in merged_used:
                            continue
                        if np.sqrt((r1 - r2) ** 2 + (c1 - c2) ** 2) < min_sep_cells:
                            mr.append(r2)
                            mc.append(c2)
                            ms = max(ms, s2)
                            md = max(md, d2)
                            merged_used.add(j)
                    merged.append((np.mean(mr), np.mean(mc), ms, md))
                if len(merged) == len(clustered):
                    break
                clustered = merged
            clustered = merged

            for avg_r, avg_c, peak_score, peak_raw in clustered:
                cx = ox + (avg_c + 0.5) * venue.cell_m
                cy = oy + (avg_r + 0.5) * venue.cell_m
                lon, lat = venue.to_lonlat(cx, cy)
                display_density = peak_raw * 0.56
                hotspots.append({
                    "lon": float(lon),
                    "lat": float(lat),
                    "peak_density": round(float(display_density), 1),
                    "danger_score": round(float(peak_score), 1),
                    "peak_pressure": round(float(display_density * 0.3), 2),
                })

    return {"frames": frames, "hotspots": hotspots}


def run_festival_serializable(
    geojson: dict,
    meta: dict,
    setlist: list[dict],
    draw: dict[str, float],
    tickets_sold: int,
    n_agents: int = 1500,
    extra_obstacles: list[list[list[float]]] | None = None,
    density_red: float = 6.0,
    affinity: dict[str, dict[str, float]] | None = None,
    seed: int = 42,
) -> dict:
    """Dask-safe wrapper: reconstructs VenueGrid from serializable inputs."""
    venue = load_venue_from_geojson(geojson, meta)
    return run_festival(
        venue=venue,
        setlist=setlist,
        draw=draw,
        tickets_sold=tickets_sold,
        n_agents=n_agents,
        extra_obstacles=extra_obstacles,
        density_red=density_red,
        affinity=affinity,
        seed=seed,
    )
