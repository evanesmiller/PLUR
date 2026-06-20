# Data/ML Engineer Workstream

You are working on the demand index, macro model, and schedule optimizer (M4/M5).

## Your Files
- `backend/demand/service.py` — Last.fm + Ticketmaster API client (cached to JSON)
- `backend/sim/macro.py` — share-of-audience timeline model
- `backend/optimize/schedule.py` — local-search schedule optimizer with parallel scoring

## Key Specs

### Demand Service (SURGE_Design_Doc.md §5)
- Last.fm API (primary, key only, NO OAuth):
  - artist.getInfo → global listeners/playcount
  - geo.getTopArtists (country=US) → regional proxy
  - artist.getSimilar → pairwise affinity 0-1 → affinity matrix
  - artist.getTopTags → genre tags
- Ticketmaster Discovery API (secondary, free, 5k/day): venue capacities
- Cache ALL responses to /data/cache/*.json
- DO NOT use Spotify (deprecated), Songkick (closed), Bandsintown (gated)

### Composite Draw
```
draw_i = w1·streaming + w2·local_boost + w3·venue_capacity_proxy + w4·momentum − w5·genre_mismatch
```
Default weights: [0.30, 0.25, 0.25, 0.10, 0.10]. Expose for tuning.
Normalize to share of concurrent audience via softmax.

### Macro Model (§4.2)
```
attendance(t) = tickets_sold × arrival_cdf(t)
share_s(t) = softmax(draw over concurrent_sets)[stage s]
base_pop_s(t) = attendance(t) × share_s(t)
migration_in_s(t) = Σ (pop_j × affinity(j,current_s) × distance_decay(stage_j, stage_s))
stage_pop_s(t) = base_pop_s(t) + migration_in_s(t)  # renormalized
```
Output: stage_pop[s][t] + macro risk score per (s,t).

### Schedule Optimizer (§6)
- Decision variables: artist → (stage, time-slot)
- Hard constraints: headliners in final slots, no double-booking, respect durations
- Objective: minimize integrated + peak macro risk
- Method: local search with pairwise swaps, parallel scoring via joblib
- Validate final schedule with one micro-sim of worst window
- Output: proposed_schedule, risk_before, risk_after, changes list, rationale

## Implementation Order
1. DemandService with Last.fm client + caching
2. Composite draw calculation + affinity matrix
3. Macro model (share-of-audience + migration)
4. Arrival CDF model
5. Schedule optimizer (local search + parallel scoring)
6. Integration with micro-sim for final validation
