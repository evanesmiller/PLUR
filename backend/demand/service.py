from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import numpy as np
import requests

# Matches " b2b ", " x " (case-insensitive) as set-collaboration separators.
# Spaces required on both sides to avoid splitting artist names like "X Ambassadors".
_SET_SPLIT_RE = re.compile(r"\s+b2b\s+|\s+x\s+", re.IGNORECASE)


def parse_set_name(name: str) -> list[str]:
    """Return the individual artist names from a B2B/x set name.

    'Fred again.. b2b Four Tet' → ['Fred again..', 'Four Tet']
    A plain artist name returns a single-element list.
    """
    parts = [p.strip() for p in _SET_SPLIT_RE.split(name) if p.strip()]
    return parts if len(parts) > 1 else [name.strip()]

_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
_LASTFM_URL = "http://ws.audioscrobbler.com/2.0/"
_TM_URL = "https://app.ticketmaster.com/discovery/v2/"

LASTFM_API_KEY = os.getenv("LASTFM_API_KEY", "")
TICKETMASTER_API_KEY = os.getenv("TICKETMASTER_API_KEY", "")


def _cache_key(tag: str, params: dict) -> Path:
    digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
    return _CACHE_DIR / f"{tag}_{digest}.json"


def _load_or_fetch(tag: str, params: dict, url: str, request_params: dict) -> dict:
    path = _cache_key(tag, params)
    if path.exists():
        return json.loads(path.read_text())
    if not request_params.get("api_key") and not request_params.get("apikey"):
        return {}
    try:
        r = requests.get(url, params=request_params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception:
        data = {}
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


class DemandService:
    def __init__(self, cache_dir: Path | None = None):
        self._cache = cache_dir or _CACHE_DIR
        self._cache.mkdir(parents=True, exist_ok=True)

    def compute(self, setlist: list[dict]) -> dict:
        set_names = list({e["artist"] for e in setlist})

        # Map each set name → component artist names (B2B sets expand to multiple)
        set_members: dict[str, list[str]] = {s: parse_set_name(s) for s in set_names}

        # Fetch data for every individual artist (deduplicated)
        all_artists = list({a for members in set_members.values() for a in members})
        raw: dict[str, dict] = {}
        for artist in all_artists:
            raw[artist] = self._artist_data(artist)

        # Build per-set aggregated data: sum listeners/playcount, union tags/affinity
        draw_raw: dict[str, dict] = {}
        for s, members in set_members.items():
            if len(members) == 1:
                draw_raw[s] = raw[members[0]]
            else:
                draw_raw[s] = self._aggregate_set(members, raw)

        # Build regional rank lookup from geo.getTopArtists
        regional_ranks = self._regional_ranks()

        draw = self._composite_draw(set_names, draw_raw, regional_ranks)
        affinity = self._affinity_matrix(set_names, draw_raw)
        tags = {s: draw_raw[s].get("tags", []) for s in set_names}

        return {"draw": draw, "affinity": affinity, "tags": tags, "set_members": set_members}

    def _aggregate_set(self, members: list[str], raw: dict[str, dict]) -> dict:
        """Combine per-artist API data for a B2B/collab set."""
        listeners = sum(raw[a]["listeners"] for a in members)
        playcount = sum(raw[a]["playcount"] for a in members)
        tm_capacity = max(raw[a]["tm_capacity"] for a in members)
        # Union tags, preserving order by first appearance
        seen: set[str] = set()
        tags: list[str] = []
        for a in members:
            for t in raw[a].get("tags", []):
                if t not in seen:
                    seen.add(t)
                    tags.append(t)
        # Merge affinity scores: take max across members for each other artist
        affinity_scores: dict[str, float] = {}
        for a in members:
            for other, score in raw[a].get("affinity_scores", {}).items():
                affinity_scores[other] = max(affinity_scores.get(other, 0.0), score)
        return {
            "listeners": listeners,
            "playcount": playcount,
            "affinity_scores": affinity_scores,
            "tags": tags[:10],
            "tm_capacity": tm_capacity,
        }

    def _artist_data(self, artist: str) -> dict:
        info = self._fetch_lastfm("artist.getInfo", {"artist": artist})
        similar = self._fetch_lastfm("artist.getSimilar", {"artist": artist, "limit": 100})
        tag_data = self._fetch_lastfm("artist.getTopTags", {"artist": artist, "limit": 10})
        tm_cap = self._fetch_ticketmaster(artist)

        listeners = int(info.get("artist", {}).get("stats", {}).get("listeners", 0) or 0)
        playcount = int(info.get("artist", {}).get("stats", {}).get("playcount", 0) or 0)

        similar_list = (
            similar.get("similarartists", {}).get("artist", [])
            if isinstance(similar.get("similarartists", {}), dict)
            else []
        )
        affinity_scores = {
            s["name"]: float(s.get("match", 0))
            for s in similar_list
            if isinstance(s, dict)
        }

        tags_raw = (
            tag_data.get("toptags", {}).get("tag", [])
            if isinstance(tag_data.get("toptags", {}), dict)
            else []
        )
        tags = [t["name"] for t in tags_raw if isinstance(t, dict)][:10]

        return {
            "listeners": listeners,
            "playcount": playcount,
            "affinity_scores": affinity_scores,
            "tags": tags,
            "tm_capacity": tm_cap,
        }

    def _regional_ranks(self) -> dict[str, int]:
        data = self._fetch_lastfm(
            "geo.getTopArtists",
            {"country": "united states", "limit": 200},
        )
        artists_list = (
            data.get("topartists", {}).get("artist", [])
            if isinstance(data.get("topartists", {}), dict)
            else []
        )
        return {a["name"]: i + 1 for i, a in enumerate(artists_list) if isinstance(a, dict)}

    def _composite_draw(
        self,
        artists: list[str],
        draw_raw: dict[str, dict],
        regional_ranks: dict[str, int],
    ) -> dict[str, float]:
        n = len(artists)
        if n == 0:
            return {}

        streaming = np.array([
            (draw_raw[a]["listeners"] * draw_raw[a]["playcount"]) ** 0.5
            for a in artists
        ], dtype=float)
        ranks = np.array([
            regional_ranks.get(a, 201) for a in artists
        ], dtype=float)
        # invert: lower rank number = higher score
        local_boost = 1.0 / ranks
        capacities = np.array([draw_raw[a]["tm_capacity"] for a in artists], dtype=float)

        def zscore(x: np.ndarray) -> np.ndarray:
            std = x.std()
            return (x - x.mean()) / std if std > 0 else np.zeros_like(x)

        w = [0.35, 0.30, 0.25, 0.05, 0.05]
        score = (
            w[0] * zscore(streaming)
            + w[1] * zscore(local_boost)
            + w[2] * zscore(capacities)
        )
        # shift to [0, 1]
        s_min, s_max = score.min(), score.max()
        if s_max > s_min:
            score = (score - s_min) / (s_max - s_min)
        else:
            score = np.ones(n) * 0.5

        return {a: float(score[i]) for i, a in enumerate(artists)}

    def _affinity_matrix(
        self,
        artists: list[str],
        draw_raw: dict[str, dict],
    ) -> dict[str, dict[str, float]]:
        artist_set = set(artists)
        matrix: dict[str, dict[str, float]] = {a: {} for a in artists}
        for a in artists:
            scores = draw_raw[a].get("affinity_scores", {})
            for b, score in scores.items():
                if b in artist_set:
                    matrix[a][b] = float(score)
                    matrix[b][a] = max(matrix[b].get(a, 0.0), float(score))
        return matrix

    def _fetch_lastfm(self, method: str, extra: dict) -> dict:
        if not LASTFM_API_KEY:
            return {}
        params = {"method": method, "api_key": LASTFM_API_KEY, "format": "json", **extra}
        tag = method.replace(".", "_")
        return _load_or_fetch(tag, extra, _LASTFM_URL, params)

    def _fetch_ticketmaster(self, artist: str) -> int:
        if not TICKETMASTER_API_KEY:
            return 0
        params = {"apikey": TICKETMASTER_API_KEY, "keyword": artist, "size": 5}
        tag = "tm_events"
        data = _load_or_fetch(tag, {"artist": artist}, _TM_URL + "events.json", params)
        events = (
            data.get("_embedded", {}).get("events", [])
            if isinstance(data.get("_embedded", {}), dict)
            else []
        )
        caps = []
        for ev in events:
            venues = (
                ev.get("_embedded", {}).get("venues", [])
                if isinstance(ev.get("_embedded", {}), dict)
                else []
            )
            for v in venues:
                cap = v.get("capacity")
                if cap:
                    try:
                        caps.append(int(cap))
                    except (ValueError, TypeError):
                        pass
        return max(caps) if caps else 0
