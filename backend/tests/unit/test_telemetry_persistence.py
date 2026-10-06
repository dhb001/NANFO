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


# ---------------------------------------------------------------- ADR-028 timestamp bounds


@pytest.mark.asyncio
@pytest.mark.parametrize("observed_at,message", [
    ("2026-09-08T00:00:00", "explicit UTC offset"),      # naive: was silently assumed UTC
    (datetime(2026, 9, 8), "explicit UTC offset"),
    ("2999-01-01T00:00:00+00:00", "too far in the future"),
    ("not-a-date", "invalid datetime"),
    (None, "required"),
])
async def test_persist_rejects_naive_future_and_invalid_timestamps(mock_db, observed_at, message):
    svc = TelemetryPersistenceService(db=mock_db)
    svc._repo.get_by_event_id = AsyncMock(return_value=None)
    svc._repo.create = AsyncMock()
    event = _valid_event()
    event["payload"]["observed_at"] = observed_at
    with pytest.raises(ValueError, match=message):
        await svc.persist_event(event)
    svc._repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_normalizes_offsets_and_allows_bounded_skew(mock_db):
    from datetime import timedelta

    from app.modules.telemetry.validation import MAX_FUTURE_SKEW

    svc = TelemetryPersistenceService(db=mock_db)
    svc._repo.get_by_event_id = AsyncMock(return_value=None)
    svc._repo.create = AsyncMock()
    event = _valid_event()
    event["payload"]["observed_at"] = "2026-09-08T03:00:00+03:00"
    await svc.persist_event(event)
    assert svc._repo.create.await_args.kwargs["observed_at"] == datetime(2026, 9, 8, tzinfo=UTC)
    event = _valid_event()
    event["payload"]["observed_at"] = (datetime.now(UTC) + MAX_FUTURE_SKEW - timedelta(seconds=5)).isoformat()
    assert await svc.persist_event(event) is True
