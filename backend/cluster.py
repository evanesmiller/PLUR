"""Dask cluster manager with dual-mode support.

Set DASK_SCHEDULER=tcp://192.168.68.25:8786 to use the cluster.
Unset or empty -> all work runs locally on the coordinator.

Workers must have the repo cloned and on PYTHONPATH so they can
import backend.* modules. Do NOT use upload_file() -- it breaks
relative imports.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

log = logging.getLogger(__name__)

_client = None


def init_client() -> bool:
    global _client
    scheduler = os.getenv("DASK_SCHEDULER", "")
    if not scheduler:
        log.info("DASK_SCHEDULER not set — running in local mode")
        return False
    try:
        from dask.distributed import Client
        _client = Client(scheduler)
        nw = len(_client.scheduler_info()["workers"])
        log.info("Connected to Dask scheduler %s — %d workers", scheduler, nw)
        return True
    except Exception as exc:
        log.warning("Failed to connect to Dask scheduler %s: %s — falling back to local", scheduler, exc)
        _client = None
        return False


def get_client():
    return _client


def is_distributed() -> bool:
    return _client is not None


def worker_count() -> int:
    if _client is None:
        return 0
    try:
        return len(_client.scheduler_info()["workers"])
    except Exception:
        return 0


def submit(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    if _client is not None:
        future = _client.submit(fn, *args, **kwargs)
        return future.result()
    return fn(*args, **kwargs)


def map_calls(fn: Callable, arg_lists: list[tuple]) -> list[Any]:
    if _client is not None:
        futures = [_client.submit(fn, *args) for args in arg_lists]
        return _client.gather(futures)
    return [fn(*args) for args in arg_lists]


def shutdown():
    global _client
    if _client is not None:
        _client.close()
        _client = None
