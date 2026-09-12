"""Pure configured link-energy estimate. No telemetry, drivers or physical claims."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=120)]
Watts = Annotated[float, Field(ge=0, le=1_000_000, allow_inf_nan=False)]


class EnergyLink(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    link_id: Identifier
    source: Identifier
    target: Identifier
    active_watts: Watts
    idle_watts: Watts


class EnergyScenario(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    duration_hours: float = Field(gt=0, le=8784, allow_inf_nan=False)
    nodes: list[Identifier] = Field(min_length=2, max_length=500)
    links: list[EnergyLink] = Field(min_length=1, max_length=2000)
    candidate_idle_link_ids: list[Identifier] = Field(max_length=2000)

    @model_validator(mode="after")
    def validate_graph(self) -> EnergyScenario:
        nodes = set(self.nodes)
        ids = {link.link_id for link in self.links}
        candidates = set(self.candidate_idle_link_ids)
        if len(nodes) != len(self.nodes) or len(ids) != len(self.links):
            raise ValueError("Node and link identifiers must be unique.")
        if len(candidates) != len(self.candidate_idle_link_ids) or not candidates <= ids:
            raise ValueError("Candidate link identifiers must be unique and present in the graph.")
        adjacency: dict[str, set[str]] = {node: set() for node in nodes}
        for link in self.links:
            if link.source not in nodes or link.target not in nodes or link.source == link.target:
                raise ValueError("Links require two distinct declared endpoints.")
            if link.link_id not in candidates:
                adjacency[link.source].add(link.target)
                adjacency[link.target].add(link.source)
        # Connected after all candidates are removed also implies connected baseline.
        visited: set[str] = set()
        pending = [self.nodes[0]]
        while pending:
            node = pending.pop()
            if node not in visited:
                visited.add(node)
                pending.extend(adjacency[node] - visited)
        if visited != nodes:
            raise ValueError("Baseline and candidate plan must retain connectivity for every declared node.")
        return self


class EnergyEstimate(BaseModel):
    model_only: Literal[True] = True
    guaranteed_savings: Literal[False] = False
    physical_control: Literal[False] = False
    controls_status: Literal["unsupported"] = "unsupported"
    power_control_acceptance: Literal["blocked"] = "blocked"
    evidence_kind: Literal["configured_estimate"] = "configured_estimate"
    connectivity_status: Literal["modeled_connected"] = "modeled_connected"
    assumptions: EnergyScenario
    baseline_watts: float
    candidate_watts: float
    baseline_energy_wh: float
    candidate_energy_wh: float
    estimated_savings_wh: float
    limitations: list[str] = Field(default_factory=lambda: [
        "Operator-configured link wattage only; no inferred or measured consumption.",
        "Baseline assumes every declared link active for the entire duration.",
        "Undirected graph connectivity only; no capacity, routing, traffic or failure-safety proof.",
        "Link model excludes device chassis, cooling, PoE and energized-port physics.",
        "Idle alternatives are hypothetical, not commands or physical port-sleep capabilities.",
    ])


def estimate_energy(scenario: EnergyScenario) -> EnergyEstimate:
    """Revalidate at the public boundary; never mutate caller data or operate links."""
    scenario = EnergyScenario.model_validate(scenario.model_dump())
    candidates = set(scenario.candidate_idle_link_ids)
    baseline = sum(link.active_watts for link in scenario.links)
    candidate = sum(
        link.idle_watts if link.link_id in candidates else link.active_watts
        for link in scenario.links
    )
    return EnergyEstimate(
        assumptions=scenario, baseline_watts=baseline, candidate_watts=candidate,
        baseline_energy_wh=baseline * scenario.duration_hours,
        candidate_energy_wh=candidate * scenario.duration_hours,
        estimated_savings_wh=(baseline - candidate) * scenario.duration_hours,
    )
