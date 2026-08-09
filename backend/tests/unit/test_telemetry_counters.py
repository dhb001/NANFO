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
    }


@pytest.mark.asyncio
async def test_telemetry_health_counter_increments_are_reflected_in_snapshot(fake_redis):
    svc = TelemetryHealthCounterService(fake_redis)

    await svc.increment_ingested()
    await svc.increment_ingested()
    await svc.increment_persisted()
    await svc.increment_fanout()
    await svc.increment_dropped()

    snapshot = await svc.get_snapshot()

    assert snapshot == {
        "ingested_events": 2,
        "persisted_events": 1,
        "fanout_events": 1,
        "dropped_events": 1,
    }
