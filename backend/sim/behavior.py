"""Agent decision layer: arrival, stage choice, set changes, amenity visits, egress.

Runs between physics chunks and only rewrites each agent's destination
(target point, flow field, desired speed); the physics kernel does the moving.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .pathfinding import WalkableSnapper

GATE, STAGE, AMENITY = 0, 1, 2
WAITING, ACTIVE, EXITED = 0, 1, 2

AMENITY_DWELL_MIN = {"restroom": 1.5, "water": 0.75, "bar": 4.0}
MAX_DWELL_MIN = 15.0
QUEUE_DWELL_PER_AGENT_MIN = 0.1
QUEUE_DWELL_CAP_MIN = 1.5
ENTRY_AMENITY_P = 0.25  # new arrivals who stop at a restroom/water first
TRANSIT_AMENITY_P = (
    0.15  # chance of a restroom/water stop per set change (max 1 per day)
)
BAR_ELIGIBLE_P = 0.22  # share of attendees who are 21+
BAR_VISIT_P = 0.05  # chance of a bar stop per set change
SET_LEAVE_MEAN_MIN = 4.0  # crowds drain over a few minutes after a set ends
CHURN_PER_HOUR = 0.2  # mid-set drifting between concurrent stages
UPCOMING_LOOKAHEAD_MIN = 60
EGRESS_MEAN_MIN = 8.0  # after the last set, mean time before an agent heads out
EARLY_LEAVE_FRAC = 0.10  # share who leave during the final window before close
EARLY_LEAVE_WINDOW_MIN = 45
DRAW_TEMPERATURE = 2.0
V0_MEAN, V0_STD = 1.3, 0.3
IDLE_V0 = 0.05
HEADING_NOISE_RAD = 0.26
AMENITY_REACH_M = 6.0  # close enough to join the queue
SETTLE_SPEED = 0.25  # agents blocked by the crowd inside the audience area stop pushing
SPAWN_JITTER_M = 4.0

# audience area: sector in front of the stage, opening ±60°
AUDIENCE_HALF_ANGLE = np.deg2rad(60.0)
AUDIENCE_MIN_R = 5.0
DEFAULT_AUDIENCE_AREA_M2 = 6000.0


@dataclass
class Layout:
    """Static destination geometry. Flow-field ids: gates, then stages, then amenities."""

    snapper: WalkableSnapper
    dists: np.ndarray  # (T, rows, cols) walking metres
    gate_pts: np.ndarray  # (G, 2)
    gate_weights: np.ndarray  # (G,) arrival share
    stage_ids: list[str]
    stage_pts: np.ndarray  # (S, 2)
    stage_spots: list[
        tuple[np.ndarray, np.ndarray]
    ]  # per stage: (K,2) cell centres, (K,) cumulative probs
    stage_reach: np.ndarray  # (S,) max distance of the audience area from the stage
    amenity_pts: np.ndarray  # (A, 2)
    amenity_types: np.ndarray  # (A,) str

    @property
    def n_gates(self) -> int:
        return len(self.gate_pts)

    def gate_flow(self, g):
        return g

    def stage_flow(self, s):
        return self.n_gates + s

    def amenity_flow(self, a):
        return self.n_gates + len(self.stage_pts) + a

    def walk(self, flow_ids: np.ndarray, pos: np.ndarray) -> np.ndarray:
        """(len(flow_ids), len(pos)) walking distances."""
        r, c = self.snapper.cell_of(pos)
        f = np.atleast_1d(np.asarray(flow_ids))
        return self.dists[f[:, None], r[None, :], c[None, :]]


def audience_spots(
    stage_xy: np.ndarray,
    orientation_deg: float | None,
    area_m2: float | None,
    stage_dist: np.ndarray,
    snapper: WalkableSnapper,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Walkable, reachable cells in the stage's audience sector, weighted toward the front."""
    area = area_m2 or DEFAULT_AUDIENCE_AREA_M2
    occ = snapper.occupancy & np.isfinite(stage_dist)
    r_idx, c_idx = np.nonzero(occ)
    centers = snapper.center(r_idx, c_idx)
    rel = centers - stage_xy
    dist = np.hypot(rel[:, 0], rel[:, 1])

    if orientation_deg is None:
        r_max = np.sqrt(area / np.pi + AUDIENCE_MIN_R**2)
        in_zone = (dist >= AUDIENCE_MIN_R) & (dist <= r_max)
    else:
        # orientation: compass bearing from the stage toward its audience
        theta = np.deg2rad(90.0 - orientation_deg)
        facing = np.array([np.cos(theta), np.sin(theta)])
        cos_ang = (rel @ facing) / np.maximum(dist, 1e-9)
        r_max = np.sqrt(area / AUDIENCE_HALF_ANGLE + AUDIENCE_MIN_R**2)
        in_zone = (
            (dist >= AUDIENCE_MIN_R)
            & (dist <= r_max)
            & (cos_ang >= np.cos(AUDIENCE_HALF_ANGLE))
        )

    if in_zone.sum() < 10:
        # sector blocked or venue too small: fall back to the nearest reachable cells
        in_zone = dist <= np.sort(dist)[min(len(dist) - 1, 200)]
    spots = centers[in_zone]
    w = np.exp(-dist[in_zone] / (0.5 * r_max))
    return spots, np.cumsum(w) / w.sum(), float(dist[in_zone].max())


