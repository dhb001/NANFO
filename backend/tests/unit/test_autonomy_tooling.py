"""Synthetic offline fixtures test refusal/diagnostics, never qualify a real model."""

import copy
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.autonomy.artifact_io import ArtifactStore, EvidenceError, parse_json
from app.modules.autonomy.calibration import (
    CalibrationPlan,
    MeasuredTraces,
    assess_calibration,
    calibrate,
    universal_queue_bound,
)
from app.modules.autonomy.qualification import (
    MeasuredDecision,
    ProducerQualification,
    import_qualification,
    inspect_checkpoint_bytes,
    validate_producer_qualification,
)
from app.modules.autonomy.readiness_cli import assess, calibration_main, main

HASH = "a" * 64


def write_artifact(root, name, value):
    content = (
        value
        if isinstance(value, bytes)
        else json.dumps(value, allow_nan=False).encode()
    )
    (root / name).write_bytes(content)
    return {
        "path": name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


@pytest.fixture
def calibration_data():
    plan = {
        "schema_version": "nanfo.calibration-plan.v1",
        "spec_sha256": HASH,
        "contract_sha256": HASH,
        "declared_at_unix_seconds": 1.0,
        "fit_seeds": [1000],
        "holdout_seeds": [1001],
        "egress_ids": ["egress"],
        "action_ids": ["route0"],
        "min_samples_per_group": 2,
        "queue_threshold_bytes": 1000.0,
        "dt_seconds": 2.0,
    }
    samples = []
    for index, seed in enumerate([1000, 1000, 1001, 1001]):
        samples.append(
            {
                "sample_id": f"sample{index}",
                "episode_id": f"episode{seed}",
                "seed": seed,
                "action_id": "route0",
                "egress_id": "egress",
                "start_unix_seconds": 10.0 + index * 2,
                "end_unix_seconds": 12.0 + index * 2,
                "queue_before_bytes": 100.0,
                "queue_after_bytes": 50.0,
                "arrival_counter_before_bytes": 0,
                "arrival_counter_after_bytes": 100,
                "service_counter_before_bytes": 0,
                "service_counter_after_bytes": 150,
                "measurement_complete": True,
                "attribution_complete": True,
                "stationary": True,
                "counter_reset": False,
                "raw_evidence": {"path": "raw.json", "sha256": HASH, "size_bytes": 2},
            }
        )
    traces = {
        "schema_version": "nanfo.matched-queue-traces.v1",
        "provenance": "measured-lab",
        "dataplane": "linux-frr",
        "spec_sha256": HASH,
        "contract_sha256": HASH,
        "plan_sha256": HASH,
        "samples": samples,
    }
    return plan, traces


def run_calibration(data):
    plan, traces = data
    return calibrate(
        CalibrationPlan.model_validate(plan), MeasuredTraces.model_validate(traces)
    )


@pytest.fixture
def producer():
    metric = {
        "pairs": [
            {"seed": 2600, "policy": 0.9, "baseline": 0.5, "delta": 0.4},
            {"seed": 2601, "policy": 0.9, "baseline": 0.5, "delta": 0.4},
        ],
        "paired_seed_count": 2,
        "mean_delta": 0.4,
        "ci95": [0.4, 0.4],
        "method": "paired seed-mean Student-t interval; normality assumption",
        "limitation": "fixture",
    }
    return {
        "version": 3,
        "qualified": True,
        "scope": "useful adaptation on validation only",
        "checkpoint": {
            "checkpoint_sha256": HASH,
            "manifest": {"version": 3, "provenance": "measured-lab"},
        },
        "plan_sha256": HASH,
        "training_evidence_sha256": HASH,
        "train_only_action_effects": {"path0": 0.4, "path1": 0.4},
        "calibration_evidence_sha256": {"constant0": HASH, "constant1": HASH},
        "evidence_paths": {
            "checkpoint": "checkpoint.ptz",
            "training": "training.json",
            "validation": [f"validation-{i}.json" for i in range(5)],
            "calibration": ["calibration-0.json", "calibration-1.json"],
            "plan": "plan.json",
        },
        "validation_evidence_sha256": {
            p: HASH for p in ("ppo", "constant0", "constant1", "heuristic", "ospf")
        },
        "minimum_margin_exclusive": 0.02,
        "margins_over_both_constants": {"constant0": 0.4, "constant1": 0.4},
        "directional_dependence": {
            scenario: {
                "desired_route_fraction": 1.0,
                "pressure_swap_desired_route_fraction": 1.0,
                "swap_is_diagnostic_not_measured_reward": True,
            }
            for scenario in ("path0", "path1")
        },
        "comparisons": {
            p: {
                m: copy.deepcopy(metric)
                for m in ("reward", "goodput_mbps", "loss_fraction", "icmp_rtt_ms")
            }
            for p in ("constant0", "constant1", "heuristic", "ospf")
        },
        "validation_mean_reward": 0.9,
        "test_status": "not assessed; freeze selection before fresh holdout",
        "autonomous_dispatch": "blocked",
        "safety_guarantee": False,
        "limitation": "fixture",
    }


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/etc/passwd",
        "a/../b",
        "a//b",
        "./a",
        "a/./b",
        "a\\b",
        "",
        "a\x00b",
        "x" * 513,
        "/".join(["a"] * 33),
    ],
)
def test_artifact_paths_fail_closed(tmp_path, path):
    with pytest.raises(EvidenceError, match="artifact_path_not_allowed"):
        ArtifactStore(str(tmp_path)).read(path)


