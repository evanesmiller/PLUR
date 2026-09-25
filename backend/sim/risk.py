"""Crowd risk fields: density (people/m²) and crowd pressure P = ρ·Var(v) (1/s²).

Density is a Gaussian kernel estimate normalised by the walkable fraction of
the kernel ("normalised convolution"), so it neither leaks into walls nor
under-reads next to them. A cell is red when ρ ≥ density_red, or when
ρ ≥ density_orange and P ≥ PRESSURE_CRITICAL (onset of crowd turbulence,
Helbing, Johansson & Al-Abideen 2007).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numba
import numpy as np
from scipy.ndimage import binary_dilation, gaussian_filter, label

DENSITY_GREEN = 3.0
DENSITY_ORANGE = 4.0
DENSITY_RED = 6.0
PRESSURE_CRITICAL = 0.02
KERNEL_SIGMA_M = 2.0
MIN_LOCAL_AGENTS = (
    3.0  # below this many agents under the kernel, velocity variance is noise
)
HOTSPOT_MERGE_M = 15.0
MAX_HOTSPOTS = 10


@numba.njit(cache=True)
def _splat(r, c, vx, vy, w1d, out):
    """Gaussian-splat agent count, Σv and Σ|v|² onto the grid (same result as
    binning then gaussian_filter with mode="constant", at a fraction of the cost)."""
    rows, cols = out.shape[1], out.shape[2]
    R = w1d.shape[0] // 2
    for i in range(r.shape[0]):
        v2 = vx[i] * vx[i] + vy[i] * vy[i]
        for a in range(-R, R + 1):
            rr = r[i] + a
            if rr < 0 or rr >= rows:
                continue
            wa = w1d[a + R]
            for b in range(-R, R + 1):
                cc = c[i] + b
                if cc < 0 or cc >= cols:
                    continue
                w = wa * w1d[b + R]
                out[0, rr, cc] += w
                out[1, rr, cc] += w * vx[i]
                out[2, rr, cc] += w * vy[i]
                out[3, rr, cc] += w * v2


@dataclass
class RiskField:
    density: np.ndarray  # (rows, cols) peak ρ over the run, people/m²
    pressure: np.ndarray  # (rows, cols) peak P over the run, 1/s²
    t_peak: np.ndarray  # (rows, cols) event minute of peak ρ
    exposure: np.ndarray  # (rows, cols) person-minutes spent in red conditions
    hotspots: list[dict]
    peak_density: float
    peak_pressure: float
    red_exposure_person_min: float
    timeline: list[dict] = field(default_factory=list)


class RiskAccumulator:
    def __init__(
        self,
        occupancy: np.ndarray,
        origin_m: tuple[float, float],
        cell_m: float,
        density_red: float = DENSITY_RED,
        density_orange: float = DENSITY_ORANGE,
        pressure_critical: float = PRESSURE_CRITICAL,
        sigma_m: float = KERNEL_SIGMA_M,
    ):
        self.occupancy = occupancy.astype(bool)
        self.ox, self.oy = origin_m
        self.cell_m = cell_m
        self.rows, self.cols = occupancy.shape
        self.density_red = density_red
        self.density_orange = density_orange
        self.pressure_critical = pressure_critical
        self.sigma_cells = sigma_m / cell_m
        # mean agents per cell below which velocity statistics are unreliable
        self._min_mass = MIN_LOCAL_AGENTS / (2.0 * np.pi * self.sigma_cells**2)
        radius = int(3.0 * self.sigma_cells + 0.5)
        k = np.arange(-radius, radius + 1)
        w1d = np.exp(-0.5 * (k / self.sigma_cells) ** 2)
        self._w1d = w1d / w1d.sum()
        self._buf = np.zeros((4, self.rows, self.cols))
        walk = self._smooth(self.occupancy.astype(np.float64))
        self._walk_norm = np.where(self.occupancy, np.maximum(walk, 1e-6), np.inf)

        shape = occupancy.shape
        self.peak_density = np.zeros(shape)
        self.peak_pressure = np.zeros(shape)
        self.t_peak = np.zeros(shape)
        self.exposure = np.zeros(shape)
        self.timeline: list[dict] = []

    def _smooth(self, a: np.ndarray) -> np.ndarray:
        return gaussian_filter(a, self.sigma_cells, mode="constant", truncate=3.0)

    def fields(
        self, pos: np.ndarray, vel: np.ndarray, scale: float
    ) -> tuple[np.ndarray, np.ndarray]:
        """Instantaneous (density, pressure) grids for one snapshot."""
        shape = (self.rows, self.cols)
        if len(pos) == 0:
            return np.zeros(shape), np.zeros(shape)
        r = np.clip(
            ((pos[:, 1] - self.oy) / self.cell_m).astype(np.int64), 0, self.rows - 1
        )
        c = np.clip(
            ((pos[:, 0] - self.ox) / self.cell_m).astype(np.int64), 0, self.cols - 1
        )
        buf = self._buf
        buf[:] = 0.0
        _splat(
            r,
            c,
            np.ascontiguousarray(vel[:, 0]),
            np.ascontiguousarray(vel[:, 1]),
            self._w1d,
            buf,
        )
        mass = buf[0]
        density = mass * scale / (self.cell_m**2) / self._walk_norm

        valid = mass > self._min_mass
        safe = np.where(valid, mass, 1.0)
        mvx = buf[1] / safe
        mvy = buf[2] / safe
        var = np.maximum(buf[3] / safe - mvx**2 - mvy**2, 0.0)
        pressure = np.where(valid, density * var, 0.0)
        return density, pressure

    def red_mask(self, density: np.ndarray, pressure: np.ndarray) -> np.ndarray:
        return (density >= self.density_red) | (
            (density >= self.density_orange) & (pressure >= self.pressure_critical)
        )

    def add(
        self,
        pos: np.ndarray,
        vel: np.ndarray,
        scale: float,
        t_min: float,
        dt_min: float,
    ) -> None:
        density, pressure = self.fields(pos, vel, scale)
        higher = density > self.peak_density
        self.peak_density[higher] = density[higher]
        self.t_peak[higher] = t_min
        np.maximum(self.peak_pressure, pressure, out=self.peak_pressure)
        red = self.red_mask(density, pressure)
        people_in_red = density * red * self.cell_m**2
        self.exposure += people_in_red * dt_min
        self.timeline.append(
            {
                "t_min": float(t_min),
                "max_density": round(float(density.max()), 2),
                "max_pressure": round(float(pressure.max()), 4),
                "people_in_red": round(float(people_in_red.sum()), 1),
            }
        )

    def result(self, to_lonlat: Callable) -> RiskField:
        return RiskField(
            density=self.peak_density,
            pressure=self.peak_pressure,
            t_peak=self.t_peak,
            exposure=self.exposure,
            hotspots=self._hotspots(to_lonlat),
            peak_density=float(self.peak_density.max()),
            peak_pressure=float(self.peak_pressure.max()),
            red_exposure_person_min=float(self.exposure.sum()),
            timeline=self.timeline,
        )

    def _hotspots(self, to_lonlat: Callable) -> list[dict]:
        red = self.red_mask(self.peak_density, self.peak_pressure) & self.occupancy
        if not red.any():
            return []
        # label on a dilated mask so red patches a few metres apart form one hotspot
        merge_iter = max(1, int(round(HOTSPOT_MERGE_M / 2 / self.cell_m)))
        labels, n = label(binary_dilation(red, iterations=merge_iter))
        labels = np.where(red, labels, 0)

        hotspots = []
        for lbl in range(1, n + 1):
            rr, cc = np.nonzero(labels == lbl)
            if len(rr) == 0:
                continue
            k = int(np.argmax(self.peak_density[rr, cc]))
            r, c = rr[k], cc[k]
            lon, lat = to_lonlat(
                self.ox + (c + 0.5) * self.cell_m, self.oy + (r + 0.5) * self.cell_m
            )
            exposure = float(self.exposure[rr, cc].sum())
            hotspots.append(
                {
                    "lon": float(lon),
                    "lat": float(lat),
                    "peak_density": round(float(self.peak_density[r, c]), 2),
                    "peak_pressure": round(float(self.peak_pressure[rr, cc].max()), 4),
                    "t_peak_min": float(self.t_peak[r, c]),
                    "area_m2": round(len(rr) * self.cell_m**2, 1),
                    "exposure_person_min": round(exposure, 1),
                    # kept for API compatibility: ranking score = red exposure
                    "danger_score": round(exposure, 1),
                }
            )
        hotspots.sort(key=lambda h: (-h["exposure_person_min"], -h["peak_density"]))
        return hotspots[:MAX_HOTSPOTS]
