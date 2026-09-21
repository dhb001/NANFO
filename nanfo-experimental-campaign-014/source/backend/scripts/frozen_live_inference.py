"""ADR023 fixed read-only AI-interpreter entrypoint; frozen sources remain unchanged."""

import argparse
import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import resource
import sys
import tempfile
import time
import uuid

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.autonomy.artifact_io import EvidenceError, parse_json
from app.modules.autonomy.live_schemas import RuntimeResult
from app.modules.autonomy.registry import LiveRegistry
from scripts.frozen_model_diagnostic import canonical_hash, confine_filesystem, deny_control_access

REBUILT_GATES = {"constant_reward_margin_strict_gt": .02, "constant_reward_ci_lower_strict_gt": 0,
    "ospf_goodput_ci_lower_strict_gt": 0, "ospf_rtt_ci_upper_strict_lt": 0,
    "direction_correct_fraction_strict_gt": .5, "paired_seeds": 12}


def validate_rebuilt_plan(plan, selection, identity, installation, documents, parent_identity):
    model = installation.model
    lineage = parse_json(documents[model.lineage.path])
    audit = parse_json(documents[model.seed_audit.path])
    seeds = plan.get("test_seeds", [])
    reserved = audit.get("reserved_seeds", [])
    if (plan.get("version") != model.qualification_protocol
            or plan.get("checkpoint") != identity or plan.get("parent_checkpoint_sha256") != model.parent_checkpoint.sha256
            or plan.get("image_id") != identity["manifest"]["lab_provenance"]["lab_image_id"]
            or plan.get("lineage_sha256") != model.lineage.sha256
            or plan.get("seed_audit_sha256") != model.seed_audit.sha256
            or plan.get("client_source_sha256") != model.source_sha256 or plan.get("runtime_versions") != model.runtime_versions
            or type(plan.get("created_unix")) not in (int, float) or plan["created_unix"] <= 0
            or plan.get("qualification") != REBUILT_GATES or plan.get("test_attempts_before_selection") != 0
            or plan.get("scenarios") != ["path0", "path1"] or plan.get("steps") != 4 or plan.get("window_seconds") != 2.0
            or len(seeds) != 12 or any(type(seed) is not int or not 3000 <= seed <= 3999 for seed in seeds)
            or seeds != list(range(seeds[0], seeds[0] + 12)) or set(seeds) & set(reserved)
            or audit.get("selected_seeds") != seeds or audit.get("version") != 1
            or selection != {"plan_sha256": model.plan.sha256, "checkpoint": identity,
                             "selection_rule": plan.get("selection_rule"), "test_only": True}):
        raise EvidenceError("live_rebuilt_preregistration_mismatch")
    documents_seeds = {seed for row in audit.get("documents", []) for seed in row["seeds"]}
    if (not audit.get("documents") or documents_seeds != set(reserved)
            or not set(range(3900, 3912)) <= set(reserved)
            or not set(parent_identity["manifest"]["training_seeds"]) <= set(reserved)
            or any(not re.fullmatch(r"[a-f0-9]{64}", row.get("sha256", "")) for row in audit["documents"])
            or plan.get("scope") != "stationary-campus-small-v4-scoped-benchmark"
            or plan.get("autonomous_dispatch") is not False):
        raise EvidenceError("live_rebuilt_seed_audit_incomplete")
    expected_lineage = dict(version=model.qualification_protocol, operation="provenance-rebinding-only-no-training",
        parent_checkpoint_sha256=model.parent_checkpoint.sha256, derived_checkpoint_sha256=model.checkpoint.sha256,
        parent_manifest_sha256=canonical_hash(parent_identity["manifest"]), derived_manifest_sha256=canonical_hash(identity["manifest"]),
        tensor_payload_sha256=identity["manifest"]["weights_sha256"], exact_tensor_bytes_equal=True,
        parent_image_id=parent_identity["manifest"]["lab_provenance"]["lab_image_id"], image_id=plan["image_id"],
        source_sha256=identity["manifest"]["environment_spec"]["source_sha256"], client_source_sha256=model.source_sha256,
        changed_manifest_fields=["lab_provenance.lab_image_id"], qualified=False)
    if lineage != expected_lineage:
        raise EvidenceError("live_rebuilt_lineage_document_mismatch")


