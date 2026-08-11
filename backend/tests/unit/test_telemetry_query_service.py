"""Unit tests for telemetry read/query service logic (VS2 Step 7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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


def _event_calls(mock_logger: MagicMock, event_name: str) -> list:
    return [
        call for call in mock_logger.call_args_list if call.args and call.args[0] == event_name
    ]


def _trend_window_summary(
    *,
    window_size: int,
    severity_transition_counts: dict[str, int] | None = None,
    anomaly_reason_frequency: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "window_size": window_size,
        "severity_transition_counts": severity_transition_counts or {},
        "anomaly_reason_frequency": anomaly_reason_frequency or {},
    }


def _append_correlation_window_entry(
    svc: TelemetryQueryService,
    *,
    window_size: int,
    transition_phase: str,
    reason_phase: str,
    transition_threshold_crossed: bool,
    transition_cooldown_active: bool,
    transition_next_emit_in_reads: int,
    reason_threshold_crossed: bool,
    reason_cooldown_active: bool,
    reason_next_emit_in_reads: int,
    transition_max_observed_value: int,
    reason_max_observed_value: int,
    transition_recovery_transition: bool = False,
    reason_recovery_transition: bool = False,
    transition_cooldown_re_emitted: bool = False,
    reason_cooldown_re_emitted: bool = False,
) -> None:
    transition_reads_since_last_crossed_emit = (
        max(3 - transition_next_emit_in_reads, 0) if transition_threshold_crossed else 0
    )
    reason_reads_since_last_crossed_emit = (
        max(3 - reason_next_emit_in_reads, 0) if reason_threshold_crossed else 0
    )

    svc._append_runtime_adapter_slo_trend_threshold_correlation_window_entry(
        trend_window_summary=_trend_window_summary(window_size=window_size),
        latest_threshold_trigger_state={
            "transition_frequency": {
                "threshold_dimension": "transition_frequency",
                "threshold_value": 3,
                "max_observed_value": transition_max_observed_value,
                "crossed_values": (
                    {"ok->degraded": transition_max_observed_value}
                    if transition_threshold_crossed
                    else {}
                ),
                "threshold_crossed": transition_threshold_crossed,
                "recovery_transition": transition_recovery_transition,
                "cooldown_re_emitted": transition_cooldown_re_emitted,
                "window_size": window_size,
            },
            "reason_frequency": {
                "threshold_dimension": "reason_frequency",
                "threshold_value": 3,
                "max_observed_value": reason_max_observed_value,
                "crossed_values": (
                    {"ingest_failures_detected": reason_max_observed_value}
                    if reason_threshold_crossed
                    else {}
                ),
                "threshold_crossed": reason_threshold_crossed,
                "recovery_transition": reason_recovery_transition,
                "cooldown_re_emitted": reason_cooldown_re_emitted,
                "window_size": window_size,
            },
        },
        cooldown_transition_phase={
            "transition_frequency": transition_phase,
            "reason_frequency": reason_phase,
        },
        cooldown_summary={
            "transition_frequency": {
                "initialized": True,
                "threshold_crossed": transition_threshold_crossed,
                "reads_since_last_crossed_emit": transition_reads_since_last_crossed_emit,
                "next_crossed_emit_in_reads": transition_next_emit_in_reads,
                "cooldown_active": transition_cooldown_active,
            },
            "reason_frequency": {
                "initialized": True,
                "threshold_crossed": reason_threshold_crossed,
                "reads_since_last_crossed_emit": reason_reads_since_last_crossed_emit,
                "next_crossed_emit_in_reads": reason_next_emit_in_reads,
                "cooldown_active": reason_cooldown_active,
            },
        },
    )


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
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
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
async def test_get_health_logs_runtime_adapter_slo_snapshot(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 7,
            "persisted_events": 7,
            "fanout_events": 6,
            "dropped_events": 1,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 12,
            "runtime_adapter_invalid_samples": 2,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 10,
            "runtime_adapter_ingest_failures": 1,
            "runtime_adapter_anomaly_streak": 0,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch("app.modules.telemetry.service.logger.info") as mock_info,
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        result = await svc.get_health()

    assert result.status == "ok"
    snapshot_logs = _event_calls(mock_info, "telemetry_health_runtime_adapter_slo_snapshot")
    assert len(snapshot_logs) == 1
    info_kwargs = snapshot_logs[0].kwargs
    assert info_kwargs["last_batch_size"] == 12
    assert info_kwargs["invalid_samples"] == 2
    assert info_kwargs["dropped_samples"] == 0
    assert info_kwargs["ingest_attempts"] == 10
    assert info_kwargs["ingest_failures"] == 1
    assert info_kwargs["status"] == "ok"
    assert info_kwargs["dropped_events"] == 1
    ingest_failure_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_ingest_failures_detected"
    )
    assert len(ingest_failure_logs) == 1
    transition_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(transition_logs) == 1
    transition_log = transition_logs[0]
    assert transition_log.kwargs["previous_streak"] == 0
    assert transition_log.kwargs["current_streak"] == 1
    assert transition_log.kwargs["anomaly_reason_flags"] == ["ingest_failures_detected"]
    rollup_logs = _event_calls(mock_warning, "telemetry_health_runtime_adapter_slo_rollup")
    assert len(rollup_logs) == 1
    rollup_log = rollup_logs[0]
    assert rollup_log.kwargs["severity"] == "degraded"
    assert rollup_log.kwargs["severity_reason"] == "runtime_adapter_anomaly_detected"
    assert rollup_log.kwargs["runtime_adapter_anomaly_streak"] == 1
    assert rollup_log.kwargs["runtime_sustained_failure_active"] is False
    assert rollup_log.kwargs["ingest_attempts"] == 10
    assert rollup_log.kwargs["ingest_failures"] == 1
    assert rollup_log.kwargs["invalid_samples"] == 2
    assert rollup_log.kwargs["dropped_samples"] == 0
    assert rollup_log.kwargs["invalid_sample_ratio"] == pytest.approx(2 / 12)
    assert rollup_log.kwargs["last_batch_size"] == 12
    assert rollup_log.kwargs["anomaly_reason_flags"] == ["ingest_failures_detected"]


@pytest.mark.asyncio
async def test_get_health_returns_positive_lag(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 4,
            "persisted_events": 4,
            "fanout_events": 4,
            "dropped_events": 1,
            "runtime_exhausted_cycles": 5,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 1,
            "runtime_sustained_failure_active": 0,
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

    with (
        patch("app.modules.telemetry.service.logger.info") as mock_info,
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        result = await svc.get_health()

    assert result.status == "ok"
    assert result.dropped_events == 0
    snapshot_logs = _event_calls(mock_info, "telemetry_health_runtime_adapter_slo_snapshot")
    assert len(snapshot_logs) == 1
    info_kwargs = snapshot_logs[0].kwargs
    assert info_kwargs["last_batch_size"] == 0
    assert info_kwargs["invalid_samples"] == 0
    assert info_kwargs["dropped_samples"] == 0
    assert info_kwargs["ingest_attempts"] == 0
    assert info_kwargs["ingest_failures"] == 0
    counter_snapshot_failed_logs = _event_calls(mock_warning, "telemetry_health_counter_snapshot_failed")
    assert len(counter_snapshot_failed_logs) == 1
    transition_logs = _event_calls(
        mock_info, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(transition_logs) == 1
    transition_log = transition_logs[0]
    assert transition_log.kwargs["previous_streak"] == 0
    assert transition_log.kwargs["current_streak"] == 0
    assert transition_log.kwargs["anomaly_reason_flags"] == []
    rollup_logs = _event_calls(mock_info, "telemetry_health_runtime_adapter_slo_rollup")
    assert len(rollup_logs) == 1
    rollup_log = rollup_logs[0]
    assert rollup_log.kwargs["severity"] == "ok"
    assert rollup_log.kwargs["severity_reason"] == "runtime_adapter_healthy"
    assert rollup_log.kwargs["runtime_adapter_anomaly_streak"] == 0
    assert rollup_log.kwargs["runtime_sustained_failure_active"] is False
    assert rollup_log.kwargs["ingest_attempts"] == 0
    assert rollup_log.kwargs["ingest_failures"] == 0
    assert rollup_log.kwargs["invalid_samples"] == 0
    assert rollup_log.kwargs["dropped_samples"] == 0
    assert rollup_log.kwargs["invalid_sample_ratio"] == pytest.approx(0.0)
    assert rollup_log.kwargs["last_batch_size"] == 0
    assert rollup_log.kwargs["anomaly_reason_flags"] == []
    trend_logs = _event_calls(mock_info, "telemetry_health_runtime_adapter_slo_trend_window_summary")
    assert len(trend_logs) == 1
    trend_log = trend_logs[0]
    assert trend_log.kwargs["latest_severity"] == "ok"
    assert trend_log.kwargs["latest_anomaly_reason_flags"] == []
    assert trend_log.kwargs["window_size"] == 1
    assert trend_log.kwargs["max_window_size"] == 10
    assert trend_log.kwargs["severity_transition_counts"] == {}
    assert trend_log.kwargs["anomaly_reason_frequency"] == {}
    transition_not_crossed_logs = _event_calls(
        mock_info, "telemetry_health_runtime_adapter_slo_transition_frequency_threshold_not_crossed"
    )
    assert len(transition_not_crossed_logs) == 1
    transition_not_crossed = transition_not_crossed_logs[0]
    assert transition_not_crossed.kwargs["transition_frequency_threshold"] == 3
    assert transition_not_crossed.kwargs["max_transition_count"] == 0
    assert transition_not_crossed.kwargs["window_size"] == 1
    reason_not_crossed_logs = _event_calls(
        mock_info, "telemetry_health_runtime_adapter_slo_reason_frequency_threshold_not_crossed"
    )
    assert len(reason_not_crossed_logs) == 1
    reason_not_crossed = reason_not_crossed_logs[0]
    assert reason_not_crossed.kwargs["reason_frequency_threshold"] == 3
    assert reason_not_crossed.kwargs["max_reason_frequency"] == 0
    assert reason_not_crossed.kwargs["window_size"] == 1


@pytest.mark.asyncio
async def test_get_health_status_degraded_when_runtime_sustained_failure_active(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 10,
            "persisted_events": 9,
            "fanout_events": 9,
            "dropped_events": 1,
            "runtime_exhausted_cycles": 8,
            "runtime_exhausted_streak": 4,
            "runtime_sustained_failure_windows": 2,
            "runtime_sustained_failure_active": 1,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    result = await svc.get_health()

    assert result.status == "degraded"


@pytest.mark.asyncio
async def test_get_health_rollup_logs_ok_severity_for_healthy_runtime_adapter(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 5,
            "runtime_adapter_invalid_samples": 1,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 9,
            "runtime_adapter_ingest_failures": 0,
            "runtime_adapter_anomaly_streak": 0,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with patch("app.modules.telemetry.service.logger.info") as mock_info:
        result = await svc.get_health()

    assert result.status == "ok"
    rollup_logs = _event_calls(mock_info, "telemetry_health_runtime_adapter_slo_rollup")
    assert len(rollup_logs) == 1
    rollup_log = rollup_logs[0]
    assert rollup_log.kwargs["severity"] == "ok"
    assert rollup_log.kwargs["severity_reason"] == "runtime_adapter_healthy"
    assert rollup_log.kwargs["runtime_adapter_anomaly_streak"] == 0
    assert rollup_log.kwargs["runtime_sustained_failure_active"] is False
    assert rollup_log.kwargs["ingest_attempts"] == 9
    assert rollup_log.kwargs["ingest_failures"] == 0
    assert rollup_log.kwargs["invalid_samples"] == 1
    assert rollup_log.kwargs["invalid_sample_ratio"] == pytest.approx(0.1)
    assert rollup_log.kwargs["last_batch_size"] == 5
    assert rollup_log.kwargs["anomaly_reason_flags"] == []


@pytest.mark.asyncio
async def test_get_health_rollup_logs_critical_severity_when_runtime_failure_active(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 7,
            "runtime_exhausted_streak": 3,
            "runtime_sustained_failure_windows": 2,
            "runtime_sustained_failure_active": 1,
            "runtime_adapter_last_batch_size": 7,
            "runtime_adapter_invalid_samples": 2,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 8,
            "runtime_adapter_ingest_failures": 0,
            "runtime_adapter_anomaly_streak": 0,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with patch("app.modules.telemetry.service.logger.error") as mock_error:
        result = await svc.get_health()

    assert result.status == "degraded"
    rollup_logs = _event_calls(mock_error, "telemetry_health_runtime_adapter_slo_rollup")
    assert len(rollup_logs) == 1
    rollup_log = rollup_logs[0]
    assert rollup_log.kwargs["severity"] == "critical"
    assert rollup_log.kwargs["severity_reason"] == "runtime_sustained_failure_active"
    assert rollup_log.kwargs["runtime_adapter_anomaly_streak"] == 0
    assert rollup_log.kwargs["runtime_sustained_failure_active"] is True
    assert rollup_log.kwargs["ingest_attempts"] == 8
    assert rollup_log.kwargs["ingest_failures"] == 0
    assert rollup_log.kwargs["invalid_samples"] == 2
    assert rollup_log.kwargs["invalid_sample_ratio"] == pytest.approx(0.2)
    assert rollup_log.kwargs["last_batch_size"] == 7
    assert rollup_log.kwargs["anomaly_reason_flags"] == []


@pytest.mark.asyncio
async def test_get_health_rollup_logs_critical_severity_when_anomaly_streak_reaches_threshold(
    mock_db,
):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 6,
            "runtime_adapter_invalid_samples": 0,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 4,
            "runtime_adapter_ingest_failures": 1,
            "runtime_adapter_anomaly_streak": 2,
        }
    )
    counter_service.set_runtime_adapter_anomaly_streak = AsyncMock(return_value=3)
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with patch("app.modules.telemetry.service.logger.error") as mock_error:
        result = await svc.get_health()

    assert result.status == "ok"
    rollup_logs = _event_calls(mock_error, "telemetry_health_runtime_adapter_slo_rollup")
    assert len(rollup_logs) == 1
    rollup_log = rollup_logs[0]
    assert rollup_log.kwargs["severity"] == "critical"
    assert rollup_log.kwargs["severity_reason"] == "anomaly_streak_threshold_exceeded"
    assert rollup_log.kwargs["runtime_adapter_anomaly_streak"] == 3
    assert rollup_log.kwargs["runtime_sustained_failure_active"] is False
    assert rollup_log.kwargs["ingest_attempts"] == 4
    assert rollup_log.kwargs["ingest_failures"] == 1
    assert rollup_log.kwargs["invalid_samples"] == 0
    assert rollup_log.kwargs["invalid_sample_ratio"] == pytest.approx(0.0)
    assert rollup_log.kwargs["last_batch_size"] == 6
    assert rollup_log.kwargs["anomaly_reason_flags"] == ["ingest_failures_detected"]


@pytest.mark.asyncio
async def test_get_health_trend_window_summary_aggregates_transitions_and_reason_frequency(
    mock_db,
):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        side_effect=[
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 4,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 4,
                "runtime_adapter_ingest_failures": 0,
                "runtime_adapter_anomaly_streak": 0,
            },
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 5,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 5,
                "runtime_adapter_ingest_failures": 1,
                "runtime_adapter_anomaly_streak": 0,
            },
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 3,
                "runtime_exhausted_streak": 2,
                "runtime_sustained_failure_windows": 1,
                "runtime_sustained_failure_active": 1,
                "runtime_adapter_last_batch_size": 6,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 6,
                "runtime_adapter_ingest_failures": 0,
                "runtime_adapter_anomaly_streak": 0,
            },
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 7,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 7,
                "runtime_adapter_ingest_failures": 1,
                "runtime_adapter_anomaly_streak": 0,
            },
        ]
    )
    counter_service.set_runtime_adapter_anomaly_streak = AsyncMock(return_value=1)
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch("app.modules.telemetry.service.logger.info") as mock_info,
        patch("app.modules.telemetry.service.logger.warning"),
        patch("app.modules.telemetry.service.logger.error"),
    ):
        await svc.get_health()
        await svc.get_health()
        await svc.get_health()
        await svc.get_health()

    trend_logs = _event_calls(mock_info, "telemetry_health_runtime_adapter_slo_trend_window_summary")
    assert len(trend_logs) == 4
    final_trend_log = trend_logs[-1]
    assert final_trend_log.kwargs["latest_severity"] == "degraded"
    assert final_trend_log.kwargs["latest_anomaly_reason_flags"] == ["ingest_failures_detected"]
    assert final_trend_log.kwargs["window_size"] == 4
    assert final_trend_log.kwargs["max_window_size"] == 10
    assert final_trend_log.kwargs["severity_transition_counts"] == {
        "critical->degraded": 1,
        "degraded->critical": 1,
        "ok->degraded": 1,
    }
    assert final_trend_log.kwargs["anomaly_reason_frequency"] == {
        "ingest_failures_detected": 2
    }
    transition_not_crossed_logs = _event_calls(
        mock_info, "telemetry_health_runtime_adapter_slo_transition_frequency_threshold_not_crossed"
    )
    assert len(transition_not_crossed_logs) == 1
    transition_not_crossed = transition_not_crossed_logs[0]
    assert transition_not_crossed.kwargs["transition_frequency_threshold"] == 3
    assert transition_not_crossed.kwargs["max_transition_count"] == 0
    assert transition_not_crossed.kwargs["window_size"] == 1
    assert transition_not_crossed.kwargs["recovery_transition"] is False
    reason_not_crossed_logs = _event_calls(
        mock_info, "telemetry_health_runtime_adapter_slo_reason_frequency_threshold_not_crossed"
    )
    assert len(reason_not_crossed_logs) == 1
    reason_not_crossed = reason_not_crossed_logs[0]
    assert reason_not_crossed.kwargs["reason_frequency_threshold"] == 3
    assert reason_not_crossed.kwargs["max_reason_frequency"] == 0
    assert reason_not_crossed.kwargs["window_size"] == 1
    assert reason_not_crossed.kwargs["recovery_transition"] is False


@pytest.mark.asyncio
async def test_get_health_trend_window_thresholds_crossed_for_transition_and_reason_frequency(
    mock_db,
):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        side_effect=[
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 1,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 1,
                "runtime_adapter_ingest_failures": 1,
                "runtime_adapter_anomaly_streak": 0,
            },
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 1,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 1,
                "runtime_adapter_ingest_failures": 0,
                "runtime_adapter_anomaly_streak": 1,
            },
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 1,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 1,
                "runtime_adapter_ingest_failures": 1,
                "runtime_adapter_anomaly_streak": 0,
            },
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 1,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 1,
                "runtime_adapter_ingest_failures": 0,
                "runtime_adapter_anomaly_streak": 1,
            },
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 1,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 1,
                "runtime_adapter_ingest_failures": 1,
                "runtime_adapter_anomaly_streak": 0,
            },
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 1,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 1,
                "runtime_adapter_ingest_failures": 0,
                "runtime_adapter_anomaly_streak": 1,
            },
        ]
    )
    counter_service.set_runtime_adapter_anomaly_streak = AsyncMock(return_value=1)
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
        patch("app.modules.telemetry.service.logger.info") as mock_info,
        patch("app.modules.telemetry.service.logger.error"),
    ):
        for _ in range(6):
            await svc.get_health()

    transition_crossed_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_slo_transition_frequency_threshold_crossed"
    )
    assert len(transition_crossed_logs) == 1
    transition_crossed = transition_crossed_logs[0]
    assert transition_crossed.kwargs["transition_frequency_threshold"] == 3
    assert transition_crossed.kwargs["max_transition_count"] == 3
    assert transition_crossed.kwargs["crossed_transition_counts"] == {"degraded->ok": 3}
    assert transition_crossed.kwargs["window_size"] == 6
    assert transition_crossed.kwargs["cooldown_re_emitted"] is False

    reason_crossed_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_slo_reason_frequency_threshold_crossed"
    )
    assert len(reason_crossed_logs) == 1
    reason_crossed = reason_crossed_logs[0]
    assert reason_crossed.kwargs["reason_frequency_threshold"] == 3
    assert reason_crossed.kwargs["max_reason_frequency"] == 3
    assert reason_crossed.kwargs["crossed_reason_frequency"] == {
        "ingest_failures_detected": 3
    }
    assert reason_crossed.kwargs["window_size"] == 5
    assert reason_crossed.kwargs["cooldown_re_emitted"] is False

    reason_crossed_suppressed_logs = _event_calls(
        mock_info,
        "telemetry_health_runtime_adapter_slo_reason_frequency_threshold_crossed_suppressed",
    )
    assert len(reason_crossed_suppressed_logs) == 1
    suppressed_log = reason_crossed_suppressed_logs[0]
    assert suppressed_log.kwargs["reason_frequency_threshold"] == 3
    assert suppressed_log.kwargs["max_reason_frequency"] == 3
    assert suppressed_log.kwargs["crossed_reason_frequency"] == {
        "ingest_failures_detected": 3
    }
    assert suppressed_log.kwargs["window_size"] == 6
    assert suppressed_log.kwargs["cooldown_reads"] == 3
    assert suppressed_log.kwargs["cooldown_reads_elapsed"] == 1
    assert suppressed_log.kwargs["cooldown_reads_remaining"] == 2


@pytest.mark.asyncio
async def test_get_health_trend_window_summary_respects_bounded_max_size(mock_db):
    counter_service = AsyncMock()
    snapshots = []
    for index in range(12):
        snapshots.append(
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 1,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 1,
                "runtime_adapter_ingest_failures": 1 if index % 2 == 1 else 0,
                "runtime_adapter_anomaly_streak": 0,
            }
        )
    counter_service.get_snapshot = AsyncMock(side_effect=snapshots)
    counter_service.set_runtime_adapter_anomaly_streak = AsyncMock(return_value=1)
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch("app.modules.telemetry.service.logger.info") as mock_info,
        patch("app.modules.telemetry.service.logger.warning"),
        patch("app.modules.telemetry.service.logger.error"),
    ):
        for _ in range(12):
            await svc.get_health()

    trend_logs = _event_calls(mock_info, "telemetry_health_runtime_adapter_slo_trend_window_summary")
    assert len(trend_logs) == 12
    final_trend_log = trend_logs[-1]
    assert final_trend_log.kwargs["window_size"] == 10
    assert final_trend_log.kwargs["max_window_size"] == 10
    transition_counts = final_trend_log.kwargs["severity_transition_counts"]
    assert sum(transition_counts.values()) == 9


@pytest.mark.asyncio
async def test_get_health_trend_window_state_write_failure_is_fail_open(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 3,
            "runtime_adapter_invalid_samples": 0,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 3,
            "runtime_adapter_ingest_failures": 0,
            "runtime_adapter_anomaly_streak": 0,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch.object(
            svc,
            "_append_runtime_adapter_slo_trend_window_entry",
            side_effect=RuntimeError("trend write failed"),
        ),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
        patch("app.modules.telemetry.service.logger.info") as mock_info,
    ):
        result = await svc.get_health()

    assert result.status == "ok"
    trend_state_write_failed = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_slo_trend_window_state_write_failed"
    )
    assert len(trend_state_write_failed) == 1
    trend_summary_logs = _event_calls(mock_info, "telemetry_health_runtime_adapter_slo_trend_window_summary")
    assert len(trend_summary_logs) == 0


@pytest.mark.asyncio
async def test_get_health_trend_window_state_read_failure_is_fail_open(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 3,
            "runtime_adapter_invalid_samples": 0,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 3,
            "runtime_adapter_ingest_failures": 0,
            "runtime_adapter_anomaly_streak": 0,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch.object(
            svc,
            "_build_runtime_adapter_slo_trend_window_summary",
            side_effect=RuntimeError("trend read failed"),
        ),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
        patch("app.modules.telemetry.service.logger.info") as mock_info,
    ):
        result = await svc.get_health()

    assert result.status == "ok"
    trend_state_read_failed = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_slo_trend_window_state_read_failed"
    )
    assert len(trend_state_read_failed) == 1
    trend_summary_logs = _event_calls(mock_info, "telemetry_health_runtime_adapter_slo_trend_window_summary")
    assert len(trend_summary_logs) == 0


@pytest.mark.asyncio
async def test_get_health_trend_threshold_evaluation_failure_is_fail_open(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 1,
            "runtime_adapter_invalid_samples": 0,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 1,
            "runtime_adapter_ingest_failures": 0,
            "runtime_adapter_anomaly_streak": 0,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch.object(
            svc,
            "_log_runtime_adapter_slo_trend_threshold_triggers",
            side_effect=RuntimeError("threshold eval failed"),
        ),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        result = await svc.get_health()

    assert result.status == "ok"
    evaluation_failed_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_slo_trend_threshold_evaluation_failed"
    )
    assert len(evaluation_failed_logs) == 1


def test_trend_threshold_cooldown_re_emits_crossed_after_cooldown_reads(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with (
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
        patch("app.modules.telemetry.service.logger.info") as mock_info,
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=5,
                anomaly_reason_frequency={"ingest_failures_detected": 3},
            )
        )
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=6,
                anomaly_reason_frequency={"ingest_failures_detected": 4},
            )
        )
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=7,
                anomaly_reason_frequency={"ingest_failures_detected": 5},
            )
        )
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=8,
                anomaly_reason_frequency={"ingest_failures_detected": 6},
            )
        )

    reason_crossed_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_slo_reason_frequency_threshold_crossed"
    )
    assert len(reason_crossed_logs) == 2
    first_crossed = reason_crossed_logs[0]
    assert first_crossed.kwargs["window_size"] == 5
    assert first_crossed.kwargs["cooldown_re_emitted"] is False
    re_emitted_crossed = reason_crossed_logs[1]
    assert re_emitted_crossed.kwargs["window_size"] == 8
    assert re_emitted_crossed.kwargs["cooldown_re_emitted"] is True
    assert re_emitted_crossed.kwargs["cooldown_reads_elapsed"] == 3

    reason_crossed_suppressed_logs = _event_calls(
        mock_info,
        "telemetry_health_runtime_adapter_slo_reason_frequency_threshold_crossed_suppressed",
    )
    assert len(reason_crossed_suppressed_logs) == 2
    assert reason_crossed_suppressed_logs[0].kwargs["cooldown_reads_elapsed"] == 1
    assert reason_crossed_suppressed_logs[0].kwargs["cooldown_reads_remaining"] == 2
    assert reason_crossed_suppressed_logs[1].kwargs["cooldown_reads_elapsed"] == 2
    assert reason_crossed_suppressed_logs[1].kwargs["cooldown_reads_remaining"] == 1


def test_trend_threshold_recovery_not_crossed_logs_transition(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with (
        patch("app.modules.telemetry.service.logger.warning"),
        patch("app.modules.telemetry.service.logger.info") as mock_info,
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=1,
                severity_transition_counts={},
                anomaly_reason_frequency={},
            )
        )
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=2,
                severity_transition_counts={},
                anomaly_reason_frequency={"ingest_failures_detected": 3},
            )
        )
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=3,
                severity_transition_counts={},
                anomaly_reason_frequency={"ingest_failures_detected": 2},
            )
        )

    reason_not_crossed_logs = _event_calls(
        mock_info, "telemetry_health_runtime_adapter_slo_reason_frequency_threshold_not_crossed"
    )
    assert len(reason_not_crossed_logs) == 2
    assert reason_not_crossed_logs[0].kwargs["recovery_transition"] is False
    assert reason_not_crossed_logs[1].kwargs["recovery_transition"] is True
    assert reason_not_crossed_logs[1].kwargs["window_size"] == 3


def test_trend_threshold_cooldown_state_read_failure_is_fail_open(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with (
        patch.object(
            svc,
            "_read_runtime_adapter_slo_threshold_cooldown_state",
            side_effect=RuntimeError("cooldown read failed"),
        ),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(window_size=1)
        )

    read_failed_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_trend_threshold_cooldown_state_read_failed",
    )
    assert len(read_failed_logs) == 1
    transition_read_failed_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_threshold_cooldown_transition_state_read_failed",
    )
    assert len(transition_read_failed_logs) == 1


def test_trend_threshold_cooldown_state_write_failure_is_fail_open(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with (
        patch.object(
            svc,
            "_write_runtime_adapter_slo_threshold_cooldown_state",
            side_effect=RuntimeError("cooldown write failed"),
        ),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(window_size=1)
        )

    write_failed_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_trend_threshold_cooldown_state_write_failed",
    )
    assert len(write_failed_logs) == 1
    transition_write_failed_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_threshold_cooldown_transition_state_write_failed",
    )
    assert len(transition_write_failed_logs) == 1


def test_trend_threshold_cooldown_transition_entered_event_metadata(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with patch("app.modules.telemetry.service.logger.warning") as mock_warning:
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=4,
                anomaly_reason_frequency={"ingest_failures_detected": 3},
            )
        )

    entered_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_threshold_cooldown_transition_entered",
    )
    assert len(entered_logs) == 1
    entered = entered_logs[0]
    assert entered.kwargs["threshold_dimension"] == "reason_frequency"
    assert entered.kwargs["threshold_value"] == 3
    assert entered.kwargs["max_observed_value"] == 3
    assert entered.kwargs["crossed_values"] == {"ingest_failures_detected": 3}
    assert entered.kwargs["window_size"] == 4
    assert entered.kwargs["cooldown_reads"] == 3
    assert entered.kwargs["previous_threshold_crossed"] is False
    assert entered.kwargs["current_threshold_crossed"] is True
    assert entered.kwargs["previous_reads_since_last_crossed_emit"] == 0
    assert entered.kwargs["current_reads_since_last_crossed_emit"] == 0
    assert entered.kwargs["recovery_transition"] is False
    assert entered.kwargs["cooldown_re_emitted"] is False


def test_trend_threshold_cooldown_transition_suppressed_event_metadata(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with (
        patch("app.modules.telemetry.service.logger.warning"),
        patch("app.modules.telemetry.service.logger.info") as mock_info,
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=5,
                severity_transition_counts={"degraded->ok": 3},
            )
        )
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=6,
                severity_transition_counts={"degraded->ok": 4},
            )
        )

    suppressed_logs = _event_calls(
        mock_info,
        "telemetry_health_runtime_adapter_slo_threshold_cooldown_transition_suppressed",
    )
    assert len(suppressed_logs) == 1
    suppressed = suppressed_logs[0]
    assert suppressed.kwargs["threshold_dimension"] == "transition_frequency"
    assert suppressed.kwargs["threshold_value"] == 3
    assert suppressed.kwargs["max_observed_value"] == 4
    assert suppressed.kwargs["crossed_values"] == {"degraded->ok": 4}
    assert suppressed.kwargs["window_size"] == 6
    assert suppressed.kwargs["cooldown_reads"] == 3
    assert suppressed.kwargs["previous_threshold_crossed"] is True
    assert suppressed.kwargs["current_threshold_crossed"] is True
    assert suppressed.kwargs["previous_reads_since_last_crossed_emit"] == 0
    assert suppressed.kwargs["current_reads_since_last_crossed_emit"] == 1
    assert suppressed.kwargs["recovery_transition"] is False
    assert suppressed.kwargs["cooldown_re_emitted"] is False


def test_trend_threshold_cooldown_transition_expired_reemit_event_metadata(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with (
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
        patch("app.modules.telemetry.service.logger.info"),
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=5,
                anomaly_reason_frequency={"ingest_failures_detected": 3},
            )
        )
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=6,
                anomaly_reason_frequency={"ingest_failures_detected": 4},
            )
        )
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=7,
                anomaly_reason_frequency={"ingest_failures_detected": 5},
            )
        )
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=8,
                anomaly_reason_frequency={"ingest_failures_detected": 6},
            )
        )

    expired_reemit_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_threshold_cooldown_transition_expired_reemit",
    )
    assert len(expired_reemit_logs) == 1
    expired_reemit = expired_reemit_logs[0]
    assert expired_reemit.kwargs["threshold_dimension"] == "reason_frequency"
    assert expired_reemit.kwargs["threshold_value"] == 3
    assert expired_reemit.kwargs["max_observed_value"] == 6
    assert expired_reemit.kwargs["crossed_values"] == {"ingest_failures_detected": 6}
    assert expired_reemit.kwargs["window_size"] == 8
    assert expired_reemit.kwargs["cooldown_reads"] == 3
    assert expired_reemit.kwargs["previous_threshold_crossed"] is True
    assert expired_reemit.kwargs["current_threshold_crossed"] is True
    assert expired_reemit.kwargs["previous_reads_since_last_crossed_emit"] == 2
    assert expired_reemit.kwargs["current_reads_since_last_crossed_emit"] == 0
    assert expired_reemit.kwargs["recovery_transition"] is False
    assert expired_reemit.kwargs["cooldown_re_emitted"] is True


def test_trend_threshold_cooldown_transition_cleared_recovery_event_metadata(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with (
        patch("app.modules.telemetry.service.logger.warning"),
        patch("app.modules.telemetry.service.logger.info") as mock_info,
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=2,
                anomaly_reason_frequency={"ingest_failures_detected": 3},
            )
        )
        svc._safe_log_runtime_adapter_slo_trend_threshold_triggers(
            trend_window_summary=_trend_window_summary(
                window_size=3,
                anomaly_reason_frequency={"ingest_failures_detected": 2},
            )
        )

    recovery_logs = _event_calls(
        mock_info,
        "telemetry_health_runtime_adapter_slo_threshold_cooldown_transition_cleared_recovery",
    )
    assert len(recovery_logs) == 1
    recovery = recovery_logs[0]
    assert recovery.kwargs["threshold_dimension"] == "reason_frequency"
    assert recovery.kwargs["threshold_value"] == 3
    assert recovery.kwargs["max_observed_value"] == 2
    assert recovery.kwargs["crossed_values"] == {}
    assert recovery.kwargs["window_size"] == 3
    assert recovery.kwargs["cooldown_reads"] == 3
    assert recovery.kwargs["previous_threshold_crossed"] is True
    assert recovery.kwargs["current_threshold_crossed"] is False
    assert recovery.kwargs["previous_reads_since_last_crossed_emit"] == 0
    assert recovery.kwargs["current_reads_since_last_crossed_emit"] == 0
    assert recovery.kwargs["recovery_transition"] is True
    assert recovery.kwargs["cooldown_re_emitted"] is False


def test_trend_threshold_cooldown_summary_logs_dimension_metadata(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    cooldown_state = {
        "transition_frequency": {
            "initialized": True,
            "threshold_crossed": True,
            "reads_since_last_crossed_emit": 1,
        },
        "reason_frequency": {
            "initialized": True,
            "threshold_crossed": False,
            "reads_since_last_crossed_emit": 0,
        },
    }
    trend_window_summary = _trend_window_summary(window_size=6)
    trend_window_summary["max_window_size"] = 10

    with patch("app.modules.telemetry.service.logger.info") as mock_info:
        svc._safe_log_runtime_adapter_slo_trend_threshold_cooldown_summary(
            trend_window_summary=trend_window_summary,
            cooldown_state=cooldown_state,
        )

    summary_logs = _event_calls(
        mock_info,
        "telemetry_health_runtime_adapter_slo_trend_threshold_cooldown_summary",
    )
    assert len(summary_logs) == 1
    summary_log = summary_logs[0]
    assert summary_log.kwargs["window_size"] == 6
    assert summary_log.kwargs["max_window_size"] == 10
    assert summary_log.kwargs["cooldown_reads"] == 3

    transition_cooldown = summary_log.kwargs["transition_frequency_cooldown"]
    assert transition_cooldown["initialized"] is True
    assert transition_cooldown["threshold_crossed"] is True
    assert transition_cooldown["reads_since_last_crossed_emit"] == 1
    assert transition_cooldown["next_crossed_emit_in_reads"] == 2
    assert transition_cooldown["cooldown_active"] is True

    reason_cooldown = summary_log.kwargs["reason_frequency_cooldown"]
    assert reason_cooldown["initialized"] is True
    assert reason_cooldown["threshold_crossed"] is False
    assert reason_cooldown["reads_since_last_crossed_emit"] == 0
    assert reason_cooldown["next_crossed_emit_in_reads"] == 0
    assert reason_cooldown["cooldown_active"] is False


def test_trend_threshold_cooldown_summary_state_read_failure_is_fail_open(mock_db):
    svc = TelemetryQueryService(db=mock_db)
    with (
        patch.object(
            svc,
            "_build_runtime_adapter_slo_trend_threshold_cooldown_summary",
            side_effect=RuntimeError("cooldown summary read failed"),
        ),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_cooldown_summary(
            trend_window_summary=_trend_window_summary(window_size=1),
            cooldown_state=svc._new_runtime_adapter_slo_threshold_cooldown_state(),
        )

    summary_read_failed_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_trend_threshold_cooldown_summary_state_read_failed",
    )
    assert len(summary_read_failed_logs) == 1


def test_trend_threshold_cooldown_summary_log_failure_is_fail_open(mock_db):
    svc = TelemetryQueryService(db=mock_db)
    with (
        patch("app.modules.telemetry.service.logger.info", side_effect=RuntimeError("log failed")),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_cooldown_summary(
            trend_window_summary=_trend_window_summary(window_size=1),
            cooldown_state=svc._new_runtime_adapter_slo_threshold_cooldown_state(),
        )

    summary_log_failed_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_trend_threshold_cooldown_summary_log_failed",
    )
    assert len(summary_log_failed_logs) == 1


def test_trend_threshold_cooldown_summary_defaults_invalid_fields_to_zero(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    cooldown_summary = svc._build_runtime_adapter_slo_trend_threshold_cooldown_summary(
        trend_window_summary={
            "window_size": "invalid",
            "max_window_size": None,
        },
        cooldown_state={
            "transition_frequency": {
                "initialized": "truthy",
                "threshold_crossed": 1,
                "reads_since_last_crossed_emit": "bad",
            }
        },
    )

    assert cooldown_summary["window_size"] == 0
    assert cooldown_summary["max_window_size"] == 0
    transition_cooldown = cooldown_summary["transition_frequency"]
    assert transition_cooldown["initialized"] is True
    assert transition_cooldown["threshold_crossed"] is True
    assert transition_cooldown["reads_since_last_crossed_emit"] == 0
    assert transition_cooldown["next_crossed_emit_in_reads"] == 3
    assert transition_cooldown["cooldown_active"] is True


def test_trend_threshold_cooldown_transition_log_failure_is_fail_open(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with (
        patch(
            "app.modules.telemetry.service.logger.info",
            side_effect=[RuntimeError("transition log failed")],
        ),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        svc._safe_log_runtime_adapter_slo_threshold_cooldown_transition_event(
            event_name="telemetry_health_runtime_adapter_slo_threshold_cooldown_transition_suppressed",
            threshold_dimension="transition_frequency",
            threshold_value=3,
            max_observed_value=4,
            crossed_values={"degraded->ok": 4},
            window_size=6,
            previous_state={
                "initialized": True,
                "threshold_crossed": True,
                "reads_since_last_crossed_emit": 0,
            },
            current_state={
                "initialized": True,
                "threshold_crossed": True,
                "reads_since_last_crossed_emit": 1,
            },
            recovery_transition=False,
            cooldown_re_emitted=False,
            log_level="info",
        )

    transition_log_failed_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_threshold_cooldown_transition_log_failed",
    )
    assert len(transition_log_failed_logs) == 1
    transition_log_failed = transition_log_failed_logs[0]
    assert (
        transition_log_failed.kwargs["event_name"]
        == "telemetry_health_runtime_adapter_slo_threshold_cooldown_transition_suppressed"
    )
    assert transition_log_failed.kwargs["threshold_dimension"] == "transition_frequency"


def test_trend_threshold_correlation_snapshot_aggregates_phase_and_summary_windows(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    _append_correlation_window_entry(
        svc,
        window_size=4,
        transition_phase="enter-cooldown",
        reason_phase="cooldown-suppressed",
        transition_threshold_crossed=True,
        transition_cooldown_active=True,
        transition_next_emit_in_reads=3,
        reason_threshold_crossed=True,
        reason_cooldown_active=True,
        reason_next_emit_in_reads=2,
        transition_max_observed_value=4,
        reason_max_observed_value=3,
    )
    _append_correlation_window_entry(
        svc,
        window_size=5,
        transition_phase="cooldown-suppressed",
        reason_phase="cooldown-expired-reemit",
        transition_threshold_crossed=True,
        transition_cooldown_active=True,
        transition_next_emit_in_reads=2,
        reason_threshold_crossed=True,
        reason_cooldown_active=True,
        reason_next_emit_in_reads=3,
        transition_max_observed_value=5,
        reason_max_observed_value=6,
        reason_cooldown_re_emitted=True,
    )
    _append_correlation_window_entry(
        svc,
        window_size=6,
        transition_phase="cooldown-cleared-recovery",
        reason_phase="",
        transition_threshold_crossed=False,
        transition_cooldown_active=False,
        transition_next_emit_in_reads=0,
        reason_threshold_crossed=False,
        reason_cooldown_active=False,
        reason_next_emit_in_reads=0,
        transition_max_observed_value=1,
        reason_max_observed_value=1,
        transition_recovery_transition=True,
    )

    snapshot = svc._build_runtime_adapter_slo_trend_threshold_correlation_snapshot()

    assert snapshot["window_size"] == 3
    assert snapshot["max_window_size"] == 10
    assert snapshot["cooldown_reads"] == 3

    transition_phase_counts = snapshot["cooldown_transition_phase_counts"]["transition_frequency"]
    assert transition_phase_counts["enter-cooldown"] == 1
    assert transition_phase_counts["cooldown-suppressed"] == 1
    assert transition_phase_counts["cooldown-expired-reemit"] == 0
    assert transition_phase_counts["cooldown-cleared-recovery"] == 1

    reason_phase_counts = snapshot["cooldown_transition_phase_counts"]["reason_frequency"]
    assert reason_phase_counts["enter-cooldown"] == 0
    assert reason_phase_counts["cooldown-suppressed"] == 1
    assert reason_phase_counts["cooldown-expired-reemit"] == 1
    assert reason_phase_counts["cooldown-cleared-recovery"] == 0

    transition_window_state = snapshot["cooldown_summary_window_state"]["transition_frequency"]
    assert transition_window_state["threshold_crossed_reads"] == 2
    assert transition_window_state["cooldown_active_reads"] == 2
    assert transition_window_state["max_next_crossed_emit_in_reads"] == 3

    reason_window_state = snapshot["cooldown_summary_window_state"]["reason_frequency"]
    assert reason_window_state["threshold_crossed_reads"] == 2
    assert reason_window_state["cooldown_active_reads"] == 2
    assert reason_window_state["max_next_crossed_emit_in_reads"] == 3

    latest_trigger_state = snapshot["latest_threshold_trigger_state"]
    assert latest_trigger_state["transition_frequency"]["threshold_crossed"] is False
    assert latest_trigger_state["transition_frequency"]["recovery_transition"] is True
    assert latest_trigger_state["transition_frequency"]["window_size"] == 6
    assert latest_trigger_state["reason_frequency"]["threshold_crossed"] is False
    assert latest_trigger_state["reason_frequency"]["window_size"] == 6

    latest_cooldown_state = snapshot["latest_cooldown_summary_state"]
    assert latest_cooldown_state["transition_frequency"]["threshold_crossed"] is False
    assert latest_cooldown_state["transition_frequency"]["cooldown_active"] is False
    assert latest_cooldown_state["reason_frequency"]["threshold_crossed"] is False
    assert latest_cooldown_state["reason_frequency"]["cooldown_active"] is False


def test_trend_threshold_correlation_snapshot_window_is_bounded(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    for index in range(12):
        is_crossed = index % 2 == 0
        _append_correlation_window_entry(
            svc,
            window_size=index + 1,
            transition_phase=("cooldown-suppressed" if is_crossed else ""),
            reason_phase=("enter-cooldown" if is_crossed else ""),
            transition_threshold_crossed=is_crossed,
            transition_cooldown_active=is_crossed,
            transition_next_emit_in_reads=(1 if is_crossed else 0),
            reason_threshold_crossed=is_crossed,
            reason_cooldown_active=is_crossed,
            reason_next_emit_in_reads=(2 if is_crossed else 0),
            transition_max_observed_value=index + 2,
            reason_max_observed_value=index + 3,
        )

    snapshot = svc._build_runtime_adapter_slo_trend_threshold_correlation_snapshot()

    assert snapshot["window_size"] == 10
    assert snapshot["max_window_size"] == 10
    latest_trigger_state = snapshot["latest_threshold_trigger_state"]
    assert latest_trigger_state["transition_frequency"]["window_size"] == 12
    assert latest_trigger_state["reason_frequency"]["window_size"] == 12


def test_trend_threshold_correlation_snapshot_logs_metadata(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with patch("app.modules.telemetry.service.logger.info") as mock_info:
        svc._safe_log_runtime_adapter_slo_trend_threshold_correlation_snapshot(
            trend_window_summary=_trend_window_summary(window_size=4),
            latest_threshold_trigger_state={
                "transition_frequency": {
                    "threshold_dimension": "transition_frequency",
                    "threshold_value": 3,
                    "max_observed_value": 4,
                    "crossed_values": {"ok->degraded": 4},
                    "threshold_crossed": True,
                    "recovery_transition": False,
                    "cooldown_re_emitted": False,
                    "window_size": 4,
                },
                "reason_frequency": {
                    "threshold_dimension": "reason_frequency",
                    "threshold_value": 3,
                    "max_observed_value": 1,
                    "crossed_values": {},
                    "threshold_crossed": False,
                    "recovery_transition": False,
                    "cooldown_re_emitted": False,
                    "window_size": 4,
                },
            },
            cooldown_transition_phase={
                "transition_frequency": "enter-cooldown",
                "reason_frequency": "",
            },
            cooldown_summary={
                "transition_frequency": {
                    "initialized": True,
                    "threshold_crossed": True,
                    "reads_since_last_crossed_emit": 0,
                    "next_crossed_emit_in_reads": 3,
                    "cooldown_active": True,
                },
                "reason_frequency": {
                    "initialized": True,
                    "threshold_crossed": False,
                    "reads_since_last_crossed_emit": 0,
                    "next_crossed_emit_in_reads": 0,
                    "cooldown_active": False,
                },
            },
        )

    correlation_logs = _event_calls(
        mock_info,
        "telemetry_health_runtime_adapter_slo_threshold_correlation_snapshot",
    )
    assert len(correlation_logs) == 1
    correlation_log = correlation_logs[0]
    assert correlation_log.kwargs["window_size"] == 1
    assert correlation_log.kwargs["max_window_size"] == 10
    assert correlation_log.kwargs["cooldown_reads"] == 3

    transition_phase_counts = correlation_log.kwargs["cooldown_transition_phase_counts"][
        "transition_frequency"
    ]
    assert transition_phase_counts["enter-cooldown"] == 1
    assert transition_phase_counts["cooldown-suppressed"] == 0
    assert transition_phase_counts["cooldown-expired-reemit"] == 0
    assert transition_phase_counts["cooldown-cleared-recovery"] == 0

    reason_phase_counts = correlation_log.kwargs["cooldown_transition_phase_counts"]["reason_frequency"]
    assert reason_phase_counts["enter-cooldown"] == 0

    latest_trigger_state = correlation_log.kwargs["latest_threshold_trigger_state"]
    assert latest_trigger_state["transition_frequency"]["threshold_crossed"] is True
    assert latest_trigger_state["transition_frequency"]["max_observed_value"] == 4
    assert latest_trigger_state["reason_frequency"]["threshold_crossed"] is False


def test_trend_threshold_correlation_snapshot_state_write_failure_is_fail_open(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with (
        patch.object(
            svc,
            "_append_runtime_adapter_slo_trend_threshold_correlation_window_entry",
            side_effect=RuntimeError("correlation write failed"),
        ),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_correlation_snapshot(
            trend_window_summary=_trend_window_summary(window_size=1),
            latest_threshold_trigger_state=svc._new_runtime_adapter_slo_latest_threshold_trigger_state(),
            cooldown_transition_phase={
                "transition_frequency": "",
                "reason_frequency": "",
            },
            cooldown_summary={},
        )

    write_failed_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_threshold_correlation_snapshot_state_write_failed",
    )
    assert len(write_failed_logs) == 1


def test_trend_threshold_correlation_snapshot_state_read_failure_is_fail_open(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with (
        patch.object(
            svc,
            "_build_runtime_adapter_slo_trend_threshold_correlation_snapshot",
            side_effect=RuntimeError("correlation read failed"),
        ),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_correlation_snapshot(
            trend_window_summary=_trend_window_summary(window_size=1),
            latest_threshold_trigger_state=svc._new_runtime_adapter_slo_latest_threshold_trigger_state(),
            cooldown_transition_phase={
                "transition_frequency": "",
                "reason_frequency": "",
            },
            cooldown_summary={},
        )

    read_failed_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_threshold_correlation_snapshot_state_read_failed",
    )
    assert len(read_failed_logs) == 1


def test_trend_threshold_correlation_snapshot_log_failure_is_fail_open(mock_db):
    svc = TelemetryQueryService(db=mock_db)

    with (
        patch("app.modules.telemetry.service.logger.info", side_effect=RuntimeError("log failed")),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        svc._safe_log_runtime_adapter_slo_trend_threshold_correlation_snapshot(
            trend_window_summary=_trend_window_summary(window_size=1),
            latest_threshold_trigger_state=svc._new_runtime_adapter_slo_latest_threshold_trigger_state(),
            cooldown_transition_phase={
                "transition_frequency": "",
                "reason_frequency": "",
            },
            cooldown_summary={},
        )

    log_failed_logs = _event_calls(
        mock_warning,
        "telemetry_health_runtime_adapter_slo_threshold_correlation_snapshot_log_failed",
    )
    assert len(log_failed_logs) == 1


@pytest.mark.asyncio
async def test_get_health_runtime_adapter_slo_snapshot_invalid_values_are_fail_open(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 3,
            "persisted_events": 3,
            "fanout_events": 3,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": -1,
            "runtime_adapter_invalid_samples": "bad",
            "runtime_adapter_ingest_attempts": None,
            "runtime_adapter_ingest_failures": "4",
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch("app.modules.telemetry.service.logger.info") as mock_info,
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        result = await svc.get_health()

    assert result.status == "ok"
    snapshot_logs = _event_calls(mock_info, "telemetry_health_runtime_adapter_slo_snapshot")
    assert len(snapshot_logs) == 1
    info_kwargs = snapshot_logs[0].kwargs
    assert info_kwargs["last_batch_size"] == 0
    assert info_kwargs["invalid_samples"] == 0
    assert info_kwargs["ingest_attempts"] == 0
    assert info_kwargs["ingest_failures"] == 4

    invalid_counter_warnings = [
        call
        for call in mock_warning.call_args_list
        if call.args and call.args[0] == "telemetry_health_runtime_adapter_counter_invalid"
    ]
    assert len(invalid_counter_warnings) == 3
    warned_counter_names = {call.kwargs["counter_name"] for call in invalid_counter_warnings}
    assert warned_counter_names == {
        "runtime_adapter_last_batch_size",
        "runtime_adapter_invalid_samples",
        "runtime_adapter_ingest_attempts",
    }
    ingest_failure_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_ingest_failures_detected"
    )
    assert len(ingest_failure_logs) == 1
    transition_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(transition_logs) == 1
    transition_log = transition_logs[0]
    assert transition_log.kwargs["previous_streak"] == 0
    assert transition_log.kwargs["current_streak"] == 1
    assert transition_log.kwargs["anomaly_reason_flags"] == ["ingest_failures_detected"]


@pytest.mark.asyncio
async def test_get_health_runtime_adapter_slo_snapshot_log_failure_is_fail_open(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 2,
            "persisted_events": 2,
            "fanout_events": 2,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 2,
            "runtime_adapter_invalid_samples": 0,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 2,
            "runtime_adapter_ingest_failures": 0,
            "runtime_adapter_anomaly_streak": 0,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch("app.modules.telemetry.service.logger.info", side_effect=RuntimeError("log failed")),
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
    ):
        result = await svc.get_health()

    assert result.status == "ok"
    assert any(
        call.args and call.args[0] == "telemetry_health_runtime_adapter_slo_snapshot_log_failed"
        for call in mock_warning.call_args_list
    )


@pytest.mark.asyncio
async def test_get_health_warns_when_invalid_sample_ratio_exceeds_threshold(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 8,
            "runtime_adapter_invalid_samples": 3,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 5,
            "runtime_adapter_ingest_failures": 0,
            "runtime_adapter_anomaly_streak": 0,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with patch("app.modules.telemetry.service.logger.warning") as mock_warning:
        result = await svc.get_health()

    assert result.status == "ok"
    ratio_warnings = [
        call
        for call in mock_warning.call_args_list
        if call.args and call.args[0] == "telemetry_health_runtime_adapter_invalid_sample_ratio_exceeded"
    ]
    assert len(ratio_warnings) == 1
    ratio_warning = ratio_warnings[0]
    assert ratio_warning.kwargs["invalid_samples"] == 3
    assert ratio_warning.kwargs["ingest_attempts"] == 5
    assert ratio_warning.kwargs["invalid_sample_ratio"] == pytest.approx(0.375)
    assert ratio_warning.kwargs["invalid_sample_ratio_threshold"] == pytest.approx(0.25)
    streak_increment_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_incremented"
    )
    assert len(streak_increment_logs) == 1
    transition_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(transition_logs) == 1
    transition_log = transition_logs[0]
    assert transition_log.kwargs["previous_streak"] == 0
    assert transition_log.kwargs["current_streak"] == 1
    assert transition_log.kwargs["anomaly_reason_flags"] == ["invalid_sample_ratio_exceeded"]


@pytest.mark.asyncio
async def test_get_health_does_not_warn_when_invalid_sample_ratio_within_threshold(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 10,
            "runtime_adapter_invalid_samples": 2,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 8,
            "runtime_adapter_ingest_failures": 0,
            "runtime_adapter_anomaly_streak": 0,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with patch("app.modules.telemetry.service.logger.warning") as mock_warning:
        result = await svc.get_health()

    assert result.status == "ok"
    assert not any(
        call.args and call.args[0] == "telemetry_health_runtime_adapter_invalid_sample_ratio_exceeded"
        for call in mock_warning.call_args_list
    )


@pytest.mark.asyncio
async def test_get_health_warns_ingest_failures_with_zero_attempt_guard(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 0,
            "runtime_adapter_invalid_samples": 0,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 0,
            "runtime_adapter_ingest_failures": 2,
            "runtime_adapter_anomaly_streak": 0,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with patch("app.modules.telemetry.service.logger.warning") as mock_warning:
        result = await svc.get_health()

    assert result.status == "ok"
    ingest_failure_warnings = [
        call
        for call in mock_warning.call_args_list
        if call.args and call.args[0] == "telemetry_health_runtime_adapter_ingest_failures_detected"
    ]
    assert len(ingest_failure_warnings) == 1
    warning = ingest_failure_warnings[0]
    assert warning.kwargs["ingest_failures"] == 2
    assert warning.kwargs["ingest_attempts"] == 0
    assert warning.kwargs["zero_attempt_guard_applied"] is True
    assert warning.kwargs["failure_ratio"] == pytest.approx(2.0)
    streak_increment_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_incremented"
    )
    assert len(streak_increment_logs) == 1
    transition_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(transition_logs) == 1
    transition_log = transition_logs[0]
    assert transition_log.kwargs["previous_streak"] == 0
    assert transition_log.kwargs["current_streak"] == 1
    assert transition_log.kwargs["anomaly_reason_flags"] == ["ingest_failures_detected"]


@pytest.mark.asyncio
async def test_get_health_warns_when_runtime_adapter_dropped_samples_detected(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 3,
            "runtime_adapter_invalid_samples": 0,
            "runtime_adapter_dropped_samples": 2,
            "runtime_adapter_ingest_attempts": 3,
            "runtime_adapter_ingest_failures": 0,
            "runtime_adapter_anomaly_streak": 0,
        }
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with patch("app.modules.telemetry.service.logger.warning") as mock_warning:
        result = await svc.get_health()

    assert result.status == "ok"
    dropped_sample_warnings = [
        call
        for call in mock_warning.call_args_list
        if call.args and call.args[0] == "telemetry_health_runtime_adapter_dropped_samples_detected"
    ]
    assert len(dropped_sample_warnings) == 1
    dropped_sample_warning = dropped_sample_warnings[0]
    assert dropped_sample_warning.kwargs["dropped_samples"] == 2
    assert dropped_sample_warning.kwargs["invalid_samples"] == 0
    assert dropped_sample_warning.kwargs["ingest_failures"] == 0
    assert dropped_sample_warning.kwargs["ingest_attempts"] == 3
    transition_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(transition_logs) == 1
    transition_log = transition_logs[0]
    assert transition_log.kwargs["previous_streak"] == 0
    assert transition_log.kwargs["current_streak"] == 1
    assert transition_log.kwargs["anomaly_reason_flags"] == ["dropped_samples_detected"]


@pytest.mark.asyncio
async def test_get_health_transition_metadata_includes_combined_anomaly_reason_flags(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 4,
            "runtime_adapter_invalid_samples": 3,
            "runtime_adapter_dropped_samples": 2,
            "runtime_adapter_ingest_attempts": 1,
            "runtime_adapter_ingest_failures": 1,
            "runtime_adapter_anomaly_streak": 2,
        }
    )
    counter_service.set_runtime_adapter_anomaly_streak = AsyncMock(return_value=3)
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with patch("app.modules.telemetry.service.logger.warning") as mock_warning:
        result = await svc.get_health()

    assert result.status == "ok"
    counter_service.set_runtime_adapter_anomaly_streak.assert_awaited_once_with(3)
    transition_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(transition_logs) == 1
    transition_log = transition_logs[0]
    assert transition_log.kwargs["previous_streak"] == 2
    assert transition_log.kwargs["current_streak"] == 3
    assert transition_log.kwargs["anomaly_reason_flags"] == [
        "ingest_failures_detected",
        "dropped_samples_detected",
        "invalid_sample_ratio_exceeded",
    ]


@pytest.mark.asyncio
async def test_get_health_anomaly_streak_increments_on_consecutive_anomaly_snapshots(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        side_effect=[
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 0,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 0,
                "runtime_adapter_ingest_failures": 1,
                "runtime_adapter_anomaly_streak": 0,
            },
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 0,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 0,
                "runtime_adapter_ingest_failures": 1,
                "runtime_adapter_anomaly_streak": 1,
            },
        ]
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
        patch.object(
            counter_service,
            "set_runtime_adapter_anomaly_streak",
            new=AsyncMock(return_value=1),
        ) as mock_set_streak,
    ):
        await svc.get_health()
        await svc.get_health()

    streak_warnings = [
        call
        for call in mock_warning.call_args_list
        if call.args and call.args[0] == "telemetry_health_runtime_adapter_anomaly_streak_incremented"
    ]
    assert len(streak_warnings) == 2
    assert streak_warnings[0].kwargs["anomaly_streak"] == 1
    assert streak_warnings[1].kwargs["anomaly_streak"] == 2
    assert mock_set_streak.await_args_list[0].args[0] == 1
    assert mock_set_streak.await_args_list[1].args[0] == 2
    transition_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(transition_logs) == 2
    assert transition_logs[0].kwargs["previous_streak"] == 0
    assert transition_logs[0].kwargs["current_streak"] == 1
    assert transition_logs[0].kwargs["anomaly_reason_flags"] == ["ingest_failures_detected"]
    assert transition_logs[1].kwargs["previous_streak"] == 1
    assert transition_logs[1].kwargs["current_streak"] == 2
    assert transition_logs[1].kwargs["anomaly_reason_flags"] == ["ingest_failures_detected"]


@pytest.mark.asyncio
async def test_get_health_anomaly_streak_resets_on_healthy_snapshot(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        side_effect=[
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 0,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 0,
                "runtime_adapter_ingest_failures": 1,
                "runtime_adapter_anomaly_streak": 2,
            },
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 4,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 4,
                "runtime_adapter_ingest_failures": 0,
                "runtime_adapter_anomaly_streak": 3,
            },
        ]
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
        patch("app.modules.telemetry.service.logger.info") as mock_info,
        patch.object(
            counter_service,
            "set_runtime_adapter_anomaly_streak",
            new=AsyncMock(return_value=0),
        ) as mock_set_streak,
    ):
        await svc.get_health()
        await svc.get_health()

    assert any(
        call.args and call.args[0] == "telemetry_health_runtime_adapter_anomaly_streak_incremented"
        for call in mock_warning.call_args_list
    )
    reset_logs = [
        call
        for call in mock_info.call_args_list
        if call.args and call.args[0] == "telemetry_health_runtime_adapter_anomaly_streak_reset"
    ]
    assert len(reset_logs) == 1
    assert reset_logs[0].kwargs["previous_streak"] == 3
    assert mock_set_streak.await_args_list[0].args[0] == 3
    assert mock_set_streak.await_args_list[1].args[0] == 0
    warning_transition_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(warning_transition_logs) == 1
    assert warning_transition_logs[0].kwargs["previous_streak"] == 2
    assert warning_transition_logs[0].kwargs["current_streak"] == 3
    assert warning_transition_logs[0].kwargs["anomaly_reason_flags"] == [
        "ingest_failures_detected"
    ]
    info_transition_logs = _event_calls(
        mock_info, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(info_transition_logs) == 1
    assert info_transition_logs[0].kwargs["previous_streak"] == 3
    assert info_transition_logs[0].kwargs["current_streak"] == 0
    assert info_transition_logs[0].kwargs["anomaly_reason_flags"] == []


@pytest.mark.asyncio
async def test_get_health_snapshot_failure_keeps_anomaly_streak_fail_open(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        side_effect=[
            {
                "ingested_events": 0,
                "persisted_events": 0,
                "fanout_events": 0,
                "dropped_events": 0,
                "runtime_exhausted_cycles": 0,
                "runtime_exhausted_streak": 0,
                "runtime_sustained_failure_windows": 0,
                "runtime_sustained_failure_active": 0,
                "runtime_adapter_last_batch_size": 0,
                "runtime_adapter_invalid_samples": 0,
                "runtime_adapter_ingest_attempts": 0,
                "runtime_adapter_ingest_failures": 1,
                "runtime_adapter_anomaly_streak": 0,
            },
            RuntimeError("redis unavailable"),
        ]
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
        patch("app.modules.telemetry.service.logger.info") as mock_info,
    ):
        await svc.get_health()
        await svc.get_health()

    streak_warnings = [
        call
        for call in mock_warning.call_args_list
        if call.args and call.args[0] == "telemetry_health_runtime_adapter_anomaly_streak_incremented"
    ]
    assert len(streak_warnings) == 1
    assert any(
        call.args and call.args[0] == "telemetry_health_counter_snapshot_failed"
        for call in mock_warning.call_args_list
    )
    assert not any(
        call.args and call.args[0] == "telemetry_health_runtime_adapter_anomaly_streak_reset"
        for call in mock_info.call_args_list
    )
    warning_transition_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(warning_transition_logs) == 1
    assert warning_transition_logs[0].kwargs["previous_streak"] == 0
    assert warning_transition_logs[0].kwargs["current_streak"] == 1
    assert warning_transition_logs[0].kwargs["anomaly_reason_flags"] == [
        "ingest_failures_detected"
    ]
    info_transition_logs = _event_calls(
        mock_info, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(info_transition_logs) == 1
    assert info_transition_logs[0].kwargs["previous_streak"] == 0
    assert info_transition_logs[0].kwargs["current_streak"] == 0
    assert info_transition_logs[0].kwargs["anomaly_reason_flags"] == []


@pytest.mark.asyncio
async def test_get_health_anomaly_streak_counter_write_failure_is_fail_open(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 0,
            "runtime_adapter_invalid_samples": 0,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 0,
            "runtime_adapter_ingest_failures": 1,
            "runtime_adapter_anomaly_streak": 4,
        }
    )
    counter_service.set_runtime_adapter_anomaly_streak = AsyncMock(
        side_effect=RuntimeError("redis write failed")
    )
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with patch("app.modules.telemetry.service.logger.warning") as mock_warning:
        result = await svc.get_health()

    assert result.status == "ok"
    assert any(
        call.args and call.args[0] == "telemetry_health_runtime_adapter_anomaly_streak_incremented"
        for call in mock_warning.call_args_list
    )
    assert any(
        call.args and call.args[0] == "telemetry_health_runtime_adapter_anomaly_streak_persist_failed"
        for call in mock_warning.call_args_list
    )
    transition_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(transition_logs) == 1
    transition_log = transition_logs[0]
    assert transition_log.kwargs["previous_streak"] == 4
    assert transition_log.kwargs["current_streak"] == 5
    assert transition_log.kwargs["anomaly_reason_flags"] == ["ingest_failures_detected"]


@pytest.mark.asyncio
async def test_get_health_anomaly_streak_counter_read_failure_falls_back_to_zero(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(side_effect=RuntimeError("redis read failed"))
    counter_service.set_runtime_adapter_anomaly_streak = AsyncMock(return_value=0)
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with (
        patch("app.modules.telemetry.service.logger.warning") as mock_warning,
        patch("app.modules.telemetry.service.logger.info") as mock_info,
    ):
        result = await svc.get_health()

    assert result.status == "ok"
    assert any(
        call.args and call.args[0] == "telemetry_health_counter_snapshot_failed"
        for call in mock_warning.call_args_list
    )
    assert not any(
        call.args and call.args[0] == "telemetry_health_runtime_adapter_anomaly_streak_reset"
        for call in mock_info.call_args_list
    )
    transition_logs = _event_calls(
        mock_info, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(transition_logs) == 1
    transition_log = transition_logs[0]
    assert transition_log.kwargs["previous_streak"] == 0
    assert transition_log.kwargs["current_streak"] == 0
    assert transition_log.kwargs["anomaly_reason_flags"] == []


@pytest.mark.asyncio
async def test_get_health_uses_counter_snapshot_streak_for_cross_instance_continuity(mock_db):
    counter_service = AsyncMock()
    counter_service.get_snapshot = AsyncMock(
        return_value={
            "ingested_events": 0,
            "persisted_events": 0,
            "fanout_events": 0,
            "dropped_events": 0,
            "runtime_exhausted_cycles": 0,
            "runtime_exhausted_streak": 0,
            "runtime_sustained_failure_windows": 0,
            "runtime_sustained_failure_active": 0,
            "runtime_adapter_last_batch_size": 0,
            "runtime_adapter_invalid_samples": 0,
            "runtime_adapter_dropped_samples": 0,
            "runtime_adapter_ingest_attempts": 0,
            "runtime_adapter_ingest_failures": 1,
            "runtime_adapter_anomaly_streak": 7,
        }
    )
    counter_service.set_runtime_adapter_anomaly_streak = AsyncMock(return_value=8)
    svc = TelemetryQueryService(db=mock_db, counter_service=counter_service)
    svc._repo.get_latest_observed_at = AsyncMock(return_value=None)
    svc._repo.count_all = AsyncMock(return_value=0)

    with patch("app.modules.telemetry.service.logger.warning") as mock_warning:
        result = await svc.get_health()

    assert result.status == "ok"
    counter_service.set_runtime_adapter_anomaly_streak.assert_awaited_once_with(8)
    streak_logs = [
        call
        for call in mock_warning.call_args_list
        if call.args and call.args[0] == "telemetry_health_runtime_adapter_anomaly_streak_incremented"
    ]
    assert len(streak_logs) == 1
    assert streak_logs[0].kwargs["anomaly_streak"] == 8
    transition_logs = _event_calls(
        mock_warning, "telemetry_health_runtime_adapter_anomaly_streak_transition"
    )
    assert len(transition_logs) == 1
    transition_log = transition_logs[0]
    assert transition_log.kwargs["previous_streak"] == 7
    assert transition_log.kwargs["current_streak"] == 8
    assert transition_log.kwargs["anomaly_reason_flags"] == ["ingest_failures_detected"]
