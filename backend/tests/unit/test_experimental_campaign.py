"""Offline campaign protocol tests; these never launch containers or claim lab evidence."""

import json
import os
import time
import zipfile

import pytest

from scripts import audit_experimental_lab as auditor
from scripts import verify_experimental_lab as runner


def test_typed_seed_fields_exclude_counts_hashes_domains_not_reservations():
    assert runner.seed_values({"reserved_seed_count": 1342}) == set()
    assert runner.seed_values({"seed_count": 1342, "paired_seeds": 1342,
        "seed_audit_sha256": "a" * 64,
        "seed_namespaces": {"train": [1000, 1999], "validation": [2000, 2999], "test": [3000, 3999]}}) == set()
    assert runner.seed_values({"request": {"seed": 1342}, "reserved_seed_count": 1342,
        "training_seeds": [1100], "plan": {"reserved_seeds": [1200]}}) == {1100, 1200, 1342}
    for value in ({"mystery_seed": 1342}, {"seeds": [True]}, {"seed": "1342"},
                  {"reserved_seed_count": [1342]}):
        with pytest.raises(ValueError):
            runner.seed_values(value)


def test_inventory_transitive_correction_requires_exact_provenance_and_keeps_plans(tmp_path):
    origin = tmp_path / "review.json"
    pin = runner.write(origin, {"reserved_seed_count": 1342, "seeds": [3003]})
    one = dict(version=1, documents=[dict(path="/old/review.json", sha256=pin, seeds=[1342, 3003])],
               reserved_seeds=[1342, 3003])
    first = tmp_path / "audit1.json"
    first_hash = runner.write(first, one)
    runner.write(tmp_path / "audit2.json", dict(version=1,
        documents=[dict(path="/old/audit1.json", sha256=first_hash, seeds=[1342, 3003])], reserved_seeds=[1342, 3003]))
    result = runner.audit_seeds([tmp_path])
    assert result["reserved_seeds"] == [3003]
    assert len(result["provenance_corrections"]) == 2
    # Missing original plan still constitutes a reservation, even for the same value.
    runner.write(tmp_path / "audit3.json", dict(version=1,
        documents=[dict(path="/missing/plan.json", sha256="f"*64, seeds=[1342])], reserved_seeds=[1342]))
    assert runner.audit_seeds([tmp_path])["reserved_seeds"] == [1342, 3003]


def test_unexplained_inventory_assertions_cannot_be_erased(tmp_path):
    pin = runner.write(tmp_path / "review.json", {"reserved_seed_count": 1342})
    runner.write(tmp_path / "inventory.json", dict(version=1,
        documents=[dict(path="review.json", sha256=pin, seeds=[1342, 1450])],
        reserved_seeds=[1342, 1450, 1460]))
    assert runner.audit_seeds([tmp_path])["reserved_seeds"] == [1342, 1450, 1460]


def test_unknown_or_changed_missing_inventory_not_covered_by_reviewed_correction(tmp_path):
    runner.write(tmp_path / "inventory.json", dict(version=1,
        documents=[dict(path="/tmp/opencode/nanfo-experimental-campaign-001/seed-audit.json",
                        sha256="a"*64, seeds=[1342, 1100])], reserved_seeds=[1342, 1100]))
    assert runner.audit_seeds([tmp_path])["reserved_seeds"] == [1100, 1342]


def test_reviewed_missing_inventory_correction_needs_origin_and_never_erases_plan(tmp_path, monkeypatch):
    origin = tmp_path / "origin.json"
    pin = runner.write(origin, {"reserved_seed_count": 1342, "seeds": [3003]})
    monkeypatch.setattr(runner, "COUNT_ONLY_ORIGIN", pin)
    runner.write(tmp_path / "inventory.json", dict(version=1,
        documents=[dict(path="/tmp/opencode/nanfo-experimental-campaign-001/seed-audit.json",
                        sha256=runner.REVIEWED_COUNT_INVENTORIES[1], seeds=[1342, 1100])],
        reserved_seeds=[1342, 1100]))
    assert runner.audit_seeds([tmp_path])["reserved_seeds"] == [1100, 3003]
    origin.unlink()
    assert runner.audit_seeds([tmp_path])["reserved_seeds"] == [1100, 1342]
    runner.write(origin, {"reserved_seed_count": 1342, "seeds": [3003]})
    runner.write(tmp_path / "true-plan.json", {"reserved_seeds": [1342]})
    assert runner.audit_seeds([tmp_path])["reserved_seeds"] == [1100, 1342, 3003]


def test_all_retained_historical_plan_assertions_remain_reserved():
    if not (runner.ROOT / "nanfo-experimental-campaign-014/seed-audit.json").exists():
        pytest.skip("historical inventory absent from executable snapshot")
    inventory = runner.read(runner.ROOT / "nanfo-experimental-campaign-014/seed-audit.json")
    plans = [row for row in inventory["documents"] if "/nanfo-experimental-campaign-" in row["path"]
             and row["path"].endswith("/plan.json")]
    assert plans
    for row in plans:
        assert runner.seed_values(row) == set(row["seeds"])
    for name in ("015", "016", "017"):
        plan = runner.read(runner.ROOT / f"ai-engine/artifacts/nanfo-experimental-campaign-{name}/plan.json")
        selected = {row["seed"] for row in plan["trials"] + plan["faults"] + plan["smoke"]}
        assert selected <= runner.seed_values(plan)


def test_seed_inventory_includes_failures_jsonl_and_checkpoint_manifest(tmp_path):
    runner.write(tmp_path / "failed.json", {"status": "failed", "reserved_seeds": [1100]})
    (tmp_path / "rows.jsonl").write_text(json.dumps({"request": {"seed": 1101}}) + "\n")
    with zipfile.ZipFile(tmp_path / "original.ptz", "w") as archive:
        archive.writestr("manifest.json", json.dumps({"training_seeds": [1102]}))
    audit = runner.audit_seeds([tmp_path])
    assert audit["reserved_seeds"] == [1100, 1101, 1102]
    assert len(audit["documents"]) == 3
    assert runner.audit_seeds([tmp_path, tmp_path]) == {
        **audit, "roots": [str(tmp_path), str(tmp_path)]}


