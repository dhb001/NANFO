"""Unprivileged arithmetic/adversarial tests; fixtures are NOT native evidence."""

import copy
import json
from fractions import Fraction

import pytest

from app.modules.autonomy.safety import (
    CandidateBounds, DemandObservation, DemandRoute, QueueBounds, QueueObservation,
    SafetyAction, SafetyObservation, SafetyPolicy, SafetyShield, SafetyState,
    TrustedCalibration, safety_input_digest,
)
from emulation.native_qualification import (
    CATEGORIES, capture_endpoint, digest, queue_commands, regulator_transactions, validate_rules,
)
from emulation.native_qualification_routes import assert_design_mapping, execution_map, mutation_manifest
from scripts.native_qualification import NativeDesign, PacketBucket, analyze, preregistered_schedule
from scripts.native_qualification_capture import replay_window


def design():
    return NativeDesign(version="nanfo.native-design/v1", environment="isolated-emulation",
        host_addresses={"h1": "10.0.0.1", "h2": "10.0.0.2", "h3": "10.0.0.3", "h4": "10.0.0.4"},
        egresses=[dict(egress_id="edge", node="access1", peer="dist1", interface="access1-eth1",
            queue_limit_bytes=1048576, shaper_bytes_per_second=125000, shaper_burst_bytes=4096,
            epoch_quota_bytes=65536, buckets={c: dict(packets_per_second=10, burst_packets=2, max_skb_bytes=1600)
                                             for c in CATEGORIES})],
        horizon_seconds=1., minimum_window_seconds=1., sensor_span_seconds=.01,
        clock_error_seconds=.001, prequeue_delay_upper_seconds=None,
        sensor_error_bytes=1024., accounting_error_bytes=1024.)


def policy():
    # New scoped test policy; no installed policy/test criteria are changed.
    return SafetyPolicy(network_id="lab", policy_version="scoped-test-v1", queue_threshold_bytes=262144.,
        max_dt_seconds=1., max_observation_age_seconds=.2, max_delay_seconds=.5, min_dwell_seconds=0.,
        rate_window_seconds=1., max_actions_per_window=10, drift_budget_bytes_squared=float(2**33),
        allowed_paths=[dict(route_id="path", source="access1", destination="dist1", egress_ids=["edge"])])


def test_finite_epoch_positive_traffic_and_fixed_budget_accept_and_reject():
    d, p = design(), policy()
    accepted = analyze(d, p, {"edge": 0})
    assert accepted["arithmetic_passed"]
    assert accepted["queues"][0]["arrival_upper_bytes_per_second"] == 65536
    assert accepted["queues"][0]["strictly_tighter_than_queue_cap"]
    assert not accepted["activation_ready"]
    assert "fixed_drift_budget_failed" in analyze(d, p, {"edge": 131072})["blockers"]
    assert "queue_threshold_failed:edge" in analyze(d, p, {"edge": 250000})["blockers"]
    assert p.drift_budget_bytes_squared == 2**33


def test_zero_budget_remains_infeasible_not_loosened():
    p = policy().model_copy(update={"drift_budget_bytes_squared": 0.})
    assert "fixed_drift_budget_failed" in analyze(design(), p, {"edge": 0})["blockers"]


def test_actual_frozen_shield_agrees_with_native_bound_arithmetic():
    d, p = design(), policy()
    for q0, decision in ((0., "accept"), (131072., "no_dispatch")):
        r = analyze(d, p, {"edge": q0})["queues"][0]
        calibration = TrustedCalibration(calibration_id="test-only", provider_id="test", model_version="bounded-fluid-v1",
            network_id="lab", run_id="run", valid_from_unix_seconds=0., valid_until_unix_seconds=100.,
            egress_ids=["edge"], demand_ids=["demand"], min_error_upper_bytes=r["error_upper_bytes"],
            min_service_uncertainty_bytes_per_second=0.)
        obs = SafetyObservation(network_id="lab", run_id="run", snapshot_id="sample", sequence=1,
            observed_at_unix_seconds=10., counter_reset=False, attribution_complete=True, unknown_demand_ids=[],
            queues=[QueueObservation(egress_id="edge", source="access1", destination="dist1", queue_bytes=q0,
                                     capacity_bytes_per_second=2000000.)],
            demands=[DemandObservation(demand_id="demand", source="access1", destination="dist1",
                arrival_lower_bytes_per_second=0., arrival_upper_bytes_per_second=r["arrival_upper_bytes_per_second"])])
        routes = [DemandRoute(demand_id="demand", route_id="path")]
        bounds = CandidateBounds(network_id="lab", run_id="run", snapshot_id="sample", action_id="hold",
            calibration_id="test-only", provider_id="test", model_version="bounded-fluid-v1", policy_version=p.policy_version,
            input_sha256=safety_input_digest(obs, routes), observed_at_unix_seconds=10., valid_until_unix_seconds=100.,
            dt_seconds=1., actuation_delay_upper_seconds=.1,
            queues=[QueueBounds(egress_id="edge", arrival_lower_bytes_per_second=0.,
                arrival_upper_bytes_per_second=r["arrival_upper_bytes_per_second"], service_lower_bytes_per_second=0.,
                service_upper_bytes_per_second=2000000., error_upper_bytes=r["error_upper_bytes"])])
        state = SafetyState(network_id="lab", run_id="run", snapshot_id="sample", observed_at_unix_seconds=10.,
            last_evaluated_sequence=0, active_routes=routes, route_since_unix_seconds=0.,
            history_complete_since_unix_seconds=0., last_applied_at_unix_seconds=None, recent_dispatch_at_unix_seconds=[])
        action = SafetyAction(action_id="hold", network_id="lab", run_id="run", snapshot_id="sample", routes=routes, bounds=bounds)
        result = SafetyShield(p, calibration).evaluate(obs, action, state=state, now=10.)
        assert result["decision"] == decision
        if decision == "accept":
            assert result["certificate"]["envelope"]["q_next_upper_bytes"]["edge"] == r["q_next_upper_bytes"]


