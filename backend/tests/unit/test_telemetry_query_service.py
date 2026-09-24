"""Telemetry read service: history pages and the read-only health view (ADR-028 C12)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.health import TOTAL_RECORDS_CACHE_KEY, TOTAL_RECORDS_CACHE_SECONDS
from app.modules.telemetry.service import TelemetryQueryService
from app.modules.telemetry.slo.evaluator import TelemetrySLOEvaluator
from app.modules.telemetry.slo.store import STATE_KEY, TelemetrySLOSettings
from app.modules.telemetry.validation import MAX_FUTURE_SKEW


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


def _health_service(mock_db, fake_redis, *, latest=None, total=(0, False)):
    svc = TelemetryQueryService(db=mock_db, counter_service=TelemetryHealthCounterService(fake_redis))
    svc._repo.get_latest_observed_at = AsyncMock(return_value=latest)
    svc._repo.estimate_total_records = AsyncMock(return_value=total)
    return svc


@pytest.mark.asyncio
async def test_get_history_returns_paginated_response(mock_db):
    svc = TelemetryQueryService(db=mock_db)
    svc._repo.list_history = AsyncMock(return_value=([_make_row(metric="cpu_usage")], 1))
    result = await svc.get_history(network_id=None, workspace_id=None, metric=None, page=1, page_size=50)
    assert (result.total, result.page, result.page_size, result.total_capped) == (1, 1, 50, False)
    assert result.items[0].metric == "cpu_usage"


@pytest.mark.asyncio
@pytest.mark.parametrize("counted,expected", [(10_001, (10_000, True)), (10_000, (10_000, False)), (7, (7, False))])
async def test_history_totals_are_capped_only_when_requested(mock_db, counted, expected):
    svc = TelemetryQueryService(db=mock_db)
    svc._repo.list_history = AsyncMock(return_value=([], counted))
    svc._repo.list_for_device = AsyncMock(return_value=([], counted))
    result = await svc.get_history(network_id=None, workspace_id=uuid.uuid4(), metric=None, page=3,
                                   page_size=50, count_cap=10_000)
    assert (result.total, result.total_capped) == expected
    assert svc._repo.list_history.await_args.kwargs["count_cap"] == 10_000
    device = await svc.get_device_history(device_id=uuid.uuid4(), network_id=uuid.uuid4(),
                                          workspace_id=uuid.uuid4(), metric=None, page=1, page_size=5,
                                          count_cap=10_000)
    assert (device.total, device.total_capped) == expected
    # Internal owners (report/alert/autonomy) keep exact totals by default.
    exact = await svc.get_history(network_id=None, workspace_id=uuid.uuid4(), metric=None, page=1, page_size=5)
    assert exact.total == counted and not exact.total_capped
    assert "count_cap" not in svc._repo.list_history.await_args.kwargs


@pytest.mark.asyncio
async def test_get_device_history_returns_device_scoped_records(mock_db):
    svc = TelemetryQueryService(db=mock_db)
    device_id = uuid.uuid4()
    row = _make_row(metric="latency_ms", device_id=device_id)
    svc._repo.list_for_device = AsyncMock(return_value=([row], 1))
    result = await svc.get_device_history(device_id=device_id, network_id=row.network_id,
                                          workspace_id=row.workspace_id, metric=None, page=1, page_size=20)
    assert result.device_id == device_id and result.total == 1
    assert result.items[0].metric == "latency_ms"


@pytest.mark.asyncio
async def test_get_health_returns_unavailable_and_null_lag_when_no_records(mock_db, fake_redis):
    for _ in range(2):
        await TelemetryHealthCounterService(fake_redis).increment_dropped()
    result = await _health_service(mock_db, fake_redis).get_health()
    assert result.status == "unavailable" and result.ingest_lag_ms is None
    assert result.dropped_events == 2 and result.latest_observed_at is None and result.total_records == 0
    assert result.slo.status == "unavailable" and result.slo.stale is True


@pytest.mark.asyncio
async def test_get_health_returns_positive_lag_and_excludes_future_rows(mock_db, fake_redis):
    latest = datetime.now(UTC) - timedelta(seconds=5)
    svc = _health_service(mock_db, fake_redis, latest=latest, total=(12, False))
    before = datetime.now(UTC)
    result = await svc.get_health()
    assert result.status == "ok" and result.ingest_lag_ms >= 5000 and result.total_records == 12
    bound = svc._repo.get_latest_observed_at.await_args.kwargs["not_after"]
    assert before + MAX_FUTURE_SKEW <= bound <= datetime.now(UTC) + MAX_FUTURE_SKEW


@pytest.mark.asyncio
async def test_get_health_degraded_when_runtime_sustained_failure_active(mock_db, fake_redis):
    await TelemetryHealthCounterService(fake_redis).set_runtime_sustained_failure_active(True)
    result = await _health_service(mock_db, fake_redis, latest=datetime.now(UTC)).get_health()
    assert result.status == "degraded"


@pytest.mark.asyncio
async def test_get_health_falls_back_to_zero_counters_on_counter_failure(mock_db):
    counters = MagicMock(redis=MagicMock())
    counters.get_snapshot = AsyncMock(side_effect=RuntimeError("redis unavailable"))
    svc = TelemetryQueryService(db=mock_db, counter_service=counters)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    result = await svc.get_health()
    assert result.status == "unavailable" and result.dropped_events == 0 and result.slo is None


@pytest.mark.asyncio
async def test_health_is_read_only_and_never_publishes_or_evaluates(mock_db, fake_redis):
    """Regression (C12): health used to publish alert.generated into the last-ingesting tenant."""
    counters = TelemetryHealthCounterService(fake_redis)
    for _ in range(10):
        await counters.increment_runtime_adapter_ingest_failure()
        await counters.increment_runtime_adapter_dropped_sample()
    await counters.set_runtime_sustained_failure_active(True)
    svc = _health_service(mock_db, fake_redis, latest=datetime.now(UTC), total=(3, False))
    with patch("app.events.publisher.publish_event", new_callable=AsyncMock) as publish:
        for _ in range(5):
            result = await svc.get_health()
    publish.assert_not_awaited()
    assert await fake_redis.xlen("stream:alert") == 0
    assert await fake_redis.get(STATE_KEY) is None
    snapshot = await counters.get_snapshot()
    assert snapshot["runtime_adapter_anomaly_streak"] == 0 and snapshot["runtime_adapter_slo_alert_active"] == 0
    assert result.slo.status == "unavailable"


@pytest.mark.asyncio
async def test_health_projects_collector_evaluated_slo_state(mock_db, fake_redis):
    counters = TelemetryHealthCounterService(fake_redis)
    await counters.set_runtime_sustained_failure_active(True)
    now = datetime.now(UTC)
    slo = TelemetrySLOEvaluator(redis=fake_redis, counter_service=counters, clock=lambda: now,
                                settings=TelemetrySLOSettings(interval_seconds=30))
    await slo.maybe_evaluate()
    result = await _health_service(mock_db, fake_redis, latest=now).get_health()
    assert result.slo.status == "critical" and result.slo.alert_active
    assert result.slo.severity_reason == "runtime_sustained_failure_active"
    assert result.slo.evaluated_at == now and result.slo.stale is False
    assert result.slo.window.ingest_failures == 0 and result.slo.trend.window_size == 1
    assert result.slo.thresholds["anomaly_streak_critical_threshold"] == 3


@pytest.mark.asyncio
async def test_health_total_is_cached_for_at_least_sixty_seconds(mock_db, fake_redis):
    svc = _health_service(mock_db, fake_redis, latest=datetime.now(UTC), total=(5_000_000, True))
    first = await svc.get_health()
    second = await svc.get_health()
    assert first.total_records == second.total_records == 5_000_000
    assert first.total_records_estimated is True
    svc._repo.estimate_total_records.assert_awaited_once()
    assert TOTAL_RECORDS_CACHE_SECONDS >= 60
    assert 0 < await fake_redis.ttl(TOTAL_RECORDS_CACHE_KEY) <= TOTAL_RECORDS_CACHE_SECONDS


@pytest.mark.asyncio
async def test_health_total_cache_failure_falls_back_to_database(mock_db):
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=ConnectionError("down"))
    redis.set = AsyncMock(side_effect=ConnectionError("down"))
    counters = MagicMock(redis=redis)
    counters.get_snapshot = AsyncMock(return_value={"dropped_events": 0})
    svc = TelemetryQueryService(db=mock_db, counter_service=counters)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=datetime.now(UTC))
    svc._repo.estimate_total_records = AsyncMock(return_value=(9, False))
    result = await svc.get_health()
    assert result.total_records == 9 and result.status == "ok"


def test_event_redis_argument_is_accepted_but_unused(mock_db):
    svc = TelemetryQueryService(db=mock_db, counter_service=None, event_redis=MagicMock())
    assert not hasattr(svc, "_event_redis")
