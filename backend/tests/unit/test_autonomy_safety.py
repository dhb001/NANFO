"""Synthetic arithmetic/contract tests, NOT physical bound calibration evidence."""

import copy
import json
import math
from fractions import Fraction

import pytest
from pydantic import ValidationError

from app.modules.autonomy.safety import (
    CandidateBounds,
    DemandObservation,
    QueueBounds,
    QueueObservation,
    SafetyAction,
    SafetyObservation,
    SafetyPolicy,
    SafetyShield,
    SafetyState,
    TrustedCalibration,
    safety_input_digest,
)


@pytest.fixture
def inputs():
    policy = {
        "network_id": "network-1",
        "policy_version": "test-policy-v1",
        "queue_threshold_bytes": 100.0,
        "max_dt_seconds": 2.0,
        "max_observation_age_seconds": 3.0,
        "max_delay_seconds": 2.0,
        "min_dwell_seconds": 5.0,
        "rate_window_seconds": 10.0,
        "max_actions_per_window": 2,
        "hysteresis_bytes_squared": 0.0,
        "allowed_paths": [
            {
                "route_id": "route-A",
                "source": "s",
                "destination": "t",
                "egress_ids": ["a"],
            },
            {
                "route_id": "route-B",
                "source": "s",
                "destination": "t",
                "egress_ids": ["b"],
            },
        ],
    }
    calibration = {
        "calibration_id": "test-only-not-installed",
        "provider_id": "test-provider",
        "model_version": "bounded-fluid-v1",
        "network_id": "network-1",
        "run_id": "run-1",
        "valid_from_unix_seconds": 0.0,
        "valid_until_unix_seconds": 200.0,
        "egress_ids": ["a", "b"],
        "demand_ids": ["demand-1"],
        "min_error_upper_bytes": 1.0,
        "min_service_uncertainty_bytes_per_second": 1.0,
    }
    observation = {
        "network_id": "network-1",
        "run_id": "run-1",
        "snapshot_id": "snapshot-2",
        "sequence": 2,
        "observed_at_unix_seconds": 100.0,
        "counter_reset": False,
        "attribution_complete": True,
        "unknown_demand_ids": [],
        "queues": [
            {
                "egress_id": key,
                "source": "s",
                "destination": "t",
                "queue_bytes": 50.0,
                "capacity_bytes_per_second": 100.0,
            }
            for key in ("a", "b")
        ],
        "demands": [
            {
                "demand_id": "demand-1",
                "source": "s",
                "destination": "t",
                "arrival_lower_bytes_per_second": 5.0,
                "arrival_upper_bytes_per_second": 10.0,
            }
        ],
    }
    state = {
        "network_id": "network-1",
        "run_id": "run-1",
        "snapshot_id": "snapshot-2",
        "observed_at_unix_seconds": 100.0,
        "last_evaluated_sequence": 1,
        "active_routes": [{"demand_id": "demand-1", "route_id": "route-A"}],
        "route_since_unix_seconds": 80.0,
        "history_complete_since_unix_seconds": 80.0,
        "last_applied_at_unix_seconds": 80.0,
        "recent_dispatch_at_unix_seconds": [80.0],
    }
    action = {
        "action_id": "proposed",
        "network_id": "network-1",
        "run_id": "run-1",
        "snapshot_id": "snapshot-2",
        "routes": [{"demand_id": "demand-1", "route_id": "route-B"}],
        "bounds": {
            "action_id": "proposed",
            "network_id": "network-1",
            "run_id": "run-1",
            "snapshot_id": "snapshot-2",
            "calibration_id": calibration["calibration_id"],
            "provider_id": "test-provider",
            "model_version": "bounded-fluid-v1",
            "policy_version": policy["policy_version"],
            "input_sha256": safety_input_digest(
                observation, [{"demand_id": "demand-1", "route_id": "route-B"}]
            ),
            "observed_at_unix_seconds": 100.0,
            "valid_until_unix_seconds": 110.0,
            "dt_seconds": 1.0,
            "actuation_delay_upper_seconds": 0.1,
            "queues": [
                {
                    "egress_id": key,
                    "arrival_lower_bytes_per_second": 5.0,
                    "arrival_upper_bytes_per_second": 10.0,
                    "service_lower_bytes_per_second": 20.0,
                    "service_upper_bytes_per_second": 21.0,
                    "error_upper_bytes": 1.0,
                }
                for key in ("a", "b")
            ],
        },
    }
    return {
        "policy": policy,
        "calibration": calibration,
        "observation": observation,
        "state": state,
        "action": action,
    }


