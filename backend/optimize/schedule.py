from __future__ import annotations

import copy
import random

import numpy as np

from ..sim.macro import MacroModel


def _score_schedule(
    setlist: list[dict],
    draw: dict[str, float],
    affinity: dict[str, dict[str, float]],
    stages: list[dict],
    tickets_sold: int,
    max_capacity: int,
    macro: MacroModel,
) -> float:
    result = macro.run(
        setlist=setlist,
        draw=draw,
        affinity=affinity,
        stages=stages,
        tickets_sold=tickets_sold,
        max_capacity=max_capacity,
    )
    stage_pop = result["stage_pop"]
    safe_caps = result["stage_safe_capacity"]
    total = 0.0
    for sid, pops in stage_pop.items():
        cap = safe_caps.get(sid, max_capacity / max(len(stage_pop), 1))
        for entry in pops:
            excess = max(0.0, entry["pop"] / cap - 1.0)
            total += excess ** 2
    return total


def _swap_slots(setlist: list[dict], i: int, j: int) -> list[dict]:
    new_sl = copy.deepcopy(setlist)
    new_sl[i]["stage"], new_sl[j]["stage"] = new_sl[j]["stage"], new_sl[i]["stage"]
    new_sl[i]["start"], new_sl[j]["start"] = new_sl[j]["start"], new_sl[i]["start"]
    new_sl[i]["end"], new_sl[j]["end"] = new_sl[j]["end"], new_sl[i]["end"]
    return new_sl


class ScheduleOptimizer:
    def optimize(
        self,
        setlist: list[dict],
        draw: dict[str, float],
        affinity: dict[str, dict[str, float]],
        stages: list[dict],
        headliners: list[str],
        tickets_sold: int,
        max_capacity: int,
        macro_model: MacroModel | None = None,
        n_iterations: int = 200,
        dask_client=None,
    ) -> dict:
        macro = macro_model or MacroModel()
        headliner_set = set(headliners)

        current = copy.deepcopy(setlist)
        risk_before = _score_schedule(
            current, draw, affinity, stages, tickets_sold, max_capacity, macro
        )
        best = copy.deepcopy(current)
        best_score = risk_before

        swappable = [
            i for i, e in enumerate(current)
            if e["artist"] not in headliner_set
        ]

        if len(swappable) < 2:
            return {
                "proposed_schedule": current,
                "risk_before": risk_before,
                "risk_after": risk_before,
                "changes": [],
                "rationale": "",
            }

        rng = random.Random(42)
        pairs_per_iter = min(20, len(swappable) * (len(swappable) - 1) // 2)

        for _ in range(n_iterations):
            candidates = []
            for _ in range(pairs_per_iter):
                i, j = rng.sample(swappable, 2)
                candidates.append((i, j))

            candidate_setlists = [
                _swap_slots(best, i, j) for i, j in candidates
            ]

            if dask_client is not None:
                futures = [
                    dask_client.submit(
                        _score_schedule, sl,
                        draw, affinity, stages, tickets_sold, max_capacity, macro
                    )
                    for sl in candidate_setlists
                ]
                scores = dask_client.gather(futures)
            else:
                scores = [
                    _score_schedule(
                        sl, draw, affinity, stages, tickets_sold, max_capacity, macro
                    )
                    for sl in candidate_setlists
                ]

            min_idx = int(np.argmin(scores))
            if scores[min_idx] < best_score:
                best_score = scores[min_idx]
                best = candidate_setlists[min_idx]

        changes = _compute_changes(setlist, best)

        return {
            "proposed_schedule": best,
            "risk_before": float(risk_before),
            "risk_after": float(best_score),
            "changes": changes,
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
            changes.append({
                "artist": a,
                "from_stage": orig["stage"],
                "from_time": orig["start"],
                "to_stage": entry["stage"],
                "to_time": entry["start"],
            })
    return changes
