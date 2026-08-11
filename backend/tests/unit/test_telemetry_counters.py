"""Unit tests for telemetry health counters (VS2 Step 8)."""

from __future__ import annotations

import pytest
from app.modules.telemetry.counters import TelemetryHealthCounterService


@pytest.mark.asyncio
async def test_telemetry_health_counter_snapshot_defaults_to_zero(fake_redis):
    svc = TelemetryHealthCounterService(fake_redis)

    snapshot = await svc.get_snapshot()

    assert snapshot == {
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
        "runtime_adapter_ingest_failures": 0,
        "runtime_adapter_anomaly_streak": 0,
    }


@pytest.mark.asyncio
async def test_telemetry_health_counter_increments_are_reflected_in_snapshot(fake_redis):
    svc = TelemetryHealthCounterService(fake_redis)

    await svc.increment_ingested()
    await svc.increment_ingested()
    await svc.increment_persisted()
    await svc.increment_fanout()
    await svc.increment_dropped()
    await svc.increment_runtime_exhausted_cycle()
    await svc.set_runtime_exhausted_streak(2)
    await svc.increment_runtime_sustained_failure_window()
    await svc.set_runtime_sustained_failure_active(True)
    await svc.set_runtime_adapter_last_batch_size(25)
    await svc.increment_runtime_adapter_invalid_sample()
    await svc.increment_runtime_adapter_invalid_sample()
    await svc.increment_runtime_adapter_dropped_sample()
    await svc.increment_runtime_adapter_ingest_attempt()
    await svc.increment_runtime_adapter_ingest_attempt()
    await svc.increment_runtime_adapter_ingest_failure()
    await svc.set_runtime_adapter_anomaly_streak(2)

    snapshot = await svc.get_snapshot()

    assert snapshot == {
        "ingested_events": 2,
        "persisted_events": 1,
        "fanout_events": 1,
        "dropped_events": 1,
        "runtime_exhausted_cycles": 1,
        "runtime_exhausted_streak": 2,
        "runtime_sustained_failure_windows": 1,
        "runtime_sustained_failure_active": 1,
        "runtime_adapter_last_batch_size": 25,
        "runtime_adapter_invalid_samples": 2,
        "runtime_adapter_dropped_samples": 1,
        "runtime_adapter_ingest_attempts": 2,
        "runtime_adapter_ingest_failures": 1,
        "runtime_adapter_anomaly_streak": 2,
    }
