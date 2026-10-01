"""Offline ADR025 evidence reconstruction; no device, provider or result-flag trust."""

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VERSION = "nanfo.experimental-acceptance/v1"
POLICIES = {"qualified", "fixed0", "fixed1", "heuristic"}
OUTCOME_PROTOCOL = "nanfo.experimental-outcomes/v2"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifact(root, ref):
    """Evidence references are contained, immutable exact bytes, including ancestors."""
    relative = Path(ref["path"])
    require(not relative.is_absolute() and ".." not in relative.parts, "artifact_escape")
    path = root / relative
    require(not any(part.is_symlink() for part in [path, *path.parents] if part != root.parent),
            "artifact_symlink")
    require(path.resolve().is_relative_to(root.resolve()), "artifact_escape")
    require(file_hash(path) == ref["sha256"], "artifact_hash_mismatch")
    return path


def metrics(raw):
    """Recompute from native counts and durations; missing counts stay unavailable."""
    start, end = raw.get("window_started_ns"), raw.get("window_ended_ns")
    require(type(start) is int and type(end) is int and 0 < start < end, "traffic_clock_invalid")
    received_bytes = raw.get("received_bytes")
    sent, received = raw.get("probe_sent"), raw.get("probe_received")
    require(received_bytes is None or type(received_bytes) is int and received_bytes >= 0,
            "traffic_bytes_invalid")
    require(sent is None or type(sent) is int and sent >= 0, "probe_count_invalid")
    require(received is None or type(received) is int and received >= 0, "probe_count_invalid")
    require(sent is None or received is None or received <= sent, "probe_count_invalid")
    rtts = raw.get("probe_rtt_ms")
    if rtts is not None:
        require(isinstance(rtts, list) and len(rtts) == received
                and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in rtts),
                "probe_rtt_count_invalid")
    return dict(goodput_mbps=None if received_bytes is None else received_bytes * 8000 / (end - start),
                loss_fraction=None if not sent or received is None else (sent - received) / sent,
                rtt_ms=statistics.mean(rtts) if rtts else None,
                probe_sent=sent, probe_received=received, traffic_bytes=received_bytes)


def paired_metrics(cases):
    indexed = {(c["scenario"], c["seed"], c["policy"]): c["metrics"] for c in cases}
    outcomes = {(c["scenario"],c["seed"],c["policy"]): c.get("outcome","kept_then_restored") for c in cases}
    require(len(indexed) == len(cases), "duplicate_matched_case")
    pairs = sorted({(scenario, seed) for scenario, seed, _ in indexed})
    require(all({p for s, n, p in indexed if (s, n) == pair} == POLICIES for pair in pairs),
            "unmatched_baseline_case")
    result = []
    for baseline in ("fixed0", "fixed1", "heuristic"):
        names = ("goodput_mbps", "loss_fraction", "rtt_ms")
        if all("udp_loss_fraction" in c["metrics"] for c in cases):
            names += ("udp_loss_fraction",)
        for name in names:
            rows = []
            for scenario, seed in pairs:
                policy = indexed[scenario, seed, "qualified"][name]
                value = indexed[scenario, seed, baseline][name]
                rows.append(dict(scenario=scenario, seed=seed, policy=policy, baseline=value,
                                  policy_outcome=outcomes[scenario,seed,"qualified"],
                                  baseline_outcome=outcomes[scenario,seed,baseline],
                                 delta=None if policy is None or value is None else policy - value))
            available = [row["delta"] for row in rows if row["delta"] is not None]
            # Report the entire preregistered denominator, never silently drop bad windows.
            result.append(dict(baseline=baseline, metric=name, pairs=rows,
                expected_pairs=len(rows), available_pairs=len(available),
                mean_delta=statistics.mean(available) if len(available) == len(rows) else None,
                sample_stdev=statistics.stdev(available) if len(available) == len(rows) > 1 else None,
                uncertainty="descriptive paired-seed sample SD; no packet pseudoreplication or superiority gate",
                superiority_claim=False))
    return result


def measured_latencies(journal):
    from datetime import datetime
    rows = journal["receipts"]
    stamps = {}
    for row in rows:
        stamps.setdefault(row["kind"], datetime.fromisoformat(row["created_at"]))
    def difference(start, end):
        return (stamps[end] - stamps[start]).total_seconds() if start in stamps and end in stamps else None
    return dict(decision_seconds=difference("observed", "inferred"),
                simulation_seconds=difference("inferred", "simulated"),
                action_seconds=difference("dispatching", "verifying"),
                recovery_seconds=difference("recovering", "restored"),
                chronology="private PostgreSQL journal UTC; process timings retained separately")


