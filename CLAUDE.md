# SURGE — Simulated Understanding of Risk in Gathering Events

Crowd-crush prediction & mitigation tool for multi-stage music festivals.
Hackathon project targeting Ddoski's Lab + Anthropic + Most Technical tracks.

## Source of Truth

- `SURGE_Design_Doc.md` — full engineering spec (architecture, API, repo layout, milestones M0–M9, parameters)
- `SURGE_Team_Handoff.md` — decisions log, current status, data stack, infra plan

Read both before making any architectural decisions.

## Key Decisions (DO NOT re-litigate)

- **Two-tier sim engine**: fast macroscopic layer (whole-day timeline) + detailed microscopic social-force layer (chosen window only, ~5-10k subsampled agents)
- **Real sim first; surrogate is deferred backup only**
- **Frontend**: React + deck.gl + MapLibre GL with free Esri satellite tiles (NO Mapbox token)
- **Backend**: Python 3.12, FastAPI, numba, numpy, scipy, shapely, pyproj, joblib
- **Placements are heuristic, not globally optimized** — report as "recommended"
- **Crush metric = density + pressure** (ρ ≥ 6 or pressure spike = red)
- **Framing**: "decision-support prototype, not a certified life-safety system"
- **DO NOT use Spotify API** (deprecated for new apps), AnyLogic, or Oasys MassMotion

## Data Sources

- **Last.fm API** (primary, free, key only) — artist.getInfo, geo.getTopArtists, artist.getSimilar, artist.getTopTags
- **Ticketmaster Discovery API** (secondary, free, 5k/day) — venue capacities
- Cache ALL API responses to JSON. Never call live during demo.

## Test Venue

HARD Summer 2025, Hollywood Park (Inglewood, CA), 7 stages, ~80k/day.
UTM Zone 11N / EPSG:32611 for metric projection.

## Repo Structure

```
surge/
├── backend/
│   ├── main.py                 # FastAPI app + routes
│   ├── venue/loader.py         # GeoJSON → grid, pyproj transforms
│   ├── demand/service.py       # Last.fm/Ticketmaster + composite index
│   ├── sim/macro.py            # share-of-audience timeline
│   ├── sim/micro.py            # numba social-force engine + spatial hash
│   ├── sim/risk.py             # density/pressure → zones, hotspots
│   ├── optimize/schedule.py    # local search + parallel scoring
│   ├── optimize/mitigation.py  # barrier/staff/facility heuristics
│   ├── agent/claude.py         # Claude-powered rationale/briefing
│   └── data/
│       ├── venues/hard_summer_2025/{venue.geojson,meta.json}
│       └── cache/*.json
├── frontend/
│   ├── src/App.jsx
│   ├── src/components/
│   └── src/deck/
├── scripts/
├── requirements.txt
└── README.md
```

## Milestones (MVP = through M6)

- M0: Scaffold (FastAPI + React/deck.gl/MapLibre with Esri satellite)
- M1: Venue GeoJSON + loader + render
- M2: Micro-sim (social-force + spatial hash + numba)
- M3: Risk fields (density/pressure → zones/hotspots + timeline)
- M4: Demand service (Last.fm/Ticketmaster cached) + macro model
- M5: Schedule optimizer (parallel local search, headliners-last)
- M6: Mitigations (barriers + staff heuristics + sim validation)
- M7: Claude agent for rationale/briefing
- M8: Stretch (restrooms/water, facility placement, dynamic entry)
- M9: Polish & demo

## Commands

Use project slash commands for workstream-specific guidance:
- `/project:sim` — micro-sim + risk engine work
- `/project:data` — demand index + macro model + scheduler
- `/project:frontend` — deck.gl + MapLibre UI
- `/project:infra` — FastAPI + cluster + mitigations + Claude agent

## Style

- Python: type hints, no docstrings unless non-obvious, black formatting
- Frontend: functional React components, JSX
- All sim math in meters (UTM projection); convert to lon/lat only for frontend
- Density in people/m², pressure = ρ × var(local_velocity)
