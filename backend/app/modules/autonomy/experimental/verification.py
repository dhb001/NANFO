"""Raw measured verification and paired comparisons for bounded ADR025 trials."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from app.modules.autonomy.experimental.metrics import _count, measured_metrics  # noqa: F401 - re-export
from app.modules.autonomy.experimental.simulation import (
    ActionProposal,
    Contract,
    FrozenMeasuredFrame,
    Nonnegative,
    frame_digest,
    fresh_frame,
)
from app.modules.simulation.evaluator import digest
from app.modules.simulation.schemas import Digest, Identifier


class VerificationPolicy(Contract):
    version: Literal[1]
    max_observation_age_seconds: float = Field(gt=0, le=30)
    min_goodput_mbps: Nonnegative
    max_udp_loss_pct: float = Field(ge=0, le=100)
    max_probe_loss_pct: float = Field(ge=0, le=100)
    max_rtt_ms: Nonnegative
    min_probe_sent: int = Field(default=1, strict=True, ge=1)
    min_traffic_bytes: int = Field(default=1, strict=True, ge=1)
    # Complete independently read kernel node paths, including endpoint hosts.
    foreground_nodes: list[list[Identifier]] = Field(min_length=2, max_length=2)
    background_nodes: list[Identifier] = Field(min_length=3, max_length=128)

    @model_validator(mode="after")
    def routes(self):
        if (any(not 3 <= len(path) <= 128 or len(set(path)) != len(path)
                for path in self.foreground_nodes + [self.background_nodes])
                or self.foreground_nodes[0] == self.foreground_nodes[1]
                or self.foreground_nodes[0][0] != self.foreground_nodes[1][0]
                or self.foreground_nodes[0][-1] != self.foreground_nodes[1][-1]):
            raise ValueError("verification_exact_paths_required")
        return self


def _route_checks(frame, policy, action_index):
    evidence = frame.raw["evidence"]
    expected = policy.foreground_nodes[action_index]
    for key in ("route", "route_end"):
        if evidence[key]["path"] != expected[1:-1]:
            return False
    # Start readback can legitimately precede the action. End readback must
    # independently walk both selected directions and the unchanged background.
    # Qualified frozen v4 retains MatchedRouting.readback inside route_end;
    # later v5 additionally records stationaryReadback. Both contain actual
    # bidirectional kernel walks, never construct them from selected action IDs.
    readback = evidence["route_end"].get("readback")
    if readback is None:
        readback = evidence.get("routing_health_end")
    paths = readback["paths"]
    for nodes in (expected, policy.background_nodes):
        for path in (nodes, list(reversed(nodes))):
            row = paths[f"{path[0]}->{path[-1]}"]
            if row["nodes"] != path or not row.get("kernel_routes"):
                return False
    return True


def _same_experiment(before, after):
    return (before.network_id == after.network_id and before.workspace_id == after.workspace_id
            and before.runtime_sha256 == after.runtime_sha256
            and all(before.raw.get(key) == after.raw.get(key)
                    for key in ("seed", "scenario", "episode_id", "mode"))
            and all(before.raw["evidence"].get(key) == after.raw["evidence"].get(key)
                    for key in ("provenance", "spec_hash", "environment_spec")))


def verify_post_action(*, before, after, action, policy, policy_sha256,
                       action_completed_at: datetime, now: datetime,
                       purpose: Literal["post_action", "restoration"] = "post_action"):
    """Return missing/fail/keep/restoration; only keep permits continued holding.

    `restoration` means a fresh measured restoration passed the same checks, not
    a request or acknowledgement. For failures `restoration_required` stays true.
    """
    before = FrozenMeasuredFrame.model_validate(before)
    action = ActionProposal.model_validate(action)
    policy = VerificationPolicy.model_validate(policy)
    if purpose not in ("post_action", "restoration"):
        raise ValueError("invalid_verification_purpose")
    # Validate the externally installed whole-policy hash as well as this policy.
    binding = VerificationBinding(observation_sha256=frame_digest(before),
        action_sha256=digest(action.model_dump(mode="json")), policy_sha256=policy_sha256,
        verification_policy_sha256=digest(policy.model_dump(mode="json")))
    status, reasons, metrics, after_hash = "missing", [], None, None
    checks = {}
    try:
        if after is None:
            raise ValueError("post_action_frame_missing")
        after = FrozenMeasuredFrame.model_validate(after)
        after_hash = frame_digest(after)
        fresh_frame(after, now=now, max_age=policy.max_observation_age_seconds)
        if (action_completed_at.utcoffset() is None or not before.observed_at <= action_completed_at
                or not action_completed_at < after.window_started_at
                or after.observed_at <= before.observed_at):
            raise ValueError("post_action_window_not_fresh_after_action")
        if not _same_experiment(before, after):
            raise ValueError("post_action_scope_seed_or_runtime_mismatch")
        route_pass = _route_checks(after, policy, action.action_index)
        metrics = measured_metrics(after)
        checks = {"route": route_pass,
            "probe_count": None if metrics["probe_sent"] == 0 else metrics["probe_sent"] >= policy.min_probe_sent,
            "traffic_count": None if metrics["traffic_bytes"] == 0 else metrics["traffic_bytes"] >= policy.min_traffic_bytes,
            "goodput": None if metrics["goodput_mbps"] is None else metrics["goodput_mbps"] >= policy.min_goodput_mbps,
            "udp_loss": None if metrics["udp_loss_pct"] is None else metrics["udp_loss_pct"] <= policy.max_udp_loss_pct,
            "probe_loss": None if metrics["probe_loss_pct"] is None else metrics["probe_loss_pct"] <= policy.max_probe_loss_pct,
            "rtt": None if metrics["rtt_ms"] is None else metrics["rtt_ms"] <= policy.max_rtt_ms,
            "service_available": not metrics["service_outage"]}
        if any(value is False for value in checks.values()):
            status = "fail"
            reasons = [key for key, value in checks.items() if value is False]
        elif any(value is None for value in checks.values()):
            reasons = [key + "_unavailable" for key, value in checks.items() if value is None]
        else:
            status = "restoration" if purpose == "restoration" else "keep"
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        reasons = ["missing_stale_invalid_or_mismatched_raw_evidence"]
    result = {"status": status, "purpose": purpose, "keep": status == "keep",
        "restoration_required": status in ("missing", "fail"), "reasons": reasons, "checks": checks,
        "metrics": metrics, "binding": binding.model_dump(mode="json"), "after_sha256": after_hash,
        "action_completed_at": action_completed_at.isoformat(), "verified_at": now.isoformat(),
        "physical_safety_authorized": False, "source": "measured_lab_evidence"}
    return {**result, "verification_sha256": digest(result)}


def verification_record(*, before, after, prepared, policy, action_completed_at, now):
    """Bridge raw independent acquisition to the core Transport.verify record.

    The transport owns acquisition and supplies actual completion time. Retain
    the complete classification in provenance; unknown/failed evidence cannot
    become an affirmative route_verified record.
    """
    from .schemas import (
        ExperimentalPolicy,
        PreparedAction,
        VerificationRecord,
        contract_digest,
    )
    from .simulation import from_core_frame

    policy = ExperimentalPolicy.model_validate(policy)
    prepared = PreparedAction.model_validate(prepared)
    command = prepared.command
    if (command.policy_sha256 != contract_digest(policy) or command.runtime != policy.runtime
            or command.run_id != policy.run_id or command.network_id != policy.network_id
            or command.workspace_id != policy.workspace_id):
        raise ValueError("verification_command_policy_mismatch")
    if command.frame_sha256 != contract_digest(before):
        raise ValueError("verification_preaction_frame_binding_mismatch")
    routes = [i for i, route in enumerate(policy.routes) if route == command.route]
    if len(routes) != 1 or len(policy.routes) != 2:
        raise ValueError("verification_command_route_mismatch")
    # Core simulation paths may omit endpoint access links. Verification uses
    # separately installed complete kernel paths (including hosts).
    nodes = policy.assumptions.get("verification_paths")
    if nodes is None or not isinstance(nodes, dict):
        raise ValueError("installed_verification_paths_missing")
    thresholds = VerificationPolicy(version=1,
        max_observation_age_seconds=policy.max_observation_age_seconds,
        min_goodput_mbps=policy.verification.min_goodput_mbps,
        max_udp_loss_pct=policy.verification.max_loss_fraction * 100,
        max_probe_loss_pct=policy.verification.max_probe_loss_fraction * 100,
        max_rtt_ms=policy.verification.max_rtt_ms,
        min_probe_sent=policy.verification.min_probe_sent,
        min_traffic_bytes=policy.verification.min_traffic_bytes,
        foreground_nodes=nodes["foreground_nodes"], background_nodes=nodes["background_nodes"])
    pre = from_core_frame(before)
    post = from_core_frame(after) if after is not None else None
    result = verify_post_action(before=pre, after=post,
        action=ActionProposal(intent_id=command.request_id, action_id=command.route.action_id,
            action_index=routes[0], plan_sha256=contract_digest(command)),
        policy=thresholds, policy_sha256=contract_digest(policy), action_completed_at=action_completed_at, now=now)
    metrics = result["metrics"] or {}
    return VerificationRecord(request_id=command.request_id, action_sha256=contract_digest(prepared),
        run_id=command.run_id, action_id=command.route.action_id,
        route_verified=result["status"] == "keep", observed_at=post.observed_at if post else pre.observed_at,
        window_started_at=post.window_started_at if post else pre.window_started_at,
        goodput_mbps=metrics.get("goodput_mbps"),
        loss_fraction=metrics["udp_loss_pct"] / 100 if metrics.get("udp_loss_pct") is not None else None,
        rtt_ms=metrics.get("rtt_ms"), probe_sent=metrics.get("probe_sent"),
        probe_received=metrics.get("probe_received"), traffic_bytes=metrics.get("traffic_bytes"),
        provenance={"verification": result, "raw_before_sha256": pre.raw_sha256,
                    "raw_after_sha256": post.raw_sha256 if post else None})


class VerificationBinding(Contract):
    observation_sha256: Digest
    action_sha256: Digest
    policy_sha256: Digest
    verification_policy_sha256: Digest


class ObservedTiming(Contract):
    """Endpoints recorded by the controller on one real monotonic clock."""

    clock_id: str = Field(min_length=1, max_length=128)
    evidence_sha256: Digest
    started_seconds: Nonnegative
    finished_seconds: Nonnegative

    @model_validator(mode="after")
    def chronology(self):
        if self.finished_seconds < self.started_seconds:
            raise ValueError("observed_timing_reversed")
        return self


class PerformanceTrial(Contract):
    comparator: Literal["experimental", "fixed0", "fixed1", "heuristic"]
    frame: FrozenMeasuredFrame
    # Shared preregistered workload/scenario/window identity, not result hashes.
    workload_sha256: Digest
    # Shared gates are separate from full policy hashes (which include run IDs).
    admission_policy_sha256: Digest
    simulation_sha256: Digest
    selected_action_index: int = Field(strict=True, ge=0, le=1)
    outcome: Literal["measured", "predispatch_rejected"] = "measured"
    mutation_count: int = Field(strict=True, ge=0)
    window_index: int = Field(strict=True, ge=0)
    decision_timing: ObservedTiming | None = None
    action_timing: ObservedTiming | None = None
    recovery_timing: ObservedTiming | None = None
    collected_at: AwareDatetime

    @model_validator(mode="after")
    def honest_outcome(self):
        if (self.comparator in ("fixed0", "fixed1")
                and self.selected_action_index != int(self.comparator[-1])):
            raise ValueError("fixed_comparator_selection_mismatch")
        if self.outcome == "predispatch_rejected" and (
                self.mutation_count != 0 or self.action_timing is not None or self.recovery_timing is not None):
            raise ValueError("predispatch_rejection_requires_zero_mutation_no_action_metrics")
        return self


def paired_performance(trials):
    """Require complete one-to-one same-seed pairs; preserve unavailable results.

    No bootstrap confidence or speedup is invented. Differences are experimental
    minus comparator; goodput positive is better, loss/RTT/time negative is better.
    """
    trials = [PerformanceTrial.model_validate(trial) for trial in trials]
    groups = {}
    for trial in trials:
        raw = trial.frame.raw
        key = (raw["seed"], raw["scenario"], trial.window_index)
        group = groups.setdefault(key, {})
        if trial.comparator in group:
            raise ValueError("duplicate_paired_trial")
        group[trial.comparator] = trial
    if not groups:
        raise ValueError("paired_trials_missing")
    pairs = []
    for key, group in sorted(groups.items()):
        if set(group) != {"experimental", "fixed0", "fixed1", "heuristic"}:
            raise ValueError("paired_comparators_or_seeds_missing")
        reference = group["experimental"]
        def identity(trial):
            return (str(trial.frame.network_id), str(trial.frame.workspace_id),
                trial.frame.runtime_sha256, trial.workload_sha256, trial.admission_policy_sha256,
                digest({k: trial.frame.raw["evidence"].get(k) for k in ("provenance", "spec_hash", "environment_spec")}),
                # Stationary workload values must match; phase index differs between
                # a predispatch rejection and a completed postaction measurement.
                digest({k: v for k, v in trial.frame.raw["evidence"].get("phase", {}).items() if k != "phase_index"}),
                trial.frame.raw["evidence"].get("desired_window_seconds"))
        if any(identity(trial) != identity(reference) for trial in group.values()):
            raise ValueError("paired_scope_runtime_or_workload_mismatch")
        values, unavailable = {}, {}
        for comparator, trial in group.items():
            if trial.outcome == "predispatch_rejected":
                # This frame is the PREdecision observation. Do not advertise its
                # traffic as the performance of a route that was never dispatched.
                values[comparator] = None
                unavailable[comparator] = "predispatch_rejected_zero_mutation_no_postaction_metrics"
                continue
            try:
                # Historical reports check freshness at actual collection, not now.
                fresh_frame(trial.frame, now=trial.collected_at, max_age=30)
                metrics = measured_metrics(trial.frame)
                if trial.frame.raw["observation"]["previous_action"] != trial.selected_action_index:
                    raise ValueError("fixed_comparator_action_mismatch")
                values[comparator] = {key: metrics[key] for key in (
                    "goodput_mbps", "udp_loss_pct", "probe_loss_pct", "rtt_ms", "service_window_seconds")}
                for name in ("decision", "action", "recovery"):
                    timing = getattr(trial, name + "_timing")
                    values[comparator][name + "_seconds"] = (
                        timing.finished_seconds - timing.started_seconds if timing else None)
            except (ValueError, KeyError, TypeError, IndexError):
                values[comparator] = None
                unavailable[comparator] = "invalid_or_missing_measured_evidence"
        deltas = {}
        for comparator in ("fixed0", "fixed1", "heuristic"):
            left, right = values["experimental"], values[comparator]
            deltas[comparator] = None if left is None or right is None else {
                metric: left[metric] - right[metric] if left[metric] is not None and right[metric] is not None else None
                for metric in left}
        pairs.append({"seed": key[0], "scenario": key[1], "window_index": key[2],
            "metrics": values, "deltas": deltas, "unavailable": unavailable,
            "admission_policy_sha256": reference.admission_policy_sha256,
            "outcomes": {name: {"status": trial.outcome, "mutation_count": trial.mutation_count,
                "simulation_sha256": trial.simulation_sha256,
                "selected_action_index": trial.selected_action_index} for name, trial in group.items()},
            "trial_sha256": {name: digest(trial.model_dump(mode="json")) for name, trial in group.items()}})
    report = {"source": "paired_measured_lab_evidence", "pairs": pairs, "pair_count": len(pairs),
              "physical_safety_authorized": False}
    return {**report, "comparison_sha256": digest(report)}
