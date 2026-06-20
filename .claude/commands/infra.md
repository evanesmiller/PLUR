# Integration/Infra Workstream

You are handling FastAPI + cluster + mitigations + Claude agent (M0 API + M6 + M7).

## Your Files
- `backend/main.py` — FastAPI app + all routes
- `backend/venue/loader.py` — GeoJSON → occupancy grid, pyproj transforms
- `backend/optimize/mitigation.py` — barrier/staff/facility heuristics + sim validation
- `backend/agent/claude.py` — Claude-powered rationale + safety briefing
- `scripts/build_golden.sh` — golden VM provisioning
- `scripts/clone_init.sh` — clone initialization

## Key Specs

### FastAPI Routes (SURGE_Design_Doc.md §10)
```
GET  /venues → list of venues with metadata
GET  /venues/{id} → full GeoJSON + grid meta
POST /demand → draw scores + affinity + stage_pop + risk_windows
POST /simulate → frames with agents, density/pressure grids, zones, hotspots (WebSocket stream)
POST /optimize_schedule → proposed_schedule + risk_before/after + rationale
POST /suggest_mitigations → barriers + staff + facilities with reasons + risk_reduction
```

### Venue Loader (§11)
- Input: /data/venues/<venue_id>/venue.geojson + meta.json (WGS84)
- Reproject to UTM (EPSG from meta.json) for sim math
- Rasterize walkable−obstacles into occupancy grid
- Output: grid array, coordinate transforms, stage/gate/facility positions in meters

### Mitigation Planner (§7)
- Barriers: identify chokepoints (high pressure + velocity variance), propose segments perpendicular to flow gradient, validate by re-sim in parallel
- Staff: rank cells by risk (peak ρ×pressure×dwell-time), place at top-N + egress chokepoints, spaced by coverage radius
- Report as "recommended" with simulated risk reduction

### Claude Agent (§6 Anthropic track hook)
- Takes optimizer output + schedule changes
- Generates human-readable rationale for schedule changes
- Writes safety briefing document
- Built with Claude Code (Anthropic track requirement)

### Cluster (§4 of handoff)
- Ubuntu 26.04 LTS, Miniforge, Python 3.12 env (name: surge)
- Golden VM + clone workflow
- Dask scheduler on coordinator, workers on clones
- 8 vCPUs per host, ~40-44 total cores
- Single-host must work correctly; cluster is throughput boost

## Implementation Order
1. FastAPI skeleton with stub routes
2. Venue loader (GeoJSON parse + UTM projection + grid rasterization)
3. WebSocket streaming for simulation frames
4. Mitigation planner (after micro-sim is ready)
5. Claude agent integration
6. Cluster provisioning scripts
