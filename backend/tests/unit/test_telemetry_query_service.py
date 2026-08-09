"""Unit tests for telemetry read/query service logic (VS2 Step 7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.telemetry.service import TelemetryQueryService


def _make_row(metric: str, device_id: uuid.UUID | None = None) -> MagicMock:
    row = MagicMock()
    row.record_id = uuid.uuid4()
    row.event_id = uuid.uuid4()
    row.correlation_id = uuid.uuid4()
    row.device_id = device_id or uuid.uuid4()
    row.network_id = uuid.uuid4()
    row.workspace_id = uuid.uuid4()
    row.metric = metric
    row.value = 42.0
    row.unit = "percent"
    row.observed_at = datetime.now(UTC)
    row.source = "collector"
    row.tags = {"vendor": "test"}
    row.created_at = datetime.now(UTC)
    return row


@pytest.mark.asyncio
async def test_get_history_returns_paginated_response(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    row = _make_row(metric="cpu_usage")

    svc._repo.list_history = AsyncMock(return_value=([row], 1))

    result = await svc.get_history(
        network_id=None,
        workspace_id=None,
        metric=None,
        page=1,
        page_size=50,
    )

    assert result.total == 1
    assert result.page == 1
    assert result.page_size == 50
    assert len(result.items) == 1
    assert result.items[0].metric == "cpu_usage"


@pytest.mark.asyncio
async def test_get_device_history_returns_device_scoped_records(mock_db):
    svc = TelemetryQueryService(db=mock_db)
    device_id = uuid.uuid4()

    row = _make_row(metric="latency_ms", device_id=device_id)
    row.value = 12.3
    row.unit = "ms"
    row.tags = {}

    svc._repo.list_for_device = AsyncMock(return_value=([row], 1))

    result = await svc.get_device_history(
        device_id=device_id,
        metric=None,
        page=1,
        page_size=20,
    )

    assert result.device_id == device_id
    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].metric == "latency_ms"


@pytest.mark.asyncio
async def test_get_health_returns_zero_when_no_records(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 2,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    result = await svc.get_health()

    assert result.status == "ok"
    assert result.ingest_lag_ms == 0
    assert result.dropped_events == 2
    assert result.latest_observed_at is None
    assert result.total_records == 0


@pytest.mark.asyncio
async def test_get_health_returns_positive_lag(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 4,
            "persisted_events": 4,
            "fanout_events": 4,
            "dropped_events": 1,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    observed_at = datetime.now(UTC) - timedelta(seconds=3)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=observed_at)
    svc._repo.count_all = AsyncMock(return_value=15)

    result = await svc.get_health()

    assert result.status == "ok"
    assert result.ingest_lag_ms >= 0
    assert result.dropped_events == 1
    assert result.total_records == 15
    assert result.latest_observed_at == observed_at


@pytest.mark.asyncio
async def test_get_health_falls_back_to_zero_counters_on_counter_failure(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(side_effect=RuntimeError("redis unavailable"))
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    observed_at = datetime.now(UTC)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=observed_at)
    svc._repo.count_all = AsyncMock(return_value=1)

    result = await svc.get_health()

    assert result.status == "ok"
    assert result.dropped_events == 0
