"""ADR025 pure configured-model adapter; never physical safety authorization."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.modules.simulation.evaluator import (
    advance,
    canonical_config,
    digest,
    initial_checkpoint,
    output,
)
from app.modules.simulation.schemas import (
    Digest,
    Identifier,
    ScenarioConfig,
    ScenarioLimits,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, revalidate_instances="always")


Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]


def number(value, *, positive=False):
    """Raw evidence must contain finite JSON numbers, never bools/coerced strings."""
    if (type(value) not in (int, float) or not math.isfinite(value)
            or value < 0 or positive and value == 0):
        raise ValueError("invalid_measured_number")
    return float(value)


class FrozenMeasuredFrame(Contract):
    network_id: UUID
    workspace_id: UUID
    runtime_sha256: Digest
    window_started_at: AwareDatetime
    observed_at: AwareDatetime
    raw_sha256: Digest
    raw: dict

    @model_validator(mode="after")
    def bound(self):
        if self.window_started_at >= self.observed_at or digest(self.raw) != self.raw_sha256:
            raise ValueError("frame_chronology_or_digest_mismatch")
        if (type(self.raw.get("seed")) is not int or not 0 <= self.raw["seed"] < 2**63
                or not isinstance(self.raw.get("episode_id"), str)
                or not self.raw["episode_id"] or self.raw.get("mode") != "matched"
                or not isinstance(self.raw.get("scenario"), str) or not self.raw["scenario"]):
            raise ValueError("frame_scope_invalid")
        return self


class LinkAssumption(Contract):
    link_id: Identifier
    source: Identifier
    target: Identifier
    capacity_source: Literal["htb_readback", "link_plan"]
    # HTB identifies exact egress; link_plan identifies exact endpoint pair.
    node: Identifier
    interface: Identifier
    buffer_bytes: Annotated[float, Field(ge=0, le=1e12)]
    initial_queue_bytes: Annotated[float, Field(ge=0, le=1e12)]
    delay_ms: Annotated[float, Field(ge=0, le=60000)]
    source_label: Literal["operator_configured_model"]


class SimulationAssumptions(Contract):
    version: Literal[1]
    links: list[LinkAssumption] = Field(min_length=1, max_length=128)
    foreground_paths: list[list[Identifier]] = Field(min_length=2, max_length=2)
    background_path: list[Identifier] = Field(min_length=1, max_length=128)
    tick_ms: int = Field(strict=True, ge=1, le=1000)
    duration_ticks: int = Field(strict=True, ge=1, le=1000)
    max_observation_age_seconds: Annotated[float, Field(gt=0, le=30)]
    limits: ScenarioLimits

    @model_validator(mode="after")
    def exact_paths(self):
        ids = [link.link_id for link in self.links]
        paths = self.foreground_paths + [self.background_path]
        if (len(ids) != len(set(ids)) or self.foreground_paths[0] == self.foreground_paths[1]
                or any(not path or len(path) > 128 for path in paths)
                or set(ids) != {link for path in paths for link in path}
                or len({(link.node, link.interface) for link in self.links}) != len(ids)):
            raise ValueError("assumptions_require_exact_two_paths_and_background")
        links = {link.link_id: link for link in self.links}
        if len({(links[path[0]].source, links[path[-1]].target)
                for path in self.foreground_paths}) != 1:
            raise ValueError("foreground_endpoint_mismatch")
        return self


class ActionProposal(Contract):
    intent_id: UUID
    action_id: Identifier
    action_index: int = Field(strict=True, ge=0, le=1)
    plan_sha256: Digest


def frame_digest(frame: FrozenMeasuredFrame) -> str:
    return digest(frame.model_dump(mode="json"))


def fresh_frame(frame, *, now: datetime, max_age: float):
    if now.utcoffset() is None or not 0 <= (now - frame.observed_at).total_seconds() <= max_age:
        raise ValueError("frame_stale_or_future")
    evidence = frame.raw.get("evidence", {})
    if (evidence.get("measurement_complete") is not True or evidence.get("error") is not None
            or frame.raw.get("truncated") is not False or frame.raw.get("terminated") is not False
            or evidence.get("cleanup_verified") is True):
        raise ValueError("frame_incomplete_or_terminal")
    if (not evidence.get("provenance") or not evidence.get("environment_spec")
            or not evidence.get("spec_hash")):
        raise ValueError("frame_runtime_provenance_missing")
    return evidence


def sender_rates(evidence):
    senders = evidence.get("udp_sent")
    if not isinstance(senders, list) or len(senders) != 2:
        raise ValueError("both_raw_senders_required")
    rates = []
    for sender in senders:
        byte_count = sender.get("bytes")
        if type(byte_count) is not int or byte_count < 0:
            raise ValueError("invalid_sender_bytes")
        rates.append(byte_count * 8 / number(sender.get("duration_seconds"), positive=True) / 1e6)
    return rates


def _capacity(evidence, link):
    if link.capacity_source == "htb_readback":
        capacities = []
        for key in ("capacity_readback", "capacity_readback_end"):
            rows = [row for row in evidence.get(key, [])
                    if row.get("node") == link.node and row.get("interface") == link.interface]
            if len(rows) != 1 or link.node != link.source:
                raise ValueError("capacity_exact_egress_missing")
            row = rows[0]
            # Parse actual retained tc JSON, not the convenient capacity label.
            classes = _raw_classes(row["raw"])
            owned = [item for item in classes if item.get("kind") == "htb" and item.get("handle") == "5:1"]
            if len(owned) != 1:
                raise ValueError("capacity_htb_class_missing")
            options = owned[0]["options"]
            rate = number(options.get("rate"), positive=True) * 8 / 1e6
            if (number(options.get("ceil"), positive=True) * 8 / 1e6 != rate
                    or number(row.get("capacity_mbps"), positive=True) != rate):
                raise ValueError("capacity_readback_inconsistent")
            capacities.append(rate)
        if capacities[0] != capacities[1]:
            raise ValueError("capacity_changed_in_window")
        return capacities[0]
    plans = evidence.get("linkPlan", evidence.get("environment_spec", {}).get("links"))
    if not isinstance(plans, list):
        raise TypeError("raw_link_plan_missing")
    rows = [row for row in plans if {row["a"][0], row["b"][0]} == {link.source, link.target}]
    if len(rows) != 1:
        raise ValueError("raw_link_plan_ambiguous")
    # Shaped egresses cannot silently fall back to nominal manifest capacities.
    if any(row.get("node") == link.node and row.get("interface") == link.interface
           for row in evidence.get("capacity_readback", [])):
        raise ValueError("shaped_egress_requires_htb_readback")
    return number(rows[0].get("capacity_mbps"), positive=True)


def _raw_classes(raw):
    """Decode only HTB rate/ceil evidence, without importing an actuating driver.

    Qualified Bullseye tc prints text even with -j for classes. Preserve that
    authentic format rather than requiring a rewritten JSON frame.
    """
    if not isinstance(raw, str) or len(raw) > 65536:
        raise ValueError("bounded_raw_htb_readback_required")
    if raw.lstrip().startswith("["):
        return json.loads(raw)
    rows = []
    for line in raw.strip().splitlines():
        match = re.fullmatch(
            r"class htb (\S+) (?:root|parent \S+) (?:leaf \S+ )?prio \d+ "
            r"rate ([\d.]+)([KMG]?)bit ceil ([\d.]+)([KMG]?)bit burst \S+ cburst \S+\s*", line)
        if match is None:
            raise ValueError("unsupported_raw_htb_class")
        handle, rate, unit, ceiling, ceiling_unit = match.groups()
        scale = {"": 1, "K": 1000, "M": 1000000, "G": 1000000000}
        rows.append({"kind": "htb", "handle": handle, "options": {
            "rate": float(rate) * scale[unit] / 8, "ceil": float(ceiling) * scale[ceiling_unit] / 8}})
    return rows


def _checks(metrics, limits):
    return {
        "max_loss_pct": metrics.get("loss_pct") is not None and metrics["loss_pct"] <= limits.max_loss_pct,
        "max_latency_ms": metrics.get("latency_ms") is not None and metrics["latency_ms"] <= limits.max_latency_ms,
        "min_throughput_mbps": metrics.get("throughput_mbps") is not None
        and metrics["throughput_mbps"] >= limits.min_throughput_mbps,
    }


def evaluate_actions(*, frame, assumptions, actions, policy_sha256, now):
    """Run both registered actions against the same frozen demand and thresholds.

    The caller installs/protects assumptions and policy before acquisition and
    persists the returned binding before dispatch. Exceptions are predispatch blocks.
    """
    frame = FrozenMeasuredFrame.model_validate(frame)
    assumptions = SimulationAssumptions.model_validate(assumptions)
    actions = [ActionProposal.model_validate(action) for action in actions]
    if (len(actions) != 2 or {action.action_index for action in actions} != {0, 1}
            or len({action.action_id for action in actions}) != 2):
        raise ValueError("exact_two_action_proposals_required")
    evidence = fresh_frame(frame, now=now, max_age=assumptions.max_observation_age_seconds)
    # Validate the actual frozen raw measurement, not its complete flag alone.
    from .verification import measured_metrics

    try:
        measured_metrics(frame)
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError("raw_measurement_evidence_invalid") from exc
    rates = sender_rates(evidence)
    links = []
    try:
        for link in assumptions.links:
            links.append({key: getattr(link, key) for key in (
                "link_id", "source", "target", "buffer_bytes", "initial_queue_bytes", "delay_ms")}
                | {"capacity_mbps": _capacity(evidence, link)})
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError("raw_capacity_evidence_invalid") from exc
    by_id = {link["link_id"]: link for link in links}
    results = []
    for action in sorted(actions, key=lambda action: action.action_index):
        binding = SimulationBinding(
            observation_sha256=frame_digest(frame), action_sha256=digest(action.model_dump(mode="json")),
            policy_sha256=policy_sha256, assumptions_sha256=digest(assumptions.model_dump(mode="json")))
        flows = []
        for name, path, rate in zip(("foreground", "background"),
                (assumptions.foreground_paths[action.action_index], assumptions.background_path), rates):
            flows.append({"flow_id": name, "source": by_id[path[0]]["source"],
                "target": by_id[path[-1]]["target"], "path": path, "demand_mbps": [rate]})
        config = ScenarioConfig.model_validate({"version": 1, "seed": frame.raw["seed"],
            "tick_ms": assumptions.tick_ms, "duration_ticks": assumptions.duration_ticks, "links": links, "flows": flows,
            "action_binding": {"intent_id": action.intent_id, "plan_sha256": action.plan_sha256,
                                "network_state_sha256": frame_digest(frame)}, "limits": assumptions.limits})
        checkpoint = initial_checkpoint(config)
        while checkpoint["state"]["tick"] < config.duration_ticks:
            checkpoint = advance(config, checkpoint, ticks=32)
        result = output(config, checkpoint)
        checks = _checks(result["flows"]["foreground"], config.limits)
        admission = {"action": action.model_dump(mode="json"), "scenario_config": canonical_config(config),
            "scenario_sha256": result["input_sha256"], "result": result, "result_sha256": result["output_sha256"],
            "binding": binding.model_dump(mode="json"), "assumptions": assumptions.model_dump(mode="json"),
            "foreground_checks": checks,
            "metric_semantics": {"modeled_latency": "delivered-byte-weighted residence time, not ICMP RTT",
                "modeled_loss": "dropped/offered fluid bytes percent",
                "modeled_throughput": "delivered fluid bytes over configured model horizon",
                "demand": "actual raw sender bytes over sender lifetime; modeled constant over horizon"},
            "risk_gate": "passed" if result["risk_gate"] == "passed" and all(checks.values()) else "blocked",
            "source": "operator_configured_model", "physical_safety_authorized": False}
        results.append({**admission, "admission_sha256": digest(admission)})
    return results


class SimulationBinding(Contract):
    observation_sha256: Digest
    action_sha256: Digest
    policy_sha256: Digest
    assumptions_sha256: Digest


def validate_admission(admission, *, frame, assumptions, action, policy_sha256, now):
    """Validate binding and independently replay the actual evaluator before dispatch."""
    frame = FrozenMeasuredFrame.model_validate(frame)
    assumptions = SimulationAssumptions.model_validate(assumptions)
    action = ActionProposal.model_validate(action)
    fresh_frame(frame, now=now, max_age=assumptions.max_observation_age_seconds)
    binding = SimulationBinding(observation_sha256=frame_digest(frame),
        action_sha256=digest(action.model_dump(mode="json")), policy_sha256=policy_sha256,
        assumptions_sha256=digest(assumptions.model_dump(mode="json")))
    if (admission.get("binding") != binding.model_dump(mode="json")
            or admission.get("admission_sha256") != digest({k: v for k, v in admission.items() if k != "admission_sha256"})):
        raise ValueError("simulation_binding_mismatch")
    # Regenerate both path evaluations rather than trusting mutable embedded config/results.
    other = action.model_copy(update={"action_id": "validation-alternative", "action_index": 1 - action.action_index})
    if other.action_id == action.action_id:
        other = other.model_copy(update={"action_id": "validation-other"})
    expected = evaluate_actions(frame=frame, assumptions=assumptions, actions=[action, other],
                                policy_sha256=policy_sha256, now=now)[action.action_index]
    if admission != expected or admission["risk_gate"] != "passed":
        raise ValueError("simulation_not_reproducible_or_blocked")
    return admission


def evaluator_sha256():
    """Installed evaluator/schema/adapter source identity for protected policy pins."""
    from app.modules.simulation import evaluator, schemas

    from . import verification

    return digest({name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ("evaluator", evaluator.__file__), ("schemas", schemas.__file__), ("adapter", __file__),
        ("raw_verification", verification.__file__))})


def from_core_frame(frame):
    """Preserve the core's single unchanged frozen frame and trusted clock binding."""
    from .schemas import MeasuredFrame

    frame = MeasuredFrame.model_validate(frame)
    frames = frame.snapshot.history["frames"]
    if len(frames) != 1 or frames[0]["response"].get("ok") is not True:
        raise ValueError("single_successful_frozen_frame_required")
    raw = frames[0]["response"]["data"]
    return FrozenMeasuredFrame(network_id=frame.snapshot.network_id, workspace_id=frame.snapshot.workspace_id,
        runtime_sha256=digest(frame.runtime.model_dump(mode="json")),
        window_started_at=frame.snapshot.window_started_at, observed_at=frame.snapshot.observed_at,
        raw_sha256=digest(raw), raw=raw)


