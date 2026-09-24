import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

import app.main as main
from app.core.config import get_settings


@pytest.fixture
def runtime_parts(monkeypatch):
    settings = get_settings().model_copy(update={"API_REALTIME_DISTRIBUTED": True, "API_REALTIME_COLLECTOR_WATCHDOG_SECONDS": 0.01})
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    collectors = []
    def collector_factory(**kwargs):
        collector = AsyncMock()
        collector.runtime_healthy = True
        collector.start_with_retry.return_value = True
        collectors.append(collector)
        return collector
    monkeypatch.setattr(main, "TelemetryCollectorRunner", collector_factory)
    monkeypatch.setattr(main, "_run_topology_workspace_backfill", AsyncMock(return_value=0))
    async def consumer(**kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(main, "run_consumer_loop", consumer)
    poll = AsyncMock()
    monkeypatch.setattr(main, "build_runtime_poll_action", lambda **kwargs: poll)
    lease = SimpleNamespace(verify=AsyncMock(return_value=True))
    return settings, collectors, lease, poll


async def test_leader_reacquire_has_local_cleanup_and_fenced_poll(runtime_parts):
    _, collectors, lease, poll = runtime_parts
    app = FastAPI()
    for _ in range(2):
        async with main._runtime_lifespan(app, lease=lease) as tasks:
            assert len(tasks) == len(main.STREAM_GROUPS) + 1
            assert len(app.state.consumer_tasks) == len(main.STREAM_GROUPS)
            collector = collectors[-1]
            wrapped = collector.start_runtime_loop.call_args.kwargs["poll_action"]
            await wrapped()
            count = poll.await_count
            lease.verify.return_value = False
            with pytest.raises(asyncio.CancelledError):
                await wrapped()
            assert poll.await_count == count
            lease.verify.return_value = True
        assert all(task.done() for task in tasks)
        assert app.state.consumer_tasks == [] and app.state.telemetry_collector is None
        collector.stop.assert_awaited_once()
    assert len(collectors) == 2 and collectors[0] is not collectors[1]


async def test_partial_startup_cancellation_stops_collector(runtime_parts, monkeypatch):
    _, collectors, lease, _ = runtime_parts
    reached = asyncio.Event()
    async def schema():
        reached.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(main, "_ensure_graph_schema", schema)
    settings = runtime_parts[0]
    settings.API_STARTUP_GRAPH_SCHEMA_TIMEOUT_SECONDS = 60
    app = FastAPI()
    async def startup():
        async with main._runtime_lifespan(app, lease=lease):
            pytest.fail("unfinished startup yielded")
    task = asyncio.create_task(startup())
    await reached.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    collectors[0].stop.assert_awaited_once()
    assert app.state.collector_watchdog is None and not app.state.consumer_tasks


async def test_failed_collector_start_is_cleaned_before_leadership_retry(runtime_parts, monkeypatch):
    _, collectors, lease, _ = runtime_parts
    collector = AsyncMock()
    collector.start_with_retry.return_value = False
    monkeypatch.setattr(main, "TelemetryCollectorRunner", lambda **kwargs: collector)
    with pytest.raises(RuntimeError, match="failed to start"):
        async with main._runtime_lifespan(FastAPI(), lease=lease):
            pytest.fail("Failed collector must not start leader heartbeats")
    collector.stop.assert_awaited_once()


async def test_collector_watchdog_reports_failure(runtime_parts):
    _, collectors, lease, _ = runtime_parts
    app = FastAPI()
    async with main._runtime_lifespan(app, lease=lease):
        collectors[-1].runtime_healthy = False
        with pytest.raises(RuntimeError, match="collector is unhealthy"):
            await asyncio.wait_for(app.state.collector_watchdog, 1)
    collectors[-1].stop.assert_awaited_once()


@pytest.mark.parametrize("distributed", [False, True])
async def test_fleet_mode_never_constructs_api_collector(runtime_parts, distributed):
    settings, collectors, lease, _ = runtime_parts
    settings.TELEMETRY_FLEET_ENABLED = True
    app = FastAPI()
    async with main._runtime_lifespan(app, lease=lease if distributed else None) as tasks:
        assert len(tasks) == len(main.STREAM_GROUPS)
        assert app.state.telemetry_collector is None
        assert not collectors


async def test_consumers_keep_handler_identity_and_require_current_lease(runtime_parts, monkeypatch):
    _, _, lease, _ = runtime_parts
    captured = []
    async def consumer(**kwargs):
        captured.append(kwargs["handlers"])
        await asyncio.Event().wait()
    monkeypatch.setattr(main, "run_consumer_loop", consumer)
    async with main._runtime_lifespan(FastAPI(), lease=lease):
        await asyncio.sleep(0)
        handler = captured[0]["network.device.added"][-1]
        original = main.WS_PUSH_HANDLERS["network.device.added"]
        assert handler.__qualname__ == original.__qualname__
        lease.verify.return_value = False
        with pytest.raises(asyncio.CancelledError):
            await handler({})


async def test_unbounded_backfill_runs_in_background_and_is_cancelled_on_exit(runtime_parts, monkeypatch):
    """ADR-028: leader startup never waits on the topology backfill (< 35 s budget)."""
    _, collectors, lease, _ = runtime_parts
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def backfill(**kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(main, "_run_topology_workspace_backfill", backfill)
    app = FastAPI()
    async with asyncio.timeout(2):
        async with main._runtime_lifespan(app, lease=lease) as tasks:
            assert started.is_set()  # began before readiness, never awaited by startup
            assert len(tasks) == len(main.STREAM_GROUPS) + 1  # optional work is not supervised
            assert {task.get_name() for task in app.state.background_tasks} == {
                "leader-topology-backfill", "leader-consumer-janitor"}
    assert cancelled.is_set() and app.state.background_tasks == []


async def test_graph_schema_is_ensured_before_consumers_and_failure_is_bounded(runtime_parts, monkeypatch):
    settings, _, lease, _ = runtime_parts
    order = []

    async def schema():
        order.append("schema")
        raise RuntimeError("graph unavailable")

    async def consumer(**kwargs):
        order.append("consumer")
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "_ensure_graph_schema", schema)
    monkeypatch.setattr(main, "run_consumer_loop", consumer)
    async with main._runtime_lifespan(FastAPI(), lease=lease):
        await asyncio.sleep(0)
    assert order[0] == "schema" and order.count("consumer") == len(main.STREAM_GROUPS)


async def test_consumers_use_stable_name_and_delivery_bounds(runtime_parts, monkeypatch):
    settings, _, lease, _ = runtime_parts
    settings.EVENT_CONSUMER_NAME = "api-node-1"
    captured = []

    async def consumer(**kwargs):
        captured.append(kwargs)
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "run_consumer_loop", consumer)
    async with main._runtime_lifespan(FastAPI(), lease=lease):
        await asyncio.sleep(0)
    assert {kwargs["consumer_name"] for kwargs in captured} == {"api-node-1"}
    assert {kwargs["max_deliveries"] for kwargs in captured} == {settings.EVENT_MAX_DELIVERIES}
    assert {kwargs["concurrency"] for kwargs in captured} == {settings.EVENT_CONSUMER_CONCURRENCY}
    handlers = captured[0]["handlers"]
    from app.events.bus import is_idempotent
    assert is_idempotent(handlers["network.device.added"][0])  # audit: unique event_id
    assert is_idempotent(handlers["telemetry.metric.ingested"][0])  # telemetry persistence
    # Audit (unique) then the alert-publishing transition handler (keeps markers).
    assert [is_idempotent(item) for item in handlers["telemetry.collector.sustained_failure_activated"]] == [
        True, False]
    assert not is_idempotent(handlers["network.device.added"][1])  # topology keeps markers


async def test_graph_schema_hook_delegates_to_network_module(monkeypatch):
    from app.modules.network import topology

    ensure = AsyncMock(return_value={"device_id_unique": "ok"})
    monkeypatch.setattr(topology, "ensure_graph_schema", ensure)
    assert await main._ensure_graph_schema() == {"device_id_unique": "ok"}
    ensure.assert_awaited_once_with()
    monkeypatch.delattr(topology, "ensure_graph_schema")
    assert await main._ensure_graph_schema() is None  # tolerated until the owner ships it
