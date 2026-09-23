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
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import JWTError
from neo4j.exceptions import Neo4jError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.readiness import router as readiness_router
from app.api.v1.alerts import router as alerts_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.autonomy import router as autonomy_router
from app.api.v1.autonomy_controls import router as autonomy_controls_router
from app.api.v1.intents import router as intent_router
from app.api.v1.model_diagnostics import router as model_diagnostics_router
from app.api.v1.networks import router as network_router
from app.api.v1.organizations import router as org_router
from app.api.v1.plugins import router as plugins_router
from app.api.v1.reports import router as reports_router
from app.api.v1.simulation import router as simulation_router
from app.api.v1.spatial import router as spatial_router
from app.api.v1.telemetry import router as telemetry_router
from app.api.v1.telemetry_paths import router as telemetry_paths_router
from app.api.v1.topology import router as topology_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.request_context import RequestContextMiddleware, error_meta
from app.db.neo4j import close_neo4j, get_neo4j_driver, init_neo4j
from app.db.postgres import AsyncSessionLocal
from app.db.redis import close_redis, get_redis_client, init_redis
from app.events.bus import STREAM_GROUPS, ensure_consumer_groups, run_consumer_loop
from app.events.consumers.alert_consumer import ALERT_HANDLERS
from app.events.consumers.audit_consumer import AUDIT_HANDLERS
from app.events.consumers.report_consumer import REPORT_HANDLERS
from app.events.consumers.simulation_consumer import SIMULATION_HANDLERS
from app.events.consumers.telemetry_consumer import TELEMETRY_HANDLERS
from app.events.consumers.topology_consumer import TOPOLOGY_HANDLERS
from app.events.consumers.ws_push_consumer import WS_PUSH_HANDLERS
from app.events.realtime import ApiRealtimeLease
from app.events.distributed_realtime import DistributedRealtime, fenced_handlers, require_leadership
from app.modules.network.topology import TopologyQueryService
from app.modules.telemetry.service import (
    TelemetryCollectorRunner,
    TelemetryIngestionService,
    build_production_runtime_adapter,
    build_runtime_poll_action,
)
from app.websocket.alerts import router as alerts_ws_router
from app.websocket.digital_twin import router as digital_twin_ws_router
from app.websocket.telemetry import router as telemetry_ws_router
from app.websocket.topology import router as ws_router

logger = get_logger(__name__)

_TELEMETRY_COLLECTOR_START_MAX_ATTEMPTS = 3
_TELEMETRY_COLLECTOR_BACKOFF_BASE_SECONDS = 0.5
_TELEMETRY_COLLECTOR_BACKOFF_MAX_SECONDS = 2.0
_TELEMETRY_COLLECTOR_RUNTIME_INTERVAL_SECONDS = 5.0
_TELEMETRY_COLLECTOR_RUNTIME_POLL_MAX_ATTEMPTS = 3
_TELEMETRY_COLLECTOR_RUNTIME_POLL_BACKOFF_BASE_SECONDS = 0.5
_TELEMETRY_COLLECTOR_RUNTIME_POLL_BACKOFF_MAX_SECONDS = 2.0
_TELEMETRY_COLLECTOR_RUNTIME_SUSTAINED_FAILURE_THRESHOLD = 3


async def _telemetry_collector_noop_poll_action() -> None:
    """Default safe runtime poll action until adapter polling is wired."""
    return


def _merge_handlers(*handler_dicts: dict) -> dict:
    merged: dict = {}
    for d in handler_dicts:
        for k, v in d.items():
            merged.setdefault(k, []).append(v)
    return merged


async def _run_topology_workspace_backfill(correlation_id: str) -> int:
    driver = get_neo4j_driver()
    service = TopologyQueryService(driver=driver)
    async with AsyncSessionLocal() as db:
        return await service.backfill_missing_workspace_ids(db=db, correlation_id=correlation_id)


