"""Concrete server-installed action-specific calibrated bounds and safety shield."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, model_serializer, model_validator

from app.modules.autonomy.artifact_io import ArtifactRef, ArtifactStore, parse_json
from app.modules.autonomy.provider_state import ProviderStateRepository
from app.modules.autonomy.frr_contract import FRRPlan
from app.modules.autonomy.calibration_verification_models import ExecutionBinding
from app.modules.autonomy.calibration_verification import runtime_service_bounds
from app.modules.autonomy.safety import (
    CandidateBounds, DemandRoute, Nonnegative, Positive, QueueBounds, SafetyAction,
    SafetyPolicy, SafetyShield, TrustedCalibration, safety_input_digest,
)
from app.modules.autonomy.schemas import (
    SHA256, Contract, ProviderStatus, SafetyAssessment, SafetyBinding, contract_digest,
)
from app.modules.intent.lab import LabPlan


class CalibratedQueue(Contract):
    egress_id: str = Field(min_length=1, max_length=200)
    service_lower_bytes_per_second: Nonnegative
    service_upper_bytes_per_second: Nonnegative
    error_upper_bytes: Nonnegative
    arrival_upper_bytes_per_second: Nonnegative
    capacity_bytes_per_second: Positive


class CalibratedQueueV2(CalibratedQueue):
    # Preserve original reviewed profile, NOT an inflated nominal shaping rate.
    service_lower_semantics: Literal["actual-departures", "busy-period-available"]
    service_upper_burst_bytes: Nonnegative
    shaper_nominal_bytes_per_second: Positive | None


class InstalledAction(Contract):
    action_id: str = Field(min_length=1, max_length=128)
    routes: list[DemandRoute] = Field(min_length=1, max_length=256)
    queues: list[CalibratedQueueV2 | CalibratedQueue] = Field(min_length=1, max_length=256)
    plan: LabPlan | FRRPlan


class SafetyInstallation(Contract):
    version: Literal["nanfo.calibrated-safety/v1", "nanfo.calibrated-safety/v2"]
    runtime_action: Literal["isolated-ovs-autonomous/v1", "isolated-linux-frr-host-route/v1"]
    runtime_binding: ArtifactRef | None = None
    execution: ExecutionBinding | None = None
    workspace_id: uuid.UUID
    network_id: uuid.UUID
    observation_contract: str = Field(min_length=1, max_length=200)
    configuration_sha256: SHA256
    checkpoints: list[SHA256] = Field(min_length=1, max_length=32)
    policy: SafetyPolicy
    calibration: TrustedCalibration
    dt_seconds: Positive
    actuation_delay_upper_seconds: Nonnegative
    actions: list[InstalledAction] = Field(min_length=1, max_length=256)
    transitions: list[tuple[str, str]] = Field(min_length=1, max_length=1000)
    evidence: list[ArtifactRef] = Field(min_length=1, max_length=100)
    min_dt_seconds: Positive | None = None
    service_semantics_evidence: ArtifactRef | None = None

    @model_serializer(mode="wrap")
    def preserve_v1_shape(self, handler):
        result = handler(self)
        if self.version.endswith("/v1"):
            result.pop("min_dt_seconds", None)
            result.pop("service_semantics_evidence", None)
        return result

    @model_validator(mode="after")
    def scope(self):
        v2 = self.version.endswith("/v2")
        if v2:
            if (self.min_dt_seconds is None or self.min_dt_seconds > self.dt_seconds
                    or self.service_semantics_evidence is None
                    or self.service_semantics_evidence not in self.evidence):
                raise ValueError("v2_installed_horizon_and_source_required")
        elif self.min_dt_seconds is not None or self.service_semantics_evidence is not None:
            raise ValueError("v2_installation_fields_require_explicit_version")
        if any(isinstance(q, CalibratedQueueV2) != v2 for a in self.actions for q in a.queues):
            raise ValueError("installed_queue_profile_version_mismatch")
        if self.policy.network_id != str(self.network_id) or self.calibration.network_id != str(self.network_id):
            raise ValueError("installation_scope_mismatch")
        if len({a.action_id for a in self.actions}) != len(self.actions):
            raise ValueError("duplicate_installed_action")
        ids = {a.action_id for a in self.actions}
        if any(old not in ids or new not in ids for old, new in self.transitions):
            raise ValueError("transition_action_not_installed")
        from app.modules.autonomy.drivers import Capability, runtime_profile

        profile = runtime_profile(self.runtime_action)
        bound = profile.needs(Capability.RUNTIME_BINDING)
        for action in self.actions:
            if not isinstance(action.plan, profile.plan_type):
                raise ValueError("runtime_plan_discriminator_mismatch")
            if bound and (self.runtime_binding is None or any(
                    getattr(action.plan, field) != self.runtime_binding.sha256 for field in profile.plan_binding_fields)):
                raise ValueError("runtime_evidence_required")
            if (len({q.egress_id for q in action.queues}) != len(action.queues)
                    or {q.egress_id for q in action.queues} != set(self.calibration.egress_ids)
                    or {r.demand_id for r in action.routes} != set(self.calibration.demand_ids)
                    or len(action.routes) != len(self.calibration.demand_ids)):
                raise ValueError("incomplete_calibrated_action")
        if not bound and self.runtime_binding is not None:
            raise ValueError("runtime_binding_not_supported")
        return self


class InstallationValidator(Protocol):
    def validate(self, installation: SafetyInstallation, evidence: dict[str, bytes], *, sha256: str) -> str:
        """Independently validate raw/preregistered evidence and exact plan/route mapping.

        Return sha256 only on authentic scoped bounded-fluid qualification; a report's
        self-assertion or statistical coverage alone cannot satisfy this interface.
        """
        ...


@dataclass(frozen=True)
class ValidatedInstallation:
    # Retain immutable bytes; callers receive detached validated instances.
    content: bytes
    sha256: str
    reviewed_configuration: bytes | None = None

    def assert_reviewed_execution(self):
        from app.modules.autonomy.calibration_verification_models import NetworkQualificationConfig
        from app.modules.autonomy.safety_installation import validate_execution_binding
        if self.reviewed_configuration is None:
            raise ValueError("independent_execution_binding_missing")
        config = NetworkQualificationConfig.model_validate_json(self.reviewed_configuration)
        validate_execution_binding(self.data, config)

    def service_bounds(self, queue, horizon):
        data = self.data
        if data.version.endswith("/v1"):
            return queue.service_lower_bytes_per_second, queue.service_upper_bytes_per_second
        from app.modules.autonomy.calibration_verification_models import NetworkQualificationConfig
        self.assert_reviewed_execution()
        config = NetworkQualificationConfig.model_validate_json(self.reviewed_configuration)
        if horizon != data.dt_seconds or horizon < data.min_dt_seconds:
            raise ValueError("action_horizon_differs_from_fixed_installation")
        return runtime_service_bounds(config, queue, horizon)

    @property
    def data(self):
        return SafetyInstallation.model_validate(parse_json(self.content))

    def action(self, action_id):
        for action in self.data.actions:
            if action.action_id == action_id:
                return action
        raise ValueError("action_not_installed")


def load_safety_installation(path, expected_sha256, validator: InstallationValidator):
    path = Path(path)
    store = ArtifactStore(str(path.parent))
    content = store.read(path.name, sha256=expected_sha256)
    data = SafetyInstallation.model_validate(parse_json(content))
    evidence = {ref.path: store.read(ref.path, sha256=ref.sha256, size_bytes=ref.size_bytes)
                for ref in data.evidence}
    if data.runtime_binding is not None:
        ref = data.runtime_binding
        evidence[ref.path] = store.read(ref.path, sha256=ref.sha256, size_bytes=ref.size_bytes)
    digest = hashlib.sha256(content).hexdigest()
    if validator.validate(data, evidence, sha256=digest) != digest:
        raise ValueError("independent_calibration_validation_failed")
    loaded = getattr(validator, "loaded", None)
    reviewed = loaded.configuration.model_dump_json().encode() if loaded is not None else None
    return ValidatedInstallation(content, digest, reviewed)


class CalibratedSafetyProvider:
    def __init__(self, sessions, installation: ValidatedInstallation):
        self.sessions, self.installation = sessions, installation

    @property
    def status(self):
        data = self.installation.data
        valid = data.calibration.valid_from_unix_seconds <= datetime.now(UTC).timestamp() < data.calibration.valid_until_unix_seconds
        return ProviderStatus(provider_id=data.calibration.provider_id, status="ready" if valid else "uncalibrated",
                              reasons=[] if valid else ["calibration_expired_or_not_yet_valid"])

    def evaluate(self, observation, proposal, obs, state, *, now):
        data = self.installation.data
        if (observation.network_id != data.network_id or observation.workspace_id != data.workspace_id
                or observation.contract != data.observation_contract or proposal.observation_contract != observation.contract
                or proposal.checkpoint_sha256 not in data.checkpoints or not observation.compatible
                or not observation.fresh or not observation.evidence or observation.observed_at is None
                or obs.observed_at_unix_seconds != observation.observed_at.timestamp()):
            raise ValueError("calibrated_observation_scope_mismatch")
        installed = self.installation.action(proposal.action_id)
        active = {(r.demand_id, r.route_id) for r in state.active_routes}
        previous = [a.action_id for a in data.actions if {(r.demand_id, r.route_id) for r in a.routes} == active]
        if len(previous) != 1 or (previous[0], installed.action_id) not in data.transitions:
            raise ValueError("uncalibrated_action_transition")
        paths = {p.route_id: p for p in data.policy.allowed_paths}
        demands = {d.demand_id: d for d in obs.demands}
        observed_queues = {q.egress_id: q for q in obs.queues}
        if data.execution is not None:
            for q in obs.queues:
                physical = data.execution.egresses.get(q.egress_id)
                if physical is None or (q.source, q.destination) != (physical.source, physical.destination):
                    raise ValueError("observation_physical_egress_mismatch")
            for demand in obs.demands:
                physical = data.execution.demands.get(demand.demand_id)
                if physical is None or (demand.source, demand.destination) != (physical.source, physical.destination):
                    raise ValueError("observation_physical_demand_mismatch")
        queues = []
        for q in installed.queues:
            if observed_queues[q.egress_id].capacity_bytes_per_second != q.capacity_bytes_per_second:
                raise ValueError("queue_capacity_outside_calibration")
            attributed = sum(
                demands[r.demand_id].arrival_upper_bytes_per_second for r in installed.routes
                if q.egress_id in paths[r.route_id].egress_ids)
            if attributed > q.arrival_upper_bytes_per_second:
                raise ValueError("measured_arrivals_exceed_installed_profile")
            lower, upper = self.installation.service_bounds(q, data.dt_seconds)
            queues.append(QueueBounds(egress_id=q.egress_id, arrival_lower_bytes_per_second=0.0,
                arrival_upper_bytes_per_second=q.arrival_upper_bytes_per_second, service_lower_bytes_per_second=lower,
                service_upper_bytes_per_second=upper, error_upper_bytes=q.error_upper_bytes))
        bounds = CandidateBounds(network_id=obs.network_id, run_id=obs.run_id, snapshot_id=obs.snapshot_id,
            action_id=installed.action_id, calibration_id=data.calibration.calibration_id,
            provider_id=data.calibration.provider_id, model_version=data.calibration.model_version,
            policy_version=data.policy.policy_version, input_sha256=safety_input_digest(obs, installed.routes),
            observed_at_unix_seconds=obs.observed_at_unix_seconds,
            valid_until_unix_seconds=data.calibration.valid_until_unix_seconds,
            dt_seconds=data.dt_seconds, actuation_delay_upper_seconds=data.actuation_delay_upper_seconds, queues=queues)
        action = SafetyAction(action_id=installed.action_id, network_id=obs.network_id, run_id=obs.run_id,
                              snapshot_id=obs.snapshot_id, routes=installed.routes, bounds=bounds)
        result = SafetyShield(data.policy, data.calibration).evaluate(obs, action, state=state, now=now)
        if result["decision"] != "accept":
            return SafetyAssessment(admissible=False, model_version=data.calibration.model_version,
                                    reasons=[result["reason"]])
        binding = SafetyBinding(workspace_id=data.workspace_id, observation_sha256=contract_digest(observation),
            proposal_sha256=contract_digest(proposal), calibration_sha256=contract_digest(data.calibration),
            selected_action_sha256=contract_digest(action), evaluated_at_unix_seconds=now,
            observation=obs, policy=data.policy, calibration=data.calibration, state=state)
        return SafetyAssessment(admissible=True, action_id=action.action_id, model_version=data.calibration.model_version,
            selected_action=action, certificate=result["certificate"], binding=binding,
            evidence=["calibration_installation:" + self.installation.sha256,
                      *("calibration_evidence:" + ref.sha256 for ref in data.evidence)][:100])

    async def assess(self, observation, proposal):
        try:
            async with self.sessions() as db:
                obs, state = await ProviderStateRepository(db).inputs(observation, self.installation)
            return self.evaluate(observation, proposal, obs, state, now=datetime.now(UTC).timestamp())
        except (ValueError, KeyError):
            return SafetyAssessment(admissible=False, model_version="bounded-fluid-v1",
                                    reasons=["calibrated_inputs_unavailable_or_incompatible"])
