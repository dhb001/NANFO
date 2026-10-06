import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.modules.alert.detector import (
    DetectorRule, DetectorSettings, MeasuredObservation, advance_window, detector_identity, identity_key,
)
from app.modules.alert.measured import MeasuredAlertService
from tests.alert_support import ORG, RUN, START, event_for, observation


def state():
    return SimpleNamespace(last_observed_at=None, last_event_id=None, phase=None, phase_since=None, sample_count=0)


@pytest.mark.parametrize("metric,rule_name,breach,recover", [
    ("link_utilization_percent", "utilization", 85, 70),
    ("latency_ms", "latency", 100, 70),
    ("packet_loss_percent", "loss", 2, 1),
    ("queue_backlog_packets", "queue", 80, 40),
])
def test_exact_threshold_duration_hysteresis(metric, rule_name, breach, recover):
    rule = getattr(DetectorSettings(), rule_name)
    assert (rule.breach, rule.recover) == (breach, recover)
    window = state()
    for seconds, ready in [(0, False), (4, False), (9, False), (10, True)]:
        sample = observation(seconds, breach, metric)
        assert advance_window(window, sample, rule, now=sample.observed_at) is ready
    sample = observation(15, recover, metric)
    assert not advance_window(window, sample, rule, now=sample.observed_at)
    assert window.phase is None
    for seconds, ready in [(20, False), (25, False), (30, True)]:
        sample = observation(seconds, recover - 1, metric)
        assert advance_window(window, sample, rule, now=sample.observed_at) is ready
        assert window.phase == "recovery"


def test_two_samples_not_enough_even_over_duration():
    window, rule = state(), DetectorSettings().utilization
    for seconds in [0, 10]:
        sample = observation(seconds)
        assert not advance_window(window, sample, rule, now=sample.observed_at)
    assert window.sample_count == 2


def test_gap_resets_and_max_gap_is_inclusive():
    window, rule = state(), DetectorSettings().utilization
    for seconds, count, ready in [(0, 1, False), (5, 2, False), (16, 1, False), (26, 2, False), (36, 3, True)]:
        sample = observation(seconds)
        assert advance_window(window, sample, rule, now=sample.observed_at) is ready
        assert window.sample_count == count


@pytest.mark.parametrize("offset,age", [(0, 0), (-1, 0), (5, 31), (5, -1)])
def test_duplicate_out_of_order_stale_future_do_not_advance(offset, age):
    window, rule = state(), DetectorSettings().utilization
    advance_window(window, observation(), rule, now=START)
    before = vars(window).copy()
    sample = observation(offset, 0)
    assert not advance_window(window, sample, rule, now=sample.observed_at + timedelta(seconds=age))
    assert vars(window) == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, "85", -1, None])
def test_invalid_measurement_values(value):
    with pytest.raises(ValidationError):
        observation(value=value)


@pytest.mark.parametrize("changes", [
    {"unit": "ratio"}, {"source": "demo"}, {"unit": "bytes"},
    {"tags": {"synthetic": True}}, {"tags": {"synthetic": "false"}},
    {"tags": {"quality": "modeled"}}, {"tags": {"freshness": "stale"}},
    {"tags": {"measurement_method": "unknown"}}, {"tags": {"port_no": None}},
    {"tags": {"run_id": None}}, {"tags": {"rate_quality": "unavailable"}},
    {"tags": {"capacity_mbps": None}}, {"tags": {"interval_seconds": None}},
    {"observed_at": START.replace(tzinfo=None)},
])
def test_provenance_units_missing_tags_rejected(changes):
    data = observation().model_dump()
    if "tags" in changes:
        changes = {"tags": {**data["tags"], **changes["tags"]}}
    with pytest.raises(ValidationError):
        MeasuredObservation.model_validate({**data, **changes})


