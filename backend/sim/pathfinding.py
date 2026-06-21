from __future__ import annotations

import heapq

import numpy as np
from numba import njit
from scipy.ndimage import distance_transform_edt


def precompute_distance_field(
    occupancy: np.ndarray,
    target_rc: tuple[int, int],
    cell_m: float,
    wall_cost_field: np.ndarray | None = None,
) -> np.ndarray:
    """Dijkstra distance field from target cell. When wall_cost_field is
    provided, cells near walls are more expensive to traverse, pushing
    paths toward corridor centers."""
    rows, cols = occupancy.shape
    dist = np.full((rows, cols), np.inf, dtype=np.float64)
    tr, tc = target_rc
    if not (0 <= tr < rows and 0 <= tc < cols and occupancy[tr, tc]):
        return dist

    dist[tr, tc] = 0.0
    heap = [(0.0, tr, tc)]
    SQRT2 = 1.4142135623730951

    while heap:
        d, r, c = heapq.heappop(heap)
        if d > dist[r, c]:
            continue
        for dr, dc in (
            (-1, 0), (1, 0), (0, -1), (0, 1),
            (-1, -1), (-1, 1), (1, -1), (1, 1),
        ):
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and occupancy[nr, nc]:
                base_step = SQRT2 if (dr != 0 and dc != 0) else 1.0
                if wall_cost_field is not None:
                    cost = base_step * cell_m * wall_cost_field[nr, nc]
                else:
                    cost = base_step * cell_m
                nd = d + cost
                if nd < dist[nr, nc]:
                    dist[nr, nc] = nd
                    heapq.heappush(heap, (nd, nr, nc))
    return dist


def compute_wall_cost_field(occupancy: np.ndarray, cell_m: float) -> np.ndarray:
    """Cells near walls are expensive; cells in corridor centers are cheap.
    Returns a multiplier >=1.0 per cell."""
    wall_dist_cells = distance_transform_edt(occupancy.astype(bool))
    wall_dist_m = wall_dist_cells * cell_m
    # at 1m from wall: cost ~5x; at 5m: ~1.7x; at 15m+: ~1.0x
    cost = 1.0 + 4.0 / (wall_dist_m + 1.0)
    return cost.astype(np.float64)


def compute_flow_field(dist_field: np.ndarray, cell_m: float) -> np.ndarray:
    """From a distance field, compute a (rows, cols, 2) unit-vector flow field
    pointing downhill (toward the target). Zero vector at unreachable cells."""
    rows, cols = dist_field.shape
    flow = np.zeros((rows, cols, 2), dtype=np.float64)
    for r in range(rows):
        for c in range(cols):
            if np.isinf(dist_field[r, c]):
                continue
            best_d = dist_field[r, c]
            best_dx, best_dy = 0.0, 0.0
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1),
                           (-1, -1), (-1, 1), (1, -1), (1, 1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    nd = dist_field[nr, nc]
                    if nd < best_d:
                        best_d = nd
                        best_dx = float(dc) * cell_m
                        best_dy = float(dr) * cell_m
            mag = np.sqrt(best_dx ** 2 + best_dy ** 2)
            if mag > 1e-9:
                flow[r, c, 0] = best_dx / mag
                flow[r, c, 1] = best_dy / mag
    return flow


@njit(cache=True)
def sample_flow(
    flow_field: np.ndarray,
    x: float, y: float,
    origin_x: float, origin_y: float,
    cell_m: float, rows: int, cols: int,
) -> tuple[float, float]:
    """Look up the flow direction for a world-space position."""
    gi = int((y - origin_y) / cell_m)
    gj = int((x - origin_x) / cell_m)
    if gi < 0 or gi >= rows or gj < 0 or gj >= cols:
        return 0.0, 0.0
    return flow_field[gi, gj, 0], flow_field[gi, gj, 1]


class FlowFieldCache:
    """Precomputes and caches flow fields for each destination (stages + gate).
    Paths prefer corridor centers over wall-hugging."""

    def __init__(self, occupancy: np.ndarray, cell_m: float, origin_m: tuple[float, float]):
        self.occupancy = occupancy.astype(bool)
        self.cell_m = cell_m
        self.origin_m = origin_m
        self.rows, self.cols = occupancy.shape
        self._cache: dict[str, np.ndarray] = {}
        self._wall_cost = compute_wall_cost_field(occupancy, cell_m)

    def pos_to_rc(self, x: float, y: float) -> tuple[int, int]:
        c = int((x - self.origin_m[0]) / self.cell_m)
        r = int((y - self.origin_m[1]) / self.cell_m)
        r = max(0, min(self.rows - 1, r))
        c = max(0, min(self.cols - 1, c))
        if not self.occupancy[r, c]:
            best_r, best_c, best_d = r, c, 1e9
            for dr in range(-5, 6):
                for dc in range(-5, 6):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < self.rows and 0 <= nc < self.cols and self.occupancy[nr, nc]:
                        d = dr * dr + dc * dc
                        if d < best_d:
                            best_r, best_c, best_d = nr, nc, d
            r, c = best_r, best_c
        return r, c

    def get_flow(self, key: str, target_xy: tuple[float, float]) -> np.ndarray:
        if key not in self._cache:
            tr, tc = self.pos_to_rc(target_xy[0], target_xy[1])
            dist = precompute_distance_field(
                self.occupancy, (tr, tc), self.cell_m, self._wall_cost
            )
            self._cache[key] = compute_flow_field(dist, self.cell_m)
        return self._cache[key]

    def invalidate(self):
        self._cache.clear()
