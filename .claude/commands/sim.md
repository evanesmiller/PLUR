# Sim Engineer Workstream

You are working on the simulation engine — the technical core of SURGE (M2/M3).

## Your Files
- `backend/sim/micro.py` — numba social-force engine + uniform-grid spatial hashing
- `backend/sim/risk.py` — density/pressure fields → zone classification + hotspots

## Key Specs (from SURGE_Design_Doc.md §4)

### Microscopic Social-Force Model (Helbing–Molnár–Vicsek)
- Parameters: v0=1.3 m/s (σ 0.3), τ=0.5s, A=2000N, B=0.08m, r=0.25m, m=70kg
- Physical contact terms (k, κ) at high density
- dt = 0.1–0.25s
- Subsample N≈5,000–10,000 agents, each representing scale = real_headcount/N

### Performance Requirements
- Spatial hashing / uniform grid for O(N) neighbor lookup — NOT O(N²)
- Vectorize with numpy; JIT the force loop with numba
- Simulate only the selected window (minutes), seeded from macro stage_pop

### Risk Metric (§4.5)
- Rasterize onto occupancy grid (cell ≈ 1-2m)
- density ρ = (agent_count × scale) / cell_area [people/m²]
- pressure P = ρ × var(local_velocity) [crowd turbulence proxy]
- Zones: ρ<3 green, 3-4 yellow, 4-6 orange, ρ≥6 OR pressure spike = RED

### Agent Goals
- Current destination: stage front (during sets), gate (egress), facility (stretch)
- Egress at set-end: retarget fraction to nearest exits — highest-crush scenario
- Destinations drawn from macro model's stage populations + migration flows

## Implementation Order
1. Spatial hash grid (uniform grid, cell size ≈ 2×interaction radius)
2. Social-force computation (numba JIT) — repulsion + driving force + wall forces
3. Agent state management (position, velocity, destination, scale)
4. Risk field computation (density + pressure per grid cell)
5. Zone classification + hotspot detection (contiguous red cells)
6. Integration with venue loader (walls = obstacles from GeoJSON)

All math in meters (UTM projection). The venue loader handles coordinate transforms.
