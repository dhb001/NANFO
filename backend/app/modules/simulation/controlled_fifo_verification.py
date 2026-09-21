"""Independent event replay and theorem obligations; no acquisition/model calls."""

from __future__ import annotations

import hashlib

from app.modules.autonomy.artifact_io import ArtifactRef, ArtifactStore, EvidenceError, parse_json
from app.modules.simulation.controlled_fifo_campaign import ControlledPlan, RUNTIME


def _integer(value):
    return type(value) is int and value >= 0


def replay(plan: ControlledPlan, window: dict) -> dict:
    def require(condition, reason):
        if not condition:
            raise EvidenceError(reason)

    key = window.get("sample_id")
    require(key in plan.plans and window.get("plan") == plan.plans[key], "unreviewed_executable_fifo_plan")
    require(window.get("runtime") == RUNTIME and window.get("physical_qualified") is False
            and window.get("collector_sha256") == plan.collector_sha256, "fifo_runtime_scope_mismatch")
    start, end = window["start_monotonic_ns"], window["end_monotonic_ns"]
    require(_integer(start) and _integer(end) and end - start >= plan.epoch_ns
            and _integer(window["socket_closed_monotonic_ns"])
            and window["socket_closed_monotonic_ns"] <= start, "unsealed_or_invalid_fifo_epoch")
    require(all(type(window[k]) is int and window[k] == 0 for k in
                ("arrivals_during_epoch_bytes", "unknown_demand_bytes", "dropped_bytes", "service_lower_bytes_per_second")),
            "fifo_epoch_not_closed")
    prefill = window["prefill"]
    require(len(prefill) == plan.prefill_packets, "incomplete_fifo_prefill")
    for i, row in enumerate(prefill):
        expected = hashlib.sha256(i.to_bytes(4, "big") + bytes(plan.packet_bytes - 4)).hexdigest()
        require(type(row["sequence"]) is int and row["sequence"] == i and row["sha256"] == expected
                and type(row["bytes"]) is int and row["bytes"] == plan.packet_bytes
                and _integer(row["received_monotonic_ns"])
                and row["received_monotonic_ns"] <= window["socket_closed_monotonic_ns"], "fifo_native_prefill_mismatch")
    q = plan.capacity_bytes
    require(type(window["queue_before_bytes"]) is int and window["queue_before_bytes"] == q, "fifo_initial_queue_mismatch")
    action = plan.plans[key]["previous_action_id"]
    last, next_service, served, transitions = start, start, 0, []
    for event in window["events"]:
        now = event["monotonic_ns"]
        require(type(now) is int and last <= now < end, "fifo_event_order_mismatch")
        last = now
        if event["kind"] == "action":
            action = plan.plans[key]["action_id"]
            require(event["action_id"] == action
                    and event["packet_interval_ns"] == plan.action_packet_interval_ns[action]
                    and now - start >= plan.transition_after_ns, "fifo_action_mapping_mismatch")
            transitions.append(now)
        elif event["kind"] == "dequeue":
            require(served < len(prefill) and event["sha256"] == prefill[served]["sha256"]
                    and event["bytes"] == plan.packet_bytes and event["action_id"] == action
                    and now >= next_service, "fifo_service_regulator_or_payload_mismatch")
            next_service = now + plan.action_packet_interval_ns[action]
            served += 1
            q -= plan.packet_bytes
            require(event["queue_after_bytes"] == q and 0 <= q <= plan.capacity_bytes, "fifo_conservation_failed")
        else:
            raise EvidenceError("unpermitted_fifo_operation")
    require(type(window["queue_after_bytes"]) is int and window["queue_after_bytes"] == q
            and len(transitions) == 1, "fifo_endpoint_or_transition_incomplete")
    require(transitions[0] - start < plan.epoch_ns, "fifo_transition_deadline_missed")
    return dict(sample_id=key, q_initial_bytes=plan.capacity_bytes, q_actual_next_bytes=q,
                q_next_upper_bytes=plan.capacity_bytes, arrivals_upper_bytes_per_second=0,
                service_lower_bytes_per_second=0, error_upper_bytes=0,
                drift_upper_bytes_squared=0,
                actual_drift_bytes_squared=(q*q-plan.capacity_bytes**2)//2,
                transition_elapsed_ns=transitions[0]-start, served_bytes=served*plan.packet_bytes,
                mathematical_bound_passed=True)


