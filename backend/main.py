from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="SURGE", description="Crowd-crush prediction & mitigation for multi-stage music festivals")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "ok", "project": "SURGE", "version": "0.1.0"}


@app.get("/venues")
async def list_venues():
    return []


@app.get("/venues/{venue_id}")
async def get_venue(venue_id: str):
    return {"error": "not implemented"}


@app.post("/demand")
async def compute_demand():
    return {"error": "not implemented"}


@app.post("/simulate")
async def simulate():
    return {"error": "not implemented"}


@app.post("/optimize_schedule")
async def optimize_schedule():
    return {"error": "not implemented"}


@app.post("/suggest_mitigations")
async def suggest_mitigations():
    return {"error": "not implemented"}
