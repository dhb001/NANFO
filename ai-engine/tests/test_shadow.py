"""Synthetic offline decision-contract tests, never measured acceptance or calibration."""

import ast
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from shadow.evaluate import canonicalHash, diagnosticFromExport, evaluate  # noqa: E402
from shadow.io import loadEvaluation, parseJson, readPinned  # noqa: E402
from shadow.schemas import (  # noqa: E402
    METHODS,
    Decision,
    Diagnostic,
    DiagnosticResult,
    ModelIdentity,
    Outcomes,
    Plan,
)
from shadow_evaluate import main as shadowMain  # noqa: E402

sys.path.remove(str(SCRIPTS))

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
SCOPE = {
    "network_id": "00000000-0000-0000-0000-000000000001",
    "workspace_id": "00000000-0000-0000-0000-000000000002",
}
DIAGNOSTIC_ID = "00000000-0000-0000-0000-000000000003"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def timestamp(seconds):
    return (NOW + timedelta(seconds=seconds)).isoformat()


def validated(cls, value):
    return cls.model_validate_json(json.dumps(value))


@pytest.fixture
def bundle():
    observation = {
        "path_capacity_mbps": [2.0, 20.0],
        "path_utilization": [0.96, 0.3],
        "path_queue_packets": [10.0, 0.0],
        "latency_ms": 12.0,
        "loss_fraction": 0.02,
        "goodput_mbps": 1.8,
        "offered_mbps": 4.0,
        "actual_offered_mbps": 4.0,
        "background_mbps": 1.0,
        "previous_action": 0,
        "seconds_since_change": 10.0,
    }
    model = {key: digest(key.encode()) for key in ModelIdentity.model_fields}
    model.update(
        model_id="incumbent",
        checkpoint_id="train-06",
        history_reference="history-06",
        input_sha256=canonicalHash(observation),
        benchmark_evidence_sha256=digest(b"benchmark"),
    )
    comparison = {
        key: digest(key.encode())
        for key in (
            "lab_provenance_sha256",
            "topology_sha256",
            "addressing_sha256",
            "queues_sha256",
            "ospf_costs_sha256",
            "measurement_sha256",
        )
    }
    comparison.update(
        spec_hash=model["spec_hash"],
        contract_hash=model["contract_hash"],
        mode="matched",
        provenance="historical_measured_v4",
        latency_metric="icmp_rtt_ms",
        window_seconds=2.0,
        episode_steps=4,
    )
    cases = [
        {
            "seed": seed,
            "scenario": scenario,
            "workload_sha256": digest(f"workload:{seed}".encode()),
            "schedule_sha256": digest(f"schedule:{seed}".encode()),
        }
        for seed, scenario in ((3900, "path0"), (3901, "path1"))
    ]
    methods = [
        {
            "method": method,
            "policy_sha256": model["policy_sha256"] if method == "ppo" else digest(method.encode()),
        }
        for method in METHODS
    ]
    diagnostic = {
        **SCOPE,
        "diagnostic_id": DIAGNOSTIC_ID,
        "actor_id": "operator",
        "created_at": timestamp(-10),
        "result": {
            **model,
            "action": 1,
            "action_path": ["a", "c", "d"],
            "probabilities": [0.01, 0.99],
            "value": 0.8,
            "inference_seconds": 0.001,
            "artifact_validation_and_inference_seconds": 0.1,
            "subprocess_seconds": 0.2,
            "evidence": [observation],
            "history_kind": "historical_measured_v4",
            "live": False,
            "execution": "not_applied",
            "safety_authorized": False,
            "probabilities_are_safety_confidence": False,
            "benchmark_status": "qualified_scoped_benchmark",
            "benchmark_scope": "Synthetic fixture for matched stationary contract tests.",
            "benchmark_limitations": ["Fixture, not real calibration or qualification."],
        },
    }
    rows = []
    for case in cases:
        for method in methods:
            rows.append(
                {
                    **SCOPE,
                    "case": deepcopy(case),
                    **method,
                    "comparison": deepcopy(comparison),
                    "split": "test",
                    "measured_start": timestamp(-70),
                    "measured_end": timestamp(-60),
                    "raw_evidence_sha256": digest(f"{case['seed']}:{method['method']}".encode()),
                    "status": "completed",
                    "reward": 0.8 if method["method"] == "ppo" else 0.6,
                    "goodput_mbps": 3.0,
                    "loss_fraction": 0.01,
                    "icmp_rtt_ms": 5.0,
                    "route_changes": 1,
                }
            )
    outcomes = {
        "version": 1,
        "benchmark_evidence_sha256": model["benchmark_evidence_sha256"],
        "rows": rows,
    }
    plan = {
        **SCOPE,
        "version": 1,
        "purpose": "historical_shadow_review",
        "frozen_at": timestamp(-200),
        "selected_at": timestamp(-100),
        "selection_split": "validation",
        "train_seeds": [1000],
        "validation_seeds": [2000],
        "cases": cases,
        "methods": methods,
        "comparison": comparison,
        "model": model,
        "diagnostic_id": DIAGNOSTIC_ID,
        "diagnostic_sha256": "a" * 64,
        "outcomes_sha256": "b" * 64,
        "observation_at": timestamp(-20),
        "action_paths": [["a", "b", "d"], ["a", "c", "d"]],
        "allowed_actions": [0, 1],
        "max_age_seconds": 120.0,
        "utilization_review_threshold": 0.9,
        "loss_review_threshold": 0.01,
    }
    return plan, diagnostic, outcomes