async def _build_emulation_adapter(settings, redis):
    """ADR-009 composition: Network validates discovery before Telemetry ingestion."""
    from app.modules.identity.service import AuthService
    from app.modules.network.emulation import EmulationDiscoveryService, load_binding
    from app.modules.network.repository import DeviceRepository
    from app.modules.network.service import NetworkService
    from app.modules.telemetry.emulation import (
        EmulationTelemetryAdapter,
        SnapshotReader,
    )

    if settings.EXECUTION_MODE != "emulation":
        raise ValueError("Snapshot telemetry is restricted to emulation mode")
    if not settings.EMULATION_SNAPSHOT_PATH or not settings.EMULATION_BINDING_PATH:
        raise ValueError("Emulation snapshot and binding paths are required")
    try:
        from emulation.topology import manifest
    except ImportError as exc:
        raise ValueError("Trusted emulation topology must be installed on the backend Python path") from exc
    expected_topology = manifest()
    snapshot_path = Path(settings.EMULATION_SNAPSHOT_PATH)
    binding = await load_binding(Path(settings.EMULATION_BINDING_PATH), snapshot_path=snapshot_path)

    async def prepare(snapshot):
        # A fresh session prevents cached membership/capabilities surviving revocation.
        async with AsyncSessionLocal() as db:
            service = EmulationDiscoveryService(
                identity=AuthService(db, redis), network=NetworkService(db, redis),
                devices=DeviceRepository(db), topology=TopologyQueryService(get_neo4j_driver()),
                expected_topology=expected_topology,
            )
            return await service.apply_snapshot(binding, snapshot)

    return EmulationTelemetryAdapter(
        reader=SnapshotReader(snapshot_path, max_bytes=settings.EMULATION_SNAPSHOT_MAX_BYTES,
                              max_age_seconds=settings.EMULATION_SNAPSHOT_MAX_AGE_SECONDS,
                              future_skew_seconds=settings.EMULATION_SNAPSHOT_FUTURE_SKEW_SECONDS),
        prepare_snapshot=prepare,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Acquire the mandatory guard before any realtime side effects."""
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    app.state.consumer_tasks = []
    app.state.collector_watchdog = None
    app.state.telemetry_collector = None
    app.state.distributed_realtime = None
    app.state.realtime_lease = None
    async with AsyncExitStack() as stack:
        stack.push_async_callback(close_redis)
        await init_redis()
        if not settings.API_REALTIME_DISTRIBUTED:
            lease = await stack.enter_async_context(ApiRealtimeLease(
                get_redis_client(), ttl_seconds=settings.API_REALTIME_LEASE_TTL_SECONDS,
            ))
            app.state.realtime_lease = lease
        stack.push_async_callback(close_neo4j)
        await init_neo4j()
        if settings.API_REALTIME_DISTRIBUTED:
            runtime = DistributedRealtime(
                get_redis_client(), settings=settings.realtime_fanout_settings(),
                leader_factory=lambda lease: _runtime_lifespan(app, lease=lease),
            )
            app.state.distributed_realtime = runtime
            app.state.realtime_lease = runtime
            await stack.enter_async_context(runtime)
        else:
            await stack.enter_async_context(_runtime_lifespan(app))
            if not lease.healthy:
                raise RuntimeError("API realtime lease lost during startup")
        yield


@asynccontextmanager
async def _runtime_lifespan(app: FastAPI, *, lease: ApiRealtimeLease | None = None):
    # Each acquisition owns its own cleanup, including cancellation during startup.
    async with AsyncExitStack() as stack:
        tasks = await stack.enter_async_context(_runtime_startup(app, stack, lease=lease))
        yield tasks


async def _collector_watchdog(collector: TelemetryCollectorRunner, lease: ApiRealtimeLease, interval: float):
    while True:
        await require_leadership(lease)
        if not collector.runtime_healthy:
            raise RuntimeError("Leader collector is unhealthy")
        await asyncio.sleep(interval)


@asynccontextmanager
async def _runtime_startup(app: FastAPI, stack: AsyncExitStack, *, lease: ApiRealtimeLease | None):
    settings = get_settings()
    startup_correlation_id = "startup-topology-workspace-backfill"
    consumer_tasks: list[asyncio.Task] = []
    app.state.consumer_tasks = consumer_tasks
    app.state.telemetry_collector = None
    telemetry_collector: TelemetryCollectorRunner | None = None
    watchdog: asyncio.Task | None = None

    async def stop_runtime():
        for task in consumer_tasks:
            task.cancel()
        if watchdog is not None:
            watchdog.cancel()
        try:
            await asyncio.gather(*consumer_tasks, *([watchdog] if watchdog else []), return_exceptions=True)
            if telemetry_collector is not None:
                await telemetry_collector.stop()
        finally:
            app.state.consumer_tasks = []
            app.state.telemetry_collector = None
            app.state.collector_watchdog = None
        logger.info("nanfo_shutdown_complete")

    # Registered before startup so partial startup/cancellation also stops work
    # before the lease is released to a successor.
    async def finish_runtime():
        cleanup = asyncio.create_task(stop_runtime(), name="leader-runtime-cleanup")
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            # A supervisor cancellation must not interrupt ownership teardown.
            await cleanup
            raise
    stack.push_async_callback(finish_runtime)

    redis = get_redis_client()
    if lease is not None:
        await require_leadership(lease)
    await ensure_consumer_groups(redis)

    try:
        telemetry_ingestion_service = TelemetryIngestionService(redis=redis)
        if not settings.TELEMETRY_FLEET_ENABLED:
            telemetry_collector = TelemetryCollectorRunner(ingestion_service=telemetry_ingestion_service)
        started = telemetry_collector is not None and await telemetry_collector.start_with_retry(
            max_attempts=_TELEMETRY_COLLECTOR_START_MAX_ATTEMPTS,
            base_backoff_seconds=_TELEMETRY_COLLECTOR_BACKOFF_BASE_SECONDS,
            max_backoff_seconds=_TELEMETRY_COLLECTOR_BACKOFF_MAX_SECONDS,
        )
        if started:
            interval_seconds = _TELEMETRY_COLLECTOR_RUNTIME_INTERVAL_SECONDS
            if settings.TELEMETRY_RUNTIME_ADAPTER_MODE.strip().lower() == "measured_snmp":
                from app.modules.telemetry.snmp_composition import build_measured_snmp_poll_action

                runtime_poll_action = await build_measured_snmp_poll_action(
                    settings=settings, session_factory=AsyncSessionLocal, redis=redis,
                    ingestion_service=telemetry_ingestion_service,
                )
                interval_seconds = settings.TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS
            else:
                adapter_options = {}
                if settings.TELEMETRY_RUNTIME_ADAPTER_MODE.strip().lower() == "emulation":
                    adapter_options["emulation_adapter"] = await _build_emulation_adapter(settings, redis)
                runtime_adapter = build_production_runtime_adapter(
                    mode=settings.TELEMETRY_RUNTIME_ADAPTER_MODE,
                    seeded_sample_key=settings.TELEMETRY_RUNTIME_ADAPTER_SEEDED_SAMPLE_KEY,
                    seeded_metric=settings.TELEMETRY_RUNTIME_ADAPTER_SEEDED_METRIC,
                    seeded_value=settings.TELEMETRY_RUNTIME_ADAPTER_SEEDED_VALUE,
                    seeded_unit=settings.TELEMETRY_RUNTIME_ADAPTER_SEEDED_UNIT,
                    seeded_source=settings.TELEMETRY_RUNTIME_ADAPTER_SEEDED_SOURCE,
                    snmp_target=settings.TELEMETRY_RUNTIME_ADAPTER_SNMP_TARGET,
                    snmp_oid=settings.TELEMETRY_RUNTIME_ADAPTER_SNMP_OID,
                    snmp_sample_key=settings.TELEMETRY_RUNTIME_ADAPTER_SNMP_SAMPLE_KEY,
                    snmp_metric=settings.TELEMETRY_RUNTIME_ADAPTER_SNMP_METRIC,
                    snmp_value=settings.TELEMETRY_RUNTIME_ADAPTER_SNMP_VALUE,
                    snmp_unit=settings.TELEMETRY_RUNTIME_ADAPTER_SNMP_UNIT,
                    snmp_source=settings.TELEMETRY_RUNTIME_ADAPTER_SNMP_SOURCE,
                    grpc_endpoint=settings.TELEMETRY_RUNTIME_ADAPTER_GRPC_ENDPOINT,
                    grpc_method=settings.TELEMETRY_RUNTIME_ADAPTER_GRPC_METHOD,
                    grpc_sample_key=settings.TELEMETRY_RUNTIME_ADAPTER_GRPC_SAMPLE_KEY,
                    grpc_metric=settings.TELEMETRY_RUNTIME_ADAPTER_GRPC_METRIC,
                    grpc_value=settings.TELEMETRY_RUNTIME_ADAPTER_GRPC_VALUE,
                    grpc_unit=settings.TELEMETRY_RUNTIME_ADAPTER_GRPC_UNIT,
                    grpc_source=settings.TELEMETRY_RUNTIME_ADAPTER_GRPC_SOURCE,
                    **adapter_options,
                )
                runtime_poll_action = build_runtime_poll_action(
                    collector_runner=telemetry_collector,
                    adapter=runtime_adapter,
                )
            if lease is not None:
                actual_poll_action = runtime_poll_action

                async def fenced_poll_action():
                    await require_leadership(lease)
                    await actual_poll_action()
                    await require_leadership(lease)

                runtime_poll_action = fenced_poll_action
            await telemetry_collector.start_runtime_loop(
                poll_action=runtime_poll_action,
                interval_seconds=interval_seconds,
                poll_max_attempts=_TELEMETRY_COLLECTOR_RUNTIME_POLL_MAX_ATTEMPTS,
                poll_base_backoff_seconds=_TELEMETRY_COLLECTOR_RUNTIME_POLL_BACKOFF_BASE_SECONDS,
                poll_max_backoff_seconds=_TELEMETRY_COLLECTOR_RUNTIME_POLL_BACKOFF_MAX_SECONDS,
                runtime_sustained_failure_threshold=_TELEMETRY_COLLECTOR_RUNTIME_SUSTAINED_FAILURE_THRESHOLD,
            )
        else:
            if lease is not None and telemetry_collector is not None:
                # A failed start may still have partially initialized resources.
                await telemetry_collector.stop()
            telemetry_collector = None
    except (RuntimeError, ValueError) as exc:
        if telemetry_collector is not None:
            try:
                await telemetry_collector.stop()
            except Exception as stop_exc:  # noqa: BLE001
                logger.warning(
                    "telemetry_collector_shutdown_after_startup_failure_failed",
                    correlation_id=startup_correlation_id,
                    error_type=type(stop_exc).__name__,
                )
                if lease is not None:
                    # Retain the collector reference for the registered cleanup.
                    raise
        telemetry_collector = None
        logger.warning(
            "telemetry_collector_startup_failed",
            correlation_id=startup_correlation_id,
            error_type=type(exc).__name__,
        )

    app.state.telemetry_collector = telemetry_collector
    if lease is not None:
        if telemetry_collector is None and not settings.TELEMETRY_FLEET_ENABLED:
            raise RuntimeError("Leader collector failed to start")
        if telemetry_collector is not None:
            watchdog = asyncio.create_task(_collector_watchdog(
                telemetry_collector, lease, settings.API_REALTIME_COLLECTOR_WATCHDOG_SECONDS,
            ), name="leader-collector-watchdog")
            app.state.collector_watchdog = watchdog

    try:
        if lease is not None:
            await require_leadership(lease)
        updated_nodes = await _run_topology_workspace_backfill(correlation_id=startup_correlation_id)
        if lease is not None:
            await require_leadership(lease)
        logger.info(
            "topology_workspace_backfill_startup",
            correlation_id=startup_correlation_id,
            updated_nodes=updated_nodes,
        )
    except (RuntimeError, Neo4jError, SQLAlchemyError) as exc:
        logger.warning(
            "topology_workspace_backfill_startup_failed",
            correlation_id=startup_correlation_id,
            error_type=type(exc).__name__,
        )

    # Merge all handlers — network events go to audit + topology + ws_push consumers
    all_handlers = _merge_handlers(
        AUDIT_HANDLERS,
        TOPOLOGY_HANDLERS,
        WS_PUSH_HANDLERS,
        TELEMETRY_HANDLERS,
        ALERT_HANDLERS,
        REPORT_HANDLERS,
        SIMULATION_HANDLERS,
    )
    if lease is not None:
        all_handlers = fenced_handlers(all_handlers, lease)

    # Start one consumer loop per stream
    for stream_key, group in STREAM_GROUPS.items():
        task = asyncio.create_task(
            run_consumer_loop(
                redis=redis,
                stream_key=stream_key,
                group=group,
                consumer_name="nanfo-api",
                handlers=all_handlers,
                reclaim_idle_ms=settings.EVENT_RECLAIM_IDLE_MS,
                batch_size=settings.EVENT_CONSUMER_BATCH_SIZE,
                completion_ttl_seconds=settings.EVENT_COMPLETION_TTL_SECONDS,
                handler_timeout_seconds=settings.EVENT_HANDLER_TIMEOUT_SECONDS,
            ),
            name=f"consumer:{stream_key}",
        )
        consumer_tasks.append(task)

    logger.info("nanfo_startup_complete", env=settings.APP_ENV)
    yield [*consumer_tasks, *([watchdog] if watchdog is not None else [])]


app = FastAPI(
    title="NANFO API",
    description="Network AI & Neural Fabric Orchestrator — REST and WebSocket API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.CORS_ALLOW_ORIGINS_LIST,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
            "meta": error_meta(request),
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


def _error_response_headers(request: Request, existing: dict[str, str] | None = None) -> dict[str, str] | None:
    """Apply a narrow CORS fallback for error responses when Origin is allowed.

    CORSMiddleware can miss internal error responses depending on where exceptions
    are raised in the middleware stack. This fallback keeps allowed browser
    clients from seeing opaque CORS failures when a real API error occurs.
    """
    headers = dict(existing or {})
    origin = request.headers.get("Origin")
    if origin and origin in _settings.CORS_ALLOW_ORIGINS_LIST:
        headers.setdefault("Access-Control-Allow-Origin", origin)
        headers.setdefault("Access-Control-Allow-Credentials", "true")

    return headers or None


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
        headers=_error_response_headers(request, getattr(exc, "headers", None)),
        content={
            "success": False,
            "data": None,
            "meta": error_meta(request),
            "errors": {"code": code, "message": message},
        },
    )


# Reviewed static public guidance from Telemetry, Report and Organization schemas.
# Exact type/message lookup only: never prefix-match, interpolate ctx/input/loc,
# or return an arbitrary validator's text. New messages need explicit review here.
_SAFE_VALIDATION_MESSAGES = {
    ("value_error", f"Value error, {message}"): f"Value error, {message}"
    for message in (
        "start_time must be before end_time (exclusive)",
        "aggregation requires a metric",
        "flow_* aggregation is unavailable: snapshot v1 has no durable flow match identity; use raw history",
        "aggregation requires start_time, end_time and bucket_seconds",
        "aggregation time range must not exceed seven days",
        "bucket_seconds requires aggregation",
        "cursor mode requires raw history and page=1",
        "cursor requires pagination=cursor",
        "date_range must be increasing and at most 31 days; end is exclusive",
        "date_range cannot extend into the future",
        "duplicate source IDs",
        "simulation_ids require a simulation or summary report",
        "intent_ids require an intent or summary report",
        "metric requires a telemetry or summary report",
        "alert filters require an alerts or summary report",
        "Supply at least one field; name cannot be null.",
        "Slug must be 3-63 characters, lowercase alphanumeric and hyphens only, and must not start or end with a hyphen.",
    )
}


def _safe_validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    first = errors[0] if errors else None
    if isinstance(first, dict):
        error_type, message = first.get("type"), first.get("msg")
        if isinstance(error_type, str) and isinstance(message, str):
            return _SAFE_VALIDATION_MESSAGES.get((error_type, message), "Request validation failed.")
    return "Request validation failed."


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return canonical validation error envelope for body/query/path validation failures."""
    # Validator messages/context can interpolate raw passwords, tokens or payloads.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        headers=_error_response_headers(request),
        content={
            "success": False,
            "data": None,
            "meta": error_meta(request),
            "errors": {
                "code": "VALIDATION_ERROR",
                "message": _safe_validation_message(exc),
            },
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return 500 without leaking internal trace details (security.md: 'never leak raw internal traces')."""
    meta = error_meta(request)
    logger.error("unhandled_exception", path=request.url.path, error_type=type(exc).__name__,
                 request_id=meta["request_id"], request_timestamp=meta["timestamp"])
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        headers=_error_response_headers(request),
        content={
            "success": False,
            "data": None,
            "meta": meta,
            "errors": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
        },
    )


app.add_middleware(RequestContextMiddleware, http_error_handler=http_exception_handler,
                   error_handler=unhandled_exception_handler)


# ── Mount routers ─────────────────────────────────────────────────────────────

app.include_router(readiness_router)
app.include_router(auth_router)
app.include_router(autonomy_router)
app.include_router(autonomy_controls_router)
app.include_router(org_router)
app.include_router(network_router)
app.include_router(spatial_router)
app.include_router(topology_router)
app.include_router(telemetry_router)
app.include_router(telemetry_paths_router)
app.include_router(simulation_router)
app.include_router(intent_router)
app.include_router(model_diagnostics_router)
app.include_router(plugins_router)
app.include_router(reports_router)
app.include_router(alerts_router)
app.include_router(audit_router)
app.include_router(ws_router)
app.include_router(telemetry_ws_router)
app.include_router(digital_twin_ws_router)
app.include_router(alerts_ws_router)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}
