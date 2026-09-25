"""Fit the mean-field model's risk constants against agent-sim runs.

Runs the agent simulation on the bundled HARD Summer venue for the sample
schedule and shuffled variants of it, then grid-searches the three constants in
macro.py (rho_cap, c_move, rho_queue) so the mean-field per-minute count of
people in red conditions matches the agent sim. Agent runs are cached, so
re-fitting after a model change only re-runs what changed.

    python -m scripts.calibrate_macro [--agents 5000] [--variants 7] [--fresh]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from backend.demand.service import DemandService
from backend.sim.festival import run_festival
from backend.sim.macro import CALIBRATION_PATH, MacroModel, MacroVenue
from backend.venue.loader import load_venue

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "backend" / "data"
VENUE_ID = "hard_summer_2025"
RUN_CACHE = DATA / "cache" / "calibration_micro.json"
SMOOTH_MIN = 5

GRID = {
    "rho_cap": np.arange(4.5, 9.01, 0.25),
    "rho_queue": np.arange(1.0, 9.01, 0.25),
    "c_move": np.geomspace(0.1, 100.0, 31),
}


def variants(
    setlist: list[dict], n: int, seed: int = 7
) -> list[tuple[list[dict], int]]:
    """(schedule, tickets): the sample, then shuffles of its unlocked slots, with
    the last two at lower and higher attendance for spread."""
    rng = np.random.default_rng(seed)
    free = [i for i, e in enumerate(setlist) if not e.get("locked")]
    out = [(setlist, 60000)]
    for k in range(1, n):
        perm = rng.permutation(free)
        sl = [dict(e) for e in setlist]
        for i, j in zip(free, perm, strict=True):
            for key in ("stage", "start", "end"):
                sl[i][key] = setlist[j][key]
        tickets = 45000 if k == n - 2 else 75000 if k == n - 1 else 60000
        out.append((sl, tickets))
    return out


SIM_SOURCES = ("micro.py", "behavior.py", "festival.py", "crowd_model.py", "risk.py")


def _key(setlist: list[dict], tickets: int, agents: int) -> str:
    """Cache key for an agent run; changes whenever the agent simulation's code does."""
    h = hashlib.sha1(json.dumps([setlist, tickets, agents], sort_keys=True).encode())
    for name in SIM_SOURCES:
        h.update((ROOT / "backend" / "sim" / name).read_bytes())
    return h.hexdigest()


def smooth(x: np.ndarray) -> np.ndarray:
    return np.convolve(x, np.ones(SMOOTH_MIN) / SMOOTH_MIN, mode="same")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=5000)
    ap.add_argument("--variants", type=int, default=7)
    ap.add_argument("--fresh", action="store_true", help="ignore cached agent runs")
    args = ap.parse_args()

    venue = load_venue(VENUE_ID, DATA)
    setlist = json.loads(
        (DATA / "venues" / VENUE_ID / "sample_setlist.json").read_text(encoding="utf-8")
    )
    demand = DemandService(DATA / "cache").compute(setlist)
    draw, affinity = dict(demand["draw"]), demand["affinity"]
    neutral = float(np.median(list(draw.values()))) if draw else 0.5
    for a in demand["unknown"]:
        draw[a] = neutral

    cache = (
        {}
        if args.fresh or not RUN_CACHE.exists()
        else json.loads(RUN_CACHE.read_text())
    )
    runs = []
    for i, (sl, tickets) in enumerate(variants(setlist, args.variants)):
        key = _key(sl, tickets, args.agents)
        if key not in cache:
            t = time.time()
            m = run_festival(
                venue, sl, draw, tickets, n_agents=args.agents,
                affinity=affinity, density_frames=False,
            )["metrics"]  # fmt: skip
            cache[key] = {
                "timeline": [(e["t_min"], e["people_in_red"]) for e in m["timeline"]],
                "red_person_min": m["red_exposure_person_min"],
            }
            RUN_CACHE.write_text(json.dumps(cache))
            print(f"  agent run {i + 1}: {time.time() - t:.0f}s, "
                  f"{cache[key]['red_person_min']:.0f} red person-min")  # fmt: skip
        runs.append((sl, tickets, cache[key]))

    macro = MacroModel(MacroVenue.from_venue(venue))
    series, targets = [], []
    for sl, tickets, micro in runs:
        ser = macro.series(sl, draw, affinity, tickets)
        tl = dict((int(round(t)), r) for t, r in micro["timeline"])
        target = np.array([tl.get(int(t), 0.0) for t in ser["t"]])
        series.append(ser)
        targets.append(smooth(target))
    denom = sum(float((y**2).sum()) for y in targets)

    walking = [smooth(s["transit"] + s["walking_out"]) for s in series]
    ww = sum(float((w * w).sum()) for w in walking)
    best = None
    for rho_cap in GRID["rho_cap"]:
        for c_move in GRID["c_move"]:
            for rho_queue in GRID["rho_queue"]:
                cal = {
                    "rho_cap": rho_cap,
                    "c_move": c_move,
                    "rho_queue": rho_queue,
                    "c_transit": 0.0,
                }
                base = [smooth(macro.risk(s, cal)[0].sum(axis=1)) for s in series]
                # the walkway term is linear, so its least-squares weight is exact
                wy = sum(
                    float((w * (y - b)).sum())
                    for w, y, b in zip(walking, targets, base, strict=True)
                )
                cal["c_transit"] = max(0.0, wy / ww) if ww else 0.0
                err = sum(
                    float(((b + cal["c_transit"] * w - y) ** 2).sum())
                    for w, y, b in zip(walking, targets, base, strict=True)
                )
                if best is None or err < best[0]:
                    best = (err, cal)

    err, cal = best
    macro_totals = [float(macro.risk(s, cal)[0].sum()) for s in series]
    micro_totals = [r[2]["red_person_min"] for r in runs]
    rho = spearmanr(macro_totals, micro_totals).statistic if len(runs) > 2 else None
    same = [i for i, r in enumerate(runs) if r[1] == runs[0][1]]
    rho_same = (
        spearmanr(
            [macro_totals[i] for i in same], [micro_totals[i] for i in same]
        ).statistic
        if len(same) > 2
        else None
    )
    result = {
        "rho_cap": round(float(cal["rho_cap"]), 3),
        "c_move": round(float(cal["c_move"]), 4),
        "rho_queue": round(float(cal["rho_queue"]), 3),
        "c_transit": round(float(cal["c_transit"]), 4),
        "fit": {
            "relative_squared_error": round(err / denom, 4) if denom else None,
            "spearman_total_red": None if rho is None else round(float(rho), 3),
            # ranking among schedules at the same attendance: what the optimizer needs
            "spearman_same_attendance": (
                None if rho_same is None else round(float(rho_same), 3)
            ),
            "macro_red_person_min": [round(x) for x in macro_totals],
            "agent_red_person_min": [round(x) for x in micro_totals],
        },
        "runs": len(runs),
        "agents": args.agents,
        "venue": VENUE_ID,
        "fitted_on": dt.date.today().isoformat(),
    }
    CALIBRATION_PATH.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
