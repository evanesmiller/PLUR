from __future__ import annotations

from dataclasses import dataclass

import numba
import numpy as np
from scipy.ndimage import distance_transform_edt

from ..venue.loader import VenueGrid

V0_MEAN = 1.3
V0_STD = 0.3
TAU = 0.5
A_REP = 2000.0
B_REP = 0.08
A_WALL = 2000.0
B_WALL = 0.08
RADIUS = 0.25
MASS = 70.0
K_BODY = 1.2e5
KAPPA = 2.4e5
MAX_SPEED = 5.0
DT = 0.1
HASH_CELL = 2.0  # spatial hash cell size in meters


@dataclass
class AgentState:
    pos: np.ndarray   # (N, 2) float64, meters
    vel: np.ndarray   # (N, 2) float64, m/s
    dest: np.ndarray  # (N, 2) float64, meters
    v0: np.ndarray    # (N,) float64
    scale: float       # real_headcount / N


@numba.njit(cache=True)
def _force_kernel(
    pos, vel, dest, v0,
    wall_dist, wall_gx, wall_gy,
    grid_origin_x, grid_origin_y, grid_cell_m, grid_rows, grid_cols,
    sorted_agents, cell_offsets,
    hash_origin_x, hash_origin_y, hash_cell_m, hash_rows, hash_cols,
    mass, tau, A, B, A_w, B_w, k_body, kappa, radius,
):
    N = pos.shape[0]
    forces = np.zeros_like(pos)

    for i in range(N):
        xi = pos[i, 0]
        yi = pos[i, 1]
        vxi = vel[i, 0]
        vyi = vel[i, 1]

        # driving force toward destination
        ddx = dest[i, 0] - xi
        ddy = dest[i, 1] - yi
        dist_dest = np.sqrt(ddx * ddx + ddy * ddy) + 1e-9
        ex = ddx / dist_dest
        ey = ddy / dist_dest
        fx = mass * (v0[i] * ex - vxi) / tau
        fy = mass * (v0[i] * ey - vyi) / tau

        # agent–agent repulsion via spatial hash
        hash_col_i = int((xi - hash_origin_x) / hash_cell_m)
        hash_row_i = int((yi - hash_origin_y) / hash_cell_m)
        for drow in range(-2, 3):
            for dcol in range(-2, 3):
                nr = hash_row_i + drow
                nc = hash_col_i + dcol
                if nr < 0 or nr >= hash_rows or nc < 0 or nc >= hash_cols:
                    continue
                cell_id = nr * hash_cols + nc
                for k_idx in range(cell_offsets[cell_id], cell_offsets[cell_id + 1]):
                    j = sorted_agents[k_idx]
                    if j == i:
                        continue
                    rxij = xi - pos[j, 0]
                    ryij = yi - pos[j, 1]
                    dij = np.sqrt(rxij * rxij + ryij * ryij) + 1e-9
                    nxij = rxij / dij
                    nyij = ryij / dij
                    rsum = 2.0 * radius
                    # Helbing social repulsion: A * exp((r_sum - d) / B)
                    social_f = A * np.exp((rsum - dij) / B)
                    fx += social_f * nxij
                    fy += social_f * nyij
                    # granular contact (body compression + sliding friction)
                    overlap = rsum - dij
                    if overlap > 0.0:
                        delta_vt = (
                            (vel[j, 0] - vxi) * (-nyij)
                            + (vel[j, 1] - vyi) * nxij
                        )
                        fx += k_body * overlap * nxij - kappa * overlap * delta_vt * (-nyij)
                        fy += k_body * overlap * nyij - kappa * overlap * delta_vt * nxij

        # wall repulsion from precomputed distance field
        gi = int((yi - grid_origin_y) / grid_cell_m)
        gj = int((xi - grid_origin_x) / grid_cell_m)
        gi = max(0, min(grid_rows - 1, gi))
        gj = max(0, min(grid_cols - 1, gj))
        dw = wall_dist[gi, gj]
        if dw < 3.0:
            wall_f = A_w * np.exp(-dw / B_w)
            fx += wall_f * wall_gx[gi, gj]
            fy += wall_f * wall_gy[gi, gj]

        forces[i, 0] = fx
        forces[i, 1] = fy

    return forces


