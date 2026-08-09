"""Unit tests for telemetry event consumer persistence behavior (VS2 Step 6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.events.consumers.telemetry_consumer import handle_telemetry_event


def _telemetry_event() -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "telemetry.metric.ingested",
        "correlation_id": str(uuid.uuid4()),
        "payload": {
            "device_id": str(uuid.uuid4()),
            "network_id": str(uuid.uuid4()),
            "workspace_id": str(uuid.uuid4()),
            "metric": "packet_loss",
            "value": 0.02,
            "unit": "ratio",
            "observed_at": datetime.now(UTC).isoformat(),
            "source": "collector",
            "tags": {},
        },
    }


@pytest.mark.asyncio
async def test_telemetry_consumer_persists_event_and_commits():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=query_result)

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None

    with (
        patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm),
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
        patch("app.events.consumers.telemetry_consumer.telemetry_ws_manager") as mock_ws_manager,
    ):
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(return_value=1)
        mock_get_redis.return_value = fake_redis
        mock_ws_manager.push_delta = AsyncMock()
        await handle_telemetry_event(_telemetry_event())

    db.commit.assert_awaited_once()
    db.flush.assert_awaited_once()
    db.add.assert_called_once()
    assert fake_redis.incr.await_count == 2
    mock_ws_manager.push_delta.assert_awaited_once()
    fanout_kwargs = mock_ws_manager.push_delta.call_args.kwargs
    assert fanout_kwargs["event_type"] == "telemetry.metric.ingested"
    assert fanout_kwargs["metric"]["metric"] == "packet_loss"


@pytest.mark.asyncio
async def test_telemetry_consumer_duplicate_skips_commit():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = object()
    db.execute = AsyncMock(return_value=query_result)

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None

    with (
        patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm),
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
        patch("app.events.consumers.telemetry_consumer.telemetry_ws_manager") as mock_ws_manager,
    ):
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(return_value=1)
        mock_get_redis.return_value = fake_redis
        mock_ws_manager.push_delta = AsyncMock()
        await handle_telemetry_event(_telemetry_event())

    db.commit.assert_not_awaited()
    db.add.assert_not_called()
    fake_redis.incr.assert_not_awaited()
    mock_ws_manager.push_delta.assert_not_awaited()


@pytest.mark.asyncio
async def test_telemetry_consumer_validation_error_does_not_raise():
    db = AsyncMock()
    db.commit = AsyncMock()

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None

    event = _telemetry_event()
    event["event_id"] = "not-a-uuid"

    with (
        patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm),
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
    ):
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(return_value=1)
        mock_get_redis.return_value = fake_redis
        await handle_telemetry_event(event)

    db.commit.assert_not_awaited()
    fake_redis.incr.assert_awaited_once()


@pytest.mark.asyncio
async def test_telemetry_consumer_sql_error_is_raised_for_retry():
    session_cm = AsyncMock()
    db = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None

    with (
        patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm),
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
        patch(
            "app.events.consumers.telemetry_consumer.TelemetryPersistenceService.persist_event",
            new=AsyncMock(side_effect=SQLAlchemyError("db down")),
        ),
        pytest.raises(SQLAlchemyError),
    ):
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(return_value=1)
        mock_get_redis.return_value = fake_redis
        await handle_telemetry_event(_telemetry_event())

    fake_redis.incr.assert_not_awaited()


@pytest.mark.asyncio
async def test_telemetry_consumer_fanout_failure_increments_dropped_and_does_not_raise():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=query_result)

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None

    with (
        patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm),
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
        patch("app.events.consumers.telemetry_consumer.telemetry_ws_manager") as mock_ws_manager,
    ):
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(side_effect=[1, 1])
        mock_get_redis.return_value = fake_redis
        mock_ws_manager.push_delta = AsyncMock(side_effect=RuntimeError("ws down"))
        await handle_telemetry_event(_telemetry_event())

    db.commit.assert_awaited_once()
    assert fake_redis.incr.await_count == 2