@pytest.mark.parametrize(
    "content",
    [
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":1e999}',
        b"\xff",
        b"[] trailing",
        b"[" * 30 + b"0" + b"]" * 30,
    ],
)
def test_json_rejects_ambiguous_and_unbounded(content):
    with pytest.raises(EvidenceError):
        parse_json(content)


def test_artifact_hash_size_missing_and_limit(tmp_path):
    ref = write_artifact(tmp_path, "value.json", {"value": 1})
    store = ArtifactStore(str(tmp_path))
    assert store.document("value.json") == {"value": 1}
    with pytest.raises(EvidenceError, match="artifact_hash_mismatch"):
        store.read("value.json", sha256=HASH)
    with pytest.raises(EvidenceError, match="artifact_size_mismatch"):
        store.read("value.json", size_bytes=1)
    with pytest.raises(EvidenceError, match="artifact_size_out_of_bounds"):
        store.read("value.json", limit=1)
    with pytest.raises(EvidenceError, match="artifact_missing"):
        store.read("missing.json")
    assert len(store.read(ref["path"])) == ref["size_bytes"]


def test_artifact_rejects_symlinks_and_fifo(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "value").write_bytes(b"x")
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    (tmp_path / "filelink").symlink_to(tmp_path / "real" / "value")
    os.mkfifo(tmp_path / "pipe")
    store = ArtifactStore(str(tmp_path))
    for path in ("link/value", "filelink", "pipe"):
        with pytest.raises(EvidenceError):
            store.read(path)


def test_artifact_relative_root_and_missing_configuration(monkeypatch):
    monkeypatch.delenv("NANFO_AUTONOMY_ARTIFACT_ROOT", raising=False)
    with pytest.raises(EvidenceError, match="unconfigured"):
        ArtifactStore.from_environment()
    with pytest.raises(EvidenceError, match="absolute"):
        ArtifactStore("relative")


def test_empirical_perfect_coverage_is_never_trusted(calibration_data):
    result = run_calibration(calibration_data)
    assert not result["qualified"] and result["trusted_calibration"] is None
    assert result["groups"][0]["holdout_queue_coverage"] == 1
    assert result["groups"][0]["worst_holdout_drift_bytes_squared"] == -3750
    assert "causal_arrival_service_guarantees_missing" in result["reasons"]


