"""NANFO Backend — FastAPI application entry point.

Startup lifecycle:
  1. Configure structlog
  2. Init Redis + Neo4j connections
  3. Ensure Redis consumer groups exist
  4. Start background event consumer tasks
  5. Mount all API routers and WebSocket endpoint

Shutdown lifecycle:
  1. Cancel consumer tasks
  2. Close Neo4j and Redis connections
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse
from jose import JWTError
from neo4j.exceptions import Neo4jError
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.networks import router as network_router
from app.api.v1.organizations import router as org_router
from app.api.v1.telemetry import router as telemetry_router
from app.api.v1.topology import router as topology_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.neo4j import close_neo4j, get_neo4j_driver, init_neo4j
from app.db.postgres import AsyncSessionLocal
from app.db.redis import close_redis, get_redis_client, init_redis
from app.events.bus import STREAM_GROUPS, ensure_consumer_groups, run_consumer_loop
from app.events.consumers.audit_consumer import AUDIT_HANDLERS
from app.events.consumers.telemetry_consumer import TELEMETRY_HANDLERS
from app.events.consumers.topology_consumer import TOPOLOGY_HANDLERS
from app.events.consumers.ws_push_consumer import WS_PUSH_HANDLERS
from app.modules.network.topology import TopologyQueryService
from app.modules.telemetry.service import (
    TelemetryCollectorRunner,
    TelemetryIngestionService,
)
from app.websocket.telemetry import router as telemetry_ws_router
from app.websocket.topology import router as ws_router

logger = get_logger(__name__)

def _merge_handlers(*handler_dicts: dict) -> dict:
    merged: dict = {}
    for d in handler_dicts:
        for k, v in d.items():
            if k in merged:
                # Wrap both handlers so all consumers receive the event
                existing = merged[k]
                async def _combined(event, _h1=existing, _h2=v):
                    await _h1(event)
                    await _h2(event)
                merged[k] = _combined
            else:
                merged[k] = v
    return merged


async def _run_topology_workspace_backfill(correlation_id: str) -> int:
    driver = get_neo4j_driver()
    service = TopologyQueryService(driver=driver)
    async with AsyncSessionLocal() as db:
        return await service.backfill_missing_workspace_ids(db=db, correlation_id=correlation_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    startup_correlation_id = "startup-topology-workspace-backfill"
    consumer_tasks: list[asyncio.Task] = []
    telemetry_collector: TelemetryCollectorRunner | None = None

    # Initialise external connections
    await init_redis()
    await init_neo4j()

    redis = get_redis_client()
    await ensure_consumer_groups(redis)

    try:
        telemetry_ingestion_service = TelemetryIngestionService(redis=redis)
        telemetry_collector = TelemetryCollectorRunner(ingestion_service=telemetry_ingestion_service)
        await telemetry_collector.start()
    except (RuntimeError, ValueError) as exc:
        telemetry_collector = None
        logger.warning(
            "telemetry_collector_startup_failed",
            correlation_id=startup_correlation_id,
            error=str(exc),
        )

    try:
        updated_nodes = await _run_topology_workspace_backfill(correlation_id=startup_correlation_id)
        logger.info(
            "topology_workspace_backfill_startup",
            correlation_id=startup_correlation_id,
            updated_nodes=updated_nodes,
        )
    except (RuntimeError, Neo4jError, SQLAlchemyError) as exc:
        logger.warning(
            "topology_workspace_backfill_startup_failed",
            correlation_id=startup_correlation_id,
            error=str(exc),
        )

    # Merge all handlers — network events go to audit + topology + ws_push consumers
    all_handlers = _merge_handlers(AUDIT_HANDLERS, TOPOLOGY_HANDLERS, WS_PUSH_HANDLERS, TELEMETRY_HANDLERS)

    # Start one consumer loop per stream
    for stream_key, group in STREAM_GROUPS.items():
        task = asyncio.create_task(
            run_consumer_loop(
                redis=redis,
                stream_key=stream_key,
                group=group,
                consumer_name="nanfo-main-0",
                handlers=all_handlers,
            ),
            name=f"consumer:{stream_key}",
        )
        consumer_tasks.append(task)

    logger.info("nanfo_startup_complete", env=settings.APP_ENV)
    yield

    # Graceful shutdown
    for task in consumer_tasks:
        task.cancel()
    await asyncio.gather(*consumer_tasks, return_exceptions=True)
    if telemetry_collector is not None:
        await telemetry_collector.stop()
    await close_neo4j()
    await close_redis()
    logger.info("nanfo_shutdown_complete")


app = FastAPI(
    title="NANFO API",
    description="Network AI & Neural Fabric Orchestrator — REST and WebSocket API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


# ── Exception handlers ────────────────────────────────────────────────────────

@app.exception_handler(JWTError)
async def jwt_error_handler(request: Request, exc: JWTError):
    """Return 401 on JWT errors with the canonical error envelope."""
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "success": False,
            "data": None,
            "meta": {"request_id": request.headers.get("X-Request-ID", ""), "timestamp": ""},
            "errors": {"code": "AUTH_TOKEN_INVALID", "message": "Invalid or expired token."},
        },
    )


def _http_error_code(status_code: int) -> str:
    """Map an HTTP status code to the canonical error code string (API_STANDARD.md §4)."""
    return {
        400: "BAD_REQUEST",
        401: "AUTH_TOKEN_MISSING_OR_INVALID",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, f"HTTP_{status_code}")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Wrap all HTTPException responses in the canonical API envelope (API_STANDARD.md §2).

    This overrides FastAPI's default handler that returns {"detail": "..."} and
    ensures every HTTP error (401, 403, 404, 409, 429, ...) carries:
        { success: false, data: null, meta: {...}, errors: {code, message} }
    """
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code", _http_error_code(exc.status_code))
        message = detail.get("message", str(detail))
    else:
        code = _http_error_code(exc.status_code)
        message = str(detail) if detail else "An error occurred."

    return JSONResponse(
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
        content={
            "success": False,
            "data": None,
            "meta": {"request_id": request.headers.get("X-Request-ID", ""), "timestamp": ""},
            "errors": {"code": code, "message": message},
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return 500 without leaking internal trace details (security.md: 'never leak raw internal traces')."""
    logger.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "data": None,
            "meta": {"request_id": request.headers.get("X-Request-ID", ""), "timestamp": ""},
            "errors": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
        },
    )


# ── Mount routers ─────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(org_router)
app.include_router(network_router)
app.include_router(topology_router)
app.include_router(telemetry_router)
app.include_router(audit_router)
app.include_router(ws_router)
app.include_router(telemetry_ws_router)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}
