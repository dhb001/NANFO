"""Pinned durable frozen-v4 replay, not a fresh observation or lab campaign.

Only the test envelope/clock/installed model assumptions are constructed. Original
request/response bytes and counter evidence are read unchanged from preservation.
"""

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from app.modules.autonomy.experimental.comparators import ComparatorAdapter
from app.modules.autonomy.experimental.schemas import (
    ActionCommand,
    ExperimentalPolicy,
    MeasuredFrame,
    PreparedAction,
    contract_digest,
)
from app.modules.autonomy.experimental.simulation import (
    ConfiguredSimulator,
    admission_policy_sha256,
    evaluator_sha256,
    from_core_frame,
)
from app.modules.autonomy.experimental.verification import (
    measured_metrics,
    verification_record,
)
from app.modules.simulation.evaluator import digest

from tests.experimental_lab_support import case

ROOT = Path(__file__).resolve().parents[3] / "ai-engine/artifacts/adr024-qualified-001/model"
PINS = {
    "path0": "21529463ae34c83d6f44518b25712d6d935fdece8614628886ae59c0090d19c9",
    "path1": "253a53d91feff7ca5b31cca54b05c20123bb86e56033509bbae0ab69a0e91a32",
}


def durable_case(scenario):
    path = ROOT / f"recorded-history-{scenario}.json"
    if not path.exists():
        pytest.skip("durable ADR024 raw artifacts not installed; synthetic tests remain mandatory")
    content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == PINS[scenario]
    history = json.loads(content)
    raw = history["frames"][0]["response"]["data"]
    evidence = raw["evidence"]
    # Explicitly synthetic clock anchor for OFFLINE replay. Never publish it or
    # assert these historical raw frames are currently fresh measured evidence.
    epoch = datetime(2000, 1, 1, tzinfo=UTC)
    start, end = (epoch + timedelta(seconds=evidence["post_control_interval"][key]) for key in ("start", "end"))
    now = end + timedelta(seconds=5)
    fixture = case()
    verification_paths = {"foreground_nodes": [
        ["h1", "access1", middle, "access2", "h3"] for middle in ("dist1", "dist2")],
        "background_nodes": ["h2", "access1", "dist1", "access2", "h4"]}
    assumptions = {"version": 1, "tick_ms": 20, "duration_ticks": 100,
        "foreground_paths": [["a-d1", "d1-z"], ["a-d2", "d2-z"]],
        "background_path": ["a-d1", "d1-z"], "verification_paths": verification_paths,
        "links": [{"link_id": link_id, "source": source, "target": target, "node": source,
            "interface": interface, "capacity_source": "htb_readback", "buffer_bytes": 25000.,
            "initial_queue_bytes": 0., "delay_ms": 5., "source_label": "operator_configured_model"}
            for link_id, source, target, interface in (
                ("a-d1", "access1", "dist1", "access1-eth1"), ("d1-z", "dist1", "access2", "dist1-eth4"),
                ("a-d2", "access1", "dist2", "access1-eth2"), ("d2-z", "dist2", "access2", "dist2-eth4"))]}
    policy = ExperimentalPolicy.model_validate({**fixture.policy.model_dump(),
        "run_id": raw["episode_id"], "policy_kind": "heuristic", "assumptions": assumptions,
        "objectives": {"max_loss_pct": 5., "max_latency_ms": 400., "min_throughput_mbps": 4.},
        "evaluator_sha256": evaluator_sha256(), "starts_at": start - timedelta(seconds=30),
        "expires_at": now + timedelta(seconds=30),
        "routes": [{"action_id": f"route{i}", "device_ids": ["access1", middle, "access2"],
                    "path": ["access1", middle, "access2"]} for i, middle in enumerate(("dist1", "dist2"))]})
    snapshot = {**fixture.frame.snapshot.model_dump(), "run_id": UUID(raw["episode_id"]),
        "window_started_at": start, "observed_at": end, "published_at": now,
        "history": history, "history_sha256": digest(history), "spec_sha256": evidence["spec_hash"]}
    observation = {**fixture.frame.observation.model_dump(), "observed_at": end, "collected_at": now}
    frame = MeasuredFrame.model_validate({**fixture.frame.model_dump(), "snapshot": snapshot,
        "observation": observation, "features": raw["observation"],
        "provenance": {"source": "offline-historical-replay", "artifact_sha256": PINS[scenario],
                       "clock": "synthetic-test-anchor-not-live-attachment"}})
    return frame, policy, now, content