def evaluate(
    protocol_store: ArtifactStore, capture_store: ArtifactStore, manifest_ref: ArtifactRef,
    *, registered_protocol_sha256: str, registered_at_unix_ns: int,
) -> dict:
    manifest = parse_json(capture_store.referenced(manifest_ref))
    if manifest.get("schema_version") != "nanfo.controlled-fifo-measurements.v1":
        raise EvidenceError("controlled_manifest_required")
    pref = ArtifactRef.model_validate(manifest["protocol"])
    if (pref.sha256 != registered_protocol_sha256 or type(registered_at_unix_ns) is not int
            or manifest["registered_at_unix_ns"] != registered_at_unix_ns):
        raise EvidenceError("external_preregistration_receipt_mismatch")
    plan = ControlledPlan.model_validate(parse_json(protocol_store.referenced(pref)))
    rows, windows = [], []
    for raw in manifest["windows"]:
        window = parse_json(capture_store.referenced(ArtifactRef.model_validate(raw)))
        if not plan.declared_at_unix_ns <= manifest["registered_at_unix_ns"] < window["start_unix_ns"]:
            raise EvidenceError("fifo_protocol_not_preregistered")
        rows.append(replay(plan, window))
        windows.append((window["start_monotonic_ns"], window["end_monotonic_ns"]))
    if sorted(row["sample_id"] for row in rows) != sorted(plan.plans):
        raise EvidenceError("fifo_group_coverage_incomplete")
    ordered = sorted(windows)
    if any(right[0] < left[1] for left, right in zip(ordered, ordered[1:])):
        raise EvidenceError("fifo_group_overlap")
    return dict(schema_version="nanfo.controlled-fifo-validation.v1", protocol_sha256=pref.sha256,
                manifest_sha256=manifest_ref.sha256, runtime=RUNTIME, environment="isolated-emulation",
                raw_replay_passed=True, conditional_mathematical_bound_passed=True,
                proof="Closed admission gives A=0. Dequeue-only transitions give S>=0; hence 0<=q(t)<=q0<=B and V(q(t))-V(q0)<=0, regardless of scheduling stalls.",
                service_guarantee="Zero lower bound only. Enforced pacing gives departures <= packet_bytes*(1+floor(elapsed_ns/min_interval_ns)); not a wall-clock service minimum.",
                assumptions=["single-owner immutable collector/source and plan", "prefill sockets closed before observation",
                             "no enqueue/reset/foreign mutation during sealed epoch", "finite queue contains only observed owned payloads"],
                rows=rows, independent_attestation_accepted=False, receiver_installable=False,
                physical_qualified=False, trusted_installation=None,
                blockers=["independent_operator_attestation_not_supplied", "controlled_fifo_runtime_not_supported_by_OVS_FRR_receiver",
                          "FIFO_theorem_does_not_establish_FRR_arrival_service_or_transition_guarantees",
                          "positive_wall_clock_service_and_transition_deadline_not_guaranteed_by_general_purpose_scheduler"])


def blocked_rf_result() -> dict:
    return dict(schema_version="nanfo.independent-rf-validation-manifest.v1", status="blocked",
                environment="physical-network", protocol=None, raw_sources=[], measurement_count=0,
                empirical_acceptance_passed=False, physical_qualified=False, trusted_installation=None,
                missing=["independent_calibrated_RF_sensor_identity_and_calibration", "raw_timestamped_dBm_survey",
                         "externally_preregistered_site_session_split_and_acceptance_thresholds",
                         "surveyed_coordinate_registration_and_error", "actual_radio_antenna_material_parameters",
                         "independent_authenticated_measurements_or_operator_attestation"],
                reason="No independent hardware RF evidence supplied; no generated survey or fitted qualification.")


def blocked_receiver_result(source_store: ArtifactStore) -> dict:
    paths = ["backend/app/modules/autonomy/frr_contract.py", "backend/app/modules/autonomy/frr_installation.py",
             "backend/app/modules/autonomy/causal_frames.py", "backend/scripts/autonomous_frr_receiver.py",
             "emulation/autonomous_frr.py", "emulation/autonomous_causal.py"]
    sources = []
    for path in paths:
        content = source_store.read(path)
        sources.append(dict(path=path, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content)))
    return dict(schema_version="nanfo.independent-receiver-validation.v1", status="blocked",
                target_runtime="isolated-linux-frr-host-route/v1", environment="isolated-emulation",
                source_snapshot=sources, native_action_transition_captures=[], physical_qualified=False,
                trusted_installation=None, receiver_exercised=False,
                missing=["parent_serialized_exclusive_namespace_handoff", "preregistered_executable_plan_egress_demand_mapping",
                         "native_all_egress_same_window_byte_counters_with_unknown_control_background_traffic",
                         "enforced_arrival_envelope_not_counter_average", "within_interval_service_error_guarantee",
                         "old_to_new_route_transition_and_total_delay_guarantee", "independent_operator_attestation",
                         "accepted_exact_runtime_equivalence_and_installation"],
                reason="FRR instrumentation can measure endpoints; it does not enforce causal arrival/service or transition bounds. A sealed application FIFO theorem does not qualify kernel routing.")
