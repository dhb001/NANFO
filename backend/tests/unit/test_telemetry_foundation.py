"""Step1 telemetry truth: mode gates, finite samples, provenance, and unknown health."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.load_tooling import (
    build_vs17_deterministic_sample,
    get_vs17_load_profile,
)
from app.modules.telemetry.service import (
    TelemetryIngestionService,
    TelemetryQueryService,
    build_production_runtime_adapter,
)

pytestmark = pytest.mark.usefixtures("execution_mode")


def _adapter(mode):
    return build_production_runtime_adapter(
        mode=mode, seeded_sample_key="foundation", seeded_metric="latency_ms",
        seeded_value=12.5, seeded_unit="ms", seeded_source="runtime_seeded",
    )


@pytest.mark.parametrize("mode", ["demo", "emulation", "production"])
def test_execution_mode_loads_from_environment(execution_mode, mode):
    execution_mode(mode)
    assert get_settings().EXECUTION_MODE == mode


def test_execution_mode_default_and_invalid_value(execution_mode, monkeypatch):
    monkeypatch.delenv("EXECUTION_MODE")
    assert Settings(_env_file=None).EXECUTION_MODE == "demo"
    execution_mode("invalid")
    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.parametrize("mode", ["emulation", "production"])
@pytest.mark.parametrize("adapter_mode", ["seeded", "snmp", "grpc"])
async def test_synthetic_adapter_blocked_at_construction_and_poll(execution_mode, mode, adapter_mode):
    adapter = _adapter(adapter_mode)
    execution_mode(mode)
    with pytest.raises(ValueError, match="No measured runtime telemetry adapter"):
        _adapter(adapter_mode)
    with pytest.raises(ValueError, match="only available in demo mode"):
        await adapter.poll()


@pytest.mark.parametrize("mode", ["demo", "emulation", "production"])
async def test_stub_never_fabricates_samples(execution_mode, mode):
    execution_mode(mode)
    assert await _adapter("stub").poll() == []


@pytest.mark.parametrize("adapter_mode", ["seeded", "snmp", "grpc"])
async def test_demo_provenance_survives_ingestion(adapter_mode, fake_redis):
    raw = (await _adapter(adapter_mode).poll())[0]
    with patch("app.modules.telemetry.ingestion.publish_event", new_callable=AsyncMock) as publish:
        await TelemetryIngestionService(fake_redis).ingest(raw, str(uuid.UUID(int=1)))
    tags = publish.await_args.kwargs["payload"]["tags"]
    assert tags["synthetic"] is True
    assert tags["execution_mode"] == "demo"
    assert tags["adapter_mode"] == adapter_mode
    assert tags.get("measured") is not True


@pytest.mark.parametrize("raw_value", [None, True, False, "invalid", "", "NaN", "Infinity", float("nan"), float("inf"), -float("inf"), {}, []])
async def test_invalid_value_never_becomes_zero_or_publishes(raw_value, fake_redis):
    svc = TelemetryIngestionService(fake_redis)
    with patch("app.modules.telemetry.ingestion.publish_event", new_callable=AsyncMock) as publish:
        with pytest.raises(ValueError):
            await svc.ingest({"metric": "latency_ms", "value": raw_value}, str(uuid.UUID(int=1)))
        publish.assert_not_awaited()
    assert await fake_redis.get("telemetry:health:ingested_events") is None


async def test_missing_value_rejected(fake_redis):
    with pytest.raises(ValueError):
        TelemetryIngestionService(fake_redis).normalize_payload({"metric": "latency_ms"})


@pytest.mark.parametrize("value", [0, 0.0, "0", -2.5, "42.5"])
def test_finite_values_including_real_zero_preserved(fake_redis, value):
    normalized = TelemetryIngestionService(fake_redis).normalize_payload({"metric": "value", "value": value})
    assert normalized["value"] == float(value)
    assert normalized["tags"] == {}


@pytest.mark.parametrize("profile", ["local-smoke", "local-burst", "staging-baseline"])
def test_load_fixture_explicitly_synthetic_demo(profile, fake_redis):
    raw = build_vs17_deterministic_sample(profile=get_vs17_load_profile(profile), index=0)
    tags = TelemetryIngestionService(fake_redis).normalize_payload(raw)["tags"]
    assert tags["synthetic"] is True
    assert tags["execution_mode"] == "demo"
    assert tags.get("measured") is not True


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("observed", [False, True])
async def test_health_distinguishes_unknown_lag_from_measured_lag(mock_db, fake_redis, failure, observed):
    await fake_redis.set("telemetry:health:runtime_sustained_failure_active", int(failure))
    svc = TelemetryQueryService(mock_db, counter_service=TelemetryHealthCounterService(fake_redis))
    latest = datetime.now(UTC) - timedelta(seconds=2) if observed else None
    svc._repo.get_latest_observed_at = AsyncMock(return_value=latest)
    svc._repo.estimate_total_records = AsyncMock(return_value=(1 if observed else 0, False))
    result = await svc.get_health()
    assert result.status == ("degraded" if failure else "ok" if observed else "unavailable")
    assert result.latest_observed_at == latest
    if observed:
        assert result.ingest_lag_ms >= 2000
    else:
        assert result.model_dump(mode="json")["ingest_lag_ms"] is None


@pytest.mark.parametrize("observed_at", ["2026-09-08T00:00:00", "3000-01-01T00:00:00Z", 12345])
def test_ingestion_rejects_naive_and_far_future_timestamps(fake_redis, observed_at):
    with pytest.raises(ValueError):
        TelemetryIngestionService(fake_redis).normalize_payload(
            {"metric": "latency_ms", "value": 1, "observed_at": observed_at})


def test_ingestion_emits_canonical_utc_timestamps(fake_redis):
    normalized = TelemetryIngestionService(fake_redis).normalize_payload(
        {"metric": "latency_ms", "value": 1, "observed_at": "2026-09-08T03:00:00+03:00"})
    assert normalized["observed_at"] == "2026-09-08T00:00:00+00:00"
    stamped = TelemetryIngestionService(fake_redis).normalize_payload({"metric": "latency_ms", "value": 1})
    assert datetime.fromisoformat(stamped["observed_at"]).tzinfo is not None


async def test_poll_action_counts_bad_timestamps_as_invalid_samples_not_failures(fake_redis):
    from app.modules.telemetry.service import TelemetryCollectorRunner, build_runtime_poll_action

    svc = TelemetryIngestionService(fake_redis)
    runner = TelemetryCollectorRunner(svc, slo_evaluator=None)
    sample = {"device_id": str(uuid.uuid4()), "network_id": str(uuid.uuid4()), "workspace_id": str(uuid.uuid4()),
              "metric": "latency_ms", "value": 1.0, "observed_at": "2026-09-08T00:00:00"}
    adapter = AsyncMock()
    adapter.poll = AsyncMock(return_value=[sample])
    await build_runtime_poll_action(collector_runner=runner, adapter=adapter)()
    snapshot = await svc.counter_service.get_snapshot()
    assert snapshot["runtime_adapter_invalid_samples"] == 1 and snapshot["runtime_adapter_ingest_failures"] == 0
    adapter.acknowledge_batch.assert_not_awaited()
