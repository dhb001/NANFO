"""Pure shadow review: content binding, complete matched pairs and honest abstention."""

import hashlib
import json
from datetime import datetime
from statistics import mean, stdev

from .agents import analyze
from .schemas import (
    METHODS,
    Alternative,
    Decision,
    Diagnostic,
    EvidenceSource,
    Freshness,
    MetricComparison,
    ModelIdentity,
    Outcomes,
    Plan,
    Qualification,
)


def canonicalHash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def diagnosticFromExport(value: dict, plan: Plan) -> Diagnostic:
    """Accept an ADR018 record, successful POST envelope, or existing GET export."""
    if "success" in value:
        if value["success"] is not True or value.get("errors") is not None:
            raise ValueError("unsuccessful diagnostic export")
        value = value["data"]
    if not isinstance(value, dict):
        raise ValueError("diagnostic export object required")
    if "diagnostics" in value:
        if (value.get("network_id"), value.get("workspace_id")) != (
            plan.network_id,
            plan.workspace_id,
        ):
            raise ValueError("diagnostic export scope mismatch")
        if (
            value.get("status") != "operator_registered"
            or value.get("safety_authorized") is not False
            or value.get("production_dispatch") is not False
        ):
            raise ValueError("incompatible diagnostic export status")
        model = value.get("model") or {}
        if not isinstance(model, dict):
            raise ValueError("diagnostic model status object required")
        if (model.get("model_id"), model.get("checkpoint_id"), model.get("checkpoint_sha256")) != (
            plan.model.model_id,
            plan.model.checkpoint_id,
            plan.model.policy_sha256,
        ):
            raise ValueError("diagnostic registry status mismatch")
        records = value["diagnostics"]
        if (
            not isinstance(records, list)
            or len(records) > 100
            or any(not isinstance(row, dict) for row in records)
        ):
            raise ValueError("diagnostic export bound")
        matches = [row for row in records if row.get("diagnostic_id") == plan.diagnostic_id]
        if len(matches) != 1:
            raise ValueError("exactly one selected diagnostic required")
        value = matches[0]
    return Diagnostic.model_validate_json(json.dumps(value, allow_nan=False))


def validateBindings(plan: Plan, diagnostic: Diagnostic, outcomes: Outcomes) -> None:
    if (diagnostic.network_id, diagnostic.workspace_id, diagnostic.diagnostic_id) != (
        plan.network_id,
        plan.workspace_id,
        plan.diagnostic_id,
    ):
        raise ValueError("diagnostic scope or identity mismatch")
    result = diagnostic.result
    identity = ModelIdentity.model_validate(
        {name: getattr(result, name) for name in ModelIdentity.model_fields}
    )
    if identity != plan.model:
        raise ValueError("model/input/provenance identity mismatch")
    if canonicalHash(result.evidence[-1].model_dump()) != result.input_sha256:
        raise ValueError("diagnostic input evidence hash mismatch")
    if result.action_path != plan.action_paths[result.action]:
        raise ValueError("action path contract mismatch")
    if outcomes.benchmark_evidence_sha256 != plan.model.benchmark_evidence_sha256:
        raise ValueError("outcome benchmark provenance mismatch")
    if diagnostic.created_at < plan.observation_at:
        raise ValueError("diagnostic predates observation")
    expected = {(case.seed, method) for case in plan.cases for method in METHODS}
    actual = [(row.case.seed, row.method) for row in outcomes.rows]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError("complete unique matched baseline coverage required")
    cases = {case.seed: case for case in plan.cases}
    methods = {method.method: method.policy_sha256 for method in plan.methods}
    if len({row.raw_evidence_sha256 for row in outcomes.rows}) != len(outcomes.rows):
        raise ValueError("raw outcome evidence reused across independent trials")
    for row in outcomes.rows:
        if (row.network_id, row.workspace_id) != (plan.network_id, plan.workspace_id):
            raise ValueError("outcome scope mismatch")
        if row.case != cases[row.case.seed] or row.comparison != plan.comparison:
            raise ValueError("baseline comparability mismatch")
        if row.policy_sha256 != methods[row.method]:
            raise ValueError("outcome frozen policy mismatch")
        if not plan.selected_at < row.measured_start < row.measured_end:
            raise ValueError("held-out outcome preceded selection or invalid measurement interval")
        duration = (row.measured_end - row.measured_start).total_seconds()
        if duration < row.comparison.window_seconds * row.comparison.episode_steps:
            raise ValueError("incomplete episode measurement interval")


def comparisons(plan: Plan, outcomes: Outcomes) -> list[MetricComparison]:
    rows = {(row.case.seed, row.method): row for row in outcomes.rows}
    records = []
    for baseline in METHODS[1:]:
        for metric in ("reward", "goodput_mbps", "loss_fraction", "icmp_rtt_ms", "route_changes"):
            pairs, missing, deltas = [], [], []
            for seed in sorted(case.seed for case in plan.cases):
                policy_value = getattr(rows[seed, "ppo"], metric)
                baseline_value = getattr(rows[seed, baseline], metric)
                if policy_value is None or baseline_value is None:
                    missing.append(seed)
                else:
                    pairs.append(seed)
                    deltas.append(policy_value - baseline_value)
            records.append(
                MetricComparison(
                    baseline=baseline,
                    metric=metric,
                    direction="higher" if metric in ("reward", "goodput_mbps") else "lower",
                    paired_seeds=pairs,
                    missing_seeds=missing,
                    mean_policy_minus_baseline=mean(deltas) if deltas else None,
                    min_paired_difference=min(deltas) if deltas else None,
                    max_paired_difference=max(deltas) if deltas else None,
                    standard_error=stdev(deltas) / len(deltas) ** 0.5 if len(deltas) > 1 else None,
                )
            )
    return records


