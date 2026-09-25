"""Coarse-grained Helbing–Molnár social-force engine.

Each agent stands for `scale` real people. Body radius and interaction range
grow with sqrt(scale) so that a packed crowd of agents has the same areal
density (people/m²) as the real crowd it represents, and force stiffnesses are
clamped so explicit integration stays stable at the chosen dt.
"""

from __future__ import annotations

from dataclasses import dataclass

import numba
import numpy as np
from scipy.ndimage import distance_transform_edt

# Real-person parameters (Helbing, Farkas & Vicsek 2000).
PERSON_RADIUS = 0.25
A_SOCIAL = 2000.0
B_SOCIAL = 0.08
K_BODY = 1.2e5
KAPPA = 2.4e5
MASS = 70.0
TAU = 0.5
MAX_SPEED = 5.0  # numerical safety cap; a stable run should almost never touch it
MAX_EXPONENT = 1.0  # caps exp() growth, and so stiffness, once bodies overlap
MAX_THREADS = 8  # measured: more threads are slower on hybrid P/E-core CPUs
STIFFNESS_SAFETY = 0.1  # per-neighbour (k/m)·dt²; ~6 packed neighbours must stay < 4
# Soft contact forces alone let long pushing queues overlap without limit, so
# agent centres are also kept at least this fraction of a body diameter apart.
# Hexagonal packing at 0.7 diameters is 4.62 / 0.7² ≈ 9.4 people/m² at any agent
# scale, close to the highest densities observed in real crowd crushes.
MIN_SPACING_FRAC = 0.7

# prm vector layout passed to the kernel
(
    P_MASS,
    P_TAU,
    P_A,
    P_B,
    P_K,
    P_KAPPA,
    P_R,
    P_AW,
    P_BW,
    P_CUTOFF,
    P_DIRECT,
    P_SLOW,
    P_ARRIVE,
    P_EXIT,
    P_MAXV,
    P_DT,
    P_DMIN,
) = range(17)


@dataclass(frozen=True)
class PhysicsParams:
    scale: float
    dt: float
    radius: float
    a_social: float
    b_social: float
    k_body: float
    kappa: float
    a_wall: float
    b_wall: float
    cutoff: float
    min_spacing: float
    # walking distance at which agents steer straight at their spot
    direct_radius: float = 12.0
    slow_radius: float = 3.0  # agents decelerate inside this distance of their spot
    arrive_radius: float = 2.5
    exit_radius: float = 8.0

    @classmethod
    def for_scale(cls, scale: float, dt: float = 0.1) -> "PhysicsParams":
        s = np.sqrt(max(scale, 1.0))
        radius = PERSON_RADIUS * s
        b = B_SOCIAL * s
        k_max = STIFFNESS_SAFETY * MASS / dt**2
        # the social term's stiffness at contact is A/B
        a = min(A_SOCIAL, k_max * b)
        k_body = min(K_BODY, k_max)
        kappa = min(KAPPA, STIFFNESS_SAFETY * MASS / (dt * radius))
        return cls(
            scale=scale,
            dt=dt,
            radius=radius,
            a_social=a,
            b_social=b,
            k_body=k_body,
            kappa=kappa,
            a_wall=a,
            b_wall=b,
            # social force is < 5% of contact strength beyond the cutoff
            cutoff=2.0 * radius + 3.0 * b,
            min_spacing=MIN_SPACING_FRAC * 2.0 * radius,
        )

    def vector(self) -> np.ndarray:
        return np.array(
            [
                MASS,
                TAU,
                self.a_social,
                self.b_social,
                self.k_body,
                self.kappa,
                self.radius,
                self.a_wall,
                self.b_wall,
                self.cutoff,
                self.direct_radius,
                self.slow_radius,
                self.arrive_radius,
                self.exit_radius,
                MAX_SPEED,
                self.dt,
                self.min_spacing,
            ],
            dtype=np.float64,
        )


