"""Strict operator-configured fluid model contract (ADR-017)."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Rate = Annotated[float, Field(ge=0, le=1e6, allow_inf_nan=False)]
Bytes = Annotated[float, Field(ge=0, le=1e12, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SimulationEvidence(StrictModel):
    simulation_id: str
    intent_id: str
    workspace_id: str
    network_id: str
    plan_sha256: Digest
    network_state_sha256: Digest
    input_sha256: Digest
    checkpoint_sha256: Digest
    output_sha256: Digest
    completed_at: str
    evidence_expires_at: str
    source: Literal["operator_configured_model"]
    validation_scope: Literal["configured_model_admission_only"]
    physical_safety_authorized: Literal[False]

    @field_validator("simulation_id", "intent_id", "workspace_id", "network_id")
    @classmethod
    def uuid_identity(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("Canonical UUID required")
        return value

    @field_validator("completed_at", "evidence_expires_at")
    @classmethod
    def aware_timestamp(cls, value):
        if datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError("Aware timestamp required")
        return value


Finite = Annotated[float, Field(allow_inf_nan=False)]


class UnavailableOutput(StrictModel):
    latency_ms: None = None
    loss_pct: None = None
    throughput_mbps: None = None


class FluidMetrics(StrictModel):
    offered_bytes: Finite
    delivered_bytes: Finite
    dropped_bytes: Finite
    queued_bytes: Finite
    inflight_bytes: Finite
    delivered_residence_byte_ms: Finite
    loss_pct: Finite | None
    delivery_ratio: Finite | None
    throughput_mbps: Finite | None
    latency_ms: Finite | None


class LinkFlowTrace(StrictModel):
    arrived_bytes: Finite
    dropped_bytes: Finite
    served_bytes: Finite
    queued_bytes: Finite


class LinkTrace(StrictModel):
    flows: dict[Identifier, LinkFlowTrace]
    served_bytes: Finite
    queued_bytes: Finite
    utilization: Finite
    background_queued_bytes: Finite
    background_served_bytes: Finite


class SimulationTrace(StrictModel):
    tick: Annotated[int, Field(ge=1, le=1000)]
    elapsed_ms: Annotated[int, Field(ge=1, le=1000000)]
    links: dict[Identifier, LinkTrace]
    flows: dict[Identifier, FluidMetrics]


class InitialBackground(StrictModel):
    initial_bytes: Finite
    queued_bytes: Finite
    inflight_bytes: Finite
    delivered_bytes: Finite


class ObjectiveChecks(StrictModel):
    max_loss_pct: bool
    max_latency_ms: bool
    min_throughput_mbps: bool


class ModeledOutput(FluidMetrics):
    model_version: Literal["finite-buffer-fluid.v1"]
    input_sha256: Digest
    workload_sha256: Digest
    checkpoint_sha256: Digest
    output_sha256: Digest
    elapsed_ms: Annotated[int, Field(ge=0, le=1000000)]
    duration_ticks: Annotated[int, Field(ge=1, le=1000)]
    tick: Annotated[int, Field(ge=0, le=1000)]
    source: Literal["operator_configured_model"]
    physical_safety_authorized: Literal[False]
    latency_definition: str
    objective_checks: ObjectiveChecks
    risk_gate: Literal["passed", "blocked"]
    flows: dict[Identifier, FluidMetrics]
    initial_background: dict[Identifier, InitialBackground]
    trace: Annotated[list[SimulationTrace], Field(max_length=1000)]


class ScenarioLink(StrictModel):
    link_id: Identifier
    source: Identifier
    target: Identifier
    capacity_mbps: Annotated[float, Field(gt=0, le=1e6, allow_inf_nan=False)]
    buffer_bytes: Bytes
    delay_ms: Annotated[float, Field(ge=0, le=60000, allow_inf_nan=False)]
    initial_queue_bytes: Bytes

    @model_validator(mode="after")
    def valid_queue(self) -> Self:
        if self.source == self.target or self.initial_queue_bytes > self.buffer_bytes:
            raise ValueError(
                "Distinct link endpoints and initial queue <= buffer required"
            )
        return self


class ScenarioFlow(StrictModel):
    flow_id: Identifier
    source: Identifier
    target: Identifier
    path: Annotated[list[Identifier], Field(min_length=1, max_length=128)]
    demand_mbps: Annotated[list[Rate], Field(min_length=1, max_length=1000)]


class ActionBinding(StrictModel):
    # JSON UUID strings are accepted at the API's Python validation boundary.
    intent_id: Annotated[UUID, Field(strict=False)]
    plan_sha256: Digest
    network_state_sha256: Digest


class ScenarioLimits(StrictModel):
    max_loss_pct: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    max_latency_ms: Annotated[float, Field(ge=0, le=1e9, allow_inf_nan=False)]
    min_throughput_mbps: Rate


class ScenarioConfig(StrictModel):
    version: Literal[1]
    seed: Annotated[int, Field(ge=0, le=2**63 - 1)]
    tick_ms: Annotated[int, Field(ge=1, le=1000)]
    duration_ticks: Annotated[int, Field(ge=1, le=1000)]
    links: Annotated[list[ScenarioLink], Field(min_length=1, max_length=128)]
    flows: Annotated[list[ScenarioFlow], Field(min_length=1, max_length=64)]
    action_binding: ActionBinding | None
    limits: ScenarioLimits

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("version must be integer 1")
        return value

    @model_validator(mode="after")
    def valid_graph_and_work(self) -> Self:
        links = {link.link_id: link for link in self.links}
        nodes = {node for link in self.links for node in (link.source, link.target)}
        if len(links) != len(self.links) or len(
            {flow.flow_id for flow in self.flows}
        ) != len(self.flows):
            raise ValueError("Duplicate link or flow ID")
        work = self.duration_ticks * (
            len(links) + len(self.flows) + sum(len(flow.path) for flow in self.flows)
        )
        if len(nodes) > 128 or work > 16384:
            raise ValueError(
                "Scenario exceeds 128 nodes or 16384 tick/link/flow/path work units"
            )
        for flow in self.flows:
            if len(flow.demand_mbps) not in {1, self.duration_ticks}:
                raise ValueError("Demand must be singleton or exactly duration_ticks")
            node, visited = flow.source, {flow.source}
            for link_id in flow.path:
                link = links.get(link_id)
                if link is None or link.source != node or link.target in visited:
                    raise ValueError(
                        "Flow path must be declared, connected, directed and acyclic"
                    )
                node = link.target
                visited.add(node)
            if node != flow.target:
                raise ValueError("Flow path target mismatch")
        return self
