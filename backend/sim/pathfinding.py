from __future__ import annotations

import hashlib
from collections import OrderedDict

import numpy as np
from scipy.ndimage import distance_transform_edt
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

_SQRT2 = float(np.sqrt(2.0))
# (drow, dcol, length in cells)
_NEIGHBOURS = [
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (-1, -1, _SQRT2),
    (-1, 1, _SQRT2),
    (1, -1, _SQRT2),
    (1, 1, _SQRT2),
]

_GRAPH_CACHE: OrderedDict = OrderedDict()
_FIELD_CACHE: OrderedDict = OrderedDict()
_GRAPH_CACHE_MAX = 4
_FIELD_CACHE_MAX = 96


def occupancy_key(occupancy: np.ndarray, cell_m: float) -> str:
    h = hashlib.blake2b(np.packbits(occupancy).tobytes(), digest_size=16)
    h.update(f"{occupancy.shape}{cell_m}".encode())
    return h.hexdigest()


def wall_cost_field(occupancy: np.ndarray, cell_m: float) -> np.ndarray:
    """Traversal cost multiplier >= 1 that pushes routes toward corridor centres."""
    wall_dist_m = distance_transform_edt(occupancy) * cell_m
    return 1.0 + 4.0 / (wall_dist_m + 1.0)


def _shift(a: np.ndarray, dr: int, dc: int, fill) -> np.ndarray:
    """out[r, c] = a[r + dr, c + dc], `fill` outside the grid."""
    rows, cols = a.shape[:2]
    out = np.full_like(a, fill)
    r0, r1 = max(0, -dr), min(rows, rows - dr)
    c0, c1 = max(0, -dc), min(cols, cols - dc)
    out[r0:r1, c0:c1] = a[r0 + dr : r1 + dr, c0 + dc : c1 + dc]
    return out


def _allowed_moves(occupancy: np.ndarray) -> list[np.ndarray]:
    """Per neighbour, mask of cells whose move in that direction is legal.
    Diagonal moves may not cut the corner of a blocked cell."""
    masks = []
    for dr, dc, _ in _NEIGHBOURS:
        ok = occupancy & _shift(occupancy, dr, dc, False)
        if dr != 0 and dc != 0:
            ok &= _shift(occupancy, dr, 0, False) & _shift(occupancy, 0, dc, False)
        masks.append(ok)
    return masks


def _graph(occupancy: np.ndarray, cell_m: float, key: str):
    if key in _GRAPH_CACHE:
        _GRAPH_CACHE.move_to_end(key)
        return _GRAPH_CACHE[key]
    rows, cols = occupancy.shape
    cost = wall_cost_field(occupancy, cell_m)
    idx = np.arange(rows * cols).reshape(rows, cols)
    src, dst, w = [], [], []
    for (dr, dc, length), ok in zip(_NEIGHBOURS, _allowed_moves(occupancy)):
        r, c = np.nonzero(ok)
        src.append(idx[r, c])
        dst.append(idx[r + dr, c + dc])
        w.append(length * cell_m * 0.5 * (cost[r, c] + cost[r + dr, c + dc]))
    n = rows * cols
    graph = coo_matrix(
        (np.concatenate(w), (np.concatenate(src), np.concatenate(dst))), shape=(n, n)
    ).tocsr()
    _GRAPH_CACHE[key] = graph
    if len(_GRAPH_CACHE) > _GRAPH_CACHE_MAX:
        _GRAPH_CACHE.popitem(last=False)
    return graph


