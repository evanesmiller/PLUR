from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import label, uniform_filter

from ..venue.loader import VenueGrid

DENSITY_GREEN = 3.0
DENSITY_YELLOW = 4.0
DENSITY_ORANGE = 6.0
PRESSURE_RED_THRESHOLD = 5.0
MAX_HOTSPOTS = 10


@dataclass
class RiskField:
    density: np.ndarray    # (rows, cols) float32, people/m²
    pressure: np.ndarray   # (rows, cols) float32
    zones: list[dict]      # [{polygon:[[lon,lat],...], level:str}]
    hotspots: list[dict]   # [{row,col,lon,lat,peak_density,peak_pressure}]
    peak_density: float
    peak_pressure: float


def density_at_frame(
    pos_m: np.ndarray,   # (N, 2)
    venue: VenueGrid,
    scale: float,
) -> np.ndarray:
    rows, cols = venue.grid_shape
    ox, oy = venue.origin_m
    cm = venue.cell_m
    gi = np.clip(((pos_m[:, 1] - oy) / cm).astype(int), 0, rows - 1)
    gj = np.clip(((pos_m[:, 0] - ox) / cm).astype(int), 0, cols - 1)
    grid = np.zeros((rows, cols), dtype=np.float32)
    np.add.at(grid, (gi, gj), 1)
    grid *= float(scale) / (cm * cm)
    return grid


def pressure_at_frame(
    pos_m: np.ndarray,   # (N, 2)
    vel_m: np.ndarray,   # (N, 2)
    venue: VenueGrid,
    scale: float,
    radius_cells: int = 2,
) -> np.ndarray:
    rows, cols = venue.grid_shape
    ox, oy = venue.origin_m
    cm = venue.cell_m
    gi = np.clip(((pos_m[:, 1] - oy) / cm).astype(int), 0, rows - 1)
    gj = np.clip(((pos_m[:, 0] - ox) / cm).astype(int), 0, cols - 1)

    count = np.zeros((rows, cols), dtype=np.float32)
    vx_sum = np.zeros((rows, cols), dtype=np.float64)
    vy_sum = np.zeros((rows, cols), dtype=np.float64)
    vx2_sum = np.zeros((rows, cols), dtype=np.float64)
    vy2_sum = np.zeros((rows, cols), dtype=np.float64)

    np.add.at(count, (gi, gj), 1)
    np.add.at(vx_sum, (gi, gj), vel_m[:, 0])
    np.add.at(vy_sum, (gi, gj), vel_m[:, 1])
    np.add.at(vx2_sum, (gi, gj), vel_m[:, 0] ** 2)
    np.add.at(vy2_sum, (gi, gj), vel_m[:, 1] ** 2)

    size = 2 * radius_cells + 1
    n_local = uniform_filter(count, size=size, mode="constant")
    vx_local_sum = uniform_filter(vx_sum, size=size, mode="constant")
    vy_local_sum = uniform_filter(vy_sum, size=size, mode="constant")
    vx2_local_sum = uniform_filter(vx2_sum, size=size, mode="constant")
    vy2_local_sum = uniform_filter(vy2_sum, size=size, mode="constant")

    eps = 1e-9
    safe_n = np.maximum(n_local, eps)
    var_x = vx2_local_sum / safe_n - (vx_local_sum / safe_n) ** 2
    var_y = vy2_local_sum / safe_n - (vy_local_sum / safe_n) ** 2
    velocity_variance = np.maximum(0.0, var_x + var_y)

    density = density_at_frame(pos_m, venue, scale)
    return (density * velocity_variance).astype(np.float32)