def validate_rebuilt_capture(plan, row, session, documents, manifest):
    attachment = parse_json(documents[session.attachment.path])
    raw = documents[session.evidence.path]
    first = raw.split(b"\n", 1)[0] + b"\n"
    if (attachment.get("session_sha256") != hashlib.sha256(first).hexdigest()
            or attachment.get("feed_offset") != len(first)
            or type(attachment.get("attached_unix")) not in (int, float)
            or not plan["created_unix"] < attachment["attached_unix"] <= time.time()
            or type(attachment.get("attached_monotonic")) not in (int, float)
            or attachment["attached_monotonic"] <= 0
            or row["lab_provenance"] != manifest["lab_provenance"]
            or row["environment_spec"] != manifest["environment_spec"]):
        raise EvidenceError("live_rebuilt_capture_chronology_or_runtime_mismatch")
    previous_end = attachment["attached_monotonic"]
    measurements = 0
    for line in raw.splitlines():
        item = parse_json(line)
        if item.get("kind") != "ipc" or item["request"]["command"] == "close":
            continue
        data = item["response"]["data"]
        evidence = data["evidence"]
        start, end = (evidence["post_control_interval"][key] for key in ("start", "end"))
        if (not previous_end < start < end
                or evidence["provenance"] != manifest["lab_provenance"]
                or evidence["environment_spec"] != manifest["environment_spec"]
                or evidence["spec_hash"] != manifest["spec_hash"]):
            raise EvidenceError("live_rebuilt_raw_capture_before_plan_or_wrong_runtime")
        previous_end = end
        measurements += 1
    if measurements != 60:
        raise EvidenceError("live_rebuilt_raw_capture_incomplete")


def validate_benchmark(cli, artifacts, root, installation, documents):
    """Reconstruct all raw outcomes and deterministic checkpoint decisions, not flags."""
    model = installation.model
    plan = parse_json(documents[model.plan.path])
    selection = parse_json(documents[model.selection.path])
    identity = artifacts.inspectCheckpoint(root / "checkpoint.ptz")
    rebuilt_protocol = model.qualification_protocol == "adr024-rebuilt-evaluation-v1"
    if rebuilt_protocol:
        parent_identity = artifacts.inspectCheckpoint(root / "parent.ptz")
        # Both bundles pass the unchanged loader; no image check or tensor allowlist patch.
        artifacts.loadCheckpoint(root / "parent.ptz")
        validate_rebuilt_plan(plan, selection, identity, installation, documents, parent_identity)
    elif (plan.get("version") != "adr014-test-only-v1" or plan.get("checkpoint") != identity
            or plan.get("client_source_sha256") != model.source_sha256
            or plan.get("runtime_versions") != model.runtime_versions
            or plan.get("test_attempts_before_selection") != 0
            or plan.get("test_seeds") != list(range(3900, 3912))
            or plan.get("scenarios") != ["path0", "path1"]
            or plan.get("steps") != 4 or plan.get("window_seconds") != 2.0
            or selection != {"plan_sha256": model.plan.sha256, "checkpoint": identity,
                             "selection_rule": plan.get("selection_rule"), "test_only": True}):
        raise EvidenceError("live_benchmark_preregistration_mismatch")
    paths = [root / "benchmark" / str(index) / "summary.json" for index in range(5)]
    summaries = [parse_json(documents[session.summary.path]) for session in model.sessions]
    policies = [row["policy"] for row in summaries]
    if (set(policies) != {"ppo", "constant0", "constant1", "heuristic", "ospf"}
            or policies != plan["policy_order"]):
        raise EvidenceError("live_benchmark_policies_incomplete")
    for row, session in zip(summaries, model.sessions, strict=True):
        if (row["seeds"] != plan["test_seeds"] or row["split"] != "test"
                or row["kind"] != "evaluation" or row["status"] != "completed"
                or row["generalization"] is not False or row["valid_transitions"] != 48
                or row["plan_sha256"] != (model.plan.sha256 if rebuilt_protocol else plan["original_plan_sha256"])
                or row["evidence_sha256"] != session.evidence.sha256
                or (row["policy"] == "ppo" and row["checkpoint"] != identity)):
            raise EvidenceError("live_benchmark_scope_mismatch")
        if rebuilt_protocol:
            validate_rebuilt_capture(plan, row, session, documents, identity["manifest"])
    rebuilt = cli.report(paths, checkpoint=root / "checkpoint.ptz")
    saved = parse_json(documents[model.report.path])
    if any(saved.get(key) != value for key, value in rebuilt.items()):
        raise EvidenceError("live_benchmark_raw_reconstruction_mismatch")
    validate_benchmark_gates(rebuilt)


