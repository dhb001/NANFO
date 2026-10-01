"""Adapter to the independent ADR023 validator owner's actual public interface."""

from datetime import UTC, datetime
from fractions import Fraction

from app.modules.autonomy.artifact_io import ArtifactStore
from app.modules.autonomy.calibration_verification import load_trusted_calibration, runtime_service_bounds, runtime_uncertainty_floor
from app.modules.autonomy.drivers import Capability, runtime_profile
from app.modules.autonomy.safety_provider import load_safety_installation


def validate_execution_binding(data, config):
    validate_service_profiles(data, config)
    reviewed = config.execution
    if reviewed is None or data.execution != reviewed or data.runtime_action != reviewed.runtime:
        raise ValueError("independent_execution_binding_missing_or_mismatched")
    if not 0 <= data.actuation_delay_upper_seconds <= data.policy.max_delay_seconds <= config.max_delay_seconds:
        raise ValueError("runtime_total_delay_exceeds_reviewed_envelope")
    profile = runtime_profile(data.runtime_action)
    for action in data.actions:
        plan = action.plan.model_dump(mode="json")
        for field in profile.plan_binding_fields:
            plan.pop(field)  # evidence-bound fields are validated with the runtime binding instead
        if plan != reviewed.plans.get(action.action_id):
            raise ValueError("executable_plan_differs_from_reviewed_calibration")
    paths = {p.route_id: p for p in data.policy.allowed_paths}
    profiles = {a.action_id: a for a in config.actions}
    for action in data.actions:
        for route in action.routes:
            path, demand = paths[route.route_id], reviewed.demands[route.demand_id]
            chain = profiles[action.action_id].demand_egress_ids[route.demand_id]
            if (path.egress_ids != chain or path.source != demand.source or path.destination != demand.destination):
                raise ValueError("reviewed_physical_route_mismatch")
            node = demand.source
            for key in chain:
                egress = reviewed.egresses[key]
                if egress.source != node:
                    raise ValueError("reviewed_physical_chain_disconnected")
                node = egress.destination
            if node != demand.destination:
                raise ValueError("reviewed_physical_chain_disconnected")


def validate_service_profiles(data, config):
    """Replay the versioned mapping at every existing receiver read checkpoint.

    Fixed installed horizon H is deliberate: each alternate horizon needs its own
    pinned installation/uncertainty. Measurement windows may range [h_min,H].
    v1 returns without changing its historical validation/serialization behavior.
    """
    v2 = config.schema_version.endswith(".v2")
    if v2 != data.version.endswith("/v2"):
        raise ValueError("installation_service_version_mismatch")
    if not v2:
        return
    if (data.min_dt_seconds != config.min_dt_seconds or data.dt_seconds != config.dt_seconds
            or data.dt_seconds < data.min_dt_seconds
            or data.service_semantics_evidence != config.service_semantics_evidence
            or data.service_semantics_evidence not in data.evidence
            or data.policy.queue_threshold_bytes != config.queue_threshold_bytes
            or data.policy.drift_budget_bytes_squared != config.drift_budget_bytes_squared):
        raise ValueError("v2_installed_service_scope_mismatch")
    profiles = {a.action_id: a for a in config.actions}
    if {a.action_id for a in data.actions} != set(profiles):
        raise ValueError("v2_installed_action_scope_mismatch")
    if (data.calibration.min_service_uncertainty_bytes_per_second != runtime_uncertainty_floor(config)
            or data.calibration.min_error_upper_bytes != min(b.error_upper_bytes for a in config.actions for b in a.bounds)):
        raise ValueError("v2_installed_uncertainty_floor_mismatch")
    for action in data.actions:
        expected = {b.egress_id: b for b in profiles[action.action_id].bounds}
        if {q.egress_id for q in action.queues} != set(expected):
            raise ValueError("v2_installed_queue_scope_mismatch")
        for q in action.queues:
            original = expected[q.egress_id]
            fields = ("arrival_upper_bytes_per_second", "service_lower_bytes_per_second",
                      "service_upper_bytes_per_second", "error_upper_bytes", "capacity_bytes_per_second",
                      "service_lower_semantics", "service_upper_burst_bytes", "shaper_nominal_bytes_per_second")
            if any(getattr(q, k) != getattr(original, k) for k in fields):
                raise ValueError("v2_original_service_profile_mismatch")
            lower, upper = runtime_service_bounds(config, original, data.dt_seconds)
            uncertainty = Fraction(upper) - Fraction(lower)
            if (uncertainty < Fraction(data.calibration.min_service_uncertainty_bytes_per_second)
                    or q.error_upper_bytes < data.calibration.min_error_upper_bytes):
                raise ValueError("v2_installed_uncertainty_not_representable")


