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
