"""Analytic configured-model and raw measured fixtures; no live-evidence claims."""

import copy
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.modules.autonomy.experimental.simulation import (
    ConfiguredSimulator,
    evaluate_actions,
    evaluator_sha256,
    validate_admission,
)
from app.modules.autonomy.experimental.verification import (
    measured_metrics,
    paired_performance,
    verify_post_action,
)
from app.modules.simulation.evaluator import digest

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
IDENTITY = UUID("00000000-0000-0000-0000-000000000001")


def frame_fixture(*, capacities=(2, 20), age=1, action=1):
    def worker(packets, start, end):
        return {"packets": packets, "bytes": packets * 1200, "highest_sequence": packets - 1, "duration_seconds": end - start,
                "started_monotonic_seconds": start, "finished_monotonic_seconds": end}

    rows = []
    for node, dev, capacity in (("a", "a-eth0", capacities[0]), ("b", "b-eth0", capacities[0]),
                                ("a", "a-eth1", capacities[1]), ("c", "c-eth0", capacities[1])):
        classes = [{"kind": "htb", "handle": "5:1", "options": {
            "rate": capacity * 1e6 / 8, "ceil": capacity * 1e6 / 8}}]
        rows.append({"node": node, "interface": dev, "capacity_mbps": capacity, "raw": json.dumps(classes)})
    path = ["h1", "a", "b" if action == 0 else "c", "z", "h3"]
    bg = ["h2", "a", "b", "z", "h4"]
    paths = {f"{p[0]}->{p[-1]}": {"nodes": p, "kernel_routes": [{"raw": "independent fixture"}]}
             for p in (path, path[::-1], bg, bg[::-1])}
    raw = {"episode_id": str(IDENTITY), "seed": 42, "scenario": "path0", "mode": "matched",
        "terminated": False, "truncated": False, "step_index": 1,
        "observation": {"previous_action": action, "path_queue_packets": [999, 999], "goodput_mbps": 999},
        "evidence": {"measurement_complete": True, "error": None,
            "capacity_readback": rows, "capacity_readback_end": copy.deepcopy(rows),
            "udp_sent": [worker(2000, 9, 13), worker(400, 9, 13)],
            "udp_received": [worker(2000, 8, 14), worker(400, 8, 14)],
            "post_control_interval": {"start": 10, "end": 12},
            "control_start_monotonic_seconds": 9.5, "drain_begin": 13, "drain_end": 13.5,
            "drain_status": "verified_empty", "desired_window_seconds": 2, "measured_window_seconds": 2,
            "ping": {"sent": 20, "received": 20, "rtt_avg_ms": 12, "interval_seconds": 4},
            "route": {"path": path[1:-1]}, "route_end": {"path": path[1:-1], "readback": {"paths": paths}},
            "provenance": {"source_sha256": "a" * 64, "lab_image_id": "b" * 64},
            "environment_spec": {"version": 5, "drain_max_seconds": 3}, "spec_hash": "c" * 64}}
    return {"network_id": IDENTITY, "workspace_id": IDENTITY, "runtime_sha256": "d" * 64,
        "window_started_at": NOW - timedelta(seconds=age + 2), "observed_at": NOW - timedelta(seconds=age),
        "raw_sha256": digest(raw), "raw": raw}


def rehash(frame):
    frame["raw_sha256"] = digest(frame["raw"])
    return frame


def assumptions_fixture():
    return {"version": 1, "tick_ms": 100, "duration_ticks": 20, "max_observation_age_seconds": 30,
        "foreground_paths": [["ab", "bz"], ["ac", "cz"]], "background_path": ["ab", "bz"],
        "limits": {"max_loss_pct": 5., "max_latency_ms": 400., "min_throughput_mbps": 4.},
        "links": [{"link_id": name, "source": source, "target": target, "node": source,
            "interface": interface, "capacity_source": "htb_readback", "buffer_bytes": 100000.,
            "initial_queue_bytes": 0., "delay_ms": 0., "source_label": "operator_configured_model"}
            for name, source, target, interface in (
                ("ab", "a", "b", "a-eth0"), ("bz", "b", "z", "b-eth0"),
                ("ac", "a", "c", "a-eth1"), ("cz", "c", "z", "c-eth0"))]}


def actions_fixture():
    return [{"intent_id": IDENTITY, "action_id": f"route{i}", "action_index": i,
             "plan_sha256": str(i) * 64} for i in (0, 1)]


