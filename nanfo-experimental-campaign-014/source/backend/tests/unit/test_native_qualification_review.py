"""Q1/Q2/Q5 regressions. No native namespace operations or synthetic installation."""

import copy
import json
import os
from datetime import UTC, datetime, timedelta
from fractions import Fraction

import pytest
from pydantic import ValidationError

from app.modules.autonomy.artifact_io import ArtifactRef, ArtifactStore, EvidenceError
from app.modules.autonomy.calibration_verification import (
    backlog_reading_digest, shield_service_upper, verify_network_campaign,
)
from app.modules.autonomy.calibration_verification_models import NetworkQualificationConfig, NetworkReading
from app.modules.autonomy.causal_frames import safety_frame
from app.modules.autonomy.schemas import contract_digest
from emulation.native_qualification import digest
from emulation.native_qualification_causal import acquire_window, validate_ns_capture
from emulation.native_qualification_clock import causal_clock_binding, canonical_observation_clock
from scripts.native_qualification_observation import passive_causal_observation
from tests.unit.test_autonomous_causal import Instrument, configuration
from tests.unit.test_independent_validation import imported, put


def v2_campaign(tmp_path):
    campaign = imported(tmp_path)
    ref = put(tmp_path, "service-review.json", {"test_only": "source derivation fixture, not reviewed evidence"})
    campaign.configuration.update(schema_version="nanfo.network-qualification-config.v2", min_dt_seconds=.125,
                                  service_semantics_evidence=ref)
    return campaign, dict(evidence_store=ArtifactStore(str(tmp_path)), accepted_service_semantics_sha256={ref["sha256"]})


def test_q1_v1_documents_actual_departures_idle_and_drained_still_reject(tmp_path):
    campaign = imported(tmp_path)
    for capture in campaign.captures:
        for record in capture.records:
            q = record.measurement["queues"][0]
            q.update(queue_before_bytes=0., queue_after_bytes=0.)
            q["arrivals"]["after"] = q["demand_arrivals"]["d"]["after"] = q["departures"]["after"] = 0
    result = verify_network_campaign(campaign)
    assert not result["empirical_acceptance_passed"]
    assert all("service_inequality_failed" in r["failures"] for r in result["rows"])
    assert "service_lower_semantics" not in result["rows"][0]["queues"][0]  # original v1 report shape


def test_q2_burst_departures_explicit_v2_not_capacity_inflation(tmp_path):
    campaign, trust = v2_campaign(tmp_path)
    b = campaign.configuration["actions"][0]["bounds"][0]
    b.update(capacity_bytes_per_second=10000., arrival_upper_bytes_per_second=0.,
             service_lower_bytes_per_second=0., service_upper_bytes_per_second=1000.,
             service_upper_burst_bytes=200., shaper_nominal_bytes_per_second=1000.)
    for capture in campaign.captures:
        for record in capture.records:
            reading = record.measurement
            start = reading["start_unix_seconds"]
            reading.update(end_unix_seconds=start + .125, applied_unix_seconds=start,
                           transition_complete_unix_seconds=start)
            q = reading["queues"][0]
            q.update(queue_before_bytes=200., queue_after_bytes=0.)
            q["departures"]["after"] = 200
            q["arrivals"]["after"] = q["demand_arrivals"]["d"]["after"] = 0
    with pytest.raises(EvidenceError, match="service_semantics_review"):
        verify_network_campaign(campaign)
    report = verify_network_campaign(campaign, **trust)
    assert report["empirical_acceptance_passed"]
    assert report["rows"][0]["queues"][0]["shaper_nominal_bytes_per_second"] == 1000
    b["service_upper_burst_bytes"] = 0.
    assert "service_upper_inequality_failed" in verify_network_campaign(campaign, **trust)["rows"][0]["failures"]
    b["service_upper_burst_bytes"] = 200.
    b["capacity_bytes_per_second"] = 1000.
    assert "capacity_inequality_failed" in verify_network_campaign(campaign, **trust)["rows"][0]["failures"]