def review(bundle, now=NOW):
    plan, diagnostic, outcomes = bundle
    return evaluate(
        validated(Plan, plan),
        validated(Diagnostic, diagnostic),
        validated(Outcomes, outcomes),
        now=now,
        plan_sha256="f" * 64,
    )


def writeBundle(tmp_path, bundle, export=None):
    plan, diagnostic, outcomes = deepcopy(bundle)
    paths = {
        key: tmp_path / f"{key}.json" for key in ("plan", "diagnostic", "outcomes", "benchmark")
    }
    paths["diagnostic"].write_bytes(json.dumps(export or diagnostic).encode())
    paths["outcomes"].write_bytes(json.dumps(outcomes).encode())
    paths["benchmark"].write_bytes(b"benchmark")
    plan["diagnostic_sha256"] = digest(paths["diagnostic"].read_bytes())
    plan["outcomes_sha256"] = digest(paths["outcomes"].read_bytes())
    paths["plan"].write_bytes(json.dumps(plan).encode())
    return {f"{key}_path": path for key, path in paths.items()} | {
        "plan_sha256": digest(paths["plan"].read_bytes()),
        "now": NOW,
    }


def test_useful_typed_shadow_review(bundle):
    decision = review(bundle)
    assert decision.status == "review"
    assert len(decision.comparisons) == 20
    reward = decision.comparisons[0]
    assert reward.paired_seeds == [3900, 3901]
    assert reward.mean_policy_minus_baseline == pytest.approx(0.2)
    assert reward.standard_error == 0
    assert [finding.agent for finding in decision.findings] == ["capacity", "failure", "policy"]
    assert [finding.status for finding in decision.findings] == ["review", "review", "observed"]
    assert all(finding.assumptions and finding.evidence_references for finding in decision.findings)
    assert {item.option for item in decision.alternatives} == set(METHODS[1:]) | {"hold_and_review"}
    assert decision.qualification.safety_confidence is None
    assert not decision.qualification.calibrated
    assert not decision.safety_authorized and decision.execution == "not_applied"
    assert not decision.production_dispatch and not decision.online_learning
    assert "authorized_executor" in decision.unavailable_providers
    assert Decision.model_validate_json(decision.model_dump_json()) == decision


