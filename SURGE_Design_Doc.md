# SURGE — Design & Build Document
### Simulated Understanding of Risk in Gathering Events
*A crowd-crush prediction and mitigation tool for multi-stage music festivals.*

**Audience for this document:** Claude Code (and the human team) implementing the project from scratch during a ~24–36h hackathon.
**Test venue:** HARD Summer 2025, Hollywood Park grounds adjacent to SoFi Stadium, Inglewood CA (Aug 2–3 2025, 7 stages, ~80,000 attendees/day).

---

## 0. One-paragraph summary

SURGE lets a festival organizer load a scale venue map, optionally enter a set-list (which artist plays which stage at which time), and adjust event parameters (capacity, tickets sold, arrival profile). It simulates how the crowd moves through the day, predicts **where and when dangerous crowd-crush conditions form**, highlights red (danger) / green (safe) zones on a satellite map, and recommends **(a)** where to place physical barriers, **(b)** where to station staff, and **(c)** a safer artist schedule (re-arranging acts by stage and time to reduce crush, while keeping headliners in the final slots). Secondary features model restroom/water foot-traffic, recommend facility placement, and model a realistic ramping entry influx.

---

## 1. Critical design decisions & feasibility constraints (READ FIRST)

These decisions resolve real physical/compute limits. Do not "simplify" them away without understanding why they exist.

| # | Constraint | Decision |
|---|-----------|----------|
| 1 | Cannot render/simulate 80k discrete agents in real time. | Simulate a **subsample of N≈5,000–10,000 agents**, each representing `scale = real_headcount / N` people. Density and risk fields are multiplied by `scale`. |
| 2 | A continuous 8-hour micro-simulation is not interactive; one sim run is sequential in time so 44 cores don't accelerate a single run. | **Two-tier engine.** Macroscopic analytic layer covers the whole day cheaply and finds risk windows; microscopic social-force layer runs only on a chosen window (a few minutes of sim time). See §4. |
| 3 | "Optimal" barrier/staff/facility placement is combinatorial and cannot be globally optimized in the timeframe. | **Heuristic candidate generation** from simulation hotspots, then **parallel sim-validation** of top candidates across the 44 cores. Report as "recommended," not "optimal." |
| 4 | "Tickets sold" ≠ people present at time t. | Define `attendance(t) = tickets_sold × arrival_cdf(t)` from an arrival model (§4.3). Enforce `tickets_sold ≤ max_capacity`. |
| 5 | No real regional ticket-buyer data is publicly available. | Regional demand is an **estimate** from Last.fm `geo.getTopArtists` + similarity (§5). Label it as such in the UI. |
| 6 | This is not a certified life-safety system. | Surface a persistent disclaimer: *"SURGE is a planning and decision-support prototype, not a certified life-safety system."* |
| 7 | The 44-core ESXi VM is reachable from the venue via a **tested tunnel** (Tailscale). The browser runs on localhost. | Frontend served locally; all heavy compute (sim, optimizer) runs on the VM behind a FastAPI server reached over the tunnel. A surrogate model is a **deferred backup** only (§9). |

---

## 2. Goals (scope-tagged)

**Priority (MVP — must ship):**
- P1. Simulate the venue to scale and move agents through it realistically (social-force model). *(§4)*
- P2. Detect crush risk and render red/green zones; recommend staff and barrier placements. *(§4.5, §7)*
- P3. Build a regional artist demand index from a submitted set-list and recommend a safer schedule (headliners stay last). *(§5, §6)*

**Secondary (stretch — wire in only after MVP is solid):**
- S1. Model restroom/water foot-traffic as additional attractors with need-states and queues. *(§8.1)*
- S2. Recommend restroom/water placement. *(§8.2)*
- S3. Dynamic entry: time-varying influx that ramps toward high-demand sets. *(§4.3 — partially in MVP as the attendance curve; full per-gate dynamic spawn is the stretch.)*

---

## 3. System architecture

