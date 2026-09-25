"""Schedule optimizer: local search over slot swaps, scored by the mean-field
crowd model in the micro-sim's units (people-minutes in red conditions)."""

from __future__ import annotations

import copy

import numpy as np

from ..sim.macro import MacroModel
from ..sim.timeline import event_minutes

# dense (orange+) exposure breaks ties when a schedule has no red at all
DENSE_WEIGHT = 0.05


def score_schedule(
    setlist: list[dict],
    draw: dict[str, float],
    affinity: dict[str, dict[str, float]],
    tickets_sold: int,
    macro: MacroModel,
) -> tuple[float, dict]:
    r = macro.run(setlist, draw, affinity, tickets_sold, summary_only=True)
    return r["red_person_min"] + DENSE_WEIGHT * r["dense_person_min"], r


def _swap_slots(setlist: list[dict], i: int, j: int) -> list[dict]:
    new_sl = copy.deepcopy(setlist)
    for key in ("stage", "start", "end"):
        new_sl[i][key], new_sl[j][key] = new_sl[j][key], new_sl[i][key]
    return new_sl


def _place_headliners(
    setlist: list[dict], headliners: set[str]
) -> tuple[list[dict], list[str]]:
    """Move each unlocked headliner into the final slot of its stage, swapping with
    the act there unless that act is locked or also a headliner. Returns warnings."""
    sl = copy.deepcopy(setlist)
    warnings = []
    for i, e in enumerate(sl):
        # a locked slot is where the user wants the act, headliner or not
        if e["artist"] not in headliners or e.get("locked"):
            continue
        same_stage = [k for k, o in enumerate(sl) if o["stage"] == e["stage"]]
        last = max(
            same_stage, key=lambda k: event_minutes(sl[k]["start"], sl[k]["end"])[0]
        )
        if last == i:
            continue
        other = sl[last]
        if other.get("locked") or other["artist"] in headliners:
            warnings.append(
                f"{e['artist']} is a headliner but the last slot on {e['stage']} "
                f"is held by {other['artist']}"
            )
            continue
        sl = _swap_slots(sl, i, last)
    return sl, warnings


class ScheduleOptimizer:
    def optimize(
        self,
        setlist: list[dict],
        draw: dict[str, float],
        affinity: dict[str, dict[str, float]],
        headliners: list[str],
        tickets_sold: int,
        macro: MacroModel,
        n_iterations: int = 150,
        pairs_per_iter: int = 20,
        seed: int = 42,
    ) -> dict:
        headliner_set = set(headliners)
        risk_before, detail_before = score_schedule(
            setlist, draw, affinity, tickets_sold, macro
        )
        current, warnings = _place_headliners(setlist, headliner_set)
        best_score, detail = score_schedule(
            current, draw, affinity, tickets_sold, macro
        )
        best = current

        # locked slots and headliners never move; auto-filled acts are proposed
        # three times as often as ones the user placed by hand
        swappable = [
            i
            for i, e in enumerate(current)
            if not e.get("locked", False) and e["artist"] not in headliner_set
        ]
        if len(swappable) >= 2:
            weights = np.array(
                [3.0 if not current[i].get("manual", True) else 1.0 for i in swappable]
            )
            weights /= weights.sum()
            rng = np.random.default_rng(seed)
            n_pairs = min(pairs_per_iter, len(swappable) * (len(swappable) - 1) // 2)
            for _ in range(n_iterations):
                improved = False
                for _ in range(n_pairs):
                    a, b = rng.choice(len(swappable), size=2, replace=False, p=weights)
                    cand = _swap_slots(best, swappable[a], swappable[b])
                    s, d = score_schedule(cand, draw, affinity, tickets_sold, macro)
                    if s < best_score:
                        best, best_score, detail, improved = cand, s, d, True
                if (
                    not improved
                    and n_pairs >= len(swappable) * (len(swappable) - 1) // 2
                ):
                    break

        return {
            "proposed_schedule": best,
            "risk_before": float(risk_before),
            "risk_after": float(best_score),
            "red_person_min_before": detail_before["red_person_min"],
            "red_person_min_after": detail["red_person_min"],
            "changes": _compute_changes(setlist, best),
            "warnings": warnings,
            "rationale": "",
        }


def _compute_changes(original: list[dict], proposed: list[dict]) -> list[dict]:
    orig_map = {e["artist"]: e for e in original}
    changes = []
    for entry in proposed:
        a = entry["artist"]
        if a not in orig_map:
            continue
        orig = orig_map[a]
        if orig["stage"] != entry["stage"] or orig["start"] != entry["start"]:
            changes.append(
                {
                    "artist": a,
                    "from_stage": orig["stage"],
                    "from_time": orig["start"],
                    "to_stage": entry["stage"],
                    "to_time": entry["start"],
                }
            )
    return changes