def validate_benchmark_gates(rebuilt):
    """Identical scoped acceptance thresholds for original and rebuilt protocols."""
    if not rebuilt["comparable_held_out_schedules"]:
        raise EvidenceError("live_benchmark_schedules_incompatible")
    comparisons = {row["baseline"]: row["metrics"] for row in rebuilt["paired_seed_comparisons"]}
    for policy in ("constant0", "constant1"):
        reward = comparisons[policy]["reward"]
        if (reward["paired_seed_count"] != 12 or reward["mean_delta"] <= .02
                or reward["ci95"] is None or reward["ci95"][0] <= 0):
            raise EvidenceError("live_benchmark_constant_advantage_missing")
    goodput, rtt = (comparisons["ospf"][key] for key in ("goodput_mbps", "icmp_rtt_ms"))
    if (goodput["paired_seed_count"] != 12 or rtt["paired_seed_count"] != 12
            or goodput["ci95"] is None or rtt["ci95"] is None
            or goodput["ci95"][0] <= 0 or rtt["ci95"][1] >= 0):
        raise EvidenceError("live_benchmark_ospf_criterion_failed")
    learned = next(row for row in rebuilt["sessions"] if row["policy"] == "ppo")
    for scenario, desired in (("path0", 1), ("path1", 0)):
        rows = [row for row in learned["reconstructed_steps"] if row["scenario"] == scenario]
        if len(rows) != 24 or sum(row["action"] == desired for row in rows) <= len(rows) / 2:
            raise EvidenceError("live_benchmark_directional_dependence_missing")


