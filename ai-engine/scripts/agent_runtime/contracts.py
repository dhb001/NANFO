"""Strict local operator contracts, separate from frozen training and backend APIs."""

from typing import Annotated, Literal

from pydantic import Field, model_validator
from shadow.schemas import ID, UUID, Alternative, Decision, Finding, Hash, Record, Text

Seconds = Annotated[float, Field(ge=0, le=1e12)]
Tier = Literal["working", "short_term", "long_term", "semantic"]
AgentID = Literal["capacity", "failure", "policy"]
Permission = Literal["analyze", "run", "memory_read", "memory_write", "export"]
Tool = Literal["read_observation", "read_review_policy"]


class Scope(Record):
    # tenant_id is the existing shadow/backend workspace_id, not a new backend field.
    tenant_id: UUID
    network_id: UUID
    model_sha256: Hash
    trace_id: ID


class AgentRegistration(Record):
    agent_id: AgentID
    version: Literal[1] = 1
    scopes: Annotated[list[Scope], Field(min_length=1, max_length=100)]
    tools: Annotated[list[Tool], Field(min_length=1, max_length=2)]
    timeout_seconds: Annotated[float, Field(gt=0, le=2)] = 0.5

    @model_validator(mode="after")
    def uniqueTools(self):
        if len(set(self.tools)) != len(self.tools):
            raise ValueError("duplicate tool permission")
        return self


class Registry(Record):
    version: Literal[1]
    operator_id: ID
    expires_unix: Seconds
    scopes: Annotated[list[Scope], Field(min_length=1, max_length=100)]
    permissions: Annotated[list[Permission], Field(min_length=1, max_length=5)]
    agents: Annotated[list[AgentRegistration], Field(min_length=1, max_length=3)]

    @model_validator(mode="after")
    def uniqueAgents(self):
        if len({agent.agent_id for agent in self.agents}) != len(self.agents):
            raise ValueError("duplicate registered agent")
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("duplicate registry permission")
        if any(scope not in self.scopes for agent in self.agents for scope in agent.scopes):
            raise ValueError("agent scope exceeds operator scope")
        return self


class MemoryItem(Record):
    memory_id: ID
    scope: Scope
    session_id: ID
    tier: Tier
    kind: Literal["observation_note", "incident", "graph_reference", "reflection"]
    summary: Text
    provenance_sha256: Annotated[list[Hash], Field(min_length=1, max_length=16)]
    source_reference: Text
    source_observed_unix: Seconds
    source_expires_unix: Seconds
    created_unix: Seconds
    ttl_seconds: Annotated[float, Field(gt=0, le=31536000)]
    graph_references: Annotated[list[ID], Field(max_length=32)] = []

    @model_validator(mode="after")
    def tierContract(self):
        if not self.source_observed_unix <= self.created_unix < self.source_expires_unix:
            raise ValueError("invalid source freshness interval")
        if self.tier == "working" and self.ttl_seconds > 3600:
            raise ValueError("working TTL exceeds one hour")
        if self.tier == "short_term" and self.ttl_seconds > 86400:
            raise ValueError("short-term TTL exceeds one day")
        if self.tier == "long_term" and self.kind not in ("incident", "reflection"):
            raise ValueError("long-term memory requires incident or reflection")
        if self.tier == "semantic" and (
            self.kind != "graph_reference" or not self.graph_references
        ):
            raise ValueError("semantic memory requires explicit graph references")
        if self.tier != "semantic" and self.graph_references:
            raise ValueError("graph references require semantic tier")
        return self

    def expires(self) -> float:
        return min(self.source_expires_unix, self.created_unix + self.ttl_seconds)


class Request(Record):
    version: Literal[1]
    scope: Scope
    session_id: ID
    run_id: ID
    retrieval_limit: Annotated[int, Field(ge=1, le=50)] = 10
    tiers: Annotated[list[Tier], Field(min_length=1, max_length=4)] = [
        "working",
        "short_term",
        "long_term",
        "semantic",
    ]
    item: MemoryItem | None = None


class AgentOutcome(Record):
    agent_id: AgentID
    state: Literal["completed", "denied", "timeout", "error", "unavailable"]
    finding: Finding | None = None
    # Count of complete, relevant observed fields, NOT a probability or confidence.
    evidence_weight: Annotated[int, Field(ge=0, le=4)] = 0
    reason: Text


class Consensus(Record):
    posture: Literal["review", "observe", "abstain"]
    review_weight: Annotated[int, Field(ge=0)]
    observe_weight: Annotated[int, Field(ge=0)]
    weighting: Literal["complete_relevant_evidence_fields_not_confidence"] = (
        "complete_relevant_evidence_fields_not_confidence"
    )
    rationale: Text
    dissent: list[AgentOutcome]
    alternatives: list[Alternative]
    safety_confidence: None = None
    safety_authorized: Literal[False] = False


class RuntimeDecision(Record):
    version: Literal[1] = 1
    run_id: ID
    session_id: ID
    scope: Scope
    registry_sha256: Hash
    input_sha256: Hash
    shadow: Decision
    agents: list[AgentOutcome]
    consensus: Consensus
    memory_ids: list[ID]
    memory_sha256: list[Hash]
    workflow: list[Text]
    reflection: Text
    execution: Literal["not_applied"] = "not_applied"
    safety_authorized: Literal[False] = False
    production_dispatch: Literal[False] = False
    online_learning: Literal[False] = False
    unavailable_providers: list[Text] = [
        "qualified_runtime_model_registry",
        "compatible_live_observer",
        "calibrated_safety_bounds",
        "authorized_executor",
        "governed_recovery",
    ]
