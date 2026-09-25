from __future__ import annotations

DAY_MIN = 24 * 60
# Clock times before this belong to the following calendar day, so a set
# listed as "00:00"–"01:00" follows one listed as "23:00"–"00:00".
ROLLOVER_MIN = 6 * 60


def clock_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def event_minutes(start: str, end: str) -> tuple[int, int]:
    """Convert "HH:MM" set times to monotonic minutes since the festival day's midnight."""
    s = clock_to_min(start)
    e = clock_to_min(end)
    if s < ROLLOVER_MIN:
        s += DAY_MIN
    if e < ROLLOVER_MIN:
        e += DAY_MIN
    if e <= s:
        e += DAY_MIN
    return s, e


def parse_setlist(setlist: list[dict]) -> list[dict]:
    out = []
    for e in setlist:
        s, t = event_minutes(e["start"], e["end"])
        out.append({**e, "start_min": s, "end_min": t})
    return out