def test_rule_configuration_requires_hysteresis_and_minimums(monkeypatch):
    for change in [{"recover": 85}, {"min_samples": 2}, {"duration_seconds": 9}, {"max_gap_seconds": 0}]:
        with pytest.raises(ValidationError):
            DetectorRule.model_validate({**DetectorSettings().utilization.model_dump(), **change})
    monkeypatch.setenv("ALERT_UTILIZATION", '{"version":"site-v2","breach":90,"recover":60}')
    assert DetectorSettings().utilization.breach == 90


def test_identity_includes_all_tenant_resource_run_rule_dimensions():
    base = detector_identity(observation(), ORG, DetectorSettings().utilization)
    key = identity_key(base)
    for dimension in ["org_id", "workspace_id", "network_id", "device_id", "port_no", "peer_host", "run_id", "rule_version"]:
        assert identity_key({**base, dimension: str(uuid.uuid4())}) != key
    assert identity_key(dict(reversed(list(base.items())))) == key


async def test_invalid_synthetic_event_never_queries_or_applies(mock_db):
    service = MeasuredAlertService(db=mock_db)
    service.apply_observation = AsyncMock()
    event = event_for(observation())
    event["payload"]["tags"]["synthetic"] = True
    await service.ingest_persisted_event(event)
    service.apply_observation.assert_not_awaited()
    mock_db.execute.assert_not_awaited()


@pytest.mark.parametrize("metric,change", [
    ("latency_ms", {"latency_semantics": "one_way"}),
    ("packet_loss_percent", {"loss_semantics": "interface_drops"}),
    ("latency_ms", {"peer_host": None}),
])
def test_unknown_probe_semantics_rejected(metric, change):
    data = observation(metric=metric).model_dump()
    data["tags"].update(change)
    with pytest.raises(ValidationError):
        MeasuredObservation.model_validate(data)


def test_queue_bytes_or_fractional_packets_are_not_packet_measurements():
    with pytest.raises(ValidationError):
        observation(metric="queue_backlog_packets", value=80.5)
    with pytest.raises(ValidationError):
        observation(metric="queue_backlog_packets", value=80, unit="bytes")


def test_identity_digest_is_an_explicitly_named_nan_tolerant_variant():
    """ADR-028 C20: persisted detector keys/payload receipts keep their exact bytes."""
    import hashlib
    import json

    from app.core.canonical import canonical_sha256
    from app.modules.alert.detector import nan_tolerant_identity_sha256

    identity = detector_identity(observation(), ORG, DetectorSettings().utilization)
    historical = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert identity_key(identity) == nan_tolerant_identity_sha256(identity) == historical
    # Finite values agree with the strict canonical helper...
    assert identity_key(identity) == canonical_sha256(identity)
    # ...but legacy payloads with non-finite numbers must still hash (strict one rejects them).
    legacy = {"source": "telemetry", "payload": {"threshold": float("nan"), "limit": float("inf")}}
    assert identity_key(legacy) == hashlib.sha256(
        b'{"payload":{"limit":Infinity,"threshold":NaN},"source":"telemetry"}').hexdigest()
    with pytest.raises(ValueError):
        canonical_sha256(legacy)


@pytest.mark.parametrize("correlation", ["req-opaque-123", "{%s}" % RUN, RUN.hex])
async def test_opaque_event_correlation_still_locates_the_persisted_record(mock_db, monkeypatch, correlation):
    """ADR-028 C20: the locator's request id maps via app.core.correlation, never drops the sample."""
    from app.modules.alert import measured
    from app.modules.telemetry.schemas import TelemetryDeviceHistoryResponse

    sample = observation()
    event = {**event_for(sample), "correlation_id": correlation}
    history = AsyncMock(return_value=TelemetryDeviceHistoryResponse(device_id=sample.device_id, items=[], total=0,
                                                                    page=1, page_size=500))
    monkeypatch.setattr(measured.TelemetryQueryService, "get_device_history", history)
    service = MeasuredAlertService(db=mock_db)
    service.apply_observation = AsyncMock()
    await service.ingest_persisted_event(event)
    history.assert_awaited_once()
    assert history.await_args.kwargs["device_id"] == sample.device_id
    service.apply_observation.assert_not_awaited()  # nothing persisted under that event id
