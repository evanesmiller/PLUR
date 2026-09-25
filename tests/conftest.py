from __future__ import annotations

import numpy as np
import pytest
from pyproj import Transformer

from backend.venue.loader import load_venue_from_geojson

# Synthetic test venue near Hollywood Park: a 200 m x 120 m field split by a
# wall with a 10 m gap, two stages facing each other, one gate, two amenities.
_TO_LL = Transformer.from_crs("EPSG:32611", "EPSG:4326", always_xy=True).transform
_X0, _Y0 = 376000.0, 3757000.0


def _ll(x: float, y: float) -> list[float]:
    lon, lat = _TO_LL(_X0 + x, _Y0 + y)
    return [lon, lat]


def _rect(x0, y0, x1, y1) -> list[list[float]]:
    return [_ll(x0, y0), _ll(x1, y0), _ll(x1, y1), _ll(x0, y1), _ll(x0, y0)]


def _feature(ftype: str, geom: dict, **props) -> dict:
    return {"type": "Feature", "properties": {"type": ftype, **props}, "geometry": geom}


def _point(x, y) -> dict:
    return {"type": "Point", "coordinates": _ll(x, y)}


def make_geojson(gap_m: float = 10.0) -> dict:
    features = [
        _feature(
            "walkable", {"type": "Polygon", "coordinates": [_rect(0, 0, 200, 120)]}
        ),
        # dividing wall at x=100..104 with a gap centred on y=60
        _feature(
            "obstacle",
            {"type": "Polygon", "coordinates": [_rect(100, 0, 104, 60 - gap_m / 2)]},
        ),
        _feature(
            "obstacle",
            {"type": "Polygon", "coordinates": [_rect(100, 60 + gap_m / 2, 104, 120)]},
        ),
        _feature(
            "stage",
            _point(10, 60),
            stage_id="west",
            name="West",
            orientation=90,
            capacity_area_m2=2500,
        ),
        _feature(
            "stage",
            _point(190, 60),
            stage_id="east",
            name="East",
            orientation=270,
            capacity_area_m2=2500,
        ),
        _feature("gate", _point(150, 3), gate_id="gate", name="Gate"),
        _feature(
            "facility",
            _point(60, 110),
            facility_id="wc",
            facility_type="restroom",
            name="WC",
        ),
        _feature(
            "facility",
            _point(150, 110),
            facility_id="bar",
            facility_type="bar",
            name="Bar",
        ),
    ]
    return {"type": "FeatureCollection", "features": features}


@pytest.fixture(scope="session")
def venue():
    return load_venue_from_geojson(
        make_geojson(), {"utm_epsg": 32611, "grid_cell_m": 1.0}, "test"
    )


@pytest.fixture(scope="session")
def setlist():
    return [
        {"artist": "Opener", "stage": "west", "start": "22:00", "end": "22:20"},
        {"artist": "Other", "stage": "east", "start": "22:00", "end": "22:20"},
        {"artist": "Closer", "stage": "east", "start": "22:20", "end": "22:40"},
    ]


@pytest.fixture
def rng():
    return np.random.default_rng(0)