def test_unreadable_seed_evidence_is_not_silently_omitted(tmp_path):
    (tmp_path / "broken.json").write_text("{truncated")
    with pytest.raises(ValueError):
        runner.audit_seeds([tmp_path])


def test_seed_scan_does_not_follow_symlinks(tmp_path):
    runner.write(tmp_path / "original.json", {"seed": 1100})
    (tmp_path / "alias.json").symlink_to(tmp_path / "original.json")
    with pytest.raises(ValueError, match="seed_audit_symlink"):
        runner.audit_seeds([tmp_path])


def test_common_lock_excludes_second_campaign_without_unlink(tmp_path, monkeypatch):
    lock = tmp_path / "slot.lock"
    monkeypatch.setattr(runner, "LOCK", lock)
    with runner.campaign_slot():
        inode = lock.stat().st_ino
        with pytest.raises(BlockingIOError), runner.campaign_slot():
            pytest.fail("second campaign entered")
    assert lock.stat().st_ino == inode
    with runner.campaign_slot():
        assert lock.stat().st_ino == inode


@pytest.mark.parametrize("change", [
    {"core_adapter_ready": False}, {"authorize_privileged_launch": False},
    {"plan_sha256": "0" * 64}, {"expires_ns": 1},
])
def test_parent_admission_is_exact_plan_and_readiness_bound(tmp_path, change):
    runner.write(tmp_path / "plan.json", {"training": False})
    value = dict(version="nanfo.experimental-parent-admission/v1", core_adapter_ready=True,
                 authorize_privileged_launch=True, plan_sha256=runner.digest(tmp_path / "plan.json"),
                 expires_ns=time.time_ns() + 10**9)
    runner.write(tmp_path / "admission.json", value | change)
    with pytest.raises(ValueError, match="not_admitted"):
        runner.admission(tmp_path, tmp_path / "admission.json")


def test_admission_rejects_world_readable_and_symlink(tmp_path):
    path = tmp_path / "admission.json"
    runner.write(path, {})
    os.chmod(path, 0o644)
    with pytest.raises(ValueError, match="private_owned"):
        runner.admission(tmp_path, path)
    os.chmod(path, 0o600)
    (tmp_path / "alias.json").symlink_to(path)
    with pytest.raises(ValueError, match="private_owned"):
        runner.admission(tmp_path, tmp_path / "alias.json")


def test_fault_matrix_labels_real_vs_injected_and_exact_write_boundary():
    cases = runner.fault_matrix()
    assert len(cases) == len({row["case_id"] for row in cases}) == 20
    assert {row["intervention"] for row in cases} == {"real", "injected_failpoint"}
    assert all(row["write_index"] == (row["phase"] == "afterwrite") for row in cases)
    for scenario in runner.SCENARIOS:
        assert {row["fault"] for row in cases if row["scenario"] == scenario} == {
            "delayed-data", "STOP-before", "STOP-after", "revoke-before", "revoke-after",
            "link-failure", "disconnect", "restart", "partial-apply", "ambiguous-receipt"}


def test_raw_metrics_reconstruct_bytes_seconds_counts_and_missingness():
    raw = dict(window_started_ns=10**9, window_ended_ns=3 * 10**9,
               received_bytes=1500000, probe_sent=4, probe_received=3, probe_rtt_ms=[1, 2, 6])
    result = auditor.metrics(raw)
    assert result["goodput_mbps"] == 6
    assert result["loss_fraction"] == .25
    assert result["rtt_ms"] == 3
    missing = auditor.metrics({**raw, "received_bytes": None, "probe_rtt_ms": None})
    assert missing["goodput_mbps"] is None and missing["rtt_ms"] is None
    with pytest.raises(ValueError, match="probe_count_invalid"):
        auditor.metrics({**raw, "probe_received": 5})
    with pytest.raises(ValueError, match="probe_rtt_count_invalid"):
        auditor.metrics({**raw, "probe_rtt_ms": [float("nan"), 1, 2]})


def matched():
    return [dict(scenario=scenario, seed=seed, policy=policy,
                 metrics=dict(goodput_mbps=2 if policy == "qualified" else 1,
                              loss_fraction=.1, rtt_ms=10))
            for scenario, seed in (("path0", 1100), ("path1", 1101))
            for policy in runner.POLICIES]


def test_paired_metrics_exact_denominator_no_selective_missing_window_drop():
    cases = matched()
    report = auditor.paired_metrics(cases)
    assert report[0]["mean_delta"] == 1
    assert report[0]["expected_pairs"] == 2
    cases[0]["metrics"]["goodput_mbps"] = None
    report = auditor.paired_metrics(cases)
    assert report[0]["available_pairs"] == 1 and report[0]["mean_delta"] is None
    assert all(not row["superiority_claim"] for row in report)


def test_unmatched_baseline_and_duplicate_pair_rejected():
    with pytest.raises(ValueError, match="unmatched_baseline"):
        auditor.paired_metrics(matched()[:-1])
    with pytest.raises(ValueError, match="duplicate_matched"):
        auditor.paired_metrics(matched() + matched()[:1])


def test_artifact_tamper_and_traversal_fail(tmp_path):
    pin = runner.write(tmp_path / "raw.json", {"received_bytes": 1})
    ref = {"path": "raw.json", "sha256": pin}
    assert auditor.artifact(tmp_path, ref) == tmp_path / "raw.json"
    with pytest.raises(ValueError, match="artifact_escape"):
        auditor.artifact(tmp_path, {**ref, "path": "../raw.json"})
    (tmp_path / "raw.json").write_text("{}")
    with pytest.raises(ValueError, match="artifact_hash_mismatch"):
        auditor.artifact(tmp_path, ref)


