import numpy as np
import pytest
from conftest import make_geojson

from backend.sim.macro import MacroModel, MacroVenue, _people_above
from backend.venue.loader import load_venue_from_geojson

CAL = {"rho_cap": 6.5, "c_move": 5.0, "rho_queue": 6.5}
SETLIST = [
    {"artist": "A", "stage": "west", "start": "22:00", "end": "22:20"},
    {"artist": "B", "stage": "east", "start": "22:00", "end": "22:20"},
    {"artist": "C", "stage": "east", "start": "22:20", "end": "22:40"},
]
DRAW = {"A": 0.3, "B": 0.4, "C": 0.9}


@pytest.fixture(scope="module")
def macro_venue():
    venue = load_venue_from_geojson(
        make_geojson(), {"utm_epsg": 32611, "grid_cell_m": 1.0}
    )
    venue.gates[0]["capacity_pph"] = 3000
    return MacroVenue.from_venue(venue)


def test_water_fill_matches_brute_force():
    rng = np.random.default_rng(0)
    for _ in range(200):
        k = int(rng.integers(1, 50))
        q = np.sort(rng.random(k))[::-1]
        q /= q.sum()
        qc = np.concatenate([[0.0], np.cumsum(q)])
        cap = rng.uniform(1, 20)
        pop = rng.uniform(0, k * cap * 0.999)
        thr = rng.uniform(0, cap * 1.1)
        lo, hi = 0.0, 1e9
        for _ in range(200):
            lam = (lo + hi) / 2
            if np.minimum(lam * q, cap).sum() < pop:
                lo = lam
            else:
                hi = lam
        cells = np.minimum(hi * q, cap)
        expected = cells[cells >= thr - 1e-9].sum()
        assert abs(_people_above(pop, q, qc, cap, thr) - expected) < 1e-4 * max(1, pop)


def test_everyone_arrives_and_leaves_through_the_gate(macro_venue):
    ser = MacroModel(macro_venue, CAL).series(SETLIST, DRAW, {}, 3000)
    assert ser["released"].sum() == pytest.approx(3000, rel=1e-3)
    assert ser["released"].max() <= 3000 / 60 + 1e-6  # never faster than the gate
    assert ser["queue"].max() > 100  # 3000 people through 50/min must queue


def test_crowd_follows_the_programme(macro_venue):
    m = MacroModel(macro_venue, CAL)
    ser = m.series(SETLIST, DRAW, {}, 3000)
    t = ser["t"]
    east = m.venue.stage_ids.index("east")
    during_c = (t >= 22 * 60 + 30) & (t < 22 * 60 + 40)
    share = ser["pop"][during_c, east].sum() / ser["pop"][during_c].sum()
    assert share > 0.95  # C is the only set still playing


def test_risk_grows_with_attendance(macro_venue):
    m = MacroModel(macro_venue, CAL)
    lo = m.run(SETLIST, DRAW, {}, 1000, summary_only=True)["red_person_min"]
    hi = m.run(SETLIST, DRAW, {}, 3000, summary_only=True)["red_person_min"]
    assert hi > lo


def test_run_reports_windows_with_clock_times(macro_venue):
    r = MacroModel(macro_venue, CAL).run(SETLIST, DRAW, {}, 3000)
    assert r["risk_windows"], "3000 people leaving through a 50/min gate must flag"
    w = r["risk_windows"][0]
    assert {"stage", "t_start_min", "t_end_min", "score", "red_person_min"} <= set(w)
    assert r["red_person_min"] == pytest.approx(
        sum(e["people_in_red"] for e in r["red_timeline"])
    )
