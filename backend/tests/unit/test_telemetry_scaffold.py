"""Unit tests for telemetry ingestion scaffold (VS2 Step 5)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.telemetry.service import (
    TelemetryCollectorRunner,
    TelemetryIngestionService,
    compute_bounded_backoff_seconds,
)


@pytest.mark.asyncio
async def test_telemetry_normalize_payload_coerces_types_and_defaults(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    normalized = svc.normalize_payload(
        {
            "device_id": uuid.uuid4(),
            "network_id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "metric": "cpu_usage",
            "value": "42.5",
            "unit": "percent",
            "source": "snmp",
            "tags": {"vendor": "test"},
        }
    )

    assert normalized["metric"] == "cpu_usage"
    assert normalized["value"] == 42.5
    assert normalized["unit"] == "percent"
    assert normalized["source"] == "snmp"
    assert normalized["tags"] == {"vendor": "test"}
    assert normalized["observed_at"]


@pytest.mark.asyncio
async def test_telemetry_ingest_publishes_expected_event(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    with patch("app.modules.telemetry.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "1712425-0"
        entry_id = await svc.ingest(
            raw={
                "device_id": str(uuid.uuid4()),
                "network_id": str(uuid.uuid4()),
                "workspace_id": str(uuid.uuid4()),
                "metric": "latency_ms",
                "value": 12,
            },
            correlation_id=str(uuid.uuid4()),
        )

    assert entry_id == "1712425-0"
    kwargs = mock_publish.call_args.kwargs
    assert kwargs["event_type"] == "telemetry.metric.ingested"
    assert kwargs["source"] == "telemetry"
    assert "metric" in kwargs["payload"]
    assert kwargs["payload"]["metric"] == "latency_ms"
    assert await fake_redis.get("telemetry:health:ingested_events") == "1"


@pytest.mark.asyncio
async def test_telemetry_ingest_ignores_counter_failures(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    with (
        patch("app.modules.telemetry.service.publish_event", new_callable=AsyncMock) as mock_publish,
        patch.object(svc._counter_service, "increment_ingested", new_callable=AsyncMock) as mock_increment,
    ):
        mock_publish.return_value = "1712425-0"
        mock_increment.side_effect = RuntimeError("redis unavailable")
        entry_id = await svc.ingest(
            raw={
                "device_id": str(uuid.uuid4()),
                "network_id": str(uuid.uuid4()),
                "workspace_id": str(uuid.uuid4()),
                "metric": "latency_ms",
                "value": 12,
            },
            correlation_id=str(uuid.uuid4()),
        )

    assert entry_id == "1712425-0"


@pytest.mark.asyncio
async def test_collector_runner_start_stop_and_ingest_once(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    assert runner.running is False
    await runner.start()
    assert runner.running is True

    with patch.object(svc, "ingest", new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = "1-0"
        entry_id = await runner.ingest_once(raw={"metric": "cpu", "value": 1}, correlation_id=str(uuid.uuid4()))

    assert entry_id == "1-0"
    mock_ingest.assert_awaited_once()

    await runner.stop()
    assert runner.running is False


@pytest.mark.asyncio
async def test_compute_bounded_backoff_seconds_is_bounded_and_exponential():
    assert compute_bounded_backoff_seconds(
        1,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
    ) == 0.5
    assert compute_bounded_backoff_seconds(
        2,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
    ) == 1.0
    assert compute_bounded_backoff_seconds(
        3,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
    ) == 2.0
    assert compute_bounded_backoff_seconds(
        4,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
    ) == 2.0


@pytest.mark.asyncio
async def test_collector_runner_start_with_retry_succeeds_after_transient_failures(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    sleep = AsyncMock()
    with patch.object(
        runner,
        "start",
        new=AsyncMock(side_effect=[RuntimeError("first"), RuntimeError("second"), None]),
    ):
        started = await runner.start_with_retry(
            max_attempts=3,
            base_backoff_seconds=0.5,
            max_backoff_seconds=2.0,
            sleep=sleep,
        )

    assert started is True
    assert sleep.await_count == 2
    assert sleep.await_args_list[0].args[0] == 0.5
    assert sleep.await_args_list[1].args[0] == 1.0


@pytest.mark.asyncio
async def test_collector_runner_start_with_retry_exhausts_attempts(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    sleep = AsyncMock()
    with patch.object(
        runner,
        "start",
        new=AsyncMock(side_effect=[RuntimeError("first"), RuntimeError("second"), RuntimeError("third")]),
    ):
        started = await runner.start_with_retry(
            max_attempts=3,
            base_backoff_seconds=0.5,
            max_backoff_seconds=2.0,
            sleep=sleep,
        )

    assert started is False
    assert runner.running is False
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_collector_runner_start_with_retry_immediate_success_avoids_sleep(fake_redis):
    svc = TelemetryIngestionService(redis=fake_redis)
    runner = TelemetryCollectorRunner(ingestion_service=svc)

    sleep = AsyncMock()
    started = await runner.start_with_retry(
        max_attempts=3,
        base_backoff_seconds=0.5,
        max_backoff_seconds=2.0,
        sleep=sleep,
    )

    assert started is True
    assert runner.running is True
    sleep.assert_not_awaited()
