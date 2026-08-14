"""Integration coverage for VS15 synthetic telemetry burst campaign."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.events.consumers.telemetry_consumer import handle_telemetry_event
from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.service import TelemetryIngestionService


def _synthetic_sample(index: int) -> dict[str, object]:
    return {
        "device_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"vs15-device-{index}")),
        "network_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "vs15-network")),
        "workspace_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "vs15-workspace")),
        "metric": "latency_ms",
        "value": float(10 + (index % 7)),
        "unit": "ms",
        "observed_at": datetime.now(UTC).isoformat(),
        "source": "synthetic_load",
        "tags": {
            "campaign": "vs15_burst",
            "sample_index": str(index),
        },
    }


def _build_session_context() -> tuple[AsyncMock, AsyncMock]:
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
    return db, session_cm


@pytest.mark.asyncio
async def test_synthetic_telemetry_burst_preserves_pipeline_counters(integration_fake_redis):
    burst_size = 120
    await integration_fake_redis.delete(
        "stream:telemetry",
        "telemetry:health:ingested_events",
        "telemetry:health:persisted_events",
        "telemetry:health:fanout_events",
        "telemetry:health:dropped_events",
    )

    ingestion = TelemetryIngestionService(redis=integration_fake_redis)
    for index in range(burst_size):
        await ingestion.ingest(
            raw=_synthetic_sample(index),
            correlation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"vs15-correlation-{index}")),
        )

    stream_entries = await integration_fake_redis.xrange("stream:telemetry")
    assert len(stream_entries) == burst_size

    db, session_cm = _build_session_context()
    with (
        patch("app.events.consumers.telemetry_consumer.AsyncSessionLocal", return_value=session_cm),
        patch("app.events.consumers.telemetry_consumer.get_redis_client", return_value=integration_fake_redis),
        patch("app.events.consumers.telemetry_consumer.telemetry_ws_manager") as mock_ws_manager,
    ):
        mock_ws_manager.push_delta = AsyncMock()
        for _, fields in stream_entries:
            event_data = {**fields, "payload": json.loads(fields["payload"])}
            await handle_telemetry_event(event_data)

    snapshot = await TelemetryHealthCounterService(integration_fake_redis).get_snapshot()
    assert snapshot["ingested_events"] == burst_size
    assert snapshot["persisted_events"] == burst_size
    assert snapshot["fanout_events"] == burst_size
    assert snapshot["dropped_events"] == 0
    assert db.commit.await_count == burst_size