def wall_fields(
    occupancy: np.ndarray, cell_m: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Distance from each cell centre to the nearest wall surface (m) and the unit gradient pointing away from it."""
    dist = distance_transform_edt(occupancy).astype(np.float64) * cell_m - 0.5 * cell_m
    dist = np.maximum(dist, 0.0)
    d_dy, d_dx = np.gradient(dist)
    mag = np.hypot(d_dx, d_dy) + 1e-12
    return dist, d_dx / mag, d_dy / mag


class HashGrid:
    """Preallocated buffers for the kernel's spatial hash: a per-cell linked list
    (head[cell] -> first agent, nxt[agent] -> next agent), rebuilt in O(agents)."""

    def __init__(
        self,
        grid_shape: tuple[int, int],
        cell_m: float,
        hash_cell: float,
        n_agents: int,
    ):
        rows, cols = grid_shape
        self.cell = float(hash_cell)
        self.rows = int(np.ceil(rows * cell_m / hash_cell)) + 1
        self.cols = int(np.ceil(cols * cell_m / hash_cell)) + 1
        self.head = np.full(self.rows * self.cols, -1, dtype=np.int64)
        self.nxt = np.full(n_agents, -1, dtype=np.int64)
        self.agent_cell = np.full(n_agents, -1, dtype=np.int64)
        self.forces = np.zeros((n_agents, 2), dtype=np.float64)


@numba.njit(cache=True, inline="always")
def _cell(x, y, ox, oy, cell, rows, cols):
    r = int((y - oy) / cell)
    c = int((x - ox) / cell)
    r = min(max(r, 0), rows - 1)
    c = min(max(c, 0), cols - 1)
    return r, c


@numba.njit(cache=True, parallel=True)
def advance(
    n_steps,
    pos,
    vel,
    status,
    target,
    flow_id,
    v0,
    heading,
    exit_on_arrival,
    arrived,
    flows,
    dists,
    wall_dist,
    wall_gx,
    wall_gy,
    occupancy,
    ox,
    oy,
    cell_m,
    h_cell,
    h_rows,
    h_cols,
    h_head,
    h_nxt,
    h_agent_cell,
    forces,
    prm,
):
    """Advance all active agents (status == 1) by n_steps. Mutates state in place.

    Agents follow their flow field until within `direct_radius` walking metres
    of their personal target, then steer straight at it and slow on approach.
    Agents with exit_on_arrival count as arrived inside exit_radius; the
    behaviour layer releases them at the gate's throughput."""
    n = pos.shape[0]
    rows, cols = occupancy.shape
    mass = prm[P_MASS]
    tau = prm[P_TAU]
    A = prm[P_A]
    B = prm[P_B]
    k_body = prm[P_K]
    kappa = prm[P_KAPPA]
    radius = prm[P_R]
    A_w = prm[P_AW]
    B_w = prm[P_BW]
    cutoff = prm[P_CUTOFF]
    direct_r = prm[P_DIRECT]
    slow_r = prm[P_SLOW]
    arrive_r = prm[P_ARRIVE]
    exit_r = prm[P_EXIT]
    max_v = prm[P_MAXV]
    dt = prm[P_DT]
    d_min = prm[P_DMIN]
    rsum = 2.0 * radius

    for _ in range(n_steps):
        # --- spatial hash (serial, O(agents): only cells used last step are cleared) ---
        for i in range(n):
            if h_agent_cell[i] >= 0:
                h_head[h_agent_cell[i]] = -1
        for i in range(n):
            if status[i] != 1:
                h_agent_cell[i] = -1
                continue
            r, c = _cell(pos[i, 0], pos[i, 1], ox, oy, h_cell, h_rows, h_cols)
            cid = r * h_cols + c
            h_agent_cell[i] = cid
            h_nxt[i] = h_head[cid]
            h_head[cid] = i

        # --- forces (parallel over agents; each writes only its own row) ---
        for i in numba.prange(n):
            if status[i] != 1:
                continue
            xi = pos[i, 0]
            yi = pos[i, 1]
            vxi = vel[i, 0]
            vyi = vel[i, 1]
            gi, gj = _cell(xi, yi, ox, oy, cell_m, rows, cols)

            # desired direction
            dx = target[i, 0] - xi
            dy = target[i, 1] - yi
            dtarget = np.sqrt(dx * dx + dy * dy)
            fid = flow_id[i]
            walk = dists[fid, gi, gj]
            if walk < direct_r or dtarget < 2.0 * slow_r or not np.isfinite(walk):
                if dtarget > 1e-6:
                    ex = dx / dtarget
                    ey = dy / dtarget
                else:
                    ex = 0.0
                    ey = 0.0
            else:
                fx0 = flows[fid, gi, gj, 0]
                fy0 = flows[fid, gi, gj, 1]
                ch = np.cos(heading[i])
                sh = np.sin(heading[i])
                ex = fx0 * ch - fy0 * sh
                ey = fx0 * sh + fy0 * ch
            speed = v0[i] * min(1.0, dtarget / slow_r)
            fx = 0.0
            fy = 0.0
            d_ahead = cutoff  # nearest agent within 45° of the walking direction

            # agent–agent
            hr, hc = _cell(xi, yi, ox, oy, h_cell, h_rows, h_cols)
            for rr in range(hr - 1, hr + 2):
                if rr < 0 or rr >= h_rows:
                    continue
                for cc in range(hc - 1, hc + 2):
                    if cc < 0 or cc >= h_cols:
                        continue
                    j = h_head[rr * h_cols + cc]
                    while j >= 0:
                        if j == i:
                            j = h_nxt[j]
                            continue
                        rx = xi - pos[j, 0]
                        ry = yi - pos[j, 1]
                        d = np.sqrt(rx * rx + ry * ry)
                        if d >= cutoff:
                            j = h_nxt[j]
                            continue
                        if -(rx * ex + ry * ey) > 0.7071 * d and d < d_ahead:
                            d_ahead = d
                        if d < 1e-9:
                            # coincident agents: deterministic split by index
                            nx = 1.0 if i > j else -1.0
                            ny = 0.0
                        else:
                            nx = rx / d
                            ny = ry / d
                        f_soc = A * np.exp(min((rsum - d) / B, MAX_EXPONENT))
                        fx += f_soc * nx
                        fy += f_soc * ny
                        overlap = rsum - d
                        if overlap > 0.0:
                            dvt = (vel[j, 0] - vxi) * (-ny) + (vel[j, 1] - vyi) * nx
                            fx += k_body * overlap * nx + kappa * overlap * dvt * (-ny)
                            fy += k_body * overlap * ny + kappa * overlap * dvt * nx
                        j = h_nxt[j]

            # people walking out queue rather than push: desired speed falls to
            # zero as the gap to the person ahead closes to shoulder contact
            if exit_on_arrival[i] and d_ahead < cutoff:
                speed *= min(max((d_ahead - rsum) / (cutoff - rsum), 0.0), 1.0)
            fx += mass * (speed * ex - vxi) / tau
            fy += mass * (speed * ey - vyi) / tau

            # walls
            dw = wall_dist[gi, gj]
            if dw < cutoff:
                f_w = A_w * np.exp(min((radius - dw) / B_w, MAX_EXPONENT))
                fx += f_w * wall_gx[gi, gj]
                fy += f_w * wall_gy[gi, gj]

            forces[i, 0] = fx
            forces[i, 1] = fy

        # --- semi-implicit Euler + wall sliding + arrival (parallel) ---
        for i in numba.prange(n):
            if status[i] != 1:
                continue
            vx = vel[i, 0] + forces[i, 0] / mass * dt
            vy = vel[i, 1] + forces[i, 1] / mass * dt
            sp = np.sqrt(vx * vx + vy * vy)
            if sp > max_v:
                vx *= max_v / sp
                vy *= max_v / sp
            x0 = pos[i, 0]
            y0 = pos[i, 1]
            x1 = x0 + vx * dt
            y1 = y0 + vy * dt
            r1, c1 = _cell(x1, y1, ox, oy, cell_m, rows, cols)
            if not occupancy[r1, c1]:
                rx_, cx_ = _cell(x1, y0, ox, oy, cell_m, rows, cols)
                ry_, cy_ = _cell(x0, y1, ox, oy, cell_m, rows, cols)
                if occupancy[rx_, cx_]:
                    y1 = y0
                    vy = 0.0
                elif occupancy[ry_, cy_]:
                    x1 = x0
                    vx = 0.0
                else:
                    x1 = x0
                    y1 = y0
                    vx = 0.0
                    vy = 0.0
            pos[i, 0] = x1
            pos[i, 1] = y1
            vel[i, 0] = vx
            vel[i, 1] = vy

            dx = target[i, 0] - x1
            dy = target[i, 1] - y1
            d2 = dx * dx + dy * dy
            if d2 < arrive_r * arrive_r or (
                exit_on_arrival[i] and d2 < exit_r * exit_r
            ):
                arrived[i] = True

        # --- minimum spacing: Jacobi projection of overlapping pairs (parallel),
        # two passes; velocity driving into an overlap is removed, as in
        # position-based dynamics, so pushing agents cannot re-compress next step
        for _pass in range(2):
            for i in numba.prange(n):
                forces[i, 0] = 0.0
                forces[i, 1] = 0.0
                if status[i] != 1:
                    continue
                xi = pos[i, 0]
                yi = pos[i, 1]
                hr, hc = _cell(xi, yi, ox, oy, h_cell, h_rows, h_cols)
                for rr in range(hr - 1, hr + 2):
                    if rr < 0 or rr >= h_rows:
                        continue
                    for cc in range(hc - 1, hc + 2):
                        if cc < 0 or cc >= h_cols:
                            continue
                        j = h_head[rr * h_cols + cc]
                        while j >= 0:
                            if j != i and status[j] == 1:
                                rx = xi - pos[j, 0]
                                ry = yi - pos[j, 1]
                                d = np.sqrt(rx * rx + ry * ry)
                                if d < 1e-9:
                                    forces[i, 0] += (
                                        0.5 * d_min * (1.0 if i > j else -1.0)
                                    )
                                elif d < d_min:
                                    push = 0.5 * (d_min - d) / d
                                    forces[i, 0] += push * rx
                                    forces[i, 1] += push * ry
                            j = h_nxt[j]
            for i in numba.prange(n):
                cx = forces[i, 0]
                cy = forces[i, 1]
                if status[i] != 1 or (cx == 0.0 and cy == 0.0):
                    continue
                x1 = pos[i, 0] + cx
                y1 = pos[i, 1] + cy
                r1, c1 = _cell(x1, y1, ox, oy, cell_m, rows, cols)
                if not occupancy[r1, c1]:
                    continue
                pos[i, 0] = x1
                pos[i, 1] = y1
                cn = np.sqrt(cx * cx + cy * cy)
                vn = (vel[i, 0] * cx + vel[i, 1] * cy) / cn
                if vn < 0.0:
                    vel[i, 0] -= vn * cx / cn
                    vel[i, 1] -= vn * cy / cn
