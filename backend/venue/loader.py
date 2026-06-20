from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import shape

_DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class VenueGrid:
    occupancy: np.ndarray          # (rows, cols) bool  True=walkable
    origin_m: tuple[float, float]  # UTM SW-corner (easting, northing)
    cell_m: float
    grid_shape: tuple[int, int]    # (rows, cols)
    stages: list[dict]
    gates: list[dict]
    facilities: list[dict]
    to_lonlat: Callable
    to_utm: Callable
    meta: dict
    bbox_lonlat: tuple             # (min_lon, min_lat, max_lon, max_lat)
    geojson: dict                  # raw FeatureCollection for frontend


def load_venue(
    venue_id: str,
    data_dir: Path | None = None,
    cell_m: float = 2.0,
) -> VenueGrid:
    base = (data_dir or _DATA_DIR) / "venues" / venue_id
    meta = json.loads((base / "meta.json").read_text())
    geojson = json.loads((base / "venue.geojson").read_text())

    epsg = meta["utm_epsg"]
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform
    to_lonlat = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True).transform

    walkable_polys_ll: list = []
    obstacle_polys_ll: list = []
    stages: list[dict] = []
    gates: list[dict] = []
    facilities: list[dict] = []

    for feat in geojson["features"]:
        props = feat.get("properties", {})
        geom = feat["geometry"]
        ftype = props.get("type", "")
        if ftype == "walkable":
            walkable_polys_ll.append(shape(geom))
        elif ftype in ("obstacle", "vip_area"):
            obstacle_polys_ll.append(shape(geom))
        elif ftype == "stage":
            lon, lat = geom["coordinates"]
            x_m, y_m = to_utm(lon, lat)
            stages.append({
                "id": props.get("id", props.get("stage_id", "")),
                "name": props.get("name", ""),
                "pos_m": [float(x_m), float(y_m)],
                "lonlat": [lon, lat],
            })
        elif ftype == "gate":
            lon, lat = geom["coordinates"]
            x_m, y_m = to_utm(lon, lat)
            gates.append({
                "id": props.get("id", props.get("gate_id", "")),
                "name": props.get("name", ""),
                "pos_m": [float(x_m), float(y_m)],
                "lonlat": [lon, lat],
            })
        elif ftype == "facility":
            lon, lat = geom["coordinates"]
            x_m, y_m = to_utm(lon, lat)
            facilities.append({
                "id": props.get("id", props.get("facility_id", "")),
                "name": props.get("name", ""),
                "facility_type": props.get("facility_type", ""),
                "pos_m": [float(x_m), float(y_m)],
                "lonlat": [lon, lat],
            })

    if not walkable_polys_ll:
        raise ValueError(f"No walkable polygon found in {venue_id}")

    # union walkable polys, subtract obstacles — all in lon/lat for now
    walkable_ll = walkable_polys_ll[0]
    for p in walkable_polys_ll[1:]:
        walkable_ll = walkable_ll.union(p)
    for obs in obstacle_polys_ll:
        walkable_ll = walkable_ll.difference(obs)

    # bbox in lon/lat
    minx_ll, miny_ll, maxx_ll, maxy_ll = walkable_ll.bounds
    bbox_lonlat = (minx_ll, miny_ll, maxx_ll, maxy_ll)

    # reproject walkable polygon to UTM
    def _reproject_poly(poly_ll):
        if poly_ll.geom_type == "Polygon":
            ext = [to_utm(x, y) for x, y in poly_ll.exterior.coords]
            holes = [[to_utm(x, y) for x, y in ring.coords] for ring in poly_ll.interiors]
            return shapely.geometry.Polygon(ext, holes)
        elif poly_ll.geom_type == "MultiPolygon":
            return shapely.geometry.MultiPolygon([_reproject_poly(p) for p in poly_ll.geoms])
        return poly_ll

    walkable_utm = _reproject_poly(walkable_ll)
    minx, miny, maxx, maxy = walkable_utm.bounds

    # pad by 5 cells
    pad = 5 * cell_m
    origin_x = minx - pad
    origin_y = miny - pad
    n_cols = int(np.ceil((maxx + pad - origin_x) / cell_m)) + 1
    n_rows = int(np.ceil((maxy + pad - origin_y) / cell_m)) + 1

    # rasterize using shapely 2.x vectorized contains
    col_idx = np.arange(n_cols)
    row_idx = np.arange(n_rows)
    grid_x, grid_y = np.meshgrid(
        origin_x + (col_idx + 0.5) * cell_m,
        origin_y + (row_idx + 0.5) * cell_m,
    )
    flat_x = grid_x.ravel()
    flat_y = grid_y.ravel()

    pts = shapely.points(flat_x, flat_y)
    occupancy = shapely.contains(walkable_utm, pts).reshape(n_rows, n_cols)

    def _to_lonlat_vec(x_m, y_m):
        lon, lat = to_lonlat(x_m, y_m)
        return lon, lat

    def _to_utm_vec(lon, lat):
        x, y = to_utm(lon, lat)
        return x, y

    return VenueGrid(
        occupancy=occupancy,
        origin_m=(float(origin_x), float(origin_y)),
        cell_m=cell_m,
        grid_shape=(n_rows, n_cols),
        stages=stages,
        gates=gates,
        facilities=facilities,
        to_lonlat=_to_lonlat_vec,
        to_utm=_to_utm_vec,
        meta=meta,
        bbox_lonlat=bbox_lonlat,
        geojson=geojson,
    )
