from backend.sim.timeline import event_minutes, parse_setlist


def test_same_day_set():
    assert event_minutes("21:00", "22:00") == (1260, 1320)


def test_set_ending_at_midnight():
    assert event_minutes("23:00", "00:00") == (1380, 1440)


def test_sets_after_midnight_follow_evening_sets():
    _, e1 = event_minutes("23:00", "00:00")
    s2, e2 = event_minutes("00:00", "01:30")
    assert (s2, e2) == (1440, 1530)
    assert s2 >= e1


def test_parse_setlist_keeps_fields():
    out = parse_setlist(
        [{"artist": "A", "stage": "x", "start": "01:00", "end": "02:00"}]
    )
    assert out[0]["artist"] == "A"
    assert (out[0]["start_min"], out[0]["end_min"]) == (1500, 1560)