def test_packet_rate_rounding_and_unproved_prequeue_delay():
    b = PacketBucket(packets_per_second=3, burst_packets=2, max_skb_bytes=1600)
    sigma, rho = b.envelope()
    assert sigma == 3200 and rho > 4800
    assert rho == Fraction(1600 * 10**9, 333333333)
    d = design()
    d.egresses[0].epoch_quota_bytes = None
    assert analyze(d, policy(), {"edge": 0})["blockers"] == ["prequeue_delay_not_proved"]
    d.prequeue_delay_upper_seconds = .01
    assert analyze(d, policy(), {"edge": 0})["queues"][0]["service_lower_bytes_per_second"] == 0


def test_queue_cap_cannot_be_used_to_clamp_shield_or_claim_nonvacuity():
    d = design()
    d.egresses[0].queue_limit_bytes = 65536
    r = analyze(d, policy(), {"edge": 0})
    assert r["queues"][0]["q_next_upper_bytes"] > 65536
    assert "cap_only_tautology" in r["blockers"]


def test_counter_rules_cover_control_and_drop_unknown_without_exemptions():
    spec = design().model_dump(mode="json")
    transaction = regulator_transactions(spec)["access1"]
    assert transaction["nftables"][0].get("create", {}).get("table")
    rows = [next(iter(x.values())) for x in transaction["nftables"]]
    limits = [expr["limit"] for r in rows for expr in r.get("rule", {}).get("expr", []) if "limit" in expr]
    assert len(limits) == 6 and all(limit["inv"] for limit in limits)
    assert rows[-1]["rule"]["expr"] == [{"counter": "edge_unknown"}, {"drop": None}]
    assert any("quota" in r for r in rows)
    assert queue_commands(spec)[0]["commands"][0][2] == "add"


def raw_rules(spec):
    rows = [copy.deepcopy(next(iter(r.values()))) for r in regulator_transactions(spec)["access1"]["nftables"]]
    for row in rows:
        if "counter" in row:
            row["counter"].update(bytes=0, packets=0)
        if "quota" in row:
            row["quota"]["used"] = 0
    return {"nftables": rows}


@pytest.mark.parametrize("mutation", ["quota", "limit", "policy", "extra", "negative"])
def test_regulator_tampering_fails_closed(mutation):
    spec = design().model_dump(mode="json")
    raw = raw_rules(spec)
    if mutation == "quota":
        next(r["quota"] for r in raw["nftables"] if "quota" in r)["bytes"] += 1
    elif mutation == "limit":
        next(x["limit"] for r in raw["nftables"] for x in r.get("rule", {}).get("expr", []) if "limit" in x)["rate"] += 1
    elif mutation == "policy":
        next(r["chain"] for r in raw["nftables"] if "chain" in r)["policy"] = "accept"
    elif mutation == "extra":
        raw["nftables"].append({"flowtable": {}})
    else:
        next(r["counter"] for r in raw["nftables"] if "counter" in r)["bytes"] = -1
    with pytest.raises(ValueError):
        validate_rules(raw, regulator_transactions(spec)["access1"])


class Clock:
    def __init__(self, offset=0):
        self.now = 10**12 + offset

    def time_ns(self):
        self.now += 100
        return self.now

    monotonic_ns = time_ns


class Instrument:
    def __init__(self, spec, broken=False):
        self.spec, self.broken = spec, broken

    def command(self, node, args):
        assert args[0] in {"ip", "nft", "tc"} and not set(args) & {"add", "replace", "del"}
        if self.broken:
            raise ValueError("failed")
        if args[0] == "nft":
            return json.dumps(raw_rules(self.spec))
        if "qdisc" in args:
            return json.dumps([dict(kind="tbf", handle="1:", root=True, options=dict(rate=125000)),
                               dict(kind="bfifo", handle="10:", parent="1:1", options=dict(limit=1048576),
                                    backlog=0, bytes=0, drops=0)])
        return "[]"


