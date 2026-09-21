"""Unit tests for telemetry persistence baseline (VS2 Step 6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.modules.telemetry.service import TelemetryPersistenceService


@pytest.fixture(autouse=True)
def no_archived_events(mock_db):
    mock_db.scalar.return_value = None


def _valid_event() -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "telemetry.metric.ingested",
        "correlation_id": str(uuid.uuid4()),
        "payload": {
            "device_id": str(uuid.uuid4()),
            "network_id": str(uuid.uuid4()),
            "workspace_id": str(uuid.uuid4()),
            "metric": "cpu_usage",
            "value": 42.5,
            "unit": "percent",
            "observed_at": datetime.now(UTC).isoformat(),
            "source": "collector",
            "tags": {"vendor": "test"},
        },
    }


@pytest.mark.asyncio
async def test_persist_event_creates_record_when_not_duplicate(mock_db):
    svc = TelemetryPersistenceService(db=mock_db)

    svc._repo.get_by_event_id = AsyncMock(return_value=None)
    svc._repo.create = AsyncMock()

    persisted = await svc.persist_event(_valid_event())

    assert persisted is True
    svc._repo.get_by_event_id.assert_awaited_once()
    svc._repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_event_returns_false_for_duplicate(mock_db):
    svc = TelemetryPersistenceService(db=mock_db)

    svc._repo.get_by_event_id = AsyncMock(return_value=object())
    svc._repo.create = AsyncMock()

    persisted = await svc.persist_event(_valid_event())

    assert persisted is False
    svc._repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_event_raises_value_error_for_invalid_payload(mock_db):
    svc = TelemetryPersistenceService(db=mock_db)
    event = _valid_event()
    event["payload"]["value"] = "not-a-number"

    svc._repo.get_by_event_id = AsyncMock(return_value=None)

    with pytest.raises(ValueError):
        await svc.persist_event(event)


@pytest.mark.asyncio
async def test_persist_event_raises_type_error_for_non_dict_payload(mock_db):
    svc = TelemetryPersistenceService(db=mock_db)
    event = _valid_event()
    event["payload"] = "invalid"

    svc._repo.get_by_event_id = AsyncMock(return_value=None)

    with pytest.raises(TypeError):
        await svc.persist_event(event)
