"""Unit tests for event publisher envelope behavior."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.events.publisher import publish_event


@pytest.mark.asyncio
async def test_publish_event_uses_provided_event_id_in_envelope():
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value="100-0")
    event_id = str(uuid.uuid4())

    stream_entry_id = await publish_event(
        redis=fake_redis,
        event_type="simulation.completed",
        source="simulation",
        payload={"simulation_id": str(uuid.uuid4())},
        correlation_id=str(uuid.uuid4()),
        event_id=event_id,
    )

    assert stream_entry_id == "100-0"
    fake_redis.xadd.assert_awaited_once()
    args = fake_redis.xadd.await_args.args
    assert args[0] == "stream:simulation"
    envelope = args[1]
    assert envelope["event_id"] == event_id
    assert envelope["event_type"] == "simulation.completed"


@pytest.mark.asyncio
async def test_publish_event_invalid_event_id_raises_value_error():
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value="100-0")

    with pytest.raises(ValueError):
        await publish_event(
            redis=fake_redis,
            event_type="simulation.completed",
            source="simulation",
            payload={"simulation_id": str(uuid.uuid4())},
            correlation_id=str(uuid.uuid4()),
            event_id="not-a-uuid",
        )

    fake_redis.xadd.assert_not_awaited()


# ── ADR-028 producer admission and envelope version ──────────────────────────

import fakeredis  # noqa: E402

from app.core.errors import DependencyUnavailableError  # noqa: E402
from app.events import publisher  # noqa: E402


def memory_redis(used, maximum):
    redis = AsyncMock()
    redis.info = AsyncMock(return_value={"used_memory": used, "maxmemory": maximum})
    redis.xadd = AsyncMock(return_value="1-0")
    return redis


async def publish(redis, **overrides):
    return await publish_event(redis=redis, event_type="alert.generated", source="alert",
                               payload={"alert_id": "a"}, correlation_id=str(uuid.uuid4()), **overrides)


@pytest.mark.parametrize("used,maximum,admitted", [
    (89, 100, True), (90, 100, False), (100, 100, False), (10**9, 0, True),
])
async def test_publish_admission_uses_redis_memory_ratio(used, maximum, admitted):
    redis = memory_redis(used, maximum)
    if admitted:
        assert await publish(redis) == "1-0"
        # Durable streams are never trimmed by producers.
        assert set(redis.xadd.await_args.kwargs) == set() and len(redis.xadd.await_args.args) == 2
    else:
        with pytest.raises(DependencyUnavailableError) as error:
            await publish(redis)
        assert error.value.dependency == "redis"
        redis.xadd.assert_not_awaited()


async def test_memory_sample_is_cached_for_at_most_five_seconds(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(publisher, "_clock", lambda: clock[0])
    redis = memory_redis(10, 100)
    for _ in range(3):
        await publish(redis)
    assert redis.info.await_count == 1
    redis.info.return_value = {"used_memory": 95, "maxmemory": 100}
    clock[0] += 4.9
    await publish(redis)
    clock[0] += 0.2
    with pytest.raises(DependencyUnavailableError):
        await publish(redis)
    assert redis.info.await_count == 2


@pytest.mark.parametrize("failure", ["unsupported", "unavailable", "shape"])
async def test_unknown_capacity_admits_and_leaves_outages_to_xadd(failure):
    from redis.exceptions import ConnectionError as RedisConnectionError

    if failure == "unsupported":
        redis = fakeredis.FakeAsyncRedis(decode_responses=True)  # no INFO command
        assert await publish(redis)
        assert await redis.xlen("stream:alert") == 1
        return
    redis = AsyncMock()
    redis.info = AsyncMock(side_effect=RedisConnectionError("down")) if failure == "unavailable" else AsyncMock(
        return_value="not-a-mapping")
    redis.xadd = AsyncMock(side_effect=RedisConnectionError("down") if failure == "unavailable" else None,
                           return_value="2-0")
    if failure == "unavailable":
        with pytest.raises(RedisConnectionError):
            await publish(redis)
    else:
        assert await publish(redis) == "2-0"


@pytest.mark.parametrize("version", ["2", "0", "v1", ""])
async def test_publisher_never_emits_an_unsupported_major_version(version):
    redis = memory_redis(1, 100)
    with pytest.raises(ValueError):
        await publish(redis, version=version)
    redis.xadd.assert_not_awaited()