def audit_chain(root, refs, policy, *, positive):
    """Use owner Pydantic contracts, not runner-specific imitations of domain records."""
    from app.modules.autonomy.experimental.schemas import (
        ExecutionReceipt, InferenceRecord, MeasuredFrame, PreparedAction,
        RecoveryReceipt, SimulationRecord, VerificationRecord,
    )
    from app.modules.autonomy.experimental.schemas import contract_digest

    types = dict(frame=MeasuredFrame, inference=InferenceRecord, simulation=SimulationRecord,
                 prepared=PreparedAction, receipt=ExecutionReceipt, verification=VerificationRecord,
                 recovery=RecoveryReceipt)
    records = {name: cls.model_validate(read(artifact(root, refs[name])))
               for name, cls in types.items() if name in refs}
    require({"frame", "inference", "simulation"} <= records.keys(), "joined_chain_missing")
    frame, inference, sim = (records[key] for key in ("frame", "inference", "simulation"))
    fh, ih, sh = (contract_digest(records[k]) for k in ("frame", "inference", "simulation"))
    require(inference.frame_sha256 == fh and sim.frame_sha256 == fh
            and sim.inference_sha256 == ih and sim.policy_sha256 == contract_digest(policy),
            "joined_hash_binding_mismatch")
    if policy.policy_kind != "model":
        features = frame.features
        expected = int(policy.policy_kind[-1]) if policy.policy_kind in ("fixed0", "fixed1") else min(
            range(2), key=lambda i: (features.path_utilization[i], features.path_queue_packets[i], i))
        require(inference.qualification is None and inference.result.action == expected
                and inference.result.input_sha256 == contract_digest(features)
                and inference.proposal.checkpoint_sha256 is None, "baseline_decision_forged")
    else:
        require(frame.runtime == policy.runtime and inference.qualification.qualified
            and inference.result.checkpoint_sha256 == policy.checkpoint_sha256
            and inference.result.weights_sha256 == policy.weights_sha256
            and inference.result.registry_sha256 == policy.registry_sha256
            and inference.result.source_sha256 == policy.model_source_sha256,
                "joined_qualification_identity_mismatch")
        require(inference.result.history_sha256 == frame.snapshot.history_sha256
            and inference.result.input_sha256 == contract_digest(frame.features)
            and inference.result.snapshot_sha256 == contract_digest(frame.snapshot),
                "joined_raw_inference_mismatch")
        require(inference.wrapper_equivalence_sha256 == policy.wrapper_equivalence_sha256
                and inference.model_adapter_sha256 == policy.model_adapter_sha256
                and policy.wrapper_equivalence_sha256 is not None, "experimental_wrapper_equivalence_unbound")
    require(sim.evaluator_sha256 == policy.evaluator_sha256
            and sim.assumptions == policy.assumptions and sim.objectives == policy.objectives,
            "simulation_policy_mismatch")
    from app.modules.autonomy.experimental.simulation import (
        SimulationAssumptions, from_core_frame, evaluate_actions,
    )
    selected = sim.result["selected"]
    assumptions = SimulationAssumptions.model_validate({**policy.assumptions,
        "limits": policy.objectives, "max_observation_age_seconds": policy.max_observation_age_seconds})
    # Replay at the recorded acquisition/admission time, never freshen the frame.
    replay = evaluate_actions(frame=from_core_frame(frame), assumptions=assumptions,
        actions=[row["action"] for row in sim.result["per_action"]], policy_sha256=contract_digest(policy),
        now=records["prepared"].command.created_at if "prepared" in records else frame.snapshot.published_at)
    require(replay == sim.result["per_action"] and selected == replay[inference.result.action]
            and sim.admitted == (selected["risk_gate"]=="passed"), "simulation_not_reproducible")
    if positive:
        require(sim.admitted and {"prepared", "receipt", "verification", "recovery"} <= records.keys(),
                "positive_blocked_or_incomplete")
    if "prepared" in records:
        prepared = records["prepared"]
        command = prepared.command
        require(command.frame_sha256 == fh and command.inference_sha256 == ih
                and command.simulation_sha256 == sh and command.policy_sha256 == contract_digest(policy)
                and command.run_id == policy.run_id and command.runtime == policy.runtime
                and command.route.action_id == sim.action_id == inference.proposal.action_id,
                "prepared_chain_mismatch")
        require(command.network_id == policy.network_id and command.workspace_id == policy.workspace_id
                and command.route in policy.routes and command.resource_id == policy.runtime.resource_id
                and command.expires_at <= policy.expires_at
                and 0 < (command.expires_at-command.created_at).total_seconds() <= policy.max_action_duration_seconds,
                "command_scope_or_duration_unbound")
        age = (command.created_at - frame.snapshot.observed_at).total_seconds()
        require(0 <= age <= policy.max_observation_age_seconds, "dispatch_stale")
        for name in ("receipt", "verification", "recovery"):
            if name in records:
                record = records[name]
                require(record.request_id == command.request_id
                        and record.action_sha256 == contract_digest(prepared), "receipt_binding_mismatch")
        if "recovery" in records:
            recovery = records["recovery"]
            require(recovery.status == "restored" and recovery.baseline_sha256 == prepared.baseline_sha256,
                    "recovery_unresolved")
    if positive:
        verification = records["verification"]
        require(records["receipt"].status == "applied" and verification.route_verified
                and verification.action_id == records["prepared"].command.route.action_id,
                "positive_not_applied")
    return records


