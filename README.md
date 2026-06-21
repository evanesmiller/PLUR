# PLUR — Predictive Large-scale User Routing

Crowd-crush prediction and mitigation tool for multi-stage music festivals. PLUR simulates how an audience moves through a venue, identifies where and when dangerous density conditions form, and gives event ops teams interactive controls — barriers, amenity repositioning, and schedule changes — to reduce risk before the event begins.

Built for the Ddoski's Lab + Anthropic + Most Technical hackathon tracks. Test venue: **HARD Summer 2025, Hollywood Park, Inglewood CA** (5 stages, ~80,000 attendees/day).

> **Disclaimer:** PLUR is a planning and decision-support prototype. It is not a validated or certified life-safety system. All recommendations must be reviewed by qualified event-safety professionals.

---

## What it does

**Simulate** — Run a two-tier crowd simulation across the full event day. The macroscopic layer computes per-stage populations over time; the microscopic social-force engine simulates individual agent movement and identifies crush-risk zones.

**Visualize** — Watch the crowd move in real time on a satellite-backed 3D map. Toggle heatmap, agent, and hotspot layers. Scrub the timeline or play back at variable speed.

**Mitigate** — Place and reposition physical barriers on the map by drawing them in the UI. Move restrooms, water stations, and bars to better distribute crowd load. Lock headliners and let the optimizer rearrange everything else.

**Optimize** — Submit your setlist to a distributed schedule optimizer running across **44 CPU cores on 7 virtual machines** (6 workers + 1 coordinator). It performs parallel local search across thousands of candidate schedules, scoring each against the crowd-crush risk model, and returns the arrangement that minimizes peak density while respecting locked headliner slots.

**Brief** — Generate a Claude-powered plain-text safety briefing covering risk windows, stage-by-stage danger levels, actionable ops recommendations, and specific suggestions for repositioning amenities based on current hotspot locations.

---

## How the simulation works

PLUR uses a two-tier engine:

- **Macroscopic layer** — analytic model covering the full event day. Computes per-stage population over time using artist draw scores (from Last.fm) and crowd migration between stages. Identifies risk windows where density is likely to spike.
- **Microscopic layer** — Helbing–Molnár social-force simulation run on a chosen time window (~5,000 subsampled agents, each representing ~16 real people). Uses numba JIT compilation and spatial hashing for real-time performance.

Risk is defined as `density ρ (people/m²)` and `pressure P = ρ × var(local_velocity)`. Cells at `ρ ≥ 6` or with a pressure spike are flagged red.

---

## Schedule optimizer — distributed cluster

The schedule optimizer runs on a dedicated compute cluster:

- **7 virtual machines** — 1 coordinator + 6 workers
- **44 CPU cores** total across all nodes
- **joblib + parallel local search** — the coordinator distributes candidate schedule perturbations across workers, each of which scores the candidate against the macroscopic risk model
- Headliner slots can be locked in the Set Times interface; the optimizer only moves unlocked artists
- Returns the proposed schedule, risk score before/after, a list of changes, and a Claude-generated plain-text rationale explaining each move

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

cd backend
uvicorn main:app --reload --port 8000
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
  "density_red": 6.0
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
  "setlist": [...],
  "headliners": ["Artist A", "Artist B"],
  "sliders": { "max_capacity": 80000, "tickets_sold": 60000 }
}
```

**`POST /optimize_schedule` response:**
```json
{
  "proposed_schedule": [...],
  "risk_before": 0.82,
  "risk_after": 0.54,
  "changes": [{ "artist": "...", "from_stage": "...", "to_stage": "...", ... }],
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
Restrooms, water stations, and bars are displayed as interactive dots on the map. Click to select, drag to reposition. Their positions are forwarded to the Claude safety briefing, which will suggest specific moves to reduce wait times and distribute crowd load away from hotspots.

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

## Risk thresholds

| Density | Level |
|---------|-------|
| < 3 p/m² | Green — comfortable |
| 3–4 p/m² | Yellow — busy |
| 4–6 p/m² | Orange — caution |
| ≥ 6 p/m² or pressure spike | Red — crush risk |

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
| Parallelism | joblib — 44 cores across 7 VMs for schedule optimization |
| Storage | Redis (asyncio, project persistence) |
| AI | Anthropic Claude (schedule rationale and safety briefing) |
