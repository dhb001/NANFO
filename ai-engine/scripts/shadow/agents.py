"""Deterministic evidence analyzers. No LLM, registry loading, tools or executor."""

from dataclasses import dataclass
from typing import Protocol

from .schemas import Finding, Observation, Plan


@dataclass(frozen=True)
class AgentContext:
    observations: tuple[Observation, ...]
    action: int
    allowed_actions: tuple[int, ...]
    utilization_threshold: float
    loss_threshold: float
    evidence_reference: str


class DomainAgent(Protocol):
    """Extension boundary for reviewed pure analyzers, not executable user plugins.

    Only observation evidence is supplied: held-out outcomes are never an input to
    an agent. Implementations return findings, never commands or authorization.
    """

    def analyze(self, context: AgentContext) -> Finding: ...


class CapacityAgent:
    def analyze(self, context: AgentContext) -> Finding:
        observation = context.observations[-1]
        values = observation.path_utilization + observation.path_capacity_mbps
        if any(value is None for value in values):
            return Finding(
                agent="capacity",
                status="unavailable",
                rationale="Complete per-path capacity/utilization evidence unavailable.",
                evidence_references=[context.evidence_reference],
                assumptions=[],
            )
        busy = [
            i
            for i, value in enumerate(observation.path_utilization)
            if value >= context.utilization_threshold
        ]
        rationale = (
            f"Observed utilization {observation.path_utilization} on capacities "
            f"{observation.path_capacity_mbps} Mbps; review paths {busy}."
        )
        return Finding(
            agent="capacity",
            status="review" if busy else "observed",
            rationale=rationale,
            evidence_references=[context.evidence_reference],
            assumptions=[
                "Utilization is a measured ratio, not a causal service bound.",
                "No prediction of spare capacity after a route change.",
            ],
        )


class FailureAgent:
    def analyze(self, context: AgentContext) -> Finding:
        observation = context.observations[-1]
        if observation.loss_fraction is None:
            status, rationale = "unavailable", "Loss evidence unavailable; no health conclusion."
        else:
            review = (
                observation.loss_fraction > context.loss_threshold or observation.latency_ms is None
            )
            status = "review" if review else "observed"
            rationale = (
                f"Observed loss fraction {observation.loss_fraction}; "
                f"ICMP RTT ms {observation.latency_ms}. "
                "Missing RTT is censored/unavailable, never zero latency."
            )
        return Finding(
            agent="failure",
            status=status,
            rationale=rationale,
            evidence_references=[context.evidence_reference],
            assumptions=["Observed loss does not identify a failed device or root cause."],
        )


class PolicyAgent:
    def analyze(self, context: AgentContext) -> Finding:
        permitted = context.action in context.allowed_actions
        return Finding(
            agent="policy",
            status="observed" if permitted else "review",
            rationale=(
                f"Diagnostic action {context.action} is "
                f"{'inside' if permitted else 'outside'} the pinned review set "
                f"{list(context.allowed_actions)}; no execution permission."
            ),
            evidence_references=[context.evidence_reference, "plan:allowed_actions"],
            assumptions=["Review policy membership is not runtime RBAC or safety approval."],
        )


def analyze(plan: Plan, observations: list[Observation], action: int) -> list[Finding]:
    context = AgentContext(
        tuple(observations),
        action,
        tuple(plan.allowed_actions),
        plan.utilization_review_threshold,
        plan.loss_review_threshold,
        "diagnostic:result.evidence",
    )
    agents: tuple[DomainAgent, ...] = (CapacityAgent(), FailureAgent(), PolicyAgent())
    return [agent.analyze(context) for agent in agents]
