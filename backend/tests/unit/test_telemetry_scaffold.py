"""Unit tests for telemetry ingestion scaffold (VS2 Step 5)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.events.consumers.telemetry_consumer import handle_telemetry_event
from app.modules.telemetry.service import (
    TelemetryCollectorRunner,
    TelemetryIngestionService,
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


@pytest.mark.asyncio
async def test_telemetry_consumer_stub_parses_without_side_effects():
    event = {
        "event_type": "telemetry.metric.ingested",
        "correlation_id": str(uuid.uuid4()),
        "payload": {
            "device_id": str(uuid.uuid4()),
            "network_id": str(uuid.uuid4()),
            "workspace_id": str(uuid.uuid4()),
            "metric": "packet_loss",
            "value": 0.02,
            "unit": "ratio",
            "observed_at": "2026-08-09T00:00:00+00:00",
            "source": "collector",
            "tags": {},
        },
    }
    await handle_telemetry_event(event)


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
