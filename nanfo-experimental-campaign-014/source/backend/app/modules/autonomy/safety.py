"""ADR-012 conditional, one-step safety certificates; never authorizes dispatch.

Policy, calibration and state must be injected by trusted backend providers, not
constructed from API claims. No production calibration is installed by default.
See docs/architecture/SafetyModel.md for the model and trust obligations.
"""

from __future__ import annotations

import hashlib
import json
import math
from fractions import Fraction
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Nonnegative = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
Positive = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
Finite = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Identifier = Annotated[
    str, Field(strict=True, min_length=1, max_length=200, pattern=r"^\S+$")
]
Sequence = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
Digest = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]


class SafetyModel(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", revalidate_instances="always"
    )


class AllowedPath(SafetyModel):
    route_id: Identifier
    source: Identifier
    destination: Identifier
    egress_ids: Annotated[list[Identifier], Field(min_length=1, max_length=256)]


class DemandRoute(SafetyModel):
    demand_id: Identifier
    route_id: Identifier


class SafetyPolicy(SafetyModel):
    network_id: Identifier
    policy_version: Identifier
    queue_threshold_bytes: Positive
    max_dt_seconds: Positive
    max_observation_age_seconds: Positive
    max_delay_seconds: Positive
    min_dwell_seconds: Nonnegative
    rate_window_seconds: Positive
    max_actions_per_window: Annotated[int, Field(strict=True, gt=0, le=10000)]
    hysteresis_bytes_squared: Nonnegative = 0.0
    drift_budget_bytes_squared: Finite = 0.0
    allowed_paths: Annotated[list[AllowedPath], Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def unique_paths(self) -> Self:
        if len({p.route_id for p in self.allowed_paths}) != len(self.allowed_paths):
            raise ValueError("duplicate route identity")
        return self


class TrustedCalibration(SafetyModel):
    """Server-owned installation record, NOT a payload self-attestation flag."""

    calibration_id: Identifier
    provider_id: Identifier
    model_version: Literal["bounded-fluid-v1"]
    network_id: Identifier
    run_id: Identifier
    valid_from_unix_seconds: Nonnegative
    valid_until_unix_seconds: Positive
    egress_ids: Annotated[list[Identifier], Field(min_length=1, max_length=256)]
    demand_ids: Annotated[list[Identifier], Field(min_length=1, max_length=256)]
    min_error_upper_bytes: Nonnegative
    min_service_uncertainty_bytes_per_second: Nonnegative

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.valid_until_unix_seconds <= self.valid_from_unix_seconds:
            raise ValueError("empty calibration interval")
        for identities in (self.egress_ids, self.demand_ids):
            if len(set(identities)) != len(identities):
                raise ValueError("duplicate calibration scope")
        return self


class QueueObservation(SafetyModel):
    egress_id: Identifier
    source: Identifier
    destination: Identifier
    queue_bytes: Nonnegative
    capacity_bytes_per_second: Positive


class DemandObservation(SafetyModel):
    demand_id: Identifier
    source: Identifier
    destination: Identifier
    arrival_lower_bytes_per_second: Nonnegative
    arrival_upper_bytes_per_second: Nonnegative

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.arrival_lower_bytes_per_second > self.arrival_upper_bytes_per_second:
            raise ValueError("inverted demand bounds")
        return self


class SafetyObservation(SafetyModel):
    network_id: Identifier
    run_id: Identifier
    snapshot_id: Identifier
    sequence: Sequence
    observed_at_unix_seconds: Nonnegative
    counter_reset: bool
    attribution_complete: bool
    unknown_demand_ids: Annotated[list[Identifier], Field(max_length=256)]
    queues: Annotated[list[QueueObservation], Field(min_length=1, max_length=256)]
    demands: Annotated[list[DemandObservation], Field(min_length=1, max_length=256)]


class QueueBounds(SafetyModel):
    egress_id: Identifier
    arrival_lower_bytes_per_second: Nonnegative
    arrival_upper_bytes_per_second: Nonnegative
    service_lower_bytes_per_second: Nonnegative
    service_upper_bytes_per_second: Nonnegative
    error_upper_bytes: Nonnegative

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.arrival_lower_bytes_per_second > self.arrival_upper_bytes_per_second:
            raise ValueError("inverted arrival bounds")
        if self.service_lower_bytes_per_second > self.service_upper_bytes_per_second:
            raise ValueError("inverted service bounds")
        return self


class CandidateBounds(SafetyModel):
    network_id: Identifier
    run_id: Identifier
    snapshot_id: Identifier
    action_id: Identifier
    calibration_id: Identifier
    provider_id: Identifier
    model_version: Literal["bounded-fluid-v1"]
    policy_version: Identifier
    input_sha256: Digest
    observed_at_unix_seconds: Nonnegative
    valid_until_unix_seconds: Positive
    dt_seconds: Positive
    actuation_delay_upper_seconds: Nonnegative
    queues: Annotated[list[QueueBounds], Field(min_length=1, max_length=256)]


class SafetyAction(SafetyModel):
    action_id: Identifier
    network_id: Identifier
    run_id: Identifier
    snapshot_id: Identifier
    routes: Annotated[list[DemandRoute], Field(min_length=1, max_length=256)]
    bounds: CandidateBounds


class SafetyState(SafetyModel):
    """Fresh, durable executor history, independent of candidate/model evidence."""

    network_id: Identifier
    run_id: Identifier
    snapshot_id: Identifier
    observed_at_unix_seconds: Nonnegative
    last_evaluated_sequence: Sequence
    active_routes: Annotated[list[DemandRoute], Field(min_length=1, max_length=256)]
    route_since_unix_seconds: Nonnegative
    history_complete_since_unix_seconds: Nonnegative
    last_applied_at_unix_seconds: Nonnegative | None
    recent_dispatch_at_unix_seconds: Annotated[
        list[Nonnegative], Field(max_length=10000)
    ]


class EvaluationClock(SafetyModel):
    now: Nonnegative


def safety_input_digest(
    observation: SafetyObservation | dict,
    routes: list[DemandRoute | dict],
) -> str:
    """Bind validated provider inputs; a digest is NOT provider authentication."""
    obs = SafetyObservation.model_validate(observation)
    assignments = [DemandRoute.model_validate(route) for route in routes]
    payload = {
        "observation": obs.model_dump(mode="json"),
        "routes": [
            route.model_dump(mode="json")
            for route in sorted(assignments, key=lambda r: (r.demand_id, r.route_id))
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _upper_float(value: Fraction) -> float:
    """Outward rounding keeps serialized evidence conservative, including drift."""
    result = float(value)
    if Fraction(result) < value:
        result = math.nextafter(result, math.inf)
    if not math.isfinite(result):
        raise OverflowError("certificate not representable")
    return result


class SafetyShield:
    """Pure evaluation; caller owns authentication, persistence and actuation locks."""

    def __init__(
        self,
        policy: SafetyPolicy | dict | None = None,
        calibration: TrustedCalibration | dict | None = None,
    ) -> None:
        # Validate and copy even existing model instances; retain no caller aliases.
        self._policy = (
            SafetyPolicy.model_validate(policy).model_copy(deep=True)
            if policy is not None
            else None
        )
        self._calibration = (
            TrustedCalibration.model_validate(calibration).model_copy(deep=True)
            if calibration is not None
            else None
        )

    def evaluate(
        self,
        observation: SafetyObservation | dict | None,
        proposed_action: SafetyAction | dict | None,
        alternatives: list[SafetyAction | dict] | None = None,
        *,
        state: SafetyState | dict | None = None,
        now: float,
    ) -> dict:
        """Return JSON-safe decision/evidence; rejection never mutates rate/dwell state.

        Decisions: accept, project, no_dispatch. All candidates are evaluated;
        alternatives are projected in lexicographic action_id order, not input order.
        A certificate is conditional evidence, not dispatch authorization.
        """
        result = {
            "decision": "no_dispatch",
            "selected_action": None,
            "reason": "safety_unavailable",
            "checks": [],
            "certificate": None,
            "validity": {"valid": False, "conditional": True},
            "expires_at_unix_seconds": None,
            "drift": None,
            "envelope": None,
            "guidance": "Do not dispatch; reconcile evidence or seek operator review. "
            "Holding is not certified safe.",
        }
        p, c = self._policy, self._calibration
        if p is None or c is None:
            result["reason"] = "trusted_policy_or_calibration_unavailable"
            return result
        try:
            clock = EvaluationClock(now=now)
            obs = SafetyObservation.model_validate(observation)
            history = SafetyState.model_validate(state)
        except ValidationError:
            result["reason"] = "invalid_observation_state_or_clock"
            return result
        now = clock.now
        queues = {q.egress_id: q for q in obs.queues}
        demands = {d.demand_id: d for d in obs.demands}
        paths = {path.route_id: path for path in p.allowed_paths}
        active = {r.demand_id: r.route_id for r in history.active_routes}
        common = []
        if not (p.network_id == c.network_id == obs.network_id == history.network_id):
            common.append("network_mismatch")
        if c.run_id != obs.run_id or history.run_id != obs.run_id:
            common.append("run_mismatch")
        if (
            history.snapshot_id != obs.snapshot_id
            or history.observed_at_unix_seconds != obs.observed_at_unix_seconds
        ):
            common.append("state_snapshot_mismatch")
        age = Fraction(now) - Fraction(obs.observed_at_unix_seconds)
        if age < 0 or age >= Fraction(p.max_observation_age_seconds):
            common.append("future_or_stale_observation")
        if (
            not c.valid_from_unix_seconds
            <= obs.observed_at_unix_seconds
            <= now
            < c.valid_until_unix_seconds
        ):
            common.append("calibration_expired_or_not_yet_valid")
        if obs.counter_reset or obs.sequence <= history.last_evaluated_sequence:
            common.append("reset_or_replayed_snapshot")
        if not obs.attribution_complete or obs.unknown_demand_ids:
            common.append("unknown_demand_attribution")
        if (
            len(queues) != len(obs.queues)
            or set(queues) != set(c.egress_ids)
            or len(demands) != len(obs.demands)
            or set(demands) != set(c.demand_ids)
        ):
            common.append("incomplete_or_duplicate_scope")
        if (
            len(active) != len(history.active_routes)
            or set(active) != set(demands)
            or any(route not in paths for route in active.values())
        ):
            common.append("invalid_active_routes")
        times = history.recent_dispatch_at_unix_seconds
        last = history.last_applied_at_unix_seconds
        start = history.history_complete_since_unix_seconds
        if (
            Fraction(start) > Fraction(now) - Fraction(p.rate_window_seconds)
            or history.route_since_unix_seconds > obs.observed_at_unix_seconds
            or any(t < start or t > obs.observed_at_unix_seconds for t in times)
            or times != sorted(set(times))
            or (last is None and bool(times))
            or (
                last is not None
                and (
                    last > obs.observed_at_unix_seconds
                    or last < history.route_since_unix_seconds
                    or (last >= start and (not times or times[-1] != last))
                    or (last < start and bool(times))
                )
            )
        ):
            common.append("invalid_or_incomplete_action_history")
        if (
            sum(
                Fraction(now) - Fraction(t) < Fraction(p.rate_window_seconds)
                for t in times
            )
            >= p.max_actions_per_window
        ):
            common.append("action_rate_limited")
        if common:
            result["reason"] = common[0]
            result["checks"] = [
                {"action_id": None, "passed": False, "blockers": common}
            ]
            return result
        if alternatives is not None and (
            not isinstance(alternatives, list) or len(alternatives) > 255
        ):
            result["reason"] = "invalid_alternatives"
            return result
        candidates = []
        for index, raw in enumerate([proposed_action, *(alternatives or [])]):
            try:
                candidate = SafetyAction.model_validate(raw)
                candidates.append((index, candidate))
            except ValidationError:
                result["checks"].append(
                    {
                        "action_id": None,
                        "candidate_index": index,
                        "passed": False,
                        "blockers": ["invalid_candidate"],
                        "certificate": None,
                    }
                )
        ids = [a.action_id for _, a in candidates]
        if len(set(ids)) != len(ids):
            result["reason"] = "duplicate_action_identity"
            return result
        evaluated = []
        exact_next_v = {}
        for index, action in sorted(candidates, key=lambda item: item[1].action_id):
            b = action.bounds
            blockers = []
            certificate = None
            routes = {r.demand_id: r.route_id for r in action.routes}
            bounds = {q.egress_id: q for q in b.queues}
            if (
                any(
                    getattr(action, key) != getattr(obs, key)
                    or getattr(b, key) != getattr(obs, key)
                    for key in ("network_id", "run_id", "snapshot_id")
                )
                or b.action_id != action.action_id
            ):
                blockers.append("candidate_identity_mismatch")
            if (
                b.calibration_id != c.calibration_id
                or b.provider_id != c.provider_id
                or b.model_version != c.model_version
                or b.policy_version != p.policy_version
                or b.observed_at_unix_seconds != obs.observed_at_unix_seconds
            ):
                blockers.append("uncorrelated_bounds")
            if b.input_sha256 != safety_input_digest(obs, action.routes):
                blockers.append("bound_input_mismatch")
            if len(routes) != len(action.routes) or set(routes) != set(demands):
                blockers.append("incomplete_or_duplicate_demand_routes")
            if len(bounds) != len(b.queues) or set(bounds) != set(queues):
                blockers.append("incomplete_or_duplicate_queue_bounds")
            t0, dt = Fraction(obs.observed_at_unix_seconds), Fraction(b.dt_seconds)
            delay = Fraction(b.actuation_delay_upper_seconds)
            end = t0 + dt
            expires = min(
                t0 + Fraction(p.max_observation_age_seconds),
                t0 + Fraction(p.max_delay_seconds) - delay,
                end - delay,
            )
            if (
                dt > Fraction(p.max_dt_seconds)
                or Fraction(now) >= expires
                or end > Fraction(b.valid_until_unix_seconds)
                or end > Fraction(c.valid_until_unix_seconds)
            ):
                blockers.append("invalid_horizon_or_excessive_delay")
            attributed = {key: Fraction(0) for key in queues}
            for demand_id, route_id in routes.items():
                path, demand = paths.get(route_id), demands.get(demand_id)
                if path is None or demand is None:
                    blockers.append("path_not_allowed")
                    continue
                node = path.source
                visited = {node}
                connected = (
                    path.source == demand.source
                    and path.destination == demand.destination
                )
                for key in path.egress_ids:
                    queue = queues.get(key)
                    if (
                        queue is None
                        or queue.source != node
                        or queue.destination in visited
                    ):
                        connected = False
                        break
                    node = queue.destination
                    visited.add(node)
                    attributed[key] += Fraction(demand.arrival_upper_bytes_per_second)
                if not connected or node != path.destination:
                    blockers.append("path_disconnected_or_cyclic")
            if not blockers:
                for key, bound in bounds.items():
                    if (
                        bound.service_upper_bytes_per_second
                        > queues[key].capacity_bytes_per_second
                        or Fraction(bound.service_upper_bytes_per_second)
                        - Fraction(bound.service_lower_bytes_per_second)
                        < Fraction(c.min_service_uncertainty_bytes_per_second)
                        or bound.error_upper_bytes < c.min_error_upper_bytes
                    ):
                        blockers.append("capacity_or_calibrated_uncertainty_violation")
                    if Fraction(bound.arrival_upper_bytes_per_second) < attributed[key]:
                        blockers.append("understated_attributed_arrivals")
            if not blockers:
                # Exact rational arithmetic over validated IEEE values avoids false
                # acceptance through overflow, cancellation or downward rounding.
                q = {key: Fraction(value.queue_bytes) for key, value in queues.items()}
                upper = {
                    key: max(
                        Fraction(0),
                        q[key]
                        + (
                            Fraction(bound.arrival_upper_bytes_per_second)
                            - Fraction(bound.service_lower_bytes_per_second)
                        )
                        * dt,
                    )
                    + Fraction(bound.error_upper_bytes)
                    for key, bound in bounds.items()
                }
                before = sum(value * value for value in q.values()) / 2
                after = sum(value * value for value in upper.values()) / 2
                exact_next_v[action.action_id] = after
                drift = after - before
                threshold = Fraction(p.queue_threshold_bytes)
                if any(value > threshold for value in q.values()):
                    blockers.append("initial_envelope_violated")
                if any(value > threshold for value in upper.values()):
                    blockers.append("next_envelope_violated")
                if drift > Fraction(p.drift_budget_bytes_squared):
                    blockers.append("drift_budget_exceeded")
                try:
                    certificate = {
                        "model": c.model_version,
                        "calibration_id": c.calibration_id,
                        "provider_id": c.provider_id,
                        "policy_version": p.policy_version,
                        "input_sha256": b.input_sha256,
                        "network_id": obs.network_id,
                        "run_id": obs.run_id,
                        "snapshot_id": obs.snapshot_id,
                        "action_id": action.action_id,
                        "routes": [
                            route.model_dump(mode="json") for route in action.routes
                        ],
                        "conditional": True,
                        "observed_at_unix_seconds": obs.observed_at_unix_seconds,
                        "horizon_end_unix_seconds": _upper_float(end),
                        "dt_seconds": b.dt_seconds,
                        "actuation_delay_upper_seconds": b.actuation_delay_upper_seconds,
                        # Round expiry inward: it must never extend the valid window.
                        "expires_at_unix_seconds": -_upper_float(-expires),
                        "drift": {
                            "v_before_bytes_squared": _upper_float(before),
                            "v_next_upper_bytes_squared": _upper_float(after),
                            "upper_bytes_squared": _upper_float(drift),
                            "budget_bytes_squared": p.drift_budget_bytes_squared,
                        },
                        "envelope": {
                            "threshold_bytes": p.queue_threshold_bytes,
                            "q_next_upper_bytes": {
                                key: _upper_float(value) for key, value in upper.items()
                            },
                        },
                        "model_checks_passed": not blockers,
                    }
                except (OverflowError, ValueError):
                    blockers.append("nonrepresentable_certificate")
                if (
                    certificate is not None
                    and now >= certificate["expires_at_unix_seconds"]
                ):
                    blockers.append("certificate_expired")
            changed = routes != active
            if changed and Fraction(now) - Fraction(
                history.route_since_unix_seconds
            ) < Fraction(p.min_dwell_seconds):
                blockers.append("minimum_dwell_not_elapsed")
            check = {
                "action_id": action.action_id,
                "candidate_index": index,
                "passed": not blockers,
                "blockers": blockers,
                "certificate": certificate,
            }
            evaluated.append((index, action, check, changed))
        incumbent = next(
            (
                action
                for _, action, check, changed in evaluated
                if not changed
                and check["certificate"] is not None
                and "certificate_expired" not in check["blockers"]
            ),
            None,
        )
        for _, action, check, changed in evaluated:
            if changed and p.hysteresis_bytes_squared > 0:
                candidate_cert = check["certificate"]
                # Compare exact envelopes, not rounded serialized Lyapunov values.
                if incumbent is None or candidate_cert is None:
                    check["blockers"].append("hysteresis_baseline_unavailable")
                else:
                    improvement = (
                        exact_next_v[incumbent.action_id]
                        - exact_next_v[action.action_id]
                    )
                    if incumbent.bounds.dt_seconds != action.bounds.dt_seconds:
                        check["blockers"].append("hysteresis_horizon_mismatch")
                    elif improvement < Fraction(p.hysteresis_bytes_squared):
                        check["blockers"].append("hysteresis_margin_not_met")
                check["passed"] = not check["blockers"]
            result["checks"].append(check)
        admissible = [entry for entry in evaluated if entry[2]["passed"]]
        if not admissible:
            result["reason"] = "no_admissible_candidate"
            return result
        index, action, check, _ = min(
            admissible, key=lambda entry: (entry[0] != 0, entry[1].action_id)
        )
        cert = check["certificate"]
        result.update(
            {
                "decision": "accept" if index == 0 else "project",
                "selected_action": action.model_dump(mode="json"),
                "reason": "proposed_candidate_certified"
                if index == 0
                else "admissible_alternative_selected",
                "certificate": cert,
                "validity": {"valid": True, "conditional": True},
                "expires_at_unix_seconds": cert["expires_at_unix_seconds"],
                "drift": cert["drift"],
                "envelope": cert["envelope"],
                "guidance": "Recheck certificate expiry, trusted evidence and separate authorization "
                "under the executor lock before dispatch.",
            }
        )
        return result