def test_q2_version_and_minimum_horizon_are_enforced(tmp_path):
    campaign, trust = v2_campaign(tmp_path)
    b = campaign.configuration["actions"][0]["bounds"][0]
    b["service_upper_burst_bytes"] = 2.
    config = NetworkQualificationConfig.model_validate_json(json.dumps(campaign.configuration))
    bound = config.actions[0].bounds[0]
    assert shield_service_upper(config, bound, .125) == 46
    assert shield_service_upper(config, bound, 1.) == 32
    with pytest.raises(EvidenceError, match="horizon"):
        shield_service_upper(config, bound, .0625)
    reading = campaign.captures[0].records[0].measurement
    reading["end_unix_seconds"] = reading["start_unix_seconds"] + .0625
    with pytest.raises(EvidenceError, match="horizon"):
        verify_network_campaign(campaign, **trust)
    campaign.configuration["schema_version"] = "nanfo.network-qualification-config.v1"
    with pytest.raises(ValidationError, match="explicit_version"):
        NetworkQualificationConfig.model_validate_json(json.dumps(campaign.configuration))


def busy_evidence(tmp_path, campaign):
    accepted = set()
    for capture in campaign.captures:
        for record in capture.records:
            reading = NetworkReading.model_validate(record.measurement)
            source = put(tmp_path, record.sample_id + ".source.json", {"test_native_trace": True})
            ref = put(tmp_path, record.sample_id + ".busy.json", dict(
                schema_version="nanfo.native-busy-period.v1", sample_id=record.sample_id, egress_id="q",
                reading_sha256=backlog_reading_digest(reading), start_unix_seconds=reading.start_unix_seconds,
                end_unix_seconds=reading.end_unix_seconds, initial_queue_bytes=100, final_queue_bytes=90,
                lost_events=0, native_source=source, events=[
                    dict(offset_ns=100000000, operation="enqueue", bytes=10),
                    dict(offset_ns=200000000, operation="dequeue", bytes=20)]))
            record.measurement["queues"][0]["native_backlog_evidence"] = ref
            accepted.add(ref["sha256"])
    return accepted


def test_q1_available_service_requires_independently_pinned_lossless_busy_trace(tmp_path):
    campaign, trust = v2_campaign(tmp_path)
    b = campaign.configuration["actions"][0]["bounds"][0]
    b["service_lower_semantics"] = "busy-period-available"
    with pytest.raises(EvidenceError, match="backlog_evidence_required"):
        verify_network_campaign(campaign, **trust)
    accepted = busy_evidence(tmp_path, campaign)
    assert verify_network_campaign(campaign, **trust, accepted_native_backlog_sha256=accepted)["empirical_acceptance_passed"]
    config = NetworkQualificationConfig.model_validate_json(json.dumps(campaign.configuration))
    from app.modules.autonomy.calibration_verification import runtime_service_bounds
    assert runtime_service_bounds(config, config.actions[0].bounds[0], 1.) == (0., 30.)
    q = campaign.captures[0].records[0].measurement["queues"][0]
    q["departures"]["after"] = 19
    with pytest.raises(EvidenceError, match="scope_or_precision"):
        verify_network_campaign(campaign, **trust, accepted_native_backlog_sha256=accepted)


@pytest.mark.parametrize("mutation", ["idle", "loss", "order", "total", "missing_source"])
def test_q1_bad_native_busy_evidence_refuses_even_when_pinned(tmp_path, mutation):
    campaign, trust = v2_campaign(tmp_path)
    campaign.configuration["actions"][0]["bounds"][0]["service_lower_semantics"] = "busy-period-available"
    accepted = busy_evidence(tmp_path, campaign)
    q = campaign.captures[0].records[0].measurement["queues"][0]
    ref = ArtifactRef(**q["native_backlog_evidence"])
    raw = trust["evidence_store"].document(ref.path)
    if mutation == "idle":
        raw["events"] = [dict(offset_ns=0, operation="dequeue", bytes=100),
                         dict(offset_ns=1, operation="enqueue", bytes=90)]
    elif mutation == "loss":
        raw["lost_events"] = 1
    elif mutation == "order":
        raw["events"][0]["offset_ns"] = 900000000
    elif mutation == "total":
        raw["events"][0]["bytes"] = 11
    else:
        raw["native_source"]["path"] = "absent.json"
    changed = put(tmp_path, "bad-busy.json", raw)
    q["native_backlog_evidence"] = changed
    with pytest.raises(EvidenceError):
        verify_network_campaign(campaign, **trust, accepted_native_backlog_sha256=accepted | {changed["sha256"]})


class IntegerClock:
    def __init__(self):
        self.wall = 1789895035123456400
        self.mono = 123456200

    def time_ns(self):
        self.wall += 100
        return self.wall

    def monotonic_ns(self):
        self.mono += 100
        return self.mono

    def sleep(self, seconds):
        self.wall += round(seconds * 10**9)
        self.mono += round(seconds * 10**9)


