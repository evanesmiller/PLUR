import numpy as np
import pytest
from conftest import _ll, make_geojson

from backend.sim.festival import run_festival
from backend.venue.loader import load_venue_from_geojson

DRAW = {"Opener": 0.4, "Other": 0.5, "Closer": 0.9}


@pytest.fixture(scope="module")
def result(venue, setlist):
    return run_festival(venue, setlist, DRAW, tickets_sold=2000, n_agents=400)


def _xy(venue, frame):
    ll = np.array(frame["agents"])[:, :2]
    x, y = venue.to_utm(ll[:, 0], ll[:, 1])
    return np.asarray(x) - venue.origin_m[0], np.asarray(y) - venue.origin_m[1]


def test_everyone_arrives_and_leaves(result):
    last = result["frames"][-1]
    assert last["n_arrived"] == 400
    assert last["n_exited"] >= 398
    counts = [f["n_active"] + f["n_exited"] for f in result["frames"]]
    assert counts == sorted(counts)


def test_frame_contract(result):
    f = result["frames"][len(result["frames"]) // 2]
    assert set(f) >= {"t_min", "agents", "n_active", "n_arrived", "n_exited", "scale"}
    assert len(f["agents"]) == f["n_active"]
    assert all(len(a) == 4 for a in f["agents"])
    ts = [fr["t_min"] for fr in result["frames"]]
    assert ts[0] == 22 * 60 - 60 and np.all(np.diff(ts) > 0)


def test_metrics_and_hotspots_have_real_units(result):
    m = result["metrics"]
    assert m["people_per_agent"] == 5.0
    assert 0 < m["peak_density"] < 12
    assert len(m["timeline"]) > 0
    for h in result["hotspots"]:
        assert {
            "lon",
            "lat",
            "peak_density",
            "peak_pressure",
            "danger_score",
            "t_peak_min",
        } <= set(h)


def test_agents_stay_on_walkable_ground(venue, result):
    x, y = _xy(venue, result["frames"][len(result["frames"]) // 2])
    r = (y / venue.cell_m).astype(int)
    c = (x / venue.cell_m).astype(int)
    # lon/lat rounding can nudge one agent onto a boundary cell
    assert venue.occupancy[r, c].mean() > 0.99


def test_deterministic(venue, setlist, result):
    again = run_festival(venue, setlist, DRAW, tickets_sold=2000, n_agents=400)
    assert again["frames"][-5]["agents"] == result["frames"][-5]["agents"]
    assert again["hotspots"] == result["hotspots"]


def test_midnight_schedule_runs_in_order(venue):
    sl = [
        {"artist": "Late", "stage": "west", "start": "23:40", "end": "00:00"},
        {"artist": "Later", "stage": "east", "start": "00:00", "end": "00:20"},
    ]
    r = run_festival(venue, sl, {}, tickets_sold=500, n_agents=100)
    ts = [f["t_min"] for f in r["frames"]]
    assert ts[0] == 23 * 60 + 40 - 60
    assert ts[-1] <= 24 * 60 + 20 + 120


def test_barrier_closing_the_gap_keeps_crowd_east_of_the_wall():
    venue = load_venue_from_geojson(
        make_geojson(), {"utm_epsg": 32611, "grid_cell_m": 1.0}
    )
    barrier = [_ll(98, 50), _ll(106, 50), _ll(106, 70), _ll(98, 70), _ll(98, 50)]
    sl = [{"artist": "Solo", "stage": "west", "start": "22:00", "end": "22:30"}]
    r = run_festival(
        venue, sl, {}, tickets_sold=500, n_agents=100, extra_obstacles=[barrier]
    )
    # the gate is east of the wall; with the gap closed nobody can reach the west stage
    mid = max(r["frames"], key=lambda f: f["n_active"])
    x, _ = _xy(venue, mid)
    assert np.all(x > 100)


def test_unknown_stage_and_empty_inputs(venue):
    assert run_festival(venue, [], {}, 1000, n_agents=50)["frames"] == []
    bad = [{"artist": "X", "stage": "nope", "start": "20:00", "end": "21:00"}]
    r = run_festival(venue, bad, {}, 1000, n_agents=50)
    assert r["frames"] == [] and r["hotspots"] == []
