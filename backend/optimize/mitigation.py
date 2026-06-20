from __future__ import annotations

import math

import numpy as np

from ..venue.loader import VenueGrid


class MitigationPlanner:
    def suggest(
        self,
        risk_field,
        venue: VenueGrid,
        top_n_barriers: int = 5,
        top_n_staff: int = 10,
        n_jobs: int = 4,
    ) -> dict:
        barriers = self._suggest_barriers(risk_field, venue, top_n_barriers)
        staff = self._suggest_staff(risk_field, venue, top_n_staff)
        return {"barriers": barriers, "staff": staff, "facilities": []}

    def _suggest_barriers(
        self, risk_field, venue: VenueGrid, top_n: int
    ) -> list[dict]:
        density = risk_field.density
        pressure = risk_field.pressure

        # chokepoints: high density AND high pressure
        d_thresh = max(5.0, float(np.percentile(density[density > 0], 80)) if (density > 0).any() else 5.0)
        p_thresh = float(np.percentile(pressure[pressure > 0], 80)) if (pressure > 0).any() else 1.0

        choke = (density >= d_thresh) & (pressure >= p_thresh) & venue.occupancy
        if not choke.any():
            choke = (density >= 4.0) & venue.occupancy

        rows_idx, cols_idx = np.where(choke)
        if len(rows_idx) == 0:
            return []

        # greedy cluster centroids with 20m exclusion
        cm = venue.cell_m
        ox, oy = venue.origin_m
        scores = density[rows_idx, cols_idx] * pressure[rows_idx, cols_idx]
        order = np.argsort(-scores)
        selected_m: list[tuple[float, float]] = []
        results: list[dict] = []

        for idx in order:
            r, c = int(rows_idx[idx]), int(cols_idx[idx])
            x_m = ox + (c + 0.5) * cm
            y_m = oy + (r + 0.5) * cm
            too_close = any(
                math.hypot(x_m - sx, y_m - sy) < 20.0 for sx, sy in selected_m
            )
            if too_close:
                continue
            selected_m.append((x_m, y_m))

            # barrier segment perpendicular to dominant flow (approximate as E-W or N-S)
            # orient along N-S (perpendicular to E-W flow is default heuristic)
            half_len = 7.5  # 15m total barrier
            seg_start = (x_m, y_m - half_len)
            seg_end = (x_m, y_m + half_len)
            lon0, lat0 = venue.to_lonlat(*seg_start)
            lon1, lat1 = venue.to_lonlat(*seg_end)

            peak_d = float(density[r, c])
            # heuristic risk reduction: scales with how far over threshold we are
            risk_reduction = min(0.40, 0.10 + (peak_d - 4.0) * 0.05)

            results.append({
                "id": f"barrier_{len(results)}",
                "segment": [[float(lon0), float(lat0)], [float(lon1), float(lat1)]],
                "reason": (
                    f"Crowd density {peak_d:.1f} people/m² with elevated pressure; "
                    "barrier redirects converging flow at chokepoint"
                ),
                "risk_reduction": round(risk_reduction, 2),
            })
            if len(results) >= top_n:
                break

        return results

    def _suggest_staff(
        self, risk_field, venue: VenueGrid, top_n: int
    ) -> list[dict]:
        density = risk_field.density
        pressure = risk_field.pressure
        score_grid = density * (pressure + 0.01) * venue.occupancy.astype(float)

        rows_idx, cols_idx = np.where(score_grid > 0)
        if len(rows_idx) == 0:
            return []

        scores = score_grid[rows_idx, cols_idx]
        order = np.argsort(-scores)
        cm = venue.cell_m
        ox, oy = venue.origin_m
        selected_m: list[tuple[float, float]] = []
        results: list[dict] = []

        for idx in order:
            r, c = int(rows_idx[idx]), int(cols_idx[idx])
            x_m = ox + (c + 0.5) * cm
            y_m = oy + (r + 0.5) * cm
            too_close = any(
                math.hypot(x_m - sx, y_m - sy) < 15.0 for sx, sy in selected_m
            )
            if too_close:
                continue
            selected_m.append((x_m, y_m))
            lon, lat = venue.to_lonlat(x_m, y_m)
            peak_d = float(density[r, c])
            results.append({
                "id": f"staff_{len(results)}",
                "point": [float(lon), float(lat)],
                "reason": (
                    f"Peak density {peak_d:.1f} people/m² — crowd management required"
                ),
            })
            if len(results) >= top_n:
                break

        return results