@pytest.mark.parametrize("scenario,good", [("path0", 1), ("path1", 0)])
async def test_durable_frame_counts_model_units_and_honest_comparator_admission(scenario, good):
    frame, policy, now, original = durable_case(scenario)
    frozen = from_core_frame(frame)
    evidence = frozen.raw["evidence"]
    measured = measured_metrics(frozen)
    sender, receiver = evidence["udp_sent"][0], evidence["udp_received"][0]
    # Independent arithmetic from raw counts, not observation summaries.
    assert measured["goodput_mbps"] == pytest.approx(receiver["bytes"] * 8 / sender["duration_seconds"] / 1e6)
    assert measured["udp_loss_pct"] == pytest.approx(100 * (sender["packets"] - receiver["packets"]) / sender["packets"])
    probe = evidence["ping"]
    assert measured["probe_loss_pct"] == pytest.approx(100 * (probe["sent"] - probe["received"]) / probe["sent"])
    assert measured["rtt_ms"] == probe["rtt_avg_ms"]
    lanes = {}
    for kind in ("fixed0", "fixed1", "heuristic"):
        lane_policy = policy.model_copy(update={"policy_kind": kind})
        inference = await ComparatorAdapter(lane_policy).infer(frame)
        assert inference.qualification is None and inference.proposal.checkpoint_sha256 is None
        assert inference.result.probabilities is None and inference.result.value is None
        record = await ConfiguredSimulator(clock=lambda: now).simulate(frame, inference, lane_policy)
        selected = inference.result.action
        assert record.admitted is (selected == good)
        assert record.result["policy_kind"] == kind
        lanes[kind] = record
        for i, admission in enumerate(record.result["per_action"]):
            config, result = admission["scenario_config"], admission["result"]
            assert config["limits"] == policy.objectives
            assert admission["risk_gate"] == ("passed" if i == good else "blocked")
            # Common limits apply independently to foreground and aggregate;
            # a passing aggregate alone must never mask a failing foreground.
            assert admission["foreground_checks"]["min_throughput_mbps"] is (i == good)
            assert result["objective_checks"]["min_throughput_mbps"] is (i == good)
            horizon = config["tick_ms"] * config["duration_ticks"] / 1000
            for flow in config["flows"]:
                index = 0 if flow["flow_id"] == "foreground" else 1
                raw_sender = evidence["udp_sent"][index]
                rate = raw_sender["bytes"] * 8 / raw_sender["duration_seconds"] / 1e6
                metrics = result["flows"][flow["flow_id"]]
                assert flow["demand_mbps"] == [rate]
                assert metrics["offered_bytes"] == pytest.approx(rate * 1e6 / 8 * horizon)
                assert metrics["offered_bytes"] == pytest.approx(sum(metrics[key] for key in (
                    "delivered_bytes", "dropped_bytes", "queued_bytes", "inflight_bytes")))
                assert metrics["throughput_mbps"] == pytest.approx(metrics["delivered_bytes"] * 8 / horizon / 1e6)
                assert metrics["loss_pct"] == pytest.approx(metrics["dropped_bytes"] / metrics["offered_bytes"] * 100)
            foreground = result["flows"]["foreground"]
            assert foreground["latency_ms"] == pytest.approx(
                foreground["delivered_residence_byte_ms"] / foreground["delivered_bytes"])
            assert "not measured RTT" in result["latency_definition"]
            assert not result["physical_safety_authorized"]
    assert len({record.result["admission_policy_sha256"] for record in lanes.values()}) == 1
    assert admission_policy_sha256(policy) == admission_policy_sha256(policy.model_copy(update={"policy_kind": "model"}))
    # Baseline identity changes bindings, never the numeric scenario or thresholds.
    for i in (0, 1):
        outputs = [record.result["per_action"][i]["result"]["flows"] for record in lanes.values()]
        assert outputs[0] == outputs[1] == outputs[2]
    assert not lanes[f"fixed{1-good}"].admitted
    assert lanes[f"fixed{1-good}"].result["predispatch_status"] == "rejected"
    # There is no transport in this test: rejection cannot become measured effect.
    assert (ROOT / f"recorded-history-{scenario}.json").read_bytes() == original
    with pytest.raises(ValueError, match="stale"):
        await ConfiguredSimulator(clock=lambda: datetime.now(UTC)).simulate(
            frame, await ComparatorAdapter(policy).infer(frame), policy)


