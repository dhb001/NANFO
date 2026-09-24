"""Lease fencing and startup gates, with injected infrastructure and fatal exit."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from redis.exceptions import ConnectionError

from app.events.realtime import ApiRealtimeLease


class LeaseRedis:
    """Minimal atomic Redis operations for unit tests; real Lua is tested opt-in."""

    def __init__(self):
        self.owner = None

    async def set(self, key, value, **kwargs):
        if self.owner is not None:
            return False
        self.owner = value
        return True

    async def eval(self, script, numkeys, key, token, *args):
        if token != self.owner:
            return 0
        if not args:
            self.owner = None
        return 1

    async def get(self, key):
        return self.owner


async def test_multi_instance_exclusion_renewal_release_and_restart():
    redis = LeaseRedis()
    lost = Mock()
    async with ApiRealtimeLease(redis, ttl_seconds=0.12, on_lost=lost) as first:
        with pytest.raises(RuntimeError, match="exactly one"):
            async with ApiRealtimeLease(redis, on_lost=lost):
                pytest.fail("second API started")
        await asyncio.sleep(0.16)
        assert first.healthy
    assert redis.owner is None
    async with ApiRealtimeLease(redis, on_lost=lost) as second:
        assert second.token != first.token
    lost.assert_not_called()


async def test_readiness_verifies_live_ownership_without_renew_or_delete():
    redis = LeaseRedis()
    async with ApiRealtimeLease(redis) as lease:
        deadline = lease.deadline
        assert await lease.verify()
        redis.owner = "successor"
        assert not await lease.verify()
        assert lease.deadline == deadline
        assert redis.owner == "successor"
    assert redis.owner == "successor"


async def test_readiness_rejects_dead_lease_task_even_before_deadline():
    async with ApiRealtimeLease(LeaseRedis()) as lease:
        lease.task.cancel()
        await asyncio.gather(lease.task, return_exceptions=True)
        assert lease.healthy
        assert not await lease.verify()


@pytest.mark.parametrize("failure", ["owner", "redis", "timeout"])
async def test_renewal_loss_is_fatal_and_cannot_release_successor(failure):
    redis = LeaseRedis()
    lost = asyncio.Event()
    async with ApiRealtimeLease(redis, ttl_seconds=0.09, on_lost=lost.set) as lease:
        if failure == "owner":
            redis.owner = "successor"
        elif failure == "redis":
            redis.eval = AsyncMock(side_effect=ConnectionError("offline"))
        else:
            redis.eval = AsyncMock(side_effect=lambda *args: None)

            async def hang(*args):
                await asyncio.Event().wait()

            redis.eval = hang
        await asyncio.wait_for(lost.wait(), 1)
        assert not lease.healthy
    if failure == "owner":
        assert redis.owner == "successor"


async def test_redis_startup_failure_does_not_start_runtime():
    from app import main

    with (
        patch.object(main, "init_redis", AsyncMock(side_effect=ConnectionError("offline"))),
        patch.object(main, "close_redis", AsyncMock()) as close,
        patch.object(main, "init_neo4j", AsyncMock()) as neo4j,
        patch.object(main, "ensure_consumer_groups", AsyncMock()) as groups,
        pytest.raises(ConnectionError),
    ):
        async with main.lifespan(FastAPI()):
            pytest.fail("API started without Redis")
    close.assert_awaited_once()
    neo4j.assert_not_awaited()
    groups.assert_not_awaited()


async def test_conflicting_api_fails_before_side_effects():
    from app import main

    redis = LeaseRedis()
    async with ApiRealtimeLease(redis):
        with (
            patch.object(main, "init_redis", AsyncMock()),
            patch.object(main, "get_redis_client", return_value=redis),
            patch.object(main, "close_redis", AsyncMock()),
            patch.object(main, "init_neo4j", AsyncMock()) as neo4j,
            patch.object(main, "ensure_consumer_groups", AsyncMock()) as groups,
            pytest.raises(RuntimeError, match="exactly one"),
        ):
            async with main.lifespan(FastAPI()):
                pytest.fail("duplicate API started")
        neo4j.assert_not_awaited()
        groups.assert_not_awaited()


async def test_lease_acquisition_failure_closes_redis_before_neo4j_startup():
    from app import main

    redis = LeaseRedis()
    redis.set = AsyncMock(side_effect=ConnectionError("lease acquisition failed"))
    with (
        patch.object(main, "init_redis", AsyncMock()),
        patch.object(main, "get_redis_client", return_value=redis),
        patch.object(main, "close_redis", AsyncMock()) as close,
        patch.object(main, "init_neo4j", AsyncMock()) as neo4j,
        pytest.raises(ConnectionError),
    ):
        async with main.lifespan(FastAPI()):
            pytest.fail("API started")
    close.assert_awaited_once()
    neo4j.assert_not_awaited()


async def test_neo4j_startup_failure_releases_lease_and_closes_connections():
    from app import main

    redis = LeaseRedis()
    with (
        patch.object(main, "init_redis", AsyncMock()),
        patch.object(main, "get_redis_client", return_value=redis),
        patch.object(main, "close_redis", AsyncMock()) as close_redis,
        patch.object(main, "init_neo4j", AsyncMock(side_effect=RuntimeError("neo4j offline"))),
        patch.object(main, "close_neo4j", AsyncMock()) as close_neo4j,
        pytest.raises(RuntimeError),
    ):
        async with main.lifespan(FastAPI()):
            pytest.fail("API started")
    assert redis.owner is None
    close_neo4j.assert_awaited_once()
    close_redis.assert_awaited_once()


# ── ADR-028: renewal retries inside the deadline; loss fences then shuts down ──

async def test_transient_renewal_failures_retry_within_deadline():
    redis = LeaseRedis()
    lost = Mock()
    original = redis.eval
    failures = {"left": 2}

    async def flaky(*args):
        if failures["left"]:
            failures["left"] -= 1
            raise ConnectionError("blip")
        return await original(*args)

    redis.eval = flaky
    async with ApiRealtimeLease(redis, ttl_seconds=0.6, on_lost=lost) as lease:
        await asyncio.sleep(0.5)
        assert lease.healthy and failures["left"] == 0
    lost.assert_not_called()


async def test_loss_fences_before_callback():
    redis = LeaseRedis()
    observed = []
    lease = ApiRealtimeLease(redis, ttl_seconds=0.09, on_lost=lambda: observed.append(lease.healthy))
    async with lease:
        redis.owner = "successor"
        async with asyncio.timeout(1):
            while not observed:
                await asyncio.sleep(0.01)
    assert observed == [False]


def test_terminate_api_requests_graceful_shutdown_with_hard_timeout(monkeypatch):
    from app.events import realtime

    signals, timers, exits = [], [], []

    class Timer:
        def __init__(self, interval, function):
            timers.append(interval)
            self.daemon = False

        def start(self):
            assert self.daemon  # never keeps a stalled process alive

    monkeypatch.setattr(realtime, "_termination_requested", False)
    monkeypatch.setattr(realtime.threading, "Timer", Timer)
    monkeypatch.setattr(realtime.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(realtime.atexit, "register", lambda function: exits.append(function))
    realtime.terminate_api(hard_timeout_seconds=7)
    realtime.terminate_api(hard_timeout_seconds=7)  # idempotent
    assert signals == [(realtime.os.getpid(), realtime.signal.SIGTERM)]
    assert timers == [7] and exits == [realtime._exit_nonzero]


async def test_singleton_lease_loss_cancels_domain_work_then_terminates():
    from types import SimpleNamespace

    from app.runtime.lifespan import fence_and_terminate

    consumer = asyncio.create_task(asyncio.Event().wait())
    background = asyncio.create_task(asyncio.Event().wait())
    collector = SimpleNamespace(stop=AsyncMock())
    app = FastAPI()
    app.state.consumer_tasks, app.state.background_tasks = [consumer], [background]
    app.state.collector_watchdog, app.state.telemetry_collector = None, collector
    deps = SimpleNamespace(terminate_api=Mock())
    fence_and_terminate(app, deps)
    await asyncio.gather(consumer, background, return_exceptions=True)
    await asyncio.sleep(0)
    assert consumer.cancelled() and background.cancelled()
    collector.stop.assert_awaited_once()
    deps.terminate_api.assert_called_once_with()


async def test_draining_process_never_reacquires_leadership(monkeypatch):
    from app.events import distributed_realtime, realtime
    from app.events.fanout_contract import FanoutSettings

    monkeypatch.setattr(realtime, "_termination_requested", True)
    acquired = []
    monkeypatch.setattr(distributed_realtime, "ApiRealtimeLease", lambda *a, **k: acquired.append(1))
    runtime = distributed_realtime.DistributedRealtime(AsyncMock(), leader_factory=None, managers={},
                                                       settings=FanoutSettings())
    await asyncio.wait_for(runtime._supervise(), 1)
    assert acquired == []
