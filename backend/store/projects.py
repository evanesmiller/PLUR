from __future__ import annotations

import json
import uuid
from datetime import datetime

import redis.asyncio as aioredis


class ProjectStore:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._url = redis_url
        self._redis: aioredis.Redis | None = None

    def _conn(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._url, decode_responses=True)
        return self._redis

    async def create(
        self,
        name: str,
        geojson: dict,
        meta: dict,
        artists: list[str],
        setlist: list[dict] | None = None,
    ) -> dict:
        pid = uuid.uuid4().hex[:8]
        now = datetime.utcnow().isoformat()
        thumbnail = next(
            (
                f
                for f in geojson.get("features", [])
                if f.get("properties", {}).get("type") == "walkable"
            ),
            None,
        )
        project = {
            "id": pid,
            "name": name,
            "geojson": geojson,
            "thumbnail": thumbnail,
            "meta": meta,
            "artists": artists,
            "setlist": setlist or [],
            "created_at": now,
            "updated_at": now,
        }
        r = self._conn()
        await r.set(f"project:{pid}", json.dumps(project))
        await r.zadd("projects", {pid: datetime.utcnow().timestamp()})
        return {k: v for k, v in project.items() if k != "geojson"}

    async def list_all(self) -> list[dict]:
        r = self._conn()
        ids = await r.zrevrange("projects", 0, -1)
        result = []
        for pid in ids:
            raw = await r.get(f"project:{pid}")
            if not raw:
                continue
            p = json.loads(raw)
            result.append({
                "id": p["id"],
                "name": p["name"],
                "created_at": p["created_at"],
                "thumbnail": p.get("thumbnail"),
                "artist_count": len(p.get("artists", [])),
            })
        return result

    async def get(self, project_id: str) -> dict | None:
        r = self._conn()
        raw = await r.get(f"project:{project_id}")
        return json.loads(raw) if raw else None

    async def update(self, project_id: str, updates: dict) -> dict | None:
        r = self._conn()
        raw = await r.get(f"project:{project_id}")
        if not raw:
            return None
        project = json.loads(raw)
        project.update(updates)
        project["updated_at"] = datetime.utcnow().isoformat()
        await r.set(f"project:{project_id}", json.dumps(project))
        return {k: v for k, v in project.items() if k != "geojson"}

    async def delete(self, project_id: str) -> None:
        r = self._conn()
        await r.delete(f"project:{project_id}")
        await r.zrem("projects", project_id)
