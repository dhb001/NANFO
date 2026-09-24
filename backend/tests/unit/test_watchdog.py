"""ADR-028 in-process watchdog: stalled loops exit 70; healthy, frozen or stopped ones do not."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.watchdog import EXIT_CODE, ProcessWatchdog, build_watchdog, start_watchdog, watchdog_guard


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make(clock, *, exits=None, log=None, wait=None, timeout=120.0, heartbeat=5.0, check=5.0, report=1.0):
    exits = [] if exits is None else exits
    return ProcessWatchdog(
        "unit", timeout_seconds=timeout, heartbeat_interval_seconds=heartbeat, check_interval_seconds=check,
        clock=clock, exit_process=exits.append, log=log or MagicMock(), wait=wait, report_timeout_seconds=report,
    ), exits


def test_exit_code_is_ex_software():
    assert EXIT_CODE == 70


def test_fresh_heartbeat_never_fires_and_stale_heartbeat_exits_once_with_a_structured_event():
    clock, log = FakeClock(), MagicMock()
    watchdog, exits = make(clock, log=log)
    clock.advance(119.9)
    assert watchdog.check() is False and exits == []
    watchdog.beat()
    clock.advance(120.0)
    assert watchdog.check() is False  # exactly at the timeout is still healthy
    clock.advance(0.5)
    assert watchdog.check() is True and exits == [70]
    assert watchdog.check() is True and exits == [70]  # never exits twice
    event, fields = log.critical.call_args.args[0], log.critical.call_args.kwargs
    assert event == "process_watchdog_timeout"
    assert fields["process"] == "unit" and fields["exit_code"] == 70 and fields["timeout_seconds"] == 120.0
    assert fields["stalled_seconds"] == pytest.approx(120.5) and isinstance(fields["pid"], int)
    assert fields["loop_thread_frames"] == []  # not started inside a loop


def test_stopped_watchdog_never_fires():
    clock = FakeClock()
    watchdog, exits = make(clock)
    watchdog._stopped.set()
    clock.advance(10_000)
    assert watchdog.check() is False and exits == []


def test_watch_loop_exits_after_missed_heartbeats_with_fake_wait():
    clock = FakeClock()

    def wait(seconds):
        clock.advance(seconds)
        return False

    watchdog, exits = make(clock, wait=wait, timeout=30.0, check=5.0)
    watchdog._watch()  # returns once it has terminated the (fake) process
    assert exits == [70] and 30.0 < watchdog.stale_seconds() <= 35.0


def test_watch_loop_stops_without_exit_when_disarmed():
    clock, calls = FakeClock(), []

    def wait(seconds):
        calls.append(seconds)
        clock.advance(seconds)
        return len(calls) >= 3  # stop requested on the third wake-up

    watchdog, exits = make(clock, wait=wait, timeout=30.0, check=5.0)
    watchdog._watch()
    assert exits == [] and calls == [5.0, 5.0, 5.0]


def test_whole_process_freeze_rearms_instead_of_killing():
    clock, log, wakeups = FakeClock(), MagicMock(), iter([500.0, 5.0, 5.0])

    def wait(seconds):
        try:
            clock.advance(next(wakeups))  # the first wake-up oversleeps: docker pause / SIGSTOP
        except StopIteration:
            clock.advance(seconds)
        return False

    watchdog, exits = make(clock, log=log, wait=wait, timeout=30.0, check=5.0)
    watchdog._watch()
    # Re-armed at the freeze, then fired only after a full timeout without heartbeats.
    assert exits == [70]
    assert log.warning.call_args.args[0] == "process_watchdog_rearmed"
    assert log.warning.call_args.kwargs["overslept_seconds"] == pytest.approx(500.0)
    assert 30.0 < watchdog.stale_seconds() <= 35.0


def test_a_wedged_log_handler_cannot_prevent_the_exit():
    release = threading.Event()
    log = MagicMock()
    log.critical.side_effect = lambda *args, **kwargs: release.wait(5)
    clock = FakeClock()
    watchdog, exits = make(clock, log=log, report=0.05)
    clock.advance(121)
    started = time.monotonic()
    assert watchdog.check() is True
    assert exits == [70] and time.monotonic() - started < 2
    release.set()


def test_reporting_failures_do_not_change_the_decision():
    log = MagicMock()
    log.critical.side_effect = RuntimeError("handler closed")
    clock = FakeClock()
    watchdog, exits = make(clock, log=log)
    clock.advance(121)
    assert watchdog.check() is True and exits == [70]


@pytest.mark.parametrize("kwargs", [
    {"timeout_seconds": 0}, {"timeout_seconds": float("inf")}, {"heartbeat_interval_seconds": -1},
    {"check_interval_seconds": float("nan")}, {"heartbeat_interval_seconds": 120}, {"check_interval_seconds": 121},
    {"timeout_seconds": True}, {"report_timeout_seconds": 0},
])
def test_invalid_durations_are_rejected(kwargs):
    values = {"timeout_seconds": 120, "heartbeat_interval_seconds": 5, "check_interval_seconds": 5, **kwargs}
    with pytest.raises(ValueError):
        ProcessWatchdog("unit", **values)


def _blocking_call(seconds: float) -> None:
    time.sleep(seconds)  # deliberately blocks the event loop thread


async def test_real_thread_detects_a_blocked_loop_and_reports_its_frames():
    exits, log = [], MagicMock()
    watchdog = ProcessWatchdog("unit", timeout_seconds=0.3, heartbeat_interval_seconds=0.05,
                               check_interval_seconds=0.05, exit_process=exits.append, log=log,
                               report_timeout_seconds=1.0).start()
    try:
        await asyncio.sleep(0.2)
        assert exits == []
        _blocking_call(1.0)
    finally:
        await watchdog.stop()
    assert exits == [70]
    frames = log.critical.call_args.kwargs["loop_thread_frames"]
    assert frames and any(frame.endswith(":_blocking_call") for frame in frames)
    assert all(frame.count(":") >= 2 for frame in frames)  # file:line:function only


async def test_real_thread_leaves_a_responsive_loop_alone_and_stop_disarms():
    exits = []
    watchdog = ProcessWatchdog("unit", timeout_seconds=0.3, heartbeat_interval_seconds=0.05,
                               check_interval_seconds=0.05, exit_process=exits.append).start()
    await asyncio.sleep(0.8)  # awaiting (not blocking) keeps the heartbeat fresh
    await watchdog.stop()
    await watchdog.stop()  # idempotent
    await asyncio.to_thread(watchdog._thread.join, 1)
    assert not watchdog._thread.is_alive() and watchdog.stopped and exits == []
    _blocking_call(0.5)  # a later stall after stop() is not reported
    assert exits == []


async def test_cancelling_the_heartbeat_task_disarms_instead_of_killing():
    exits = []
    watchdog = ProcessWatchdog("unit", timeout_seconds=0.3, heartbeat_interval_seconds=0.05,
                               check_interval_seconds=0.05, exit_process=exits.append).start()
    watchdog._task.cancel()
    await asyncio.sleep(0.05)
    assert watchdog.stopped
    _blocking_call(0.6)
    await watchdog.stop()
    assert exits == []


async def test_a_failing_heartbeat_disarms_and_is_logged(monkeypatch):
    from app.core import watchdog as watchdog_module

    class FailingHeartbeat(ProcessWatchdog):
        def beat(self):
            if self._task is not None:
                raise RuntimeError("clock failed")
            super().beat()

    log, exits = MagicMock(), []
    monkeypatch.setattr(watchdog_module, "logger", log)
    watchdog = FailingHeartbeat("unit", timeout_seconds=0.3, heartbeat_interval_seconds=0.05,
                                check_interval_seconds=0.05, exit_process=exits.append).start()
    await asyncio.sleep(0.05)
    assert watchdog.stopped
    assert log.error.call_args.args[0] == "process_watchdog_heartbeat_failed"
    assert log.error.call_args.kwargs == {"process": "unit", "error_type": "RuntimeError"}
    _blocking_call(0.5)
    await watchdog.stop()
    assert exits == []


async def test_start_twice_is_rejected():
    watchdog = ProcessWatchdog("unit", timeout_seconds=1, heartbeat_interval_seconds=0.1,
                               check_interval_seconds=0.1, exit_process=lambda code: None).start()
    try:
        with pytest.raises(RuntimeError):
            watchdog.start()
    finally:
        await watchdog.stop()


def test_build_is_disabled_in_tests_and_for_non_settings_objects():
    assert get_settings().watchdog_enabled is False  # APP_ENV=test
    assert build_watchdog("api", get_settings()) is None
    assert build_watchdog("api", MagicMock()) is None  # a truthy mock never arms os._exit
    assert build_watchdog("api", SimpleNamespace()) is None


def test_build_uses_configured_durations_when_enabled():
    settings = get_settings().model_copy(update={
        "WATCHDOG_ENABLED": True, "WATCHDOG_TIMEOUT_SECONDS": 60.0,
        "WATCHDOG_HEARTBEAT_INTERVAL_SECONDS": 2.0, "WATCHDOG_CHECK_INTERVAL_SECONDS": 3.0,
    })
    watchdog = build_watchdog("api", settings, exit_process=lambda code: None)
    assert (watchdog.name, watchdog.timeout_seconds, watchdog.heartbeat_interval_seconds,
            watchdog.check_interval_seconds) == ("api", 60.0, 2.0, 3.0)


async def test_guard_arms_for_the_body_and_disarms_even_on_error():
    settings = get_settings().model_copy(update={"WATCHDOG_ENABLED": True})
    seen = []
    with pytest.raises(RuntimeError, match="boom"):
        async with watchdog_guard("worker", settings, exit_process=lambda code: None) as watchdog:
            seen.append(watchdog)
            assert watchdog is not None and not watchdog.stopped
            raise RuntimeError("boom")
    assert seen[0].stopped and seen[0]._task is None
    async with watchdog_guard("worker", get_settings()) as disabled:
        assert disabled is None


async def test_start_watchdog_returns_none_when_disabled():
    assert start_watchdog("api", get_settings()) is None


async def test_api_lifespan_arms_first_and_disarms_last():
    from app import main

    order = []
    fake = MagicMock()
    fake.stop = AsyncMock(side_effect=lambda: order.append("watchdog"))

    def record(name):
        return AsyncMock(side_effect=lambda: order.append(name))

    def arm(name, settings):
        order.append(f"arm:{name}")
        return fake

    lease = AsyncMock()
    lease.__aenter__.return_value = AsyncMock(healthy=True)

    async def consumer(**kwargs):
        await asyncio.Event().wait()

    collector = AsyncMock()
    collector.start_with_retry.return_value = False
    app = FastAPI()
    with (
        patch("app.runtime.lifespan.start_watchdog", side_effect=arm),
        patch.object(main, "TelemetryCollectorRunner", return_value=collector),
        patch.object(main, "init_redis", AsyncMock(side_effect=lambda: order.append("init:redis"))),
        patch.object(main, "init_neo4j", AsyncMock()),
        patch.object(main, "close_redis", record("redis")), patch.object(main, "close_neo4j", record("neo4j")),
        patch.object(main, "dispose_engine", record("postgres")),
        patch.object(main, "ApiRealtimeLease", return_value=lease),
        patch.object(main, "get_redis_client", return_value=AsyncMock()),
        patch.object(main, "ensure_consumer_groups", AsyncMock()),
        patch.object(main, "run_consumer_loop", consumer),
        patch.object(main, "_run_topology_workspace_backfill", AsyncMock(return_value=0)),
        patch.object(main, "_ensure_graph_schema", AsyncMock()),
    ):
        async with main.lifespan(app):
            assert app.state.process_watchdog is fake
    assert order[:2] == ["arm:api", "init:redis"]
    assert order[-4:] == ["neo4j", "redis", "postgres", "watchdog"]


def test_api_lifespan_default_test_settings_arm_nothing():
    assert build_watchdog("api", get_settings()) is None


async def _run_runner(module, monkeypatch, *, worker_attr, argv=None):
    events = []

    @contextlib.asynccontextmanager
    async def guard(name, settings=None, **overrides):
        events.append(f"arm:{name}")
        try:
            yield None
        finally:
            events.append(f"disarm:{name}")

    class Worker:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            events.append("run")

        async def run_one(self):
            events.append("run")
            return False

        async def publish_one(self):
            return False

    redis = AsyncMock()
    monkeypatch.setattr(module, "watchdog_guard", guard)
    monkeypatch.setattr(module, worker_attr, Worker)
    if hasattr(module, "aioredis"):
        monkeypatch.setattr(module.aioredis, "from_url", lambda *args, **kwargs: redis)
    if hasattr(module, "Redis"):
        monkeypatch.setattr(module.Redis, "from_url", lambda *args, **kwargs: redis)
    if hasattr(module, "get_engine"):
        monkeypatch.setattr(module, "get_engine", lambda: AsyncMock())
    if hasattr(module, "sweep_plugins"):
        monkeypatch.setattr(module, "sweep_plugins", AsyncMock())
    if argv is not None:
        monkeypatch.setattr("sys.argv", argv)
    await module.main()
    return events, redis


@pytest.mark.parametrize(("module_name", "worker_attr", "process", "argv"), [
    ("scripts.run_execution_worker", "ExecutionWorker", "execution-worker", None),
    ("scripts.run_autonomy_worker", "AutonomyWorker", "autonomy-worker", None),
    ("scripts.run_simulation_worker", "SimulationWorker", "simulation-worker", ["run_simulation_worker", "--once"]),
])
async def test_worker_runners_run_their_loop_inside_the_watchdog(module_name, worker_attr, process, argv, monkeypatch):
    module = importlib.import_module(module_name)
    events, redis = await _run_runner(module, monkeypatch, worker_attr=worker_attr, argv=argv)
    assert events == [f"arm:{process}", "run", f"disarm:{process}"]
    redis.aclose.assert_awaited_once()
