"""Closed read-only tool registry: declarative config cannot import or execute code."""

import json
import math
from pathlib import Path

from shadow.agents import AgentContext, CapacityAgent, FailureAgent, PolicyAgent
from shadow.io import parseJson, readPinned
from shadow.schemas import Diagnostic, Plan

from .contracts import AgentOutcome, AgentRegistration, Registry, Scope

TOOLS = {
    "capacity": frozenset({"read_observation"}),
    "failure": frozenset({"read_observation"}),
    "policy": frozenset({"read_review_policy"}),
}


def loadRegistry(path: Path, pin: str) -> Registry:
    return Registry.model_validate_json(json.dumps(parseJson(readPinned(path, pin, limit=262144))))


def authorize(registry: Registry, scope: Scope, permission: str, now: float) -> None:
    if not math.isfinite(now) or now < 0:
        raise ValueError("invalid_clock")
    if now >= registry.expires_unix or scope not in registry.scopes:
        raise PermissionError("registry_expired_or_scope_denied")
    if permission not in registry.permissions:
        raise PermissionError("registry_permission_denied")


def permissionReason(agent: AgentRegistration, scope: Scope) -> str | None:
    if scope not in agent.scopes:
        return "agent_scope_denied"
    if not TOOLS[agent.agent_id] <= set(agent.tools):
        return "agent_read_tool_denied"
    return None


def invoke(agent: AgentRegistration, plan: Plan, diagnostic: Diagnostic) -> AgentOutcome:
    """Only built-ins; give each the minimum read-only context its tool needs."""
    observation = diagnostic.result.evidence[-1]
    if agent.agent_id == "capacity":
        analyzer = CapacityAgent()
        weight = sum(
            value is not None
            for value in (*observation.path_capacity_mbps, *observation.path_utilization)
        )
    elif agent.agent_id == "failure":
        analyzer = FailureAgent()
        weight = sum(
            value is not None for value in (observation.loss_fraction, observation.latency_ms)
        )
    else:
        analyzer = PolicyAgent()
        weight = 1  # exact bound action + configured permitted review set
    context = AgentContext(
        tuple(diagnostic.result.evidence) if agent.agent_id != "policy" else (),
        diagnostic.result.action if agent.agent_id == "policy" else 0,
        tuple(plan.allowed_actions) if agent.agent_id == "policy" else (),
        plan.utilization_review_threshold,
        plan.loss_review_threshold,
        "diagnostic:result.evidence",
    )
    finding = analyzer.analyze(context)
    unavailable = finding.status == "unavailable"
    return AgentOutcome(
        agent_id=agent.agent_id,
        state="unavailable" if unavailable else "completed",
        finding=finding,
        evidence_weight=0 if unavailable else weight,
        reason="evidence_unavailable" if unavailable else "read_only_analysis_completed",
    )