def test_blocked_campaign_never_passes_offline_audit(tmp_path):
    pin = runner.write(tmp_path / "seed-audit.json", {"reserved_seeds": [], "documents": []})
    plan_pin = runner.write(tmp_path / "plan.json", dict(version=runner.VERSION, training=False,
        calibrated=False, seed_audit_sha256=pin, paired_seeds_per_direction=2,
        trials=[dict(case_id=f"{s}-{n}-{p}", scenario=s, seed=n, policy=p)
                for s, n in (("path0", 1100), ("path1", 1101), ("path0", 1102), ("path1", 1103))
                for p in runner.POLICIES],
        faults=[row | {"seed": 1200 + i} for i, row in enumerate(runner.fault_matrix())]))
    runner.write(tmp_path / "campaign-evidence.json", dict(plan_sha256=plan_pin, status="blocked"))
    with pytest.raises(ValueError, match="blocked_or_incomplete"):
        auditor.audit(tmp_path)


async def test_incomplete_contract_blocks_before_private_services_or_lab(tmp_path, monkeypatch):
    pin = runner.write(tmp_path / "offline-gates.json", {})
    monkeypatch.setattr(runner, "verify_runtime_snapshot", lambda *_: {})
    original_digest=runner.digest
    monkeypatch.setattr(runner,"digest",lambda path: "a"*64 if path.name=="frozen-runtime.json" else original_digest(path))
    monkeypatch.setattr(runner, "validate_plan", lambda *_: {"offline_gates_sha256": pin,"runtime_snapshot_sha256":"a"*64})
    monkeypatch.setattr(runner, "contract_readiness", lambda: {"core": True, "faults": False})
    monkeypatch.setattr(runner.OwnedReceiver, "allocate", lambda *_: pytest.fail("privileged allocation"))
    result = await runner.launch(tmp_path)
    assert result["status"] == "blocked" and result["privileged_launch"] is False
    assert runner.read(tmp_path / "launch-blocked.json") == result


def test_native_trace_rejects_ambiguous_write_and_accepts_exact_completed_prefix():
    row = dict(node="access1", argv=["ip", "rule", "add", "priority", "100"],
               began=1.0, completed=None, restoring=False)
    with pytest.raises(ValueError, match="native_mutation_ambiguous"):
        auditor.native_trace([row])
    assert auditor.native_trace([{**row, "completed": 1.1}]) == [{**row, "completed": 1.1}]


def test_empty_preregistration_cannot_become_success(tmp_path):
    pin = runner.write(tmp_path / "seed-audit.json", {"reserved_seeds": [], "documents": []})
    runner.write(tmp_path / "plan.json", dict(version=runner.VERSION, training=False, calibrated=False,
        seed_audit_sha256=pin, paired_seeds_per_direction=2, trials=[], faults=[]))
    with pytest.raises(ValueError, match="incomplete_preregistered_matrix"):
        auditor.audit(tmp_path)


def test_simulation_assumptions_are_typed_and_independent_of_new_results():
    from app.modules.autonomy.experimental.simulation import SimulationAssumptions
    policy = runner.simulation_policy()
    parsed = SimulationAssumptions.model_validate({**policy["assumptions"],
        "limits": policy["objectives"], "max_observation_age_seconds": 30})
    assert len(parsed.foreground_paths) == 2
    assert all(link.initial_queue_bytes == 0 and link.source_label == "operator_configured_model"
               for link in parsed.links)


def test_preparation_reserves_failed_seeds_and_exact_matched_matrix(tmp_path, monkeypatch):
    history = tmp_path / "history"
    history.mkdir()
    runner.write(history / "failed.json", {"seeds": [1000, 1001, 1002]})
    monkeypatch.setattr(runner, "model_identity", lambda _: {"checkpoint_sha256": runner.CHECKPOINT})
    output = tmp_path / "campaign"
    plan = runner.prepare(output, roots=[history], pairs=2)
    assert len(plan["trials"]) == 16 and len(plan["faults"]) == 20
    assert min(row["seed"] for row in plan["trials"]) == 1003
    assert not {r["seed"] for r in plan["trials"]} & {r["seed"] for r in plan["faults"]}
    for seed in {r["seed"] for r in plan["trials"]}:
        rows = [r for r in plan["trials"] if r["seed"] == seed]
        assert {r["policy"] for r in rows} == set(runner.POLICIES)
        assert len({r["scenario"] for r in rows}) == 1
    with pytest.raises(FileExistsError):
        runner.prepare(output, roots=[history], pairs=2)


async def test_real_port_capture_preserves_returned_receipt_bytes(tmp_path):
    from types import SimpleNamespace
    from app.modules.autonomy.experimental.schemas import ExecutionReceipt
    from uuid import uuid4

    record = ExecutionReceipt(request_id=uuid4(), action_sha256="a" * 64,
                              action_id="route1", status="uncertain", evidence={"raw": [1, 2, 3]})
    async def actual_method():
        return record
    capture = runner.CapturedPorts(SimpleNamespace(), tmp_path, "b" * 64, tmp_path)
    assert await capture.call("receipt", actual_method) is record
    ref = capture.records["receipt"]
    assert runner.read(tmp_path / ref["path"]) == record.model_dump(mode="json")
    assert runner.digest(tmp_path / ref["path"]) == ref["sha256"]
    assert capture.timings[0]["finished_ns"] >= capture.timings[0]["started_ns"]