def evaluate(frame=None, assumptions=None):
    return evaluate_actions(frame=frame or frame_fixture(), assumptions=assumptions or assumptions_fixture(),
        actions=actions_fixture(), policy_sha256="e" * 64, now=NOW)


def test_analytic_thresholds_distinguish_both_congestion_directions_and_conserve():
    for capacities, passing in (((2, 20), 1), ((20, 2), 0)):
        results = evaluate(frame_fixture(capacities=capacities))
        assert [r["risk_gate"] for r in results] == (["blocked", "passed"] if passing else ["passed", "blocked"])
        assert results[passing]["result"]["flows"]["foreground"]["throughput_mbps"] == pytest.approx(4.8 * 19 / 20)
        for result in results:
            assert not result["physical_safety_authorized"]
            for metrics in result["result"]["flows"].values():
                assert metrics["offered_bytes"] == pytest.approx(sum(metrics[key] for key in (
                    "delivered_bytes", "dropped_bytes", "queued_bytes", "inflight_bytes")))
            assert all(link["initial_queue_bytes"] == 0 for link in result["scenario_config"]["links"])
    assert evaluate() == evaluate()


def test_model_missing_delivery_unknown_blocks_without_division_by_zero():
    frame = frame_fixture()
    for sender in frame["raw"]["evidence"]["udp_sent"]:
        sender.update(bytes=0, packets=0)
    for receiver in frame["raw"]["evidence"]["udp_received"]:
        receiver.update(bytes=0, packets=0, highest_sequence=-1)
    results = evaluate(rehash(frame))
    assert all(result["risk_gate"] == "blocked" for result in results)
    assert results[0]["result"]["latency_ms"] is None
    assert results[0]["result"]["loss_pct"] is None


def test_passing_aggregate_cannot_mask_foreground_threshold_failure():
    frame, assumptions = frame_fixture(capacities=(5, 20)), assumptions_fixture()
    for key in ("udp_sent", "udp_received"):
        frame["raw"]["evidence"][key][1] = copy.deepcopy(frame["raw"]["evidence"][key][0])
    assumptions["limits"].update(max_loss_pct=100., max_latency_ms=10000.)
    bad, good = evaluate(rehash(frame), assumptions)
    assert bad["result"]["risk_gate"] == "passed"
    assert not bad["foreground_checks"]["min_throughput_mbps"]
    assert bad["risk_gate"] == "blocked" and good["risk_gate"] == "passed"


@pytest.mark.parametrize("kind", ["stale", "future", "missing_capacity", "lying_capacity", "zero_duration", "zero_capacity"])
def test_invalid_model_inputs_block(kind):
    frame = frame_fixture(age=31 if kind == "stale" else -1 if kind == "future" else 1)
    evidence = frame["raw"]["evidence"]
    if kind == "missing_capacity":
        evidence.pop("capacity_readback")
    elif kind == "lying_capacity":
        evidence["capacity_readback"][0]["capacity_mbps"] = 100
    elif kind == "zero_duration":
        evidence["udp_sent"][0]["duration_seconds"] = 0
    elif kind == "zero_capacity":
        evidence["capacity_readback"][0]["raw"] = json.dumps([
            {"kind": "htb", "handle": "5:1", "options": {"rate": 0, "ceil": 0}}])
    with pytest.raises(ValueError):
        evaluate(rehash(frame))


def test_binding_replay_rejects_action_policy_assumptions_observation_and_result_tamper():
    admitted = evaluate()[1]
    kwargs = {"frame": frame_fixture(), "assumptions": assumptions_fixture(),
              "action": actions_fixture()[1], "policy_sha256": "e" * 64, "now": NOW}
    assert validate_admission(admitted, **kwargs) == admitted
    for field in ("action", "policy", "assumptions", "observation", "result"):
        args, row = copy.deepcopy(kwargs), copy.deepcopy(admitted)
        if field == "action":
            args["action"]["plan_sha256"] = "f" * 64
        elif field == "policy":
            args["policy_sha256"] = "f" * 64
        elif field == "assumptions":
            args["assumptions"]["links"][0]["initial_queue_bytes"] = 1.
        elif field == "observation":
            args["frame"]["raw"]["seed"] = 43
            rehash(args["frame"])
        else:
            row["result"]["throughput_mbps"] = 999
            row["admission_sha256"] = digest({k: v for k, v in row.items() if k != "admission_sha256"})
        with pytest.raises(ValueError):
            validate_admission(row, **args)