class IndependentInstallationValidator:
    def __init__(self, loaded_calibration, *, runtime_trust=None):
        self.loaded = loaded_calibration
        self.runtime_trust = runtime_trust

    def validate(self, installation, evidence, *, sha256):
        loaded, data = self.loaded, installation
        config, scope = loaded.configuration, loaded.scope
        validate_execution_binding(data, config)
        if (scope.environment != "isolated-emulation" or data.calibration != loaded.calibration
                or data.configuration_sha256 != scope.configuration_sha256
                or data.dt_seconds != config.dt_seconds
                or data.policy.max_delay_seconds > scope.max_delay_seconds
                or data.policy.queue_threshold_bytes != config.queue_threshold_bytes
                or data.policy.drift_budget_bytes_squared != config.drift_budget_bytes_squared
                or set(data.transitions) != set(config.required_transitions)
                or {a.action_id for a in data.actions} != set(scope.action_ids)
                or loaded.installation_sha256 not in {ref.sha256 for ref in data.evidence}):
            raise ValueError("independent_installation_profile_mismatch")
        paths = {path.route_id: path for path in data.policy.allowed_paths}
        profiles = {action.action_id: action for action in config.actions}
        for action in data.actions:
            profile = profiles[action.action_id]
            if {r.demand_id: paths[r.route_id].egress_ids for r in action.routes} != profile.demand_egress_ids:
                raise ValueError("independent_route_attribution_mismatch")
            expected = {bound.egress_id: bound for bound in profile.bounds}
            for queue in action.queues:
                if any(getattr(queue, key) != getattr(expected[queue.egress_id], key) for key in (
                    "arrival_upper_bytes_per_second", "service_lower_bytes_per_second",
                    "service_upper_bytes_per_second", "error_upper_bytes", "capacity_bytes_per_second")):
                    raise ValueError("independent_action_bounds_mismatch")
        profile = runtime_profile(data.runtime_action)
        if profile.needs(Capability.RUNTIME_BINDING):
            if self.runtime_trust is None or profile.validate_runtime_binding is None:
                raise ValueError("independent_runtime_trust_missing")
            profile.validate_runtime_binding(data, evidence, **self.runtime_trust)
        return sha256


def load_independently_validated_safety(*, root, calibration_path, calibration_sha256,
        provider_path, provider_sha256, expected_scope, trusted_preregistrations,
        trusted_attesters, accepted_guarantee_sha256, accepted_runtime_sha256=frozenset(),
        accepted_equivalence_sha256=frozenset(), source_root=None,
        accepted_service_semantics_sha256=frozenset(), accepted_native_backlog_sha256=frozenset()):
    """All arguments are protected deployment configuration, never request fields."""
    from pathlib import Path

    loaded = load_trusted_calibration(ArtifactStore(root), calibration_path,
        expected_installation_sha256=calibration_sha256, expected_scope=expected_scope,
        now=datetime.now(UTC).timestamp(), trusted_preregistrations=trusted_preregistrations,
        trusted_attesters=trusted_attesters, accepted_guarantee_sha256=accepted_guarantee_sha256,
        accepted_service_semantics_sha256=accepted_service_semantics_sha256,
        accepted_native_backlog_sha256=accepted_native_backlog_sha256)
    # Provider document and referenced independent installation share the same root.
    if Path(provider_path).name != provider_path:
        raise ValueError("provider_installation_must_be_root_file")
    return load_safety_installation(Path(root) / provider_path, provider_sha256,
        IndependentInstallationValidator(loaded, runtime_trust=dict(
            accepted_runtime_sha256=accepted_runtime_sha256, accepted_equivalence_sha256=accepted_equivalence_sha256,
            store=ArtifactStore(root), source_root=source_root) if source_root is not None else None))
