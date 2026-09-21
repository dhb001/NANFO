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
