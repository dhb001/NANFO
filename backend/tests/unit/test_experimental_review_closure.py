"""Offline regressions for ADR027; retained014 is read-only historical evidence."""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import audit_experimental_lab as audit
from scripts import verify_experimental_lab as runner

CAMPAIGN = Path(__file__).resolve().parents[3] / "nanfo-experimental-campaign-014"


def test_rejection_enforcement_is_window_and_action_bound_without_historical_artifacts(tmp_path):
    """Runs in the frozen gates too: no accepted marker substitutes for enforcement."""
    class Record:
        def __init__(self, value):
            self.value = value
        def model_dump(self, **_):
            return self.value
    frame = {"response": {"data": {"episode_id": "episode", "step_index": 1}}}
    prepared = Record({"command": {"request_id": "action"}})
    prepared.command = SimpleNamespace(request_id="action")
    recovery = Record({"status": "restored", "action_sha256": audit.canonical(prepared.value)})
    records = dict(prepared=prepared, recovery=recovery)
    journal = {"receipts": [dict(kind=phase, request_id="action", payload=recovery.value if phase == "restored" else {})
        for phase in ("prepared", "dispatching", "interrupted", "recovering", "restored")]}
    controller = dict(status="failed", error_type="ValueError", exception=[
        dict(type="ValueError", message="experimental_receiver_uncertain_or_rejected")])
    runner.write(tmp_path / "controller.json", controller)
    directory = tmp_path / "case"
    directory.mkdir()
    row = dict(case_id="case", controller=runner.reference(tmp_path, tmp_path / "controller.json"))
    req = dict(request_id="action", operation="execute", policy_sha256="a"*64, fence=1)
    response = dict(request_id="action", policy_sha256="a"*64, fence=1, status="rejected",
        evidence=dict(failed_frame=frame, reason="measured_verification_failed"))
    runner.write(directory / "wire-action.json", dict(request=req, response=response))
    native = dict(policy_sha256="a"*64, receipts={"action": dict(request_sha256=audit.canonical(req), response=response)})
    failed = [dict(raw_sha256=audit.canonical(frame))]
    audit.audit_rejection(tmp_path, row, records, journal, native, failed)
    for phase in ("dispatching", "interrupted", "recovering", "restored"):
        broken = {"receipts": [r for r in journal["receipts"] if r["kind"] != phase]}
        with pytest.raises(ValueError, match="rejection_phase_missing"):
            audit.audit_rejection(tmp_path, row, records, broken, native, failed)
    with pytest.raises(ValueError, match="enforcement_unbound"):
        audit.audit_rejection(tmp_path, row, records, journal, native, [dict(raw_sha256="b"*64)])
    broken = deepcopy(journal)
    broken["receipts"][-1]["payload"]["status"] = "uncertain"
    with pytest.raises(ValueError, match="recovery_not_durable"):
        audit.audit_rejection(tmp_path, row, records, broken, native, failed)


@pytest.mark.skipif(not CAMPAIGN.exists(), reason="historical014 not copied into executable snapshot")
def test_all_case_diagnostic_continues_through_eight_recorded_failures():
    result = audit.diagnose(CAMPAIGN)
    assert result["status"] == "diagnostic_only" and result["acceptance"] is False
    assert len(result["cases"]) == 68 and result["recorded_failed"] == 8
    cases = {c["case_id"]: c for c in result["cases"]}
    for name in ("path0-1429-fixed1", "path1-1432-heuristic"):
        assert cases[name]["diagnostic_outcome"] == "measurement_invalid"
        assert cases[name]["windows"][-1]["metrics"] is None
        assert cases[name]["windows"][-1]["truncated"] is True
    assert cases["path1-link-failure"]["native_phase"] == "restored"
    assert cases["path1-link-failure"]["core_phase"] == "uncertain"
    assert cases["path1-link-failure"]["core_released"] is False


def rejection_fixture():
    from app.modules.autonomy.experimental.schemas import ExperimentalPolicy
    manifest = audit.read(CAMPAIGN / "campaign-evidence.json")
    row = next(r for r in manifest["cases"] if r["outcome"] == "performance_rejected_then_restored")
    policy = ExperimentalPolicy.model_validate(audit.read(audit.artifact(CAMPAIGN, row["operator_policy"])))
    records = audit.audit_chain(CAMPAIGN, row["chain"], policy, positive=False)
    journal = audit.read(audit.artifact(CAMPAIGN, row["journal"]))
    native = audit.read(audit.artifact(CAMPAIGN, row["native_journal"]))
    windows = [audit.raw_performance(f, policy) for f in native["frames"] if f["request"]["command"] == "step"]
    failures = [w for w in windows if not w["passed"]]
    return row, records, journal, native, failures


@pytest.mark.skipif(not CAMPAIGN.exists(), reason="historical014 not copied into executable snapshot")
def test_actual_bad_performance_requires_exact_failed_receipt_and_durable_recovery():
    row, records, journal, native, failures = rejection_fixture()
    audit.audit_rejection(CAMPAIGN, row, records, journal, native, failures)
    for phase in ("dispatching", "interrupted", "recovering", "restored"):
        broken = deepcopy(journal)
        broken["receipts"] = [r for r in broken["receipts"] if r["kind"] != phase]
        with pytest.raises(ValueError, match="rejection_phase_missing"):
            audit.audit_rejection(CAMPAIGN, row, records, broken, native, failures)
    broken = deepcopy(native)
    for receipt in broken["receipts"].values():
        receipt["response"]["evidence"].pop("failed_frame", None)
    with pytest.raises(ValueError, match="not_durable"):
        audit.audit_rejection(CAMPAIGN, row, records, journal, broken, failures)