def evaluate(data, alternatives=None, now=100.0):
    # Synthetic provider: bind each intentionally varied test scenario before use.
    data, alternatives = copy.deepcopy((data, alternatives))
    for action in [
        data["action"],
        *(alternatives if isinstance(alternatives, list) else []),
    ]:
        if isinstance(action, dict):
            try:
                action["bounds"]["input_sha256"] = safety_input_digest(
                    data["observation"], action["routes"]
                )
            except ValidationError:
                pass
    return SafetyShield(data["policy"], data["calibration"]).evaluate(
        data["observation"],
        data["action"],
        alternatives,
        state=data["state"],
        now=now,
    )


def candidate(data, identity, route="route-A"):
    action = copy.deepcopy(data["action"])
    action["action_id"] = action["bounds"]["action_id"] = identity
    action["routes"][0]["route_id"] = route
    action["bounds"]["input_sha256"] = safety_input_digest(
        data["observation"], action["routes"]
    )
    return action


def blockers(result):
    return {reason for check in result["checks"] for reason in check["blockers"]}


def test_explicit_one_step_certificate_and_serialization(inputs):
    result = evaluate(inputs)
    assert result["decision"] == "accept"
    assert result["selected_action"] == inputs["action"]
    assert result["envelope"]["q_next_upper_bytes"] == {"a": 41.0, "b": 41.0}
    assert result["drift"] == {
        "v_before_bytes_squared": 2500.0,
        "v_next_upper_bytes_squared": 1681.0,
        "upper_bytes_squared": -819.0,
        "budget_bytes_squared": 0.0,
    }
    assert result["expires_at_unix_seconds"] <= 100.9
    assert result["validity"] == {"valid": True, "conditional": True}
    assert result["certificate"]["horizon_end_unix_seconds"] == 101.0
    json.dumps(result, allow_nan=False)


def test_reflection_then_positive_error_not_clipped_away(inputs):
    for bound in inputs["action"]["bounds"]["queues"]:
        bound.update(
            service_lower_bytes_per_second=90.0, service_upper_bytes_per_second=91.0
        )
    assert evaluate(inputs)["envelope"]["q_next_upper_bytes"] == {"a": 1.0, "b": 1.0}


def test_unsafe_proposal_deterministic_projection_preserves_ids(inputs):
    a, z = candidate(inputs, "alternative-a"), candidate(inputs, "alternative-z")
    inputs["action"]["bounds"]["queues"][0]["arrival_upper_bytes_per_second"] = 200.0
    first = evaluate(inputs, [z, a])
    second = evaluate(inputs, [a, z])
    assert first["decision"] == second["decision"] == "project"
    assert first["selected_action"] == second["selected_action"] == a
    assert first["certificate"]["action_id"] == "alternative-a"
    assert first["certificate"]["routes"] == a["routes"]
    assert len(first["checks"]) == 3
    assert "next_envelope_violated" in blockers(first)
    assert "drift_budget_exceeded" in blockers(first)


def test_proposed_is_preferred_even_if_alternative_sorts_first(inputs):
    assert (
        evaluate(inputs, [candidate(inputs, "aaa")])["selected_action"]["action_id"]
        == "proposed"
    )


def test_overload_no_dispatch_does_not_certify_hold(inputs):
    for bound in inputs["action"]["bounds"]["queues"]:
        bound["arrival_upper_bytes_per_second"] = 200.0
    result = evaluate(inputs, [candidate(inputs, "hold")])
    assert result["decision"] == "no_dispatch"
    assert (
        result["selected_action"] is result["certificate"] is result["envelope"] is None
    )
    assert result["validity"]["valid"] is False
    assert "Holding is not certified safe" in result["guidance"]
    json.dumps(result, allow_nan=False)


