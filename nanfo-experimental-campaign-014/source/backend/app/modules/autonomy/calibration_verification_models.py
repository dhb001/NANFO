"""Exact offline ADR023 calibration installation and measurement schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_serializer, model_validator

from app.modules.autonomy.artifact_io import SHA256, ArtifactRef, StrictEvidence
from app.modules.autonomy.safety import TrustedCalibration
from app.modules.simulation.qualification_protocol import Amount, Name, Positive


class CalibrationScope(StrictEvidence):
    network_id: Name
    run_id: Name
    provider_id: Name
    environment: Literal["isolated-emulation", "physical-network"]
    configuration_sha256: SHA256
    egress_ids: list[Name] = Field(min_length=1, max_length=256)
    demand_ids: list[Name] = Field(min_length=1, max_length=256)
    action_ids: list[Name] = Field(min_length=1, max_length=256)
    max_dt_seconds: Positive
    max_delay_seconds: Amount

    @model_validator(mode="after")
    def unique_scope(self):
        for values in (self.egress_ids, self.demand_ids, self.action_ids):
            if len(values) != len(set(values)):
                raise ValueError("duplicate_scope")
        if self.max_delay_seconds >= self.max_dt_seconds:
            raise ValueError("delay_exceeds_horizon")
        return self


class EgressBound(StrictEvidence):
    egress_id: Name
    capacity_bytes_per_second: Positive
    arrival_upper_bytes_per_second: Amount
    service_lower_bytes_per_second: Amount
    service_upper_bytes_per_second: Amount
    error_upper_bytes: Amount
    # v1 means actual departures, including idle windows; NOT available service.
    service_lower_semantics: Literal["actual-departures", "busy-period-available"] = "actual-departures"
    service_upper_burst_bytes: Amount = 0.0
    # Metadata distinct from independent physical/queue-boundary capacity.
    shaper_nominal_bytes_per_second: Positive | None = None

    @model_validator(mode="after")
    def ordered(self):
        if not self.service_lower_bytes_per_second <= self.service_upper_bytes_per_second <= self.capacity_bytes_per_second:
            raise ValueError("invalid_service_bounds")
        return self


class ActionEnvelope(StrictEvidence):
    action_id: Name
    # Egress attribution includes all traversed egresses, not just final delivery.
    demand_egress_ids: dict[Name, list[Name]]
    bounds: list[EgressBound] = Field(min_length=1, max_length=256)


class PhysicalEgress(StrictEvidence):
    node: Name
    interface: Name
    queue_handle: Name
    source: Name
    destination: Name


class PhysicalDemand(StrictEvidence):
    source: Name
    destination: Name
    source_node: Name
    destination_node: Name
    source_address: Name
    destination_address: Name


class ExecutionBinding(StrictEvidence):
    version: Literal["nanfo.reviewed-execution/v1"]
    runtime: Literal["isolated-ovs-autonomous/v1", "isolated-linux-frr-host-route/v1"]
    plans: dict[Name, dict] = Field(min_length=1, max_length=256)
    egresses: dict[Name, PhysicalEgress] = Field(min_length=1, max_length=256)
    demands: dict[Name, PhysicalDemand] = Field(min_length=1, max_length=256)


class NetworkQualificationConfig(StrictEvidence):
    schema_version: Literal["nanfo.network-qualification-config.v1", "nanfo.network-qualification-config.v2"]
    provider_id: Name
    egress_ids: list[Name] = Field(min_length=1, max_length=256)
    demand_ids: list[Name] = Field(min_length=1, max_length=256)
    actions: list[ActionEnvelope] = Field(min_length=1, max_length=256)
    queue_units: Literal["bytes"]
    rate_units: Literal["bytes/second"]
    time_units: Literal["unix-seconds"]
    dt_seconds: Positive
    max_delay_seconds: Amount
    queue_threshold_bytes: Positive
    drift_budget_bytes_squared: float
    min_samples_per_action_per_split: int = Field(ge=2, le=10000)
    # All directed old/new transitions to test, including hold where allowed.
    required_transitions: list[tuple[Name, Name]] = Field(min_length=1, max_length=1000)
    execution: ExecutionBinding | None = None
    min_dt_seconds: Positive | None = None
    # External review must accept this exact source/hierarchy/accounting derivation.
    service_semantics_evidence: ArtifactRef | None = None

    @model_serializer(mode="wrap")
    def preserve_v1_configuration(self, handler):
        result = handler(self)
        if self.schema_version.endswith(".v1"):
            result.pop("min_dt_seconds", None)
            result.pop("service_semantics_evidence", None)
            for action in result["actions"]:
                for bound in action["bounds"]:
                    for key in ("service_lower_semantics", "service_upper_burst_bytes", "shaper_nominal_bytes_per_second"):
                        bound.pop(key, None)
        return result

    @model_validator(mode="after")
    def complete(self):
        if self.schema_version.endswith(".v1"):
            if (self.min_dt_seconds is not None or self.service_semantics_evidence is not None
                    or any(b.service_lower_semantics != "actual-departures" or b.service_upper_burst_bytes != 0
                           or b.shaper_nominal_bytes_per_second is not None for a in self.actions for b in a.bounds)):
                raise ValueError("v2_service_fields_require_explicit_version")
        elif (self.min_dt_seconds is None or self.min_dt_seconds > self.dt_seconds
              or self.service_semantics_evidence is None):
            raise ValueError("v2_service_horizon_and_source_derivation_required")
        for ids in (self.egress_ids, self.demand_ids, [a.action_id for a in self.actions]):
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate_network_scope")
        for action in self.actions:
            if (sorted(b.egress_id for b in action.bounds) != sorted(self.egress_ids)
                    or set(action.demand_egress_ids) != set(self.demand_ids)):
                raise ValueError("incomplete_action_scope")
            for route in action.demand_egress_ids.values():
                if not route or len(route) != len(set(route)) or not set(route) <= set(self.egress_ids):
                    raise ValueError("invalid_demand_egress_attribution")
        actions = {a.action_id for a in self.actions}
        if self.execution is not None and (
                set(self.execution.plans) != actions or set(self.execution.egresses) != set(self.egress_ids)
                or set(self.execution.demands) != set(self.demand_ids)
                or len({(e.node, e.interface, e.queue_handle) for e in self.execution.egresses.values()}) != len(self.egress_ids)):
            raise ValueError("incomplete_physical_execution_binding")
        if (self.max_delay_seconds >= self.dt_seconds
                or len(set(self.required_transitions)) != len(self.required_transitions)
                or any(old not in actions or new not in actions for old, new in self.required_transitions)):
            raise ValueError("invalid_transition_scope")
        return self


class CounterPair(StrictEvidence):
    before: int = Field(ge=0, le=2**63 - 1)
    after: int = Field(ge=0, le=2**63 - 1)

    @model_validator(mode="after")
    def monotonic(self):
        if self.after < self.before:
            raise ValueError("counter_reset")
        return self

    @property
    def delta(self):
        return self.after - self.before


class QueueReading(StrictEvidence):
    egress_id: Name
    queue_before_bytes: Amount
    queue_after_bytes: Amount
    arrivals: CounterPair
    departures: CounterPair
    drops: CounterPair
    # Separately observed demand counters at EACH egress, including zero traffic.
    demand_arrivals: dict[Name, CounterPair]
    unknown_arrival_bytes: int = Field(ge=0, le=2**63 - 1)
    measurement_error_bytes: Amount
    native_backlog_evidence: ArtifactRef | None = None


class NativeBacklogEvent(StrictEvidence):
    # A lossless, totally ordered native queue mutation trace, not endpoint polls.
    offset_ns: int = Field(ge=0, le=2**63 - 1)
    operation: Literal["enqueue", "dequeue", "drop"]
    bytes: int = Field(gt=0, le=2**63 - 1)


class NativeBacklogEvidence(StrictEvidence):
    schema_version: Literal["nanfo.native-busy-period.v1"]
    sample_id: Name
    egress_id: Name
    # Digest of the complete reading with native_backlog_evidence fields removed,
    # avoiding a circular self-reference while binding all counters and timing.
    reading_sha256: SHA256
    start_unix_seconds: Amount
    end_unix_seconds: Amount
    initial_queue_bytes: int = Field(gt=0, le=2**63 - 1)
    final_queue_bytes: int = Field(gt=0, le=2**63 - 1)
    lost_events: int = Field(ge=0, le=2**63 - 1)
    native_source: ArtifactRef
    events: list[NativeBacklogEvent] = Field(max_length=10000)


class NetworkReading(StrictEvidence):
    action_id: Name
    previous_action_id: Name
    start_unix_seconds: Amount
    end_unix_seconds: Amount
    dispatch_unix_seconds: Amount
    applied_unix_seconds: Amount
    transition_complete_unix_seconds: Amount
    queue_units: Literal["bytes"]
    rate_units: Literal["bytes/second"]
    time_units: Literal["unix-seconds"]
    measurement_complete: bool
    attribution_complete: bool
    counter_reset: bool
    unknown_demand_ids: list[Name] = Field(max_length=256)
    queues: list[QueueReading] = Field(min_length=1, max_length=256)


class BoundGuarantee(StrictEvidence):
    schema_version: Literal["nanfo.bound-guarantee.v1"]
    scope: CalibrationScope
    campaign_sha256: SHA256
    valid_from_unix_seconds: Amount
    valid_until_unix_seconds: Positive
    # Each is a hashed reviewed derivation/certification, NOT a boolean assertion.
    arrival_enforcement: ArtifactRef
    service_curve: ArtifactRef
    within_interval_dynamics: ArtifactRef
    transition_and_delay: ArtifactRef
    complete_demand_attribution: ArtifactRef
    queue_sensor_error: ArtifactRef
    capacity_and_scheduler: ArtifactRef
    environment_identity: ArtifactRef
    reviewer_id: Name
    assumptions: str = Field(min_length=40, max_length=8000)


class CalibrationInstallation(StrictEvidence):
    schema_version: Literal["nanfo.trusted-calibration-installation.v1"]
    scope: CalibrationScope
    campaign: ArtifactRef
    calibration: TrustedCalibration
    guarantee: ArtifactRef