def _build_spatial_hash(
    pos: np.ndarray,
    hash_cell_m: float,
    origin_x: float,
    origin_y: float,
    n_rows: int,
    n_cols: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Build CSR spatial hash: (sorted_agents, cell_offsets)."""
    hash_col = np.clip(
        ((pos[:, 0] - origin_x) / hash_cell_m).astype(np.int32), 0, n_cols - 1
    )
    hash_row = np.clip(
        ((pos[:, 1] - origin_y) / hash_cell_m).astype(np.int32), 0, n_rows - 1
    )
    cell_ids = hash_row * n_cols + hash_col
    sorted_idx = np.argsort(cell_ids, kind="stable").astype(np.int32)
    sorted_ids = cell_ids[sorted_idx]
    n_cells = n_rows * n_cols
    offsets = np.zeros(n_cells + 1, dtype=np.int32)
    for cid in sorted_ids:
        offsets[cid + 1] += 1
    np.cumsum(offsets, out=offsets)
    return sorted_idx, offsets


def _precompute_walls(
    occupancy: np.ndarray, cell_m: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Precompute wall distance field (meters) and gradient."""
    dist_m = distance_transform_edt(occupancy).astype(np.float64) * cell_m
    # np.gradient returns [d/d_row, d/d_col]; row↔y, col↔x
    d_dy, d_dx = np.gradient(dist_m)
    mag = np.sqrt(d_dx ** 2 + d_dy ** 2) + 1e-9
    return dist_m, (d_dx / mag).astype(np.float64), (d_dy / mag).astype(np.float64)


class MicroSim:
    def __init__(self, venue: VenueGrid):
        self.venue = venue
        self._wall_dist, self._wall_gx, self._wall_gy = _precompute_walls(
            venue.occupancy.astype(bool), venue.cell_m
        )
        rows, cols = venue.grid_shape
        ox, oy = venue.origin_m
        self._hash_cols = int(np.ceil(cols * venue.cell_m / HASH_CELL)) + 2
        self._hash_rows = int(np.ceil(rows * venue.cell_m / HASH_CELL)) + 2

    def init_agents(
        self,
        n_agents: int,
        stage_populations: dict[str, float],
        real_headcount: int,
        rng: np.random.Generator | None = None,
    ) -> AgentState:
        rng = rng or np.random.default_rng(0)
        stage_map = {s["id"]: np.array(s["pos_m"]) for s in self.venue.stages}
        total_pop = sum(stage_populations.values()) or 1.0

        pos_list: list[np.ndarray] = []
        dest_list: list[np.ndarray] = []
        v0_list: list[np.ndarray] = []

        for sid, pop in stage_populations.items():
            if sid not in stage_map:
                continue
            n_here = max(1, int(round(n_agents * pop / total_pop)))
            sp = stage_map[sid]
            angles = rng.uniform(0, 2 * np.pi, n_here)
            radii_spawn = rng.uniform(2.0, 35.0, n_here)
            p = sp + np.column_stack([np.cos(angles), np.sin(angles)]) * radii_spawn[:, None]
            pos_list.append(p)
            dest_list.append(np.tile(sp, (n_here, 1)))
            v0_list.append(rng.normal(V0_MEAN, V0_STD, n_here).clip(0.3, 3.0))

        if not pos_list:
            # fallback: scatter agents at venue center
            cx = self.venue.origin_m[0] + self.venue.grid_shape[1] * self.venue.cell_m / 2
            cy = self.venue.origin_m[1] + self.venue.grid_shape[0] * self.venue.cell_m / 2
            p = np.column_stack([
                rng.uniform(cx - 50, cx + 50, n_agents),
                rng.uniform(cy - 50, cy + 50, n_agents),
            ])
            pos_list.append(p)
            dest_list.append(np.tile([cx, cy], (n_agents, 1)))
            v0_list.append(np.full(n_agents, V0_MEAN))

        pos = np.vstack(pos_list)[:n_agents].astype(np.float64)
        dest = np.vstack(dest_list)[:n_agents].astype(np.float64)
        v0 = np.concatenate(v0_list)[:n_agents].astype(np.float64)
        n = len(pos)
        vel = rng.normal(0.0, 0.1, (n, 2)).astype(np.float64)
        return AgentState(pos=pos, vel=vel, dest=dest, v0=v0, scale=real_headcount / max(n, 1))

    def step(self, state: AgentState, dt: float = DT) -> AgentState:
        v = self.venue
        ox, oy = v.origin_m
        rows, cols = v.grid_shape
        sorted_agents, cell_offsets = _build_spatial_hash(
            state.pos, HASH_CELL, ox, oy, self._hash_rows, self._hash_cols
        )
        forces = _force_kernel(
            state.pos, state.vel, state.dest, state.v0,
            self._wall_dist, self._wall_gx, self._wall_gy,
            float(ox), float(oy), float(v.cell_m), rows, cols,
            sorted_agents, cell_offsets,
            float(ox), float(oy), float(HASH_CELL), self._hash_rows, self._hash_cols,
            MASS, TAU, A_REP, B_REP, A_WALL, B_WALL, K_BODY, KAPPA, RADIUS,
        )
        new_vel = state.vel + (forces / MASS) * dt
        speed = np.linalg.norm(new_vel, axis=1, keepdims=True)
        mask = speed > MAX_SPEED
        new_vel = np.where(mask, new_vel / speed * MAX_SPEED, new_vel)
        new_pos = state.pos + new_vel * dt

        # bounce agents off non-walkable cells
        gi = np.clip(((new_pos[:, 1] - oy) / v.cell_m).astype(int), 0, rows - 1)
        gj = np.clip(((new_pos[:, 0] - ox) / v.cell_m).astype(int), 0, cols - 1)
        walkable = v.occupancy[gi, gj]
        new_pos = np.where(walkable[:, None], new_pos, state.pos)
        new_vel = np.where(walkable[:, None], new_vel, state.vel * -0.3)

        return AgentState(
            pos=new_pos, vel=new_vel, dest=state.dest,
            v0=state.v0, scale=state.scale,
        )

    def run_window(
        self,
        stage_populations: dict[str, float],
        real_headcount: int,
        duration_s: float,
        n_agents: int = 8000,
        dt: float = DT,
        sample_every: int = 5,
    ) -> list[dict]:
        state = self.init_agents(n_agents, stage_populations, real_headcount)
        frames: list[dict] = []
        n_steps = max(1, int(duration_s / dt))
        for step_i in range(n_steps):
            state = self.step(state, dt)
            if step_i % sample_every == 0:
                frames.append({
                    "t": float(step_i * dt),
                    "pos_m": state.pos.copy(),
                    "vel_m": state.vel.copy(),
                    "scale": state.scale,
                })
        return frames