def test_threshold_and_drift_are_independent_inclusive_checks(inputs):
    for bound in inputs["action"]["bounds"]["queues"]:
        bound["arrival_upper_bytes_per_second"] = 69.0
    assert "drift_budget_exceeded" in blockers(evaluate(inputs))
    assert "next_envelope_violated" not in blockers(evaluate(inputs))
    inputs["policy"]["drift_budget_bytes_squared"] = 7500.0
    assert evaluate(inputs)["envelope"]["q_next_upper_bytes"] == {
        "a": 100.0,
        "b": 100.0,
    }
    inputs["policy"]["drift_budget_bytes_squared"] = 7499.0
    assert evaluate(inputs)["decision"] == "no_dispatch"


def test_initial_violation_cannot_be_called_preservation(inputs):
    inputs["observation"]["queues"][0]["queue_bytes"] = 101.0
    assert "initial_envelope_violated" in blockers(evaluate(inputs))


def test_default_rejects_and_payload_cannot_install_calibration(inputs):
    shield = SafetyShield()
    result = shield.evaluate(
        inputs["observation"], inputs["action"], state=inputs["state"], now=100.0
    )
    assert result["reason"] == "trusted_policy_or_calibration_unavailable"
    inputs["action"]["bounds"]["calibrated"] = True
    assert "invalid_candidate" in blockers(evaluate(inputs))


@pytest.mark.parametrize("field", ["observation", "state", "action"])
def test_null_evidence_fails_closed(inputs, field):
    inputs[field] = None
    assert evaluate(inputs)["decision"] == "no_dispatch"


@pytest.mark.parametrize(
    "now", [None, True, "100", math.nan, math.inf, -math.inf, -1.0, 99.0, 103.0]
)
def test_invalid_future_stale_clock(inputs, now):
    result = evaluate(inputs, now=now)
    assert result["decision"] == "no_dispatch"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("counter_reset", True, "reset_or_replayed_snapshot"),
        ("sequence", 1, "reset_or_replayed_snapshot"),
        ("sequence", 0, "reset_or_replayed_snapshot"),
        ("attribution_complete", False, "unknown_demand_attribution"),
        ("unknown_demand_ids", ["unknown"], "unknown_demand_attribution"),
        ("run_id", "new-run", "run_mismatch"),
        ("snapshot_id", "other", "state_snapshot_mismatch"),
        ("network_id", "other", "network_mismatch"),
    ],
)
def test_bad_observation_evidence(inputs, field, value, reason):
    inputs["observation"][field] = value
    assert reason in blockers(evaluate(inputs))


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("dt_seconds", 3.0, "invalid_horizon_or_excessive_delay"),
        ("dt_seconds", 0.0, "invalid_candidate"),
        ("actuation_delay_upper_seconds", 2.1, "invalid_horizon_or_excessive_delay"),
        ("actuation_delay_upper_seconds", 1.0, "invalid_horizon_or_excessive_delay"),
        ("valid_until_unix_seconds", 100.5, "invalid_horizon_or_excessive_delay"),
        ("observed_at_unix_seconds", 99.0, "uncorrelated_bounds"),
        ("provider_id", "untrusted", "uncorrelated_bounds"),
        ("policy_version", "other-policy", "uncorrelated_bounds"),
        ("calibration_id", "self-attested", "uncorrelated_bounds"),
        ("action_id", "other", "candidate_identity_mismatch"),
        ("run_id", "other", "candidate_identity_mismatch"),
        ("snapshot_id", "other", "candidate_identity_mismatch"),
    ],
)
def test_invalid_candidate_bounds(inputs, field, value, reason):
    inputs["action"]["bounds"][field] = value
    assert reason in blockers(evaluate(inputs))


def test_delay_includes_observation_age_and_expiry_is_exclusive(inputs):
    assert evaluate(inputs, now=100.5)["decision"] == "accept"
    assert evaluate(inputs, now=100.9)["decision"] == "no_dispatch"
    inputs["policy"]["max_delay_seconds"] = 0.5
    assert evaluate(inputs, now=100.5)["decision"] == "no_dispatch"


@pytest.mark.parametrize(
    "field,value",
    [
        ("service_lower_bytes_per_second", 22.0),
        ("arrival_lower_bytes_per_second", 11.0),
        ("service_upper_bytes_per_second", 101.0),
        ("service_lower_bytes_per_second", 20.5),
        ("error_upper_bytes", 0.5),
        ("arrival_upper_bytes_per_second", 9.0),
    ],
)
def test_order_capacity_uncertainty_and_attribution(inputs, field, value):
    inputs["action"]["bounds"]["queues"][1][field] = value
    assert evaluate(inputs)["decision"] == "no_dispatch"


