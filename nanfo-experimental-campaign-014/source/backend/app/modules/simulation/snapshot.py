"""Explicit canonical inventory/configuration snapshot -> existing ScenarioConfig.

The caller supplies owning-service exports. No inventory lookup, ID generation,
RF-to-capacity conversion, default demand, inferred route or buffer sizing occurs.
"""

from __future__ import annotations

import sys
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.modules.simulation.evaluator import canonical_config, digest, workload_hash
from app.modules.simulation.rf import Scope
from app.modules.simulation.schemas import (
    Digest,
    Identifier,
    ScenarioConfig,
    ScenarioFlow,
    ScenarioLimits,
    ScenarioLink,
    StrictModel,
)

SNAPSHOT_VERSION = "explicit-scenario-snapshot.v1"


class ValueSource(StrictModel):
    kind: Literal["measured", "configured"]
    source_id: Identifier
    record_id: Identifier
    # A content digest pins the operator's external evidence/configuration artifact.
    artifact_sha256: Digest


class LinkSources(StrictModel):
    capacity_mbps: ValueSource
    buffer_bytes: ValueSource
    delay_ms: ValueSource
    initial_queue_bytes: ValueSource


class SnapshotLink(StrictModel):
    config: ScenarioLink
    sources: LinkSources


class SnapshotFlow(StrictModel):
    config: ScenarioFlow
    demand_source: ValueSource
    route_source: ValueSource


class SnapshotRequest(StrictModel):
    version: Literal["explicit-scenario-snapshot.v1"] = SNAPSHOT_VERSION
    scope: Scope
    snapshot_id: Identifier
    # Pins the owning service's topology/configuration export, not the RF model.
    network_config_sha256: Digest
    node_ids: Annotated[list[Identifier], Field(min_length=2, max_length=128)]
    seed: Annotated[int, Field(ge=0, le=2**63 - 1)]
    tick_ms: Annotated[int, Field(ge=1, le=1000)]
    duration_ticks: Annotated[int, Field(ge=1, le=1000)]
    links: Annotated[list[SnapshotLink], Field(min_length=1, max_length=128)]
    flows: Annotated[list[SnapshotFlow], Field(min_length=1, max_length=64)]
    limits: ScenarioLimits

    @model_validator(mode="after")
    def validate_canonical_graph(self) -> Self:
        nodes = set(self.node_ids)
        if len(nodes) != len(self.node_ids):
            raise ValueError("Duplicate canonical node ID")
        for item in [*self.links, *self.flows]:
            if item.config.source not in nodes or item.config.target not in nodes:
                raise ValueError(
                    "Every endpoint must use an explicit canonical node ID"
                )
        for link in self.links:
            # The unchanged evaluator divides by this budget when reporting utilization.
            budget = link.config.capacity_mbps * self.tick_ms * 125
            if budget < sys.float_info.min:
                raise ValueError("Capacity byte budget must be a normal positive float")
        self.scenario_config()  # Reuse existing graph, path and total-work bounds.
        return self

    def scenario_config(self) -> ScenarioConfig:
        return ScenarioConfig(
            version=1,
            seed=self.seed,
            tick_ms=self.tick_ms,
            duration_ticks=self.duration_ticks,
            links=[
                item.config
                for item in sorted(self.links, key=lambda item: item.config.link_id)
            ],
            flows=[
                item.config
                for item in sorted(self.flows, key=lambda item: item.config.flow_id)
            ],
            action_binding=None,
            limits=self.limits,
        )


class FlowSources(StrictModel):
    demand: ValueSource
    route: ValueSource


class SnapshotProvenance(StrictModel):
    version: Literal["explicit-scenario-snapshot.v1"] = SNAPSHOT_VERSION
    scope: Scope
    snapshot_id: Identifier
    network_config_sha256: Digest
    snapshot_sha256: Digest
    scenario_sha256: Digest
    workload_sha256: Digest
    node_ids: list[Identifier]
    link_sources: dict[Identifier, LinkSources]
    flow_sources: dict[Identifier, FlowSources]
    source: Literal["operator_configured_model"] = "operator_configured_model"
    physical_safety_authorized: Literal[False] = False


def build_snapshot(
    request: SnapshotRequest,
) -> tuple[ScenarioConfig, SnapshotProvenance]:
    request = SnapshotRequest.model_validate(request.model_dump())
    config = request.scenario_config()
    canonical = request.model_dump(mode="json")
    canonical["node_ids"].sort()
    canonical["links"].sort(key=lambda item: item["config"]["link_id"])
    canonical["flows"].sort(key=lambda item: item["config"]["flow_id"])
    provenance = SnapshotProvenance(
        scope=request.scope,
        snapshot_id=request.snapshot_id,
        network_config_sha256=request.network_config_sha256,
        snapshot_sha256=digest(canonical),
        scenario_sha256=digest(canonical_config(config)),
        workload_sha256=workload_hash(config),
        node_ids=sorted(request.node_ids),
        link_sources={item.config.link_id: item.sources for item in request.links},
        flow_sources={
            item.config.flow_id: FlowSources(
                demand=item.demand_source, route=item.route_source
            )
            for item in request.flows
        },
    )
    return config, provenance
