"""Application lifecycle orchestration (ADR-010/020/023/028) over injected collaborators.

``app.main`` is the composition root. It imports every collaborator (connection
init/close, consumer loop, collector runner, handler registries, backfill) and passes
its own module as ``deps``; this module only sequences them. Operators and tests
replace collaborators on ``app.main`` and the lifecycle below observes the change.

Startup (all processes): logging, Redis, singleton lease (unless distributed), Neo4j.
Leader runtime: consumer groups, collector (bounded), graph schema (bounded), consumer
loops, then *background* topology backfill and consumer janitor. Nothing unbounded
runs before the leader reports ready, so distributed startup stays below the
lease-TTL + freshness deadline (35 s by default).
Shutdown: stop leader work before releasing the lease, then close Neo4j, Redis and
the PostgreSQL pool.
Process watchdog (ADR-028): armed first and disarmed last, so a blocked event loop
during startup, serving or shutdown exits the process (code 70) for the restart policy.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI
from neo4j.exceptions import Neo4jError
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.core.watchdog import start_watchdog
from app.events.distributed_realtime import fenced_handlers, require_leadership

logger = get_logger(__name__)

_TELEMETRY_COLLECTOR_START_MAX_ATTEMPTS = 3
_TELEMETRY_COLLECTOR_BACKOFF_BASE_SECONDS = 0.5
_TELEMETRY_COLLECTOR_BACKOFF_MAX_SECONDS = 2.0
_TELEMETRY_COLLECTOR_RUNTIME_INTERVAL_SECONDS = 5.0
_TELEMETRY_COLLECTOR_RUNTIME_POLL_MAX_ATTEMPTS = 3
_TELEMETRY_COLLECTOR_RUNTIME_POLL_BACKOFF_BASE_SECONDS = 0.5
_TELEMETRY_COLLECTOR_RUNTIME_POLL_BACKOFF_MAX_SECONDS = 2.0
_TELEMETRY_COLLECTOR_RUNTIME_SUSTAINED_FAILURE_THRESHOLD = 3
STARTUP_CORRELATION_ID = "startup-topology-workspace-backfill"


async def _close_quietly(name: str, close) -> None:
    try:
        await close()
    except Exception as exc:  # noqa: BLE001 - shutdown must release every resource
        logger.warning("shutdown_close_failed", resource=name, error_type=type(exc).__name__)


def fence_and_terminate(app: FastAPI, deps: Any) -> None:
    """Singleton lease loss: stop domain effects now, then shut the process down gracefully."""
    for task in [*getattr(app.state, "consumer_tasks", []), *getattr(app.state, "background_tasks", [])]:
        task.cancel()
    watchdog = getattr(app.state, "collector_watchdog", None)
    if watchdog is not None:
        watchdog.cancel()
    collector = getattr(app.state, "telemetry_collector", None)
    if collector is not None:
        try:
            asyncio.get_running_loop().create_task(collector.stop(), name="lease-loss-collector-stop")
        except RuntimeError:
            pass
    deps.terminate_api()


@asynccontextmanager
async def lifespan_context(app: FastAPI, deps: Any):
    """Acquire the mandatory guard before any realtime side effects."""
    settings = deps.get_settings()
    deps.configure_logging(settings.LOG_LEVEL)
    app.state.consumer_tasks = []
    app.state.background_tasks = []
    app.state.collector_watchdog = None
    app.state.telemetry_collector = None
    app.state.distributed_realtime = None
    app.state.realtime_lease = None
    async with AsyncExitStack() as stack:
        # First registered, last run: covers every later startup and shutdown step.
        watchdog = start_watchdog("api", settings)
        app.state.process_watchdog = watchdog
        if watchdog is not None:
            stack.push_async_callback(watchdog.stop)
        stack.push_async_callback(_close_quietly, "postgres", deps.dispose_engine)
        stack.push_async_callback(deps.close_redis)
        await deps.init_redis()
        lease = None
        if not settings.API_REALTIME_DISTRIBUTED:
            lease = await stack.enter_async_context(deps.ApiRealtimeLease(
                deps.get_redis_client(), ttl_seconds=settings.API_REALTIME_LEASE_TTL_SECONDS,
                on_lost=lambda: fence_and_terminate(app, deps),
            ))
            app.state.realtime_lease = lease
        stack.push_async_callback(deps.close_neo4j)
        await deps.init_neo4j()
        if settings.API_REALTIME_DISTRIBUTED:
            runtime = deps.DistributedRealtime(
                deps.get_redis_client(), settings=settings.realtime_fanout_settings(),
                leader_factory=lambda leader_lease: runtime_lifespan(app, deps, lease=leader_lease),
            )
            app.state.distributed_realtime = runtime
            app.state.realtime_lease = runtime
            await stack.enter_async_context(runtime)
        else:
            await stack.enter_async_context(runtime_lifespan(app, deps))
            if not lease.healthy:
                raise RuntimeError("API realtime lease lost during startup")
        yield


@asynccontextmanager
async def runtime_lifespan(app: FastAPI, deps: Any, *, lease=None):
    # Each acquisition owns its own cleanup, including cancellation during startup.
    async with AsyncExitStack() as stack:
        tasks = await stack.enter_async_context(runtime_startup(app, stack, deps, lease=lease))
        yield tasks


async def collector_watchdog(collector, lease, interval: float):
    while True:
        await require_leadership(lease)
        if not collector.runtime_healthy:
            raise RuntimeError("Leader collector is unhealthy")
        await asyncio.sleep(interval)


async def _background_backfill(deps: Any, lease, timeout_seconds: float) -> None:
    try:
        async with asyncio.timeout(timeout_seconds):
            if lease is not None:
                await require_leadership(lease)
            updated_nodes = await deps._run_topology_workspace_backfill(correlation_id=STARTUP_CORRELATION_ID)
            if lease is not None:
                await require_leadership(lease)
        logger.info("topology_workspace_backfill_startup", correlation_id=STARTUP_CORRELATION_ID,
                    updated_nodes=updated_nodes)
    except (RuntimeError, Neo4jError, SQLAlchemyError, TimeoutError, OSError) as exc:
        logger.warning("topology_workspace_backfill_startup_failed", correlation_id=STARTUP_CORRELATION_ID,
                       error_type=type(exc).__name__)


async def _ensure_graph_schema(deps: Any, timeout_seconds: float) -> None:
    """Idempotent graph constraints before projection consumers start (bounded, non-fatal)."""
    try:
        async with asyncio.timeout(timeout_seconds):
            await deps._ensure_graph_schema()
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - projection uniqueness still guarded per event
        logger.warning("graph_schema_ensure_failed", correlation_id=STARTUP_CORRELATION_ID,
                       error_type=type(exc).__name__)


async def _start_collector(deps: Any, settings, redis, lease, state: dict) -> None:
    """Collector startup section; ``state['collector']`` tracks partial resources."""
    telemetry_ingestion_service = deps.TelemetryIngestionService(redis=redis)
    if not settings.TELEMETRY_FLEET_ENABLED:
        state["collector"] = deps.TelemetryCollectorRunner(ingestion_service=telemetry_ingestion_service)
    telemetry_collector = state["collector"]
    started = telemetry_collector is not None and await telemetry_collector.start_with_retry(
        max_attempts=_TELEMETRY_COLLECTOR_START_MAX_ATTEMPTS,
        base_backoff_seconds=_TELEMETRY_COLLECTOR_BACKOFF_BASE_SECONDS,
        max_backoff_seconds=_TELEMETRY_COLLECTOR_BACKOFF_MAX_SECONDS,
    )
    if not started:
        if lease is not None and telemetry_collector is not None:
            # A failed start may still have partially initialized resources.
            await telemetry_collector.stop()
        state["collector"] = None
        return
    interval_seconds = _TELEMETRY_COLLECTOR_RUNTIME_INTERVAL_SECONDS
    mode = settings.TELEMETRY_RUNTIME_ADAPTER_MODE.strip().lower()
    if mode == "measured_snmp":
        from app.modules.telemetry.snmp_composition import build_measured_snmp_poll_action

        runtime_poll_action = await build_measured_snmp_poll_action(
            settings=settings, session_factory=deps.AsyncSessionLocal, redis=redis,
            ingestion_service=telemetry_ingestion_service,
        )
        interval_seconds = settings.TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS
    else:
        adapter_options = {}
        if mode == "emulation":
            adapter_options["emulation_adapter"] = await deps._build_emulation_adapter(settings, redis)
        runtime_adapter = deps.build_production_runtime_adapter(
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
        runtime_poll_action = deps.build_runtime_poll_action(
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


@asynccontextmanager
async def runtime_startup(app: FastAPI, stack: AsyncExitStack, deps: Any, *, lease):
    settings = deps.get_settings()
    consumer_tasks: list[asyncio.Task] = []
    background_tasks: list[asyncio.Task] = []
    app.state.consumer_tasks = consumer_tasks
    app.state.background_tasks = background_tasks
    app.state.telemetry_collector = None
    state: dict = {"collector": None, "watchdog": None}

    async def stop_runtime():
        watchdog = state["watchdog"]
        for task in (*consumer_tasks, *background_tasks):
            task.cancel()
        if watchdog is not None:
            watchdog.cancel()
        try:
            await asyncio.gather(*consumer_tasks, *background_tasks, *([watchdog] if watchdog else []),
                                 return_exceptions=True)
            if state["collector"] is not None:
                await state["collector"].stop()
        finally:
            app.state.consumer_tasks = []
            app.state.background_tasks = []
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

    redis = deps.get_redis_client()
    if lease is not None:
        await require_leadership(lease)
    await deps.ensure_consumer_groups(redis)

    try:
        async with asyncio.timeout(settings.API_STARTUP_COLLECTOR_TIMEOUT_SECONDS):
            await _start_collector(deps, settings, redis, lease, state)
    except (RuntimeError, ValueError, TimeoutError) as exc:
        if state["collector"] is not None:
            try:
                await state["collector"].stop()
            except Exception as stop_exc:  # noqa: BLE001
                logger.warning(
                    "telemetry_collector_shutdown_after_startup_failure_failed",
                    correlation_id=STARTUP_CORRELATION_ID,
                    error_type=type(stop_exc).__name__,
                )
                if lease is not None:
                    # Retain the collector reference for the registered cleanup.
                    raise
        state["collector"] = None
        logger.warning(
            "telemetry_collector_startup_failed",
            correlation_id=STARTUP_CORRELATION_ID,
            error_type=type(exc).__name__,
        )

    telemetry_collector = state["collector"]
    app.state.telemetry_collector = telemetry_collector
    if lease is not None:
        if telemetry_collector is None and not settings.TELEMETRY_FLEET_ENABLED:
            raise RuntimeError("Leader collector failed to start")
        if telemetry_collector is not None:
            state["watchdog"] = asyncio.create_task(collector_watchdog(
                telemetry_collector, lease, settings.API_REALTIME_COLLECTOR_WATCHDOG_SECONDS,
            ), name="leader-collector-watchdog")
            app.state.collector_watchdog = state["watchdog"]

    if lease is not None:
        await require_leadership(lease)
    await _ensure_graph_schema(deps, settings.API_STARTUP_GRAPH_SCHEMA_TIMEOUT_SECONDS)

    handlers = deps.build_event_handlers()
    if lease is not None:
        handlers = fenced_handlers(handlers, lease)
    block_redis = deps.get_stream_redis_client() or redis
    consumer_name = settings.event_consumer_name

    # Start one consumer loop per stream
    for stream_key, group in deps.STREAM_GROUPS.items():
        task = asyncio.create_task(
            deps.run_consumer_loop(
                redis=redis,
                stream_key=stream_key,
                group=group,
                consumer_name=consumer_name,
                handlers=handlers,
                reclaim_idle_ms=settings.EVENT_RECLAIM_IDLE_MS,
                batch_size=settings.EVENT_CONSUMER_BATCH_SIZE,
                completion_ttl_seconds=settings.EVENT_COMPLETION_TTL_SECONDS,
                handler_timeout_seconds=settings.EVENT_HANDLER_TIMEOUT_SECONDS,
                max_deliveries=settings.EVENT_MAX_DELIVERIES,
                concurrency=settings.EVENT_CONSUMER_CONCURRENCY,
                block_redis=block_redis,
            ),
            name=f"consumer:{stream_key}",
        )
        consumer_tasks.append(task)

    # Optional leader maintenance never gates readiness or leadership health.
    background_tasks.append(asyncio.create_task(
        _background_backfill(deps, lease, settings.API_STARTUP_BACKFILL_TIMEOUT_SECONDS),
        name="leader-topology-backfill",
    ))
    background_tasks.append(asyncio.create_task(deps.run_consumer_janitor(
        redis, dict(deps.STREAM_GROUPS), active_consumer=consumer_name,
        reclaim_idle_ms=settings.EVENT_RECLAIM_IDLE_MS,
        leadership=(lambda: require_leadership(lease)) if lease is not None else None,
    ), name="leader-consumer-janitor"))
    # Let the backfill begin before readiness is reported.
    await asyncio.sleep(0)

    logger.info("nanfo_startup_complete", env=settings.APP_ENV)
    yield [*consumer_tasks, *([state["watchdog"]] if state["watchdog"] is not None else [])]
