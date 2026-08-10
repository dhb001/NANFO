"""Integration tests for telemetry ingestion event -> persistence flow (VS2 Step 6)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.events.consumers.telemetry_consumer import (
    handle_telemetry_event,
    handle_telemetry_runtime_transition_event,
)
from app.modules.telemetry.service import TelemetryIngestionService


def _telemetry_event() -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "telemetry.metric.ingested",
        "correlation_id": str(uuid.uuid4()),
        "payload": {
            "device_id": str(uuid.uuid4()),
            "network_id": str(uuid.uuid4()),
            "workspace_id": str(uuid.uuid4()),
            "metric": "latency_ms",
            "value": 12.3,
            "unit": "ms",
            "observed_at": datetime.now(UTC).isoformat(),
            "source": "collector",
            "tags": {"vendor": "test"},
        },
    }


@pytest.mark.asyncio
async def test_ingested_telemetry_event_persists_via_stream_payload(integration_fake_redis):
    await integration_fake_redis.delete(
        "stream:telemetry",
        "stream:dead_letter",
        "telemetry:health:ingested_events",
        "telemetry:health:persisted_events",
        "telemetry:health:fanout_events",
        "telemetry:health:dropped_events",
    )

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

    ingestion = TelemetryIngestionService(redis=integration_fake_redis)
    event = _telemetry_event()
    entry_id = await ingestion.ingest(raw=event["payload"], correlation_id=event["correlation_id"])

    entries = await integration_fake_redis.xrange("stream:telemetry")
    assert len(entries) == 1
    stream_entry_id, fields = entries[0]
    assert stream_entry_id == entry_id
    assert fields["event_type"] == "telemetry.metric.ingested"

    event_data = {**fields, "payload": json.loads(fields["payload"])}

    with (
        patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm),
        patch("app.events.consumers.telemetry_consumer.get_redis_client", return_value=integration_fake_redis),
        patch("app.events.consumers.telemetry_consumer.telemetry_ws_manager") as mock_ws_manager,
    ):
        mock_ws_manager.push_delta = AsyncMock()
        await handle_telemetry_event(event_data)

    db.commit.assert_awaited_once()
    db.add.assert_called_once()
    assert await integration_fake_redis.get("telemetry:health:ingested_events") == "1"
    assert await integration_fake_redis.get("telemetry:health:persisted_events") == "1"
    assert await integration_fake_redis.get("telemetry:health:fanout_events") == "1"
    assert await integration_fake_redis.get("telemetry:health:dropped_events") is None


@pytest.mark.asyncio
async def test_telemetry_persist_failure_then_successful_event_still_commits(integration_fake_redis):
    await integration_fake_redis.delete(
        "stream:telemetry",
        "telemetry:health:ingested_events",
        "telemetry:health:persisted_events",
        "telemetry:health:fanout_events",
        "telemetry:health:dropped_events",
    )

    db = AsyncMock()
    db.commit = AsyncMock()

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None

    ingestion = TelemetryIngestionService(redis=integration_fake_redis)
    first_event = _telemetry_event()
    second_event = _telemetry_event()
    await ingestion.ingest(raw=first_event["payload"], correlation_id=first_event["correlation_id"])
    await ingestion.ingest(raw=second_event["payload"], correlation_id=second_event["correlation_id"])

    entries = await integration_fake_redis.xrange("stream:telemetry")
    assert len(entries) == 2

    first_event_data = {**entries[0][1], "payload": json.loads(entries[0][1]["payload"])}
    second_event_data = {**entries[1][1], "payload": json.loads(entries[1][1]["payload"])}

    with (
        patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm),
        patch("app.events.consumers.telemetry_consumer.get_redis_client", return_value=integration_fake_redis),
        patch(
            "app.events.consumers.telemetry_consumer.TelemetryPersistenceService.persist_event",
            new=AsyncMock(side_effect=SQLAlchemyError("db down")),
        ),
        pytest.raises(SQLAlchemyError),
    ):
        await handle_telemetry_event(first_event_data)

    with (
        patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm),
        patch("app.events.consumers.telemetry_consumer.get_redis_client", return_value=integration_fake_redis),
        patch("app.events.consumers.telemetry_consumer.telemetry_ws_manager") as mock_ws_manager,
        patch(
            "app.events.consumers.telemetry_consumer.TelemetryPersistenceService.persist_event",
            new=AsyncMock(return_value=True),
        ),
    ):
        mock_ws_manager.push_delta = AsyncMock()
        await handle_telemetry_event(second_event_data)

    db.commit.assert_awaited_once()
    assert await integration_fake_redis.get("telemetry:health:ingested_events") == "2"
    assert await integration_fake_redis.get("telemetry:health:persisted_events") == "1"


@pytest.mark.asyncio
async def test_telemetry_fanout_failure_increments_dropped_counter(integration_fake_redis):
    await integration_fake_redis.delete(
        "stream:telemetry",
        "telemetry:health:ingested_events",
        "telemetry:health:persisted_events",
        "telemetry:health:fanout_events",
        "telemetry:health:dropped_events",
    )

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

    ingestion = TelemetryIngestionService(redis=integration_fake_redis)
    event = _telemetry_event()
    await ingestion.ingest(raw=event["payload"], correlation_id=event["correlation_id"])
    entries = await integration_fake_redis.xrange("stream:telemetry")
    event_data = {**entries[0][1], "payload": json.loads(entries[0][1]["payload"])}

    with (
        patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm),
        patch("app.events.consumers.telemetry_consumer.get_redis_client", return_value=integration_fake_redis),
        patch("app.events.consumers.telemetry_consumer.telemetry_ws_manager") as mock_ws_manager,
    ):
        mock_ws_manager.push_delta = AsyncMock(side_effect=RuntimeError("ws unavailable"))
        await handle_telemetry_event(event_data)

    db.commit.assert_awaited_once()
    assert await integration_fake_redis.get("telemetry:health:persisted_events") == "1"
    assert await integration_fake_redis.get("telemetry:health:fanout_events") is None
    assert await integration_fake_redis.get("telemetry:health:dropped_events") == "1"


@pytest.mark.asyncio
async def test_runtime_transition_events_emit_alert_lifecycle_events(integration_fake_redis):
    await integration_fake_redis.delete("stream:alert")

    activated_event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "telemetry.collector.sustained_failure_activated",
        "correlation_id": str(uuid.uuid4()),
        "payload": {
            "exhausted_streak": 3,
            "sustained_failure_threshold": 3,
            "observed_at": datetime.now(UTC).isoformat(),
        },
    }
    recovered_event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "telemetry.collector.sustained_failure_recovered",
        "correlation_id": str(uuid.uuid4()),
        "payload": {
            "exhausted_streak": 3,
            "sustained_failure_threshold": 3,
            "observed_at": datetime.now(UTC).isoformat(),
        },
    }

    with patch("app.events.consumers.telemetry_consumer.get_redis_client", return_value=integration_fake_redis):
        await handle_telemetry_runtime_transition_event(activated_event)
        await handle_telemetry_runtime_transition_event(recovered_event)

    entries = await integration_fake_redis.xrange("stream:alert")
    assert len(entries) == 2
    first_fields = entries[0][1]
    second_fields = entries[1][1]

    assert first_fields["event_type"] == "alert.generated"
    assert second_fields["event_type"] == "alert.resolved"
    assert json.loads(first_fields["payload"]) == activated_event["payload"]
    assert json.loads(second_fields["payload"]) == recovered_event["payload"]