def test_real_preserved_frame_matches_campaign_capacity_interfaces_and_metric_semantics():
    """Historical replay for compatibility, never a fresh campaign performance claim."""
    from app.modules.autonomy.experimental.simulation import FrozenMeasuredFrame, evaluate_actions
    from app.modules.autonomy.experimental.verification import measured_metrics
    from datetime import datetime
    from uuid import uuid4
    snapshot = runner.read(runner.MODEL.parent / "live/path0/snapshot-0.json")
    raw = snapshot["history"]["frames"][0]["response"]["data"]
    frame = FrozenMeasuredFrame(network_id=snapshot["network_id"], workspace_id=snapshot["workspace_id"],
        runtime_sha256="a" * 64, window_started_at=snapshot["window_started_at"],
        observed_at=snapshot["observed_at"], raw_sha256=auditor.canonical(raw), raw=raw)
    policy = runner.simulation_policy()
    results = evaluate_actions(frame=frame, assumptions={**policy["assumptions"],
        "limits": policy["objectives"], "max_observation_age_seconds": 30},
        actions=[dict(intent_id=uuid4(), action_id=f"route{i}", action_index=i, plan_sha256="b" * 64)
                 for i in (0, 1)], policy_sha256="c" * 64, now=datetime.fromisoformat(snapshot["published_at"]))
    assert len(results) == 2
    values = measured_metrics(frame)
    assert values["goodput_mbps"] == pytest.approx(raw["observation"]["goodput_mbps"])
    assert values["udp_loss_pct"] / 100 == pytest.approx(raw["observation"]["loss_fraction"])


@pytest.mark.parametrize("fault", ["STOP-before", "STOP-after", "revoke-before", "revoke-after",
                                  "partial-apply", "ambiguous-receipt"])
async def test_actual_dispatcher_selects_declared_fault_hook_without_measurement_edits(tmp_path, monkeypatch, fault):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.modules.autonomy.experimental.authority import CurrentAuthority
    from app.modules.autonomy.experimental.controller import ExperimentalController
    case = next(c for c in runner.fault_matrix() if c["fault"] == fault)
    runner.write(tmp_path / "execute-ready.json", {})
    runner.write(tmp_path / "receiver-policy.json", {})
    class Receiver:
        receiver_policy = {"heartbeat_seconds": 2}
        published = {}
        def publish(self, name, value):
            self.published[name] = value
        def receiver_file(self, name):
            return {"id": "a" * 64, "entry": {}, "point": self.published["failpoint.json"]}
        request = AsyncMock(return_value={"stop_latched": True})
    receiver = Receiver()
    db = AsyncMock()
    db.__aenter__.return_value = db
    def sessions():
        return db
    monkeypatch.setattr(CurrentAuthority, "check", AsyncMock(side_effect=ValueError("revoked")))
    monkeypatch.setattr(ExperimentalController, "__init__", lambda self, *args: None)
    monkeypatch.setattr(ExperimentalController, "stop", AsyncMock(return_value={"stopped": True}))
    policy = SimpleNamespace(actor_id="00000000-0000-0000-0000-000000000001")
    await runner.intervene(case, tmp_path, receiver, SimpleNamespace(returncode=None), sessions, None, policy, {})
    point = receiver.published["failpoint.json"]
    assert point["when"] == ("before" if case["phase"] == "beforewrite" else "after")
    assert point["effect"] == ("raise" if fault == "partial-apply" else "pause")
    assert runner.read(tmp_path / "intervention.json")["fault"] == fault
    assert not list(tmp_path.glob("*frame*.json"))


