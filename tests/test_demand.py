import json

import numpy as np

import backend.demand.service as service


def _raw(listeners: int, capacity: int = 0) -> dict:
    return {
        "listeners": listeners,
        "playcount": listeners * 20,
        "tm_capacity": capacity,
        "affinity_scores": {},
        "tags": [],
    }


def test_one_superstar_does_not_flatten_the_lineup(tmp_path):
    svc = service.DemandService(tmp_path)
    raw = {
        "Star": _raw(40_000_000),
        "A": _raw(400_000),
        "B": _raw(90_000),
        "C": _raw(5_000),
    }
    draw = svc._composite_draw(list(raw), raw, {"Star": 3})
    assert draw["Star"] == 1.0 and draw["C"] == 0.0
    assert draw["Star"] > draw["A"] > draw["B"] > draw["C"]
    assert draw["A"] > 0.4  # ~0.01 with min-max scaling of raw counts


def test_artists_without_data_are_reported_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "LASTFM_API_KEY", "")
    monkeypatch.setattr(service, "TICKETMASTER_API_KEY", "")
    out = service.DemandService(tmp_path).compute(
        [{"artist": "Nobody", "stage": "s", "start": "20:00", "end": "21:00"}]
    )
    assert out["unknown"] == ["Nobody"] and "Nobody" not in out["draw"]


def test_cached_responses_are_used_without_api_keys(tmp_path, monkeypatch):
    """The demo must run offline from the cache (CLAUDE.md): no key, no fetch, cache hit."""
    monkeypatch.setattr(service, "LASTFM_API_KEY", "")
    monkeypatch.setattr(service, "TICKETMASTER_API_KEY", "")
    monkeypatch.setattr(service, "_CACHE_DIR", tmp_path)
    info = {"artist": {"stats": {"listeners": "1000", "playcount": "5000"}}}
    service._cache_key("artist_getInfo", {"artist": "Cached"}).write_text(
        json.dumps(info)
    )
    out = service.DemandService(tmp_path).compute(
        [{"artist": "Cached", "stage": "s", "start": "20:00", "end": "21:00"}]
    )
    assert out["unknown"] == [] and "Cached" in out["draw"]


def test_unknown_artists_fall_back_to_their_slot(tmp_path, monkeypatch):
    import backend.main as main

    monkeypatch.setattr(service, "LASTFM_API_KEY", "")
    monkeypatch.setattr(service, "TICKETMASTER_API_KEY", "")
    monkeypatch.setattr(main, "_demand_svc", service.DemandService(tmp_path))
    sl = [
        {"artist": "Opener", "stage": "s", "start": "18:00", "end": "19:00"},
        {"artist": "Closer", "stage": "s", "start": "23:00", "end": "00:00"},
    ]
    draw, _ = main._demand_for(sl)
    assert np.isclose(draw["Opener"], 0.10) and np.isclose(draw["Closer"], 0.75)
