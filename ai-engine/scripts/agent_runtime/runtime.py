"""Observe -> options -> model evidence -> recommend -> reflect; execution unavailable."""

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shadow.evaluate import canonicalHash, diagnosticFromExport
from shadow.io import loadEvaluation, parseJson, readPinned
from shadow.schemas import Decision, Diagnostic, Plan

from .contracts import AgentOutcome, MemoryItem, Registry, Request, RuntimeDecision
from .memory import Memory
from .registry import authorize
from .scheduler import consensus, schedule


@dataclass(frozen=True)
class EvidenceFiles:
    plan_path: Path
    plan_sha256: str
    diagnostic_path: Path
    outcomes_path: Path
    benchmark_path: Path

    def load(self, now: float) -> tuple[Plan, Diagnostic, Decision]:
        plan = Plan.model_validate_json(
            json.dumps(parseJson(readPinned(self.plan_path, self.plan_sha256, limit=1024 * 1024)))
        )
        diagnostic = diagnosticFromExport(
            parseJson(readPinned(self.diagnostic_path, plan.diagnostic_sha256)), plan
        )
        shadow = loadEvaluation(
            plan_path=self.plan_path,
            plan_sha256=self.plan_sha256,
            diagnostic_path=self.diagnostic_path,
            outcomes_path=self.outcomes_path,
            benchmark_path=self.benchmark_path,
            now=datetime.fromtimestamp(now, UTC),
        )
        return plan, diagnostic, shadow


def checkScope(request: Request, plan: Plan):
    if (request.scope.tenant_id, request.scope.network_id, request.scope.model_sha256) != (
        plan.workspace_id,
        plan.network_id,
        plan.model.policy_sha256,
    ):
        raise PermissionError("shadow_scope_or_model_mismatch")
    if request.item is not None:
        raise ValueError("analysis_does_not_ingest_request_item")


def analyze(
    registry: Registry,
    request: Request,
    evidence: EvidenceFiles,
    registry_pin: str,
    *,
    clock=time.time,
) -> RuntimeDecision:
    authorize(registry, request.scope, "analyze", clock())
    plan, diagnostic, shadow = evidence.load(clock())
    checkScope(request, plan)
    started = time.monotonic()
    outcomes = []
    for agent in sorted(registry.agents, key=lambda item: item.agent_id):
        authorize(registry, request.scope, "analyze", clock())
        outcomes.append(
            schedule(agent, request.scope, plan, diagnostic, 6 - (time.monotonic() - started))
        )
    # Re-evaluate expiry after analysis; a decision must not retain pre-work freshness.
    _, _, shadow = evidence.load(clock())
    authorize(registry, request.scope, "analyze", clock())
    return decisionFor(registry, request, evidence, registry_pin, shadow, outcomes, [])


def inputPin(request: Request, evidence: EvidenceFiles, registry_pin: str) -> str:
    return canonicalHash(
        {"request": request.model_dump(), "plan": evidence.plan_sha256, "registry": registry_pin}
    )


def decisionFor(
    registry: Registry,
    request: Request,
    evidence: EvidenceFiles,
    registry_pin: str,
    shadow: Decision,
    outcomes: list[AgentOutcome],
    memories: list[MemoryItem],
) -> RuntimeDecision:
    combined = consensus(outcomes, shadow)
    return RuntimeDecision(
        run_id=request.run_id,
        session_id=request.session_id,
        scope=request.scope,
        registry_sha256=registry_pin,
        input_sha256=inputPin(request, evidence, registry_pin),
        shadow=shadow,
        agents=outcomes,
        consensus=combined,
        memory_ids=[item.memory_id for item in memories],
        memory_sha256=[canonicalHash(item.model_dump()) for item in memories],
        workflow=[
            "observe:validated_scoped_frozen_diagnostic",
            "options:hold_and_matched_baselines",
            "model_evidence:frozen_shadow_comparison",
            "recommend:deterministic_evidence_weighted_review",
            "execute:unavailable",
            "reflect:record_review_without_learning",
        ],
        reflection=(
            f"Posture {combined.posture}; {len(combined.dissent)} dissent/unavailable findings; "
            f"{len(memories)} scoped memory references. Memory is contextual evidence only; "
            "no model update, diagnosis override, safety calibration or execution occurred."
        ),
    )


def runOnce(
    store: Memory,
    registry: Registry,
    request: Request,
    evidence: EvidenceFiles,
    registry_pin: str,
    *,
    clock=time.time,
) -> RuntimeDecision:
    for permission in ("run", "analyze", "memory_read", "memory_write", "export"):
        authorize(registry, request.scope, permission, clock())
    plan, diagnostic, shadow = evidence.load(clock())
    checkScope(request, plan)
    pin = inputPin(request, evidence, registry_pin)
    generation = store.claim(registry, request, pin, clock())
    if generation is None:
        # Exact replay is an immutable historical export, never a fresh decision.
        return store.export(registry, request, clock())
    checkpoints = store.checkpoints(registry, request, clock())
    if "memory" in checkpoints:
        memories = [MemoryItem.model_validate(item) for item in checkpoints["memory"]["items"]]
        if any(item.scope != request.scope for item in memories):
            raise PermissionError("checkpoint_memory_scope_denied")
        memories = [item for item in memories if item.created_unix <= clock() < item.expires()]
    else:
        memories = store.retrieve(registry, request, clock())
        store.checkpoint(
            registry,
            request,
            generation,
            "memory",
            {"items": [item.model_dump() for item in memories]},
            clock(),
        )
    started = time.monotonic()
    outcomes = []
    for agent in sorted(registry.agents, key=lambda item: item.agent_id):
        authorize(registry, request.scope, "analyze", clock())
        if agent.agent_id in checkpoints:
            outcome = AgentOutcome.model_validate(checkpoints[agent.agent_id])
            if outcome.agent_id != agent.agent_id:
                raise ValueError("checkpoint_agent_identity_mismatch")
        else:
            outcome = schedule(
                agent, request.scope, plan, diagnostic, 6 - (time.monotonic() - started)
            )
            store.checkpoint(
                registry, request, generation, agent.agent_id, outcome.model_dump(), clock()
            )
        outcomes.append(outcome)
    _, _, shadow = evidence.load(clock())
    now = clock()
    memories = [item for item in memories if item.created_unix <= now < item.expires()]
    decision = decisionFor(registry, request, evidence, registry_pin, shadow, outcomes, memories)
    expiry = min(
        registry.expires_unix,
        shadow.freshness.oldest_evidence_at.timestamp() + plan.max_age_seconds,
    )
    reflection = None
    if expiry > now and shadow.freshness.status == "within_review_window":
        reflection = MemoryItem(
            memory_id="reflection-" + pin[:64],
            scope=request.scope,
            session_id=request.session_id,
            tier="long_term",
            kind="reflection",
            summary=decision.reflection,
            provenance_sha256=[pin, plan.diagnostic_sha256],
            source_reference=f"run:{request.run_id}",
            source_observed_unix=shadow.freshness.oldest_evidence_at.timestamp(),
            source_expires_unix=expiry,
            created_unix=now,
            ttl_seconds=min(86400.0, expiry - now),
        )
    store.complete(registry, request, generation, decision, reflection, now)
    return decision