def test_calibration_fit_does_not_use_holdout(calibration_data):
    before = run_calibration(calibration_data)
    calibration_data[1]["samples"][-1]["queue_after_bytes"] = 999.0
    calibration_data[1]["samples"][-1]["arrival_counter_after_bytes"] = 200
    calibration_data[1]["samples"][-1]["service_counter_after_bytes"] = 0
    after = run_calibration(calibration_data)
    for key in (
        "arrival_fitted_max_bytes_per_second",
        "service_fitted_min_bytes_per_second",
        "error_fitted_max_bytes",
    ):
        assert before["groups"][0][key] == after["groups"][0][key]
    assert "empirical_holdout_coverage_failed" in after["reasons"]
    assert after["groups"][0]["holdout_queue_coverage"] == 0.5
    assert after["groups"][0]["failure_sample_ids"]["service"] == ["sample3"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seed", 2600),
        ("queue_before_bytes", True),
        ("measurement_complete", 1),
        ("counter_reset", 0),
        ("stationary", False),
        ("queue_after_bytes", float("nan")),
        ("arrival_counter_after_bytes", -1),
        ("fake", True),
    ],
)
def test_calibration_strict_measurements(calibration_data, field, value):
    calibration_data[1]["samples"][0][field] = value
    with pytest.raises(ValidationError):
        run_calibration(calibration_data)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda p, t: t["samples"].append(copy.deepcopy(t["samples"][0])),
            "duplicate_calibration_sample",
        ),
        (lambda p, t: t.update(spec_sha256="b" * 64), "calibration_contract_mismatch"),
        (
            lambda p, t: t["samples"][0].update(
                start_unix_seconds=1.0, end_unix_seconds=3.0
            ),
            "not_predeclared",
        ),
        (
            lambda p, t: t["samples"][0].update(end_unix_seconds=13.0),
            "horizon_mismatch",
        ),
        (lambda p, t: t["samples"][0].update(action_id="unknown"), "scope_mismatch"),
        (
            lambda p, t: t["samples"][1].update(
                start_unix_seconds=11.0, end_unix_seconds=13.0
            ),
            "windows_overlap",
        ),
        (lambda p, t: p.update(min_samples_per_group=3), "group_coverage_incomplete"),
        (lambda p, t: p["holdout_seeds"].append(1002), "seed_coverage_incomplete"),
        (
            lambda p, t: t["samples"][-1].update(episode_id="episode1000"),
            "episode_split_leakage",
        ),
    ],
)
def test_calibration_scope_and_leakage_refusals(calibration_data, mutation, reason):
    mutation(*calibration_data)
    with pytest.raises(EvidenceError, match=reason):
        run_calibration(calibration_data)


def test_fit_and_holdout_must_be_disjoint(calibration_data):
    calibration_data[0]["holdout_seeds"] = [1000]
    with pytest.raises(ValidationError, match="leakage"):
        run_calibration(calibration_data)


def test_zero_service_universal_bound_quantifies_infeasibility():
    result = universal_queue_bound(
        queue_bytes=0.0, arrival_upper_bytes_per_second=2_500_000.0, dt_seconds=2.0
    )
    assert result["q_next_upper_bytes"] == 5_000_000
    assert result["drift_upper_bytes_squared"] == 12_500_000_000_000
    assert not result["zero_budget_satisfied"]
    assert universal_queue_bound(
        queue_bytes=100, arrival_upper_bytes_per_second=0, dt_seconds=2
    )["zero_budget_satisfied"]
    assert not universal_queue_bound(
        queue_bytes=0,
        arrival_upper_bytes_per_second=0,
        dt_seconds=2,
        error_upper_bytes=1,
    )["zero_budget_satisfied"]


@pytest.mark.parametrize("number", [-1.0, float("inf"), float("nan"), True])
def test_universal_bound_rejects_invalid_values(number):
    with pytest.raises(EvidenceError):
        universal_queue_bound(
            queue_bytes=number, arrival_upper_bytes_per_second=1, dt_seconds=2
        )


def test_calibration_input_hash_binding(tmp_path, calibration_data):
    plan, traces = calibration_data
    raw = write_artifact(
        tmp_path, "raw.json", {"collector": "test fixture, not physical evidence"}
    )
    for sample in traces["samples"]:
        sample["raw_evidence"] = raw
    plan_ref = write_artifact(tmp_path, "plan.json", plan)
    traces["plan_sha256"] = plan_ref["sha256"]
    trace_ref = write_artifact(tmp_path, "traces.json", traces)
    write_artifact(
        tmp_path,
        "input.json",
        {
            "schema_version": "nanfo.calibration-input.v1",
            "plan": plan_ref,
            "traces": trace_ref,
        },
    )
    result = assess_calibration(ArtifactStore(str(tmp_path)), "input.json")
    assert not result["qualified"]
    (tmp_path / "raw.json").write_bytes(b"tampered")
    with pytest.raises(EvidenceError, match="artifact_size_mismatch"):
        assess_calibration(ArtifactStore(str(tmp_path)), "input.json")


def test_producer_schema_and_self_claim_are_not_qualification(tmp_path, producer):
    assert validate_producer_qualification(producer, None) == []
    write_artifact(tmp_path, "qualification.json", producer)
    with pytest.raises(EvidenceError, match="artifact_missing"):
        import_qualification(ArtifactStore(str(tmp_path)), "qualification.json")


