# PLUR — Predictive Large-scale User Routing

Crowd-crush prediction and mitigation tool for multi-stage music festivals. PLUR simulates how an audience moves through a venue, identifies where and when dangerous density conditions form, and recommends barriers, staff placements, and schedule changes to reduce risk.

Built for the Ddoski's Lab + Anthropic + Most Technical hackathon tracks. Test venue: **HARD Summer 2025, Hollywood Park, Inglewood CA** (7 stages, ~80,000 attendees/day).

> **Disclaimer:** PLUR is a planning and decision-support prototype. It is not a validated or certified life-safety system.

---

## How it works

PLUR uses a two-tier simulation engine:

- **Macroscopic layer** — cheap analytic model covering the full event day. Computes per-stage population over time using artist draw scores and crowd migration, identifies risk windows (minutes where density is likely to spike).
- **Microscopic layer** — Helbing–Molnár social-force simulation run only on a chosen time window (~5,000 subsampled agents, each representing ~16 real people). Uses numba JIT + spatial hashing for performance.

Risk is defined as `density ρ (people/m²)` and `pressure P = ρ × var(local_velocity)`. Cells at `ρ ≥ 6` or with a pressure spike are flagged red.

---

## Architecture

```
Browser (localhost)
  React + deck.gl + MapLibre GL (Esri satellite tiles — no token required)
        ↕  HTTP / WebSocket
Backend (FastAPI, Python 3.12)
  ├── VenueLoader      GeoJSON → occupancy grid, UTM projection (EPSG:32611)
  ├── DemandService    Last.fm + Ticketmaster → artist draw + affinity matrix (cached)
  ├── MacroModel       Share-of-audience timeline, risk window detection
  ├── MicroSim         numba social-force engine with spatial hashing
  ├── RiskAnalyzer     Density/pressure → zones, hotspots
  ├── ScheduleOptimizer  Local search, parallel candidate scoring (joblib)
  ├── MitigationPlanner  Barrier/staff heuristics + parallel sim validation
  ├── PLURAgent        Claude-powered schedule rationale and safety briefing
  └── ProjectStore     Redis-backed project persistence
```

---

## Setup

### Prerequisites

- Python 3.12
- Node.js 18+
- Redis (running on `localhost:6379`)
- Last.fm API key (free at [last.fm/api](https://www.last.fm/api))
- Anthropic API key (for the Claude agent rationale endpoint)

### Backend

```bash
# Create and activate a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export LASTFM_API_KEY=your_key_here
export ANTHROPIC_API_KEY=your_key_here
export REDIS_URL=redis://localhost:6379   # default if omitted

# Start the server
cd backend
uvicorn main:app --reload --port 8000
```

Interactive API docs are available at `http://localhost:8000/docs` once running.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:5173`. The frontend proxies API calls to `http://localhost:8000`.

---

## API Endpoints

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Health check, returns version |

### Venues

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/venues` | List all venues with stage positions and bounding box |
| `GET` | `/venues/{venue_id}` | Full venue GeoJSON, grid metadata, stages, gates, facilities |

### Simulation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/demand` | Compute artist draw scores, affinity matrix, macro stage populations, and risk windows from a setlist |
| `POST` | `/simulate` | Run the micro-sim for a time window; returns agent frames (lon/lat), risk zones, and hotspots |
| `WS` | `/ws/simulate` | Same as `/simulate` but streams frames over WebSocket for real-time playback |

**`POST /demand` body:**
```json
{
  "setlist": [{ "artist": "string", "stage": "string", "start": "HH:MM", "end": "HH:MM" }],
  "region": "US"
}
```

**`POST /simulate` body:**
```json
{
  "venue_id": "hard_summer_2025",
  "setlist": [...],
  "stage_pop": { "hard": 12000 },
  "sliders": {
    "max_capacity": 80000,
    "tickets_sold": 75000,
    "arrival_steepness": 1.0,
    "n_agents": 5000
  },
  "window": { "t_start": 0, "t_end": 10 }
}
```

### Optimization

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/optimize_schedule` | Local-search schedule optimizer; returns proposed schedule, risk delta, and Claude-generated rationale |
| `POST` | `/suggest_mitigations` | Heuristic barrier and staff placement based on sim hotspots |

**`POST /optimize_schedule` body:**
```json
{
  "venue_id": "hard_summer_2025",
  "setlist": [...],
  "headliners": ["Artist A", "Artist B"],
  "sliders": { "max_capacity": 80000, "tickets_sold": 75000 }
}
```

**`POST /optimize_schedule` response:**
```json
{
  "proposed_schedule": [...],
  "risk_before": 0.82,
  "risk_after": 0.54,
  "changes": ["Moved Artist X from Pink 21:00 to Green 19:30 ..."],
  "rationale": "Claude-generated safety briefing..."
}
```

### Projects

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/projects` | List all saved projects |
| `POST` | `/projects` | Create a new project (name, GeoJSON, setlist, artists) |
| `GET` | `/projects/{id}` | Get a project by ID |
| `PUT` | `/projects/{id}` | Update project name, setlist, artists, or metadata |
| `DELETE` | `/projects/{id}` | Delete a project |

---

## Venue data

Venue files live under `backend/data/venues/<venue_id>/`:

```
venue.geojson   # FeatureCollection: walkable area, obstacles, stages, gates (WGS84)
meta.json       # name, origin_lonlat, utm_epsg, grid_cell_m, capacity
```

The bundled venue is `hard_summer_2025` (Hollywood Park, Inglewood CA). Adding a new venue is a matter of adding a new folder with these two files.

All coordinates in simulation math use **UTM Zone 11N (EPSG:32611)** in meters. The frontend receives lon/lat.

---

## Risk thresholds

| Density | Level |
|---------|-------|
| < 3 p/m² | Green — comfortable |
| 3–4 p/m² | Yellow — busy |
| 4–6 p/m² | Orange — caution |
| ≥ 6 p/m² **or** pressure spike | Red — crush risk |

Thresholds are configurable per-project via the control panel sliders.

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
| Parallelism | joblib (parallel schedule scoring and mitigation validation) |
| Storage | Redis (asyncio, project persistence) |
| AI | Anthropic Claude (schedule rationale and safety briefing) |