@pytest.mark.parametrize(
    "part,field",
    [
        ("observation", "queues"),
        ("observation", "demands"),
        ("action", "routes"),
        ("state", "active_routes"),
    ],
)
def test_duplicate_scope_blocks(inputs, part, field):
    inputs[part][field].append(copy.deepcopy(inputs[part][field][0]))
    assert evaluate(inputs)["decision"] == "no_dispatch"


def test_duplicate_and_missing_bounds_block(inputs):
    bounds = inputs["action"]["bounds"]["queues"]
    bounds.append(copy.deepcopy(bounds[0]))
    assert "incomplete_or_duplicate_queue_bounds" in blockers(evaluate(inputs))
    bounds.pop()
    bounds.pop()
    assert "incomplete_or_duplicate_queue_bounds" in blockers(evaluate(inputs))


def test_duplicate_action_identity_refuses_ambiguous_projection(inputs):
    assert (
        evaluate(inputs, [copy.deepcopy(inputs["action"])])["reason"]
        == "duplicate_action_identity"
    )


@pytest.mark.parametrize(
    "change",
    ["not_allowed", "disconnect", "cycle", "wrong_destination", "missing_egress"],
)
def test_paths(inputs, change):
    path = inputs["policy"]["allowed_paths"][1]
    if change == "not_allowed":
        inputs["action"]["routes"][0]["route_id"] = "invented"
    elif change == "disconnect":
        inputs["observation"]["queues"][1]["source"] = "other"
    elif change == "cycle":
        inputs["observation"]["queues"][1]["destination"] = "s"
    elif change == "wrong_destination":
        path["destination"] = "other"
    else:
        path["egress_ids"] = ["missing"]
    assert evaluate(inputs)["decision"] == "no_dispatch"


def test_connected_multihop_path_attributes_each_egress(inputs):
    inputs["policy"]["allowed_paths"][1]["egress_ids"] = ["a", "b"]
    inputs["observation"]["queues"][0]["destination"] = "middle"
    inputs["observation"]["queues"][1]["source"] = "middle"
    assert evaluate(inputs)["decision"] == "accept"
    inputs["action"]["bounds"]["queues"][0]["arrival_upper_bytes_per_second"] = 9.0
    assert "understated_attributed_arrivals" in blockers(evaluate(inputs))


def test_multiple_demands_sum_not_max(inputs):
    inputs["calibration"]["demand_ids"].append("demand-2")
    demand = copy.deepcopy(inputs["observation"]["demands"][0])
    demand["demand_id"] = "demand-2"
    inputs["observation"]["demands"].append(demand)
    inputs["state"]["active_routes"].append(
        {"demand_id": "demand-2", "route_id": "route-A"}
    )
    inputs["action"]["routes"].append({"demand_id": "demand-2", "route_id": "route-B"})
    assert "understated_attributed_arrivals" in blockers(evaluate(inputs))
    inputs["action"]["bounds"]["queues"][1]["arrival_upper_bytes_per_second"] = 20.0
    assert evaluate(inputs)["decision"] == "accept"


def test_dwell_repeated_rejection_does_not_reset_history(inputs):
    inputs["state"].update(
        route_since_unix_seconds=97.0,
        last_applied_at_unix_seconds=97.0,
        recent_dispatch_at_unix_seconds=[97.0],
    )
    shield = SafetyShield(inputs["policy"], inputs["calibration"])
    original = copy.deepcopy(inputs["state"])
    for _ in range(3):
        result = shield.evaluate(
            inputs["observation"], inputs["action"], state=inputs["state"], now=100.0
        )
        assert "minimum_dwell_not_elapsed" in blockers(result)
        assert inputs["state"] == original
    for part in (inputs["observation"], inputs["state"], inputs["action"]["bounds"]):
        part["observed_at_unix_seconds"] = 102.0
    assert evaluate(inputs, now=102.0)["decision"] == "accept"


