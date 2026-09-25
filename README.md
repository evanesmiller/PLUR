# PLUR — Predictive Large-scale User Routing

Crowd-crush prediction and mitigation tool for multi-stage music festivals. PLUR simulates how an audience moves through a venue, identifies where and when dangerous density conditions form, and gives event ops teams interactive controls — barriers, amenity repositioning, and schedule changes — to reduce risk before the event begins.

Built for the Ddoski's Lab + Anthropic + Most Technical hackathon tracks. Test venue: **HARD Summer 2025, Hollywood Park, Inglewood CA** (5 stages, ~80,000 attendees/day).

> **Disclaimer:** PLUR is a planning and decision-support prototype. It is not a validated or certified life-safety system. All recommendations must be reviewed by qualified event-safety professionals.

---

## What it does

**Simulate** — Run a two-tier crowd simulation across the full event day. The macroscopic layer computes per-stage populations over time; the microscopic social-force engine simulates individual agent movement and identifies crush-risk zones.

**Visualize** — Watch the crowd move in real time on a satellite-backed 3D map. Toggle heatmap, agent, and hotspot layers. Scrub the timeline or play back at variable speed.

**Mitigate** — Place and reposition physical barriers on the map by drawing them in the UI. Move restrooms, water stations, and bars to better distribute crowd load. Lock headliners and let the optimizer rearrange everything else.

**Optimize** — Submit your setlist to the schedule optimizer. It runs a local search over thousands of candidate slot swaps, scores each with the mean-field crowd model in people-minutes spent in crush-risk conditions, moves designated headliners into their stage's final slot, never moves locked slots, and can re-check the result with the full agent simulation.

**Brief** — Generate a Claude-powered plain-text safety briefing covering risk windows, stage-by-stage danger levels, actionable ops recommendations, and specific suggestions for repositioning amenities based on current hotspot locations.

---

## How the simulation works

PLUR uses a two-tier engine:

- **Macroscopic layer** — a mean-field version of the agent model (`sim/macro.py`): expected headcounts watching, walking to, or queueing for each set, minute by minute, using the same arrival curve, stage-choice rule, drain/churn/egress rates and gate limits as the agents (`sim/crowd_model.py`). It estimates people in red conditions from each stage's audience profile, the gate queue, and people walking between stages through other crowds, with four constants fitted against agent runs (`scripts/calibrate_macro.py` → `sim/macro_calibration.json`, which also records the fit quality). A run takes ~3 ms, which is what the schedule optimizer searches with; the agent simulation remains the reference, so use `validate_with_sim` before acting on small differences between schedules.
- **Microscopic layer** — coarse-grained Helbing–Molnár social-force simulation of the whole day (gates open → egress), up to 8,000 agents each standing for `tickets_sold / n_agents` people. Agent size and interaction range scale with √(people per agent), so a packed crowd of agents has the real crowd's density. Agents choose sets by artist draw and affinity, detour to restrooms, water and bars, stand in each stage's audience sector (from its `orientation` and `capacity_area_m2`), and route with walking-distance flow fields. Physics runs in one parallel numba kernel at `dt = 0.1 s`; agent centres are kept at least 0.7 body diameters apart, which caps packing near 9.4 people/m² (about the highest density observed in real crushes) at any agent scale.
- **Gates** admit and release people at their `capacity_pph`, so queues form at the entrance and, at close, in front of the exit.
- **Two-tier refinement** — the windows with the most people in red are re-simulated from a mid-run snapshot with every agent split into finer ones (~3 people per agent by default, `refine_windows` in the request); their hotspots replace the coarse ones.

Risk is measured on a Gaussian-smoothed (σ = 2 m) density field `ρ` (people/m²) and crowd pressure `P = ρ × Var(v)` (s⁻², Helbing et al. 2007). A cell is red when `ρ ≥ 6`, or `ρ ≥ 4` with `P ≥ 0.02 s⁻²` (onset of crowd turbulence). Hotspots are ranked by red exposure in person-minutes, and `/simulate_festival` also returns a `metrics` block with a per-minute timeline and the refined windows. Each playback frame carries the density field on a 4 m grid, which the map colours with the same thresholds.