def endpoints():
    d = design()
    spec = d.model_dump(mode="json")
    return d, [capture_endpoint(Instrument(spec), spec, clock=Clock(offset)) for offset in (0, 10**9)]


def test_read_only_capture_and_replay_do_not_claim_qualification():
    d, (before, after) = endpoints()
    assert before["design_sha256"] == digest(d.model_dump(mode="json"))
    result = replay_window(before, after, d)
    assert result["raw_replay_passed"] and not result["activation_ready"]
    broken = capture_endpoint(Instrument(d.model_dump(mode="json"), broken=True), d.model_dump(mode="json"), clock=Clock())
    assert not broken["measurement_complete"] and broken["reads"] and broken["failures"]


@pytest.mark.parametrize("mutation", ["span", "clock", "raw", "missing", "bypass", "drop", "quota"])
def test_raw_replay_rejects_timing_and_native_mutation(mutation):
    d, (before, after) = endpoints()
    row = after["reads"][0]
    if mutation == "span":
        row["end_monotonic_ns"] += 100000000
        row["end_wall_ns"] += 100000000
    elif mutation == "clock":
        row["end_wall_ns"] += 100000000
    elif mutation == "raw":
        row["parsed"] = {}
    elif mutation == "missing":
        after["reads"].pop()
    elif mutation == "bypass":
        row = next(r for r in after["reads"] if r["kind"].startswith("filters_egress"))
        row["parsed"] = [{"kind": "bpf"}]
        row["raw"] = json.dumps(row["parsed"])
    elif mutation == "drop":
        row = next(r for r in after["reads"] if r["kind"].startswith("qdisc"))
        row["parsed"][1]["drops"] = 1
        row["raw"] = json.dumps(row["parsed"])
    else:
        next(r["quota"] for r in row["parsed"]["nftables"] if "quota" in r)["inv"] = False
        row["raw"] = json.dumps(row["parsed"])
    with pytest.raises(ValueError):
        replay_window(before, after, d)


def test_full_native_routes_include_reverse_hosts_link_local_and_old_new_union():
    mapping = execution_map({"h2_h4": ["h2", "access1", "dist1", "access2", "h4"],
                             "h4_h2": ["h4", "access2", "dist1", "access1", "h2"]})
    assert mapping["actions"]["0"]["h1_h3"][0] == "h1_access1"
    assert mapping["actions"]["1"]["h3_h1"][0] == "h3_access2"
    assert "access1_dist1" in mapping["transition_egresses"]["0->1"]["h1_h3"]
    assert "access1_dist2" in mapping["transition_egresses"]["0->1"]["h1_h3"]
    assert all(mapping["actions"]["0"][key + "_arp"] == [key] for key in mapping["egresses"])
    with pytest.raises(ValueError, match="exact_frr_graph"):
        assert_design_mapping(design().model_dump(mode="json"), mapping)


def test_preregistered_sessions_cover_every_directed_transition_in_both_splits():
    groups = preregistered_schedule("native-v1", [91001, 91002, 91003, 92001, 92002, 92003])
    assert len(groups) == 6
    for group in groups:
        assert len(group["samples"]) == 8
        assert {(s["previous_action"], s["action"]) for s in group["samples"]} == {(0, 0), (0, 1), (1, 0), (1, 1)}
    with pytest.raises(ValueError):
        preregistered_schedule("native-v1", [1] * 6)


def test_native_transition_manifest_matches_reserved_tables_and_order_without_dispatch():
    manifest = mutation_manifest(1)
    assert not manifest["authorization"]
    assert len(manifest["apply"]) == 12
    assert len(manifest["partial_state_prefixes"]) == 13
    assert {row["table"] for row in manifest["resources"]} == {19110, 19111}
    assert manifest["apply"][0]["argv"][:3] == ["ip", "route", "add"]
    assert manifest["apply"][1]["argv"][:3] == ["ip", "rule", "add"]
    assert manifest["recover"][0]["argv"][:3] == ["ip", "rule", "del"]
    assert manifest["partial_state_prefixes"][0] == []
    assert manifest["partial_state_prefixes"][-1] == manifest["apply"]


def test_epoch_exhaustion_and_between_endpoint_clock_jump_rejected():
    d, (before, after) = endpoints()
    row = after["reads"][0]
    next(r["counter"] for r in row["parsed"]["nftables"]
         if r.get("counter", {}).get("name") == "edge_quota_drop").update(packets=1, bytes=100)
    row["raw"] = json.dumps(row["parsed"])
    with pytest.raises(ValueError, match="quota_exhausted"):
        replay_window(before, after, d)
    d, (before, after) = endpoints()
    for row in after["reads"]:
        row["start_wall_ns"] += 10**9
        row["end_wall_ns"] += 10**9
    with pytest.raises(ValueError, match="window_clock"):
        replay_window(before, after, d)


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf")])
def test_invalid_observed_queue_rejected(value):
    with pytest.raises(ValueError):
        analyze(design(), policy(), {"edge": value})