async def test_core_record_udp_loss_is_not_probe_loss_and_probe_gate_is_independent():
    frame, policy, now, _ = durable_case("path0")
    # This tests the bridge with a historical pair-shaped fixture, not a new action.
    before_snapshot = {**frame.snapshot.model_dump(),
        "observed_at": frame.snapshot.window_started_at - timedelta(seconds=3),
        "window_started_at": frame.snapshot.window_started_at - timedelta(seconds=5)}
    before = MeasuredFrame.model_validate({**frame.model_dump(), "snapshot": before_snapshot,
        "observation": {**frame.observation.model_dump(), "observed_at": before_snapshot["observed_at"]}})
    thresholds = {**policy.verification.model_dump(), "min_goodput_mbps": 0.,
        "max_loss_fraction": 1., "max_probe_loss_fraction": 1., "max_rtt_ms": 1000.}
    policy = ExperimentalPolicy.model_validate({**policy.model_dump(), "verification": thresholds})

    def verify(active_policy):
        command = ActionCommand(request_id=UUID(int=3), run_id=active_policy.run_id,
            resource_id=active_policy.runtime.resource_id, fence=1, network_id=active_policy.network_id,
            workspace_id=active_policy.workspace_id, runtime=active_policy.runtime, route=active_policy.routes[0],
            policy_sha256=contract_digest(active_policy), frame_sha256=contract_digest(before),
            inference_sha256="a" * 64, simulation_sha256="b" * 64,
            created_at=before.snapshot.observed_at, expires_at=now + timedelta(seconds=20))
        prepared = PreparedAction(command=command, baseline={"synthetic": True},
            baseline_sha256=digest({"synthetic": True}), ownership_sha256="c" * 64)
        return verification_record(before=before, after=frame, prepared=prepared, policy=active_policy,
            action_completed_at=frame.snapshot.window_started_at - timedelta(seconds=1), now=now)

    record = verify(policy)
    assert record.route_verified
    evidence = frame.snapshot.history["frames"][0]["response"]["data"]["evidence"]
    udp_loss = 1 - evidence["udp_received"][0]["packets"] / evidence["udp_sent"][0]["packets"]
    probe_loss = 1 - evidence["ping"]["received"] / evidence["ping"]["sent"]
    assert udp_loss != probe_loss
    assert record.loss_fraction == pytest.approx(udp_loss)
    assert record.provenance["verification"]["metrics"]["probe_loss_pct"] / 100 == pytest.approx(probe_loss)
    strict = ExperimentalPolicy.model_validate({**policy.model_dump(),
        "verification": {**thresholds, "max_probe_loss_fraction": 0.}})
    rejected = verify(strict)
    assert not rejected.route_verified and rejected.loss_fraction == record.loss_fraction
    assert rejected.provenance["verification"]["reasons"] == ["probe_loss"]
    assert admission_policy_sha256(policy) != admission_policy_sha256(strict)


async def test_comparator_wrong_kind_and_forged_qualification_rejected():
    frame, policy, now, _ = durable_case("path1")
    inference = await ComparatorAdapter(policy).infer(frame)
    with pytest.raises(ValueError, match="model_binding"):
        await ConfiguredSimulator(clock=lambda: now).simulate(frame, inference, policy.model_copy(update={"policy_kind": "fixed1"}))
    value = copy.deepcopy(inference.model_dump())
    value["qualification"] = {"qualified": True, "checkpoint_sha256": "a" * 64}
    with pytest.raises(ValueError):
        await ConfiguredSimulator(clock=lambda: now).simulate(frame, value, policy)