def verification_policy():
    return {"version": 1, "max_observation_age_seconds": 30, "min_goodput_mbps": 4.,
        "max_udp_loss_pct": 5., "max_probe_loss_pct": 5., "max_rtt_ms": 50.,
        "foreground_nodes": [["h1", "a", "b", "z", "h3"], ["h1", "a", "c", "z", "h3"]],
        "background_nodes": ["h2", "a", "b", "z", "h4"]}


def verify(after, **kwargs):
    return verify_post_action(before=frame_fixture(age=8), after=after, action=actions_fixture()[1],
        policy=verification_policy(), policy_sha256="e" * 64,
        action_completed_at=NOW - timedelta(seconds=5), now=NOW, **kwargs)


def test_measured_raw_not_summary_keep_restoration_and_outage():
    result = verify(frame_fixture())
    assert result["status"] == "keep"
    assert result["metrics"]["goodput_mbps"] == 4.8  # summary deliberately says 999
    assert not result["physical_safety_authorized"]
    assert verify(frame_fixture(), purpose="restoration")["status"] == "restoration"
    frame = frame_fixture()
    frame["raw"]["evidence"]["ping"].update(received=0, rtt_avg_ms=None)
    result = verify(rehash(frame))
    assert result["status"] == "fail" and result["restoration_required"]
    assert result["metrics"]["rtt_ms"] is None


@pytest.mark.parametrize("mutation,expected", [
    ("missing", "missing"), ("stale", "missing"), ("seed", "missing"), ("runtime", "missing"),
    ("scope", "missing"), ("window", "missing"), ("zero_probe", "missing"), ("route", "fail"),
    ("loss", "fail"), ("rtt", "fail"), ("no_rtt", "missing"), ("zero_duration", "missing")])
def test_verification_fail_closed(mutation, expected):
    frame = frame_fixture(age=31 if mutation == "stale" else 1)
    evidence = frame["raw"]["evidence"]
    if mutation == "missing":
        frame = None
    elif mutation == "seed":
        frame["raw"]["seed"] += 1
    elif mutation == "runtime":
        frame["runtime_sha256"] = "f" * 64
    elif mutation == "scope":
        frame["network_id"] = UUID(int=2)
    elif mutation == "window":
        frame["window_started_at"] = NOW - timedelta(seconds=6)
    elif mutation == "zero_probe":
        evidence["ping"].update(sent=0, received=0, rtt_avg_ms=None)
    elif mutation == "route":
        evidence["route_end"]["path"] = ["a", "b", "z"]
    elif mutation == "loss":
        evidence["udp_received"][0].update(packets=1000, bytes=1200000)
    elif mutation == "rtt":
        evidence["ping"]["rtt_avg_ms"] = 100
    elif mutation == "no_rtt":
        evidence["ping"].pop("rtt_avg_ms")
    elif mutation == "zero_duration":
        evidence["udp_sent"][0]["duration_seconds"] = 0
    result = verify(rehash(frame) if frame else None)
    assert result["status"] == expected
    assert result["restoration_required"] and not result["keep"]


def paired_trials():
    return [{"comparator": comparator, "frame": frame_fixture(action=0 if comparator == "fixed0" else 1),
        "workload_sha256": "a" * 64, "window_index": 1, "collected_at": NOW,
        "admission_policy_sha256": "c" * 64, "simulation_sha256": "d" * 64, "mutation_count": 1,
        "selected_action_index": 0 if comparator == "fixed0" else 1,
        "action_timing": {"clock_id": "controller-boot-1", "evidence_sha256": "b" * 64,
                          "started_seconds": 10., "finished_seconds": 10.25}}
        for comparator in ("experimental", "fixed0", "fixed1", "heuristic")]


def test_paired_comparison_exact_seeds_observed_times_and_unavailable_metrics():
    trials = paired_trials()
    report = paired_performance(trials)
    pair = report["pairs"][0]
    assert pair["metrics"]["experimental"]["action_seconds"] == .25
    assert pair["metrics"]["experimental"]["decision_seconds"] is None
    assert pair["deltas"]["fixed0"]["goodput_mbps"] == 0
    trials[-1]["frame"]["raw"]["evidence"]["ping"].update(received=0, rtt_avg_ms=None)
    rehash(trials[-1]["frame"])
    assert paired_performance(trials)["pairs"][0]["deltas"]["heuristic"]["rtt_ms"] is None
    with pytest.raises(ValueError, match="comparators_or_seeds"):
        paired_performance(trials[:-1])
    trials[-1]["frame"]["raw"]["seed"] += 1
    rehash(trials[-1]["frame"])
    with pytest.raises(ValueError, match="comparators_or_seeds"):
        paired_performance(trials)