@pytest.mark.skipif(not CAMPAIGN.exists(), reason="historical014 not copied into executable snapshot")
def test_bad_window_cannot_hide_unexpected_control_error(tmp_path):
    row, records, journal, native, failures = rejection_fixture()
    controller = audit.read(audit.artifact(CAMPAIGN, row["controller"]))
    controller["exception"] = [{"type": "ValueError", "message": "UnexpectedControlFailure"}]
    runner.write(tmp_path / "controller.json", controller)
    row = {**row, "controller": runner.reference(tmp_path, tmp_path / "controller.json")}
    with pytest.raises(ValueError, match="unexplained_rejection_control_failure"):
        audit.audit_rejection(tmp_path, row, records, journal, native, failures)


async def test_deadline_crossing_final_authority_reports_action_expiry(monkeypatch):
    from contextlib import asynccontextmanager
    from app.modules.autonomy.experimental import controller as core
    from app.modules.autonomy.experimental.schemas import ActionCommand, utcnow
    from tests.experimental_lab_support import case
    from uuid import uuid4
    c = case()
    now = utcnow()
    command = ActionCommand(request_id=uuid4(), run_id=c.policy.run_id,
        resource_id=c.policy.runtime.resource_id, fence=1, network_id=c.policy.network_id,
        workspace_id=c.policy.workspace_id, runtime=c.policy.runtime, route=c.policy.routes[0],
        policy_sha256="a"*64, frame_sha256="a"*64, inference_sha256="a"*64,
        simulation_sha256="a"*64, created_at=now, expires_at=now + timedelta(seconds=1))
    run = SimpleNamespace(run_id=c.policy.run_id, stopped=False, released=False,
        policy_sha256="a"*64, fence=1, lease_token=uuid4())
    repo = SimpleNamespace(lock=AsyncMock(return_value=(object(), run)), owned=lambda *_: None,
        renew=lambda *_: None,
        pending=AsyncMock(return_value=SimpleNamespace(command=command.model_dump(mode="json"))))
    monkeypatch.setattr(core, "LabRepository", lambda _: repo)
    clock = [now]
    monkeypatch.setattr(core, "utcnow", lambda: clock[0])
    controller = core.ExperimentalController(None, c.authority, None, c.policy)
    @asynccontextmanager
    async def transaction():
        yield SimpleNamespace(flush=AsyncMock())
    controller.transaction = transaction
    async def cross(_):
        clock[0] = command.expires_at
    controller.authority.check = cross
    with pytest.raises(ValueError, match="^experimental_action_expired$"):
        await controller._checkpoint_state(final_authority=True)


@pytest.mark.parametrize("reason,expired,expected", [
    ("watchdog:action_expired", True, "experimental_action_expired"),
    ("watchdog:action_expired", False, "experimental_receiver_uncertain_or_rejected"),
    ("watchdog:controller_disconnected", True, "experimental_receiver_uncertain_or_rejected"),
])
async def test_only_bound_expiry_heartbeat_maps_to_action_expiry(reason, expired, expected):
    import time
    from app.modules.autonomy.experimental.adapter import ExperimentalLabAdapter
    from emulation.experimental_lab_contract import decode
    adapter = ExperimentalLabAdapter.__new__(ExperimentalLabAdapter)
    adapter.fence, adapter.token, adapter.policy_hash = 1, "b"*64, "a"*64
    adapter.action_expires_at = time.time() + (-10 if expired else 10)
    async def transport(payload):
        req = decode(payload)
        return {**{k: req[k] for k in ("version", "request_id", "fence", "policy_sha256")},
            "status": "rejected", "evidence": {"stop_cause": {"reason": reason}}}
    adapter.transport = transport
    with pytest.raises(ValueError, match="^" + expected + "$"):
        await adapter._call("heartbeat")


def test_preacquisition_failure_is_not_obscured_by_missing_policy(tmp_path):
    case = dict(case_id="path0-1433-fixed1", seed=1433, scenario="path0", policy="fixed1")
    directory = tmp_path / case["case_id"]
    directory.mkdir()
    runner.write(tmp_path / "plan.json", {"outcome_protocol": runner.OUTCOME_PROTOCOL})
    attempt = dict(status="failed", reason="qualified_frozen_runtime_unavailable")
    runner.write(directory / "attempt.json", attempt)
    row = runner.assemble_case(tmp_path, case, attempt)
    assert row["status"] == "failed"
    assert row["outcome_error"] == "ValueError:preacquisition_failed:qualified_frozen_runtime_unavailable"
    assert "attempt" in row and "operator_policy" not in row


async def test_denied_heartbeat_is_retained_without_credentials(tmp_path, monkeypatch):
    from emulation import experimental_lab_operator as operator
    from emulation.experimental_lab_contract import canonical
    request = dict(request_id="denied-heartbeat", operation="heartbeat", token="private-test-token")
    response = dict(status="rejected", evidence={"reason": "heartbeat_denied"})
    monkeypatch.setattr(operator, "exchange", lambda *_: response)
    owner = runner.OwnedReceiver(tmp_path, {}, {})
    assert await owner.exchange(canonical(request)) == response
    wire = runner.read(tmp_path / "wire-denied-heartbeat.json")
    assert wire == dict(request={k: v for k, v in request.items() if k != "token"}, response=response)
    assert b"private-test-token" not in (tmp_path / "wire-denied-heartbeat.json").read_bytes()