Artist draw combines Last.fm reach, US rank and Ticketmaster venue size, each log-scaled before standardising so one superstar cannot flatten the rest of the lineup; acts with no data get a draw inferred from their slot time.

---

## Schedule optimizer

- Local search over pairwise slot swaps, scored by the mean-field model: people-minutes in red conditions, plus 5% of people-minutes in dense (orange) conditions to break ties
- Headliners are first moved into the final slot of their stage; they and locked slots never move after that (conflicts come back as `warnings`)
- Auto-filled acts are proposed three times as often as hand-placed ones
- `validate_with_sim: true` re-runs the agent simulation on the original and proposed schedules and returns both results
- Returns the proposed schedule, the score and red person-minutes before/after, the changes, and a Claude-generated rationale

(During the hackathon the optimizer ran on a 7-VM, 44-core Dask cluster, which no longer exists. It now runs on a single machine in a few seconds.)

---

## Architecture

```
Browser (localhost)
  React + deck.gl + MapLibre GL (Esri satellite tiles — no token required)
        ↕  HTTP
Backend (FastAPI, Python 3.12)
  ├── VenueLoader        GeoJSON → occupancy grid, UTM projection (EPSG:32611)
  ├── DemandService      Last.fm + Ticketmaster → artist draw + affinity matrix (cached)
  ├── MacroModel         Share-of-audience timeline, risk window detection
  ├── MicroSim           numba social-force engine with spatial hashing
  ├── RiskAnalyzer       Density/pressure → zones, hotspots
  ├── ScheduleOptimizer  Distributed local search — 44 cores / 7 VMs (6 workers + 1 coord)
  ├── MitigationPlanner  Barrier/staff heuristics + sim validation
  ├── PLURAgent          Claude-powered schedule rationale and safety briefing
  └── ProjectStore       Redis-backed project persistence
```

---

## Setup

### Prerequisites

