"""NANFO Backend — FastAPI application entry point and composition root.

Startup lifecycle (see app.runtime.lifespan):
  1. Configure structlog
  2. Init Redis + Neo4j connections (singleton lease unless distributed)
  3. Ensure Redis consumer groups and graph schema exist
  4. Start background event consumer tasks, then background maintenance
  5. Mount all API routers and WebSocket endpoints

Shutdown lifecycle:
  1. Cancel consumer and maintenance tasks, stop the collector
  2. Close Neo4j and Redis connections, dispose the PostgreSQL pool

Collaborators are imported here and resolved through this module at runtime, so
``app.main.<name>`` remains the single seam for operators and tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from app.core.body_limit import BodyLimitMiddleware
from app.core.config import get_settings
from app.core.exception_handlers import (  # noqa: F401 - stable public import names
    _SAFE_VALIDATION_MESSAGES,
    _http_error_code,
    _safe_validation_message,
    dependency_unavailable_handler,
    error_response_headers,
    http_exception_handler,
    jwt_error_handler,
    register_exception_handlers,
    request_too_large_handler,
    request_validation_exception_handler,
    unhandled_exception_handler,
)
from app.core.logging import configure_logging, get_logger  # noqa: F401 - composition seam
from app.core.request_context import RequestContextMiddleware, error_meta  # noqa: F401
from app.core.security import JWTError  # noqa: F401 - PyJWT-backed alias (ADR-028 C10)
from app.db.neo4j import close_neo4j, get_neo4j_driver, init_neo4j  # noqa: F401 - composition seam
from app.db.postgres import AsyncSessionLocal, dispose_engine  # noqa: F401
from app.db.redis import close_redis, get_redis_client, get_stream_redis_client, init_redis  # noqa: F401
from app.events.bus import (  # noqa: F401
    STREAM_GROUPS,
    ensure_consumer_groups,
    idempotent_handlers,
    merge_handlers,
    run_consumer_janitor,
    run_consumer_loop,
)
from app.events.consumers.alert_consumer import ALERT_HANDLERS
from app.events.consumers.audit_consumer import AUDIT_HANDLERS
from app.events.consumers.report_consumer import REPORT_HANDLERS
from app.events.consumers.simulation_consumer import SIMULATION_HANDLERS
from app.events.consumers.telemetry_consumer import TELEMETRY_HANDLERS
from app.events.consumers.topology_consumer import TOPOLOGY_HANDLERS
from app.events.consumers.ws_push_consumer import WS_PUSH_HANDLERS
from app.events.distributed_realtime import (  # noqa: F401
    DistributedRealtime,
    fenced_handlers,
    require_leadership,
)
from app.events.realtime import ApiRealtimeLease, terminate_api  # noqa: F401
from app.modules.network.topology import TopologyQueryService
from app.modules.telemetry.service import (  # noqa: F401
    TelemetryCollectorRunner,
    TelemetryIngestionService,
    build_production_runtime_adapter,
    build_runtime_poll_action,
)
from app.runtime import lifespan as _runtime
from app.runtime.lifespan import (  # noqa: F401 - stable public import names
    _TELEMETRY_COLLECTOR_BACKOFF_BASE_SECONDS,
    _TELEMETRY_COLLECTOR_BACKOFF_MAX_SECONDS,
    _TELEMETRY_COLLECTOR_RUNTIME_INTERVAL_SECONDS,
    _TELEMETRY_COLLECTOR_RUNTIME_POLL_BACKOFF_BASE_SECONDS,
    _TELEMETRY_COLLECTOR_RUNTIME_POLL_BACKOFF_MAX_SECONDS,
    _TELEMETRY_COLLECTOR_RUNTIME_POLL_MAX_ATTEMPTS,
    _TELEMETRY_COLLECTOR_RUNTIME_SUSTAINED_FAILURE_THRESHOLD,
    _TELEMETRY_COLLECTOR_START_MAX_ATTEMPTS,
)
from app.websocket.alerts import router as alerts_ws_router
from app.websocket.digital_twin import router as digital_twin_ws_router
from app.websocket.telemetry import router as telemetry_ws_router
from app.websocket.topology import router as ws_router

logger = get_logger(__name__)
_composition = sys.modules[__name__]
_error_response_headers = error_response_headers

# Handlers whose durable effect is keyed by a database-unique event_id may skip
# Redis completion markers: audit_logs.event_id (ON CONFLICT DO NOTHING) and
# telemetry_records.event_id (advisory-locked existence check + UNIQUE column).
_IDEMPOTENT_TELEMETRY_EVENTS = ("telemetry.metric.ingested",)
CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
CORS_ALLOW_HEADERS = ["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key",
                      "If-None-Match", "If-Match"]
CORS_EXPOSE_HEADERS = ["X-Request-ID", "ETag", "Retry-After", "Content-Disposition"]


def _merge_handlers(*handler_dicts: dict) -> dict:
    return merge_handlers(*handler_dicts)


def build_event_handlers() -> dict:
    """Merged registry: network events go to audit + topology + ws_push consumers."""
    return _merge_handlers(
        idempotent_handlers(AUDIT_HANDLERS),
        TOPOLOGY_HANDLERS,
        WS_PUSH_HANDLERS,
        idempotent_handlers(TELEMETRY_HANDLERS, only=_IDEMPOTENT_TELEMETRY_EVENTS),
        ALERT_HANDLERS,
        REPORT_HANDLERS,
        SIMULATION_HANDLERS,
    )


async def _run_topology_workspace_backfill(correlation_id: str) -> int:
    driver = get_neo4j_driver()
    service = TopologyQueryService(driver=driver)
    async with AsyncSessionLocal() as db:
        return await service.backfill_missing_workspace_ids(db=db, correlation_id=correlation_id)


async def _ensure_graph_schema():
    """Network-owned idempotent graph constraints/indexes (imported lazily)."""
    from app.modules.network import topology

    ensure = getattr(topology, "ensure_graph_schema", None)
    if ensure is None:
        logger.warning("graph_schema_ensure_unavailable")
        return None
    report = await ensure()
    logger.info("graph_schema_ensured", items=len(report) if isinstance(report, dict) else None)
    return report


async def _build_emulation_adapter(settings, redis):
    """ADR-009 composition: Network validates discovery before Telemetry ingestion.

    ADR-028: the per-poll discovery service is Network's public composition
    (``build_emulation_discovery``) over owner services only, never a repository.
    """
    from app.modules.network.emulation import build_emulation_discovery, load_binding
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
            service = build_emulation_discovery(
                db, redis, expected_topology=expected_topology, topology=TopologyQueryService(get_neo4j_driver()),
            )
            return await service.apply_snapshot(binding, snapshot)

    return EmulationTelemetryAdapter(
        reader=SnapshotReader(snapshot_path, max_bytes=settings.EMULATION_SNAPSHOT_MAX_BYTES,
                              max_age_seconds=settings.EMULATION_SNAPSHOT_MAX_AGE_SECONDS,
                              future_skew_seconds=settings.EMULATION_SNAPSHOT_FUTURE_SKEW_SECONDS),
        prepare_snapshot=prepare,
    )


def lifespan(app: FastAPI):
    """Acquire the mandatory guard before any realtime side effects."""
    return _runtime.lifespan_context(app, _composition)


def _runtime_lifespan(app: FastAPI, *, lease: ApiRealtimeLease | None = None):
    return _runtime.runtime_lifespan(app, _composition, lease=lease)


def _runtime_startup(app: FastAPI, stack, *, lease: ApiRealtimeLease | None):
    return _runtime.runtime_startup(app, stack, _composition, lease=lease)


async def _collector_watchdog(collector: TelemetryCollectorRunner, lease: ApiRealtimeLease, interval: float):
    await _runtime.collector_watchdog(collector, lease, interval)


async def health():
    return {"status": "ok"}


def create_app() -> FastAPI:
    settings = get_settings()
    docs = settings.docs_enabled
    application = FastAPI(
        title="NANFO API",
        description="Network AI & Neural Fabric Orchestrator — REST and WebSocket API",
        version="0.1.0",
        lifespan=lifespan,
        # Schema generation (app.openapi()) always works; public routes are opt-in.
        docs_url="/api/docs" if docs else None,
        redoc_url="/api/redoc" if docs else None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    register_exception_handlers(application)
    # Added innermost-first: RequestContext -> CORS -> BodyLimit -> routing.
    application.add_middleware(
        BodyLimitMiddleware, default_limit=settings.API_MAX_BODY_BYTES,
        asset_limit=settings.API_MAX_ASSET_UPLOAD_BYTES, scene_limit=settings.API_MAX_SPATIAL_SCENE_BYTES,
        error_handler=unhandled_exception_handler,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOW_ORIGINS_LIST,
        allow_credentials=False,
        allow_methods=CORS_ALLOW_METHODS,
        allow_headers=CORS_ALLOW_HEADERS,
        expose_headers=CORS_EXPOSE_HEADERS,
    )
    application.add_middleware(RequestContextMiddleware, http_error_handler=http_exception_handler,
                               error_handler=unhandled_exception_handler)

    for router in (
        readiness_router, auth_router, autonomy_router, autonomy_controls_router, org_router,
        network_router, spatial_router, topology_router, telemetry_router, telemetry_paths_router,
        simulation_router, intent_router, model_diagnostics_router, plugins_router, reports_router,
        alerts_router, audit_router, ws_router, telemetry_ws_router, digital_twin_ws_router, alerts_ws_router,
    ):
        application.include_router(router)
    application.add_api_route("/health", health, methods=["GET"], tags=["Health"])
    return application


app = create_app()
