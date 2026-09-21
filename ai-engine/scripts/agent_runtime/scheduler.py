"""Serial deterministic POSIX main-thread scheduler with hard per-call deadlines."""

import signal
import threading
import time
from contextlib import contextmanager

from shadow.schemas import Alternative, Decision, Diagnostic, Plan

from .contracts import AgentOutcome, AgentRegistration, Consensus, Scope
from .registry import invoke, permissionReason


class DeadlineExceeded(Exception):
    pass


@contextmanager
def deadline(seconds: float):
    # These fixed pure Python analyzers need no process pool, imported plugin or
    # uncancellable background thread. Never interfere with a caller's alarm.
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("scheduler_requires_main_thread")
    if not hasattr(signal, "setitimer") or signal.getitimer(signal.ITIMER_REAL)[0] != 0:
        raise RuntimeError("scheduler_deadline_unavailable")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(signum, frame):
        raise DeadlineExceeded("agent_deadline_exceeded")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def schedule(
    agent: AgentRegistration, scope: Scope, plan: Plan, diagnostic: Diagnostic, remaining: float
) -> AgentOutcome:
    denied = permissionReason(agent, scope)
    if denied:
        return AgentOutcome(agent_id=agent.agent_id, state="denied", reason=denied)
    if remaining <= 0:
        return AgentOutcome(agent_id=agent.agent_id, state="timeout", reason="run_budget_exhausted")
    try:
        started = time.monotonic()
        budget = min(agent.timeout_seconds, remaining)
        with deadline(budget):
            result = invoke(agent, plan, diagnostic)
        if time.monotonic() - started >= budget:
            raise DeadlineExceeded()
        return result
    except DeadlineExceeded:
        return AgentOutcome(
            agent_id=agent.agent_id, state="timeout", reason="agent_deadline_exceeded"
        )
    except Exception:
        # Exception messages may contain operator data; retain only a stable code.
        return AgentOutcome(agent_id=agent.agent_id, state="error", reason="agent_analysis_failed")


def consensus(outcomes: list[AgentOutcome], shadow: Decision) -> Consensus:
    review = sum(
        row.evidence_weight
        for row in outcomes
        if row.finding and row.finding.status == "review" and row.state == "completed"
    )
    observe = sum(
        row.evidence_weight
        for row in outcomes
        if row.finding and row.finding.status == "observed" and row.state == "completed"
    )
    missing = {row.agent_id for row in outcomes} != {"capacity", "failure", "policy"}
    blocked = (
        shadow.status == "abstain" or missing or any(row.state != "completed" for row in outcomes)
    )
    posture = "abstain" if blocked else "review" if review >= observe else "observe"
    matching = "observed" if posture == "observe" else "review"
    dissent = [
        row
        for row in outcomes
        if posture == "abstain" or row.finding is None or row.finding.status != matching
    ]
    alternatives = list(shadow.alternatives)
    if review:
        alternatives.append(
            Alternative(
                option="investigate_flagged_evidence",
                rationale="Retain review findings even if outvoted.",
                evidence_references=[
                    ref
                    for row in outcomes
                    if row.finding and row.finding.status == "review"
                    for ref in row.finding.evidence_references
                ],
            )
        )
    return Consensus(
        posture=posture,
        review_weight=review,
        observe_weight=observe,
        dissent=dissent,
        alternatives=alternatives,
        rationale=(
            "Missing/denied/expired/error evidence prevents a combined recommendation."
            if blocked
            else "Complete relevant field counts weight review versus observation; "
            "ties request review. Correlated evidence counts are not independent votes "
            "or safety confidence; minority warnings remain visible."
        ),
    )
