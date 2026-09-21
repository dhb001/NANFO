"""No Docker, databases, HTTP, training, or measured lab launches in this suite."""

import json
import sys
from pathlib import Path

import pytest

from scripts.acceptance import campaign, common, runtime, stage


@pytest.mark.parametrize("argv", [[], ["--live"], ["--live", "--agents-idle", "--overall-seconds", "0"],
                                  ["--plan", "--stage-seconds", "999999"], ["--plan", "--image", "latest"],
                                  ["--plan", "--historical-json", "missing.json"]])
def test_flag_guard_no_resources(argv, monkeypatch):
    monkeypatch.setattr(campaign, "run", lambda args: pytest.fail("must not execute"))
    with pytest.raises(SystemExit) as error:
        campaign.main(argv)
    assert error.value.code == 2


def test_exact_command_map(tmp_path):
    mapping = campaign.commands("/backend/python", tmp_path, "a" * 32, "sha256:" + "b" * 64, "sha256:" + "c" * 64)
    assert set(mapping) == set(campaign.STAGES)
    for name, command in mapping.items():
        assert command == ["/backend/python", "-m", "scripts.acceptance.stage", "--live", "--stage", name,
                           "--directory", str(tmp_path / name), "--owner", "a" * 32, "--image",
                           "sha256:" + ("c" if name == "operator_override" else "b") * 64]
    assert not any("train" in argument or "test-report" in argument for argv in mapping.values() for argument in argv)
    assert "tests/integration/test_alert_postgres.py" in stage.FIXTURE_TESTS
    assert "tests/integration/test_plugin_postgres.py" in stage.FIXTURE_TESTS


def container(identity="1", name=None, owner="owner", st="execution"):
    return {"Id": identity * 64, "Name": name or "nanfo-execution-lab-" + "a" * 32,
            "Image": "sha256:" + "a" * 64, "State": "running",
            "Labels": {common.OWNER_LABEL: owner, common.STAGE_LABEL: st}}


@pytest.mark.parametrize("mutation", ["baseline", "label", "stage", "prefix", "unknown_name", "id"])
def test_cleanup_needs_all_ownership_proofs(mutation):
    row = container()
    names, baseline = {row["Name"]}, {}
    if mutation == "baseline":
        baseline[row["Id"]] = row
    elif mutation == "label":
        row["Labels"][common.OWNER_LABEL] = "other"
    elif mutation == "stage":
        row["Labels"][common.STAGE_LABEL] = "other"
    elif mutation == "prefix":
        row["Name"] = "user-postgres"
        names.add(row["Name"])
    elif mutation == "unknown_name":
        names.clear()
    else:
        row["Id"] = "short"
    assert not common.owned(row, owner="owner", stage="execution", baseline=baseline, names=names)


def test_cleanup_only_exact_new_labeled_registered_id(tmp_path, monkeypatch):
    ours, other = container(), container("2", "user-postgres", "someone-else")
    common.write_new(tmp_path / "owned-000.json", {"owner": "owner", "stage": "execution", "name": ours["Name"]})
    snapshots = iter([{ours["Id"]: ours, other["Id"]: other}, {ours["Id"]: ours, other["Id"]: other}, {other["Id"]: other}])
    monkeypatch.setattr(runtime, "snapshot", lambda **kwargs: next(snapshots))
    calls = []
    monkeypatch.setattr(runtime, "docker", lambda *args, **kwargs: calls.append(args))
    result = runtime.cleanup(tmp_path, "owner", "execution", {other["Id"]: other})
    assert result["passed"]
    assert calls == [("rm", "-f", "-v", ours["Id"])]


def test_unknown_container_not_removed_blocks(tmp_path, monkeypatch):
    row = container(owner="unknown")
    monkeypatch.setattr(runtime, "snapshot", lambda **kwargs: {row["Id"]: row})
    monkeypatch.setattr(runtime, "docker", lambda *args: pytest.fail("must preserve unknown container"))
    result = runtime.cleanup(tmp_path, "owner", "execution", {})
    assert not result["passed"] and result["unknown_new_ids"] == [row["Id"]]