def flow_from_distance(
    dist: np.ndarray, occupancy: np.ndarray, cell_m: float
) -> np.ndarray:
    """Unit descent direction of a distance field, (rows, cols, 2) as (x, y).

    Blends every downhill neighbour weighted by its descent rate, which avoids
    the 45-degree lane artefacts of steepest-neighbour flow fields."""
    fx = np.zeros(dist.shape, dtype=np.float64)
    fy = np.zeros(dist.shape, dtype=np.float64)
    finite = np.isfinite(dist)
    for (dr, dc, length), ok in zip(_NEIGHBOURS, _allowed_moves(occupancy)):
        nb = _shift(dist, dr, dc, np.inf)
        with np.errstate(invalid="ignore"):
            rate = np.where(
                ok & finite & np.isfinite(nb), (dist - nb) / (length * cell_m), 0.0
            )
        rate = np.maximum(rate, 0.0)
        fx += rate * dc / length
        fy += rate * dr / length
    mag = np.hypot(fx, fy)
    nz = mag > 1e-12
    fx[nz] /= mag[nz]
    fy[nz] /= mag[nz]
    return np.stack([fx, fy], axis=-1).astype(np.float32)


def distance_and_flow_fields(
    occupancy: np.ndarray,
    cell_m: float,
    targets_rc: list[tuple[int, int]],
) -> tuple[np.ndarray, np.ndarray]:
    """Walking-distance fields (T, rows, cols) in metres (inf = unreachable) and
    matching flow fields (T, rows, cols, 2). Targets must be walkable cells."""
    occupancy = occupancy.astype(bool)
    rows, cols = occupancy.shape
    key = occupancy_key(occupancy, cell_m)
    dists = np.empty((len(targets_rc), rows, cols), dtype=np.float32)
    flows = np.empty((len(targets_rc), rows, cols, 2), dtype=np.float32)

    missing = [t for t in dict.fromkeys(targets_rc) if (key, t) not in _FIELD_CACHE]
    if missing:
        graph = _graph(occupancy, cell_m, key)
        sources = [r * cols + c for r, c in missing]
        d_all = dijkstra(graph, directed=True, indices=sources)
        for t, d in zip(missing, d_all):
            d = d.reshape(rows, cols)
            _FIELD_CACHE[(key, t)] = (
                d.astype(np.float32),
                flow_from_distance(d, occupancy, cell_m),
            )
            if len(_FIELD_CACHE) > _FIELD_CACHE_MAX:
                _FIELD_CACHE.popitem(last=False)

    for i, t in enumerate(targets_rc):
        _FIELD_CACHE.move_to_end((key, t))
        dists[i], flows[i] = _FIELD_CACHE[(key, t)]
    return dists, flows


class WalkableSnapper:
    """Maps world positions to the centre of the nearest walkable cell."""

    def __init__(
        self, occupancy: np.ndarray, origin_m: tuple[float, float], cell_m: float
    ):
        self.occupancy = occupancy.astype(bool)
        self.ox, self.oy = origin_m
        self.cell_m = cell_m
        self.rows, self.cols = occupancy.shape
        _, (self._near_r, self._near_c) = distance_transform_edt(
            ~self.occupancy, return_indices=True
        )

    def cell_of(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xy = np.atleast_2d(xy)
        r = np.clip(
            ((xy[:, 1] - self.oy) / self.cell_m).astype(np.int64), 0, self.rows - 1
        )
        c = np.clip(
            ((xy[:, 0] - self.ox) / self.cell_m).astype(np.int64), 0, self.cols - 1
        )
        return r, c

    def snap_rc(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        r, c = self.cell_of(xy)
        return self._near_r[r, c], self._near_c[r, c]

    def center(self, r: np.ndarray, c: np.ndarray) -> np.ndarray:
        return np.column_stack(
            [
                self.ox + (c + 0.5) * self.cell_m,
                self.oy + (r + 0.5) * self.cell_m,
            ]
        )

    def snap(self, xy: np.ndarray) -> np.ndarray:
        """Leave walkable positions untouched; move blocked ones to the nearest walkable cell centre."""
        xy = np.array(np.atleast_2d(xy), dtype=np.float64)
        r, c = self.cell_of(xy)
        blocked = ~self.occupancy[r, c]
        if blocked.any():
            xy[blocked] = self.center(
                self._near_r[r[blocked], c[blocked]],
                self._near_c[r[blocked], c[blocked]],
            )
        return xy