def test_link_plan_capacity_no_defaults_and_background_initial_queue_conservation():
    frame, assumptions = frame_fixture(), assumptions_fixture()
    link = assumptions["links"][0]
    link.update(capacity_source="link_plan", initial_queue_bytes=1000.)
    for key in ("capacity_readback", "capacity_readback_end"):
        frame["raw"]["evidence"][key] = frame["raw"]["evidence"][key][1:]
    frame["raw"]["evidence"]["linkPlan"] = [{"a": ["a", 0], "b": ["b", 0], "capacity_mbps": 2}]
    result = evaluate(rehash(frame), assumptions)[0]
    bg = result["result"]["initial_background"]["ab"]
    assert bg["initial_bytes"] == 1000
    assert bg["initial_bytes"] == pytest.approx(bg["queued_bytes"] + bg["inflight_bytes"] + bg["delivered_bytes"])
    assert result["scenario_config"]["links"][0]["capacity_mbps"] == 2
    frame["raw"]["evidence"].pop("linkPlan")
    with pytest.raises(ValueError):
        evaluate(rehash(frame), assumptions)


def test_counter_mismatch_rejected():
    frame = frame_fixture()
    frame["raw"]["evidence"]["udp_received"][0]["bytes"] += 1
    with pytest.raises(ValueError, match="counter"):
        measured_metrics(rehash(frame))


