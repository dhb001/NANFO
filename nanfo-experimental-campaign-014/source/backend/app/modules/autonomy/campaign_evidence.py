"""Independent ADR013 V3 campaign reconstruction, never tensor replay or activation.

Raw Linux/FRR evidence is inspected as data. No producer code is imported/executed.
Physical endpoint calibration and pressure-swap tensor replay remain explicit gates.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from app.modules.autonomy.artifact_io import (
    MAX_ARTIFACT,
    SHA256,
    ArtifactStore,
    EvidenceError,
    StrictEvidence,
    parse_json,
)
from app.modules.autonomy.qualification import (
    CheckpointManifest,
    ProducerQualification,
    inspect_checkpoint_bytes,
    validate_producer_qualification,
)

CONTRACT_HASH = "bbcbbadec55792fa3f01bef511c1e38b0e433e125f896cdc3e64f823325e0fe6"
PORTS = (
    ("access1-eth1", "dist1-eth3", "dist1-eth4", "access2-eth1"),
    ("access1-eth2", "dist2-eth3", "dist2-eth4", "access2-eth2"),
)
Nonnegative = Annotated[float, Field(ge=0, le=1e15)]
Count = Annotated[int, Field(ge=0, le=2**63 - 1)]
Pair = Annotated[list[Nonnegative], Field(min_length=2, max_length=2)]


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def require(condition, reason):
    if not condition:
        raise EvidenceError(reason)


def same(
    actual, expected, reason="raw_derived_measurement_mismatch", *, tolerance=1e-8
):
    require(
        type(actual) in (int, float)
        and math.isfinite(actual)
        and math.isclose(actual, expected, rel_tol=1e-6, abs_tol=tolerance),
        reason,
    )


class RawObservation(StrictEvidence):
    path_capacity_mbps: Pair
    path_utilization: Pair
    path_queue_packets: Pair
    latency_ms: Nonnegative | None
    loss_fraction: Annotated[float, Field(ge=0, le=1)]
    goodput_mbps: Nonnegative
    offered_mbps: Nonnegative
    actual_offered_mbps: Nonnegative
    background_mbps: Nonnegative
    previous_action: Annotated[int, Field(ge=0, le=1)]
    seconds_since_change: Nonnegative


class RawRequest(StrictEvidence):
    version: Annotated[int, Field(ge=1, le=1)]
    command: Literal["reset", "step", "close"]
    episode_id: str | None
    episode_steps: Annotated[int, Field(ge=2, le=64)]
    mode: Literal["matched", "ospf"]
    scenario: Literal["path0", "path1"]
    seed: Annotated[int, Field(ge=1000, le=3999)]
    step_index: Annotated[int, Field(ge=1, le=64)] | None
    action: Annotated[int, Field(ge=0, le=1)] | None
    window_seconds: Annotated[float, Field(ge=2, le=10)]


class RawData(StrictEvidence):
    episode_id: str
    step_index: Annotated[int, Field(ge=0, le=64)]
    mode: Literal["matched", "ospf"]
    seed: Annotated[int, Field(ge=1000, le=3999)]
    scenario: Literal["path0", "path1"]
    terminated: bool
    truncated: bool
    observation: RawObservation
    evidence: dict


class RawIPC(StrictEvidence):
    kind: Literal["ipc"]
    elapsed_seconds: Nonnegative
    request: RawRequest
    response: dict


class RawDecision(StrictEvidence):
    kind: Literal["decision"]
    episode_id: str
    step_index: Annotated[int, Field(ge=1, le=64)]
    action: Annotated[int, Field(ge=0, le=1)]
    error: None
    inference_seconds: Nonnegative | None
    input_sha256: SHA256
    probabilities: Pair | None
    reward: dict
    terminated: bool
    truncated: bool
    valid_transition: bool
    value: float | None


class Counter(StrictEvidence):
    monotonic_seconds: Nonnegative
    rx_bytes: Count
    tx_bytes: Count


class UDPWorker(StrictEvidence):
    bytes: Count
    packets: Count
    highest_sequence: Annotated[int, Field(ge=-1, le=2**63 - 1)]
    duration_seconds: Annotated[float, Field(gt=0, le=3600)]
    started_monotonic_seconds: Nonnegative
    finished_monotonic_seconds: Nonnegative


class Pilot(StrictEvidence):
    model_seed: Annotated[int, Field(ge=0, le=2**31 - 1)]
    train_seeds: list[int] = Field(min_length=1, max_length=1000)


class CampaignPlan(StrictEvidence):
    version: Annotated[int, Field(ge=3, le=3)]
    contract_hash: SHA256
    collection_budget_seconds: Annotated[int, Field(ge=1, le=1200)]
    approval: str
    scenarios: list[Literal["path0", "path1"]]
    steps: Annotated[int, Field(ge=2, le=64)]
    window_seconds: Annotated[float, Field(ge=2, le=10)]
    rollout: Annotated[int, Field(ge=2, le=4096)]
    ppo_config: dict
    validation_margin_strictly_greater_than: Annotated[float, Field(ge=0.02, le=0.02)]
    calibration_seeds: list[int]
    pilots: list[Pilot] = Field(min_length=1, max_length=3)
    pilot_admission: str
    validation_seeds: list[int]
    test_seeds: list[int]
    baselines: list[Literal["constant0", "constant1", "heuristic", "ospf"]]
    selection: str
    test: str
    stop: str


def relative_evidence_path(store, value):
    """Producer absolute paths confer no authority; constrain to operator root."""
    path = PurePosixPath(value)
    if path.is_absolute():
        try:
            value = str(path.relative_to(PurePosixPath(store.root)))
        except ValueError as exc:
            raise EvidenceError("producer_path_outside_operator_root") from exc
    # ArtifactStore rejects traversal, symlinks and noncanonical paths at open.
    return value


def reconstruct_measurement(data: RawData, request: RawRequest, manifest: dict):
    e, o = data.evidence, data.observation
    require(
        e["environment_spec"] == manifest["environment_spec"]
        and e["spec_hash"] == manifest["spec_hash"]
        and e["provenance"] == manifest["lab_provenance"],
        "raw_spec_or_provenance_mismatch",
    )
    require(
        e["measurement_complete"] is True
        and not data.truncated
        and e.get("error") is None
        and e["transition_traffic_included"] is True,
        "raw_measurement_incomplete",
    )
    require(
        data.terminated == (data.step_index == request.episode_steps)
        and (not data.terminated or e.get("cleanup_verified") is True)
        and (data.seed, data.scenario, data.mode)
        == (request.seed, request.scenario, request.mode),
        "raw_measurement_identity_mismatch",
    )
    start, end = e["post_control_interval"]["start"], e["post_control_interval"]["end"]
    control = e["control_start_monotonic_seconds"]
    require(
        control <= start < end
        and request.window_seconds <= end - start <= request.window_seconds + 2.01,
        "raw_measurement_interval_invalid",
    )
    # Producer timestamps bracket separate monotonic reads (its declared tolerance is 10ms).
    same(
        e["measured_window_seconds"],
        end - start,
        "raw_measurement_duration_mismatch",
        tolerance=0.01,
    )
    same(o.offered_mbps, e["phase"]["offered_mbps"])
    same(o.background_mbps, e["phase"]["background_mbps"])
    sent = [UDPWorker.model_validate(row) for row in e["udp_sent"]]
    received = [UDPWorker.model_validate(row) for row in e["udp_received"]]
    require(len(sent) == len(received) == 2, "raw_flows_incomplete")
    for index, (sender, receiver) in enumerate(zip(sent, received, strict=True)):
        for worker in (sender, receiver):
            require(
                worker.started_monotonic_seconds
                <= control
                <= start
                < end
                <= worker.finished_monotonic_seconds,
                "raw_flow_window_mismatch",
            )
            same(
                worker.duration_seconds,
                worker.finished_monotonic_seconds - worker.started_monotonic_seconds,
                "raw_worker_duration_mismatch",
                tolerance=0.01,
            )
            require(worker.bytes == worker.packets * 1200, "raw_packet_bytes_mismatch")
        require(
            sender.packets > 0 and receiver.packets <= sender.packets,
            "raw_flow_counts_invalid",
        )
        rate = sender.bytes * 8 / sender.duration_seconds / 1e6
        same(e["actual_offered_mbps"][index], rate)
        if index == 0:
            same(o.actual_offered_mbps, rate)
    goodput = received[0].bytes * 8 / sent[0].duration_seconds / 1e6
    loss = 1 - received[0].packets / sent[0].packets
    same(o.goodput_mbps, goodput)
    same(o.loss_fraction, loss)
    ping = e["ping"]
    require(
        type(ping["sent"]) is int
        and type(ping["received"]) is int
        and 0 <= ping["received"] <= ping["sent"]
        and ping["sent"] > 0,
        "raw_ping_counts_invalid",
    )
    require(
        (o.latency_ms is None) == (ping["received"] == 0)
        and e["service_outage"] is (ping["received"] == 0),
        "raw_outage_mismatch",
    )
    if o.latency_ms is not None:
        same(o.latency_ms, ping["rtt_avg_ms"])
    require(
        set(e["counter_windows"])
        == set(e["queue_peaks"])
        == {p for ports in PORTS for p in ports},
        "raw_egress_scope_incomplete",
    )
    queues, utilization = [], []
    for index, ports in enumerate(PORTS):
        require(o.path_capacity_mbps[index] > 0, "raw_capacity_invalid")
        rates, packets = [], []
        for port in ports:
            window = e["counter_windows"][port]
            before, after = (
                Counter.model_validate(window["before"]),
                Counter.model_validate(window["after"]),
            )
            interval = after.monotonic_seconds - before.monotonic_seconds
            require(
                before.monotonic_seconds
                <= control
                <= start
                < end
                <= after.monotonic_seconds
                and after.tx_bytes >= before.tx_bytes
                and after.rx_bytes >= before.rx_bytes,
                "raw_counter_reset_or_interval_mismatch",
            )
            same(window["duration_seconds"], interval)
            rates.append(
                (after.tx_bytes - before.tx_bytes)
                * 8
                / interval
                / (o.path_capacity_mbps[index] * 1e6)
            )
            queue = e["queue_peaks"][port]
            require(
                start <= queue["monotonic_seconds"] <= end, "raw_queue_time_mismatch"
            )
            leaves = [
                q
                for q in queue["raw_leaf_qdiscs"]
                if q.get("kind") == "netem"
                and not any(
                    child.get("parent", "").split(":")[0]
                    == q.get("handle", "").split(":")[0]
                    for child in queue["raw_leaf_qdiscs"]
                    if child is not q
                )
            ]
            require(len(leaves) == 1, "raw_queue_leaf_ambiguous")
            same(queue["backlog_bytes"], leaves[0]["backlog"])
            same(queue["backlog_packets"], leaves[0]["qlen"])
            require(
                queue["backlog_bytes"] >= 0 and queue["backlog_packets"] >= 0,
                "raw_queue_negative",
            )
            packets.append(queue["backlog_packets"])
            queues.append(
                {
                    "egress_id": port,
                    "sampled_peak_backlog_bytes": queue["backlog_bytes"],
                    "tx_bytes_per_second": (after.tx_bytes - before.tx_bytes)
                    / interval,
                    "rx_bytes_per_second": (after.rx_bytes - before.rx_bytes)
                    / interval,
                    "counter_interval_seconds": interval,
                }
            )
        same(o.path_utilization[index], max(rates))
        same(o.path_queue_packets[index], max(packets))
        utilization.append(max(rates))
    action = o.previous_action
    for route in (e["route"], e["route_end"]):
        require(
            route["path"] == manifest["contract"]["action_map"][action],
            "raw_route_action_mismatch",
        )
        paths = (
            route["readback"]["paths"]
            if data.mode == "matched"
            else {"h1->h3": route["readback"], "h2->h4": route["background_readback"]}
        )
        for endpoints, actual in paths.items():
            require(
                actual["nodes"][0] == endpoints.split("->")[0]
                and actual["nodes"][-1] == endpoints.split("->")[1]
                and len(actual["kernel_routes"]) == len(actual["nodes"]) - 1,
                "raw_kernel_path_incomplete",
            )
            for node, hop in zip(
                actual["nodes"][:-1], actual["kernel_routes"], strict=True
            ):
                require(
                    hop["node"] == node and bool(hop["route"].get("dev")),
                    "raw_kernel_hop_invalid",
                )
        require(
            paths["h1->h3"]["nodes"][1:-1] == route["path"],
            "raw_foreground_path_mismatch",
        )
        if data.mode == "matched":
            owned = route["readback"]["owned"]
            require(
                set(owned)
                == {
                    f"{node}:{table}"
                    for node in route["path"]
                    for table in (19110, 19111)
                },
                "raw_route_ownership_incomplete",
            )
            for identity, ruleset in owned.items():
                table = int(identity.split(":")[1])
                source, destination = (
                    ("10.78.8.2", "10.78.10.2")
                    if table == 19110
                    else ("10.78.10.2", "10.78.8.2")
                )
                require(
                    len(ruleset["rules"]) == len(ruleset["routes"]) == 1,
                    "raw_route_ownership_ambiguous",
                )
                rule, kernel = ruleset["rules"][0], ruleset["routes"][0]
                require(
                    rule.get("priority") == table
                    and str(rule.get("table")) == str(table)
                    and rule.get("src") in (source, source + "/32")
                    and rule.get("dst") in (destination, destination + "/32")
                    and kernel.get("dst") in (destination, destination + "/32")
                    and kernel.get("protocol") == "static"
                    and kernel.get("dev")
                    and kernel.get("gateway"),
                    "raw_route_ownership_mismatch",
                )
    require(e["route_end"]["changed"] is False, "raw_route_changed_during_measurement")
    return {
        "goodput_mbps": goodput,
        "loss_fraction": loss,
        "icmp_rtt_ms": o.latency_ms,
        "utilization": max(utilization),
        "queue_packets": max(o.path_queue_packets),
        "goodput_ratio": min(received[0].bytes / sent[0].bytes, 1),
        "queues": queues,
        "phase": e["phase"],
        "routing_policy": e["route"]["policy"],
        "background_nodes": (
            e["route"]["readback"]["paths"]["h2->h4"]
            if data.mode == "matched"
            else e["route"]["background_readback"]
        )["nodes"],
    }


def reconstruct_session(store, summary_path, expected_hash, manifest, plan, plan_hash):
    summary = store.document(summary_path)
    require(
        summary["status"] == "completed"
        and summary["failure"] is None
        and summary["invalid_windows"] == 0
        and summary["generalization"] is False,
        "campaign_session_not_complete",
    )
    require(
        summary["contract_hash"]
        == plan.contract_hash
        == manifest["contract_hash"]
        == CONTRACT_HASH,
        "campaign_contract_unsupported",
    )
    require(
        summary["evidence_sha256"] == expected_hash,
        "campaign_summary_evidence_hash_mismatch",
    )
    path = str(PurePosixPath(summary_path).with_name("evidence.jsonl"))
    content = store.read(path, limit=MAX_ARTIFACT, sha256=expected_hash)
    require(len(content.splitlines()) <= 10000, "campaign_record_count_exceeded")
    previous, pending, closed, rows, seeds = None, None, False, [], []
    previous_input_hash = None
    for index, line in enumerate(content.splitlines()):
        require(len(line) <= 2 * 1024 * 1024, "campaign_record_size_exceeded")
        record = parse_json(line)
        if index == 0:
            require(
                record["kind"] == "session"
                and record["summary"]["plan_sha256"] == plan_hash,
                "campaign_plan_not_predeclared",
            )
            for key in (
                "kind",
                "policy",
                "mode",
                "split",
                "seeds",
                "window_seconds",
                "episode_steps",
                "scenarios",
                "config",
                "model_seed",
            ):
                require(
                    record["summary"][key] == summary[key],
                    "campaign_summary_predeclaration_mismatch",
                )
            continue
        require(not closed, "campaign_records_after_close")
        if record["kind"] == "ppo_update":
            require(
                summary["kind"] == "train" and pending is None,
                "campaign_unexpected_update",
            )
            continue
        if record["kind"] == "decision":
            decision = RawDecision.model_validate(record)
            require(
                pending is not None and decision.valid_transition,
                "campaign_decision_unmatched",
            )
            row, input_data, actual_data, request, input_hash = pending
            require(
                (
                    decision.episode_id,
                    decision.step_index,
                    decision.action,
                    decision.input_sha256,
                )
                == (
                    actual_data.episode_id,
                    actual_data.step_index,
                    request.action,
                    input_hash,
                ),
                "campaign_decision_binding_mismatch",
            )
            if request.mode == "matched":
                require(
                    decision.action == actual_data.observation.previous_action,
                    "campaign_requested_action_not_applied",
                )
            raw_reward = {
                "goodput_ratio": row["goodput_ratio"],
                "delay": (
                    row["icmp_rtt_ms"] if row["icmp_rtt_ms"] is not None else 1000
                )
                / 50,
                "loss": row["loss_fraction"],
                "utilization": row["utilization"],
                "queue": row["queue_packets"] / 100,
                "route_change": float(
                    actual_data.observation.previous_action
                    != input_data.observation.previous_action
                ),
            }
            weights = {
                "goodput_ratio": 1,
                "delay": -0.2,
                "loss": -1,
                "utilization": -0.1,
                "queue": -0.1,
                "route_change": -0.05,
            }
            contributions = {
                key: value * weights[key] for key, value in raw_reward.items()
            }
            for key, value in raw_reward.items():
                same(
                    decision.reward["raw"][key],
                    value,
                    "campaign_reward_derivation_mismatch",
                )
                same(
                    decision.reward["contributions"][key],
                    contributions[key],
                    "campaign_reward_derivation_mismatch",
                )
            row["reward"] = sum(contributions.values())
            same(
                decision.reward["total"],
                row["reward"],
                "campaign_reward_derivation_mismatch",
            )
            row.update(
                seed=actual_data.seed,
                scenario=actual_data.scenario,
                action=actual_data.observation.previous_action,
                step=actual_data.step_index,
                inference_seconds=decision.inference_seconds,
            )
            if summary["policy"].startswith("constant"):
                require(
                    decision.action == int(summary["policy"][-1]),
                    "campaign_constant_action_mismatch",
                )
            if summary["policy"] == "heuristic":
                obs = input_data.observation
                pressure = [
                    u + q / 100
                    for u, q in zip(
                        obs.path_utilization, obs.path_queue_packets, strict=True
                    )
                ]
                current = obs.previous_action
                expected = (
                    1 - current
                    if pressure[current] - pressure[1 - current] > 0.15
                    else current
                )
                require(
                    decision.action == expected, "campaign_heuristic_action_mismatch"
                )
            if summary["policy"] == "ppo":
                require(
                    decision.probabilities is not None
                    and decision.inference_seconds is not None,
                    "campaign_inference_evidence_missing",
                )
                same(sum(decision.probabilities), 1.0)
                if summary["kind"] == "evaluation":
                    require(
                        decision.action
                        == (
                            0
                            if decision.probabilities[0] >= decision.probabilities[1]
                            else 1
                        ),
                        "campaign_policy_argmax_mismatch",
                    )
            rows.append(row)
            pending = None
            continue
        require(
            record["kind"] == "ipc" and pending is None, "campaign_record_order_invalid"
        )
        ipc = RawIPC.model_validate(record)
        r, response = ipc.request, ipc.response
        require(
            response["ok"] is True
            and response["error"] is None
            and type(response["version"]) is int
            and response["version"] == 1,
            "campaign_ipc_failed",
        )
        require(
            r.mode == summary["mode"]
            and r.window_seconds == plan.window_seconds
            and r.episode_steps == plan.steps,
            "campaign_window_contract_mismatch",
        )
        if r.command == "close":
            require(
                previous is not None
                and previous.terminated
                and response["data"]["closed"] is True
                and response["data"]["cleanup_verified"] is True
                and response["data"]["episode_id"] == previous.episode_id,
                "campaign_cleanup_unverified",
            )
            closed = True
            continue
        data = RawData.model_validate(response["data"])
        row = reconstruct_measurement(data, r, manifest)
        if r.command == "reset":
            require(
                (previous is None or previous.terminated)
                and data.step_index == 0
                and r.action is None
                and r.step_index is None
                and r.episode_id is None,
                "campaign_reset_order_invalid",
            )
            seeds.append(data.seed)
            require(
                data.scenario == plan.scenarios[(len(seeds) - 1) % 2],
                "campaign_scenarios_unbalanced",
            )
        else:
            require(
                previous is not None
                and not previous.terminated
                and (data.episode_id, data.seed, data.scenario, data.step_index)
                == (
                    previous.episode_id,
                    previous.seed,
                    previous.scenario,
                    previous.step_index + 1,
                )
                and r.episode_id == data.episode_id
                and r.step_index == data.step_index,
                "campaign_transition_discontinuous",
            )
            for key in ("offered_mbps", "background_mbps", "path_capacity_mbps"):
                require(
                    getattr(data.observation, key)
                    == getattr(previous.observation, key),
                    "campaign_not_stationary",
                )
            pending = row, previous, data, r, previous_input_hash
        previous = data
        previous_input_hash = digest(data.observation.model_dump(mode="json"))
    require(
        closed
        and pending is None
        and seeds == summary["seeds"]
        and len(set(seeds)) == len(seeds)
        and len(rows) == len(seeds) * plan.steps == summary["valid_transitions"],
        "campaign_session_incomplete",
    )
    same(
        summary["mean_episode_reward"],
        sum(r["reward"] for r in rows) / len(seeds),
        "campaign_summary_reward_mismatch",
    )
    return {
        "policy": summary["policy"],
        "split": summary["split"],
        "kind": summary["kind"],
        "rows": rows,
        "seeds": seeds,
        "evidence_sha256": expected_hash,
        "evidence_bytes": len(content),
        "evidence_path": path,
    }


def assess_producer_campaign(store: ArtifactStore, path, raw, content_hash):
    producer = ProducerQualification.model_validate(raw)
    reasons = validate_producer_qualification(raw, None)
    pinned = os.environ.get("NANFO_AUTONOMY_QUALIFICATION_SHA256")
    if pinned != content_hash:
        reasons.append(
            "operator_qualification_pin_unconfigured"
            if pinned is None
            else "operator_qualification_pin_mismatch"
        )
    paths = producer.evidence_paths
    try:
        checkpoint_path = relative_evidence_path(store, paths.checkpoint)
        checkpoint = store.read(
            checkpoint_path,
            limit=16 * 1024 * 1024,
            sha256=producer.checkpoint.checkpoint_sha256,
        )
        manifest = inspect_checkpoint_bytes(checkpoint)
        require(
            manifest == producer.checkpoint.manifest,
            "campaign_checkpoint_manifest_mismatch",
        )
        CheckpointManifest.model_validate(manifest)
        plan_path = relative_evidence_path(store, paths.plan)
        plan_raw = store.document(plan_path)
        require(digest(plan_raw) == producer.plan_sha256, "campaign_plan_hash_mismatch")
        plan = CampaignPlan.model_validate(plan_raw)
        source_root = PurePosixPath(plan_path).parent / "frozen-client-source"
        for name, source_hash in manifest["client_source_files"].items():
            require(
                PurePosixPath(name).name == name and name.endswith(".py"),
                "campaign_client_source_path_invalid",
            )
            store.read(str(source_root / name), sha256=source_hash)
        require(
            plan.scenarios == ["path0", "path1"]
            and set(plan.baselines) == {"constant0", "constant1", "heuristic", "ospf"},
            "campaign_plan_scope_invalid",
        )
        pilot = next(
            (p for p in plan.pilots if p.model_seed == manifest["config"]["seed"]), None
        )
        require(
            pilot is not None and pilot.train_seeds == manifest["training_seeds"],
            "campaign_pilot_seeds_mismatch",
        )
        require(
            {k: v for k, v in manifest["config"].items() if k != "seed"}
            == plan.ppo_config
            and manifest["transitions"] == len(pilot.train_seeds) * plan.steps
            and manifest["updates"] * plan.rollout == manifest["transitions"],
            "campaign_training_budget_mismatch",
        )
        for seeds, low in (
            (pilot.train_seeds, 1000),
            (plan.calibration_seeds, 1000),
            (plan.validation_seeds, 2000),
            (plan.test_seeds, 3000),
        ):
            require(
                len(seeds) == len(set(seeds))
                and all(type(s) is int and low <= s < low + 1000 for s in seeds),
                "campaign_seed_split_invalid",
            )
        require(
            not set(pilot.train_seeds) & set(plan.calibration_seeds),
            "campaign_calibration_seed_leakage",
        )
        sessions = []
        for source, role in [
            (paths.training, "training"),
            *((s, "validation") for s in paths.validation),
            *((s, "calibration") for s in paths.calibration),
        ]:
            source = relative_evidence_path(store, source)
            summary = store.document(source)
            hashes = (
                producer.validation_evidence_sha256
                if role == "validation"
                else producer.calibration_evidence_sha256
            )
            expected_hash = (
                producer.training_evidence_sha256
                if role == "training"
                else hashes[summary["policy"]]
            )
            session = reconstruct_session(
                store, source, expected_hash, manifest, plan, producer.plan_sha256
            )
            expected_seeds = (
                pilot.train_seeds
                if role == "training"
                else (
                    plan.validation_seeds
                    if role == "validation"
                    else plan.calibration_seeds
                )
            )
            require(
                session["seeds"] == expected_seeds
                and session["split"]
                == ("validation" if role == "validation" else "train")
                and session["kind"]
                == ("train" if role == "training" else "evaluation"),
                "campaign_session_role_mismatch",
            )
            session["role"] = role
            sessions.append(session)
            require(
                sum(s["evidence_bytes"] for s in sessions) <= MAX_ARTIFACT,
                "campaign_total_bytes_exceeded",
            )
        validation = {s["policy"]: s for s in sessions if s["role"] == "validation"}
        controls = {s["policy"]: s for s in sessions if s["role"] == "calibration"}
        require(
            set(validation) == {"ppo", *plan.baselines}
            and set(controls) == {"constant0", "constant1"},
            "campaign_baselines_incomplete",
        )
        for collection in (validation, controls):
            reference = next(iter(collection.values()))["rows"]
            for session in collection.values():
                require(
                    [
                        (
                            r["seed"],
                            r["scenario"],
                            r["step"],
                            r["phase"],
                            r["routing_policy"],
                            r["background_nodes"],
                        )
                        for r in session["rows"]
                    ]
                    == [
                        (
                            r["seed"],
                            r["scenario"],
                            r["step"],
                            r["phase"],
                            r["routing_policy"],
                            r["background_nodes"],
                        )
                        for r in reference
                    ],
                    "campaign_matched_schedules_or_background_mismatch",
                )
        learned = validation["ppo"]["rows"]
        comparisons = {}
        for policy in plan.baselines:
            comparisons[policy] = {}
            for metric in ("reward", "goodput_mbps", "loss_fraction", "icmp_rtt_ms"):
                pairs = []
                for seed in plan.validation_seeds:
                    left = [r[metric] for r in learned if r["seed"] == seed]
                    right = [
                        r[metric]
                        for r in validation[policy]["rows"]
                        if r["seed"] == seed
                    ]
                    if None in left or None in right:
                        continue
                    a, b = statistics.mean(left), statistics.mean(right)
                    pairs.append(
                        {"seed": seed, "policy": a, "baseline": b, "delta": a - b}
                    )
                claimed = producer.comparisons[policy][metric]
                require(
                    len(pairs) == claimed.paired_seed_count,
                    "campaign_paired_count_mismatch",
                )
                for actual, reported in zip(pairs, claimed.pairs, strict=True):
                    require(
                        actual["seed"] == reported.seed, "campaign_paired_seed_mismatch"
                    )
                    for key in ("policy", "baseline", "delta"):
                        same(
                            getattr(reported, key),
                            actual[key],
                            "campaign_paired_metric_mismatch",
                        )
                deltas = [p["delta"] for p in pairs]
                mean_delta = statistics.mean(deltas) if pairs else None
                # The frozen campaign has four reserved validation seeds, df=3.
                # Other cardinalities remain unsupported instead of inventing uncertainty.
                require(
                    len(pairs) in (0, 4),
                    "campaign_uncertainty_sample_count_unsupported",
                )
                interval = None
                if pairs:
                    half = 3.1825 * statistics.stdev(deltas) / 2
                    interval = [mean_delta - half, mean_delta + half]
                    require(claimed.ci95 is not None, "campaign_uncertainty_missing")
                    for a, b in zip(claimed.ci95, interval, strict=True):
                        same(a, b, "campaign_uncertainty_mismatch")
                comparisons[policy][metric] = {
                    "mean_delta": mean_delta,
                    "ci95": interval,
                    "paired_seed_count": len(pairs),
                }
        mean = statistics.mean(r["reward"] for r in learned)
        same(producer.validation_mean_reward, mean, "campaign_validation_mean_mismatch")
        directional = {}
        for scenario, desired in (("path0", 1), ("path1", 0)):
            rows = [r for r in learned if r["scenario"] == scenario]
            fraction = sum(r["action"] == desired for r in rows) / len(rows)
            directional[scenario] = fraction
            same(
                producer.directional_dependence[scenario].desired_route_fraction,
                fraction,
                "campaign_directional_claim_mismatch",
            )
            if fraction <= 0.5:
                reasons.append(f"directional_dependence_failed_{scenario}")
            if (
                producer.directional_dependence[
                    scenario
                ].pressure_swap_desired_route_fraction
                <= 0.5
            ):
                reasons.append(f"producer_pressure_swap_failed_{scenario}")
            means = {
                p: statistics.mean(
                    r["reward"] for r in s["rows"] if r["scenario"] == scenario
                )
                for p, s in controls.items()
            }
            effect = means[f"constant{desired}"] - means[f"constant{1 - desired}"]
            same(
                producer.train_only_action_effects[scenario],
                effect,
                "campaign_action_effect_mismatch",
            )
            if effect <= 0.02:
                reasons.append("train_only_action_effect_failed")
        action_counts = [sum(r["action"] == a for r in learned) for a in (0, 1)]
        if 0 in action_counts or any(v <= 0.5 for v in directional.values()):
            reasons.append("useful_model_unqualified")
        if comparisons["heuristic"]["reward"]["mean_delta"] < 0:
            reasons.append("heuristic_outperforms_policy")
        reasons.extend(
            [
                "heldout_test_not_assessed",
                "frozen_policy_replay_not_independently_validated",
                "causal_arrival_service_guarantees_missing",
            ]
        )
        if manifest["transitions"] < 144:
            reasons.append("adr012_minimum_training_evidence_not_met")
        index_path = str(PurePosixPath(plan_path).with_name("artifact-hashes.json"))
        index_bytes = store.read(index_path)
        index = TypeAdapter(dict[str, SHA256]).validate_python(
            parse_json(index_bytes), strict=True
        )
        index_hash = hashlib.sha256(index_bytes).hexdigest()
        if os.environ.get("NANFO_AUTONOMY_CAMPAIGN_INDEX_SHA256") != index_hash:
            reasons.append("operator_campaign_index_pin_unconfigured_or_mismatch")
        # Check the entire supplied immutable inventory, including the collection ledger.
        total, verified = 0, []
        base = PurePosixPath(index_path).parent
        for name, expected in index.items():
            require(
                not PurePosixPath(name).is_absolute()
                and ".." not in PurePosixPath(name).parts,
                "campaign_inventory_path_invalid",
            )
            inventory_path = str(base / name)
            value = store.read(
                inventory_path, limit=MAX_ARTIFACT, sha256=expected, allow_empty=True
            )
            total += len(value)
            require(total <= MAX_ARTIFACT, "campaign_inventory_total_bytes_exceeded")
            verified.append(inventory_path)
        require(
            {path, checkpoint_path, plan_path, *(s["evidence_path"] for s in sessions)}
            <= set(verified),
            "campaign_inventory_missing_required_file",
        )
        ledger = store.document(
            str(PurePosixPath(plan_path).with_suffix(".collection.json"))
        )
        require(
            ledger["plan_sha256"] == producer.plan_sha256,
            "campaign_ledger_plan_mismatch",
        )
        test_attempts = [
            a for a in ledger["attempts"] if a["identity"]["split"] == "test"
        ]
        require(not test_attempts, "campaign_test_already_opened")
        return {
            "qualified": False,
            "producer_schema_version": 3,
            "producer_schema_revision": "adr013-001-evidence-paths-client-sources",
            "producer_claims_qualified": producer.qualified,
            "manifest_sha256": content_hash,
            "checkpoint_sha256": producer.checkpoint.checkpoint_sha256,
            "spec_sha256": manifest["spec_hash"],
            "contract_sha256": manifest["contract_hash"],
            "raw_metrics_reconstructed": True,
            "validation_action_counts": action_counts,
            "validation_mean_reward": mean,
            "measured_directional_fractions": directional,
            "comparisons": comparisons,
            "training_transitions": manifest["transitions"],
            "selected_model": None,
            "test_attempt_count": len(test_attempts),
            "inventory_sha256": index_hash,
            "inventory_files_verified": len(verified),
            "inventory_bytes_verified": total,
            "test_status": producer.test_status,
            "installed": False,
            "reasons": list(dict.fromkeys(reasons)),
            "evidence": [
                {
                    k: s[k]
                    for k in (
                        "evidence_path",
                        "evidence_sha256",
                        "evidence_bytes",
                        "role",
                    )
                }
                for s in sessions
            ],
            "calibration": raw_calibration_diagnostics(sessions),
        }
    except (KeyError, IndexError, TypeError, ZeroDivisionError) as exc:
        raise EvidenceError("campaign_raw_evidence_schema_invalid") from exc


def raw_calibration_diagnostics(sessions):
    """Use measured training bytes only. Peaks cannot become fabricated endpoints."""
    groups = {}
    for session in sessions:
        if session["split"] != "train":
            continue
        for row in session["rows"]:
            for queue in row["queues"]:
                key = queue["egress_id"], row["action"]
                groups.setdefault(key, []).append(queue)
    return {
        "qualified": False,
        "trusted_calibration": None,
        "fit_performed": False,
        "source": "raw training-only netem backlog and interface counters",
        "holdout_coverage": None,
        "groups": [
            {
                "egress_id": key[0],
                "action": key[1],
                "samples": len(rows),
                "max_sampled_peak_backlog_bytes": max(
                    r["sampled_peak_backlog_bytes"] for r in rows
                ),
                "max_measured_tx_bytes_per_second": max(
                    r["tx_bytes_per_second"] for r in rows
                ),
                "min_measured_tx_bytes_per_second": min(
                    r["tx_bytes_per_second"] for r in rows
                ),
            }
            for key, rows in sorted(groups.items())
        ],
        "reasons": [
            "queue_endpoints_not_measured",
            "interface_rx_not_attributed_queue_arrivals",
            "calibration_fit_holdout_not_predeclared",
            "causal_arrival_service_guarantees_missing",
        ],
    }