def native_capture():
    config = configuration().model_copy(update={"version": "nanfo.frr-causal-instrument/v2"})
    config.egresses[0].shaper_nominal_bytes_per_second = config.egresses[0].capacity_bytes_per_second
    config.egresses[0].measurement_error_bytes = .01
    spec = config.model_dump(mode="json")
    clock = IntegerClock()
    raw = acquire_window(Instrument(spec), spec, clock=clock, sleep=clock.sleep)
    return config, raw


def test_q5_acquisition_to_passive_observation_to_frame_without_rewriting_capture():
    config, raw = native_capture()
    original = json.dumps(raw, sort_keys=True)
    assert raw["measurement_complete"]
    # Raw submicrosecond boundary is left untouched; the old equality would fail.
    assert datetime.fromtimestamp(raw["after"]["finished_unix"], UTC).timestamp() != raw["after"]["finished_unix"]
    observation, envelope = passive_causal_observation(config, raw, collected_at=datetime(2026, 9, 21, tzinfo=UTC))
    frame = safety_frame(config, envelope, observation, sequence=1,
        accepted_guarantees={config.guarantee_sha256}, accepted_instruments={contract_digest(config)})
    assert frame.observed_at_unix_seconds == observation.observed_at.timestamp()
    assert json.dumps(raw, sort_keys=True) == original
    assert envelope["clock_binding"]["raw_capture_sha256"] == digest(raw)
    binding = envelope["clock_binding"]
    error = Fraction(raw["after"]["finished_wall_ns"], 10**9) - Fraction(frame.observed_at_unix_seconds)
    assert 0 <= error <= Fraction(binding["quantization_uncertainty_ns"], 10**9)


@pytest.mark.parametrize("mutation", ["raw", "binding", "different_time", "digest", "float_projection"])
def test_q5_mutated_raw_or_unrelated_observation_cannot_be_rebound(tmp_path, mutation):
    config, raw = native_capture()
    observation, envelope = passive_causal_observation(config, raw, collected_at=datetime(2026, 9, 21, tzinfo=UTC))
    if mutation == "raw":
        raw["after"]["queues"][0]["queue_bytes"] += 1
    elif mutation == "binding":
        envelope["clock_binding"]["quantization_uncertainty_ns"] = 0
    elif mutation == "different_time":
        observation = observation.model_copy(update={"observed_at": observation.observed_at + timedelta(microseconds=1)})
        envelope["observation_sha256"] = contract_digest(observation)
    elif mutation == "digest":
        observation = observation.model_copy(update={"evidence": ["native-capture:" + "a" * 64]})
        envelope["observation_sha256"] = contract_digest(observation)
    else:
        raw["after"]["finished_unix"] += .1
        envelope["clock_binding"] = causal_clock_binding(raw)
    with pytest.raises(ValueError):
        safety_frame(config, envelope, observation, sequence=1,
            accepted_guarantees={config.guarantee_sha256}, accepted_instruments={contract_digest(config)})


@pytest.mark.parametrize("ns", [1789895035123456200, 1789895035123456000, 1789895035999999999, 0, 2**63 - 1])
def test_canonical_timestamp_is_exact_deterministic_nonfuture_with_covered_error(ns):
    binding = canonical_observation_clock({"raw": ns}, finished_wall_ns=ns, finished_monotonic_ns=1)
    assert binding == canonical_observation_clock({"raw": ns}, finished_wall_ns=ns, finished_monotonic_ns=1)
    error = Fraction(ns, 10**9) - Fraction(binding["observed_at_unix_seconds"])
    assert 0 <= error <= Fraction(binding["quantization_uncertainty_ns"], 10**9)
    assert binding["quantization_uncertainty_ns"] <= 3000


def test_q5_native_ns_read_timing_tamper_rejected():
    config, raw = native_capture()
    raw = copy.deepcopy(raw)
    raw["after"]["queues"][0]["read_finished_monotonic_ns"] += 10**9
    with pytest.raises(ValueError):
        validate_ns_capture(raw, config.model_dump(mode="json"))


def test_v1_instrument_serialization_retains_original_digest_shape():
    assert "shaper_nominal_bytes_per_second" not in configuration().model_dump(mode="json")["egresses"][0]