def test_rejected_comparator_kept_in_pairs_without_mutation_or_metric_claim():
    trials = paired_trials()
    trials[1].update(outcome="predispatch_rejected", mutation_count=0, action_timing=None)
    for trial in trials:
        trial["frame"]["raw"]["evidence"]["phase"] = {
            "offered_mbps": 4.8, "phase_index": 0 if trial.get("outcome") == "predispatch_rejected" else 1}
        rehash(trial["frame"])
    pair = paired_performance(trials)["pairs"][0]
    assert pair["outcomes"]["fixed0"]["status"] == "predispatch_rejected"
    assert pair["outcomes"]["fixed0"]["mutation_count"] == 0
    assert pair["metrics"]["fixed0"] is None and pair["deltas"]["fixed0"] is None
    assert "no_postaction_metrics" in pair["unavailable"]["fixed0"]
    trials[1]["mutation_count"] = 1
    with pytest.raises(ValueError, match="zero_mutation"):
        paired_performance(trials)
    trials = paired_trials()
    trials[-1]["admission_policy_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="paired_scope_runtime_or_workload"):
        paired_performance(trials)


def test_frozen_bullseye_actual_text_htb_readback():
    frame = frame_fixture()
    for key in ("capacity_readback", "capacity_readback_end"):
        for row in frame["raw"]["evidence"][key]:
            capacity = row["capacity_mbps"]
            row["raw"] = f"class htb 5:1 root leaf 10: prio 0 rate {capacity}Mbit ceil {capacity}Mbit burst 1600b cburst 1600b"
    assert evaluate(rehash(frame))[1]["risk_gate"] == "passed"


async def test_core_simulator_protocol_actual_outputs_and_installed_pin():
    from app.modules.autonomy.experimental.comparators import ComparatorAdapter
    from app.modules.autonomy.experimental.schemas import (
        ActionCommand,
        ExperimentalPolicy,
        InferenceRecord,
        MeasuredFrame,
        PreparedAction,
    )
    from app.modules.autonomy.experimental.verification import verification_record
    from app.modules.autonomy.schemas import contract_digest

    from tests.experimental_lab_support import case

    fixture = case()
    assumptions = assumptions_fixture()
    objectives = assumptions.pop("limits")
    assumptions.pop("max_observation_age_seconds")
    assumptions["verification_paths"] = {key: verification_policy()[key]
        for key in ("foreground_nodes", "background_nodes")}
    policy = ExperimentalPolicy.model_validate({**fixture.policy.model_dump(),
        "assumptions": assumptions, "objectives": objectives, "evaluator_sha256": evaluator_sha256(),
        "routes": [{"action_id": f"route{i}", "device_ids": ["a"], "path": ["a", node, "z"]}
                   for i, node in enumerate(("b", "c"))]})
    raw = frame_fixture()["raw"]
    raw["episode_id"] = str(fixture.frame.snapshot.run_id)
    raw["observation"] = fixture.frame.features.model_dump(mode="json")
    history = {"frames": [{"response": {"ok": True, "data": raw}}]}
    snapshot = {**fixture.frame.snapshot.model_dump(), "history": history,
        "history_sha256": digest(history), "observed_at": NOW - timedelta(seconds=1),
        "window_started_at": NOW - timedelta(seconds=3), "published_at": NOW}
    observation = {**fixture.frame.observation.model_dump(), "observed_at": snapshot["observed_at"]}
    frame = MeasuredFrame.model_validate({**fixture.frame.model_dump(), "snapshot": snapshot, "observation": observation})
    inference = InferenceRecord.model_validate({**fixture.inference.model_dump(),
        "frame_sha256": contract_digest(frame),
        "proposal": {**fixture.inference.proposal.model_dump(), "action_id": "route1"},
        "result": {**fixture.inference.result.model_dump(), "action": 1, "action_path": ["a", "c", "z"],
                   "snapshot_sha256": contract_digest(frame.snapshot), "history_sha256": frame.snapshot.history_sha256,
                   "input_sha256": contract_digest(frame.features),
                   "probabilities": [.1, .9]}})
    simulator = ConfiguredSimulator(clock=lambda: NOW)
    result = await simulator.simulate(frame, inference, policy)
    assert result.admitted
    assert result.result["per_action"][0]["risk_gate"] == "blocked"
    assert result.result["selected"]["result"]["flows"]["foreground"]["throughput_mbps"] == pytest.approx(4.56)
    for kind in ("fixed0", "fixed1", "heuristic"):
        lane_policy = policy.model_copy(update={"policy_kind": kind})
        baseline = await ComparatorAdapter(lane_policy).infer(frame)
        assert baseline.qualification is None and baseline.result.probabilities is None
        lane = await simulator.simulate(frame, baseline, lane_policy)
        assert lane.admitted is (baseline.result.action == 1)
        assert lane.result["admission_policy_sha256"] == result.result["admission_policy_sha256"]
        for index in (0, 1):
            assert lane.result["per_action"][index]["result"]["flows"] == result.result["per_action"][index]["result"]["flows"]
    with pytest.raises(ValueError, match="installed_simulator_binding"):
        await simulator.simulate(frame, inference, policy.model_copy(update={"evaluator_sha256": "f" * 64}))

    pre_snapshot = {**frame.snapshot.model_dump(), "observed_at": NOW - timedelta(seconds=8),
                    "window_started_at": NOW - timedelta(seconds=10)}
    before = MeasuredFrame.model_validate({**frame.model_dump(), "snapshot": pre_snapshot,
        "observation": {**frame.observation.model_dump(), "observed_at": pre_snapshot["observed_at"]}})
    command = ActionCommand(request_id=IDENTITY, run_id=policy.run_id, resource_id=policy.runtime.resource_id,
        fence=1, network_id=policy.network_id, workspace_id=policy.workspace_id, runtime=policy.runtime,
        route=policy.routes[1], policy_sha256=contract_digest(policy), frame_sha256=contract_digest(before),
        inference_sha256=contract_digest(inference), simulation_sha256=contract_digest(result),
        created_at=NOW - timedelta(seconds=6), expires_at=NOW + timedelta(seconds=20))
    prepared = PreparedAction(command=command, baseline={"original": 0},
        baseline_sha256=digest({"original": 0}), ownership_sha256="a" * 64)
    kwargs = {"before": before, "prepared": prepared, "policy": policy,
              "action_completed_at": NOW - timedelta(seconds=5), "now": NOW}
    record = verification_record(after=frame, **kwargs)
    assert record.route_verified and record.goodput_mbps == 4.8
    assert record.provenance["verification"]["status"] == "keep"
    assert record.loss_fraction == 0 and record.probe_sent == 20
    assert verification_record(after=None, **kwargs).route_verified is False
    with pytest.raises(ValueError, match="preaction_frame_binding"):
        verification_record(after=frame, **{**kwargs, "before": frame})
