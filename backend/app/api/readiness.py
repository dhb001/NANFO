"""ADR020 readiness. Liveness remains the separate /health endpoint.

Dependency probes (PostgreSQL, schema, Redis, Neo4j) are reused for at most
``API_READINESS_CACHE_SECONDS`` (<= 2 s) per application so frequent probes from
compose/verify/gateway health checks cannot multiply backing-service load.
Process-local state (lease, consumers, collector) is always evaluated fresh.
"""

import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.request_context import error_meta
from app.core.runtime_health import PROBE_TIMEOUT_SECONDS, dependency_checks
from app.db.neo4j import get_neo4j_driver
from app.db.postgres import AsyncSessionLocal
from app.db.redis import get_redis_client
from app.events.bus import STREAM_GROUPS, bus_diagnostics
from app.modules.report.artifacts import ArtifactStore

router = APIRouter(tags=["Health"])
_clock = time.monotonic


async def _cached_dependency_checks(request: Request, ttl_seconds: float) -> dict[str, str]:
    state = request.app.state
    cached = getattr(state, "readiness_dependency_cache", None)
    now = _clock()
    if ttl_seconds > 0 and cached is not None and now - cached[0] < ttl_seconds:
        return dict(cached[1])
    checks = await dependency_checks(
        sessions=AsyncSessionLocal,
        redis=get_redis_client,
        neo4j=get_neo4j_driver,
    )
    state.readiness_dependency_cache = (_clock(), dict(checks))
    return checks


@router.get("/ready")
async def ready(request: Request):
    settings = get_settings()
    checks = await _cached_dependency_checks(request, settings.API_READINESS_CACHE_SECONDS)
    checks["api_lease"] = "unavailable"
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            lease = getattr(request.app.state, "realtime_lease", None)
            if lease is not None and await lease.verify():
                checks["api_lease"] = "ok"
    except Exception:  # noqa: BLE001 - no lease tokens or transport errors in diagnostics
        pass
    tasks = getattr(request.app.state, "consumer_tasks", [])
    distributed = getattr(request.app.state, "distributed_realtime", None)
    distributed_mode = settings.API_REALTIME_DISTRIBUTED
    follower = distributed_mode and distributed is not None and distributed.lease is None
    checks["api_consumers"] = (
        "ok"
        if len(tasks) == len(STREAM_GROUPS) and all(not task.done() for task in tasks)
        else "unavailable"
    )
    collector = getattr(request.app.state, "telemetry_collector", None)
    diagnostics = {
        "mode": "distributed" if distributed_mode else "singleton",
        "role": "follower" if follower else "leader" if not distributed_mode or distributed is not None else "unavailable",
        "local_consumer_count": len(tasks),
        "local_collector": collector is not None,
        "collection_owner": "fleet" if settings.TELEMETRY_FLEET_ENABLED else "domain_leader",
        "event_bus": bus_diagnostics(),
    }
    if distributed_mode:
        checks["realtime_subscription"] = checks["api_lease"] if distributed is not None else "unavailable"
        if follower:
            # Delegated is a diagnostic, never a claim of local consumer health.
            checks["api_consumers"] = "delegated" if not tasks and collector is None else "unavailable"
        elif not settings.TELEMETRY_FLEET_ENABLED:
            watchdog = getattr(request.app.state, "collector_watchdog", None)
            checks["collector_watchdog"] = "ok" if watchdog is not None and not watchdog.done() else "unavailable"
    configured = settings.TELEMETRY_RUNTIME_ADAPTER_MODE.strip().lower() not in (
        "",
        "stub",
    )
    telemetry = "unavailable"
    if configured:
        telemetry = (
            "ok" if collector is not None and collector.runtime_healthy else "degraded"
        )
    if settings.TELEMETRY_FLEET_ENABLED:
        telemetry = "external_unverified"
    elif follower:
        telemetry = "delegated" if configured else "unavailable"
    if (configured or settings.EXECUTION_MODE == "emulation") and not (follower or settings.TELEMETRY_FLEET_ENABLED):
        checks["telemetry"] = telemetry
    capabilities = {
        "telemetry": telemetry,
        "autonomous_control": "unavailable",
        "model_inference": "unavailable",
    }
    storage = {"reports": {"ready": False}}
    checks["report_storage"] = "unavailable"
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            capacity = await asyncio.to_thread(
                ArtifactStore(
                    settings.REPORTS_STORAGE_PATH, settings.REPORTS_MAX_BYTES
                ).capacity,
                settings.REPORTS_MIN_FREE_BYTES,
            )
        storage["reports"] = capacity
        checks["report_storage"] = "ok" if capacity["ready"] else "unavailable"
    except (OSError, ValueError, TimeoutError):
        pass
    is_ready = all(value == "ok" or (key == "api_consumers" and follower and value == "delegated")
                   for key, value in checks.items())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        headers={"Cache-Control": "no-store"},
        content={
            "success": is_ready,
            "data": {
                "ready": is_ready,
                "checks": checks,
                "capabilities": capabilities,
                "storage": storage,
                "realtime": diagnostics,
            },
            "meta": error_meta(request),
            "errors": None
            if is_ready
            else {
                "code": "SERVICE_UNAVAILABLE",
                "message": "Required runtime dependencies are unavailable.",
            },
        },
    )
