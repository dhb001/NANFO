"""Private lineage fixtures: never new qualification or measured acquisition."""

import copy
import io
import json
import zipfile
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.modules.autonomy.live_schemas import LiveInstallation
from app.modules.autonomy.registry import validate_rebuilt_lineage
from scripts.frozen_live_inference import (
    REBUILT_GATES,
    validate_benchmark_gates,
    validate_rebuilt_capture,
    validate_rebuilt_plan,
)
from scripts.frozen_model_diagnostic import canonical_hash
from tests.live_provider_support import CHECKPOINT, ROOT, provision


def rewritten(parent, mutate):
    with zipfile.ZipFile(io.BytesIO(parent)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        weights = archive.read("weights.pt")
    manifest["lab_provenance"]["lab_image_id"] = "sha256:" + "1" * 64
    mutate(manifest)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("weights.pt", weights)
    return output.getvalue()


def test_exact_image_only_parent_relation():
    parent = (ROOT / CHECKPOINT).read_bytes()
    derived = rewritten(parent, lambda _: None)
    manifest = validate_rebuilt_lineage(derived, parent)
    assert manifest["weights_sha256"] == "3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967"
    with pytest.raises(ValueError, match="parent_manifest_mismatch"):
        validate_rebuilt_lineage(parent, parent)


def test_actual_recovery_artifact_lineage_when_supplied():
    """Read-only artifact relation, never a campaign pass or inference qualification."""
    import os
    from pathlib import Path
    path = os.environ.get("NANFO_REBUILT_CHECKPOINT_TEST")
    if not path:
        pytest.skip("actual derived artifact not supplied")
    parent = validate_rebuilt_lineage(Path(path).read_bytes(), (ROOT / CHECKPOINT).read_bytes())
    assert parent["weights_sha256"] == "3e7e38ab4297ffd4b32b9c32d64af4b45e5f5ed1b2a74f9926f23379b0b0f967"


@pytest.mark.parametrize("field", ["transitions", "config", "client_source_files", "versions", "evidence_sha256", "lab_provenance"])
def test_lineage_rejects_every_nonimage_change(field):
    parent = (ROOT / CHECKPOINT).read_bytes()
    def mutate(manifest):
        if isinstance(manifest[field], dict):
            manifest[field]["unauthorized"] = "changed"
        elif isinstance(manifest[field], str):
            manifest[field] = "0" * 64
        else:
            manifest[field] += 1
    with pytest.raises(ValueError):
        validate_rebuilt_lineage(rewritten(parent, mutate), parent)


def test_rebuilt_protocol_requires_pinned_parent(tmp_path):
    _, _, _, document = provision(tmp_path)
    document = copy.deepcopy(document)
    document["qualification_protocol"] = "adr024-rebuilt-evaluation-v1"
    with pytest.raises(ValueError, match="parent_required"):
        LiveInstallation.model_validate(document)
    document["parent_checkpoint"] = document["checkpoint"]
    document["lineage"] = document["plan"]
    document["seed_audit"] = document["plan"]
    for session in document["sessions"]:
        session["attachment"] = session["summary"]
    LiveInstallation.model_validate(document)
    document["qualification_protocol"] = "adr014-test-only-v1"
    with pytest.raises(ValueError, match="parent_required"):
        LiveInstallation.model_validate(document)


@pytest.fixture
def rebuilt_documents(tmp_path):
    registry, _, _, document = provision(tmp_path)
    original = registry.load()
    parent = {"checkpoint_sha256": original.model.checkpoint.sha256, "manifest": original.manifest}
    manifest = copy.deepcopy(original.manifest)
    manifest["lab_provenance"]["lab_image_id"] = "sha256:" + "1" * 64
    document.update(qualification_protocol="adr024-rebuilt-evaluation-v1", parent_checkpoint=document["checkpoint"],
                    checkpoint=document["checkpoint"] | {"sha256": "1" * 64},
                    lineage={"path": "lineage.json", "sha256": "2" * 64, "size_bytes": 1},
                    seed_audit={"path": "audit.json", "sha256": "3" * 64, "size_bytes": 1})
    for session in document["sessions"]:
        session["attachment"] = session["summary"] | {"path": "attachment.json"}
    model = LiveInstallation.model_validate(document)
    installation = replace(original, model=model, manifest=manifest)
    identity = {"checkpoint_sha256": model.checkpoint.sha256, "manifest": manifest}
    plan = dict(version=model.qualification_protocol, checkpoint=identity, parent_checkpoint_sha256=model.parent_checkpoint.sha256,
        image_id=manifest["lab_provenance"]["lab_image_id"], lineage_sha256=model.lineage.sha256,
        seed_audit_sha256=model.seed_audit.sha256, client_source_sha256=model.source_sha256, runtime_versions=model.runtime_versions,
        created_unix=1000., qualification=REBUILT_GATES, test_attempts_before_selection=0, scenarios=["path0", "path1"],
        steps=4, window_seconds=2., test_seeds=list(range(3100, 3112)), selection_rule="private-fixture",
        scope="stationary-campus-small-v4-scoped-benchmark", autonomous_dispatch=False)
    selection = dict(plan_sha256=model.plan.sha256, checkpoint=identity, selection_rule=plan["selection_rule"], test_only=True)
    lineage = dict(version=model.qualification_protocol, operation="provenance-rebinding-only-no-training",
        parent_checkpoint_sha256=model.parent_checkpoint.sha256, derived_checkpoint_sha256=model.checkpoint.sha256,
        parent_manifest_sha256=canonical_hash(parent["manifest"]), derived_manifest_sha256=canonical_hash(manifest),
        tensor_payload_sha256=manifest["weights_sha256"], exact_tensor_bytes_equal=True,
        parent_image_id=parent["manifest"]["lab_provenance"]["lab_image_id"], image_id=plan["image_id"],
        source_sha256=manifest["environment_spec"]["source_sha256"], client_source_sha256=model.source_sha256,
        changed_manifest_fields=["lab_provenance.lab_image_id"], qualified=False)
    reserved = sorted({*range(3900, 3912), *parent["manifest"]["training_seeds"]})
    audit = dict(version=1, selected_seeds=plan["test_seeds"], reserved_seeds=reserved,
                 documents=[{"path": "private-fixture", "sha256": "a" * 64, "seeds": reserved}])
    documents = {model.lineage.path: json.dumps(lineage).encode(), model.seed_audit.path: json.dumps(audit).encode()}
    return plan, selection, identity, installation, documents, parent


def test_rebuilt_plan_exact_writer_fields(rebuilt_documents):
    validate_rebuilt_plan(*rebuilt_documents)


@pytest.mark.parametrize("change", ["historical", "seeds", "gates", "image", "parent", "source", "selection", "lineage", "audit"])
def test_rebuilt_plan_cannot_borrow_old_qualification(rebuilt_documents, change):
    plan, selection, identity, installation, documents, parent = rebuilt_documents
    if change == "historical":
        plan["version"] = "adr014-test-only-v1"
    elif change == "seeds":
        plan["test_seeds"] = list(range(3900, 3912))
    elif change == "gates":
        plan["qualification"] = REBUILT_GATES | {"constant_reward_margin_strict_gt": 0}
    elif change == "image":
        plan["image_id"] = parent["manifest"]["lab_provenance"]["lab_image_id"]
    elif change == "parent":
        plan["parent_checkpoint_sha256"] = "0" * 64
    elif change == "source":
        plan["client_source_sha256"] = {}
    elif change == "selection":
        selection["plan_sha256"] = "0" * 64
    else:
        path = installation.model.lineage.path if change == "lineage" else installation.model.seed_audit.path
        documents[path] = b'{"qualified":true}'
    with pytest.raises(ValueError):
        validate_rebuilt_plan(plan, selection, identity, installation, documents, parent)


@pytest.mark.parametrize("change", [None, "before_plan", "before_attach", "image", "incomplete", "header"])
def test_raw_capture_chronology_and_image(rebuilt_documents, change):
    import hashlib
    plan, _, _, installation, _, _ = rebuilt_documents
    manifest = installation.manifest
    header = b'{"kind":"session"}\n'
    rows = [dict(kind="ipc", request={"command": "step"}, response={"data": {"evidence": {
        "post_control_interval": {"start": 11. + i * 3, "end": 13. + i * 3},
        "provenance": manifest["lab_provenance"], "environment_spec": manifest["environment_spec"],
        "spec_hash": manifest["spec_hash"]}}}) for i in range(60)]
    attachment = dict(session_sha256=hashlib.sha256(header).hexdigest(), feed_offset=len(header),
                      attached_unix=1001., attached_monotonic=10.)
    if change == "before_plan":
        attachment["attached_unix"] = 999.
    elif change == "before_attach":
        attachment["attached_monotonic"] = 12.
    elif change == "image":
        rows[0]["response"]["data"]["evidence"]["provenance"] = {"lab_image_id": "old"}
    elif change == "incomplete":
        rows.pop()
    elif change == "header":
        attachment["session_sha256"] = "0" * 64
    session = SimpleNamespace(attachment=SimpleNamespace(path="attachment"), evidence=SimpleNamespace(path="raw"))
    docs = {"attachment": json.dumps(attachment).encode(), "raw": header + b"\n".join(json.dumps(row).encode() for row in rows)}
    summary = {"lab_provenance": manifest["lab_provenance"], "environment_spec": manifest["environment_spec"]}
    if change:
        with pytest.raises(ValueError):
            validate_rebuilt_capture(plan, summary, session, docs, manifest)
    else:
        validate_rebuilt_capture(plan, summary, session, docs, manifest)


@pytest.mark.parametrize("gate", [None, "constant0", "constant1", "ospf_goodput", "ospf_rtt", "direction", "schedules"])
def test_both_protocols_share_strict_original_gates(gate):
    report = dict(comparable_held_out_schedules=True, paired_seed_comparisons=[
        {"baseline": policy, "metrics": {"reward": {"paired_seed_count": 12, "mean_delta": .03, "ci95": [.01, .05]}}}
        for policy in ("constant0", "constant1")], sessions=[{"policy": "ppo", "reconstructed_steps": [
            {"scenario": scenario, "action": desired} for scenario, desired in (("path0", 1), ("path1", 0)) for _ in range(24)]}])
    ospf = {"goodput_mbps": {"paired_seed_count": 12, "ci95": [.1, .2]},
            "icmp_rtt_ms": {"paired_seed_count": 12, "ci95": [-.2, -.1]}}
    report["paired_seed_comparisons"].append({"baseline": "ospf", "metrics": ospf})
    if gate in ("constant0", "constant1"):
        report["paired_seed_comparisons"][int(gate[-1])]["metrics"]["reward"]["mean_delta"] = .02
    elif gate == "ospf_goodput":
        ospf["goodput_mbps"]["ci95"][0] = 0
    elif gate == "ospf_rtt":
        ospf["icmp_rtt_ms"]["ci95"][1] = 0
    elif gate == "direction":
        for row in report["sessions"][0]["reconstructed_steps"][:12]:
            row["action"] = 0
    elif gate == "schedules":
        report["comparable_held_out_schedules"] = False
    if gate:
        with pytest.raises(ValueError):
            validate_benchmark_gates(report)
    else:
        validate_benchmark_gates(report)