def test_rate_limit_independent_of_same_route_and_dwell(inputs):
    inputs["state"].update(
        last_applied_at_unix_seconds=99.0, recent_dispatch_at_unix_seconds=[95.0, 99.0]
    )
    inputs["action"]["routes"][0]["route_id"] = "route-A"
    assert "action_rate_limited" in blockers(evaluate(inputs))


def test_rate_window_boundary_excludes_old_action(inputs):
    inputs["state"].update(
        last_applied_at_unix_seconds=99.0, recent_dispatch_at_unix_seconds=[90.0, 99.0]
    )
    assert evaluate(inputs)["decision"] == "accept"


@pytest.mark.parametrize(
    "patch",
    [
        {"history_complete_since_unix_seconds": 99.0},
        {"route_since_unix_seconds": 101.0},
        {"last_applied_at_unix_seconds": 101.0},
        {"last_applied_at_unix_seconds": None},
        {"recent_dispatch_at_unix_seconds": []},
        {"recent_dispatch_at_unix_seconds": [80.0, 80.0]},
        {"recent_dispatch_at_unix_seconds": [79.0, 80.0]},
        {"recent_dispatch_at_unix_seconds": [101.0]},
    ],
)
def test_invalid_state_history(inputs, patch):
    inputs["state"].update(patch)
    assert "invalid_or_incomplete_action_history" in blockers(evaluate(inputs))


def test_hysteresis_requires_baseline_and_margin_not_queue_drift(inputs):
    inputs["policy"]["hysteresis_bytes_squared"] = 1.0
    assert "hysteresis_baseline_unavailable" in blockers(evaluate(inputs))
    baseline = candidate(inputs, "incumbent")
    result = evaluate(inputs, [baseline])
    assert result["decision"] == "project"
    assert "hysteresis_margin_not_met" in blockers(result)
    for bound in baseline["bounds"]["queues"]:
        bound["arrival_upper_bytes_per_second"] = 11.0
    assert evaluate(inputs, [baseline])["decision"] == "accept"
    baseline["bounds"]["dt_seconds"] = 2.0
    assert "hysteresis_horizon_mismatch" in blockers(evaluate(inputs, [baseline]))


@pytest.mark.parametrize(
    "bad", [None, True, False, "1", math.nan, math.inf, -math.inf, -1.0]
)
def test_every_unit_field_is_strict_finite_and_nonnegative(inputs, bad):
    examples = [
        (SafetyPolicy, inputs["policy"]),
        (TrustedCalibration, inputs["calibration"]),
        (SafetyObservation, inputs["observation"]),
        (SafetyState, inputs["state"]),
        (CandidateBounds, inputs["action"]["bounds"]),
        (QueueBounds, inputs["action"]["bounds"]["queues"][0]),
        (QueueObservation, inputs["observation"]["queues"][0]),
        (DemandObservation, inputs["observation"]["demands"][0]),
    ]
    for model, example in examples:
        for field in model.model_fields:
            if not field.endswith(
                ("seconds", "bytes", "bytes_squared", "bytes_per_second")
            ):
                continue
            if field == "last_applied_at_unix_seconds" and bad is None:
                continue
            if field == "drift_budget_bytes_squared" and bad == -1.0:
                continue
            payload = copy.deepcopy(example)
            payload[field] = bad
            with pytest.raises(ValidationError):
                model.model_validate(payload)


def test_mutated_model_instances_are_revalidated(inputs):
    action = SafetyAction.model_validate(inputs["action"])
    action.bounds.queues[0].error_upper_bytes = math.nan
    inputs["action"] = action
    assert "invalid_candidate" in blockers(evaluate(inputs))


def test_numeric_overflow_fails_closed_without_nan_output(inputs):
    for queue in inputs["observation"]["queues"]:
        queue["queue_bytes"] = 1e308
    result = evaluate(inputs)
    assert "nonrepresentable_certificate" in blockers(result)
    assert result["decision"] == "no_dispatch"
    json.dumps(result, allow_nan=False)


def test_exact_math_avoids_cancellation_false_acceptance(inputs):
    for queue in inputs["observation"]["queues"]:
        queue["queue_bytes"] = 1e16
    inputs["policy"]["queue_threshold_bytes"] = 1e16
    for bound in inputs["action"]["bounds"]["queues"]:
        bound.update(arrival_upper_bytes_per_second=20.0, error_upper_bytes=1.0)
    result = evaluate(inputs)
    assert "next_envelope_violated" in blockers(result)
    assert "drift_budget_exceeded" in blockers(result)


