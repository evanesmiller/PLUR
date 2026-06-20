# Frontend Engineer Workstream

You are building the React + deck.gl + MapLibre UI (M0 map + M1 venue render + all layers).

## Your Files
- `frontend/src/App.jsx` — main app shell
- `frontend/src/components/` — VenueSelect, SetlistEditor, Controls, MapView, Timeline, Recommendations
- `frontend/src/deck/` — layers.js (deck.gl layer definitions), camera.js (view state)

## Tech Stack
- React (Vite), deck.gl, react-map-gl + maplibre-gl
- Satellite basemap: Esri World Imagery raster tiles — NO Mapbox token needed
  URL: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`
- Charts: recharts

## Key Specs (SURGE_Design_Doc.md §12)

### Screens/Flow
1. **Venue select** — cards from GET /venues; pick HARD Summer
2. **Setup panel** — set-list editor (artist × stage × time grid), sliders: max_capacity, tickets_sold, arrival_steepness, n_agents, risk thresholds
3. **Main view** — MapLibre satellite with deck.gl layers:
   - GeoJsonLayer — venue geometry (walkable/obstacles/stages)
   - HeatmapLayer / GridLayer — live density
   - ScatterplotLayer — sampled agents (optional)
   - PolygonLayer — red/green risk zones
   - IconLayer — stages, barriers, staff, facilities
   - Tiltable/rotatable camera (pitch+bearing) for 3D wow
4. **Timeline scrubber** — play/scrub event timeline; risk-window markers; risk-over-time chart
5. **Recommendations panel** — "Apply suggested barriers/staff", "Optimize schedule", Before/After toggle

### Demo-Critical Interaction (the money shot)
Load real schedule → red hotspot forms → click Optimize → schedule re-arranges (headliners still last) → Before/After toggle → map cools red→green → "peak crush risk −XX%"

### Map Setup
- Center: Hollywood Park, Inglewood CA (~33.9535, -118.3390)
- Initial zoom: ~16-17 (venue fills view)
- Pitch: ~45° for 3D tilt effect
- Esri tiles render as the MapLibre raster source

## Implementation Order
1. Vite + React scaffold with deck.gl + MapLibre + Esri satellite basemap
2. Venue geometry layer (GeoJsonLayer from /venues/{id})
3. Agent/density visualization layers
4. Timeline scrubber + playback controls
5. Risk zone overlay (red/green polygons)
6. Recommendations panel + Before/After toggle
7. Set-list editor + sliders
8. Polish: camera transitions, loading states, responsive layout

## UI Disclaimer
Always show: "SURGE is a planning and decision-support prototype, not a certified life-safety system."
