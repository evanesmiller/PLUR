from __future__ import annotations

from datetime import datetime

import numpy as np


def _parse_time(s: str) -> int:
    """Parse 'HH:MM' → minutes from midnight."""
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _softmax(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    e = np.exp(x - x.max())
    return e / e.sum()


class MacroModel:
    def run(
        self,
        setlist: list[dict],
        draw: dict[str, float],
        affinity: dict[str, dict[str, float]],
        stages: list[dict],
        tickets_sold: int,
        max_capacity: int,
        arrival_steepness: float = 1.0,
        bin_minutes: int = 5,
    ) -> dict:
        if not setlist:
            return {
                "stage_pop": {},
                "attendance": [],
                "risk_windows": [],
                "stage_safe_capacity": {},
            }

        # --- parse set times ---
        parsed = []
        for e in setlist:
            parsed.append({
                "artist": e["artist"],
                "stage": e["stage"],
                "start_min": _parse_time(e["start"]),
                "end_min": _parse_time(e["end"]),
            })

        event_start = min(p["start_min"] for p in parsed)
        event_end = max(p["end_min"] for p in parsed)
        n_bins = int(np.ceil((event_end - event_start) / bin_minutes)) + 1
        t_bins = np.arange(n_bins) * bin_minutes  # minutes from event start

        stage_ids = list({p["stage"] for p in parsed})
        stage_id_map = {sid: i for i, sid in enumerate(stage_ids)}
        n_stages = len(stage_ids)

        # stage distances in meters for distance_decay
        stage_pos: dict[str, np.ndarray] = {}
        for st in stages:
            stage_pos[st["id"]] = np.array(st["pos_m"])

        def _stage_dist(s1: str, s2: str) -> float:
            if s1 not in stage_pos or s2 not in stage_pos:
                return 500.0
            return float(np.linalg.norm(stage_pos[s1] - stage_pos[s2]))

        # --- arrival CDF ---
        # inflow_rate(t) ∝ Σ draw_i * gaussian(t - set_start_i, σ=30min)
        sigma = 30.0 / bin_minutes  # in bins
        inflow = np.zeros(n_bins)
        for p in parsed:
            draw_i = draw.get(p["artist"], 0.5)
            center = (p["start_min"] - event_start) / bin_minutes
            for b in range(n_bins):
                inflow[b] += draw_i * np.exp(-0.5 * ((b - center) / sigma) ** 2)
        inflow = inflow ** arrival_steepness
        inflow_sum = inflow.sum()
        arrival_cdf = np.cumsum(inflow) / (inflow_sum + 1e-9)
        arrival_cdf = np.clip(arrival_cdf, 0.0, 1.0)
        attendance = tickets_sold * arrival_cdf  # people present at each bin

        # --- safe capacity per stage ---
        stage_area_m2 = 6000.0  # 200m × 30m crowd zone per stage
        safe_density = 4.0  # people/m²
        safe_cap_each = stage_area_m2 * safe_density
        safe_cap_fallback = max_capacity / max(n_stages, 1) * 0.7
        stage_safe_cap: dict[str, float] = {
            sid: min(safe_cap_each, safe_cap_fallback) for sid in stage_ids
        }

        # --- per-bin stage populations ---
        stage_pop_arr = np.zeros((n_stages, n_bins))

        for b in range(n_bins):
            t_abs = event_start + t_bins[b]
            concurrent = [
                p for p in parsed
                if p["start_min"] <= t_abs < p["end_min"]
            ]
            if not concurrent:
                continue

            draws = np.array([draw.get(p["artist"], 0.5) for p in concurrent])

            # 2B: affinity crowd-bleed — high-affinity pairs on nearby stages
            # pull fans from each other, softening the winner-takes-all softmax.
            # Build a bleed matrix: bleed[i][j] = fraction of stage i's draw-share
            # that also considers stage j attractive.
            n_conc = len(concurrent)
            bleed = np.zeros((n_conc, n_conc))
            for i, pi in enumerate(concurrent):
                for j, pj in enumerate(concurrent):
                    if i == j:
                        continue
                    aff = affinity.get(pi["artist"], {}).get(pj["artist"], 0.0)
                    dist = _stage_dist(pi["stage"], pj["stage"])
                    # only bleed if affinity is meaningful and stages are within 400m
                    if aff > 0.1 and dist < 400.0:
                        proximity = np.exp(-dist / 200.0)
                        bleed[i, j] = aff * proximity * 0.15  # max 15% bleed

            # Adjusted effective draw: each act loses a share proportional to bleed
            # toward high-affinity neighbours, and gains from neighbours bleeding to it
            effective_draws = draws.copy()
            for i in range(n_conc):
                loss = bleed[i].sum()          # what stage i leaks to others
                gain = bleed[:, i].sum()       # what flows into stage i
                effective_draws[i] = max(0.0, draws[i] - loss + gain)

            shares = _softmax(effective_draws * 3.0)

            base_pop = attendance[b] * shares

            # 2A: affinity-weighted egress migration — when a set ends, fans flow
            # to the next act weighted 60% by draw and 40% by affinity to the
            # act they just watched.
            migration = np.zeros(n_conc)
            just_ended = [
                p for p in parsed
                if 0 < t_abs - p["end_min"] <= bin_minutes * 2
            ]
            for ended in just_ended:
                # estimate crowd that was at the ended set as a share of prior bin
                ended_draw = draw.get(ended["artist"], 0.2)
                ended_pop = attendance[b] * ended_draw * 0.12  # ~12% of total in transit

                # compute destination weights: 60% draw affinity, 40% artist affinity
                dest_weights = np.zeros(n_conc)
                for ci, cp in enumerate(concurrent):
                    aff = affinity.get(ended["artist"], {}).get(cp["artist"], 0.0)
                    dist = _stage_dist(ended["stage"], cp["stage"])
                    proximity = np.exp(-dist / 300.0)
                    draw_score = draws[ci]
                    dest_weights[ci] = (0.6 * draw_score + 0.4 * aff) * proximity

                w_sum = dest_weights.sum()
                if w_sum > 0:
                    migration += ended_pop * dest_weights / w_sum

            total = base_pop + migration
            total_sum = total.sum()
            if total_sum > 0:
                total = total / total_sum * attendance[b]

            for ci, cp in enumerate(concurrent):
                sidx = stage_id_map[cp["stage"]]
                stage_pop_arr[sidx, b] += total[ci]

        # --- risk windows ---
        risk_score = np.zeros((n_stages, n_bins))
        for si, sid in enumerate(stage_ids):
            cap = stage_safe_cap[sid]
            risk_score[si] = np.maximum(0.0, stage_pop_arr[si] / cap - 1.0)

        risk_windows: list[dict] = []
        THRESHOLD = 0.2  # 20% over safe capacity
        MERGE_GAP = 3  # bins

        for si, sid in enumerate(stage_ids):
            flagged = np.where(risk_score[si] > THRESHOLD)[0]
            if len(flagged) == 0:
                continue
            # merge consecutive bins
            groups: list[list[int]] = []
            cur = [flagged[0]]
            for b in flagged[1:]:
                if b - cur[-1] <= MERGE_GAP:
                    cur.append(b)
                else:
                    groups.append(cur)
                    cur = [b]
            groups.append(cur)
            for grp in groups:
                risk_windows.append({
                    "t_start": int(t_bins[grp[0]]),
                    "t_end": int(t_bins[grp[-1]] + bin_minutes),
                    "stage": sid,
                    "score": float(risk_score[si, grp].max()),
                })

        risk_windows.sort(key=lambda w: -w["score"])

        stage_pop_out: dict[str, list[dict]] = {}
        for si, sid in enumerate(stage_ids):
            stage_pop_out[sid] = [
                {"t": int(t_bins[b]), "pop": float(stage_pop_arr[si, b])}
                for b in range(n_bins)
            ]

        attendance_out = [
            {"t": int(t_bins[b]), "count": float(attendance[b])}
            for b in range(n_bins)
        ]

        return {
            "stage_pop": stage_pop_out,
            "attendance": attendance_out,
            "risk_windows": risk_windows,
            "stage_safe_capacity": stage_safe_cap,
        }
