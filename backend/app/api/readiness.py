"""ADR020 readiness. Liveness remains the separate /health endpoint."""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.runtime_health import PROBE_TIMEOUT_SECONDS, dependency_checks
from app.db.neo4j import get_neo4j_driver
from app.db.postgres import AsyncSessionLocal
from app.db.redis import get_redis_client
from app.events.bus import STREAM_GROUPS
from app.modules.report.artifacts import ArtifactStore

router = APIRouter(tags=["Health"])


@router.get("/ready")
async def ready(request: Request):
    settings = get_settings()
    checks = await dependency_checks(
        sessions=AsyncSessionLocal,
        redis=get_redis_client,
        neo4j=get_neo4j_driver,
    )
    checks["api_lease"] = "unavailable"
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            lease = getattr(request.app.state, "realtime_lease", None)
            if lease is not None and await lease.verify():
                checks["api_lease"] = "ok"
    except Exception:  # noqa: BLE001 - no lease tokens or transport errors in diagnostics
        pass
    tasks = getattr(request.app.state, "consumer_tasks", [])
    checks["api_consumers"] = (
        "ok"
        if len(tasks) == len(STREAM_GROUPS) and all(not task.done() for task in tasks)
        else "unavailable"
    )
    collector = getattr(request.app.state, "telemetry_collector", None)
    configured = settings.TELEMETRY_RUNTIME_ADAPTER_MODE.strip().lower() not in (
        "",
        "stub",
    )
    telemetry = "unavailable"
    if configured:
        telemetry = (
            "ok" if collector is not None and collector.runtime_healthy else "degraded"
        )
    if configured or settings.EXECUTION_MODE == "emulation":
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
    is_ready = all(value == "ok" for value in checks.values())
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
            },
            "meta": {
                "request_id": "",
                "timestamp": datetime.now(UTC).isoformat(),
                "execution_mode": settings.EXECUTION_MODE,
            },
            "errors": None
            if is_ready
            else {
                "code": "SERVICE_UNAVAILABLE",
                "message": "Required runtime dependencies are unavailable.",
            },
        },
    )
