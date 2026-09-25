"""Mean-field counterpart of the agent simulation.

Tracks expected headcounts watching / walking to each set, holding, walking to
the exit and queueing at the gates, minute by minute, using the same behaviour
parameters as the agents (crowd_model.py). Crowd risk is estimated in the
micro-sim's units (people in red conditions, person-minutes) from each stage's
audience profile, with two constants fitted against micro runs
(scripts/calibrate_macro.py -> macro_calibration.json).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numba
import numpy as np

from ..venue.loader import VenueGrid
from .crowd_model import (
    AFFINITY_WEIGHT,
    BAR_ELIGIBLE_P,
    BAR_VISIT_P,
    CHURN_PER_HOUR,
    DRAW_TEMPERATURE,
    DRAW_WEIGHT,
    EARLY_LEAVE_FRAC,
    EARLY_LEAVE_WINDOW_MIN,
    EGRESS_MAX_MIN,
    EGRESS_MEAN_MIN,
    GATES_OPEN_BEFORE_MIN,
    SET_LEAVE_MEAN_MIN,
    TRANSIT_AMENITY_P,
    UPCOMING_LOOKAHEAD_MIN,
    WALK_SPEED,
    AMENITY_DWELL_MIN,
    arrival_fraction,
)
from .risk import DENSITY_ORANGE, DENSITY_RED
from .timeline import parse_setlist

CALIBRATION_PATH = Path(__file__).with_name("macro_calibration.json")
DEFAULT_CALIBRATION = {
    "rho_cap": 6.0,
    "c_move": 5.0,
    "rho_queue": 5.0,
    "c_transit": 0.0,
}
RISK_WINDOW_MIN_PEOPLE = 50.0  # minutes with fewer people in red are not flagged
RISK_WINDOW_MERGE_MIN = 10


def load_calibration() -> dict:
    try:
        return {**DEFAULT_CALIBRATION, **json.loads(CALIBRATION_PATH.read_text())}
    except (OSError, ValueError):
        return dict(DEFAULT_CALIBRATION)


@dataclass
class MacroVenue:
    """Geometry the mean-field model needs, derived from the same layout as the agents."""

    stage_ids: list[str]
    profiles: list[np.ndarray]  # per stage: audience share per cell, descending
    profile_cums: list[np.ndarray]  # per stage: exclusive cumulative sums of profiles
    cell_area: float
    stage_walk_min: np.ndarray  # (S, S) walking minutes between stages
    gate_walk_min: np.ndarray  # (S,) walking minutes from the nearest gate
    gate_capacity_ppm: float  # total, inf = unlimited

    @classmethod
    def from_venue(cls, venue: VenueGrid) -> "MacroVenue":
        from .festival import _build_layout

        stage_ids = sorted(s["id"] for s in venue.stages)
        layout, _ = _build_layout(venue, venue.occupancy, stage_ids, [])
        g = layout.n_gates
        r, c = layout.snapper.cell_of(layout.stage_pts)
        s_ids = np.arange(len(stage_ids))
        stage_walk = layout.dists[g + s_ids][:, r, c] / WALK_SPEED / 60.0
        gate_walk = layout.dists[:g][:, r, c].min(axis=0) / WALK_SPEED / 60.0
        profiles = []
        for _, cum in layout.stage_spots:
            q = np.diff(np.concatenate([[0.0], cum]))
            profiles.append(np.sort(q)[::-1])
        return cls(
            stage_ids=stage_ids,
            profiles=profiles,
            profile_cums=[np.concatenate([[0.0], np.cumsum(q)]) for q in profiles],
            cell_area=venue.cell_m**2,
            stage_walk_min=np.nan_to_num(stage_walk, posinf=30.0),
            gate_walk_min=np.nan_to_num(gate_walk, posinf=30.0),
            gate_capacity_ppm=float(layout.gate_capacity_ppm.sum()),
        )


@numba.njit(cache=True)
def _mean_field(
    t0, n_steps, tickets, music_end,
    set_start, set_end, set_stage, set_draw, set_aff,
    arrive_cum, transit_min, gate_walk, gate_cap,
    temp, w_draw, w_aff, churn_rate, leave_mean, egress_mean,
    early_frac, early_window, lookahead,
):  # fmt: skip
    """Expected headcounts per minute. Returns (watch[t, set], transit[t, set],
    inflow[t, set], outflow[t, set], walking_out[t], gate_queue[t], released[t])."""
    n_sets = set_start.shape[0]
    watch = np.zeros((n_steps, n_sets))
    transit = np.zeros((n_steps, n_sets))
    inflow = np.zeros((n_steps, n_sets))
    outflow = np.zeros((n_steps, n_sets))
    walking_out = np.zeros(n_steps)
    queue = np.zeros(n_steps)
    released = np.zeros(n_steps)

    W = np.zeros(n_sets)
    T = np.zeros(n_sets)
    hold = 0.0
    L = 0.0
    Q = 0.0
    entry_q = 0.0
    p = np.zeros(n_sets)
    p_leave_set = 1.0 - np.exp(-1.0 / leave_mean)
    p_egress = 1.0 - np.exp(-1.0 / egress_mean)
    p_early = 1.0 - (1.0 - early_frac) ** (1.0 / early_window)
    p_churn = churn_rate / 60.0

    for k in range(n_steps):
        t = t0 + k
        # candidate sets: live now, else the next ones within the lookahead
        n_live = 0
        for i in range(n_sets):
            if set_start[i] <= t and t < set_end[i]:
                n_live += 1
        next_start = 1e18
        if n_live == 0:
            for i in range(n_sets):
                if set_start[i] > t and set_start[i] <= t + lookahead:
                    next_start = min(next_start, set_start[i])

        def_live = np.zeros(n_sets, dtype=np.bool_)
        for i in range(n_sets):
            if n_live > 0:
                def_live[i] = set_start[i] <= t and t < set_end[i]
            else:
                def_live[i] = set_start[i] == next_start
        any_live = def_live.any()

        # base choice probabilities
        if any_live:
            m = -1e18
            for i in range(n_sets):
                if def_live[i]:
                    m = max(m, temp * set_draw[i])
            tot = 0.0
            for i in range(n_sets):
                p[i] = np.exp(temp * set_draw[i] - m) if def_live[i] else 0.0
                tot += p[i]
            for i in range(n_sets):
                p[i] /= tot

        # arrivals, limited by gate throughput
        arrivals = tickets * (arrive_cum[k + 1] - arrive_cum[k]) + entry_q
        admitted = min(arrivals, gate_cap)
        entry_q = arrivals - admitted
        if any_live:
            for i in range(n_sets):
                d = admitted * p[i]
                T[i] += d
        else:
            hold += admitted

        # holders pick a set once there is one
        if any_live and hold > 0.0:
            for i in range(n_sets):
                T[i] += hold * p[i]
            hold = 0.0

        # heading home
        if t >= music_end:
            p_home = p_egress
        elif t >= music_end - early_window:
            p_home = p_early
        else:
            p_home = 0.0
        if p_home > 0.0:
            out = hold * p_home
            hold -= out
            L += out
            for i in range(n_sets):
                o = W[i] * p_home
                W[i] -= o
                outflow[k, i] += o
                L += o
                o = T[i] * p_home
                T[i] -= o
                L += o

        if t < music_end:
            # sets that ended drain to the next choice (draw blended with affinity)
            for a in range(n_sets):
                if set_end[a] > t or W[a] <= 0.0:
                    continue
                if W[a] < 1e-3:  # drained: stop re-processing this set
                    hold += W[a]
                    W[a] = 0.0
                    continue
                out = W[a] * p_leave_set
                W[a] -= out
                outflow[k, a] += out
                if not any_live:
                    hold += out
                    continue
                m = -1e18
                for j in range(n_sets):
                    if def_live[j]:
                        m = max(
                            m, temp * (w_draw * set_draw[j] + w_aff * set_aff[a, j])
                        )
                tot = 0.0
                for j in range(n_sets):
                    q = 0.0
                    if def_live[j]:
                        q = np.exp(
                            temp * (w_draw * set_draw[j] + w_aff * set_aff[a, j]) - m
                        )
                    p[j] = q
                    tot += q
                for j in range(n_sets):
                    T[j] += out * p[j] / tot
                # restore base probabilities for later use this minute
                m = -1e18
                for j in range(n_sets):
                    if def_live[j]:
                        m = max(m, temp * set_draw[j])
                tot = 0.0
                for j in range(n_sets):
                    p[j] = np.exp(temp * set_draw[j] - m) if def_live[j] else 0.0
                    tot += p[j]
                for j in range(n_sets):
                    p[j] /= tot

            # mid-set churn between live sets
            if any_live:
                for a in range(n_sets):
                    if not def_live[a] or W[a] <= 0.0:
                        continue
                    stay = p[a]
                    out = W[a] * p_churn * (1.0 - stay)
                    if out <= 0.0:
                        continue
                    W[a] -= out
                    outflow[k, a] += out
                    for j in range(n_sets):
                        if j != a and def_live[j]:
                            T[j] += out * p[j] / (1.0 - stay)

        # walkers reach their set
        for i in range(n_sets):
            done = T[i] * (1.0 - np.exp(-1.0 / max(transit_min[i], 0.5)))
            T[i] -= done
            W[i] += done
            inflow[k, i] += done

        # walkers reach the gate; the gate releases at capacity
        arrive_gate = L * (1.0 - np.exp(-1.0 / max(gate_walk, 0.5)))
        L -= arrive_gate
        Q += arrive_gate
        rel = min(Q, gate_cap)
        Q -= rel

        for i in range(n_sets):
            watch[k, i] = W[i]
            transit[k, i] = T[i]
        walking_out[k] = L
        queue[k] = Q
        released[k] = rel
    return watch, transit, inflow, outflow, walking_out, queue, released


@numba.njit(cache=True)
def _people_above(pop, q, q_cum, cap, threshold_people):
    """People in cells holding >= threshold_people when `pop` people spread over a
    stage's audience cells in proportion to q (sorted descending), no cell above
    `cap` people and the overflow spilling to the next cells (water-filling).

    Cells 0..m-1 are full; the rest hold lam * q[k] with
    lam = (pop - m * cap) / (1 - q_cum[m])."""
    K = q.shape[0]
    if pop <= 0.0:
        return 0.0
    if pop >= K * cap:
        return pop if cap >= threshold_people else 0.0
    lo, hi = 0, K - 1  # smallest m whose cell m is not full
    while lo < hi:
        m = (lo + hi) // 2
        lam = (pop - m * cap) / max(1.0 - q_cum[m], 1e-12)
        if lam * q[m] < cap:
            hi = m
        else:
            lo = m + 1
    m = lo
    lam = (pop - m * cap) / max(1.0 - q_cum[m], 1e-12)
    above = m * cap if cap >= threshold_people else 0.0
    # unfilled cells at or above the threshold: q[k] >= threshold_people / lam
    lo2, hi2 = m, K
    while lo2 < hi2:
        k = (lo2 + hi2) // 2
        if lam * q[k] >= threshold_people:
            lo2 = k + 1
        else:
            hi2 = k
    return above + lam * (q_cum[lo2] - q_cum[m])


@numba.njit(cache=True)
def _stage_risk(pop, moving, q, q_cum, cap, red_people, orange_people, c_move):
    n = pop.shape[0]
    red = np.zeros(n)
    dense = np.zeros(n)
    for k in range(n):
        if pop[k] <= 0.0:
            continue
        d_red = _people_above(pop[k], q, q_cum, cap, red_people)
        d_or = _people_above(pop[k], q, q_cum, cap, orange_people)
        turnover = min(1.0, c_move * moving[k] / pop[k])
        red[k] = d_red + (d_or - d_red) * turnover
        dense[k] = d_or
    return red, dense


class MacroModel:
    def __init__(self, venue: MacroVenue, calibration: dict | None = None):
        self.venue = venue
        self.calibration = calibration or load_calibration()
        self._stage_index = {s: i for i, s in enumerate(venue.stage_ids)}

    def series(
        self,
        setlist: list[dict],
        draw: dict[str, float],
        affinity: dict[str, dict[str, float]],
        tickets_sold: int,
    ) -> dict | None:
        """Expected headcounts per minute; independent of the risk calibration."""
        sets = [s for s in parse_setlist(setlist) if s["stage"] in self._stage_index]
        if not sets:
            return None
        v = self.venue
        music_start = min(s["start_min"] for s in sets)
        music_end = max(s["end_min"] for s in sets)
        t0 = music_start - GATES_OPEN_BEFORE_MIN
        n_steps = int(music_end + EGRESS_MAX_MIN - t0)

        stage_of = np.array([self._stage_index[s["stage"]] for s in sets])
        names = [s["artist"] for s in sets]
        aff = np.array(
            [[affinity.get(a, {}).get(b, 0.0) for b in names] for a in names]
        ).reshape(len(sets), len(sets))
        # typical walk into each set: mean over the other stages and the gate,
        # plus the expected amenity stop on the way
        walk = np.concatenate([v.stage_walk_min, v.gate_walk_min[None, :]])
        detour = TRANSIT_AMENITY_P * (
            0.5 * (AMENITY_DWELL_MIN["restroom"] + AMENITY_DWELL_MIN["water"]) + 2.0
        ) + BAR_ELIGIBLE_P * BAR_VISIT_P * (AMENITY_DWELL_MIN["bar"] + 2.0)
        transit_min = walk.mean(axis=0)[stage_of] + detour
        arrive_cum = arrival_fraction(t0 + np.arange(n_steps + 1), t0, music_end)
        gate_cap = v.gate_capacity_ppm if np.isfinite(v.gate_capacity_ppm) else 1e12

        watch, transit, inflow, outflow, walking_out, queue, released = _mean_field(
            float(t0), n_steps, float(tickets_sold), float(music_end),
            np.array([s["start_min"] for s in sets], dtype=np.float64),
            np.array([s["end_min"] for s in sets], dtype=np.float64),
            stage_of,
            np.nan_to_num(
                np.array([draw.get(n, 0.5) for n in names], dtype=np.float64), nan=0.5
            ),
            aff,
            arrive_cum, transit_min, float(v.gate_walk_min.mean()),
            float(gate_cap),
            DRAW_TEMPERATURE, DRAW_WEIGHT, AFFINITY_WEIGHT, CHURN_PER_HOUR,
            SET_LEAVE_MEAN_MIN, EGRESS_MEAN_MIN, EARLY_LEAVE_FRAC,
            float(EARLY_LEAVE_WINDOW_MIN), float(UPCOMING_LOOKAHEAD_MIN),
        )  # fmt: skip

        n_stages = len(v.stage_ids)
        pop = np.zeros((n_steps, n_stages))
        moving = np.zeros((n_steps, n_stages))
        for i, s in enumerate(stage_of):
            pop[:, s] += watch[:, i]
            moving[:, s] += inflow[:, i] + outflow[:, i]
        return {
            "t": t0 + np.arange(n_steps),
            "music_start": music_start,
            "pop": pop,
            "moving": moving,
            "transit": transit.sum(axis=1),
            "walking_out": walking_out,
            "queue": queue,
            "released": released,
        }

    def risk(
        self,
        series: dict,
        calibration: dict | None = None,
        density_red: float = DENSITY_RED,
        density_orange: float = DENSITY_ORANGE,
    ) -> tuple[np.ndarray, np.ndarray]:
        """(red, dense) people per minute: one column per stage, then the gate
        queue, then walkways.

        People count as red where the audience profile puts them at >= density_red,
        or at >= density_orange while the crowd is turning over (people walking
        through a dense crowd are what drives crowd pressure in the agent sim).
        A fitted share (c_transit) of people walking between places counts too:
        set changes push them through other stages' crowds."""
        v = self.venue
        cal = calibration or self.calibration
        rho_cap, c_move = cal["rho_cap"], cal["c_move"]
        pop, moving, queue = series["pop"], series["moving"], series["queue"]
        n_steps, n_stages = pop.shape
        red = np.zeros((n_steps, n_stages + 2))
        dense = np.zeros((n_steps, n_stages + 2))
        for s in range(n_stages):
            red[:, s], dense[:, s] = _stage_risk(
                pop[:, s], moving[:, s], v.profiles[s], v.profile_cums[s],
                rho_cap * v.cell_area, density_red * v.cell_area,
                density_orange * v.cell_area, c_move,
            )  # fmt: skip
        # gate queue: packs outward from the gate, so its people stand at rho_queue
        q_density = np.where(queue > 1.0, cal["rho_queue"], 0.0)
        q_turn = np.minimum(1.0, c_move * series["released"] / np.maximum(queue, 1.0))
        q_dense = np.where(q_density >= density_orange, queue, 0.0)
        red[:, -2] = np.where(q_density >= density_red, queue, q_dense * q_turn)
        dense[:, -2] = q_dense
        walking = series["transit"] + series["walking_out"]
        red[:, -1] = cal.get("c_transit", 0.0) * walking
        dense[:, -1] = red[:, -1]
        return red, dense

    def run(
        self,
        setlist: list[dict],
        draw: dict[str, float],
        affinity: dict[str, dict[str, float]],
        tickets_sold: int,
        density_red: float = DENSITY_RED,
        density_orange: float = DENSITY_ORANGE,
        summary_only: bool = False,
    ) -> dict:
        """Expected crowd and risk over the day. summary_only skips the per-minute
        output (the optimizer only needs the totals)."""
        ser = self.series(setlist, draw, affinity, tickets_sold)
        if ser is None:
            return {
                "stage_pop": {},
                "attendance": [],
                "gate_queue": [],
                "risk_windows": [],
                "red_person_min": 0.0,
                "dense_person_min": 0.0,
                "red_timeline": [],
            }
        red, dense = self.risk(ser, None, density_red, density_orange)
        if summary_only:
            return {
                "red_person_min": float(red.sum()),
                "dense_person_min": float(dense.sum()),
            }

        ts, pop = ser["t"], ser["pop"]
        on_site = pop.sum(axis=1) + ser["transit"] + ser["walking_out"] + ser["queue"]
        stage_pop = {
            sid: [
                {
                    "t": int(ts[k] - ser["music_start"]),
                    "t_min": int(ts[k]),
                    "pop": float(pop[k, s]),
                }
                for k in range(len(ts))
            ]
            for s, sid in enumerate(self.venue.stage_ids)
            if pop[:, s].any()
        }
        return {
            "stage_pop": stage_pop,
            "attendance": [
                {"t_min": int(t), "count": float(c)}
                for t, c in zip(ts, on_site, strict=True)
            ],
            "gate_queue": [
                {"t_min": int(t), "people": float(q)}
                for t, q in zip(ts, ser["queue"], strict=True)
            ],
            "red_timeline": [
                {"t_min": int(t), "people_in_red": float(r)}
                for t, r in zip(ts, red.sum(axis=1), strict=True)
            ],
            "risk_windows": _windows(
                red, ts, self.venue.stage_ids + ["gate", "walkways"], ser["music_start"]
            ),
            "red_person_min": float(red.sum()),
            "dense_person_min": float(dense.sum()),
        }


def _windows(
    red: np.ndarray, ts: np.ndarray, labels: list[str], music_start: float
) -> list[dict]:
    windows = []
    for s, label in enumerate(labels):
        flagged = np.nonzero(red[:, s] >= RISK_WINDOW_MIN_PEOPLE)[0]
        if len(flagged) == 0:
            continue
        groups = [[flagged[0]]]
        for k in flagged[1:]:
            if k - groups[-1][-1] <= RISK_WINDOW_MERGE_MIN:
                groups[-1].append(k)
            else:
                groups.append([k])
        for g in groups:
            windows.append(
                {
                    "stage": label,
                    "t_start": int(ts[g[0]] - music_start),
                    "t_end": int(ts[g[-1]] + 1 - music_start),
                    "t_start_min": int(ts[g[0]]),
                    "t_end_min": int(ts[g[-1]] + 1),
                    "score": float(red[g[0] : g[-1] + 1, s].max()),
                    "red_person_min": float(red[g[0] : g[-1] + 1, s].sum()),
                }
            )
    windows.sort(key=lambda w: -w["red_person_min"])
    return windows