def test_outward_rounded_envelope_and_drift(inputs):
    for bound in inputs["action"]["bounds"]["queues"]:
        bound["error_upper_bytes"] = 1.1
    result = evaluate(inputs)
    exact_q = Fraction(40) + Fraction(1.1)
    exact_drift = exact_q**2 - 2500
    assert Fraction(result["envelope"]["q_next_upper_bytes"]["a"]) >= exact_q
    assert Fraction(result["drift"]["upper_bytes_squared"]) >= exact_drift


def test_calibration_expiry_covers_entire_horizon(inputs):
    inputs["calibration"]["valid_until_unix_seconds"] = 100.5
    assert "invalid_horizon_or_excessive_delay" in blockers(evaluate(inputs))
    inputs["calibration"]["valid_until_unix_seconds"] = 100.0
    assert "calibration_expired_or_not_yet_valid" in blockers(evaluate(inputs))


def test_configuration_is_copied_not_payload_mutable(inputs):
    shield = SafetyShield(inputs["policy"], inputs["calibration"])
    inputs["policy"]["queue_threshold_bytes"] = 1.0
    inputs["calibration"]["valid_until_unix_seconds"] = 1.0
    assert (
        shield.evaluate(
            inputs["observation"], inputs["action"], state=inputs["state"], now=100.0
        )["decision"]
        == "accept"
    )


def test_malformed_proposed_does_not_hide_valid_alternative(inputs):
    alternative = candidate(inputs, "alternative")
    inputs["action"] = None
    result = evaluate(inputs, [alternative])
    assert result["decision"] == "project"
    assert "invalid_candidate" in blockers(result)


@pytest.mark.parametrize("alternatives", [{}, "invalid", [None] * 256])
def test_invalid_alternative_collection(inputs, alternatives):
    assert evaluate(inputs, alternatives)["reason"] == "invalid_alternatives"


@pytest.mark.parametrize("field", ["counter_reset", "attribution_complete", "sequence"])
def test_flags_and_sequence_do_not_coerce(inputs, field):
    inputs["observation"][field] = "1"
    assert evaluate(inputs)["decision"] == "no_dispatch"


def test_empty_queue_positive_error_zero_budget_is_infeasible(inputs):
    for queue in inputs["observation"]["queues"]:
        queue["queue_bytes"] = 0.0
    result = evaluate(inputs)
    assert "drift_budget_exceeded" in blockers(result)
    assert "next_envelope_violated" not in blockers(result)


def test_nominal_service_margin_smaller_than_error_does_not_prove_drift(inputs):
    for bound in inputs["action"]["bounds"]["queues"]:
        bound["arrival_upper_bytes_per_second"] = 19.5
    assert "drift_budget_exceeded" in blockers(evaluate(inputs))


@pytest.mark.parametrize(
    "part,field,value",
    [
        ("policy", "queue_threshold_bytes", 0.0),
        ("policy", "max_actions_per_window", True),
        ("policy", "max_actions_per_window", 2.0),
        ("calibration", "valid_until_unix_seconds", 0.0),
        ("calibration", "egress_ids", ["a", "a"]),
        ("calibration", "demand_ids", ["demand-1", "demand-1"]),
    ],
)
def test_invalid_trusted_configuration_raises(inputs, part, field, value):
    inputs[part][field] = value
    with pytest.raises(ValidationError):
        SafetyShield(inputs["policy"], inputs["calibration"])


def test_duplicate_policy_route_raises(inputs):
    inputs["policy"]["allowed_paths"].append(
        copy.deepcopy(inputs["policy"]["allowed_paths"][0])
    )
    with pytest.raises(ValidationError):
        SafetyShield(inputs["policy"], inputs["calibration"])


