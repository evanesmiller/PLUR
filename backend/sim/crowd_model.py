"""Crowd behaviour parameters shared by the agent sim (behavior.py) and its
mean-field counterpart (macro.py), so the two layers model the same crowd."""

from __future__ import annotations

import numpy as np

# arrival: gates open this long before the first set; the arrival curve is a
# logistic in normalised time between gates-open and the last set's end
GATES_OPEN_BEFORE_MIN = 60
ARRIVAL_STEEPNESS = 8.0
ARRIVAL_MIDPOINT = 0.35

# stage choice: softmax(DRAW_TEMPERATURE * score); after a set, the score blends
# the next act's draw with its affinity to the act just watched
DRAW_TEMPERATURE = 2.0
DRAW_WEIGHT = 0.6
AFFINITY_WEIGHT = 0.4
UPCOMING_LOOKAHEAD_MIN = 60

SET_LEAVE_MEAN_MIN = 4.0  # crowds drain over a few minutes after a set ends
CHURN_PER_HOUR = 0.2  # mid-set drifting between concurrent stages
EGRESS_MEAN_MIN = 8.0  # after the last set, mean wait before heading out
EARLY_LEAVE_FRAC = 0.10  # share who leave during the final window before close
EARLY_LEAVE_WINDOW_MIN = 45
EGRESS_MAX_MIN = 240  # hard stop for the simulation after the last set

# amenities
AMENITY_DWELL_MIN = {"restroom": 1.5, "water": 0.75, "bar": 4.0}
MAX_DWELL_MIN = 15.0
QUEUE_DWELL_PER_AGENT_MIN = 0.1
QUEUE_DWELL_CAP_MIN = 1.5
ENTRY_AMENITY_P = 0.25  # arrivals who stop at a restroom/water first
TRANSIT_AMENITY_P = 0.15  # restroom/water stop per set change (max one a day)
BAR_ELIGIBLE_P = 0.22  # share of attendees who are 21+
BAR_VISIT_P = 0.05  # bar stop per set change

WALK_SPEED = 1.3  # m/s, mean free walking speed

# audience area: a sector in front of the stage, opening ±60°, sized by the
# stage's capacity_area_m2 and weighted toward the front
AUDIENCE_HALF_ANGLE = np.deg2rad(60.0)
AUDIENCE_MIN_R = 5.0
DEFAULT_AUDIENCE_AREA_M2 = 6000.0
FRONT_BIAS = 0.5  # weight = exp(-r / (FRONT_BIAS * r_max))


def arrival_fraction(t, gates_open: float, music_end: float):
    """Cumulative share of ticket holders who have arrived by time t (scalar or
    array): 0 at gates-open, 1 at the last set's end."""
    total = music_end - gates_open
    if total <= 0:
        return np.ones_like(np.asarray(t, dtype=float))
    x = np.clip((np.asarray(t, dtype=float) - gates_open) / total, 0.0, 1.0)

    def logistic(v):
        return 1.0 / (1.0 + np.exp(-ARRIVAL_STEEPNESS * (v - ARRIVAL_MIDPOINT)))

    lo, hi = logistic(0.0), logistic(1.0)
    return (logistic(x) - lo) / (hi - lo)


def choice_logits(
    draw: np.ndarray, affinity_from_prev: np.ndarray | None
) -> np.ndarray:
    score = (
        draw
        if affinity_from_prev is None
        else DRAW_WEIGHT * draw + AFFINITY_WEIGHT * affinity_from_prev
    )
    return DRAW_TEMPERATURE * score