def audit_journal(journal, records, policy, *, positive):
    """Reconstruct exported owner rows, including all hashes and write-before-I/O."""
    receipts = journal["receipts"]
    require(receipts and len({r["receipt_id"] for r in receipts}) == len(receipts), "journal_receipts_missing")
    require(all(r["run_id"] == str(policy.run_id) and canonical(r["payload"]) == r["payload_sha256"]
                for r in receipts), "journal_payload_changed")
    stamps = [r["created_at"] for r in receipts]
    require(stamps == sorted(stamps), "journal_order_invalid")
    phases = [r["kind"] for r in receipts]
    require("bootstrap_prepared" in phases and "bootstrap_completed" in phases
            and "bootstrap_restored" in phases and phases.index("bootstrap_prepared") < phases.index("bootstrap_completed"),
            "durable_bootstrap_ownership_missing")
    from app.modules.autonomy.experimental.schemas import BootstrapCommand, BootstrapReceipt, BootstrapRecoveryReceipt
    command = BootstrapCommand.model_validate(next(r["payload"] for r in receipts if r["kind"] == "bootstrap_prepared"))
    receipt = BootstrapReceipt.model_validate(next(r["payload"] for r in receipts if r["kind"] == "bootstrap_completed"))
    recovered = BootstrapRecoveryReceipt.model_validate(next(r["payload"] for r in receipts if r["kind"] == "bootstrap_restored"))
    require(command.policy_sha256 == canonical(policy.model_dump(mode="json"))
            and receipt.command_sha256 == recovered.command_sha256 == canonical(command.model_dump(mode="json"))
            and recovered.status == "restored" and receipt.baseline_sha256 == recovered.baseline_sha256 == command.baseline_sha256,
            "bootstrap_receipt_binding_mismatch")
    if positive:
        wanted = ["admitted", "observing", "observed", "inferred", "simulated", "preparing", "prepared",
                  "dispatching", "verifying", "verified", "holding", "recovering", "restored", "released"]
        offset = 0
        for phase in wanted:
            require(phase in phases[offset:], "joined_journal_phase_missing:" + phase)
            offset = phases.index(phase, offset) + 1
        for key, phase in (("frame", "observed"), ("inference", "inferred"), ("simulation", "simulated"),
                           ("prepared", "prepared"), ("receipt", "verifying"), ("verification", "verified"),
                           ("recovery", "restored")):
            require(any(r["kind"] == phase and r["payload"] == records[key].model_dump(mode="json")
                        for r in receipts), "exported_chain_not_in_durable_journal")
    return receipts


def native_trace(raw, *, allow_denied=False):
    require(isinstance(raw, list) and raw, "native_trace_missing")
    mutations = []
    for row in raw:
        args = row["argv"]
        require(isinstance(args, list) and args and isinstance(row["node"], str), "native_command_invalid")
        require(type(row["began"]) in (int, float) and math.isfinite(row["began"]), "native_time_missing")
        if args[:2] in (["ip", "route"], ["ip", "rule"]) and args[2] in ("add", "del"):
            require(allow_denied or row["completed"] is not None, "native_mutation_ambiguous")
            if row["completed"] is not None:
                require(row["completed"] >= row["began"], "native_mutation_clock_invalid")
                mutations.append(row)
    return mutations


def native_restoration(native, baseline):
    restored = native["restoration"]
    require(restored is not None and restored["baseline_sha256"] == canonical(baseline)
            and restored["baseline"] == baseline and restored["owned_empty"] is True
            and native["runtime"]["owned"] == [], "native_restoration_missing")
    require(restored["readback"]["tables"] == baseline["tables"]
            and all(restored["readback"]["paths"][key]["nodes"] == value["nodes"]
                    for key, value in baseline["paths"].items()), "native_original_state_not_restored")


def verification_metrics(record, policy):
    from app.modules.autonomy.experimental.simulation import FrozenMeasuredFrame
    from app.modules.autonomy.experimental.metrics import measured_metrics
    raw = record.provenance["frame"]["response"]["data"]
    frame = FrozenMeasuredFrame(network_id=policy.network_id, workspace_id=policy.workspace_id,
        runtime_sha256=canonical(policy.runtime.model_dump(mode="json")), raw=raw, raw_sha256=canonical(raw),
        window_started_at=record.window_started_at, observed_at=record.observed_at)
    measured = measured_metrics(frame)
    expected = ["h1", *next(r.path for r in policy.routes if r.action_id == record.action_id), "h3"]
    health = raw["evidence"]["route_end"]["readback"]["paths"]
    require(health["h1->h3"]["nodes"] == expected and health["h3->h1"]["nodes"] == expected[::-1],
            "independent_route_readback_failed")
    require(all(health[k]["kernel_routes"] for k in ("h1->h3", "h3->h1", "h2->h4", "h4->h2")),
            "raw_kernel_readback_missing")
    value = dict(goodput_mbps=measured["goodput_mbps"], rtt_ms=measured["rtt_ms"],
                 loss_fraction=None if measured["probe_loss_pct"] is None else measured["probe_loss_pct"] / 100,
                 udp_loss_fraction=None if measured["udp_loss_pct"] is None else measured["udp_loss_pct"] / 100)
    require(math.isclose(record.goodput_mbps, value["goodput_mbps"], abs_tol=1e-6)
            and math.isclose(record.loss_fraction, value["udp_loss_fraction"], abs_tol=1e-6)
            and record.rtt_ms == value["rtt_ms"], "convenience_metrics_disagree_with_counts")
    t = policy.verification
    require(value["goodput_mbps"] >= t.min_goodput_mbps and value["udp_loss_fraction"] <= t.max_loss_fraction
            and value["loss_fraction"] <= t.max_probe_loss_fraction and value["rtt_ms"] is not None
            and value["rtt_ms"] <= t.max_rtt_ms and record.probe_sent >= t.min_probe_sent
            and record.traffic_bytes >= t.min_traffic_bytes, "positive_measured_threshold_failed")
    return value, raw