@pytest.mark.parametrize("field", list(ModelIdentity.model_fields))
def test_every_model_input_provenance_identity_is_bound(bundle, field):
    bundle[1]["result"][field] = (
        "other" if field.endswith("_id") or field == "history_reference" else "0" * 64
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        review(bundle)


@pytest.mark.parametrize("target", ["diagnostic", "outcome"])
@pytest.mark.parametrize("field", ["network_id", "workspace_id"])
def test_no_cross_scope_evidence(bundle, target, field):
    value = bundle[1] if target == "diagnostic" else bundle[2]["rows"][0]
    value[field] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    with pytest.raises(ValueError, match="scope"):
        review(bundle)


@pytest.mark.parametrize(
    "field",
    [
        "spec_hash",
        "contract_hash",
        "lab_provenance_sha256",
        "topology_sha256",
        "addressing_sha256",
        "queues_sha256",
        "ospf_costs_sha256",
        "measurement_sha256",
    ],
)
def test_comparison_semantics_must_match(bundle, field):
    bundle[2]["rows"][1]["comparison"][field] = "e" * 64
    with pytest.raises(ValueError, match="comparability"):
        review(bundle)


@pytest.mark.parametrize(
    "field,value",
    [
        ("window_seconds", 3.0),
        ("episode_steps", 5),
        ("mode", "sdn"),
        ("provenance", "synthetic"),
        ("latency_metric", "udp_rtt_ms"),
    ],
)
def test_mismatched_measurement_or_dataplane_rejected(bundle, field, value):
    bundle[2]["rows"][1]["comparison"][field] = value
    with pytest.raises(ValueError):
        review(bundle)


@pytest.mark.parametrize("field", ["schedule_sha256", "workload_sha256", "scenario"])
def test_matched_baseline_case_binding(bundle, field):
    bundle[2]["rows"][1]["case"][field] = "different" if field == "scenario" else "d" * 64
    with pytest.raises(ValueError, match="comparability"):
        review(bundle)


@pytest.mark.parametrize("change", ["missing", "duplicate", "extra_seed", "reused_raw", "policy"])
def test_complete_baselines_no_selective_comparison(bundle, change):
    rows = bundle[2]["rows"]
    if change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows[-1] = deepcopy(rows[0])
    elif change == "extra_seed":
        rows[-1]["case"]["seed"] = 3902
    elif change == "reused_raw":
        rows[-1]["raw_evidence_sha256"] = rows[0]["raw_evidence_sha256"]
    else:
        rows[-1]["policy_sha256"] = "d" * 64
    with pytest.raises(ValueError):
        review(bundle)


@pytest.mark.parametrize(
    "change",
    [
        "train",
        "validation",
        "case",
        "duplicate",
        "select_test",
        "preselection",
        "freeze",
        "interval",
        "short",
        "wrong_split",
    ],
)
def test_leakage_and_incomplete_measurements_refused(bundle, change):
    plan, _, outcomes = bundle
    if change in ("train", "validation"):
        plan[f"{change}_seeds"] = [3900]
    elif change == "case":
        plan["cases"][0]["seed"] = 2000
    elif change == "duplicate":
        plan["cases"][1]["seed"] = 3900
    elif change == "select_test":
        plan["selection_split"] = "test"
    elif change == "preselection":
        outcomes["rows"][0]["measured_start"] = plan["selected_at"]
    elif change == "freeze":
        plan["frozen_at"] = timestamp(-50)
    elif change == "wrong_split":
        outcomes["rows"][0]["split"] = "train"
    elif change == "interval":
        outcomes["rows"][0]["measured_end"] = timestamp(-80)
    else:
        outcomes["rows"][0]["measured_end"] = timestamp(-69)
    with pytest.raises(ValueError):
        review(bundle)


def test_outcomes_never_select_model_or_enter_domain_agents(bundle):
    before = review(bundle)
    for row in bundle[2]["rows"]:
        row.update(
            reward=-100.0 if row["method"] == "ppo" else 100.0, loss_fraction=1.0, goodput_mbps=0.0
        )
    after = review(bundle)
    assert after.comparisons != before.comparisons
    for key in (
        "diagnostic_action",
        "model",
        "findings",
        "status",
        "qualification",
        "alternatives",
    ):
        assert getattr(after, key) == getattr(before, key)


@pytest.mark.parametrize("probabilities", [[0.0, 1.0], [0.49, 0.51], [0.5, 0.5]])
def test_policy_probability_is_never_safety_confidence(bundle, probabilities):
    bundle[1]["result"]["probabilities"] = probabilities
    decision = review(bundle)
    assert decision.qualification.safety_confidence is None
    assert not decision.probabilities_are_safety_confidence
    assert not decision.safety_authorized


@pytest.mark.parametrize(
    "field,value",
    [
        ("action", True),
        ("action", 1.0),
        ("probabilities", [0.1, 0.1]),
        ("probabilities", [0.99, 0.01]),
        ("value", float("nan")),
        ("live", True),
        ("live", 0),
        ("execution", "completed"),
        ("safety_authorized", True),
        ("probabilities_are_safety_confidence", True),
    ],
)
def test_strict_diagnostic_rejects_invalid_or_actuating_claims(bundle, field, value):
    bundle[1]["result"][field] = value
    with pytest.raises(ValueError):
        review(bundle)


def test_input_hash_is_recomputed_and_route_is_bound(bundle):
    bundle[1]["result"]["evidence"][-1]["goodput_mbps"] = 9.0
    with pytest.raises(ValueError, match="input evidence hash"):
        review(bundle)
    bundle[1]["result"]["evidence"][-1]["goodput_mbps"] = 1.8
    bundle[1]["result"]["action_path"] = ["a", "b", "d"]
    with pytest.raises(ValueError, match="path contract"):
        review(bundle)


def test_fresh_record_cannot_refresh_stale_observation(bundle):
    bundle[0]["observation_at"] = timestamp(-120)
    decision = review(bundle)
    assert decision.status == "abstain"  # exclusive deadline
    assert decision.freshness.status == "stale"
    assert "evidence_stale" in decision.abstention_reasons
    bundle[0]["observation_at"] = timestamp(-119.99)
    assert review(bundle).freshness.status == "within_review_window"


def test_stale_outcome_and_future_record_abstain(bundle):
    assert review(bundle, NOW + timedelta(seconds=50)).freshness.status == "stale"
    bundle[1]["created_at"] = timestamp(1)
    assert review(bundle).freshness.status == "future"
    assert review(bundle).status == "abstain"


def test_unqualified_forbidden_action_and_incomplete_data_abstain(bundle):
    plan, diagnostic, _ = bundle
    plan["allowed_actions"] = [0]
    diagnostic["result"]["benchmark_status"] = "not_qualified"
    diagnostic["result"]["evidence"][0]["path_capacity_mbps"][0] = None
    pin = canonicalHash(diagnostic["result"]["evidence"][0])
    diagnostic["result"]["input_sha256"] = plan["model"]["input_sha256"] = pin
    decision = review(bundle)
    assert set(decision.abstention_reasons) == {
        "benchmark_not_qualified",
        "action_outside_review_policy",
        "incomplete_observation",
    }
    assert decision.findings[0].status == "unavailable"
    assert decision.findings[2].status == "review"


def test_censored_rtt_never_imputed_or_hidden(bundle):
    bundle[2]["rows"][0]["icmp_rtt_ms"] = None
    comparison = next(
        row
        for row in review(bundle).comparisons
        if row.baseline == "ospf" and row.metric == "icmp_rtt_ms"
    )
    assert comparison.paired_seeds == [3901] and comparison.missing_seeds == [3900]
    assert comparison.standard_error is None


@pytest.mark.parametrize("kind", ["record", "post", "get"])
def test_read_only_backend_export_compatibility(tmp_path, bundle, backendExports, kind):
    export = backendExports[kind]
    args = writeBundle(tmp_path, bundle, export)
    assert loadEvaluation(**args).status == "review"


@pytest.fixture
def backendExports(bundle, monkeypatch):
    """Serialize actual backend models, without backend services or historical files.

    Values are synthetic contract fixtures, not claims of recorded inference. Model
    validators/defaults and UUID/date/union serialization are the production code.
    Only these schema modules (stdlib + Pydantic) are imported; no config stubs.
    """
    monkeypatch.syspath_prepend(str(SCRIPTS.parents[1] / "backend"))
    from app.modules.autonomy.model_diagnostic_schemas import (
        ModelDiagnosticRecord,
        ModelDiagnosticsResponse,
        RegisteredModelStatus,
    )

    _, diagnostic, _ = bundle
    record = ModelDiagnosticRecord.model_validate(diagnostic)
    result = record.result
    status = RegisteredModelStatus(
        model_id=result.model_id,
        checkpoint_id=result.checkpoint_id,
        checkpoint_sha256=result.policy_sha256,
        history_references=[result.history_reference],
        benchmark_status=result.benchmark_status,
        benchmark_scope=result.benchmark_scope,
        benchmark_limitations=result.benchmark_limitations,
    )
    response = ModelDiagnosticsResponse(
        network_id=record.network_id,
        workspace_id=record.workspace_id,
        status="operator_registered",
        reasons=["compatible_live_history_unavailable"],
        model=status,
        diagnostics=[record],
    )
    # Exercise defaults supplied by the real backend, then JSON roundtrip using
    # the same models that the GET and POST routers declare as response data.
    response = ModelDiagnosticsResponse.model_validate_json(response.model_dump_json())
    record = ModelDiagnosticRecord.model_validate_json(record.model_dump_json())
    assert response.live_history_status == "unavailable"
    assert response.model.status == "operator_registered"
    assert not response.production_dispatch and not record.result.safety_authorized
    meta = {
        "request_id": "shadow-schema-compatibility-test",
        "timestamp": timestamp(-5),
        "execution_time_ms": 1,
        "execution_mode": "emulation",
    }
    return {
        "record": record.model_dump(mode="json"),
        "post": {
            "success": True,
            "data": record.model_dump(mode="json"),
            "meta": meta,
            "errors": None,
        },
        "get": {
            "success": True,
            "data": response.model_dump(mode="json"),
            "meta": meta,
            "errors": None,
        },
    }


@pytest.mark.parametrize("kind", ["record", "post", "get"])
@pytest.mark.parametrize("invocation", ["script", "module"])
def test_backend_export_cli_clean_checkout(tmp_path, bundle, backendExports, kind, invocation):
    """Full CLI example: real backend serialization -> pinned files -> child -> decision.

    Copy only new source to an otherwise empty checkout layout, excluding artifacts,
    installed NANFO packages, backend services and bytecode. The child has no
    PYTHONPATH or operator provider environment. Pydantic is the only dependency.
    """
    checkout = tmp_path / "checkout" / "ai-engine"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    shutil.copytree(
        SCRIPTS / "shadow", scripts / "shadow", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copyfile(SCRIPTS / "shadow_evaluate.py", scripts / "shadow_evaluate.py")
    evidence = tmp_path / "inputs"
    evidence.mkdir()
    args = writeBundle(evidence, bundle, backendExports[kind])
    # Deliberately old and expired, so CI date cannot turn this into a fresh review.
    plan = json.loads(args["plan_path"].read_bytes())
    for field in ("frozen_at", "selected_at", "observation_at"):
        plan[field] = plan[field].replace("2026-", "2000-")
    args["plan_path"].write_text(json.dumps(plan))
    args["plan_sha256"] = digest(args["plan_path"].read_bytes())
    cli = (
        ["-m", "scripts.shadow_evaluate"]
        if invocation == "module"
        else [str(scripts / "shadow_evaluate.py")]
    )
    command = [
        sys.executable,
        "-B",
        *cli,
        "--plan",
        str(args["plan_path"]),
        "--plan-sha256",
        args["plan_sha256"],
        "--diagnostic",
        str(args["diagnostic_path"]),
        "--outcomes",
        str(args["outcomes_path"]),
        "--benchmark",
        str(args["benchmark_path"]),
    ]
    environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "HOME": str(tmp_path)}
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    completed = subprocess.run(
        command,
        cwd=checkout if invocation == "module" else tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 2, completed.stderr
    assert not completed.stderr
    decision = Decision.model_validate_json(completed.stdout)
    assert decision.status == "abstain" and "evidence_stale" in decision.abstention_reasons
    assert decision.model.input_sha256 == bundle[1]["result"]["input_sha256"]
    assert len(decision.comparisons) == 20
    assert decision.execution == "not_applied"
    assert not decision.safety_authorized and not decision.production_dispatch
    assert decision.qualification.safety_confidence is None
    assert not (checkout / "artifacts").exists() and not (checkout / "src").exists()
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before

    # Same real invocation rejects tampering, rather than emitting an executable decision.
    args["diagnostic_path"].write_bytes(args["diagnostic_path"].read_bytes() + b" ")
    rejected = subprocess.run(
        command,
        cwd=checkout if invocation == "module" else tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert rejected.returncode == 1 and not rejected.stdout
    assert json.loads(rejected.stderr)["execution"] == "not_applied"


def test_backend_result_field_compatibility_without_backend_import():
    path = SCRIPTS.parents[1] / "backend/app/modules/autonomy/model_diagnostic_schemas.py"
    tree = ast.parse(path.read_text())
    result = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DiagnosticResult"
    )
    fields = {node.target.id for node in result.body if isinstance(node, ast.AnnAssign)}
    assert fields == set(DiagnosticResult.model_fields)


def test_get_export_never_picks_latest_or_cross_scope(bundle):
    plan, diagnostic, _ = bundle
    export = {
        **SCOPE,
        "status": "operator_registered",
        "safety_authorized": False,
        "production_dispatch": False,
        "diagnostics": [diagnostic, diagnostic],
        "model": {
            "model_id": plan["model"]["model_id"],
            "checkpoint_id": plan["model"]["checkpoint_id"],
            "checkpoint_sha256": plan["model"]["policy_sha256"],
        },
    }
    with pytest.raises(ValueError, match="exactly one"):
        diagnosticFromExport(export, validated(Plan, plan))
    export["workspace_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    with pytest.raises(ValueError, match="scope"):
        diagnosticFromExport(export, validated(Plan, plan))


@pytest.mark.parametrize("data", [None, [], "invalid"])
def test_malformed_backend_envelope_is_rejected(bundle, data):
    with pytest.raises(ValueError, match="object required"):
        diagnosticFromExport(
            {"success": True, "data": data, "errors": None}, validated(Plan, bundle[0])
        )


@pytest.mark.parametrize("field", ["frozen_at", "selected_at", "observation_at"])
def test_timestamp_requires_explicit_timezone_not_epoch(bundle, field):
    for invalid in (123456.0, "2026-09-19T12:00:00"):
        bundle[0][field] = invalid
        with pytest.raises(ValueError):
            review(bundle)


@pytest.mark.parametrize("file", ["plan", "diagnostic", "outcomes", "benchmark"])
def test_operator_byte_pins_reject_tampering(tmp_path, bundle, file):
    args = writeBundle(tmp_path, bundle)
    with args[f"{file}_path"].open("ab") as output:
        output.write(b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        loadEvaluation(**args)


@pytest.mark.parametrize(
    "content",
    [
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b'{"a":1e999}',
        b"[]",
        b'{"a":' + b"[" * 30 + b"0" + b"]" * 30 + b"}",
    ],
)
def test_json_ambiguity_nonfinite_and_bounds(content):
    with pytest.raises(ValueError):
        parseJson(content)


def test_file_bounds_and_symlinks(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_bytes(b"12345")
    with pytest.raises(ValueError, match="bounded"):
        readPinned(path, digest(b"12345"), limit=4)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        readPinned(link, digest(b"12345"))


def test_no_command_or_provider_fields(bundle):
    bundle[0]["executor"] = "some.module:execute"
    with pytest.raises(ValidationError, match="Extra inputs"):
        review(bundle)


def test_cli_never_networks_executes_trains_or_writes(tmp_path, bundle, monkeypatch, capsys):
    args = writeBundle(tmp_path, bundle)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    def forbidden(*args, **kwargs):
        raise AssertionError("execution/network boundary crossed")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    original_import = __import__

    def guarded(name, *args, **kwargs):
        if name.startswith(("torch", "nanfo_routing", "app.", "gymnasium", "requests")):
            forbidden()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded)
    argv = [
        "--plan",
        str(args["plan_path"]),
        "--plan-sha256",
        args["plan_sha256"],
        "--diagnostic",
        str(args["diagnostic_path"]),
        "--outcomes",
        str(args["outcomes_path"]),
        "--benchmark",
        str(args["benchmark_path"]),
    ]
    # Real current time may make this dated fixture stale, which must still never act.
    assert shadowMain(argv) in (0, 2)
    output = json.loads(capsys.readouterr().out)
    assert output["execution"] == "not_applied" and not output["safety_authorized"]
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    args["benchmark_path"].write_bytes(b"tampered")
    assert shadowMain(argv) == 1
    captured = capsys.readouterr()
    assert not captured.out and "Traceback" not in captured.err
    assert json.loads(captured.err)["status"] == "rejected"


def test_shadow_is_outside_frozen_package_and_has_no_control_imports():
    forbidden = {"nanfo_routing", "torch", "gymnasium", "subprocess", "socket", "requests", "app"}
    for path in [*SCRIPTS.joinpath("shadow").glob("*.py"), SCRIPTS / "shadow_evaluate.py"]:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert not any(alias.name.split(".")[0] in forbidden for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden
    assert not (SCRIPTS.parent / "src/nanfo_routing/shadow.py").exists()
