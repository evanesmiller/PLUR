import pytest
from conftest import make_geojson

from backend.optimize.schedule import ScheduleOptimizer, _place_headliners
from backend.sim.macro import MacroModel, MacroVenue
from backend.venue.loader import load_venue_from_geojson

SETLIST = [
    {"artist": "Big", "stage": "east", "start": "20:00", "end": "21:00"},
    {"artist": "Mid", "stage": "west", "start": "20:00", "end": "21:00"},
    {"artist": "Small", "stage": "east", "start": "21:00", "end": "22:00"},
    {
        "artist": "Tiny",
        "stage": "west",
        "start": "21:00",
        "end": "22:00",
        "locked": True,
    },
]
DRAW = {"Big": 0.95, "Mid": 0.5, "Small": 0.2, "Tiny": 0.1}


@pytest.fixture(scope="module")
def macro():
    venue = load_venue_from_geojson(
        make_geojson(), {"utm_epsg": 32611, "grid_cell_m": 1.0}
    )
    return MacroModel(MacroVenue.from_venue(venue))


def test_headliner_moves_to_the_final_slot_of_its_stage():
    sl, warnings = _place_headliners(SETLIST, {"Big"})
    big = next(e for e in sl if e["artist"] == "Big")
    assert (big["stage"], big["start"]) == ("east", "21:00")
    assert not warnings


def test_headliner_blocked_by_a_locked_act_is_reported():
    _, warnings = _place_headliners(SETLIST, {"Mid"})
    assert warnings and "Tiny" in warnings[0]


def test_optimizer_never_worsens_and_respects_locks(macro):
    r = ScheduleOptimizer().optimize(
        SETLIST,
        DRAW,
        {},
        headliners=[],
        tickets_sold=4000,
        macro=macro,
        n_iterations=20,
    )
    assert r["risk_after"] <= r["risk_before"]
    tiny = next(e for e in r["proposed_schedule"] if e["artist"] == "Tiny")
    assert (tiny["stage"], tiny["start"]) == ("west", "21:00")
    assert r["red_person_min_after"] >= 0


def test_locked_headliner_stays_where_the_user_put_it():
    sl = [dict(e) for e in SETLIST]
    sl[1]["locked"] = True  # Mid, 20:00 on west
    placed, warnings = _place_headliners(sl, {"Mid"})
    mid = next(e for e in placed if e["artist"] == "Mid")
    assert (mid["stage"], mid["start"]) == ("west", "20:00") and not warnings
