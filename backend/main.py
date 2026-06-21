from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent.claude import PLURAgent
from .cluster import init_client, get_client, is_distributed, worker_count, submit, shutdown, reconnect
from .demand.service import DemandService
from .optimize.mitigation import MitigationPlanner
from .optimize.schedule import ScheduleOptimizer
from .sim.macro import MacroModel
from .sim.micro import MicroSim
from .sim.festival import run_festival
from .sim.risk import compute_risk
from .store.projects import ProjectStore
from .venue.loader import VenueGrid, load_venue

_DATA_DIR = Path(__file__).parent / "data"
_venue_cache: dict[str, VenueGrid] = {}
_micro_sim_cache: dict[str, MicroSim] = {}

app = FastAPI(
    title="PLUR",
    description="Predictive Large-scale User Routing — crowd-crush prediction & mitigation for music festivals",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_demand_svc = DemandService(_DATA_DIR / "cache")
_macro_model = MacroModel()
_scheduler = ScheduleOptimizer()
_mitigator = MitigationPlanner()
_agent = PLURAgent()
_project_store = ProjectStore(os.getenv("REDIS_URL", "redis://localhost:6379"))


@app.on_event("startup")
async def _startup():
    init_client()


@app.on_event("shutdown")
async def _shutdown():
    shutdown()


# ---------- request models ----------

class SetlistEntry(BaseModel):
    artist: str
    stage: str
    start: str  # "HH:MM"
    end: str


class DemandRequest(BaseModel):
    setlist: list[SetlistEntry]
    region: str = "US"


class SimSliders(BaseModel):
    max_capacity: int = 80000
    tickets_sold: int = 75000
    arrival_steepness: float = 1.0
    n_agents: int = 5000


class SimulateRequest(BaseModel):
    venue_id: str = "hard_summer_2025"
    setlist: list[SetlistEntry] | None = None
    stage_pop: dict[str, float] | None = None
    sliders: SimSliders = SimSliders()
    window: dict[str, int] = {"t_start": 0, "t_end": 10}


class OptimizeRequest(BaseModel):
    venue_id: str = "hard_summer_2025"
    setlist: list[SetlistEntry]
    headliners: list[str] = []
    sliders: SimSliders = SimSliders()


class MitigationRequest(BaseModel):
    venue_id: str = "hard_summer_2025"
    setlist: list[SetlistEntry] | None = None
    stage_pop: dict[str, float] | None = None
    sliders: SimSliders = SimSliders()
    window: dict[str, int] = {"t_start": 0, "t_end": 10}


class FestivalSimRequest(BaseModel):
    venue_id: str = "hard_summer_2025"
    project_id: str = ""
    setlist: list[SetlistEntry] = []
    sliders: SimSliders = SimSliders()
    barriers: list[list[list[float]]] = []
    density_red: float = 6.0


class CreateProjectRequest(BaseModel):
    name: str
    geojson: dict
    meta: dict = {}
    artists: list[str] = []
    setlist: list[dict] = []


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    artists: list[str] | None = None
    setlist: list[dict] | None = None
    meta: dict | None = None


# ---------- helpers ----------

def _get_venue(venue_id: str) -> VenueGrid:
    if venue_id not in _venue_cache:
        try:
            _venue_cache[venue_id] = load_venue(venue_id, _DATA_DIR)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Venue '{venue_id}' not found: {exc}")
    return _venue_cache[venue_id]


def _get_sim(venue_id: str) -> MicroSim:
    if venue_id not in _micro_sim_cache:
        _micro_sim_cache[venue_id] = MicroSim(_get_venue(venue_id))
    return _micro_sim_cache[venue_id]


def _setlist_dicts(entries: list[SetlistEntry]) -> list[dict]:
    return [e.model_dump() for e in entries]


def _resolve_stage_pop(
    setlist: list[SetlistEntry] | None,
    stage_pop: dict[str, float] | None,
    venue: VenueGrid,
    sliders: SimSliders,
) -> dict[str, float]:
    if stage_pop:
        return stage_pop
    if setlist:
        n_stages = max(len(venue.stages), 1)
        per_stage = sliders.tickets_sold / n_stages
        return {e.stage: per_stage for e in setlist}
    # fallback: distribute evenly
    n_stages = max(len(venue.stages), 1)
    per_stage = sliders.tickets_sold / n_stages
    return {s["id"]: per_stage for s in venue.stages}


# ---------- routes ----------

@app.get("/")
async def root():
    return {"status": "ok", "project": "PLUR", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "distributed": is_distributed(),
        "dask_workers": worker_count(),
    }


@app.get("/cluster")
async def cluster_info():
    client = get_client()
    if client is None:
        return {"mode": "local", "workers": 0, "total_threads": 0}
    info = client.scheduler_info()
    return {
        "mode": "distributed",
        "workers": len(info["workers"]),
        "total_threads": sum(w["nthreads"] for w in info["workers"].values()),
    }


@app.post("/cluster/reconnect")
async def cluster_reconnect():
    ok = reconnect()
    return {"ok": ok, "workers": worker_count()}




@app.get("/venues")
async def list_venues():
    venues_dir = _DATA_DIR / "venues"
    result = []
    if not venues_dir.exists():
        return result
    for folder in sorted(venues_dir.iterdir()):
        meta_path = folder / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        try:
            venue = _get_venue(folder.name)
            bbox = list(venue.bbox_lonlat)
            stages_out = [{"id": s["id"], "name": s["name"], "lonlat": s["lonlat"]} for s in venue.stages]
        except Exception:
            bbox = []
            stages_out = []
        venue_id = meta.get("id", folder.name)
        location = meta.get("location") or meta.get("venue") or meta.get("address", "")
        result.append({
            "id": venue_id,
            "name": meta.get("name", folder.name),
            "location": location,
            "bbox_lonlat": bbox,
            "stages": stages_out,
        })
    return result


@app.get("/venues/{venue_id}")
async def get_venue(venue_id: str):
    venue = _get_venue(venue_id)
    return {
        "id": venue_id,
        "meta": venue.meta,
        "geojson": venue.geojson,
        "grid": {
            "rows": venue.grid_shape[0],
            "cols": venue.grid_shape[1],
            "cell_m": venue.cell_m,
            "origin_m": list(venue.origin_m),
        },
        "stages": venue.stages,
        "gates": venue.gates,
        "facilities": venue.facilities,
        "bbox_lonlat": list(venue.bbox_lonlat),
    }


@app.post("/demand")
async def compute_demand(req: DemandRequest):
    setlist = _setlist_dicts(req.setlist)
    demand = _demand_svc.compute(setlist)
    venue = _get_venue("hard_summer_2025")
    macro = _macro_model.run(
        setlist=setlist,
        draw=demand["draw"],
        affinity=demand["affinity"],
        stages=venue.stages,
        tickets_sold=75000,
        max_capacity=80000,
    )
    return {
        "draw": demand["draw"],
        "affinity": demand["affinity"],
        "tags": demand["tags"],
        "stage_pop": macro["stage_pop"],
        "risk_windows": macro["risk_windows"],
        "attendance": macro["attendance"],
    }


@app.post("/simulate")
async def simulate(req: SimulateRequest):
    venue = _get_venue(req.venue_id)
    sim = _get_sim(req.venue_id)
    stage_pop = _resolve_stage_pop(req.setlist, req.stage_pop, venue, req.sliders)

    t_start = req.window.get("t_start", 0)
    t_end = req.window.get("t_end", 10)
    duration_s = max(5.0, (t_end - t_start) * 60.0)

    frames_raw = sim.run_window(
        stage_populations=stage_pop,
        real_headcount=req.sliders.tickets_sold,
        duration_s=duration_s,
        n_agents=req.sliders.n_agents,
    )

    scale = frames_raw[0]["scale"] if frames_raw else 1.0
    risk = compute_risk(frames_raw, venue, scale)

    # convert agent positions to lon/lat for frontend
    frames_out = []
    for fr in frames_raw:
        pos_m = fr["pos_m"]
        vel_m = fr["vel_m"]
        lons, lats = venue.to_lonlat(pos_m[:, 0], pos_m[:, 1])
        agents = [
            [float(lons[i]), float(lats[i]), float(vel_m[i, 0]), float(vel_m[i, 1])]
            for i in range(len(lons))
        ]
        frames_out.append({"t": fr["t"], "agents": agents})

    return {
        "frames": frames_out,
        "zones": risk.zones,
        "hotspots": risk.hotspots,
        "peak_density": risk.peak_density,
        "peak_pressure": risk.peak_pressure,
    }


@app.websocket("/ws/simulate")
async def ws_simulate(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        req = SimulateRequest(**data)
        venue = _get_venue(req.venue_id)
        sim = _get_sim(req.venue_id)
        stage_pop = _resolve_stage_pop(req.setlist, req.stage_pop, venue, req.sliders)

        t_start = req.window.get("t_start", 0)
        t_end = req.window.get("t_end", 10)
        duration_s = max(5.0, (t_end - t_start) * 60.0)

        frames = sim.run_window(
            stage_populations=stage_pop,
            real_headcount=req.sliders.tickets_sold,
            duration_s=duration_s,
            n_agents=req.sliders.n_agents,
        )
        scale = frames[0]["scale"] if frames else 1.0

        for fr in frames:
            pos_m = fr["pos_m"]
            vel_m = fr["vel_m"]
            lons, lats = venue.to_lonlat(pos_m[:, 0], pos_m[:, 1])
            agents = [
                [float(lons[i]), float(lats[i]), float(vel_m[i, 0]), float(vel_m[i, 1])]
                for i in range(len(lons))
            ]
            await websocket.send_json({"t": fr["t"], "agents": agents, "scale": scale})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await websocket.send_json({"error": str(exc)})


@app.post("/simulate_festival")
async def simulate_festival(req: FestivalSimRequest):
    venue = _get_venue(req.venue_id)
    setlist = _setlist_dicts(req.setlist)

    draw: dict[str, float] = {}
    try:
        demand = _demand_svc.compute(setlist)
        draw = demand.get("draw", {})
    except Exception:
        pass
    for entry in setlist:
        if entry["artist"] not in draw:
            draw[entry["artist"]] = 0.5

    n_agents = min(req.sliders.n_agents, 8000)
    result = submit(
        run_festival,
        venue=venue,
        setlist=setlist,
        draw=draw,
        tickets_sold=req.sliders.tickets_sold,
        n_agents=n_agents,
        extra_obstacles=req.barriers if req.barriers else None,
        density_red=req.density_red,
    )
    response = {
        "frames": result["frames"],
        "hotspots": result["hotspots"],
        "n_frames": len(result["frames"]),
    }

    if req.project_id:
        try:
            await _project_store.save_sim(req.project_id, response)
        except Exception:
            pass

    return response


@app.post("/optimize_schedule")
async def optimize_schedule(req: OptimizeRequest):
    venue = _get_venue(req.venue_id)
    setlist = _setlist_dicts(req.setlist)
    demand = _demand_svc.compute(setlist)

    result = _scheduler.optimize(
        setlist=setlist,
        draw=demand["draw"],
        affinity=demand["affinity"],
        stages=venue.stages,
        headliners=req.headliners,
        tickets_sold=req.sliders.tickets_sold,
        max_capacity=req.sliders.max_capacity,
        macro_model=_macro_model,
        n_iterations=100,
        n_jobs=4,
    )

    rationale = _agent.generate_rationale(
        changes=result["changes"],
        risk_before=result["risk_before"],
        risk_after=result["risk_after"],
        venue_name=venue.meta.get("name", req.venue_id),
    )
    result["rationale"] = rationale
    return result


@app.post("/suggest_mitigations")
async def suggest_mitigations(req: MitigationRequest):
    venue = _get_venue(req.venue_id)
    sim = _get_sim(req.venue_id)
    stage_pop = _resolve_stage_pop(req.setlist, req.stage_pop, venue, req.sliders)

    t_start = req.window.get("t_start", 0)
    t_end = req.window.get("t_end", 10)
    duration_s = max(5.0, (t_end - t_start) * 60.0)

    frames = sim.run_window(
        stage_populations=stage_pop,
        real_headcount=req.sliders.tickets_sold,
        duration_s=duration_s,
        n_agents=req.sliders.n_agents,
    )
    scale = frames[0]["scale"] if frames else 1.0
    risk = compute_risk(frames, venue, scale)
    mitigations = _mitigator.suggest(risk, venue)
    return mitigations


# ---------- project routes ----------

@app.get("/projects")
async def list_projects():
    return await _project_store.list_all()


@app.post("/projects")
async def create_project(req: CreateProjectRequest):
    return await _project_store.create(
        req.name, req.geojson, req.meta, req.artists, req.setlist
    )


@app.get("/projects/{project_id}")
async def get_project(project_id: str):
    project = await _project_store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.put("/projects/{project_id}")
async def update_project(project_id: str, req: UpdateProjectRequest):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    project = await _project_store.update(project_id, updates)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    await _project_store.delete(project_id)
    return {"ok": True}


@app.post("/projects/{project_id}/sim")
async def save_sim(project_id: str, body: dict):
    await _project_store.save_sim(project_id, body)
    return {"ok": True}


@app.get("/projects/{project_id}/sim")
async def get_sim(project_id: str):
    sim = await _project_store.get_sim(project_id)
    if not sim:
        return {"frames": [], "hotspots": []}
    return sim
