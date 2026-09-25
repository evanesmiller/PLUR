"""Compare a venue's obstacle polygons with OpenStreetMap footprints.

Scale and placement errors in hand-traced venue maps change corridor widths,
which matter more to crush risk than any simulation parameter. This fetches
OSM ways by name inside the venue's bounding box and reports, per matching
obstacle, the area ratio, centroid offset and overlap (IoU) in metres.

    python -m scripts.check_venue_osm hard_summer_2025 "SoFi Stadium"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon, shape
from shapely.ops import transform

ROOT = Path(__file__).resolve().parent.parent
OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)


def fetch_osm_ways(name: str, bbox: tuple[float, float, float, float]) -> list[dict]:
    min_lon, min_lat, max_lon, max_lat = bbox
    query = (
        f'[out:json][timeout:50];way["name"="{name}"]'
        f"({min_lat},{min_lon},{max_lat},{max_lon});out geom;"
    )
    last_error: Exception | None = None
    for attempt, url in enumerate(OVERPASS_MIRRORS * 2):
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode({"data": query}).encode(),
            headers={
                "User-Agent": "PLUR-venue-check/0.1",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=80) as resp:
                elements = json.load(resp)["elements"]
            return [e for e in elements if len(e.get("geometry", [])) > 3]
        except (urllib.error.URLError, TimeoutError) as exc:  # busy public servers
            last_error = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"All Overpass mirrors failed: {last_error}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("venue_id")
    ap.add_argument("name", help="feature name, identical in the venue file and OSM")
    args = ap.parse_args()

    base = ROOT / "backend" / "data" / "venues" / args.venue_id
    meta = json.loads((base / "meta.json").read_text())
    geojson = json.loads((base / "venue.geojson").read_text())
    to_utm = Transformer.from_crs(
        "EPSG:4326", f"EPSG:{meta.get('utm_epsg', 32611)}", always_xy=True
    ).transform

    ours = [f for f in geojson["features"] if f["properties"].get("name") == args.name]
    if not ours:
        sys.exit(f"No feature named {args.name!r} in {args.venue_id}")
    bbox = shape(ours[0]["geometry"]).buffer(0.01).bounds
    ways = fetch_osm_ways(args.name, bbox)
    if not ways:
        sys.exit(f"No OSM way named {args.name!r} near the venue")

    for w in ways:
        ref = transform(to_utm, Polygon([(p["lon"], p["lat"]) for p in w["geometry"]]))
        keep = ("leisure", "building", "building:part", "amenity", "landuse")
        tags = {k: v for k, v in w.get("tags", {}).items() if k in keep}
        print(f"OSM way {w['id']} {tags}: {ref.area:,.0f} m²")
        for f in ours:
            g = transform(to_utm, shape(f["geometry"]))
            iou = g.intersection(ref).area / g.union(ref).area
            print(
                f"  venue {f['properties'].get('type')}/{f['properties'].get('subtype')}: "
                f"{g.area:,.0f} m² ({g.area / ref.area:.2f}x OSM), "
                f"centroid offset {g.centroid.distance(ref.centroid):.0f} m, "
                f"IoU {iou:.2f}, largest boundary gap {g.hausdorff_distance(ref):.0f} m"
            )


if __name__ == "__main__":
    main()