class Crowd:
    def __init__(
        self,
        n: int,
        layout: Layout,
        sets: list[dict],
        draw: dict[str, float],
        affinity: dict[str, dict[str, float]],
        rng: np.random.Generator,
        cell_m: float,
    ):
        self.n = n
        self.layout = layout
        self.rng = rng
        self.cell_m = cell_m

        stage_index = {sid: i for i, sid in enumerate(layout.stage_ids)}
        self.sets = sets
        self.set_start = np.array([s["start_min"] for s in sets], dtype=np.float64)
        self.set_end = np.array([s["end_min"] for s in sets], dtype=np.float64)
        self.set_stage = np.array(
            [stage_index[s["stage"]] for s in sets], dtype=np.int64
        )
        self.set_draw = np.array(
            [draw.get(s["artist"], 0.5) for s in sets], dtype=np.float64
        )
        names = [s["artist"] for s in sets]
        self.set_aff = np.array(
            [[affinity.get(a, {}).get(b, 0.0) for b in names] for a in names],
            dtype=np.float64,
        ).reshape(len(sets), len(sets))

        # physics-facing state (passed to the kernel)
        self.pos = np.zeros((n, 2))
        self.vel = np.zeros((n, 2))
        self.status = np.zeros(n, dtype=np.int8)
        self.target = np.zeros((n, 2))
        self.flow_id = np.zeros(n, dtype=np.int64)
        self.v0_base = rng.normal(V0_MEAN, V0_STD, n).clip(0.5, 2.0)
        self.v0 = self.v0_base.copy()
        self.heading = np.zeros(n)
        self.exit_on_arrival = np.zeros(n, dtype=np.bool_)
        self.arrived = np.zeros(n, dtype=np.bool_)

        # decision state
        self.dest_kind = np.full(n, -1, dtype=np.int8)
        self.dest_ref = np.full(n, -1, dtype=np.int64)
        self.watching = np.full(
            n, -1, dtype=np.int64
        )  # set index the agent is attending / heading to
        self.next_set = np.full(
            n, -1, dtype=np.int64
        )  # set to join after an amenity stop
        self.idle_until = np.full(n, np.nan)
        self.leaving = np.zeros(n, dtype=np.bool_)
        self.bar_eligible = rng.random(n) < BAR_ELIGIBLE_P
        self.transit_visits_left = rng.integers(0, 2, n)
        self.n_arrived = 0

    # ---------- destination primitives ----------

    def _set_dest(
        self,
        idx: np.ndarray,
        kind: int,
        refs: np.ndarray,
        targets: np.ndarray,
        flows: np.ndarray,
    ):
        self.dest_kind[idx] = kind
        self.dest_ref[idx] = refs
        self.target[idx] = targets
        self.flow_id[idx] = flows
        self.exit_on_arrival[idx] = kind == GATE
        self.arrived[idx] = False
        self.heading[idx] = self.rng.normal(0.0, HEADING_NOISE_RAD, len(idx))

    def _go_stage(self, idx: np.ndarray, set_idx: np.ndarray):
        stages = self.set_stage[set_idx]
        targets = np.empty((len(idx), 2))
        for s in np.unique(stages):
            m = stages == s
            spots, cum = self.layout.stage_spots[s]
            k = np.searchsorted(cum, self.rng.random(m.sum()))
            targets[m] = spots[np.minimum(k, len(spots) - 1)] + self.rng.uniform(
                -0.5 * self.cell_m, 0.5 * self.cell_m, (m.sum(), 2)
            )
        self.watching[idx] = set_idx
        self._set_dest(idx, STAGE, stages, targets, self.layout.stage_flow(stages))

    def _go_gate(self, idx: np.ndarray):
        if len(idx) == 0:
            return
        g = np.argmin(
            self.layout.walk(np.arange(self.layout.n_gates), self.pos[idx]), axis=0
        )
        self.watching[idx] = -1
        self.leaving[idx] = True
        self._set_dest(idx, GATE, g, self.layout.gate_pts[g], self.layout.gate_flow(g))

    def _nearest_amenity(self, idx: np.ndarray, types: tuple[str, ...]) -> np.ndarray:
        """Nearest amenity of the given types by walking distance, -1 if none reachable."""
        cand = np.nonzero(np.isin(self.layout.amenity_types, types))[0]
        if len(cand) == 0 or len(idx) == 0:
            return np.full(len(idx), -1)
        d = self.layout.walk(self.layout.amenity_flow(cand), self.pos[idx])
        best = np.argmin(d, axis=0)
        return np.where(np.isfinite(d[best, np.arange(len(idx))]), cand[best], -1)

    def _go_amenity(self, idx: np.ndarray, amenity: np.ndarray, then_set: np.ndarray):
        jitter = self.rng.normal(0.0, 1.5, (len(idx), 2))
        targets = self.layout.snapper.snap(self.layout.amenity_pts[amenity] + jitter)
        self.next_set[idx] = then_set
        self._set_dest(
            idx, AMENITY, amenity, targets, self.layout.amenity_flow(amenity)
        )

    def _route_to_set(self, idx: np.ndarray, set_idx: np.ndarray, allow_detour: bool):
        """Send agents toward a set, possibly via a restroom/water or bar stop."""
        has_set = set_idx >= 0
        # no set to go to: hold position until the programme gives them one
        hold = idx[~has_set]
        self.watching[hold] = -1
        self._set_dest(
            hold, STAGE, np.full(len(hold), -1), self.pos[hold], self.flow_id[hold]
        )
        idx, set_idx = idx[has_set], set_idx[has_set]
        if len(idx) == 0:
            return

        direct = np.ones(len(idx), dtype=bool)
        if allow_detour:
            transit = (self.transit_visits_left[idx] > 0) & (
                self.rng.random(len(idx)) < TRANSIT_AMENITY_P
            )
            bar = (
                ~transit
                & self.bar_eligible[idx]
                & (self.rng.random(len(idx)) < BAR_VISIT_P)
            )
            for mask, types in ((transit, ("restroom", "water")), (bar, ("bar",))):
                sub = idx[mask]
                a = self._nearest_amenity(sub, types)
                ok = a >= 0
                self._go_amenity(sub[ok], a[ok], set_idx[mask][ok])
                direct[np.nonzero(mask)[0][ok]] = False
            self.transit_visits_left[idx[transit]] -= 1
        self._go_stage(idx[direct], set_idx[direct])

    def _choose_sets(self, idx: np.ndarray, t: float, prev: np.ndarray) -> np.ndarray:
        """Pick a set per agent: softmax over draw, blended 60/40 with affinity to the set just watched."""
        live = np.nonzero((self.set_start <= t) & (t < self.set_end))[0]
        if len(live) == 0:
            soon = np.nonzero(
                (self.set_start > t) & (self.set_start <= t + UPCOMING_LOOKAHEAD_MIN)
            )[0]
            if len(soon) == 0:
                return np.full(len(idx), -1)
            live = soon[self.set_start[soon] == self.set_start[soon].min()]
        base = np.broadcast_to(self.set_draw[live], (len(idx), len(live)))
        has_prev = prev >= 0
        aff = np.zeros((len(idx), len(live)))
        aff[has_prev] = self.set_aff[prev[has_prev]][:, live]
        score = np.where(has_prev[:, None], 0.6 * base + 0.4 * aff, base)
        logits = DRAW_TEMPERATURE * score
        p = np.exp(logits - logits.max(axis=1, keepdims=True))
        cum = np.cumsum(p, axis=1)
        u = self.rng.random(len(idx))[:, None] * cum[:, -1:]
        return live[np.minimum((u > cum).sum(axis=1), len(live) - 1)]

    # ---------- per-chunk update ----------

    def spawn(self, count: int, t: float) -> None:
        idx = np.nonzero(self.status == WAITING)[0][:count]
        if len(idx) == 0:
            return
        g = self.rng.choice(
            self.layout.n_gates, size=len(idx), p=self.layout.gate_weights
        )
        pts = self.layout.gate_pts[g] + self.rng.normal(
            0.0, SPAWN_JITTER_M, (len(idx), 2)
        )
        self.pos[idx] = self.layout.snapper.snap(pts)
        self.vel[idx] = 0.0
        self.status[idx] = ACTIVE
        self.n_arrived += len(idx)

        sets = self._choose_sets(idx, t, np.full(len(idx), -1))
        entry = (self.rng.random(len(idx)) < ENTRY_AMENITY_P) & (sets >= 0)
        a = self._nearest_amenity(idx[entry], ("restroom", "water"))
        ok = a >= 0
        self._go_amenity(idx[entry][ok], a[ok], sets[entry][ok])
        rest = np.ones(len(idx), dtype=bool)
        rest[np.nonzero(entry)[0][ok]] = False
        self._route_to_set(idx[rest], sets[rest], allow_detour=False)

    def _settle(self, active: np.ndarray) -> None:
        """Agents stopped by the crowd inside their stage's audience area take the spot they are on."""
        cand = active & (self.dest_kind == STAGE) & (self.dest_ref >= 0) & ~self.arrived
        cand &= np.hypot(self.vel[:, 0], self.vel[:, 1]) < SETTLE_SPEED
        idx = np.nonzero(cand)[0]
        if len(idx) == 0:
            return
        s = self.dest_ref[idx]
        near = (
            np.hypot(*(self.pos[idx] - self.layout.stage_pts[s]).T)
            <= self.layout.stage_reach[s]
        )
        idx = idx[near]
        self.target[idx] = self.pos[idx]
        self.arrived[idx] = True

    def update(self, t: float, chunk_min: float, music_end: float) -> None:
        active = self.status == ACTIVE
        idle = active & ~np.isnan(self.idle_until)

        # finished queueing at an amenity
        done = np.nonzero(idle & (self.idle_until <= t))[0]
        if len(done):
            self.idle_until[done] = np.nan
            self.v0[done] = self.v0_base[done]
            home = done[self.leaving[done] | (t >= music_end)]
            self._go_gate(home)
            go = done[~(self.leaving[done] | (t >= music_end))]
            nxt = self.next_set[go]
            stale = (nxt < 0) | (self.set_end[np.maximum(nxt, 0)] <= t)
            nxt = np.where(stale, self._choose_sets(go, t, nxt), nxt)
            self._route_to_set(go, nxt, allow_detour=False)

        # reached an amenity: start queueing
        reached = self.arrived | (
            np.hypot(*(self.pos - self.target).T) < AMENITY_REACH_M
        )
        at_amenity = np.nonzero(
            active & (self.dest_kind == AMENITY) & reached & np.isnan(self.idle_until)
        )[0]
        if len(at_amenity):
            refs = self.dest_ref[at_amenity]
            queued = np.bincount(
                self.dest_ref[idle & (self.dest_kind == AMENITY)],
                minlength=len(self.layout.amenity_pts),
            )
            base = np.array(
                [AMENITY_DWELL_MIN[str(self.layout.amenity_types[r])] for r in refs]
            )
            dwell = np.minimum(
                base
                + np.minimum(
                    queued[refs] * QUEUE_DWELL_PER_AGENT_MIN, QUEUE_DWELL_CAP_MIN
                ),
                MAX_DWELL_MIN,
            )
            self.idle_until[at_amenity] = t + dwell
            self.v0[at_amenity] = IDLE_V0

        active = self.status == ACTIVE
        self._settle(active)
        free = (
            active
            & ~self.leaving
            & np.isnan(self.idle_until)
            & (self.dest_kind != AMENITY)
        )

        # heading home
        if t >= music_end:
            p = 1.0 - np.exp(-chunk_min / EGRESS_MEAN_MIN)
        elif t >= music_end - EARLY_LEAVE_WINDOW_MIN:
            p = 1.0 - (1.0 - EARLY_LEAVE_FRAC) ** (chunk_min / EARLY_LEAVE_WINDOW_MIN)
        else:
            p = 0.0
        if p > 0:
            home = np.nonzero(free & (self.rng.random(self.n) < p))[0]
            self._go_gate(home)
            free[home] = False
        if t >= music_end:
            # agents mid-queue head home once they are done
            self.leaving[active & ~np.isnan(self.idle_until)] = True
            return

        # set ended, or waiting for the programme to start: drift off to the next set
        w = self.watching
        ended = free & (w >= 0) & (self.set_end[np.maximum(w, 0)] <= t)
        drift = ended & (
            self.rng.random(self.n) < 1.0 - np.exp(-chunk_min / SET_LEAVE_MEAN_MIN)
        )
        unassigned = free & (w < 0)
        churn = (
            free
            & (w >= 0)
            & ~ended
            & (self.rng.random(self.n) < CHURN_PER_HOUR * chunk_min / 60.0)
        )
        move = np.nonzero(drift | unassigned | churn)[0]
        if len(move):
            new_sets = self._choose_sets(move, t, self.watching[move])
            same = new_sets == self.watching[move]
            move, new_sets = move[~same], new_sets[~same]
            self._route_to_set(move, new_sets, allow_detour=True)