def raw_performance(frame, policy):
    """Evaluate actual counts against identical gates, not an applied/rejected flag."""
    from datetime import datetime,timedelta
    from app.modules.autonomy.experimental.simulation import FrozenMeasuredFrame
    from app.modules.autonomy.experimental.metrics import measured_metrics
    response=frame["response"]
    require(response.get("ok") is True,"original_response_invalid")
    raw=response["data"]
    evidence=raw["evidence"]
    require(evidence.get("error") is None and evidence.get("measurement_complete") is True
            and not raw["truncated"] and not raw["terminated"],"measurement_invalid")
    interval=evidence["post_control_interval"]
    # Pure reconstruction envelope at the raw probe timestamp; never used as live freshness.
    end=datetime.fromisoformat(evidence["ping"]["observed_at"].replace("Z","+00:00"))
    wrapped=FrozenMeasuredFrame(network_id=policy.network_id,workspace_id=policy.workspace_id,
        runtime_sha256=canonical(policy.runtime.model_dump(mode="json")),raw=raw,raw_sha256=canonical(raw),
        observed_at=end,window_started_at=end-timedelta(seconds=interval["end"]-interval["start"]))
    measured=measured_metrics(wrapped)
    ping=evidence["ping"]
    threshold=policy.verification
    value=dict(goodput_mbps=measured["goodput_mbps"],rtt_ms=measured["rtt_ms"],
        udp_loss_fraction=None if measured["udp_loss_pct"] is None else measured["udp_loss_pct"]/100,
        loss_fraction=None if measured["probe_loss_pct"] is None else measured["probe_loss_pct"]/100)
    checks=dict(goodput=value["goodput_mbps"]>=threshold.min_goodput_mbps,
        udp_loss=value["udp_loss_fraction"] is not None and value["udp_loss_fraction"]<=threshold.max_loss_fraction,
        probe_loss=value["loss_fraction"] is not None and value["loss_fraction"]<=threshold.max_probe_loss_fraction,
        rtt=value["rtt_ms"] is not None and value["rtt_ms"]<=threshold.max_rtt_ms,
        probe_count=ping["sent"]>=threshold.min_probe_sent,
        traffic=evidence["udp_received"][0]["bytes"]>=threshold.min_traffic_bytes)
    action=raw["observation"]["previous_action"]
    expected=["h1",*policy.routes[action].path,"h3"]
    paths=evidence["route_end"]["readback"]["paths"]
    require(paths["h1->h3"]["nodes"]==expected and paths["h3->h1"]["nodes"]==expected[::-1]
            and all(paths[k]["kernel_routes"] for k in ("h1->h3","h3->h1","h2->h4","h4->h2")),
            "route_readback_invalid")
    return dict(metrics=value,checks=checks,passed=all(checks.values()),
                step_index=raw["step_index"],action=action,raw_sha256=canonical(frame))


def audit_rejection(root, captured, records, journal, native, failures):
    """A bad window cannot conceal an unrelated controller/recovery failure."""
    controller = read(artifact(root, captured["controller"]))
    errors = controller.get("exception", [])
    require(controller.get("status") == "failed" and controller.get("error_type") == "ValueError"
            and errors and all(e.get("type") == "ValueError" and e.get("message") in {
                "experimental_receiver_uncertain_or_rejected", "experimental_verification_threshold_failed",
            } for e in errors), "unexplained_rejection_control_failure")
    prepared = records["prepared"]
    request_id = str(prepared.command.request_id)
    rows = [r for r in journal["receipts"] if r.get("request_id") == request_id]
    phases = [r["kind"] for r in rows]
    offset = 0
    for phase in ("prepared", "dispatching", "interrupted", "recovering", "restored"):
        require(phase in phases[offset:], "rejection_phase_missing:" + phase)
        offset = phases.index(phase, offset) + 1
    require(any(r["kind"] == "restored" and r["payload"] == records["recovery"].model_dump(mode="json")
                for r in rows), "rejection_recovery_not_durable")
    failed = failures[0]
    if all(e.get("message") == "experimental_verification_threshold_failed" for e in errors):
        verified = [r for r in rows if r["kind"] == "verified"
                    and canonical(r["payload"].get("provenance", {}).get("frame")) == failed["raw_sha256"]]
        require(len(verified) == 1 and verified[0]["payload"].get("action_sha256") == canonical(
            prepared.model_dump(mode="json")) and phases.index("verified") < phases.index("interrupted"),
            "core_failed_window_enforcement_unbound")
        return
    matched = []
    for path in (root / captured["case_id"]).glob("wire-*.json"):
        wire = read(path)
        req, response = wire["request"], wire["response"]
        ev = response.get("evidence", {})
        frame = ev.get("failed_frame")
        if frame is None or canonical(frame) != failed["raw_sha256"]:
            continue
        retained = native["receipts"].get(req["request_id"], {})
        require(retained.get("request_sha256") == canonical(req) and retained.get("response") == response,
                "failed_window_receipt_not_durable")
        require(response["request_id"] == req["request_id"] and response["status"] == "rejected"
                and response["policy_sha256"] == req["policy_sha256"] == native["policy_sha256"]
                and response["fence"] == req["fence"]
                and req["operation"] in ("execute", "verify")
                and (req["operation"] != "execute" or req["request_id"] == request_id)
                and ev.get("reason") == ("measured_verification_failed" if req["operation"] == "execute"
                                         else "hold_measurement_failed"), "failed_window_not_enforced")
        matched.append(req["request_id"])
    require(len(matched) == 1, "failed_window_enforcement_unbound")