@pytest.mark.parametrize("mode", ["complete", "budget", "failure", "unresolved"])
async def test_complete_matrix_dispatch_never_omits_failures_or_budget_suffix(tmp_path, monkeypatch, mode):
    from unittest.mock import AsyncMock
    cases = [dict(case_id=f"nominal-{i}", policy=p, seed=1100+i//4, scenario="path0")
             for i, p in enumerate(list(runner.POLICIES) * 12)]
    faults = [row | {"seed": 1200+i, "policy": "qualified"} for i, row in enumerate(runner.fault_matrix())]
    plan = dict(trials=cases, faults=faults, case_budget_seconds=150, cleanup_reserve_seconds=180,
                source_sha256={})
    monkeypatch.setattr(runner, "source_pins", lambda: {})
    attempted = []
    async def case(directory, plan, declared, *args):
        attempted.append(declared["case_id"])
        directory.mkdir()
        runner.write(directory / "cleanup.json", {"removed": mode != "unresolved"})
        if mode == "failure" and len(attempted) == 2:
            raise ValueError("case_failed")
        return dict(status="completed")
    monkeypatch.setattr(runner, "provision_actor", AsyncMock(return_value={}))
    monkeypatch.setattr(runner, "joined_case", case)
    monkeypatch.setattr(runner, "assemble_case", lambda root, declared, result: declared | result)
    rows, errors = await runner.dispatch_matrix(tmp_path, plan, None, None,
        0 if mode == "budget" else time.monotonic()+3600)
    assert len(rows) == 68
    assert [r["case_id"] for r in rows] == [r["case_id"] for r in cases+faults]
    assert len(list(tmp_path.glob("case-result-*.json"))) == 68
    if mode == "budget":
        assert not attempted and all(r["status"] == "not_run" for r in rows)
    elif mode == "unresolved":
        assert len(attempted) == 1 and all(r["status"] == "not_run" for r in rows[1:])
    elif mode == "failure":
        assert len(attempted) == 68 and rows[1]["status"] == "failed" and len(errors) == 1
    else:
        assert len(attempted) == 68 and not errors and all(r["status"] == "completed" for r in rows)


def test_native_seed_exclusion_requires_exact_preserved_runner_and_protocol(tmp_path):
    native = tmp_path / "native-driver-failed"
    native.mkdir()
    source = native / "source/backend/scripts/verify_native_driver.py"
    source.parent.mkdir(parents=True)
    source.write_text("# synthetic manual-only original\n")
    protocol = dict(version="nanfo.native-driver-acceptance/v1", fixture="static-FIB-no-OSPF",
        authority_kind="scoped-manual-driver-campaign",
        source_sha256={"backend/scripts/verify_native_driver.py": runner.digest(source)})
    runner.write(native / "protocol.json", protocol)
    # A deliberately unreadable-to-JSON raw setup result need not be parsed: exact
    # non-model protocol/source are the exclusion evidence, not the failure flag.
    (native / "result.json").write_text("not a model seed document")
    value = runner.audit_seeds([native])
    assert value["reserved_seeds"] == [] and len(value["exclusions"]) == 1
    assert value["documents"][0]["path"].endswith("protocol.json")
    source.write_text("# changed campaign\n")
    with pytest.raises(ValueError, match="exclusion_not_proven"):
        runner.audit_seeds([native])


def test_native_restoration_cannot_be_satisfied_by_success_booleans():
    baseline = {"tables": {"a:1": {"routes": [], "rules": []}}, "paths": {"h1->h3": {"nodes": ["a", "b"]}}}
    native = dict(runtime={"owned": []}, restoration=dict(baseline=baseline,
        baseline_sha256=auditor.canonical(baseline), owned_empty=True, readback=baseline))
    auditor.native_restoration(native, baseline)
    native["restoration"]["readback"] = {**baseline, "tables": {"a:1": {"routes": ["foreign"], "rules": []}}}
    with pytest.raises(ValueError, match="not_restored"):
        auditor.native_restoration(native, baseline)


@pytest.mark.parametrize("kind", ["model", "fixed0", "fixed1", "heuristic"])
async def test_auditor_replays_full_owner_chain_with_real_configured_simulator(tmp_path, kind):
    """Synthetic identity/decision fixtures over historical raw bytes, never live pass."""
    from datetime import timedelta
    from uuid import uuid4
    from app.modules.autonomy.experimental.schemas import (
        ExperimentalPolicy, MeasuredFrame, InferenceRecord, PreparedAction, ActionCommand,
        ExecutionReceipt, RecoveryReceipt, VerificationRecord, contract_digest,
    )
    from app.modules.autonomy.experimental.comparators import ComparatorAdapter
    from app.modules.autonomy.experimental.simulation import ConfiguredSimulator, evaluator_sha256
    from app.modules.autonomy.live_schemas import PassiveSnapshot, RuntimeResult
    from app.modules.autonomy.schemas import Observation, Proposal, Qualification
    from tests.experimental_lab_support import case
    fixture = case()
    snapshot = PassiveSnapshot.model_validate(runner.read(runner.MODEL.parent / "live/path0/snapshot-0.json"))
    now = snapshot.published_at
    configured = runner.simulation_policy()
    policy = ExperimentalPolicy.model_validate({**fixture.policy.model_dump(mode="json"),
        "run_id": str(snapshot.run_id), "policy_kind": kind,
        "network_id": str(snapshot.network_id), "workspace_id": str(snapshot.workspace_id),
        "starts_at": (now-timedelta(seconds=30)).isoformat(), "expires_at": (now+timedelta(seconds=60)).isoformat(),
        "wrapper_equivalence_sha256": "e"*64 if kind == "model" else None,
        "model_adapter_sha256": "f"*64 if kind == "model" else None,
        "evaluator_sha256": evaluator_sha256(), "assumptions": configured["assumptions"],
        "objectives": configured["objectives"], "max_action_duration_seconds": 20,
        "routes": [dict(action_id=f"route{i}", device_ids=["access1",f"dist{i+1}","access2"],
                        path=["access1",f"dist{i+1}","access2"]) for i in (0,1)]})
    frame = MeasuredFrame(snapshot=snapshot, runtime=policy.runtime,
        features=snapshot.history["frames"][0]["response"]["data"]["observation"],
        observation=Observation(network_id=policy.network_id, workspace_id=policy.workspace_id,
            provider_id="offline", contract=snapshot.version, observed_at=snapshot.observed_at,
            collected_at=now, age_seconds=1, fresh=True, compatible=True, evidence=["offline-historical"]),
        provenance={"offline": True})
    if kind == "model":
        result = RuntimeResult.model_validate({**fixture.inference.result.model_dump(mode="json"),
            "snapshot_sha256": contract_digest(snapshot), "history_sha256": snapshot.history_sha256,
            "contract_sha256": snapshot.contract_sha256, "spec_sha256": snapshot.spec_sha256,
            "input_sha256": contract_digest(frame.features), "action":1,
            "action_path": list(policy.routes[1].path), "probabilities":[.1,.9]})
        inference = InferenceRecord(frame_sha256=contract_digest(frame), result=result,
            proposal=Proposal(action_id="route1", checkpoint_sha256=policy.checkpoint_sha256,
                              observation_contract=snapshot.version, evidence=["offline-fixture"]),
            qualification=Qualification(qualified=True, checkpoint_sha256=policy.checkpoint_sha256,
                manifest_sha256=policy.registry_sha256, observation_contract=snapshot.version),
            wrapper_equivalence_sha256=policy.wrapper_equivalence_sha256,
            model_adapter_sha256=policy.model_adapter_sha256)
    else:
        inference = await ComparatorAdapter(policy).infer(frame)
    sim = await ConfiguredSimulator(clock=lambda: now).simulate(frame, inference, policy)
    command = ActionCommand(request_id=uuid4(), run_id=policy.run_id, resource_id=policy.runtime.resource_id,
        fence=1, network_id=policy.network_id, workspace_id=policy.workspace_id, runtime=policy.runtime,
        route=policy.routes[inference.result.action], policy_sha256=contract_digest(policy),
        frame_sha256=contract_digest(frame), inference_sha256=contract_digest(inference),
        simulation_sha256=contract_digest(sim), created_at=now, expires_at=now+timedelta(seconds=20))
    prepared = PreparedAction(command=command, baseline={"offline": True},
        baseline_sha256=contract_digest({"offline": True}), ownership_sha256="a"*64)
    receipt = ExecutionReceipt(request_id=command.request_id, action_sha256=contract_digest(prepared),
        action_id=command.route.action_id, status="applied", evidence={"offline": True})
    verification = VerificationRecord(request_id=command.request_id, action_sha256=contract_digest(prepared),
        run_id=policy.run_id, action_id=command.route.action_id, route_verified=True,
        observed_at=now+timedelta(seconds=3), window_started_at=now+timedelta(seconds=1),
        goodput_mbps=1, loss_fraction=0, rtt_ms=1, probe_sent=3, probe_received=3,
        traffic_bytes=1, provenance={"offline": True})
    recovery = RecoveryReceipt(request_id=command.request_id, action_sha256=contract_digest(prepared),
        baseline_sha256=prepared.baseline_sha256, status="restored", evidence={"offline": True})
    records = dict(frame=frame, inference=inference, simulation=sim, prepared=prepared,
                   receipt=receipt, verification=verification, recovery=recovery)
    refs = {}
    for name, value in records.items():
        path = tmp_path / (name+".json")
        refs[name] = {"path": path.name, "sha256": runner.write(path, value.model_dump(mode="json"))}
    audited = auditor.audit_chain(tmp_path, refs, policy, positive=True)
    assert audited["inference"].policy_kind == kind
    assert audited["simulation"].admitted
    bad = runner.read(tmp_path / "simulation.json")
    bad["result"]["selected"]["result"]["throughput_mbps"] = 999
    (tmp_path / "simulation.json").write_text(json.dumps(bad))
    refs["simulation"]["sha256"] = runner.digest(tmp_path / "simulation.json")
    with pytest.raises(ValueError):
        auditor.audit_chain(tmp_path, refs, policy, positive=True)


@pytest.mark.parametrize("fault", ["disconnect", "restart", "link-failure"])
async def test_dispatcher_process_and_link_faults_use_real_operation_ports(tmp_path, monkeypatch, fault):
    from types import SimpleNamespace
    case = next(c for c in runner.fault_matrix() if c["fault"] == fault)
    runner.write(tmp_path / "execute-ready.json", {})
    runner.write(tmp_path / "receiver-policy.json", {})
    effects = []
    class Receiver:
        receiver_policy = {"heartbeat_seconds": 2}
        def publish(self, name, value):
            effects.append((name, value))
        def receiver_file(self, name):
            return {"id": "a"*64, "entry": {}, "point": {}}
        def link_state(self, case, state):
            effects.append(("link", state))
            return {"returncode":0}
    class Child:
        pid = 1234
        returncode = None
        def kill(self):
            effects.append(("kill", self.pid))
            self.returncode = -9
        async def wait(self):
            effects.append(("wait", self.pid))
    async def sleep(seconds):
        effects.append(("sleep", seconds))
    monkeypatch.setattr(runner.asyncio, "sleep", sleep)
    monkeypatch.setattr(runner.os, "kill", lambda pid, sig: effects.append(("signal", pid, sig)))
    await runner.intervene(case, tmp_path, Receiver(), Child(), None, None, SimpleNamespace(), {})
    event = runner.read(tmp_path / "intervention.json")
    if fault == "link-failure":
        assert [item for item in effects if item[0] == "link"] == [("link","down"),("link","up")]
    else:
        assert event["returncode"] == -9 and ("kill",1234) in effects and ("wait",1234) in effects
        assert any(effect[0] == "signal" for effect in effects) == (fault == "disconnect")


async def test_delayed_data_intervention_preserves_actual_acquisition_time(tmp_path, monkeypatch):
    case = next(c for c in runner.fault_matrix() if c["fault"] == "delayed-data")
    runner.write(tmp_path / "observation-ready.json", {"monotonic_ns": 123})
    delays = []
    async def sleep(seconds):
        delays.append(seconds)
    monkeypatch.setattr(runner.asyncio, "sleep", sleep)
    await runner.intervene(case, tmp_path, None, None, None, None, None,
                           {"max_observation_age_seconds":30})
    assert delays == [31]
    assert runner.read(tmp_path / "observation-ready.json") == {"monotonic_ns":123}
    assert runner.read(tmp_path / "intervention.json")["observation_ready"]["monotonic_ns"] == 123
    assert (tmp_path / "observation-release.json").exists()
    assert not (tmp_path / "execute-release.json").exists()


def test_campaign_receiver_readonly_baseline_and_original_warmup(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from emulation.experimental_lab_receiver import Receiver
    from emulation.experimental_lab_contract import canonical
    baseline = {"tables":{}, "paths":{}}
    calls = []
    class Runtime:
        baseline = None
        experiment = SimpleNamespace(episode="actual-episode")
        def capture_baseline(self):
            calls.append("capture")
            self.baseline = baseline
            return baseline
        def original_readback(self):
            calls.append("readback")
            return baseline
        def frame(self, action):
            calls.append(("original-step",action))
            return {"frame":{"request":{"action":action},"response":{"data":{"episode_id":"actual-episode"}}}}
    runtime = Runtime()
    def init(self, *args, **kwargs):
        self.runtime, self.directory, self.policy_hash = runtime, tmp_path, "a"*64
    monkeypatch.setattr(Receiver, "__init__", init)
    monkeypatch.setattr(Receiver, "persist", lambda self: None)
    monkeypatch.setattr(Receiver, "operate", lambda self, req: {"frame":{"original_reset":True}})
    monkeypatch.setattr(Receiver, "handle", lambda self, raw: {"evidence":{}})
    wrapped = runner.campaign_receiver_class()()
    assert calls == ["capture"]
    status = wrapped.handle(canonical({"operation":"status"}))
    assert status["evidence"]["baseline"] == baseline
    runner.write(tmp_path / "campaign-setup.json", dict(receiver_policy_sha256="a"*64,
        initial_action=1, campaign_source_sha256=runner.digest(runner.Path(runner.__file__))))
    value = wrapped.operate(SimpleNamespace(operation="bootstrap"))
    assert calls[-1] == ("original-step",1)
    assert value["episode_id"] == "actual-episode" and value["initial_reset"]["frame"]["original_reset"]
    assert value["frame"]["request"]["action"] == 1


async def test_campaign_bootstrap_recovery_requires_exact_readback(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.modules.autonomy.experimental.schemas import BootstrapCommand, contract_digest
    from tests.experimental_lab_support import case
    fixture = case()
    baseline = {"tables": {"r:1":{"rules":[],"routes":[]}}, "paths":{"h1->h3":{"nodes":["h1","r","h3"]}}}
    command = BootstrapCommand(request_id=fixture.policy.run_id, run_id=fixture.policy.run_id,
        runtime=fixture.policy.runtime, policy_sha256=contract_digest(fixture.policy), receiver_policy_sha256="b"*64,
        baseline=baseline, baseline_sha256=contract_digest(baseline), ownership_sha256="c"*64)
    evidence = dict(restoration=dict(baseline=baseline, baseline_sha256=command.baseline_sha256,
                                   owned_empty=True, readback=baseline))
    owner = SimpleNamespace(request=AsyncMock(side_effect=[{},evidence]))
    adapter = SimpleNamespace(close=AsyncMock())
    transport = runner.CampaignTransport(adapter, owner)
    checkpoint = AsyncMock()
    result = await transport.recover_bootstrap(command, checkpoint)
    assert result.status == "restored"
    checkpoint.assert_awaited_once()
    evidence["restoration"]["readback"] = {"tables":{}, "paths":{}}
    owner.request = AsyncMock(side_effect=[{},evidence])
    assert (await transport.recover_bootstrap(command, checkpoint)).status == "uncertain"


def test_campaign_receiver_final_add_requires_exact_core_challenge_reply(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from emulation.experimental_lab_receiver import Receiver
    from emulation.experimental_lab_contract import atomic_write
    monkeypatch.setattr(Receiver, "authority", lambda self: None)
    cls = runner.campaign_receiver_class()
    instance = cls.__new__(cls)
    entry = dict(node="r",argv=["ip","route","add","10.0.0.1/32"],began=1.0,completed=None,restoring=False)
    instance.runtime = SimpleNamespace(restoring=False, transcript=[entry])
    instance.current = SimpleNamespace(request_id="actual-request")
    instance.directory = tmp_path
    instance.checkpoint_events = []
    identity = auditor.canonical({"entry":entry,"request_id":"actual-request"})
    atomic_write(tmp_path / "checkpoint-response.json", {"id":identity,"authorized":True})
    instance.dispatch_authority(entry)
    instance.authority()  # watchdog is liveness-only while the add remains pending
    instance.authority()
    assert len(instance.checkpoint_events) == 1
    assert instance.checkpoint_events[0]["authorized"] is True
    assert runner.read(tmp_path / "checkpoint-request.json")["entry"] == entry
    atomic_write(tmp_path / "checkpoint-response.json", {"id":identity,"authorized":False})
    with pytest.raises(ValueError, match="current_core_authority_denied"):
        instance.dispatch_authority(entry)


def test_wrapper_transfer_uses_live_tmpfs_stdin_exact_hash(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path = tmp_path / "experimental_lab_contract.py"
    path.write_bytes(b"# exact wrapper bytes\n")
    calls = []
    def run(argv, **kwargs):
        calls.append((argv,kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess,"run",run)
    owner = runner.OwnedReceiver(tmp_path,{}, {})
    owner.cid="a"*64
    owner.copy_wrapper(path)
    argv, kwargs = calls[0]
    assert argv[:4] == ["docker","exec","-i",owner.cid]
    assert argv[-2] == "/run/nanfo-wrapper/experimental_lab_contract.py"
    assert argv[-1] == runner.digest(path) and kwargs["input"] == path.read_bytes()
    assert kwargs["check"] is True and kwargs["timeout"] == 15


def test_receiver_original_lab_start_uses_frr_readable_umask_then_restores(monkeypatch):
    import sys
    from types import SimpleNamespace
    seen=[]
    class Lab:
        def start(self):
            mask=os.umask(0o022)
            seen.append(mask)
            return self
    module=SimpleNamespace(OspfLab=Lab)
    owner=SimpleNamespace(load_original=lambda source:module)
    def main(args):
        lab=owner.load_original("original").OspfLab()
        lab.start()
        return 0
    owner.main=main
    monkeypatch.setitem(sys.modules,"experimental_lab_receiver",owner)
    monkeypatch.setattr(runner,"campaign_receiver_class",lambda:object)
    prior=os.umask(0o077)
    try:
        assert runner.receiver_main("/private", "a"*64)==0
        current=os.umask(0o077)
        assert seen==[0o022] and current==0o077
    finally:
        os.umask(prior)


def test_frozen_source_runs_independent_of_workspace_and_rebases_model(tmp_path,monkeypatch):
    import subprocess
    import sys
    source=tmp_path/"workspace"
    for relative in ("backend","emulation","scripts","deploy","ai-engine/artifacts/adr024-qualified-001/model"):
        (source/relative).mkdir(parents=True,exist_ok=True)
    (source/"backend/module.py").write_text("VALUE='frozen'\n")
    (source/"backend/.env").write_text("SECRET=excluded")
    (source/"backend/__pycache__").mkdir()
    (source/"backend/__pycache__/bad.pyc").write_bytes(b"excluded")
    (source/"backend/alias").symlink_to(source/"backend",target_is_directory=True)
    (source/"ai-engine/artifacts/adr024-qualified-001/model/checkpoint.ptz").write_bytes(b"exact weights")
    monkeypatch.setattr(runner,"ROOT",source)
    monkeypatch.setattr(runner,"MODEL",source/"ai-engine/artifacts/adr024-qualified-001/model")
    monkeypatch.setattr(runner,"ai_interpreter",lambda:runner.Path(sys.executable))
    monkeypatch.setattr(runner,"history_roots",lambda:[source])
    frozen=tmp_path/"frozen"
    runner.freeze_runtime(frozen)
    (source/"backend/module.py").write_text("VALUE='changed'\n")
    manifest=runner.verify_runtime_snapshot(frozen)
    assert manifest["model_snapshot"]==str(frozen/"ai-engine/artifacts/adr024-qualified-001/model")
    assert not (frozen/"backend/.env").exists() and not (frozen/"backend/alias").exists()
    out=subprocess.run([sys.executable,"-c","import module; print(module.VALUE)"],cwd=frozen/"backend",
                       env={"PATH":os.environ["PATH"]},capture_output=True,check=True,text=True)
    assert out.stdout.strip()=="frozen"
    (frozen/"backend/module.py").write_text("VALUE='tampered'\n")
    with pytest.raises(ValueError,match="payload_changed"):
        runner.verify_runtime_snapshot(frozen)


def test_complete_denominator_contains_rejection_outcomes_and_nulls():
    cases=matched()
    cases[1]["outcome"]="simulation_rejected"
    cases[1]["metrics"]={k:None for k in ("goodput_mbps","loss_fraction","rtt_ms")}
    cases[2]["outcome"]="performance_rejected_then_restored"
    result=auditor.paired_metrics(cases)
    fixed0=result[0]
    assert fixed0["expected_pairs"]==2 and fixed0["available_pairs"]==1 and fixed0["mean_delta"] is None
    assert fixed0["pairs"][0]["baseline_outcome"]=="simulation_rejected"


def test_history_inventory_includes_relocated_campaigns_from_frozen_origin(tmp_path, monkeypatch):
    origin = tmp_path / "workspace"
    origin.mkdir()
    prior = origin / "nanfo-experimental-campaign-014"
    prior.mkdir()
    runner.write(prior / "plan.json", {"reserved_seeds": [1425, 1460]})
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    runner.write(frozen / "frozen-runtime.json", {"source_origin": str(origin), "seed_inventory_origins": []})
    monkeypatch.setattr(runner, "ROOT", frozen)
    assert prior in runner.history_roots()
    assert set(runner.audit_seeds([prior])["reserved_seeds"]) == {1425, 1460}


def test_nested_private_plan_excludes_only_its_own_reservation(tmp_path, monkeypatch):
    output = tmp_path / "campaign"
    output.mkdir()
    runner.write(output / "seed-audit.json", {"documents": []})
    plan = {"trials": [{"seed": 1500}], "faults": [], "smoke": []}
    runner.write(output / "plan.json", plan)
    monkeypatch.setattr(runner, "history_roots", lambda: [tmp_path])
    runner.reject_new_seed_reservations(output, plan)
    runner.write(tmp_path / "other-plan.json", {"seed": 1500})
    with pytest.raises(ValueError, match="new_conflicting_operational_seed_reservation"):
        runner.reject_new_seed_reservations(output, plan)


def test_poor_performance_is_measured_rejection_not_invalid_measurement():
    from tests.unit.test_experimental_simulation import frame_fixture
    from tests.experimental_lab_support import case
    import copy
    c=case()
    raw=copy.deepcopy(frame_fixture(action=0)["raw"])
    raw["evidence"]["ping"]["observed_at"]="2026-09-20T12:00:00+00:00"
    paths=raw["evidence"]["route_end"]["readback"]["paths"]
    assert paths
    routes=tuple(c.policy.routes[0].model_copy(update={"action_id":f"route{i}","path":("a","b" if i==0 else "c","z")}) for i in (0,1))
    policy=c.policy.model_copy(update={"routes":routes})
    raw["evidence"]["ping"].update(sent=20,received=2)
    result=auditor.raw_performance({"response":{"ok":True,"data":raw}},policy)
    assert not result["passed"] and not result["checks"]["probe_loss"]
    assert result["metrics"]["loss_fraction"]==.9
    raw["evidence"]["measurement_complete"]=False
    with pytest.raises(ValueError,match="measurement_invalid"):
        auditor.raw_performance({"response":{"ok":True,"data":raw}},policy)


def test_export_copies_every_frame_including_rejected_bytes(tmp_path,monkeypatch):
    from types import SimpleNamespace
    frames=[{"request":{"command":"reset"},"response":{"ok":True}},
            {"request":{"command":"step"},"response":{"ok":False,"error":"original_failure"}}]
    by_hash={auditor.canonical(f):json.dumps(f).encode() for f in frames}
    def run(argv,**kwargs):
        return SimpleNamespace(stdout=by_hash[argv[-1]])
    monkeypatch.setattr(runner.subprocess,"run",run)
    owner=runner.OwnedReceiver(tmp_path,{},{})
    owner.cid="a"*64
    owner.export_frames({"runtime":{"frame_hashes":list(by_hash)}})
    refs=runner.read(tmp_path/"raw-frame-inventory.json")
    assert len(refs)==2
    assert [auditor.read(auditor.artifact(tmp_path,r)) for r in refs]==frames


def test_prepare_has_two_model_two_heuristic_smokes_and_v2_outcomes(tmp_path,monkeypatch):
    history=tmp_path/"history"
    history.mkdir()
    monkeypatch.setattr(runner,"model_identity",lambda *_:{})
    monkeypatch.setattr(runner,"source_pins",lambda:{})
    plan=runner.prepare(tmp_path/"campaign",roots=[history],pairs=6)
    assert len(plan["trials"])==48 and len(plan["faults"])==20 and len(plan["smoke"])==4
    assert {(r["policy"],r["scenario"]) for r in plan["smoke"]}=={
        (p,s) for p in ("qualified","heuristic") for s in runner.SCENARIOS}
    assert not {r["seed"] for r in plan["smoke"]}&{r["seed"] for r in plan["trials"]+plan["faults"]}
    assert plan["outcome_protocol"]==runner.OUTCOME_PROTOCOL and plan["migration_target"]=="0029"