@pytest.mark.parametrize("queue", [0.0, 1.0, 50.0, 100.0])
@pytest.mark.parametrize("arrival", [10.0, 19.0, 20.0, 100.0])
def test_certificate_matches_exact_model_grid(inputs, queue, arrival):
    for observed in inputs["observation"]["queues"]:
        observed["queue_bytes"] = queue
    for bound in inputs["action"]["bounds"]["queues"]:
        bound["arrival_upper_bytes_per_second"] = arrival
    upper = max(Fraction(0), Fraction(queue) + Fraction(arrival) - 20) + 1
    expected_safe = upper <= 100 and upper**2 - Fraction(queue) ** 2 <= 0
    result = evaluate(inputs)
    assert (result["decision"] == "accept") is expected_safe
    if expected_safe:
        for actual_next in (Fraction(0), upper / 2, upper):
            assert actual_next <= 100
            assert actual_next**2 - Fraction(queue) ** 2 <= 0


@pytest.mark.parametrize("change", ["queue", "capacity", "demand", "route", "source"])
def test_provider_bound_inputs_cannot_mutate_under_reused_ids(inputs, change):
    if change == "queue":
        inputs["observation"]["queues"][0]["queue_bytes"] = 49.0
    elif change == "capacity":
        inputs["observation"]["queues"][0]["capacity_bytes_per_second"] = 99.0
    elif change == "demand":
        inputs["observation"]["demands"][0]["arrival_upper_bytes_per_second"] = 9.0
    elif change == "route":
        inputs["action"]["routes"][0]["route_id"] = "route-A"
    else:
        inputs["observation"]["demands"][0]["source"] = "other"
    result = SafetyShield(inputs["policy"], inputs["calibration"]).evaluate(
        inputs["observation"], inputs["action"], state=inputs["state"], now=100.0
    )
    assert result["decision"] == "no_dispatch"
    assert "bound_input_mismatch" in blockers(result)


def test_missing_input_binding_rejects_without_hiding_bound_alternative(inputs):
    alternative = candidate(inputs, "alternative")
    del inputs["action"]["bounds"]["input_sha256"]
    result = SafetyShield(inputs["policy"], inputs["calibration"]).evaluate(
        inputs["observation"],
        inputs["action"],
        [alternative],
        state=inputs["state"],
        now=100.0,
    )
    assert result["decision"] == "project"
    assert "invalid_candidate" in blockers(result)
    assert (
        result["certificate"]["input_sha256"] == alternative["bounds"]["input_sha256"]
    )


def test_input_binding_normalizes_validated_numbers_and_route_order(inputs):
    routes = inputs["action"]["routes"] + [
        {"demand_id": "demand-2", "route_id": "route-A"}
    ]
    digest = safety_input_digest(inputs["observation"], routes)
    inputs["observation"]["queues"][0]["queue_bytes"] = 50
    assert safety_input_digest(inputs["observation"], list(reversed(routes))) == digest
    assert (
        safety_input_digest(
            SafetyObservation.model_validate(inputs["observation"]), routes
        )
        == digest
    )


def test_source_timestamp_cannot_be_refreshed_without_new_bounds(inputs):
    for source in (inputs["observation"], inputs["state"]):
        source["observed_at_unix_seconds"] = 100.5
    result = evaluate(inputs, now=100.5)
    assert "uncorrelated_bounds" in blockers(result)
    assert result["decision"] == "no_dispatch"


def test_certificate_recheck_at_serialized_expiry_refuses(inputs):
    shield = SafetyShield(inputs["policy"], inputs["calibration"])
    result = shield.evaluate(
        inputs["observation"], inputs["action"], state=inputs["state"], now=100.0
    )
    expired = shield.evaluate(
        inputs["observation"],
        inputs["action"],
        state=inputs["state"],
        now=result["expires_at_unix_seconds"],
    )
    assert expired["decision"] == "no_dispatch"
    assert expired["certificate"] is None


@pytest.mark.parametrize(
    "part,model", [("observation", SafetyObservation), ("state", SafetyState)]
)
def test_mutated_observation_and_state_instances_revalidate(inputs, part, model):
    payload = model.model_validate(inputs[part])
    if part == "observation":
        payload.queues[0].queue_bytes = True
    else:
        payload.recent_dispatch_at_unix_seconds.append(math.inf)
    inputs[part] = payload
    assert evaluate(inputs)["reason"] == "invalid_observation_state_or_clock"