```
┌──────────────────────────── LOCALHOST (laptop) ────────────────────────────┐
│  Frontend: React + deck.gl + MapLibre GL (Esri World Imagery basemap)       │
│   • Venue select   • Set-list editor   • Sliders   • Timeline scrubber       │
│   • Layers: satellite, geometry, density heatmap, red/green zones,           │
│     barriers, staff, stages, facilities   • Before/After toggle              │
└───────────────▲──────────────────────────────────────────────┬─────────────┘
                │  HTTPS/WebSocket over Tailscale tunnel         │
┌───────────────┴──────────────── 44-CORE ESXi VM (Ubuntu) ─────▼─────────────┐
│  Backend: FastAPI (uvicorn)                                                  │
│   /venues  /demand  /simulate  /optimize_schedule  /suggest_mitigations      │
│                                                                              │
│  Services:                                                                   │
│   • VenueLoader        – reads GeoJSON + builds occupancy grid                │
│   • DemandService      – Last.fm/Ticketmaster → draw + affinity (cached)      │
│   • MacroModel         – share-of-audience per stage over time (fast)         │
│   • MicroSim           – numba/numpy social-force engine (spatial hashing)    │
│   • RiskAnalyzer       – density + pressure → zones, hotspots                 │
│   • ScheduleOptimizer  – local search, parallel candidate eval (joblib)      │
│   • MitigationPlanner  – barrier/staff/facility heuristics + sim validation   │
│   • (backup) Surrogate – emulates MicroSim if live latency demands            │
│                                                                              │
│  Parallelism: joblib/multiprocessing across 40 cores (leave 4 for headroom). │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Tech stack**
- **Frontend:** React (Vite), `deck.gl`, `react-map-gl` + `maplibre-gl`, satellite via Esri World Imagery raster tiles (`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` — **no token required**). Charts: `recharts`.
- **Backend:** Python 3.11, FastAPI, uvicorn, numpy, numba, scipy, shapely, pyproj, joblib, requests, pandas.
- **Data:** Last.fm API (primary), Ticketmaster Discovery API (secondary), cached to local JSON.
- **Tunnel:** Tailscale (already tested).
- **GIS authoring (offline):** QGIS and/or geojson.io + Google Earth Pro.

---

## 4. Simulation engine (two-tier)

### 4.1 Coordinate frames
- Venue stored as **GeoJSON in WGS84 (lon/lat)** for rendering.
- On load, project to a **local metric ENU frame** (meters) using `pyproj` (UTM Zone 11N, EPSG:32611, for Inglewood). Pick a venue origin; all sim math is in meters.
- Convert agent (x,y) meters → lon/lat for the frontend each frame.

### 4.2 Macroscopic layer (fast, whole-day)
Purpose: cheap timeline of "how many people are at each stage at each minute," used to (a) drive the day overview, (b) find risk windows, (c) score schedules in the optimizer.

For each time step `t` (e.g., 5-minute bins across the event hours):
```
attendance(t)          = tickets_sold × arrival_cdf(t)           # §4.3
draw_i                 = demand index per artist                 # §5
concurrent_sets(t)     = artists currently performing
share_s(t)             = softmax(draw over concurrent_sets)[stage s]
base_pop_s(t)          = attendance(t) × share_s(t)
migration_in_s(t)      = Σ_over_just-ended-sets j ( pop_j × affinity(j, current_s)
                                                    × distance_decay(stage_j, stage_s) )
