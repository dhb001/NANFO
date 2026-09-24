"""Independent queue evidence reconstruction and explicit trusted installation.

Does not call SafetyShield, fit on holdout, authorize dispatch or infer guarantees
from observed extrema. A reviewed, externally pinned guarantee is indispensable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from app.core.canonical import canonical_sha256
from app.modules.autonomy.artifact_io import ArtifactStore, EvidenceError, parse_json
from app.modules.autonomy.calibration_verification_models import (
    BoundGuarantee, CalibrationInstallation, CalibrationScope,
    NativeBacklogEvidence, NetworkQualificationConfig, NetworkReading,
)
from app.modules.autonomy.safety import SafetyAction, TrustedCalibration
from app.modules.simulation.qualification_protocol import ImportedCampaign, import_campaign


def _outward(value: Fraction) -> float:
    result = float(value)
    if Fraction(result) < value:
        result = math.nextafter(result, math.inf)
    if not math.isfinite(result):
        raise EvidenceError("unrepresentable_independent_bound")
    return result


def _config(campaign):
    # Strict JSON mode supports tuple schemas without coercing numbers/booleans.
    import json

    return NetworkQualificationConfig.model_validate_json(json.dumps(campaign.configuration))


def backlog_reading_digest(reading: NetworkReading) -> str:
    payload = reading.model_dump(mode="json")
    for queue in payload["queues"]:
        queue.pop("native_backlog_evidence", None)
    return canonical_sha256(payload)


def _busy_period(reading, queue, sample_id, store, accepted):
    """A complete busy window only; idle/draining windows cannot use this gate.

    External review authenticates trace completeness/hook semantics. Reconstruction
    here proves positive backlog after EVERY recorded queue mutation, and exact
    counter totals. Polls or a producer's 'busy' flag cannot satisfy it.
    """
    ref = queue.native_backlog_evidence
    if store is None or ref is None or ref.sha256 not in accepted:
        raise EvidenceError("independent_native_backlog_evidence_required")
    evidence = NativeBacklogEvidence.model_validate(parse_json(store.referenced(ref)))
    store.referenced(evidence.native_source)
    if (evidence.sample_id != sample_id or evidence.egress_id != queue.egress_id
            or evidence.reading_sha256 != backlog_reading_digest(reading)
            or evidence.start_unix_seconds != reading.start_unix_seconds
            or evidence.end_unix_seconds != reading.end_unix_seconds
            or evidence.initial_queue_bytes != queue.queue_before_bytes
            or evidence.final_queue_bytes != queue.queue_after_bytes
            or evidence.lost_events or queue.measurement_error_bytes):
        raise EvidenceError("native_busy_period_scope_or_precision_mismatch")
    horizon_ns = (Fraction(reading.end_unix_seconds) - Fraction(reading.start_unix_seconds)) * 10**9
    backlog, last, totals = evidence.initial_queue_bytes, -1, {k: 0 for k in ("enqueue", "dequeue", "drop")}
    for event in evidence.events:
        if not last <= event.offset_ns <= horizon_ns:
            raise EvidenceError("native_busy_period_event_order_or_horizon")
        last = event.offset_ns
        totals[event.operation] += event.bytes
        backlog += event.bytes if event.operation == "enqueue" else -event.bytes
        if backlog <= 0:
            raise EvidenceError("native_window_not_continuously_backlogged")
    if (backlog != evidence.final_queue_bytes or totals["enqueue"] != queue.arrivals.delta
            or totals["dequeue"] != queue.departures.delta or totals["drop"] != queue.drops.delta):
        raise EvidenceError("native_busy_period_counter_mismatch")


def shield_service_upper(config, bound, horizon_seconds):
    """Explicit prospective mapping for a rate-only shield; NEVER rewrite capacity.

    Only the UPPER is mapped here. Available lower service is independently mapped
    to zero by runtime_service_bounds; past backlog never proves future backlog.
    """
    h = Fraction(horizon_seconds)
    if h <= 0 or h > Fraction(config.dt_seconds) or (config.min_dt_seconds is not None and h < Fraction(config.min_dt_seconds)):
        raise EvidenceError("service_mapping_horizon_outside_reviewed_scope")
    return min(bound.capacity_bytes_per_second,
               _outward(Fraction(bound.service_upper_bytes_per_second) + Fraction(bound.service_upper_burst_bytes) / h))


def runtime_service_bounds(config, bound, horizon_seconds):
    """One shared provider/installation/receiver mapping, no change to shield math.

    Busy-period available service is never represented as future departures.
    Its zero lower bound can fail the unchanged drift policy; that is a genuine
    no-admissible-action result, not an installation capability gap.
    """
    upper = shield_service_upper(config, bound, horizon_seconds)
    lower = bound.service_lower_bytes_per_second if bound.service_lower_semantics == "actual-departures" else 0.0
    return lower, upper


def runtime_uncertainty_floor(config):
    """Global minimum across EXACT per-queue mapped widths, rounded inward.

    v2 retains every queue's full width through exact profile checks. The shield's
    global *minimum* must not be the maximum width of heterogeneous queues.
    """
    width = min(Fraction(upper) - Fraction(lower) for a in config.actions for b in a.bounds
                for lower, upper in [runtime_service_bounds(config, b, config.dt_seconds)])
    value = float(width)
    return math.nextafter(value, -math.inf) if Fraction(value) > width else value


def verify_network_campaign(campaign: ImportedCampaign, *, evidence_store=None,
                            accepted_service_semantics_sha256=frozenset(),
                            accepted_native_backlog_sha256=frozenset(),
                            runtime_projection=False) -> dict:
    config = _config(campaign)
    if campaign.protocol.domain != "network":
        raise EvidenceError("network_campaign_required")
    if config.schema_version.endswith(".v2"):
        ref = config.service_semantics_evidence
        if evidence_store is None or ref.sha256 not in accepted_service_semantics_sha256:
            raise EvidenceError("independent_service_semantics_review_required")
        evidence_store.referenced(ref)
    actions = {a.action_id: a for a in config.actions}
    reports, coverage, transitions, windows = [], {}, {}, {}
    splits = {g.group_id: g.split for g in campaign.protocol.groups}
    for capture in campaign.captures:
        split = splits[capture.group_id]
        for record in capture.records:
            reading = NetworkReading.model_validate(record.measurement)
            failures = []
            old, new = reading.previous_action_id, reading.action_id
            if old not in actions or new not in actions:
                raise EvidenceError("undeclared_action")
            if (old, new) not in config.required_transitions:
                raise EvidenceError("undeclared_transition")
            dt = Fraction(reading.end_unix_seconds) - Fraction(reading.start_unix_seconds)
            if (not 0 < dt <= Fraction(config.dt_seconds)
                    or (config.min_dt_seconds is not None and dt < Fraction(config.min_dt_seconds))
                    or reading.start_unix_seconds != record.observed_at_unix_seconds):
                raise EvidenceError("measurement_horizon_or_identity_mismatch")
            if reading.end_unix_seconds > campaign.attested_at_unix_seconds:
                raise EvidenceError("attestation_precedes_measurement_completion")
            if not (reading.start_unix_seconds <= reading.dispatch_unix_seconds
                    <= reading.applied_unix_seconds <= reading.transition_complete_unix_seconds
                    < reading.end_unix_seconds):
                failures.append("invalid_transition_timing")
            delay = Fraction(reading.transition_complete_unix_seconds) - Fraction(reading.start_unix_seconds)
            if delay > Fraction(config.max_delay_seconds):
                failures.append("delay_bound_exceeded")
            if (not reading.measurement_complete or not reading.attribution_complete
                    or reading.counter_reset or reading.unknown_demand_ids):
                failures.append("incomplete_measurement_or_unknown_demand")
            if sorted(q.egress_id for q in reading.queues) != sorted(config.egress_ids):
                raise EvidenceError("incomplete_queue_scope")
            coverage[split, new] = coverage.get((split, new), 0) + 1
            transitions[split, old, new] = transitions.get((split, old, new), 0) + 1
            windows.setdefault(capture.group_id, []).append((reading.start_unix_seconds, reading.end_unix_seconds))
            bounds = {b.egress_id: b for b in actions[new].bounds}
            details, before_v, upper_v, actual_v = [], Fraction(0), Fraction(0), Fraction(0)
            for q in reading.queues:
                bound = bounds[q.egress_id]
                if config.schema_version.endswith(".v1") and q.native_backlog_evidence is not None:
                    raise EvidenceError("v1_backlog_semantics_not_supported")
                if bound.service_lower_semantics == "busy-period-available":
                    _busy_period(reading, q, record.sample_id, evidence_store, accepted_native_backlog_sha256)
                if set(q.demand_arrivals) != set(config.demand_ids):
                    raise EvidenceError("incomplete_demand_counters")
                q0, q1 = Fraction(q.queue_before_bytes), Fraction(q.queue_after_bytes)
                arrivals, departures, drops = q.arrivals.delta, q.departures.delta, q.drops.delta
                if q.unknown_arrival_bytes or sum(p.delta for p in q.demand_arrivals.values()) != arrivals:
                    failures.append("unattributed_arrivals")
                for demand, pair in q.demand_arrivals.items():
                    allowed = set(actions[old].demand_egress_ids[demand]) | set(actions[new].demand_egress_ids[demand])
                    if pair.delta and q.egress_id not in allowed:
                        failures.append("arrival_action_attribution_mismatch")
                if abs(q1 - (q0 + arrivals - departures - drops)) > Fraction(q.measurement_error_bytes):
                    failures.append("queue_conservation_failed")
                if q.measurement_error_bytes > bound.error_upper_bytes:
                    failures.append("sensor_error_not_covered")
                arrival = Fraction(bound.arrival_upper_bytes_per_second)
                service = Fraction(bound.service_lower_bytes_per_second)
                # Installation also verifies the weaker future-departure profile.
                # Retain the measured busy-period service diagnostic below.
                future_service = (Fraction(0) if runtime_projection and bound.service_lower_semantics == "busy-period-available"
                                  else service)
                upper = max(Fraction(0), q0 + (arrival - future_service) * dt) + Fraction(bound.error_upper_bytes)
                checks = {
                    "arrival": arrivals <= arrival * dt,
                    # v1: actual-departure lower guarantee, even for idle windows.
                    # v2 available service: only after full busy trace replay above.
                    "service": departures >= service * dt,
                    "capacity": departures <= Fraction(bound.capacity_bytes_per_second) * dt,
                    "service_upper": departures <= (Fraction(bound.service_upper_bytes_per_second) * dt
                                                     + Fraction(bound.service_upper_burst_bytes)),
                    "queue": q1 <= upper,
                    "envelope": max(q0, upper) <= Fraction(config.queue_threshold_bytes),
                }
                failures.extend(f"{name}_inequality_failed" for name, passed in checks.items() if not passed)
                before_v += q0 * q0 / 2
                upper_v += upper * upper / 2
                actual_v += q1 * q1 / 2
                detail = {"egress_id": q.egress_id, "q_next_upper_bytes": _outward(upper),
                          "actual_next_bytes": q.queue_after_bytes, "checks": checks}
                if config.schema_version.endswith(".v2"):
                    detail.update(service_lower_semantics=bound.service_lower_semantics,
                                  runtime_lower_bytes_per_second=float(future_service),
                                  service_upper_burst_bytes=bound.service_upper_burst_bytes,
                                  shaper_nominal_bytes_per_second=bound.shaper_nominal_bytes_per_second)
                details.append(detail)
            drift = upper_v - before_v
            if drift > Fraction(config.drift_budget_bytes_squared):
                failures.append("drift_budget_failed")
            if actual_v - before_v > drift:
                failures.append("actual_drift_exceeds_bound")
            reports.append({"sample_id": record.sample_id, "split": split,
                            "action_id": new, "previous_action_id": old,
                            "drift_upper_bytes_squared": _outward(drift), "queues": details,
                            "failures": sorted(set(failures)), "passed": not failures})
    for intervals in windows.values():
        ordered = sorted(intervals)
        if any(right[0] < left[1] for left, right in zip(ordered, ordered[1:])):
            raise EvidenceError("overlapping_capture_windows")
    # Different nominal group IDs do not make simultaneous runs independent.
    all_windows = sorted(interval for intervals in windows.values() for interval in intervals)
    if any(right[0] < left[1] for left, right in zip(all_windows, all_windows[1:])):
        raise EvidenceError("cross_group_measurement_windows_overlap")
    for split in ("train", "holdout"):
        if any(coverage.get((split, action), 0) < config.min_samples_per_action_per_split for action in actions):
            raise EvidenceError("action_split_coverage_incomplete")
        if any(not transitions.get((split, old, new), 0) for old, new in config.required_transitions):
            raise EvidenceError("transition_split_coverage_incomplete")
    holdout = [r for r in reports if r["split"] == "holdout"]
    return {
        "schema_version": "nanfo.network-independent-result.v1",
        "campaign_sha256": campaign.campaign_sha256, "protocol_sha256": campaign.protocol_sha256,
        "empirical_acceptance_passed": all(r["passed"] for r in reports),
        "holdout_coverage": sum(r["passed"] for r in holdout) / len(holdout),
        "guaranteed_physical_bound": False, "physical_qualified": False,
        "rows": reports,
        "limitations": ["Fixed preregistered bounds; observed departure minima are not service guarantees.",
                        "Endpoint checks do not establish intersample safety or unobserved counterfactuals.",
                        "A reviewed scoped guarantee and explicit trusted installation remain required."],
    }


def _scope_equal(left: CalibrationScope, right: CalibrationScope) -> bool:
    # Order-insensitive identity comparison; deliberately NOT a canonical-JSON digest
    # (ADR-028 C20 keeps divergent helpers explicitly named and local).
    def order_insensitive_scope(scope):
        value = scope.model_dump()
        for key in ("egress_ids", "demand_ids", "action_ids"):
            value[key] = sorted(value[key])
        return value
    return order_insensitive_scope(left) == order_insensitive_scope(right)


@dataclass(frozen=True)
class LoadedCalibration:
    calibration: TrustedCalibration
    scope: CalibrationScope
    installation_sha256: str
    physical_qualified: bool
    configuration: NetworkQualificationConfig

    def validate_action(
        self, action: SafetyAction, *, configuration_sha256: str,
        route_egress_ids: dict[str, list[str]], previous_action_id: str, now: float,
    ) -> None:
        """Receiver-side exact action/bound profile guard, in addition to SafetyShield.

        No dispatch authorization. `route_egress_ids` is server-owned policy path
        mapping, not client input. Check it under the same receiver lock as dispatch.
        """
        action = SafetyAction.model_validate(action)
        bound, scope, calibration = action.bounds, self.scope, self.calibration
        v2 = self.configuration.schema_version.endswith(".v2")
        if v2 and (bound.dt_seconds < self.configuration.min_dt_seconds
                   or bound.dt_seconds != self.configuration.dt_seconds):
            raise EvidenceError("action_horizon_differs_from_fixed_installation")
        profiles = {a.action_id: a for a in self.configuration.actions}
        if (type(now) not in (int, float) or not 0 <= now <= 1e15
                or action.action_id not in profiles or configuration_sha256 != scope.configuration_sha256
                or (previous_action_id, action.action_id) not in self.configuration.required_transitions
                or action.network_id != scope.network_id or action.run_id != scope.run_id
                or bound.network_id != action.network_id or bound.run_id != action.run_id
                or bound.snapshot_id != action.snapshot_id or bound.action_id != action.action_id
                or bound.provider_id != scope.provider_id or bound.calibration_id != calibration.calibration_id
                or not calibration.valid_from_unix_seconds <= now < calibration.valid_until_unix_seconds
                or not calibration.valid_from_unix_seconds <= bound.observed_at_unix_seconds <= now
                or bound.observed_at_unix_seconds + bound.dt_seconds > calibration.valid_until_unix_seconds
                or bound.dt_seconds > scope.max_dt_seconds
                or bound.actuation_delay_upper_seconds > scope.max_delay_seconds
                or Fraction(now) - Fraction(bound.observed_at_unix_seconds)
                   + Fraction(bound.actuation_delay_upper_seconds) >= Fraction(scope.max_delay_seconds)):
            raise EvidenceError("action_outside_installed_calibration_scope")
        expected = {b.egress_id: b for b in profiles[action.action_id].bounds}
        if (sorted(q.egress_id for q in bound.queues) != sorted(expected)
                or sorted(r.demand_id for r in action.routes) != sorted(scope.demand_ids)):
            raise EvidenceError("action_incomplete_installed_scope")
        attribution = profiles[action.action_id].demand_egress_ids
        if any(route_egress_ids.get(route.route_id) != attribution[route.demand_id] for route in action.routes):
            raise EvidenceError("action_routes_differ_from_reviewed_profile")
        for queue in bound.queues:
            profile = expected[queue.egress_id]
            lower, upper = runtime_service_bounds(self.configuration, profile, bound.dt_seconds)
            if (queue.arrival_upper_bytes_per_second != profile.arrival_upper_bytes_per_second
                    or queue.service_lower_bytes_per_second != lower
                    or queue.service_upper_bytes_per_second != upper
                    or queue.error_upper_bytes != profile.error_upper_bytes):
                raise EvidenceError("action_bounds_differ_from_reviewed_profile")


def load_trusted_calibration(
    store: ArtifactStore, installation_path: str, *, expected_installation_sha256: str,
    expected_scope: CalibrationScope, now: float,
    trusted_preregistrations: dict[str, float], trusted_attesters: set[str],
    accepted_guarantee_sha256: set[str],
    accepted_service_semantics_sha256=frozenset(),
    accepted_native_backlog_sha256=frozenset(),
) -> LoadedCalibration:
    """Reconstruct measurements on every load; trust inputs are server configuration.

    `trusted_attesters` contains externally verified ATTESTATION DIGESTS, not names.
    Runtime must retain and enforce returned action/config/horizon/environment scope.
    """
    import re

    if (not isinstance(expected_installation_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_installation_sha256)
            or type(now) not in (int, float) or not 0 <= now <= 1e15):
        raise EvidenceError("invalid_installation_pin_or_clock")
    expected_scope = CalibrationScope.model_validate(expected_scope)
    installation = CalibrationInstallation.model_validate(store.document(
        installation_path, sha256=expected_installation_sha256,
    ))
    if not _scope_equal(installation.scope, expected_scope):
        raise EvidenceError("installation_scope_mismatch")
    if installation.guarantee.sha256 not in accepted_guarantee_sha256:
        raise EvidenceError("bound_guarantee_not_explicitly_accepted")
    guarantee = BoundGuarantee.model_validate(parse_json(store.referenced(installation.guarantee)))
    if (not _scope_equal(guarantee.scope, expected_scope)
            or guarantee.campaign_sha256 != installation.campaign.sha256):
        raise EvidenceError("guarantee_scope_mismatch")
    for field in ("arrival_enforcement", "service_curve", "within_interval_dynamics",
                  "transition_and_delay", "complete_demand_attribution", "queue_sensor_error",
                  "capacity_and_scheduler", "environment_identity"):
        store.referenced(getattr(guarantee, field))
    campaign = import_campaign(store, installation.campaign,
                               trusted_preregistrations=trusted_preregistrations,
                               trusted_attesters=trusted_attesters)
    config = _config(campaign)
    p, scope, c = campaign.protocol, installation.scope, installation.calibration
    if (p.environment == "synthetic" or p.environment != scope.environment
            or p.network_id != scope.network_id or p.run_id != scope.run_id
            or p.configuration.sha256 != scope.configuration_sha256
            or config.provider_id != scope.provider_id
            or sorted(config.egress_ids) != sorted(scope.egress_ids)
            or sorted(config.demand_ids) != sorted(scope.demand_ids)
            or sorted(a.action_id for a in config.actions) != sorted(scope.action_ids)
            or config.dt_seconds != scope.max_dt_seconds
            or config.max_delay_seconds != scope.max_delay_seconds):
        raise EvidenceError("campaign_installation_scope_mismatch")
    if (c.network_id != scope.network_id or c.run_id != scope.run_id or c.provider_id != scope.provider_id
            or sorted(c.egress_ids) != sorted(scope.egress_ids)
            or sorted(c.demand_ids) != sorted(scope.demand_ids)):
        raise EvidenceError("trusted_calibration_scope_mismatch")
    if not (guarantee.valid_from_unix_seconds <= c.valid_from_unix_seconds <= now
            < c.valid_until_unix_seconds <= guarantee.valid_until_unix_seconds):
        raise EvidenceError("installation_expired_or_invalid_interval")
    report = verify_network_campaign(campaign, evidence_store=store,
        accepted_service_semantics_sha256=accepted_service_semantics_sha256,
        accepted_native_backlog_sha256=accepted_native_backlog_sha256)
    if config.schema_version.endswith(".v2"):
        runtime_report = verify_network_campaign(campaign, evidence_store=store,
            accepted_service_semantics_sha256=accepted_service_semantics_sha256,
            accepted_native_backlog_sha256=accepted_native_backlog_sha256, runtime_projection=True)
        if not runtime_report["empirical_acceptance_passed"]:
            raise EvidenceError("conservative_runtime_network_validation_failed")
    records = [r for capture in campaign.captures for r in capture.records]
    if max(campaign.attested_at_unix_seconds, *(r.measurement["end_unix_seconds"] for r in records)) > c.valid_from_unix_seconds:
        raise EvidenceError("installation_precedes_measurements")
    # Installation cannot reduce margins relative to the preregistered campaign.
    v2 = config.schema_version.endswith(".v2")
    invalid_uncertainty = (c.min_service_uncertainty_bytes_per_second != runtime_uncertainty_floor(config) if v2 else
        c.min_service_uncertainty_bytes_per_second < max(b.service_upper_bytes_per_second - b.service_lower_bytes_per_second
                                                        for a in config.actions for b in a.bounds))
    invalid_error = (c.min_error_upper_bytes != min(b.error_upper_bytes for a in config.actions for b in a.bounds) if v2 else
                     c.min_error_upper_bytes < max(b.error_upper_bytes for a in config.actions for b in a.bounds))
    if invalid_error or invalid_uncertainty:
        raise EvidenceError("installed_uncertainty_understates_campaign")
    if not report["empirical_acceptance_passed"]:
        raise EvidenceError("independent_network_validation_failed")
    return LoadedCalibration(
        calibration=c.model_copy(deep=True), scope=scope.model_copy(deep=True),
        installation_sha256=expected_installation_sha256,
        physical_qualified=scope.environment == "physical-network",
        configuration=config.model_copy(deep=True),
    )