def test_model_configuration_deep_copy_and_result_isolation(inputs):
    policy = SafetyPolicy.model_validate(inputs["policy"])
    calibration = TrustedCalibration.model_validate(inputs["calibration"])
    shield = SafetyShield(policy, calibration)
    policy.allowed_paths[1].egress_ids.clear()
    calibration.egress_ids.clear()
    original = copy.deepcopy(inputs)
    result = shield.evaluate(
        inputs["observation"], inputs["action"], state=inputs["state"], now=100.0
    )
    assert result["decision"] == "accept"
    result["selected_action"]["bounds"]["queues"].clear()
    result["certificate"]["routes"].clear()
    assert inputs == original
    assert (
        shield.evaluate(
            inputs["observation"], inputs["action"], state=inputs["state"], now=100.0
        )["decision"]
        == "accept"
    )


@pytest.mark.parametrize("field", ["counter_reset", "attribution_complete"])
@pytest.mark.parametrize("value", [0, 1, 0.0, 1.0, "true", None])
def test_boolean_flags_require_actual_booleans(inputs, field, value):
    inputs["observation"][field] = value
    assert evaluate(inputs)["reason"] == "invalid_observation_state_or_clock"


@pytest.mark.parametrize("value", [True, False, 2.0, 2**63])
def test_sequence_is_bounded_strict_integer(inputs, value):
    inputs["observation"]["sequence"] = value
    assert evaluate(inputs)["reason"] == "invalid_observation_state_or_clock"


def test_rate_limit_cannot_exceed_history_contract_capacity(inputs):
    inputs["policy"]["max_actions_per_window"] = 10001
    with pytest.raises(ValidationError):
        SafetyShield(inputs["policy"], inputs["calibration"])


@pytest.mark.parametrize("value", [math.nextafter(0.0, 1.0), 1e308])
def test_extreme_finite_horizons_fail_closed(inputs, value):
    inputs["action"]["bounds"]["dt_seconds"] = value
    result = evaluate(inputs)
    assert result["decision"] == "no_dispatch"
    json.dumps(result, allow_nan=False)


def test_exact_arrival_attribution_sum_cannot_overflow(inputs):
    second = copy.deepcopy(inputs["observation"]["demands"][0])
    second["demand_id"] = "demand-2"
    inputs["observation"]["demands"].append(second)
    inputs["calibration"]["demand_ids"].append("demand-2")
    for demand in inputs["observation"]["demands"]:
        demand["arrival_upper_bytes_per_second"] = 1e308
    inputs["state"]["active_routes"].append(
        {"demand_id": "demand-2", "route_id": "route-A"}
    )
    inputs["action"]["routes"].append({"demand_id": "demand-2", "route_id": "route-B"})
    inputs["action"]["bounds"]["queues"][1]["arrival_upper_bytes_per_second"] = 1e308
    result = evaluate(inputs)
    assert "understated_attributed_arrivals" in blockers(result)
    assert result["decision"] == "no_dispatch"
    json.dumps(result, allow_nan=False)


def test_expired_rounded_incumbent_cannot_supply_hysteresis_evidence(inputs):
    inputs["policy"]["hysteresis_bytes_squared"] = 1.0
    baseline = candidate(inputs, "incumbent")
    baseline["bounds"].update(
        dt_seconds=math.ulp(100.0) / 4,
        actuation_delay_upper_seconds=0.0,
    )
    result = evaluate(inputs, [baseline])
    assert result["decision"] == "no_dispatch"
    assert "certificate_expired" in blockers(result)
    assert "hysteresis_baseline_unavailable" in blockers(result)


def test_old_source_bounds_cannot_be_used_as_projection(inputs):
    alternative = candidate(inputs, "alternative")
    alternative["bounds"]["observed_at_unix_seconds"] = 99.0
    inputs["action"]["bounds"]["queues"][0]["arrival_upper_bytes_per_second"] = 200.0
    result = evaluate(inputs, [alternative])
    assert result["decision"] == "no_dispatch"
    assert "uncorrelated_bounds" in blockers(result)


def test_huge_integer_numeric_input_fails_closed(inputs):
    inputs["observation"]["queues"][0]["queue_bytes"] = 10**10000
    result = evaluate(inputs)
    assert result["reason"] == "invalid_observation_state_or_clock"
    json.dumps(result, allow_nan=False)