stage_pop_s(t)         = base_pop_s(t) + migration_in_s(t)  (renormalized to attendance(t))
```
Output: `stage_pop[s][t]`, plus a **macro risk score** per (s,t) = `stage_pop_s(t) / safe_capacity(stage_area_s)`. Peaks above threshold = candidate risk windows.

### 4.3 Arrival / entry model (attendance curve)
`arrival_cdf(t)`: starts at gates-open, S-shaped, with the inflow rate rising toward the highest-demand sets. MVP form:
```
inflow_rate(t) ∝ Σ_artists draw_i × kernel(t − set_start_i)   # people arrive ahead of acts they want
arrival_cdf(t) = clamp(∫ inflow_rate / total, 0, 1)
```
Stretch (S3): distribute inflow across **multiple gates** as time-varying Poisson spawn points feeding the micro-sim.

### 4.4 Microscopic layer (social-force, per window)
Standard Helbing–Molnár–Vicsek social-force model. Default parameters (tune later):
- desired speed `v0 = 1.3 m/s` (σ 0.3), relaxation `τ = 0.5 s`
- agent–agent: `A = 2000 N`, `B = 0.08 m`; agent–wall same form with `A_w = 2000`, `B_w = 0.08`
- body radius `r = 0.25 m`, mass `m = 70 kg`
- physical contact terms (k, κ) enabled at high density for realistic pushing
- timestep `dt = 0.1–0.25 s`

**Performance musts:**
- **Spatial hashing / uniform grid** for neighbor lookup → O(N) not O(N²).
- **Vectorize with numpy; JIT the force loop with `numba`.**
- Subsample agents (N≈5–10k), apply `scale` to density.
- Simulate only the selected window (minutes), seeded from macro `stage_pop` and migration flows at that moment.

**Agent goals/attractors:** each agent has a current destination — a stage front (during sets), a gate (egress), or a facility (stretch S1). Destinations are drawn from the macro model's stage populations and migration flows for the window.

**Egress:** at set-end / event-end, retarget a fraction of agents to nearest exits; this is the highest-crush scenario and should always be one of the analyzed windows.

### 4.5 Risk metric (the core safety output)
Rasterize agents onto the occupancy grid (cell ≈ 1–2 m). Per cell:
```
density ρ      = (agent_count × scale) / cell_area          # people/m²
pressure P     = ρ × var(local_velocity)                    # crowd turbulence proxy
```
Zone classification (configurable):
- `ρ < 3` → green (comfortable)
- `3 ≤ ρ < 4` → yellow (busy)
- `4 ≤ ρ < 6` → orange (caution)
- `ρ ≥ 6` OR pressure spike → **red (crush risk)**

Output per window: time-series of the density & pressure fields, ranked **hotspots** (contiguous red cells), and per-stage peak risk.

---

## 5. Demand / popularity index (`DemandService`)

Input: set-list `[{artist, stage, start, end}]` + region (default: Los Angeles / Southern California).

**Sources (free; cache all responses to `/data/cache/*.json`):**
- **Last.fm (primary, key only):**
  - `artist.getInfo` → global listeners + playcount (broad reach)
  - `geo.getTopArtists` (country=US; treat as regional proxy) → local relevance boost
  - `artist.getSimilar` → pairwise affinity match score (0–1) → affinity matrix
  - `artist.getTopTags` → genre tags for genre-fit weighting
- **Ticketmaster Discovery (secondary, free, 5k/day):** venue capacities the artist headlines → live-demand proxy.
- **(Optional, do not depend on):** Bandsintown `tracker_count` is the ideal signal but access is gated; skip unless trivially available.

**Composite draw (z-score each term):**
```
draw_i = w1·streaming_reach + w2·local_boost + w3·venue_capacity_proxy
       + w4·momentum − w5·genre_mismatch
```
Default weights `w = [0.30, 0.25, 0.25, 0.10, 0.10]`; expose for tuning. `momentum` optional (Google Trends/pytrends, cached) — skip if time-constrained.

**Outputs:** `draw[artist]`, `affinity[i][j]`, both consumed by the macro model (§4.2) and the scheduler (§6).

**Calibration story (optional but high-value):** fit `w` so `draw` reproduces the billing-tier hierarchy of a few real festival posters (headliner > sub-headliner > undercard). Mention to judges as validation.

---

## 6. Schedule optimizer (`ScheduleOptimizer`)

**Decision variables:** assignment of artists → (stage, time-slot).
**Hard constraints:**
- Designated headliners occupy the final slot on their (or any) stage. (Honor user's "headliners last.")
- Each artist performs exactly once; no stage/slot double-booked; respect set durations.
**Objective:** minimize the day's **integrated + peak macro risk** (§4.2) — i.e., avoid two high-draw, high-affinity acts ending concurrently on distant stages, and avoid stacking big draws at one stage.

**Method (timeframe-appropriate):**
1. Start from the user's submitted schedule.
2. **Local search:** propose neighbor schedules via pairwise swaps (swap two artists' slots/stages).
3. Score each candidate with the **macro model** (cheap, milliseconds).
4. **Parallelize candidate scoring across 40 cores** (`joblib.Parallel(n_jobs=40)`).
5. Greedily accept improving swaps; iterate to a local optimum (optionally wrap in a small genetic algorithm if time allows).
6. Validate the final recommended schedule with one **micro-sim** of its worst window for a credible before/after number.

**Output:** `proposed_schedule`, `risk_before`, `risk_after`, and a human-readable list of the key changes ("moved Artist X from Pink Stage 21:00 to Green Stage 19:30 to de-conflict with headliner egress").

> **Anthropic-track hook:** wrap step 6 + the explanation generation in a **Claude-powered agent** that reasons over the schedule and writes the rationale + safety briefing. Built with Claude Code.

---

## 7. Mitigation planner — barriers & staff (`MitigationPlanner`)

From a micro-sim's hotspots and velocity field:

**Barriers (flow management):**
- Identify chokepoints: cells with high pressure **and** high velocity-variance / converging flow.
- Propose barrier **segments placed to split or redirect** opposing/merging flows (orient perpendicular to the dominant local flow gradient; e.g., lane dividers at a bottleneck, funnel barriers ahead of a stage front).
- **Validate:** insert each candidate barrier as a new wall obstacle, re-run the window sim, keep configurations that reduce peak `ρ`/pressure. Evaluate candidates **in parallel across cores**.

**Staff placement:**
- Rank cells by risk (peak `ρ`×pressure × dwell-time).
- Place staff markers at the top-N risk cells and at egress chokepoints, spaced by a coverage radius so they don't cluster.
- Output as map markers with a short reason each.

**Scope note:** heuristic candidates + sim-validation of the top few — not exhaustive optimization. State this in the UI ("recommended placements," with the simulated risk reduction shown).

---

## 8. Secondary goals (stretch)

### 8.1 Restroom/water foot-traffic
- Give each agent a slowly-accumulating `need` state; above threshold, retarget to nearest facility, queue (capacity-limited), then return toward their stage.
- Adds realistic cross-traffic that can itself create bottlenecks — surface this in the risk field.

### 8.2 Facility placement recommendation
- Same heuristic+validate pattern: propose facility locations that minimize added cross-traffic congestion (place near demand but off primary flow corridors), validate by sim.

### 8.3 Full dynamic per-gate entry
- Upgrade §4.3 from a single attendance curve to **multiple gates with time-varying Poisson spawn**, ramping toward high-demand sets, so ingress crush is modeled spatially.

---

## 9. Surrogate model (DEFERRED BACKUP — do not build first)

Only if live micro-sim latency is unacceptable or you need laptop-local fallback independent of the VM:
- Generate training data by running the micro-sim across many (layout, schedule, slider) combos — **embarrassingly parallel on 44 cores** (`joblib`, ~44× speedup).
- Train a **gradient-boosted model (XGBoost/LightGBM)** — CPU-friendly, fast, no GPU needed (ESXi VM has no GPU passthrough by default) — to predict the risk/density field from inputs.
- Swap it in where the optimizer or mitigation loop calls the sim, and ship it with the frontend as an offline fallback.

---

## 10. Backend API (FastAPI)

```
GET  /venues
       → [{id, name, bbox, stages:[{id,name,lonlat}], gates:[...], thumbnail}]

GET  /venues/{id}
       → full GeoJSON (walkable, obstacles, stages, gates, facilities) + grid meta

POST /demand
     body: { setlist:[{artist,stage,start,end}], region }
       → { draw:{artist:score}, affinity:[[...]], stage_pop:{stage:[{t,pop}]},
           risk_windows:[{t_start,t_end,stage,score}] }   (cached)

POST /simulate
     body: { venue_id, setlist|stage_pop, sliders:{capacity,tickets_sold,arrival,...},
             window:{t_start,t_end}, n_agents }
       → { frames:[{t, agents:[[lon,lat,vx,vy]], density_grid, pressure_grid}],
           zones:[{polygon, level}], hotspots:[{cell, peak_density, peak_pressure}] }
     (stream via WebSocket for playback)

POST /optimize_schedule
     body: { venue_id, setlist, headliners:[artist...], sliders }
       → { proposed_schedule, risk_before, risk_after, changes:[...], rationale }

POST /suggest_mitigations
     body: { venue_id, window, sliders, setlist|stage_pop }
       → { barriers:[{segment, reason, risk_reduction}],
           staff:[{point, reason}],
           facilities:[{point, reason}]  # stretch }
```

---

## 11. Venue map authoring (offline, done by humans before/early)

**Format produced:** one folder per venue under `/data/venues/<venue_id>/`:
```
venue.geojson      # FeatureCollection: walkable (Polygon), obstacles (Polygons),
                   #   stages (Points w/ name+orientation), gates (Points),
                   #   facilities (Points)  — all WGS84 lon/lat
meta.json          # {name, origin_lonlat, utm_epsg:32611, grid_cell_m, scale_ref}
```
Backend derives the **occupancy grid** (rasterized walkable−obstacles) at load.

**Build pipeline for HARD Summer 2025 (the one demo map):**
1. Get the **official 2025 festival map** (released pre-event: 7 stages incl. relocated Pink Stage, gates, bars, art installations) for semantic placement.
2. Open Google Earth Pro at **1011 Stadium Dr, Inglewood** for satellite ground-truth + scale.
3. In **QGIS** (or geojson.io for speed): trace the walkable boundary, obstacles (SoFi structure, fences, bar/vendor rows, stage back-of-house), and points (7 stages, gates, facilities). Pull SoFi/Forum/lots from OpenStreetMap (`osmnx`) to save tracing.
4. **Calibrate scale** against a known real distance (measure a lot edge / stadium in Google Earth; confirm traced distances match).
5. Export `venue.geojson` (WGS84) + `meta.json`.

**Accuracy checklist:** scale verified; gate/exit positions exact (egress = crush hotspot); inter-stage walkway widths correct (bottleneck driver); stage fronts oriented correctly.

**Modularity:** the loader reads any venue folder, so adding venues = adding folders. The venue-select UI lists everything in `/data/venues/`.

---

## 12. Frontend / UX (deck.gl + MapLibre)

> Build the UI following the `frontend-design` skill (`/mnt/skills/public/frontend-design/SKILL.md`).

**Screens/flow:**
1. **Venue select** — cards from `/venues`; pick HARD Summer.
2. **Setup panel** — optional set-list editor (artist × stage × time grid pre-filled with the real HARD Summer 2025 schedule); sliders: `max_capacity`, `tickets_sold`, `arrival_steepness`, `n_agents`, risk thresholds.
3. **Main view** — MapLibre satellite (Esri tiles) of Hollywood Park with deck.gl layers:
   - `GeoJsonLayer` — venue geometry (walkable/obstacles/stages).
   - `HeatmapLayer` / `GridLayer` — live density; or `ScatterplotLayer` for sampled agents.
   - `PolygonLayer` — red/green zones.
   - `IconLayer` — stages, recommended barriers, staff, facilities.
   - **Tilt/rotate camera** (pitch+bearing) for the 3D-ish wow.
4. **Timeline scrubber** — play/scrub the event; risk-window markers highlighted; risk-over-time chart (recharts).
5. **Recommendations panel** — "Apply suggested barriers/staff" and **"Optimize schedule"**; a **Before/After toggle** that swaps the schedule and re-colors the map (the money shot: red → green, with "peak crush risk −XX%").

**Demo-critical interaction:** load the real HARD Summer schedule → map shows a red hotspot at a known choke moment (e.g., two big sets ending on adjacent stages) → click *Optimize* → schedule re-arranges (headliners still last) → map cools to green → headline number drops.

---

## 13. Parallelism on the 44-core VM

- **Schedule optimizer:** `joblib.Parallel(n_jobs=40)` over candidate schedules (macro scoring).
- **Mitigation validation:** parallel re-sims of barrier/facility candidates.
- **Surrogate data gen (if built):** parallel sim runs.
- Leave ~4 cores for FastAPI + OS. Confirm `nproc == 44`; size RAM for parallel sims.
- A single micro-sim run stays on one core but is fast via numba + spatial hashing; parallelism is for *many* runs.

---

## 14. Repository structure

```
surge/
├── backend/
│   ├── main.py                 # FastAPI app + routes
│   ├── venue/loader.py         # GeoJSON → grid, pyproj transforms
│   ├── demand/service.py       # Last.fm/Ticketmaster + composite index (cached)
│   ├── sim/macro.py            # share-of-audience timeline
│   ├── sim/micro.py            # numba social-force engine + spatial hash
│   ├── sim/risk.py             # density/pressure → zones, hotspots
│   ├── optimize/schedule.py    # local search + joblib parallel scoring
│   ├── optimize/mitigation.py  # barrier/staff/facility heuristics + validation
│   ├── agent/claude.py         # Claude-powered rationale/briefing (Anthropic track)
│   └── data/
│       ├── venues/hard_summer_2025/{venue.geojson,meta.json}
│       └── cache/*.json
├── frontend/
│   ├── src/App.jsx
│   ├── src/components/{VenueSelect,SetlistEditor,Controls,MapView,Timeline,Recommendations}.jsx
│   └── src/deck/{layers.js, camera.js}
├── scripts/
│   ├── build_venue.py          # GIS export helper
│   └── gen_surrogate_data.py   # (deferred) parallel sim data gen
├── requirements.txt
└── README.md
```

---

## 15. Build sequence / milestones

- **M0 – Scaffolding (first):** repo, FastAPI hello-world on VM reachable via tunnel, React+deck.gl+MapLibre showing Esri satellite over Hollywood Park.
- **M1 – Venue:** author `hard_summer_2025` GeoJSON; loader → grid; render geometry on the map.
- **M2 – Micro-sim:** social-force engine (numba + spatial hash); agents flow to stage fronts; render sampled agents + density heatmap for one window.
- **M3 – Risk:** density/pressure fields → red/green zones + hotspots; timeline scrubber + risk chart.
- **M4 – Demand:** Last.fm/Ticketmaster service (cached) → draw + affinity; macro model → stage_pop timeline; auto-detect risk windows; feed micro-sim seeding.
- **M5 – Scheduler:** local-search optimizer (parallel) honoring headliners-last; Before/After toggle + risk delta.
- **M6 – Mitigations:** barrier + staff heuristics with parallel sim-validation; render markers + simulated risk reduction.
- **M7 – Anthropic agent:** Claude-generated schedule rationale + safety briefing.
- **M8 – Secondary (if time):** restroom/water traffic (S1), facility placement (S2), dynamic per-gate entry (S3).
- **M9 – Polish & demo:** pre-load the killer scenario; record backup video; rehearse before/after.

**MVP line = end of M6.** Everything after is upside.

---

## 16. Suggested team split

- **Sim engineer:** M2/M3 micro-sim + risk (the technical core).
- **Data/ML engineer:** M4/M5 demand index + scheduler + (deferred) surrogate.
- **Frontend engineer:** M0/M1 map + all deck.gl layers + timeline + recommendations UI.
- **Integration/infra (floats):** FastAPI + tunnel + parallelism + M6 mitigations + M7 Claude agent + demo.

---

## 17. Demo script (≈3 min)

1. *(15s)* Venue select → HARD Summer 2025 on satellite Hollywood Park; tilt the camera. "Real venue, to scale."
2. *(30s)* Load the **real** 2025 schedule + set sliders to the real ~80k/day. Play timeline.
3. *(30s)* A **red hotspot** forms at a real choke moment (adjacent big sets ending / egress). Zoom in; show density + pressure.
4. *(30s)* Click **Suggest mitigations** → barriers + staff appear; show simulated risk reduction.
5. *(45s)* Click **Optimize schedule** → acts re-arrange (headliners still last) → **Before/After toggle** → map cools red→green; headline "peak crush risk −XX%."
6. *(20s)* Show the **Claude-generated safety briefing** explaining the changes.
7. *(10s)* "Modular — any venue is just another map file." Done.

---

## 18. Track alignment

- **Ddoski's Lab (main):** technically deep engineering safety system — social-force sim + risk model + optimization.
- **Anthropic:** built with Claude Code; Claude agent reasons over schedules and writes the safety briefing; a real public-safety swing.
- **Most Technical:** the live agent-based simulation on a 44-core backend, two-tier engine, parallel optimization.
- **Byproducts to nudge:** Best UI/UX (the deck.gl before/after map), Hacker's Choice (festival framing is fun), SkyDeck (clear B2B product for venues/festivals/insurers).

---

## 19. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Micro-sim too slow live | Subsample agents; numba+spatial hash; sim only the chosen window; surrogate backup. |
| Demand API rate limits / downtime | Pre-pull and cache to JSON; never call live during the demo. |
| Optimizer finds weak/no improvement | Seed the demo with a deliberately bad real schedule so improvement is visible; tune weights against billing hierarchy. |
| Scope creep (secondary goals) | Hard MVP line at M6; secondary only after. |
| Network/tunnel issue at venue | Tunnel pre-tested; keep surrogate + pre-rendered demo scenario as laptop-local fallback. |
| Over-claiming safety accuracy | Persistent "decision-support prototype, not certified" disclaimer; present numbers as relative estimates. |

---

## 20. Ethical note
SURGE is a planning and decision-support prototype that produces **relative risk estimates** to help organizers reason about crowd safety. It is **not** a validated or certified life-safety system and must not be presented as one. Keep this framing in the UI and the pitch.
