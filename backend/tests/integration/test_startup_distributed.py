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
    async def backfill(**kwargs):
        reached.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(main, "_run_topology_workspace_backfill", backfill)
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