def test_best_pointer_is_not_qualification(tmp_path):
    write_artifact(
        tmp_path, "best.json", {"checkpoint": "checkpoint.ptz", "mean_reward": 0.99}
    )
    with pytest.raises(EvidenceError, match="not_best_pointer"):
        import_qualification(ArtifactStore(str(tmp_path)), "best.json")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", True),
        ("qualified", 1),
        ("safety_guarantee", True),
        ("minimum_margin_exclusive", 0),
        ("autonomous_dispatch", "enabled"),
        ("unexpected", True),
    ],
)
def test_producer_strict_schema(producer, field, value):
    producer[field] = value
    with pytest.raises(ValidationError):
        ProducerQualification.model_validate(producer)


def test_producer_recomputes_counts_and_margins(producer):
    producer["comparisons"]["constant0"]["reward"]["pairs"][0]["delta"] = 0.9
    with pytest.raises(ValidationError):
        validate_producer_qualification(producer, None)


def test_producer_action_dependence_and_uncertainty(producer):
    producer["directional_dependence"]["path1"][
        "pressure_swap_desired_route_fraction"
    ] = 0.5
    producer["comparisons"]["constant0"]["reward"]["ci95"] = [-0.1, 0.9]
    producer["qualified"] = False
    reasons = validate_producer_qualification(producer, None)
    assert set(reasons) == {
        "heldout_policy_not_action_dependent",
        "paired_improvement_uncertain",
        "producer_model_unqualified",
    }