def run(operation, network_id=None, workspace_id=None, snapshot_hash=None, replay_history=None):
    if os.geteuid() == 0:
        raise EvidenceError("live_inference_root_forbidden")
    for kind, limit in ((resource.RLIMIT_CORE, 0), (resource.RLIMIT_CPU, 90 if operation == "qualify" else 25),
                        (resource.RLIMIT_AS, 8 * 1024**3), (resource.RLIMIT_FSIZE, 64 * 1024**2),
                        (resource.RLIMIT_NOFILE, 64)):
        resource.setrlimit(kind, (limit, limit))
    registry = LiveRegistry.from_environment()
    installation = registry.load()
    model = installation.model
    documents = registry.benchmark_bytes(installation) if operation == "qualify" else {}
    snapshot = None
    history = None
    if operation == "infer":
        snapshot, actual_hash = registry.snapshot(installation, network_id, workspace_id, expected_hash=snapshot_hash)
        if actual_hash != snapshot_hash:
            raise EvidenceError("live_inference_snapshot_mismatch")
        history = snapshot.history
    elif operation == "replay":
        # Operator-only diagnostic mode: does not grant qualification or claim live input.
        from app.modules.autonomy.artifact_io import ArtifactStore
        history = parse_json(ArtifactStore(registry.configuration().artifact_root).read(replay_history))
    # Parent cleans the stage because irreversible confinement makes source read-only.
    with tempfile.TemporaryDirectory(prefix="live-frozen-", delete=False) as directory:
        root = Path(directory)
        source = root / "source"
        source.mkdir(mode=0o700)
        for name, content in installation.sources.items():
            (source / name).write_bytes(content)
        (root / "checkpoint.ptz").write_bytes(installation.checkpoint)
        if installation.parent_checkpoint is not None:
            (root / "parent.ptz").write_bytes(installation.parent_checkpoint)
        if history is not None:
            (root / "history.json").write_text(json.dumps(history, allow_nan=False))
        if operation == "qualify":
            for index, session in enumerate(model.sessions):
                target = root / "benchmark" / str(index)
                target.mkdir(parents=True, mode=0o700)
                (target / "summary.json").write_bytes(documents[session.summary.path])
                (target / "evidence.jsonl").write_bytes(documents[session.evidence.path])
        scratch = root / "scratch"
        scratch.mkdir(mode=0o700)
        os.environ.update(HOME=str(scratch), TMPDIR=str(scratch))
        tempfile.tempdir = str(scratch)
        os.chdir(scratch)
        deny_control_access()
        confine_filesystem(root, scratch)
        alias = "_nanfo_live_frozen"
        spec = importlib.util.spec_from_file_location(alias, source / "__init__.py",
                                                     submodule_search_locations=[str(source)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[alias] = package
        spec.loader.exec_module(package)
        cli = importlib.import_module(f"{alias}.cli")
        artifacts = importlib.import_module(f"{alias}.artifacts")
        if artifacts.clientSources() != model.source_sha256:
            raise EvidenceError("live_frozen_source_mismatch")
        result = dict(operation=operation, registry_sha256=installation.sha256,
            checkpoint_sha256=model.checkpoint.sha256, weights_sha256=installation.manifest["weights_sha256"],
            source_sha256=canonical_hash(model.source_sha256), contract_sha256=model.contract_sha256,
            spec_sha256=model.spec_sha256, report_sha256=model.report.sha256,
            qualification_protocol=model.qualification_protocol,
            parent_checkpoint_sha256=model.parent_checkpoint.sha256 if model.parent_checkpoint else None,
            scope="stationary-campus-small-v4-scoped-benchmark")
        if operation == "qualify":
            validate_benchmark(cli, artifacts, root, installation, documents)
        else:
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                code = cli.main(["infer", "--checkpoint", str(root / "checkpoint.ptz"),
                                 "--history", str(root / "history.json")])
            if code:
                raise EvidenceError("live_frozen_measurement_invalid")
            inferred = parse_json(output.getvalue().encode())
            if (inferred["policy_sha256"] != model.checkpoint.sha256
                    or inferred["contract_hash"] != model.contract_sha256
                    or inferred["spec_hash"] != model.spec_sha256):
                raise EvidenceError("live_frozen_result_identity_mismatch")
            result.update({key: inferred[key] for key in ("action", "probabilities", "value", "input_sha256", "inference_seconds")})
            result.update(action_path=installation.manifest["contract"]["action_map"][inferred["action"]],
                          history_sha256=canonical_hash(history), snapshot_sha256=snapshot_hash)
        return RuntimeResult.model_validate(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("qualify", "infer", "replay"))
    parser.add_argument("--network-id", type=uuid.UUID)
    parser.add_argument("--workspace-id", type=uuid.UUID)
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--replay-history")
    args = parser.parse_args()
    try:
        result = run(args.operation, args.network_id, args.workspace_id, args.snapshot_sha256, args.replay_history)
        print(result.model_dump_json())
        return 0
    except Exception:  # noqa: BLE001 - no artifact paths, loader internals or measured data on stderr
        print('{"error":"live_frozen_validation_failed"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
