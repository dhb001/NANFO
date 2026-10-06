"""Unit tests for telemetry event consumer persistence behavior (VS2 Step 6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.events.consumers.telemetry_consumer import (
    TELEMETRY_HANDLERS,
    handle_telemetry_event,
    handle_telemetry_runtime_transition_event,
)


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


def _runtime_transition_event(event_type: str = "telemetry.collector.sustained_failure_activated") -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "correlation_id": str(uuid.uuid4()),
        "payload": {
            "exhausted_streak": 3,
            "sustained_failure_threshold": 3,
            "observed_at": datetime.now(UTC).isoformat(),
        },
    }


@pytest.mark.asyncio
async def test_telemetry_consumer_persists_event_and_commits():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.scalar = AsyncMock(return_value=None)  # No archived-event tombstone.

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
        event = _telemetry_event()
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(return_value=1)
        mock_get_redis.return_value = fake_redis
        mock_ws_manager.push_delta = AsyncMock()
        await handle_telemetry_event(event)

    db.commit.assert_awaited_once()
    db.flush.assert_awaited_once()
    db.add.assert_called_once()
    assert fake_redis.incr.await_count == 2
    mock_ws_manager.push_delta.assert_awaited_once()
    fanout_kwargs = mock_ws_manager.push_delta.call_args.kwargs
    assert fanout_kwargs["event_type"] == "telemetry.metric.ingested"
    assert fanout_kwargs["metric"]["metric"] == "packet_loss"
    assert fanout_kwargs["workspace_id"] == event["payload"]["workspace_id"]


@pytest.mark.asyncio
async def test_telemetry_consumer_duplicate_skips_commit():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    event = _telemetry_event()
    record = {**event["payload"], "event_id": event["event_id"], "correlation_id": event["correlation_id"]}
    for name in ("event_id", "correlation_id", "device_id", "network_id", "workspace_id"):
        record[name] = uuid.UUID(record[name])
    record["observed_at"] = datetime.fromisoformat(record["observed_at"])
    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = SimpleNamespace(**record)
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
        await handle_telemetry_event(event)

    db.commit.assert_not_awaited()
    db.add.assert_not_called()
    fake_redis.incr.assert_not_awaited()
    mock_ws_manager.push_delta.assert_awaited_once()


@pytest.mark.asyncio
async def test_telemetry_consumer_validation_error_raises_for_dlq():
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
        with pytest.raises(ValueError):
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
async def test_telemetry_consumer_fanout_failure_after_commit_is_acknowledged():
    """Regression: a WS fanout failure after commit retried/dead-lettered durable telemetry."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

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
        patch("app.events.consumers.telemetry_consumer.logger") as mock_logger,
    ):
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(side_effect=[1, 1])
        mock_get_redis.return_value = fake_redis
        mock_ws_manager.push_delta = AsyncMock(side_effect=RuntimeError("ws down secret-token"))
        await handle_telemetry_event(_telemetry_event())  # returns -> the bus acknowledges

    db.commit.assert_awaited_once()
    assert fake_redis.incr.await_count == 2  # persisted + dropped (never fanout)
    incremented = [call.args[0] for call in fake_redis.incr.await_args_list]
    assert incremented == ["telemetry:health:persisted_events", "telemetry:health:dropped_events"]
    failure = next(call for call in mock_logger.warning.call_args_list if call.args[0] == "telemetry_ws_fanout_failed")
    assert failure.kwargs["error_code"] == "TELEMETRY_FANOUT_FAILED"
    assert failure.kwargs["error_type"] == "RuntimeError"
    assert "secret-token" not in str(failure)


@pytest.mark.asyncio
async def test_duplicate_replay_fanout_failure_is_best_effort():
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    event = _telemetry_event()
    record = {**event["payload"], "event_id": event["event_id"], "correlation_id": event["correlation_id"]}
    for name in ("event_id", "correlation_id", "device_id", "network_id", "workspace_id"):
        record[name] = uuid.UUID(record[name])
    record["observed_at"] = datetime.fromisoformat(record["observed_at"])
    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = SimpleNamespace(**record)
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
        mock_ws_manager.push_delta = AsyncMock(side_effect=ConnectionError("ws down"))
        await handle_telemetry_event(event)
    fake_redis.incr.assert_awaited_once_with("telemetry:health:dropped_events")