def test_v2_native_raw_nominal_is_not_inflated_to_physical_capacity():
    config = configuration().model_copy(update={"version": "nanfo.frr-causal-instrument/v2"})
    config.egresses[0].shaper_nominal_bytes_per_second = 1000.
    config.egresses[0].capacity_bytes_per_second = 10000.
    config.egresses[0].measurement_error_bytes = .1
    spec = config.model_dump(mode="json")
    clock = IntegerClock()
    raw = acquire_window(Instrument(spec), spec, clock=clock, sleep=clock.sleep)
    assert raw["measurement_complete"]
    assert raw["after"]["queues"][0]["raw_classes"][0]["options"]["rate"] == 1000
    assert raw["after"]["queues"][0]["capacity_bytes_per_second"] == 10000
    observation, envelope = passive_causal_observation(config, raw, collected_at=datetime(2026, 9, 21, tzinfo=UTC))
    frame = safety_frame(config, envelope, observation, sequence=1,
        accepted_guarantees={config.guarantee_sha256}, accepted_instruments={contract_digest(config)})
    assert frame.queues[0].capacity_bytes_per_second == 10000


def test_q5_quantization_uncertainty_cannot_be_discarded_to_zero_error():
    config, raw = native_capture()
    config.egresses[0].measurement_error_bytes = 0.
    observation, envelope = passive_causal_observation(config, raw, collected_at=datetime(2026, 9, 21, tzinfo=UTC))
    with pytest.raises(ValueError, match="quantization_error_not_covered"):
        safety_frame(config, envelope, observation, sequence=1,
            accepted_guarantees={config.guarantee_sha256}, accepted_instruments={contract_digest(config)})


def test_v2_loader_supports_passing_reviewed_campaign(tmp_path, monkeypatch):
    from app.modules.autonomy import calibration_verification as verifier
    from tests.unit.test_independent_validation import installation

    store, args = installation(tmp_path)
    campaign, trust = v2_campaign(tmp_path)
    # TEST ONLY dependency injection exercises the post-import runtime gate,
    # not authentic measured provenance or a fabricated installed calibration.
    monkeypatch.setattr(verifier, "import_campaign", lambda *_args, **_kwargs: campaign)
    loaded = verifier.load_trusted_calibration(store, "installation.json", **args,
        accepted_service_semantics_sha256=trust["accepted_service_semantics_sha256"])
    assert loaded.configuration.schema_version.endswith(".v2")


def test_native_feasibility_uses_the_shields_serialized_upper_inputs():
    from scripts.native_qualification import analyze
    from tests.unit.test_native_qualification import design, policy

    d, p = design(), policy()
    d.minimum_window_seconds = d.horizon_seconds = 3.
    p.max_dt_seconds = 3.
    p.queue_threshold_bytes = 67584.
    report = analyze(d, p, {"edge": 0.})
    assert not report["arithmetic_passed"]
    assert "queue_threshold_failed:edge" in report["blockers"]


def test_retained_actual_native_v2_capture_without_timestamp_rewriting():
    """Opt-in READ-ONLY replay, never acquisition during another owner's campaign.

    Parent supplies a protected receipt with exact config/raw capture references.
    No unit fixture fallback. This test's skip is an explicit measured-evidence gap.
    """
    from app.modules.autonomy.causal_frames import CausalConfig

    root = os.environ.get("NANFO_NATIVE_REPLAY_ROOT")
    receipt_sha = os.environ.get("NANFO_NATIVE_REPLAY_RECEIPT_SHA256")
    if not root or not receipt_sha:
        pytest.skip("parent has not supplied a pinned actual native v2 capture")
    store = ArtifactStore(root)
    receipt = store.document("replay-receipt.json", sha256=receipt_sha)
    config = CausalConfig.model_validate(store.document(**{
        "path": receipt["instrument"]["path"], "sha256": receipt["instrument"]["sha256"]}))
    raw_bytes = store.referenced(ArtifactRef(**receipt["raw_capture"]))
    raw = json.loads(raw_bytes)
    original_digest = digest(raw)
    collected = datetime.fromisoformat(receipt["collected_at"])
    observation, envelope = passive_causal_observation(config, raw, collected_at=collected)
    frame = safety_frame(config, envelope, observation, sequence=1,
        accepted_guarantees=set(receipt["accepted_guarantees"]),
        accepted_instruments=set(receipt["accepted_instruments"]))
    assert digest(raw) == original_digest
    assert store.referenced(ArtifactRef(**receipt["raw_capture"])) == raw_bytes
    assert frame.observed_at_unix_seconds == observation.observed_at.timestamp()
