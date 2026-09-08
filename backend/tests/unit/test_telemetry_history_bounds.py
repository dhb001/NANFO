"""Bounded telemetry query/schema regressions; no external services."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.modules.telemetry.repository import TelemetryRecordRepository
from app.modules.telemetry.schemas import TelemetryHistoryQuery, TelemetryTimeRange
from app.modules.telemetry.service import TelemetryQueryService

START = datetime(2026, 9, 8, tzinfo=UTC)


@pytest.mark.parametrize("values", [
    {"start_time": "2026-09-08T00:00:00"},
    {"end_time": "2026-09-08"},
    {"start_time": START, "end_time": START},
    {"start_time": START, "end_time": START - timedelta(seconds=1)},
    {"aggregation": "median"},
    {"aggregation": "avg"},
    {"bucket_seconds": 60},
    {"aggregation": "avg", "metric": " "},
    {"aggregation": "avg", "metric": "cpu", "start_time": START,
     "end_time": START + timedelta(days=7, microseconds=1), "bucket_seconds": 60},
    {"bucket_seconds": 0}, {"bucket_seconds": 86401}, {"bucket_seconds": 1.5},
])
def test_invalid_history_queries(values):
    with pytest.raises(ValidationError):
        TelemetryHistoryQuery(**values)


@pytest.mark.parametrize("aggregation", ["avg", "min", "max", "sum"])
@pytest.mark.parametrize("bucket", [1, 86400])
def test_aggregation_accepts_exact_seven_days(aggregation, bucket):
    query = TelemetryHistoryQuery(
        metric="queue_backlog_bytes", aggregation=aggregation, bucket_seconds=bucket,
        start_time=START, end_time=START + timedelta(days=7),
    )
    assert query.bucket_seconds == bucket


def test_time_range_normalizes_offsets_and_allows_single_bounds():
    assert TelemetryTimeRange(start_time="2026-09-08T03:00:00+03:00").start_time == START
    assert TelemetryTimeRange(end_time=START).start_time is None
    assert TelemetryHistoryQuery().aggregation is None


@pytest.mark.parametrize("device", [False, True])
async def test_raw_bounds_filter_both_sql_queries_with_stable_order(mock_db, device):
    count, result = MagicMock(), MagicMock()
    count.scalar_one.return_value = 0
    result.scalars.return_value.all.return_value = []
    mock_db.execute.side_effect = [count, result]
    scope = {"network_id": uuid.uuid4(), "workspace_id": uuid.uuid4()}
    repo = TelemetryRecordRepository(mock_db)
    method = repo.list_history
    if device:
        method = repo.list_for_device
        scope["device_id"] = uuid.uuid4()
    assert await method(**scope, start_time=START, end_time=START + timedelta(hours=1), page=3, page_size=2) == ([], 0)
    for call in mock_db.execute.call_args_list:
        sql = str(call.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        assert "observed_at >=" in sql and "observed_at <" in sql
        for value in scope.values():
            assert str(value) in sql
    assert "ORDER BY telemetry_records.observed_at DESC, telemetry_records.record_id DESC" in sql
    assert "LIMIT 2 OFFSET 4" in sql


@pytest.mark.parametrize("aggregation", ["avg", "min", "max", "sum"])
async def test_aggregation_is_sql_grouped_and_paginated(mock_db, aggregation):
    count, result = MagicMock(), MagicMock()
    count.scalar_one.return_value = 5
    result.mappings.return_value.all.return_value = []
    mock_db.execute.side_effect = [count, result]
    rows, total = await TelemetryRecordRepository(mock_db).list_history(
        workspace_id=uuid.uuid4(), metric="queue_backlog_bytes", aggregation=aggregation,
        start_time=START, end_time=START + timedelta(hours=1), bucket_seconds=60, page=4, page_size=2,
    )
    assert rows == [] and total == 5  # Out-of-range pages retain the group total.
    for call in mock_db.execute.call_args_list:
        sql = str(call.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        assert f"{aggregation}(telemetry_records.value)" in sql
        assert "GROUP BY telemetry_records.device_id, telemetry_records.metric, telemetry_records.unit, telemetry_records.source" in sql
        assert "tags ->> 'port_no'" in sql
        assert "tags ->> 'peer_host'" in sql
        assert "tags ->> 'run_id'" in sql
        assert "observed_at >=" in sql and "observed_at <" in sql
    assert "LIMIT 2 OFFSET 6" in sql
    result.scalars.assert_not_called()


@pytest.mark.parametrize("metric", ["flow_byte_count", "flow_packet_count", "flow_future_counter"])
async def test_flow_aggregation_rejected_but_raw_query_allowed(mock_db, metric):
    with pytest.raises(ValidationError, match="no durable flow match identity"):
        await TelemetryRecordRepository(mock_db).list_history(
            metric=metric, aggregation="sum", bucket_seconds=60,
            start_time=START, end_time=START + timedelta(hours=1),
        )
    mock_db.execute.assert_not_awaited()
    assert TelemetryHistoryQuery(metric=metric).metric == metric


async def test_query_service_forwards_bounds_and_aggregation(mock_db):
    svc = TelemetryQueryService(mock_db)
    svc._repo.list_history = AsyncMock(return_value=([], 4))
    svc._repo.list_for_device = AsyncMock(return_value=([], 0))
    scope = {"network_id": uuid.uuid4(), "workspace_id": uuid.uuid4(), "metric": "queue_backlog_bytes", "page": 2, "page_size": 2}
    bounds = {"start_time": START, "end_time": START + timedelta(hours=1)}
    result = await svc.get_history(**scope, **bounds, aggregation="sum", bucket_seconds=60)
    assert result.total == 4
    svc._repo.list_history.assert_awaited_once_with(**scope, **bounds, aggregation="sum", bucket_seconds=60)
    device_id = uuid.uuid4()
    await svc.get_device_history(**scope, **bounds, device_id=device_id)
    svc._repo.list_for_device.assert_awaited_once_with(**scope, **bounds, device_id=device_id)
