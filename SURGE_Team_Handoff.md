# SURGE — Team Handoff & Onboarding
*Crowd-crush prediction & mitigation tool for multi-stage music festivals.*
*Hackathon project. This doc lets a teammate pick up the work cold, using their own Claude account.*

---

## 0. Read this first (5-minute orientation)

**What we're building:** A tool where a festival organizer loads a scale venue map, optionally enters the set-list (artist × stage × time), tweaks event sliders (capacity, tickets sold, arrival profile), and the app **simulates crowd movement, predicts where/when crowd-crush danger forms, highlights red/green zones, and recommends barrier placements, staff placements, and a safer artist schedule** (keeping headliners last). Test venue: **HARD Summer 2025, Hollywood Park (Inglewood, CA), 7 stages, ~80k/day.**

**Read order to get up to speed:**
1. This handoff (decisions + status + how to continue).
2. `SURGE_Design_Doc.md` — the full engineering spec (architecture, API, repo layout, milestones M0–M9, parameters). **This is the source of truth for implementation.**

**Tracks we're targeting:** Ddoski's **Lab** (main) + **Anthropic** (built with Claude Code; Claude agent writes the safety briefing) + **Most Technical** (live agent-based sim on a distributed backend). Likely byproducts: Best UI/UX, Hacker's Choice, SkyDeck.

---

## 1. Current status

| Area | State |
|------|-------|
| Concept & scope | ✅ Locked (this doc + design doc) |
| Design document | ✅ Done (`SURGE_Design_Doc.md`) |
| Popularity/data stack | ✅ Decided & validated (see §3) |
| Compute infra plan | ✅ Decided: distributed Dask cluster on ESXi (see §4) |
| Golden VM build commands | ✅ Written (in the source chat / to be saved as `build_golden.sh`) |
| Venue map (HARD Summer) | ⬜ Not started — needs manual GIS authoring (see §5) |
| Code (backend/frontend) | ⬜ Not started — M0 scaffold is the next build step |
| API keys (Last.fm, Ticketmaster) | ⬜ TODO — register early (free) |
| Headliner designation | ⬜ TODO — needed as optimizer constraint |

**Next build step:** M0 scaffold — FastAPI hello-world on the coordinator (reachable via tunnel) + React/deck.gl/MapLibre showing the Esri satellite basemap over Hollywood Park.

---

## 2. Decision log (the "why" — don't re-litigate these)

These were worked out deliberately. Changing them without understanding the reason will cost you.

- **Problem choice — festival crowd-crush + safety-aware scheduling.** Picked over wildfire/disease/flood because those problems are *saturated* (thousands of existing repos). Crowd-crush is original; judges have no reference point. Chosen over a generic crowd sim by adding the **artist-demand-driven scheduling** axis, which nobody builds.
- **Two-tier simulation engine (the most important decision).** You cannot simulate 80k discrete agents in real time, and a continuous 8-hour social-force sim isn't interactive (one sim run is sequential in time, so cores don't speed up a single run). Solution: a **fast macroscopic layer** (share-of-audience demand model → per-stage crowd over the whole day → finds risk windows) feeding a **detailed microscopic social-force layer** that runs only on a chosen window with a **subsampled crowd (~5–10k agents scaled up)**.
- **Real sim first; surrogate is a deferred backup, NOT the foundation.** The two-tier design + the cluster already cover every place latency could hurt (optimizer scores candidates with the cheap macro model, not the sim). "We run the full agent-based simulation live" is a stronger Most-Technical story than "we trained an emulator," with no approximation to defend. A surrogate (gradient-boosted, CPU-friendly) is kept only as (a) a laptop-local fallback and (b) an option for instant slider interactivity. Build it only after MVP.
- **Frontend = deck.gl + MapLibre GL with free Esri World Imagery satellite tiles** (`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` — **no Mapbox token needed**). The sim is computed in 2D; deck.gl renders it over the real satellite map with a **tiltable/orbitable camera** for the 3D "wow" at a fraction of the cost of hand-built three.js. The density heatmap (the actual safety output) reads best from this view.
- **"Optimal" placements are heuristic, not globally optimized.** Barriers/staff/facilities: generate candidates from sim hotspots, then validate the top few by re-simulation in parallel. Report as "recommended," not "optimal."
- **Crush metric = density + pressure.** Risk isn't headcount; it's local density (people/m²) combined with crowd "pressure" (density × local velocity variance — crowd turbulence). Red zone ≈ ρ ≥ 6 or a pressure spike. (Full thresholds in design doc §4.5.)
- **Framing = decision-support prototype, not a certified life-safety system.** Keep this disclaimer in the UI and pitch — ethically required and protects credibility.

---

## 3. Popularity / demand data stack (validated — important: don't reach for Spotify)

We need a *regional artist demand* estimate to drive crowd sizes and the scheduler. We validated every source:

- **❌ Spotify Related Artists / Recommendations / Audio Features — DEAD for new apps** (deprecated Nov 27 2024; a freshly registered hackathon app gets 403/404). Do not build on these.
- **✅ Last.fm API (PRIMARY — free, API key only, no OAuth):**
  - `artist.getInfo` → global listeners/playcount (reach)
  - `geo.getTopArtists` (country=US) → regional-popularity proxy
  - `artist.getSimilar` → pairwise fan-affinity score 0–1 (drives migration waves)
  - `artist.getTopTags` → genre tags for genre-fit weighting
- **✅ Ticketmaster Discovery API (secondary — free, 5k calls/day):** venue capacities an artist headlines = live-demand proxy. (Note: it does **not** expose ticket-sales counts or buyer ZIPs — that data isn't public anywhere. Regional demand is an *estimate*.)
- **❌ Songkick / Soundcharts — closed/paid**, not hackathon-feasible.
- **⚠️ Bandsintown `tracker_count`** is the ideal concert-demand signal but API access is gated and explicitly denied to student projects. Treat as optional bonus; don't depend on it.
- **⚠️ AnyLogic / Oasys MassMotion (pro crowd-sim tools) — DO NOT USE.** MassMotion is ~£20k + needs Autodesk Softimage. We build our own social-force model (free, and a better technical story).

**Cache every API response to JSON.** The lineup is fixed, so never call these live during the demo.

**Composite draw (z-score each term):** `draw = w1·streaming + w2·local_boost + w3·venue_capacity_proxy + w4·momentum − w5·genre_mismatch`, then normalize to **share of concurrent audience** (softmax over simultaneous sets) + migration inflow weighted by affinity × inverse stage-distance. Optional calibration: tune weights so `draw` reproduces real festival **billing-tier hierarchy** (headliner > undercard).

---

## 4. Compute infra & environment

**Cluster topology (licensing: max 8 cores per host, multiple hosts up to ~44 total):**
- 5–6 ESXi VMs, **8 vCPUs each** (5×8=40 or 6 hosts for full budget).
- **1 coordinator** = FastAPI + Dask scheduler + Tailscale tunnel to the laptop. The rest are **workers**.
- All heavy work is embarrassingly parallel (independent sim runs, candidate-schedule scores, barrier-validation sims) → distribute with **Dask distributed** (`dask scheduler` / `dask worker --nworkers 8 --nthreads 1`).
- **The live single-window sim runs on one core of the coordinator** — interactivity is unaffected by the per-host limit.
- **It must run correctly on a single 8-core host.** The cluster is a throughput boost (search more candidates), not a correctness requirement. Build/demo single-host first; add the cluster as enhancement.

**OS / Python (critical gotcha):**
- **Ubuntu Server 26.04 LTS** (headless). Runs fine on ESXi with `open-vm-tools`.
- 26.04 ships **Python 3.14 by default** — the newest, least-tested with our stack. numba only gained 3.14 support in v0.63 (Dec 2025).
- **DO NOT build on system Python.** Use **Miniforge** to create a pinned **Python 3.12** env (`name: surge`) — mature, battle-tested wheels for numba/numpy/scipy/shapely/pyproj/dask/fastapi. Don't touch `/usr/bin/python3` (system tools need 3.14).
- **Cluster consistency is mandatory:** Dask needs identical Python + lib versions on every node. Build **one golden VM**, lock the env, **clone it** for all hosts.

**The env (`environment.yml`):**
```yaml
name: surge
channels: [conda-forge]
dependencies:
  - python=3.12
  - numpy
  - scipy
  - pandas
  - numba
  - llvmlite
  - shapely
  - pyproj
  - dask
  - distributed
  - pyarrow
  - fastapi
  - uvicorn
  - websockets
  - requests
  - joblib
  - python-dotenv
  - pip
```

**Provisioning summary** (full command sequence is in the source chat; ask Claude to regenerate `build_golden.sh` + `clone_init.sh`):
1. Golden VM: `apt update && apt full-upgrade -y`; install `open-vm-tools git build-essential tmux`; install Miniforge; `conda env create -f environment.yml`; verify numba JIT compiles; `conda env export > environment.lock.yml`.
2. Generalize before shutdown: clear `/etc/machine-id`, remove `/etc/ssh/ssh_host_*`, `cloud-init clean`, shut down. Keep on DHCP.
3. Clone on standalone ESXi with **`ovftool`** (export golden VM to OVA, deploy N copies — it regenerates UUIDs/MACs).
4. Per clone: set unique hostname, regenerate machine-id/SSH keys, point `/etc/surge.env` `DASK_SCHEDULER` at the coordinator IP. Start `dask scheduler` on coordinator, `dask worker` on each worker. Dashboard at `http://<coordinator>:8787` (nice live visual for the demo).

---

## 5. Venue map pipeline (HARD Summer 2025 — the one demo map)

Format: `/data/venues/hard_summer_2025/{venue.geojson, meta.json}` (WGS84 lon/lat; backend reprojects to UTM 11N / EPSG:32611 meters for the sim, rasterizes an occupancy grid).

Steps:
1. Get the **official 2025 festival map** (released pre-event: 7 stages incl. relocated Pink Stage, gates, bars, art) for semantic placement.
2. Google Earth Pro at **1011 Stadium Dr, Inglewood** for satellite footprint + scale.
3. Trace in **QGIS** (or geojson.io): walkable boundary, obstacles (SoFi structure, fences, bar/vendor rows, stage back-of-house), points (stages, gates, facilities). Pull permanent structures from OpenStreetMap via `osmnx`.
4. **Calibrate scale** against a known real distance (density thresholds are meaningless if the map isn't to scale).
5. Get gate/exit positions exact (egress = crush hotspot) and inter-stage walkway widths right (bottleneck driver).

Modularity: the loader reads any venue folder → adding venues = adding folders. (Demo only needs this one; modularity is the selling point.)

---

## 6. Open decisions / TODOs (someone needs to own these)

- [ ] **Register API keys** (free): Last.fm, Ticketmaster Discovery. Blocks M4.
- [ ] **Designate headliners** from the HARD Summer lineup — hard constraint for the scheduler (headliners stay in final slots).
- [ ] **Author the HARD Summer venue GeoJSON** (§5) — the only manual/non-code task; start early, it gates the sim render.
- [ ] **Provision the cluster** (golden VM + clones) — can proceed in parallel with code.
- [ ] **Confirm Tailscale tunnel** laptop → coordinator works from the venue network (already tested per team).

---

## 7. Suggested workstream split

- **Sim engineer:** micro social-force engine (numba + spatial hashing) + risk fields (density/pressure → zones/hotspots). Design doc §4.
- **Data/ML engineer:** demand index (§3) + macro model + schedule optimizer (local search, parallel). Design doc §5–6.
- **Frontend engineer:** deck.gl + MapLibre map, all layers, timeline scrubber, before/after toggle, controls. Design doc §12.
- **Integration/infra (floats):** cluster + FastAPI + Dask + mitigations + Claude agent (§7 of design doc) + demo.

---

## 8. How to continue using YOUR OWN Claude account

Each teammate can drive their own workstream with Claude:

1. **Give Claude the context.** Upload/paste **both** `SURGE_Design_Doc.md` and this handoff at the start of your chat. Say: *"This is the spec and handoff for a hackathon project I'm continuing. I'm working on [your workstream]."*
2. **Use Claude Code for implementation** (the Anthropic track requires it). Point it at the design doc and tell it to start at the relevant milestone. It will read the repo structure from §14 of the design doc and the `frontend-design` skill when building UI.
3. **Starter prompts by role:**
   - *Sim:* "Using SURGE_Design_Doc §4, implement the microscopic social-force engine in `backend/sim/micro.py` with numba + uniform-grid spatial hashing, ~8k agents, parameters from §4.4. Add `backend/sim/risk.py` for the density/pressure fields and zone classification."
   - *Data/ML:* "Using §3 of the handoff and §5–6 of the design doc, implement `backend/demand/service.py` (Last.fm + Ticketmaster, cached to JSON), the macro share-of-audience model in `backend/sim/macro.py`, and the local-search schedule optimizer in `backend/optimize/schedule.py` with Dask-parallel candidate scoring."
   - *Frontend:* "Using design doc §12, scaffold the React + deck.gl + MapLibre frontend with the Esri satellite basemap over Hollywood Park, plus the layer set, timeline scrubber, and before/after toggle. Follow the frontend-design skill."
   - *Infra:* "Regenerate `build_golden.sh` and `clone_init.sh` for the Ubuntu 26.04 + Miniforge (Python 3.12) golden-VM-and-clone workflow, and write the Dask scheduler/worker bootstrap + a FastAPI skeleton with the routes from design doc §10."
4. **Keep decisions in §2/§3 fixed** unless the whole team agrees to change them — they're load-bearing.

---

## 9. Demo (target ≈3 min)

Load real HARD Summer schedule + ~80k sliders → a **red hotspot** forms at a real choke moment (adjacent big sets ending / egress) → **Suggest mitigations** (barriers + staff appear with simulated risk reduction) → **Optimize schedule** → acts re-arrange (headliners still last) → **Before/After toggle** cools the map red→green with "peak crush risk −XX%" → show the **Claude-generated safety briefing**. Close: "modular — any venue is just another map file." Record a backup video (Devpost requires one anyway).

---

*Questions about any decision? The reasoning is in §2–§4 here and in `SURGE_Design_Doc.md`. When in doubt, protect the MVP line (design doc M0–M6) and the before/after demo moment — that's what wins the room.*