- Python 3.12
- Node.js 18+
- Redis (running on `localhost:6379`)
- Last.fm API key (free at [last.fm/api](https://www.last.fm/api))
- Anthropic API key (for the Claude safety briefing endpoint)

### Backend

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export LASTFM_API_KEY=your_key_here
export ANTHROPIC_API_KEY=your_key_here
export REDIS_URL=redis://localhost:6379   # default if omitted

# run from the repo root: the backend is a package
uvicorn backend.main:app --reload --port 8000
```

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Interactive API docs: `http://localhost:8000/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:5173`. API calls proxy to `http://localhost:8000`.

---

## API Endpoints

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Health check, returns version |

### Venues

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/venues/{venue_id}` | Full venue GeoJSON, grid metadata, stages, gates, facilities |

### Projects

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/projects` | List all saved projects |
| `POST` | `/projects` | Create a new project |
| `GET` | `/projects/{id}` | Get project by ID |
| `PUT` | `/projects/{id}` | Update setlist, artists, or metadata |
| `DELETE` | `/projects/{id}` | Delete a project |
| `GET` | `/projects/{id}/sim` | Retrieve last saved simulation result |

### Simulation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/simulate_festival` | Run full macro + micro sim; returns agent frames, hotspots |

**`POST /simulate_festival` body:**
```json
{
  "venue_id": "hard_summer_2025",
  "project_id": "abc123",
  "setlist": [{ "artist": "string", "stage": "string", "start": "HH:MM", "end": "HH:MM" }],
  "sliders": { "max_capacity": 80000, "tickets_sold": 60000, "n_agents": 5000 },
  "barriers": [[[lon, lat], ...]],
  "amenities": [{ "id": "...", "facility_type": "restroom|water|bar", "lon": 0.0, "lat": 0.0 }],
  "density_red": 6.0,
  "density_orange": 4.0,
  "refine_windows": 2
}
```

### Optimization

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/optimize_schedule` | Distributed local-search optimizer; returns proposed schedule, risk delta, and Claude rationale |
| `POST` | `/safety_briefing` | Claude-generated safety briefing with amenity placement advice |
| `POST` | `/demand/scores` | Artist draw scores from Last.fm cache |

**`POST /optimize_schedule` body:**
```json
{
  "venue_id": "hard_summer_2025",
  "project_id": "abc123",
  "setlist": [...],
  "headliners": ["Artist A", "Artist B"],
  "sliders": { "max_capacity": 80000, "tickets_sold": 60000, "n_agents": 5000 },
  "validate_with_sim": false
}
```

**`POST /optimize_schedule` response:**
```json
{
  "proposed_schedule": [...],
  "risk_before": 412000.0,
  "risk_after": 298000.0,
  "red_person_min_before": 390000.0,
  "red_person_min_after": 281000.0,
  "changes": [{ "artist": "...", "from_stage": "...", "to_stage": "...", ... }],
  "warnings": [],
  "rationale": "Plain-text Claude rationale..."
}
```

**`POST /safety_briefing` body:**
```json
{
  "venue_id": "hard_summer_2025",
  "setlist": [...],
  "sliders": { "max_capacity": 80000, "tickets_sold": 60000 },
  "peak_density": 4.7,
  "hotspots": [...],
  "amenities": [{ "id": "...", "name": "...", "facility_type": "restroom|water|bar", "lat": 0.0, "lon": 0.0 }]
}
```

---

## Interactive controls

### Barriers
Draw crowd-control barriers directly on the map. Click **Place Barrier** then click anywhere on the venue. Select a barrier to drag, resize, or rotate it. Barriers are included as obstacles in the next simulation run.

### Amenities
Restrooms, water stations, and bars are displayed as interactive dots on the map. Click to select, drag to reposition. The next simulation uses their new positions, and they are forwarded to the Claude safety briefing, which suggests specific moves to reduce wait times and distribute crowd load away from hotspots.

### Set Times
Drag-and-drop artists between stage slots. Double-click a slot to lock it (headliner protection). Use **Auto-fill** to distribute unassigned artists automatically or upload a `.txt` roster. Submit to the optimizer when ready.

---

## Venue data

Venue files live under `backend/data/venues/<venue_id>/`:

```
venue.geojson   # FeatureCollection: walkable area, obstacles, stages, gates, facilities (WGS84)
meta.json       # name, origin_lonlat, utm_epsg, grid_cell_m, capacity
```

The bundled venue is `hard_summer_2025` (Hollywood Park, Inglewood CA). All simulation math uses **UTM Zone 11N (EPSG:32611)** in meters; the frontend receives WGS84 lon/lat.

---

## Calibration and venue checks

```bash
python -m scripts.calibrate_macro            # refit the mean-field model against agent runs (~20 min)
python -m scripts.check_venue_osm hard_summer_2025 "SoFi Stadium"   # compare a traced obstacle with OpenStreetMap
```

The venue check currently reports the traced SoFi Stadium obstacle at about 2x the area of OpenStreetMap's stadium footprint. That narrows the corridors on either side, so confirm the intended obstacle outline before relying on corridor hotspots.

---

## Risk thresholds

| Density | Level |
|---------|-------|
| < 3 p/m² | Green — comfortable |
| 3–4 p/m² | Yellow — busy |
| 4–6 p/m² | Orange — caution |
| ≥ 6 p/m², or ≥ 4 p/m² with pressure ≥ 0.02 s⁻² | Red — crush risk |

Orange and red thresholds are adjustable per-project via the control panel sliders.

---

## Data sources

- **Last.fm API** (primary) — `artist.getInfo`, `geo.getTopArtists`, `artist.getSimilar`, `artist.getTopTags`. Free, key only.
- **Ticketmaster Discovery API** (secondary) — venue capacities as live-demand proxy. Free tier, 5k req/day.

All API responses are cached to `backend/data/cache/*.json`. The demo never calls live APIs.

---

## Tech stack

| Layer | Libraries |
|-------|-----------|
| Frontend | React 19, Vite, deck.gl 9, MapLibre GL 5, react-map-gl |
| Backend | Python 3.12, FastAPI, uvicorn, numba, numpy, scipy |
| GIS | shapely, pyproj (UTM projection) |
| Parallelism | numba (parallel physics kernel) |
| Storage | Redis (asyncio, project persistence) |
| AI | Anthropic Claude (schedule rationale and safety briefing) |