@pytest.mark.parametrize("rows,services,processes", [
    ({"x": container()}, "", ""), ({"x": {**container(), "State": "exited"}}, "", ""),
    ({}, "nanfo-refinement-long-001.service running", ""), ({}, "", "python -m emulation.runner"),
    ({}, "", "uvicorn app.main:app"), ({"x": {**container(name="innocent"), "Privileged": True}}, "", ""),
])
def test_baseline_rejects_existing_lab_training_and_backend(rows, services, processes):
    with pytest.raises(common.Blocked):
        runtime.baseline_safe(rows, services, processes)


def test_safe_unrelated_baseline():
    runtime.baseline_safe({"x": container(name="user-db")}, "postgresql.service running", "bash")


def test_durable_ledger_readonly_recovery_and_no_overwrite(tmp_path):
    ledger = common.Ledger(tmp_path)
    ledger.append("campaign_created", {"cases": [campaign.case("restart", "measured")]})
    ledger.append("stage_started", {"stage": "execution"})
    assert common.Ledger(tmp_path).sequence == 2
    recovered = campaign.status(tmp_path)
    assert recovered["overall"] == "partial"
    assert recovered["stages"]["execution"] == "interrupted_or_running"
    before = (tmp_path / "event-00000.json").read_bytes()
    with pytest.raises(FileExistsError):
        common.write_new(tmp_path / "event-00000.json", {})
    assert (tmp_path / "event-00000.json").read_bytes() == before
    # Tampering is detected by the next link, without rewriting the prior ledger.
    (tmp_path / "event-00000.json").write_text(json.dumps({"sequence": 0, "previous_sha256": None, "kind": "tampered"}))
    with pytest.raises(common.Blocked):
        common.Ledger(tmp_path)


def test_private_json_rejects_symlink(tmp_path):
    real = tmp_path / "real"
    real.write_text("unchanged")
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(OSError):
        common.write_new(link, {})
    with pytest.raises(OSError):
        common.read_json(link)
    assert real.read_text() == "unchanged"


def test_failure_artifact_sanitization_preserves_negative_assertion_keys():
    value = common.sanitize({"failure": "password=SECRET", "access_token": "SECRET", "url": "ws://host?token=SECRET",
                             "traceback": "SECRET", "checks": {"restore_partial_failure": {"status": "failed"}}})
    assert "SECRET" not in json.dumps(value)
    assert value["checks"]["restore_partial_failure"]["status"] == "failed"


def test_modeled_fixtures_conservation_reproducibility_no_fidelity():
    from scripts.acceptance.modeled import run_models

    first = run_models()
    assert first == run_models()
    assert set(first) == {"low", "ramp", "burst", "overload", "multibottleneck", "classes", "larger_topology"}
    assert len(first["larger_topology"]["input_fixture"]["links"]) == 32
    for item in first.values():
        assert item["mass_conservation_checked"]
        assert "no packet/network fidelity" in item["scope"]
        output = item["result"]
        assert output["offered_bytes"] == pytest.approx(sum(output[key] for key in
            ("delivered_bytes", "dropped_bytes", "queued_bytes", "inflight_bytes")))


@pytest.mark.parametrize("name,old", [("execution", "0012"), ("operator_override", "0016"), ("reports", "0017")])
def test_existing_verifier_migration_adapter_compiles_without_source_edits(name, old):
    path = campaign.BACKEND / "scripts" / f"verify_{name}.py"
    before = path.read_bytes()
    code, evidence = stage.adapted_source(path, {old: "0019"})
    assert code and evidence["replacement_counts"][old] >= 1
    assert path.read_bytes() == before


def test_skipblocked_and_no_combined_green():
    rows = [campaign.case("classes", "measured", "passed"), campaign.case("drl_safety", "measured")]
    assert campaign.summary(rows)["overall"] == "partial"
    assert not campaign.artifact_passed("fixtures", {"passed": True, "test_counts": {"tests": 10, "skipped": 10}})
    assert not campaign.artifact_passed("execution", {"passed": True})


def test_junit_counts_skip_detection_no_output_content(tmp_path):
    path = tmp_path / "results.xml"
    path.write_text('<testsuites><testsuite tests="3" failures="0" errors="0" skipped="1"><system-out>SECRET</system-out></testsuite></testsuites>')
    assert stage.test_counts(path) == {"tests": 3, "failures": 0, "errors": 0, "skipped": 1}