class ConfiguredSimulator:
    """Implements core ports.Simulator; uses installed policy, never actor inputs."""

    def __init__(self, *, clock=None):
        self.clock = clock or (lambda: datetime.now(UTC))

    async def simulate(self, frame, inference, policy):
        from .authority import inference_allowed
        from .schemas import (
            ExperimentalPolicy,
            InferenceRecord,
            MeasuredFrame,
            SimulationRecord,
            contract_digest,
        )

        frame = MeasuredFrame.model_validate(frame)
        inference = InferenceRecord.model_validate(inference)
        policy = ExperimentalPolicy.model_validate(policy)
        if (policy.evaluator_sha256 != evaluator_sha256() or len(policy.routes) != 2
                or frame.runtime != policy.runtime or frame.snapshot.network_id != policy.network_id
                or frame.snapshot.workspace_id != policy.workspace_id
                or inference.frame_sha256 != contract_digest(frame)):
            raise ValueError("installed_simulator_binding_mismatch")
        # Core owns selector semantics, including honest non-model comparators.
        # No qualification/probability is synthesized here for a baseline.
        inference_allowed(policy, frame, inference)
        model_assumptions = {key: value for key, value in policy.assumptions.items() if key != "verification_paths"}
        assumptions = SimulationAssumptions.model_validate({**model_assumptions,
            "limits": policy.objectives, "max_observation_age_seconds": policy.max_observation_age_seconds})
        if "limits" in policy.assumptions or "max_observation_age_seconds" in policy.assumptions:
            raise ValueError("duplicate_policy_objectives_or_age")
        links = {link.link_id: link for link in assumptions.links}
        for route, path in zip(policy.routes, assumptions.foreground_paths):
            nodes = [links[path[0]].source, *(links[link].target for link in path)]
            if list(route.path) != nodes:
                raise ValueError("registered_simulation_route_mismatch")
        actions = [ActionProposal(intent_id=uuid5(policy.run_id, contract_digest(inference) + route.action_id),
            action_id=route.action_id, action_index=index,
            # Command does not exist yet (it includes the simulation hash). Bind
            # the exact registered route + proposal + policy; core binds the later command.
            plan_sha256=digest({"route": route.model_dump(mode="json"),
                "inference_sha256": contract_digest(inference), "policy_sha256": contract_digest(policy)}))
            for index, route in enumerate(policy.routes)]
        selected = [index for index, route in enumerate(policy.routes) if route.action_id == inference.proposal.action_id]
        if len(selected) != 1 or inference.result.action != selected[0]:
            raise ValueError("inference_action_index_mismatch")
        results = await asyncio.to_thread(evaluate_actions, frame=from_core_frame(frame), assumptions=assumptions,
            actions=actions, policy_sha256=contract_digest(policy), now=self.clock())
        chosen = results[selected[0]]
        return SimulationRecord(frame_sha256=contract_digest(frame), inference_sha256=contract_digest(inference),
            policy_sha256=contract_digest(policy), action_id=inference.proposal.action_id,
            admitted=chosen["risk_gate"] == "passed", assumptions=policy.assumptions,
            objectives=policy.objectives, reasons=() if chosen["risk_gate"] == "passed" else ("configured_model_objectives_failed",),
            evaluator_sha256=evaluator_sha256(), result={"selected": chosen, "per_action": results,
                "policy_kind": inference.policy_kind,
                "admission_policy_sha256": admission_policy_sha256(policy),
                "predispatch_status": "admitted" if chosen["risk_gate"] == "passed" else "rejected",
                "physical_safety_authorized": False})


def admission_policy_sha256(policy):
    """Comparable admission semantics, excluding selector and per-run identities.

    Full policy identity still binds every simulation/command. This additional
    digest prevents campaign reports pairing lanes with relaxed numerical gates.
    """
    from .schemas import ExperimentalPolicy

    policy = ExperimentalPolicy.model_validate(policy)
    return digest({"assumptions": policy.assumptions, "objectives": policy.objectives,
        "verification": policy.verification.model_dump(mode="json"),
        "evaluator_sha256": policy.evaluator_sha256,
        "routes": [route.model_dump(mode="json") for route in policy.routes],
        "max_observation_age_seconds": policy.max_observation_age_seconds,
        "min_dwell_seconds": policy.min_dwell_seconds,
        "max_action_duration_seconds": policy.max_action_duration_seconds,
        "action_window_seconds": policy.action_window_seconds,
        "max_actions_per_window": policy.max_actions_per_window,
        "max_actions": policy.max_actions})