def classify_nominal(root, captured):
    """V2 protocol completion is distinct from candidate performance success."""
    from app.modules.autonomy.experimental.schemas import ExperimentalPolicy
    policy=ExperimentalPolicy.model_validate(read(artifact(root,captured["operator_policy"])))
    records=audit_chain(root,captured["chain"],policy,positive=False)
    journal=read(artifact(root,captured["journal"]))
    audit_journal(journal,records,policy,positive=False)
    require(journal["run"]["released"] is True and journal["run"]["phase"]=="restored","durable_recovery_unresolved")
    native=read(artifact(root,captured["native_journal"]))
    bootstrap=read(artifact(root,captured["bootstrap"]))
    native_restoration(native,bootstrap["baseline"])
    require(read(artifact(root,captured["cleanup"]))["removed"] is True,"cleanup_unresolved")
    frames=[]
    inventory=read(artifact(root,captured["raw_frames"]))
    directory=root/captured["case_id"]
    require([r["canonical_sha256"] for r in inventory]==native["runtime"]["frame_hashes"],"all_raw_frames_required")
    for ref in inventory:
        frame=read(artifact(directory,ref))
        require(canonical(frame)==ref["canonical_sha256"],"raw_frame_changed")
        frames.append(frame)
    post=[f for f in frames if f["request"]["command"]=="step"]
    for frame in frames:
        require(frame["request"]["seed"]==captured["seed"] and frame["request"]["scenario"]==captured["scenario"],
                "retained_frame_workload_mismatch")
    absent={k:None for k in ("goodput_mbps","loss_fraction","udp_loss_fraction","rtt_ms")}
    if not records["simulation"].admitted:
        require("prepared" not in records and not any(r["kind"]=="dispatching" for r in journal["receipts"])
                and not post,"simulation_rejection_dispatched")
        return dict(outcome="simulation_rejected",protocol_complete=True,candidate_passed=False,
                    metrics=absent,windows=[],missing_reason="no_postaction_window_predispatch_rejection")
    require("prepared" in records and "recovery" in records,"admitted_action_recovery_missing")
    if not post:
        return dict(outcome="control_failure",protocol_complete=False,candidate_passed=False,metrics=absent,windows=[])
    windows=[]
    for frame in post:
        try:
            result=raw_performance(frame,policy)
        except (ValueError,KeyError,TypeError) as exc:
            return dict(outcome="measurement_invalid",protocol_complete=False,candidate_passed=False,
                metrics=absent,windows=windows,reason=str(exc),invalid_frame_sha256=canonical(frame))
        require(result["action"]==records["inference"].result.action,"selected_route_changed")
        require(frame["response"]["data"]["episode_id"]==str(records["frame"].snapshot.run_id),"retained_frame_episode_mismatch")
        windows.append(result)
    failures=[w for w in windows if not w["passed"]]
    if failures:
        audit_rejection(root, captured, records, journal, native, failures)
        return dict(outcome="performance_rejected_then_restored",protocol_complete=True,candidate_passed=False,
                    metrics=failures[0]["metrics"],windows=windows)
    controller=read(artifact(root,captured["controller"]))
    require(controller["status"]=="completed" and
            (not controller.get("error_type") or controller.get("termination")=="verified_hold_expired_and_restored"),
            "control_error_is_not_performance_outcome")
    audit_chain(root,captured["chain"],policy,positive=True)
    audit_journal(journal,records,policy,positive=True)
    return dict(outcome="kept_then_restored",protocol_complete=True,candidate_passed=True,
                metrics=windows[-1]["metrics"],windows=windows)


def audit_smoke(root, plan, rows):
    from app.modules.autonomy.experimental.schemas import ExperimentalPolicy
    v2=plan.get("outcome_protocol")==OUTCOME_PROTOCOL
    require(len(rows) == (4 if v2 else 2) and [r["case_id"] for r in rows] == [r["case_id"] for r in plan["smoke"]],
            "smoke_incomplete")
    matrix_seeds = {r["seed"] for r in plan["trials"]+plan["faults"]}
    require(not matrix_seeds.intersection(r["seed"] for r in rows), "smoke_seed_not_separate")
    metrics = []
    for declared, row in zip(plan["smoke"], rows, strict=True):
        require(row["status"] == "completed", "smoke_not_completed:"+row["case_id"])
        if v2:
            result=classify_nominal(root,row)
            require(result["protocol_complete"],"smoke_protocol_incomplete")
            if declared["policy"]=="qualified":
                require(result["candidate_passed"],"model_smoke_must_keep")
                inferred=read(artifact(root,row["chain"]["inference"]))
                require(inferred["result"]["action"]==(1 if declared["scenario"]=="path0" else 0),"smoke_direction_wrong")
            metrics.append(dict(case_id=row["case_id"],**result))
            continue
        policy = ExperimentalPolicy.model_validate(read(artifact(root, row["operator_policy"])))
        records = audit_chain(root, row["chain"], policy, positive=True)
        audit_journal(read(artifact(root,row["journal"])), records, policy, positive=True)
        native = read(artifact(root,row["native_journal"]))
        native_restoration(native, read(artifact(root,row["bootstrap"]))["baseline"])
        value, raw = verification_metrics(records["verification"], policy)
        require(raw["seed"] == declared["seed"] and raw["scenario"] == declared["scenario"]
                and records["inference"].result.action == (1 if declared["scenario"] == "path0" else 0),
                "smoke_direction_or_seed_mismatch")
        require(read(artifact(root,row["cleanup"]))["removed"] is True, "smoke_cleanup_failed")
        metrics.append(dict(case_id=row["case_id"], metrics=value))
    return dict(status="passed", scope="preregistered-smokes-not-matrix-evidence", cases=metrics)