def test_failed_stage_continues_when_cleanup_safe(tmp_path, monkeypatch):
    ledger = common.Ledger(tmp_path)
    calls = []
    monkeypatch.setattr(campaign, "execute", lambda argv, **kwargs: calls.append(argv) or
                        {"returncode": 1, "timed_out": False, "bytes": {"stdout": 20, "stderr": 100},
                         "stdout": b"TOKEN", "stderr": b"Traceback TOKEN"})
    monkeypatch.setattr(campaign, "cleanup", lambda *args: {"passed": True})
    for name in ("execution", "operator_override"):
        directory = tmp_path / name
        directory.mkdir()
        result = campaign.run_stage(name, ["fake"], directory, "owner", {}, 1, ledger)
        assert result[:3] == ("failed", "stage_failed", True)
        assert "TOKEN" not in (directory / "process-log.json").read_text()
    assert len(calls) == 2


def test_timeout_cleanup_uncertain_blocks(tmp_path, monkeypatch):
    directory = tmp_path / "execution"
    directory.mkdir()
    monkeypatch.setattr(campaign, "execute", lambda *args, **kwargs: {"returncode": -9, "timed_out": True, "bytes": {}})
    monkeypatch.setattr(campaign, "cleanup", lambda *args: {"passed": False, "unknown_new_ids": ["unknown"]})
    result = campaign.run_stage("execution", ["fake"], directory, "owner", {}, 1, common.Ledger(tmp_path))
    assert result[:3] == ("blocked", "cleanup_uncertain_later_live_stages_blocked", False)


def test_bounded_process_group_timeout_kills_grandchild():
    result = runtime.execute([sys.executable, "-c", "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(p.pid,flush=True); time.sleep(60)"], timeout=0.3)
    assert result["timed_out"]
    pid = int(result["stdout"])
    state = Path(f"/proc/{pid}/stat")
    # A reparented zombie is dead and will be reaped by init; no running child remains.
    assert not state.exists() or state.read_text().split()[2] == "Z"


def test_bounded_logs():
    result = runtime.execute([sys.executable, "-c", "import sys; sys.stdout.write('x'*2000000)"], timeout=3)
    assert result["returncode"] == 0
    assert result["bytes"]["stdout"] == 2000000
    assert len(result["stdout"]) == 1024 * 1024


def test_plan_no_docker_services_or_live_children(tmp_path, monkeypatch):
    monkeypatch.setattr(campaign, "preflight", lambda *args, **kwargs: pytest.fail("no service calls"))
    monkeypatch.setattr(campaign, "execute", lambda *args, **kwargs: pytest.fail("no live children"))
    assert campaign.main(["--plan", "--output-parent", str(tmp_path)]) == 0
    evidence = next(tmp_path.glob("step14-*"))
    result, _ = common.read_json(evidence / "summary.json")
    assert result["overall"] == "partial" and result["live_authorized"] is False
    assert result["counts"]["passed"] == 7
    assert all(row["state"] == "blocked" for row in result["cases"] if row["evidence_kind"] == "measured")
    assert campaign.status(evidence)["overall"] == "partial"


def test_source_drift_blocks_before_service_inspection(monkeypatch):
    monkeypatch.setattr(campaign, "migration_head", lambda: "0019")
    monkeypatch.setattr(campaign, "sources", lambda: {"changed": "hash"})
    monkeypatch.setattr(campaign, "execute", lambda *args, **kwargs: pytest.fail("must stop before service calls"))
    with pytest.raises(common.Blocked, match="source_or_migrations_changed"):
        campaign.preflight({"old": "hash"})


def test_migration_single_head_0019_required(tmp_path, monkeypatch):
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    monkeypatch.setattr(campaign, "BACKEND", tmp_path)
    for revision, parent in (("0017", "0016"), ("0018", "0017"), ("0019", "0018")):
        (versions / f"{revision}.py").write_text(f'revision = "{revision}"\ndown_revision = "{parent}"\n')
    assert campaign.migration_head() == "0019"
    (versions / "branch.py").write_text('revision = "other"\ndown_revision = "0017"\n')
    with pytest.raises(common.Blocked, match="migration_head_not_single_0019"):
        campaign.migration_head()


