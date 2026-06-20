# HARD Summer 2025 — Venue Data Reference

## Feature Types in `venue.geojson`

### Polygons

| `type` | `subtype` | Sim behavior | Description |
|--------|-----------|-------------|-------------|
| `walkable` | — | Defines the area where agents can exist | Outer festival boundary. Traced from the official 2025 map. |
| `obstacle` | `structure` | Blocks agent movement | Permanent structures (SoFi Stadium). Agents pathfind around these. |
| `obstacle` | `terrain` | Blocks agent movement | Natural features (Rivers Lake). |
| `obstacle` | `barrier` | Blocks agent movement | **Fencing/barricades between north and south sections.** The gap between the two barriers is the only passageway connecting the north (HARD/Pink) area to the south (HARDER/Green) area. This bottleneck is a primary crush-risk location. |
| `obstacle` | `stage_boh` | Blocks agent movement | Back-of-house areas behind each stage. Production, artist access, equipment. No GA access. |
| `obstacle` | `bar` | Blocks agent movement | Bar structures. Small physical barriers that agents route around. Also act as attractors (people stop here). |
| `obstacle` | `vendor` | Blocks agent movement | Vendor stalls / food trucks (e.g., Locals Only Ice Cream Truck). Physical barriers + minor attractors. |
| `vip_area` | — | Blocks GA agent movement | VIP-only sections adjacent to stages. The sim treats these as obstacles for GA agents (vast majority of the ~80k crowd). VIP attendees (~5-10% of capacity) are inside but do not mix with GA flow. The sim can optionally model reduced-density crowd inside VIP zones. |
| `gate_area` | — | Visual only (not used by sim) | Physical footprint of the entrance/exit structure. The sim uses the `gate` point, not this polygon. |

### Points

| `type` | Properties | Sim behavior |
|--------|-----------|-------------|
| `stage` | `stage_id`, `orientation` (degrees, 0=N), `capacity_area_m2` | **Agent destination.** Agents are attracted to stage fronts during sets. `orientation` indicates which direction the audience faces. |
| `gate` | `gate_id`, `capacity_pph` | **Agent spawn/exit point.** All agents enter and leave through this single point. Egress through one gate is a major crush scenario. |
| `facility` | `facility_id`, `facility_type` (`water` or `restroom`) | **Secondary attractor (stretch goal S1).** Agents with accumulated need-states detour to these, creating cross-traffic. Not used in MVP sim. |

## Venue Layout

```
                   ┌─────────────────────────┐
                   │  HARD     VIP    Pink    │  ← North section
                   │  Stage  (shared) Stage   │
                   ├─ BOH ─── bars ── BOH ────┤
                   │     ↓ passage gap ↓      │
              ┌────┤ [barrier]   [barrier]    │
   Purple     │    │         SoFi             │
   Stage ← ──┤VIP │        Stadium           │  ← East corridor
   (BOH)      │    │       (obstacle)         │     (narrow)
              └────┤                          │
                   │  Rivers Lake (obstacle)  │
                   ├──────────────────────────┤
                   │ HARDER    VIP   Green    │  ← South section
                   │ Stage   areas   Stage    │
                   │  (BOH)          (BOH)    │
                   │         [entrance/exit]──│→ S Prairie Ave
                   └──────────────────────────┘
```

The two "Barrier" obstacles between the north and south sections create a single passageway near the HARD Stage side. This is the primary bottleneck for crowd movement between sections and the most likely crush-risk point when large sets end simultaneously on opposite sides.

## Key Distances

Run `python3 -c "from backend.venue.loader import load_venue; ..."` to compute current inter-stage distances after any coordinate edits. Critical metric: the width of the north-south passageway gap between the two barriers.