def audit(root):
    root = Path(root)
    plan = read(root / "plan.json")
    require(plan["version"] == VERSION and plan["training"] is False and plan["calibrated"] is False,
            "experimental_scope_invalid")
    require(file_hash(root / "seed-audit.json") == plan["seed_audit_sha256"], "seed_audit_changed")
    seeds = read(root / "seed-audit.json")
    reserved = set(seeds["reserved_seeds"])
    require(reserved == {seed for row in seeds["documents"] for seed in row["seeds"]},
            "seed_inventory_incomplete")
    expected = plan["trials"] + plan["faults"]
    require(len(plan["trials"]) == plan["paired_seeds_per_direction"] * 2 * 4
            and len(plan["faults"]) == 20 and {r["policy"] for r in plan["trials"]} == POLICIES
            and {r["scenario"] for r in plan["trials"]} == {"path0", "path1"}, "incomplete_preregistered_matrix")
    nominal_keys = [(r["scenario"], r["seed"], r["policy"]) for r in plan["trials"]]
    require(len(set(nominal_keys)) == len(nominal_keys), "duplicate_nominal_plan")
    groups = {(s, seed) for s, seed, _ in nominal_keys}
    require(all({p for s, n, p in nominal_keys if (s, n) == group} == POLICIES for group in groups),
            "incomplete_matched_plan")
    nominal_seeds = {r["seed"] for r in plan["trials"]}
    fault_seeds = [r["seed"] for r in plan["faults"]]
    require(len(set(fault_seeds)) == 20 and not nominal_seeds.intersection(fault_seeds)
            and all(type(s) is int and 1000 <= s < 2000 for s in nominal_seeds | set(fault_seeds)),
            "operational_seed_matrix_invalid")
    require(not reserved.intersection(row["seed"] for row in expected), "reused_seed")
    for relative, pin in plan.get("source_sha256", {}).items():
        artifact(root, {"path": "source/" + relative, "sha256": pin})
    manifest = read(root / "campaign-evidence.json")
    if plan.get("smoke"):
        require(audit_smoke(root, plan, manifest["smoke"])["status"] == "passed", "smoke_failed")
    require(manifest["plan_sha256"] == file_hash(root / "plan.json"), "campaign_plan_changed")
    require(manifest["status"] == "completed", "campaign_blocked_or_incomplete")
    require([row["case_id"] for row in manifest["cases"]] == [row["case_id"] for row in expected],
            "missing_reordered_or_retried_case")
    require(manifest["auth_mode"] == "real-private-postgres-redis"
            and manifest["provider_mocks"] is False, "live_positive_mocked")
    require(plan.get("offline_gates_sha256") and file_hash(root / "offline-gates.json") == plan["offline_gates_sha256"],
            "offline_gate_binding_missing")
    gates = read(root / "offline-gates.json")
    require(gates["status"] == "passed" and gates["source_sha256"] == plan["source_sha256"]
            and gates["sources_unchanged_during_checks"] is True, "offline_gate_sources_changed")
    cases, paired_admission, directions, latencies = [], {}, set(), []
    outcome_counts={}
    for declared, captured in zip(expected, manifest["cases"], strict=True):
        require(captured["status"] == "completed", "case_blocked_or_failed:" + declared["case_id"])
        require(captured["seed"] == declared["seed"] and captured["scenario"] == declared["scenario"]
                and captured["policy"] == declared["policy"], "case_schedule_mismatch")
        from app.modules.autonomy.experimental.schemas import ExperimentalPolicy
        policy = ExperimentalPolicy.model_validate(read(artifact(root, captured["operator_policy"])))
        from app.modules.autonomy.experimental.simulation import admission_policy_sha256
        pair = declared["scenario"], declared["seed"]
        semantic = admission_policy_sha256(policy)
        require(pair not in paired_admission or paired_admission[pair] == semantic, "unmatched_admission_policy")
        paired_admission[pair] = semantic
        native = read(artifact(root, captured["native_journal"]))
        bootstrap = read(artifact(root, captured["bootstrap"]))
        binding = native["binding"]
        require(binding["controller_policy_sha256"] == canonical(policy.model_dump(mode="json"))
                and binding["baseline_sha256"] == canonical(bootstrap["baseline"]), "native_controller_policy_unbound")
        wire_policy = read(root / declared["case_id"] / "receiver-policy.json")
        require(native["policy_sha256"] == file_hash(root / declared["case_id"] / "receiver-policy.json")
                and wire_policy["container_id"] == policy.runtime.container_id
                and wire_policy["wrapper_sha256"] == policy.runtime.wrapper_sha256
                and wire_policy["model_sha256"] == plan["model"]["checkpoint_sha256"], "native_runtime_unbound")
        native_restoration(native, bootstrap["baseline"])
        if declared.get("bootstrap_initial_action") == 1:
            require(bootstrap.get("operator_warmup_action") == 1
                    and bootstrap["frame"]["request"]["command"] == "step"
                    and bootstrap["frame"]["request"]["action"] == 1
                    and bootstrap["initial_reset"]["frame"]["request"]["command"] == "reset",
                    "declared_initial_route_not_actually_measured")
        require(bootstrap["frame"]["response"]["data"]["seed"] == declared["seed"]
                and bootstrap["frame"]["response"]["data"]["scenario"] == declared["scenario"],
                "bootstrap_workload_mismatch")
        mutations = native_trace(read(artifact(root, captured["native_commands"])), allow_denied="fault" in declared)
        authority_checks = read(artifact(root, captured["native_authority"]))
        for mutation in mutations:
            if mutation["argv"][2] != "add":
                continue
            matched = [row for row in authority_checks if row["entry"]["began"] == mutation["began"]
                       and row["entry"]["argv"] == mutation["argv"] and row["authorized"] is True]
            require(len(matched) == 1 and mutation["began"] <= matched[0]["checked_monotonic"] <= mutation["completed"],
                    "native_add_without_current_owner_authority")
        auth = read(artifact(root, captured["auth"]))
        require(auth["backend"] == "real-private-postgres-redis" and auth["login_authenticated"] is True,
                "real_auth_missing")
        journal = read(artifact(root, captured["journal"]))
        latencies.append(dict(case_id=declared["case_id"], **measured_latencies(journal)))
        require(policy.preregistration_sha256 == file_hash(root / "plan.json"), "policy_plan_unbound")
        require(policy.actor_id == auth["actor_id"] and str(policy.network_id) == auth["network_id"]
                and str(policy.workspace_id) == auth["workspace_id"], "auth_scope_mismatch")
        require(policy.policy_kind == ("model" if declared["policy"] == "qualified" else declared["policy"]),
                "policy_kind_mismatch")
        if policy.policy_kind == "model":
            from app.modules.autonomy.experimental.live_adapters import WrapperEquivalence
            path = root / declared["case_id"] / "wrapper-equivalence.json"
            require(file_hash(path) == policy.wrapper_equivalence_sha256, "equivalence_bytes_changed")
            equivalence = WrapperEquivalence.model_validate(read(path))
            require(equivalence.runtime == policy.runtime and
                    plan["offline_gates_sha256"] in equivalence.evidence_sha256
                    and equivalence.model_adapter_sha256 == policy.model_adapter_sha256,
                    "equivalence_scope_mismatch")
        v2_nominal=plan.get("outcome_protocol")==OUTCOME_PROTOCOL and "fault" not in declared
        classification=classify_nominal(root,captured) if v2_nominal else None
        if classification:
            require(classification["protocol_complete"],"nominal_protocol_incomplete")
            require(captured["outcome"]==classification["outcome"],"nominal_outcome_misreported")
            outcome_counts[classification["outcome"]]=outcome_counts.get(classification["outcome"],0)+1
        if declared.get("fault") == "delayed-data":
            records = {}
            phases = [row["kind"] for row in journal["receipts"]]
            require("observed" in phases and "dispatching" not in phases, "delayed_data_dispatched")
        else:
            records = audit_chain(root, captured["chain"], policy, positive="fault" not in declared and not v2_nominal)
        audit_journal(journal, records, policy, positive="fault" not in declared and not v2_nominal)
        require(journal["run"]["released"] is True and journal["run"]["phase"] == "restored", "durable_run_unresolved")
        if "fault" in declared:
            intervention = read(artifact(root, captured["intervention"]))
            require(all(intervention[key] == declared[key]
                        for key in ("fault", "intervention", "phase", "write_index")),
                    "fault_phase_or_mechanism_mismatch")
            events = read(artifact(root, captured["boundary_events"]))
            if declared["fault"] == "delayed-data":
                require(intervention["delay_seconds"] > plan["max_observation_age_seconds"]
                        and not events, "delayed_data_not_real")
                continue
            require(len(events) == 1 and events[0]["id"] == intervention["boundary"]["id"], "fault_boundary_missing")
            point = events[0]["point"]
            require(point["ordinal"] == 1 and point["when"] ==
                    ("before" if declared["phase"] == "beforewrite" else "after"), "fault_prefix_mismatch")
            if declared["fault"].startswith(("STOP", "revoke")) or declared["fault"] in ("disconnect", "restart", "partial-apply"):
                require(not any(r["argv"][2] == "add" and not r["restoring"]
                                and r["began"] > events[0]["reached_monotonic"] for r in mutations),
                        "post_fault_new_routing")
            if declared["fault"].startswith("revoke"):
                require(intervention["current_authority_denied"] is True, "revocation_not_real")
            if declared["fault"] in ("disconnect", "restart"):
                require(intervention["returncode"] == -9 and intervention["killed_pid"] > 0
                        and read(artifact(root, captured["recovery_process"]))["status"] == "completed",
                        "process_restart_not_real")
            if declared["fault"] == "link-failure":
                require(intervention["link_down"]["returncode"] == intervention["link_up"]["returncode"] == 0,
                        "native_link_intervention_failed")
                require("UP" not in intervention["link_down"]["readback"][0]["flags"]
                        and "UP" in intervention["link_up"]["readback"][0]["flags"], "link_state_not_observed")
                require(any(r["kind"] == "interrupted" for r in journal["receipts"]), "link_fault_had_no_failure")
            if declared["fault"] == "ambiguous-receipt":
                directory = root / declared["case_id"]
                receipt = read(directory / "lost-native-receipt.json")
                require(receipt["request_id"] in native["receipts"] and
                        native["receipts"][receipt["request_id"]]["response"] == receipt,
                        "ambiguous_result_not_durable")
                require(len([read(p) for p in directory.glob("wire-*.json")
                             if read(p)["request"]["operation"] == "execute"]) == 1, "ambiguous_execute_replayed")
        else:
            if classification:
                if declared["policy"]=="qualified" and classification["candidate_passed"]:
                    directions.add(declared["scenario"])
                cases.append({key:declared[key] for key in ("scenario","seed","policy")} |
                             {"metrics":classification["metrics"],"outcome":classification["outcome"]})
                continue
            value, raw = verification_metrics(records["verification"], policy)
            require(raw["seed"] == declared["seed"] and raw["scenario"] == declared["scenario"], "traffic_seed_mismatch")
            # Same-route decisions legitimately execute without an additional add.
            executes = [r for r in native["receipts"].values()
                        if r["response"]["request_id"] == str(records["prepared"].command.request_id)]
            require(len(executes) == 1, "native_execute_replayed_or_missing")
            if declared["policy"] == "qualified":
                expected_action = 1 if declared["scenario"] == "path0" else 0
                require(records["inference"].result.action == expected_action, "model_wrong_direction")
                directions.add(declared["scenario"])
            if declared["policy"] in ("fixed0", "fixed1"):
                require(raw["observation"]["previous_action"] == int(declared["policy"][-1]),
                        "fixed_baseline_action_mismatch")
            cases.append({key: declared[key] for key in ("scenario", "seed", "policy")} | {"metrics": value})
    cleanup = read(artifact(root, manifest["cleanup"]))
    require(cleanup["unresolved_resources"] == [] and cleanup["removed"] is True, "cleanup_unresolved")
    require(directions == {"path0", "path1"}, "both_qualified_directions_required")
    return dict(status="passed", claim="experimental-joined-loop-only", cases=len(expected),
                paired_metrics=paired_metrics(cases), latencies=latencies, outcome_counts=outcome_counts,
                calibrated=False, production_ready=False,
                independent_signoff=False)