@pytest.mark.asyncio
async def test_runtime_transition_activation_publishes_alert_generated():
    event = _runtime_transition_event("telemetry.collector.sustained_failure_activated")
    payload = event["payload"]

    with (
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
        patch("app.events.consumers.telemetry_consumer.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        fake_redis = AsyncMock()
        mock_get_redis.return_value = fake_redis
        mock_publish.return_value = "501-0"

        await handle_telemetry_runtime_transition_event(event)

    mock_publish.assert_awaited_once()
    publish_kwargs = mock_publish.await_args.kwargs
    assert publish_kwargs["redis"] is fake_redis
    assert publish_kwargs["event_type"] == "alert.generated"
    assert publish_kwargs["source"] == "telemetry"
    assert publish_kwargs["payload"] == payload
    assert publish_kwargs["correlation_id"] == event["correlation_id"]
    assert publish_kwargs["event_id"] == str(uuid.uuid5(
        uuid.NAMESPACE_URL, f"{event['event_id']}:alert.generated",
    ))


@pytest.mark.asyncio
async def test_runtime_transition_recovery_publishes_alert_resolved():
    event = _runtime_transition_event("telemetry.collector.sustained_failure_recovered")

    with (
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
        patch("app.events.consumers.telemetry_consumer.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get_redis.return_value = AsyncMock()
        mock_publish.return_value = "502-0"

        await handle_telemetry_runtime_transition_event(event)

    mock_publish.assert_awaited_once()
    assert mock_publish.await_args.kwargs["event_type"] == "alert.resolved"


@pytest.mark.asyncio
async def test_runtime_transition_publish_failure_propagates():
    event = _runtime_transition_event("telemetry.collector.sustained_failure_activated")

    with (
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
        patch("app.events.consumers.telemetry_consumer.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get_redis.return_value = AsyncMock()
        mock_publish.side_effect = RuntimeError("redis publish failed")

        with pytest.raises(RuntimeError, match="redis publish failed"):
            await handle_telemetry_runtime_transition_event(event)

    mock_publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_transition_client_unavailable_propagates():
    event = _runtime_transition_event("telemetry.collector.sustained_failure_activated")

    with (
        patch(
            "app.events.consumers.telemetry_consumer.get_redis_client",
            side_effect=RuntimeError("redis unavailable"),
        ),
        patch("app.events.consumers.telemetry_consumer.publish_event", new_callable=AsyncMock) as mock_publish,
        pytest.raises(RuntimeError, match="redis unavailable"),
    ):
        await handle_telemetry_runtime_transition_event(event)

    mock_publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_transition_opaque_correlation_id_maps_deterministically():
    from app.core.correlation import correlation_uuid

    event = _runtime_transition_event("telemetry.collector.sustained_failure_activated")
    event["correlation_id"] = "invalid-correlation-id"

    with (
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
        patch("app.events.consumers.telemetry_consumer.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get_redis.return_value = AsyncMock()
        mock_publish.return_value = "503-0"

        await handle_telemetry_runtime_transition_event(event)
        await handle_telemetry_runtime_transition_event(event)

    first, second = (call.kwargs["correlation_id"] for call in mock_publish.await_args_list)
    # The shared ADR-028 mapping, identical on every retry (was a random uuid4).
    assert first == second == str(correlation_uuid("invalid-correlation-id"))


@pytest.mark.asyncio
async def test_runtime_transition_missing_correlation_derives_from_event_identity():
    event = _runtime_transition_event("telemetry.collector.sustained_failure_recovered")
    event.pop("correlation_id")
    with (
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
        patch("app.events.consumers.telemetry_consumer.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get_redis.return_value = AsyncMock()
        await handle_telemetry_runtime_transition_event(event)
        await handle_telemetry_runtime_transition_event(event)
    first, second = (call.kwargs["correlation_id"] for call in mock_publish.await_args_list)
    assert first == second and uuid.UUID(first)


@pytest.mark.asyncio
async def test_runtime_transition_non_dict_payload_falls_back_to_empty_object():
    event = _runtime_transition_event("telemetry.collector.sustained_failure_activated")
    event["payload"] = "not-an-object"

    with (
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
        patch("app.events.consumers.telemetry_consumer.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get_redis.return_value = AsyncMock()
        mock_publish.return_value = "504-0"

        await handle_telemetry_runtime_transition_event(event)

    assert mock_publish.await_args.kwargs["payload"] == {}


@pytest.mark.asyncio
async def test_runtime_transition_unmapped_event_is_noop():
    with (
        patch("app.events.consumers.telemetry_consumer.get_redis_client") as mock_get_redis,
        patch("app.events.consumers.telemetry_consumer.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        await handle_telemetry_runtime_transition_event(
            _runtime_transition_event("telemetry.collector.unknown_transition")
        )

    mock_get_redis.assert_not_called()
    mock_publish.assert_not_awaited()


def test_telemetry_handlers_include_runtime_transition_events():
    assert "telemetry.collector.sustained_failure_activated" in TELEMETRY_HANDLERS
    assert "telemetry.collector.sustained_failure_recovered" in TELEMETRY_HANDLERS
    assert TELEMETRY_HANDLERS["telemetry.collector.sustained_failure_activated"] is handle_telemetry_runtime_transition_event
    assert TELEMETRY_HANDLERS["telemetry.collector.sustained_failure_recovered"] is handle_telemetry_runtime_transition_event