def test_cli_missing_files_and_default_remains_blocked(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("NANFO_AUTONOMY_ARTIFACT_ROOT", str(tmp_path))
    assert (
        main(["--qualification", "missing.json", "--calibration", "missing.json"]) == 2
    )
    result = json.loads(capsys.readouterr().out)
    assert result["assessments"]["qualification"]["reasons"] == ["artifact_missing"]
    assert "runtime_control_incompatible" in result["reasons"]
    assert "experiment_ownership_not_runtime_authority" in result["reasons"]
    assert not result["ready"] and not result["automatic_step"]
    assert result["runtime"]["executor_installed"] is False


def test_cli_no_configuration_or_artifacts(monkeypatch):
    monkeypatch.delenv("NANFO_AUTONOMY_ARTIFACT_ROOT", raising=False)
    result = assess()
    assert "operator_artifact_root_unconfigured" in result["reasons"]
    assert "qualification_artifact_not_supplied" in result["reasons"]
    assert "calibration_artifact_not_supplied" in result["reasons"]


def test_cli_universal_command(capsys):
    assert (
        calibration_main(["--universal-arrival-mbps", "20", "--dt-seconds", "2"]) == 2
    )
    result = json.loads(capsys.readouterr().out)
    assert (
        result["conditional_universal_diagnostic"]["drift_upper_bytes_squared"]
        == 12_500_000_000_000
    )
    assert result["qualified"] is False


def test_no_installer_training_or_execution_dependencies():
    # Guard the operator tooling's boundary from accidental control/runtime imports.
    directory = Path(__file__).parents[2] / "app" / "modules" / "autonomy"
    for name in (
        "artifact_io.py",
        "calibration.py",
        "qualification.py",
        "readiness_cli.py",
    ):
        source = (directory / name).read_text()
        for forbidden in (
            "import torch",
            "import subprocess",
            "from nanfo_routing",
            "import docker",
            "manual_approval=True",
        ):
            assert forbidden not in source


def test_measured_reward_matches_unclipped_contract():
    decision = MeasuredDecision(
        step=1,
        action=1,
        previous_action=0,
        foreground_sent_bytes=1200,
        foreground_received_bytes=0,
        foreground_sent_packets=1,
        foreground_received_packets=0,
        ping_sent=2,
        ping_received=0,
        latency_ms=None,
        max_path_utilization=20.0,
        max_path_queue_packets=2000.0,
        measured_window_seconds=2.0,
        inference_seconds=0.1,
        observation_seconds=2.1,
        control_readback_seconds=0.1,
        source={"path": "source", "sha256": HASH, "size_bytes": 1},
    )
    assert decision.reward() == pytest.approx(-9.05)


@pytest.fixture
def dossier_files(tmp_path, producer):
    def digest(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    training = write_artifact(tmp_path, "training.jsonl", b'{"fixture":true}\n')
    contract, spec, distribution = {"version": 3}, {"version": 3}, {"mode": "matched"}
    manifest = {
        "version": 3,
        "contract_hash": digest(contract),
        "contract": contract,
        "config": {},
        "provenance": "measured-lab",
        "training_seeds": [1000],
        "updates": 9,
        "transitions": 144,
        "episodes": 1,
        "versions": {},
        "weights_sha256": hashlib.sha256(b"not loaded as tensors").hexdigest(),
        "evidence_sha256": training["sha256"],
        "environment_spec": spec,
        "spec_hash": digest(spec),
        "training_distribution": distribution,
        "compatibility_hash": digest(
            {
                "contract_hash": digest(contract),
                "environment_spec": spec,
                "spec_hash": digest(spec),
                "training_distribution": distribution,
            }
        ),
        "lab_provenance": {"lab_image_id": "sha256:" + HASH},
        "client_source_files": {"contracts.py": HASH},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("weights.pt", b"not loaded as tensors")
    checkpoint = write_artifact(tmp_path, "checkpoint.ptz", buffer.getvalue())
    producer["checkpoint"] = {
        "checkpoint_sha256": checkpoint["sha256"],
        "manifest": manifest,
    }
    producer["training_evidence_sha256"] = training["sha256"]
    producer_ref = write_artifact(tmp_path, "producer.json", producer)
    plan = {
        "schema_version": "nanfo.matched-evaluation-plan.v1",
        "declared_at_unix_seconds": 1.0,
        "spec_sha256": digest(spec),
        "contract_sha256": digest(contract),
        "train_seeds": [1000],
        "validation_seeds": [2600, 2601],
        "test_seeds": [3800, 3801],
        "steps_per_episode": 2,
        "minimum_constant_margin": 0.02,
        "minimum_paired_lower_margin": 0.0,
    }
    plan_ref = write_artifact(tmp_path, "plan.json", plan)
    source = write_artifact(tmp_path, "measurement.json", {"fixture": True})
    refs = []
    for seed in [2600, 2601, 3800, 3801]:
        for policy in ["ppo", "constant0", "constant1", "heuristic", "ospf"]:
            action = seed % 2 if not policy.startswith("constant") else int(policy[-1])
            decision = {
                "step": 1,
                "action": action,
                "previous_action": action,
                "foreground_sent_bytes": 1200,
                "foreground_received_bytes": 1200,
                "foreground_sent_packets": 1,
                "foreground_received_packets": 1,
                "ping_sent": 2,
                "ping_received": 2,
                "latency_ms": 10.0,
                "max_path_utilization": 0.5,
                "max_path_queue_packets": 0.0,
                "measured_window_seconds": 2.0,
                "inference_seconds": 0.01 if policy == "ppo" else None,
                "observation_seconds": 2.0,
                "control_readback_seconds": 0.1,
                "source": source,
            }
            episode = {
                "schema_version": "nanfo.matched-episode.v1",
                "policy": policy,
                "seed": seed,
                "scenario": "path0" if seed % 2 == 0 else "path1",
                "spec_sha256": digest(spec),
                "contract_sha256": digest(contract),
                "schedule_sha256": HASH,
                "dataplane": "linux-frr",
                "checkpoint_sha256": checkpoint["sha256"] if policy == "ppo" else None,
                "started_at_unix_seconds": 10.0 if seed < 3000 else 40.0,
                "finished_at_unix_seconds": 20.0 if seed < 3000 else 50.0,
                "decisions": [decision, {**decision, "step": 2}],
            }
            refs.append(write_artifact(tmp_path, f"{seed}-{policy}.json", episode))
    dossier = {
        "schema_version": "nanfo.operator-qualification.v1",
        "checkpoint": checkpoint,
        "producer_qualification": producer_ref,
        "training_evidence": training,
        "plan": plan_ref,
        "spec_sha256": digest(spec),
        "contract_sha256": digest(contract),
        "observation_contract": "matched.v3",
        "runtime_action": "linux-frr-host-route",
        "selected_at_unix_seconds": 30.0,
        "training_rounds": 3,
        "trained_transitions": 144,
        "episodes": refs,
    }
    ref = write_artifact(tmp_path, "dossier.json", dossier)
    return dossier, ref


def test_complete_import_checks_bytes_and_does_not_promote(
    tmp_path, monkeypatch, dossier_files
):
    _, ref = dossier_files
    monkeypatch.setenv("NANFO_AUTONOMY_QUALIFICATION_SHA256", ref["sha256"])
    result = import_qualification(ArtifactStore(str(tmp_path)), "dossier.json")
    assert not result["qualified"] and not result["installed"]
    assert "normalized_measurement_derivation_unverified" in result["reasons"]
    assert "heldout_constant_advantage_not_established" in result["reasons"]
    assert "operator_qualification_pin_mismatch" not in result["reasons"]
    assert set(result["comparisons"]) == {"validation", "test"}
    assert set(result["comparisons"]["validation"]) == {
        "constant0",
        "constant1",
        "heuristic",
        "ospf",
    }
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    import_qualification(ArtifactStore(str(tmp_path)), "dossier.json")
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            lambda d: d.update(selected_at_unix_seconds=15.0),
            "selection_before_validation_completed",
        ),
        (
            lambda d: d.update(selected_at_unix_seconds=45.0),
            "test_used_before_selection",
        ),
        (
            lambda d: d.update(trained_transitions=145),
            "training_manifest_counters_or_seeds_mismatch",
        ),
        (
            lambda d: d["episodes"].append(d["episodes"][0]),
            "duplicate_evaluation_episode",
        ),
        (lambda d: d["checkpoint"].update(sha256=HASH), "artifact_hash_mismatch"),
    ],
)
def test_dossier_binding_and_leakage(tmp_path, dossier_files, change, reason):
    dossier, _ = dossier_files
    change(dossier)
    write_artifact(tmp_path, "dossier.json", dossier)
    with pytest.raises(EvidenceError, match=reason):
        import_qualification(ArtifactStore(str(tmp_path)), "dossier.json")