def compute_risk(
    frames: list[dict],
    venue: VenueGrid,
    scale: float,
) -> RiskField:
    if not frames:
        rows, cols = venue.grid_shape
        empty = np.zeros((rows, cols), dtype=np.float32)
        return RiskField(
            density=empty, pressure=empty, zones=[], hotspots=[], peak_density=0.0, peak_pressure=0.0
        )

    rows, cols = venue.grid_shape
    max_density = np.zeros((rows, cols), dtype=np.float32)
    max_pressure = np.zeros((rows, cols), dtype=np.float32)

    for frame in frames:
        d = density_at_frame(frame["pos_m"], venue, scale)
        p = pressure_at_frame(frame["pos_m"], frame["vel_m"], venue, scale)
        np.maximum(max_density, d, out=max_density)
        np.maximum(max_pressure, p, out=max_pressure)

    zones = _classify_zones(max_density, max_pressure, venue)
    hotspots = _find_hotspots(max_density, max_pressure, venue)

    return RiskField(
        density=max_density,
        pressure=max_pressure,
        zones=zones,
        hotspots=hotspots,
        peak_density=float(max_density.max()),
        peak_pressure=float(max_pressure.max()),
    )


def _cell_to_lonlat(row: int, col: int, venue: VenueGrid) -> tuple[float, float]:
    ox, oy = venue.origin_m
    cm = venue.cell_m
    x_m = ox + (col + 0.5) * cm
    y_m = oy + (row + 0.5) * cm
    lon, lat = venue.to_lonlat(x_m, y_m)
    return float(lon), float(lat)


def _classify_zones(
    density: np.ndarray,
    pressure: np.ndarray,
    venue: VenueGrid,
) -> list[dict]:
    red = (density >= DENSITY_ORANGE) | (pressure > PRESSURE_RED_THRESHOLD)
    orange = (density >= DENSITY_YELLOW) & ~red
    yellow = (density >= DENSITY_GREEN) & ~red & ~orange
    green = (density < DENSITY_GREEN) & venue.occupancy

    zones: list[dict] = []
    for mask, level in [(red, "red"), (orange, "orange"), (yellow, "yellow"), (green, "green")]:
        labeled, n_features = label(mask)
        for lbl in range(1, n_features + 1):
            cells = np.argwhere(labeled == lbl)
            if len(cells) == 0:
                continue
            r_min, c_min = cells.min(axis=0)
            r_max, c_max = cells.max(axis=0)
            # output as bounding-box polygon (simplified for performance)
            ox, oy = venue.origin_m
            cm = venue.cell_m
            corners_m = [
                (ox + c_min * cm, oy + r_min * cm),
                (ox + (c_max + 1) * cm, oy + r_min * cm),
                (ox + (c_max + 1) * cm, oy + (r_max + 1) * cm),
                (ox + c_min * cm, oy + (r_max + 1) * cm),
            ]
            poly = []
            for x, y in corners_m:
                lon, lat = venue.to_lonlat(x, y)
                poly.append([float(lon), float(lat)])
            poly.append(poly[0])
            zones.append({"polygon": poly, "level": level})

    return zones


def _find_hotspots(
    density: np.ndarray,
    pressure: np.ndarray,
    venue: VenueGrid,
) -> list[dict]:
    red_mask = (density >= DENSITY_ORANGE) | (pressure > PRESSURE_RED_THRESHOLD)
    labeled, n_features = label(red_mask)

    hotspots: list[dict] = []
    for lbl in range(1, n_features + 1):
        cells = np.argwhere(labeled == lbl)
        rows_cells = cells[:, 0]
        cols_cells = cells[:, 1]
        peak_d = float(density[rows_cells, cols_cells].max())
        peak_p = float(pressure[rows_cells, cols_cells].max())
        peak_idx = int(density[rows_cells, cols_cells].argmax())
        row, col = int(rows_cells[peak_idx]), int(cols_cells[peak_idx])
        lon, lat = _cell_to_lonlat(row, col, venue)
        hotspots.append({
            "row": row, "col": col, "lon": lon, "lat": lat,
            "peak_density": peak_d, "peak_pressure": peak_p, "cell_count": len(cells),
        })

    hotspots.sort(key=lambda h: -h["peak_density"])
    return hotspots[:MAX_HOTSPOTS]