def evaluate(
    plan: Plan, diagnostic: Diagnostic, outcomes: Outcomes, *, now: datetime, plan_sha256: str
) -> Decision:
    """Evaluate validated/pinned imports. No model selection or recommendation execution.

    Callers doing file I/O must use loadEvaluation to verify byte-level pins first.
    Invalid identities/comparability raise; valid but unusable evidence abstains.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone-aware evaluation time required")
    validateBindings(plan, diagnostic, outcomes)
    times = [plan.observation_at, *(row.measured_start for row in outcomes.rows)]
    oldest = min(times)
    future = (
        max([diagnostic.created_at, plan.selected_at, *(row.measured_end for row in outcomes.rows)])
        > now
    )
    freshness = (
        "future"
        if future
        else (
            "stale"
            if (now - oldest).total_seconds() >= plan.max_age_seconds
            else "within_review_window"
        )
    )
    reasons = []
    if freshness != "within_review_window":
        reasons.append(f"evidence_{freshness}")
    qualified = diagnostic.result.benchmark_status == "qualified_scoped_benchmark"
    if not qualified:
        reasons.append("benchmark_not_qualified")
    if diagnostic.result.action not in plan.allowed_actions:
        reasons.append("action_outside_review_policy")
    observations = diagnostic.result.evidence
    if any(
        value is None
        for observation in observations
        for value in (
            *observation.path_capacity_mbps,
            *observation.path_utilization,
            *observation.path_queue_packets,
            observation.loss_fraction,
            observation.goodput_mbps,
            observation.actual_offered_mbps,
        )
    ):
        reasons.append("incomplete_observation")
    evidence = [
        EvidenceSource(
            kind="plan", sha256=plan_sha256, reference="operator-pinned review manifest"
        ),
        EvidenceSource(
            kind="diagnostic",
            sha256=plan.diagnostic_sha256,
            reference=f"diagnostic:{diagnostic.diagnostic_id}",
        ),
        EvidenceSource(
            kind="benchmark",
            sha256=plan.model.benchmark_evidence_sha256,
            reference="original frozen benchmark artifact",
        ),
        EvidenceSource(
            kind="outcomes",
            sha256=plan.outcomes_sha256,
            reference="operator-normalized matched seed-level outcomes",
        ),
    ]
    evidence.extend(
        EvidenceSource(
            kind="raw_outcome",
            sha256=row.raw_evidence_sha256,
            reference=f"outcome:{row.case.seed}:{row.method}",
        )
        for row in sorted(outcomes.rows, key=lambda row: (row.case.seed, row.method))
    )
    alternatives = [
        Alternative(
            option="hold_and_review",
            rationale="Retain operator control; inspect evidence and limitations.",
            evidence_references=["plan:allowed_actions"],
        )
    ]
    alternatives.extend(
        Alternative(
            option=method,
            rationale="Frozen matched baseline; see paired metric differences.",
            evidence_references=[f"outcomes:{method}"],
        )
        for method in METHODS[1:]
    )
    return Decision(
        network_id=plan.network_id,
        workspace_id=plan.workspace_id,
        diagnostic_id=diagnostic.diagnostic_id,
        model=plan.model,
        status="abstain" if reasons else "review",
        abstention_reasons=reasons,
        rationale=(
            "Evidence is unsuitable for a current shadow review; retain historical diagnostics."
            if reasons
            else "Review frozen inference alongside matched historical outcomes. "
            "Comparisons do not establish benefit from executing this diagnostic action."
        ),
        diagnostic_action=diagnostic.result.action,
        diagnostic_action_path=diagnostic.result.action_path,
        evidence=evidence,
        alternatives=alternatives,
        assumptions=[
            "The operator manifest is trusted; hashes bind bytes, not authenticity.",
            "Outcome normalization and raw measurements require independent operator audit.",
            "Freeze/selection/acquisition times are attestations, not a timestamp authority.",
            "One seed-level episode is a replication; packets/windows are not independent samples.",
            "Diagnostic history and benchmark episodes are distinct historical evidence.",
            "No held-out outcome selects a model, changes a threshold or enters a domain agent.",
        ],
        qualification=Qualification(
            status="reported_scoped_benchmark_only" if qualified else "not_qualified",
            scope=diagnostic.result.benchmark_scope,
            limitations=diagnostic.result.benchmark_limitations,
        ),
        freshness=Freshness(
            status=freshness,
            oldest_evidence_at=oldest,
            evaluated_at=now,
            max_age_seconds=plan.max_age_seconds,
        ),
        findings=analyze(plan, observations, diagnostic.result.action),
        comparisons=comparisons(plan, outcomes),
        unavailable_providers=[
            "compatible_live_observer",
            "calibrated_safety_bounds",
            "authorized_executor",
            "governed_recovery",
            "llm_domain_agents",
        ],
    )