def test_dossier_operator_pin_mismatch_is_explicit(
    tmp_path, monkeypatch, dossier_files
):
    monkeypatch.setenv("NANFO_AUTONOMY_QUALIFICATION_SHA256", HASH)
    result = import_qualification(ArtifactStore(str(tmp_path)), "dossier.json")
    assert "operator_qualification_pin_mismatch" in result["reasons"]
    assert not result["qualified"]


def test_checkpoint_does_not_accept_compression_or_arbitrary_bytes():
    with pytest.raises(EvidenceError, match="checkpoint_archive_invalid"):
        inspect_checkpoint_bytes(b"not zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("weights.pt", "malicious pickle not loaded")
    with pytest.raises(EvidenceError, match="checkpoint_archive_invalid"):
        inspect_checkpoint_bytes(buffer.getvalue())


@pytest.mark.parametrize(
    ("command", "schema"),
    [
        (main, "producer"),
        (main, "qualification"),
        (main, "episode"),
        (main, "evaluation-plan"),
        (calibration_main, "input"),
        (calibration_main, "plan"),
        (calibration_main, "traces"),
    ],
)
def test_operator_schema_exports(command, schema, capsys):
    assert command(["--schema", schema]) == 0
    assert json.loads(capsys.readouterr().out)["additionalProperties"] is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("schedule_sha256", "b" * 64, "matched_schedule_mismatch"),
        ("spec_sha256", "b" * 64, "evaluation_contract_mismatch"),
        ("checkpoint_sha256", "b" * 64, "evaluation_checkpoint_mismatch"),
        ("seed", 2700, "evaluation_seed_not_reserved"),
        ("started_at_unix_seconds", 0.0, "evaluation_plan_not_predeclared"),
    ],
)
def test_independent_comparability_validation(
    tmp_path, dossier_files, field, value, reason
):
    dossier, _ = dossier_files
    episode = json.loads((tmp_path / "2600-ppo.json").read_bytes())
    episode[field] = value
    dossier["episodes"][0] = write_artifact(tmp_path, "2600-ppo.json", episode)
    write_artifact(tmp_path, "dossier.json", dossier)
    with pytest.raises(EvidenceError, match=reason):
        import_qualification(ArtifactStore(str(tmp_path)), "dossier.json")


def test_artifact_mutation_during_read_rejected(tmp_path, monkeypatch):
    write_artifact(tmp_path, "artifact", b"original")
    original_fstat = os.fstat
    calls = 0

    def modified(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            (tmp_path / "artifact").write_bytes(b"mutated after read")
        return original_fstat(fd)

    monkeypatch.setattr(os, "fstat", modified)
    with pytest.raises(EvidenceError, match="artifact_changed_during_read"):
        ArtifactStore(str(tmp_path)).read("artifact")


def test_calibration_drift_and_envelope_rejection(calibration_data):
    for row in calibration_data[1]["samples"]:
        row["service_counter_after_bytes"] = 0
        row["queue_after_bytes"] = 200.0
    calibration_data[0]["queue_threshold_bytes"] = 150.0
    result = run_calibration(calibration_data)
    assert "empirical_drift_budget_exceeded" in result["reasons"]
    assert "empirical_queue_envelope_exceeded" in result["reasons"]
    assert not result["qualified"]