def test_historical_reference_hash_only_no_replay(tmp_path, monkeypatch):
    history = tmp_path / "heldout.json"
    common.write_new(history, {"comparable_held_out_schedules": True, "autonomous_dispatch": "blocked"})
    original = history.read_bytes()
    monkeypatch.setattr(campaign, "execute", lambda *args, **kwargs: pytest.fail("historical evidence is never executed"))
    assert campaign.main(["--plan", "--output-parent", str(tmp_path), "--historical-json", str(history),
                          "--historical-sha256", common.sha(original)]) == 0
    result, _ = common.read_json(next(tmp_path.glob("step14-*/summary.json")))
    row = next(row for row in result["cases"] if row["case"] == "drl_alone")
    assert row["state"] == "passed" and row["evidence_kind"] == "historical"
    assert row["input_fixture_sha256"] == common.sha(original)
    assert history.read_bytes() == original
    assert result["overall"] == "partial"


def test_operator_interruption_cleans_and_stops_later_stages(tmp_path, monkeypatch):
    directory = tmp_path / "execution"
    directory.mkdir()
    def interrupt(*args, **kwargs):
        raise InterruptedError()
    monkeypatch.setattr(campaign, "execute", interrupt)
    calls = []
    monkeypatch.setattr(campaign, "cleanup", lambda *args: calls.append("cleaned") or {"passed": True})
    result = campaign.run_stage("execution", ["fake"], directory, "owner", {}, 1, common.Ledger(tmp_path))
    assert calls == ["cleaned"]
    assert result[:3] == ("blocked", "operator_signal_or_overall_deadline", False)


def test_missing_verifier_literal_blocks_adapter(tmp_path):
    path = tmp_path / "verifier.py"
    path.write_text('target = "future"')
    with pytest.raises(common.Blocked, match="verifier_adapter_contract_changed"):
        stage.adapted_source(path, {"0012": "0019"})


def test_explicit_stopped_preserve_exception_requires_exact_identity_and_state():
    row = {**container(), "Id": runtime.PRESERVABLE_ID, "Name": runtime.PRESERVABLE_NAME,
           "State": "exited", "Privileged": True, "InspectSHA256": "a" * 64}
    rows = {row["Id"]: row}
    runtime.baseline_safe(rows, "", "", [runtime.PRESERVABLE_ID])
    with pytest.raises(common.Blocked):
        runtime.baseline_safe(rows, "", "")
    for field, value in (("State", "running"), ("Name", "other"), ("InspectSHA256", None)):
        with pytest.raises(common.Blocked):
            runtime.baseline_safe({row["Id"]: {**row, field: value}}, "", "", [runtime.PRESERVABLE_ID])
    with pytest.raises(common.Blocked):
        runtime.baseline_safe(rows, "", "", ["b" * 64])


def test_preserved_inspect_drift_blocks_cleanup_without_deletion(tmp_path, monkeypatch):
    row = {**container(), "Id": runtime.PRESERVABLE_ID, "Name": runtime.PRESERVABLE_NAME,
           "State": "exited", "InspectSHA256": "a" * 64}
    monkeypatch.setattr(runtime, "snapshot", lambda **kwargs: {row["Id"]: {**row, "InspectSHA256": "b" * 64}})
    monkeypatch.setattr(runtime, "docker", lambda *args, **kwargs: pytest.fail("preserved container must never be changed"))
    result = runtime.cleanup(tmp_path, "owner", "execution", {row["Id"]: row})
    assert not result["passed"]
    assert result["baseline_changed_ids"] == [row["Id"]]


async def test_legacy_emulation_dispatch_runs_every_merged_handler():
    import inspect
    verifier = stage.emulation_verifier()
    assert 'await process_entry(redis, stream, group, entry_id, fields, handlers)' in inspect.getsource(verifier.verify)


def test_full_inspect_hash_is_mount_order_independent(monkeypatch):
    row = {**container(), "Id": runtime.PRESERVABLE_ID, "Name": runtime.PRESERVABLE_NAME,
           "State": "exited", "Privileged": True}
    mounts = [{"Destination": "/output", "Source": "/owned/output"}, {"Destination": "/results", "Source": "/owned/results"}]
    def docker(*argv, **kwargs):
        if argv[0] == "ps":
            return runtime.PRESERVABLE_ID
        if "--format" in argv:
            return json.dumps(row)
        mounts.reverse()
        return json.dumps([{**row, "Mounts": mounts}])
    monkeypatch.setattr(runtime, "docker", docker)
    assert runtime.snapshot() == runtime.snapshot()
