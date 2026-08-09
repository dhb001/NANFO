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

    with patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm):
        await handle_telemetry_event(_telemetry_event())

    db.commit.assert_awaited_once()
    db.flush.assert_awaited_once()
    db.add.assert_called_once()


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

    with patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm):
        await handle_telemetry_event(_telemetry_event())

    db.commit.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_telemetry_consumer_validation_error_does_not_raise():
    db = AsyncMock()
    db.commit = AsyncMock()

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None

    event = _telemetry_event()
    event["event_id"] = "not-a-uuid"

    with patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm):
        await handle_telemetry_event(event)

    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_telemetry_consumer_sql_error_is_raised_for_retry():
    session_cm = AsyncMock()
    db = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None

    with (
        patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm),
        patch(
            "app.events.consumers.telemetry_consumer.TelemetryPersistenceService.persist_event",
            new=AsyncMock(side_effect=SQLAlchemyError("db down")),
        ),
        pytest.raises(SQLAlchemyError),
    ):
        await handle_telemetry_event(_telemetry_event())