def diagnose(root):
    """Read-only, all-case diagnostics, deliberately never an acceptance verdict."""
    root = Path(root)
    plan, manifest = read(root / "plan.json"), read(root / "campaign-evidence.json")
    captured = {r["case_id"]: r for r in manifest["cases"]}
    reports = []
    for declared in plan["trials"] + plan["faults"]:
        name = declared["case_id"]
        row = captured.get(name, {})
        report = dict(case_id=name, recorded_status=row.get("status", "missing"),
                      recorded_outcome=row.get("outcome"), findings=[], windows=[])
        reports.append(report)
        def check(stage, function):
            try:
                return function()
            except (ValueError, KeyError, OSError, TypeError, IndexError) as exc:
                # Do not publish arbitrary exception strings or artifact payloads.
                reason = str(exc)
                report["findings"].append(dict(stage=stage, error_type=type(exc).__name__,
                    reason=reason if isinstance(exc, ValueError) and re.fullmatch(r"[a-z_]+(?::[a-z_]+)?", reason)
                    else "evidence_unavailable_or_invalid"))
                return None
        for key, ref in row.items():
            if isinstance(ref, dict) and "path" in ref and "sha256" in ref:
                check("reference:" + key, lambda ref=ref: artifact(root, ref))
        if not row:
            report["findings"].append(dict(stage="case_missing", error_type="MissingEvidence"))
            continue
        controller = check("controller", lambda: read(artifact(root, row["controller"]))) if "controller" in row else None
        if controller:
            report["controller_errors"] = [e["message"] for e in controller.get("exception", [])
                if re.fullmatch(r"experimental_[a-z_]+", e.get("message", ""))]
        if "fault" not in declared:
            classification = check("nominal_classification", lambda: classify_nominal(root, row))
            if classification:
                report["diagnostic_outcome"] = classification["outcome"]
        if "operator_policy" not in row:
            report["findings"].append(dict(stage="preacquisition_policy_missing", error_type="MissingEvidence"))
            # Older campaigns did not reference these setup failures in their manifest.
            # Read only the fixed local filenames and report their byte identity.
            for filename in ("attempt.json", "qualification.json", "registry.json"):
                path = root / name / filename
                ref = dict(path=str(path.relative_to(root)), sha256=check("setup_hash", lambda: file_hash(path)))
                value = check("setup:" + filename, lambda: read(artifact(root, ref)))
                if value:
                    report[filename] = dict(sha256=ref["sha256"], reasons=[r for r in value.get("reasons", [])
                        if re.fullmatch(r"live_[a-z_]+", r)],
                        installed_at=value.get("installed_at"), expires_at=value.get("expires_at"))
            continue
        from app.modules.autonomy.experimental.schemas import ExperimentalPolicy
        policy = check("policy", lambda: ExperimentalPolicy.model_validate(read(artifact(root, row["operator_policy"]))))
        native = check("native", lambda: read(artifact(root, row["native_journal"])))
        journal = check("journal", lambda: read(artifact(root, row["journal"])))
        if journal:
            report["core_released"] = journal.get("run", {}).get("released", False)
            report["core_phase"] = journal.get("run", {}).get("phase")
            check("durable_recovery", lambda: require(report["core_released"] is True
                and report["core_phase"] == "restored", "durable_recovery_unresolved"))
        if policy and declared.get("fault") != "delayed-data":
            check("joined_chain", lambda: audit_chain(root, row["chain"], policy, positive=False))
        if native:
            report["native_phase"] = native["phase"]
            check("native_restoration", lambda: native_restoration(native, read(artifact(root, row["bootstrap"]))["baseline"]))
        inventory = check("raw_inventory", lambda: read(artifact(root, row["raw_frames"])))
        if inventory is not None and native:
            check("raw_inventory_complete", lambda: require(
                [r["canonical_sha256"] for r in inventory] == native["runtime"]["frame_hashes"], "missing_frames"))
            for ref in inventory:
                frame = check("raw_frame", lambda ref=ref: read(artifact(root / name, ref)))
                if frame is None:
                    continue
                check("raw_canonical_hash", lambda: require(canonical(frame) == ref["canonical_sha256"], "changed"))
                data = frame["response"].get("data", {})
                window = dict(sha256=ref["canonical_sha256"], step_index=data.get("step_index"),
                    complete=data.get("evidence", {}).get("measurement_complete", False),
                    truncated=data.get("truncated"), metrics=None)
                if policy:
                    performance = check("window:" + ref["canonical_sha256"], lambda: raw_performance(frame, policy))
                    if performance:
                        window.update(metrics=performance["metrics"], checks=performance["checks"])
                report["windows"].append(window)
    return dict(status="diagnostic_only", acceptance=False, calibrated=False,
                plan_sha256=file_hash(root / "plan.json"), cases=reports,
                recorded_failed=sum(r["recorded_status"] != "completed" for r in reports))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--diagnose", action="store_true", help="report every case offline; never certify acceptance")
    args = parser.parse_args()
    try:
        result = diagnose(args.root) if args.diagnose else audit(args.root)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        result = dict(status="failed", reason=type(exc).__name__ + ":" + str(exc), calibrated=False)
    if args.output:
        if args.diagnose:
            require(not args.output.resolve().is_relative_to(args.root.resolve()), "diagnostic_output_must_be_outside_evidence")
        from scripts.verify_experimental_lab import write
        write(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
