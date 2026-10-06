"""Receiver decision/readback tests with fake device, not physical certification."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.modules.autonomy.execution import valid_readback
from app.modules.autonomy.execution_contract import AutonomousCommand
from app.modules.autonomy.safety_provider import CalibratedSafetyProvider, load_safety_installation
from app.modules.autonomy.worker import validate_safety
from emulation.autonomous_receiver import AutonomousReceiver
from tests.autonomous_execution_support import FakeDevice, fixture


class Journal:
    def __init__(self):
        self.record = dict(phase="accepted", prepared=None, released=False, cancel_requested=False, result=None)
        self.allowed = True
        self.owned = True
        self.order = []

    async def inspect(self, command):
        assert self.owned
        return copy.deepcopy(self.record)

    async def checkpoint(self, command, *, mutation):
        if not self.allowed or not self.owned:
            raise ValueError("actor_stop_revision_deadline_denied")
        if mutation:
            assert self.record["phase"] == "applying"
        self.order.append("checkpoint")

    async def prepare(self, command, prepared):
        self.record.update(phase="prepared", prepared=prepared)
        self.order.append("prepare_commit")

    async def begin_apply(self, command):
        await self.checkpoint(command, mutation=False)
        self.record["phase"] = "applying"
        self.order.append("dispatch_commit")

    async def begin_recovery(self, command):
        assert self.owned
        self.record["phase"] = "recovering"

    async def recovery_checkpoint(self, command):
        assert self.owned
        assert self.record["phase"] == "recovering"

    async def verified(self, command, evidence):
        assert valid_readback(evidence)
        self.record.update(phase="verified", result=evidence)
        return self.record

    async def cancelled(self, command, evidence):
        assert evidence.get("not_dispatched") or valid_readback(evidence, recovery=True)
        self.record.update(phase="cancelled", released=True, result=evidence)
        return self.record

    async def uncertain(self, command):
        self.record["phase"] = "uncertain"
        return self.record


async def test_real_provider_constructs_action_specific_bounds_and_existing_worker_binding():
    case = fixture()
    assert validate_safety(case.safety, case.observation, case.proposal) == []
    assert case.safety.selected_action.bounds.queues[0].arrival_upper_bytes_per_second == 0
    assert case.safety.selected_action.bounds.queues[1].arrival_upper_bytes_per_second == 10
    data = case.installation.data
    assert case.safety.selected_action.bounds.queues[1].service_lower_bytes_per_second == data.actions[0].queues[1].service_lower_bytes_per_second


@pytest.mark.parametrize("change", ["scope", "missing_frame", "stale", "action", "checkpoint"])
async def test_provider_refuses_incompatible_measured_inputs(change):
    case = fixture()
    obs, proposal, frame = case.observation, case.proposal, case.safety.binding.observation
    if change == "scope":
        obs = obs.model_copy(update={"contract": "other"})
    elif change == "stale":
        obs = obs.model_copy(update={"fresh": False})
    elif change == "action":
        proposal = proposal.model_copy(update={"action_id": "uninstalled"})
    elif change == "checkpoint":
        proposal = proposal.model_copy(update={"checkpoint_sha256": "f" * 64})
    else:
        frame = frame.model_copy(update={"queues": []})
    try:
        result = case.provider.evaluate(obs, proposal, frame, case.safety.binding.state, now=datetime.now(UTC).timestamp())
        assert not result.admissible
    except (ValueError, KeyError):
        pass


def test_installation_needs_exact_pin_raw_evidence_and_independent_validator(tmp_path):
    case = fixture()
    raw = b"unit-test-only-not-calibration"
    data = json.loads(case.installation.content)
    data["evidence"] = [{"path": "raw.json", "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}]
    content = json.dumps(data).encode()
    path = tmp_path / "installation.json"
    path.write_bytes(content)
    (tmp_path / "raw.json").write_bytes(raw)
    digest = hashlib.sha256(content).hexdigest()

    class Validator:
        def validate(self, installation, evidence, *, sha256):
            assert evidence == {"raw.json": raw}
            return sha256

    assert load_safety_installation(path, digest, Validator()).sha256 == digest
    with pytest.raises(ValueError):
        load_safety_installation(path, "b" * 64, Validator())
    with pytest.raises(ValueError):
        load_safety_installation(path, digest, SimpleNamespace(validate=lambda *a, **k: "bad"))
    (tmp_path / "raw.json").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        load_safety_installation(path, digest, Validator())


@pytest.mark.parametrize("field,value", [("version", "manual_approval"), ("fence", 0), ("extra", True)])
def test_versioned_wire_rejects_manual_and_malformed_identity(field, value):
    command = fixture().command.model_dump(mode="json")
    command[field] = value
    with pytest.raises(ValidationError):
        AutonomousCommand.model_validate(command)


async def test_receiver_reads_actual_device_and_keeps_verified_policy_owned():
    device, journal, command = FakeDevice(), Journal(), fixture().command
    receiver = AutonomousReceiver(device)
    result = await receiver.receive(command, journal)
    assert result["phase"] == "verified" and not result["released"]
    assert device.applied == 1
    assert journal.order.index("prepare_commit") < journal.order.index("dispatch_commit")
    await receiver.receive(command, journal)
    assert device.applied == 1  # readback only, not a second dispatch
    device.actual = "externally_changed"
    result = await receiver.receive(command, journal)
    assert result["phase"] == "cancelled" and device.restored == 1


@pytest.mark.parametrize("phase", ["accepted", "prepared", "applying", "verified", "uncertain"])
async def test_revocation_recovery_uses_exact_journal_without_actor(phase):
    device, journal, command = FakeDevice(), Journal(), fixture().command
    if phase != "accepted":
        journal.record["prepared"] = await device.prepare(command.plan.model_dump(mode="json"))
    journal.record["phase"] = phase
    journal.allowed = False
    if phase in {"applying", "verified", "uncertain"}:
        device.actual = command.plan.model_dump(mode="json")
    result = await AutonomousReceiver(device).receive(command, journal)
    assert result["released"] and result["phase"] == "cancelled"
    assert device.applied == 0
    assert device.restored == int(phase in {"applying", "verified", "uncertain"})


async def test_lost_mutation_result_restores_and_unreachable_recovery_retains_exclusion():
    device, journal, command = FakeDevice(), Journal(), fixture().command
    device.fail_apply, device.fail_restore = True, True
    result = await AutonomousReceiver(device).receive(command, journal)
    assert result["phase"] == "uncertain" and not result["released"]
    assert device.applied == 1
    device.fail_restore = False
    await AutonomousReceiver(device).receive(command, journal)
    assert device.applied == 1 and device.restored == 1 and journal.record["released"]


async def test_ownership_loss_cannot_compensate_another_execution():
    device, journal, command = FakeDevice(), Journal(), fixture().command
    journal.owned = False
    with pytest.raises(AssertionError):
        await AutonomousReceiver(device).receive(command, journal)
    assert device.applied == device.restored == 0


async def test_provider_missing_history_is_explicitly_blocked():
    provider = CalibratedSafetyProvider(None, fixture().installation)
    assert provider.status.status == "ready"  # installation status, not current observation readiness
    assert valid_readback({"readback_sha256": "a" * 64, "readback_verified": True, "probe": {"sent": 3, "received": 2}}) is False


def test_intent_exposes_no_autonomous_acceptance_path():
    """The unused Intent-side acceptance wrapper is removed (ADR-028): autonomous work enters only
    through Autonomy's executor, and Intent never handles autonomy execution authorizations."""
    import importlib.util
    from pathlib import Path

    assert importlib.util.find_spec("app.modules.intent.autonomous") is None
    intent = Path(__file__).resolve().parents[2] / "app" / "modules" / "intent"
    for path in intent.rglob("*.py"):
        source = path.read_text()
        assert "ExecutionAuthorization" not in source and "autonomy.execution" not in source, path


def test_independent_validator_exact_profiles_transitions_and_capacity():
    from app.modules.autonomy.calibration_verification import LoadedCalibration
    from app.modules.autonomy.calibration_verification_models import CalibrationScope, NetworkQualificationConfig
    from app.modules.autonomy.safety_installation import IndependentInstallationValidator
    data = fixture().installation.data
    config = NetworkQualificationConfig(schema_version="nanfo.network-qualification-config.v1",
        provider_id=data.calibration.provider_id, egress_ids=data.calibration.egress_ids,
        demand_ids=data.calibration.demand_ids, actions=[{
            "action_id": a.action_id,
            "demand_egress_ids": {r.demand_id: next(p.egress_ids for p in data.policy.allowed_paths if p.route_id == r.route_id)
                                  for r in a.routes},
            "bounds": [q.model_dump() for q in a.queues]} for a in data.actions],
        queue_units="bytes", rate_units="bytes/second", time_units="unix-seconds", dt_seconds=data.dt_seconds,
        max_delay_seconds=data.policy.max_delay_seconds, queue_threshold_bytes=data.policy.queue_threshold_bytes,
        drift_budget_bytes_squared=data.policy.drift_budget_bytes_squared, min_samples_per_action_per_split=2,
        required_transitions=data.transitions, execution=data.execution)
    scope = CalibrationScope(network_id=str(data.network_id), run_id=data.calibration.run_id,
        provider_id=data.calibration.provider_id, environment="isolated-emulation",
        configuration_sha256=data.configuration_sha256, egress_ids=data.calibration.egress_ids,
        demand_ids=data.calibration.demand_ids, action_ids=[a.action_id for a in data.actions],
        max_dt_seconds=data.dt_seconds, max_delay_seconds=data.policy.max_delay_seconds)
    loaded = LoadedCalibration(data.calibration, scope, "a" * 64, False, config)
    validator = IndependentInstallationValidator(loaded)
    assert validator.validate(data, {}, sha256="f" * 64) == "f" * 64
    changed = data.model_copy(deep=True)
    changed.actions[0].queues[0].service_lower_bytes_per_second += 1
    with pytest.raises(ValueError, match="bounds_mismatch"):
        validator.validate(changed, {}, sha256="f" * 64)
    changed = data.model_copy(deep=True)
    changed.transitions.append((data.actions[0].action_id, data.actions[0].action_id))
    with pytest.raises(ValueError, match="profile_mismatch"):
        validator.validate(changed, {}, sha256="f" * 64)


def test_lab_lifetime_lock_excludes_legacy_manual_and_other_receivers(tmp_path):
    import fcntl
    import os
    from emulation.autonomous_ownership import IsolatedLabOwnership
    lab = SimpleNamespace(mailbox=None, stopping=False, runId="run-1")
    owner = IsolatedLabOwnership(lab, "unit-lab", results_directory=tmp_path,
                                 manual_enabled=False, experiment_enabled=False)
    try:
        assert owner.check("unit-lab", "run-1")
        with pytest.raises(BlockingIOError):
            IsolatedLabOwnership(lab, "unit-lab", results_directory=tmp_path,
                                  manual_enabled=False, experiment_enabled=False)
        fd = os.open(tmp_path / ".executor.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        lab.runId = "different-run"
        assert not owner.check("unit-lab", "run-1")
    finally:
        owner.close()


async def test_ovs_adapter_checks_each_mutation_and_actual_readback():
    from emulation.autonomous_driver import IsolatedOVSDriver
    owned = True
    calls = []
    class Actions:
        def prepare(self, plan):
            return {"before": "baseline", "plan": plan}

        def apply(self, prepared, checkpoint):
            for _ in range(3):
                checkpoint()
                calls.append("write")

        def reconcile(self, prepared=None):
            return {"actual": prepared or "baseline"}

        def probe(self, plan):
            return {"sent": 3, "received": 3}

        def rollback(self, prepared, checkpoint):
            checkpoint()
            calls.append("restore")
            return {"actual": "baseline"}

    driver = IsolatedOVSDriver(Actions(), resource_id="unit-lab", run_id="run-1",
                               ownership_check=lambda *_: owned)
    checkpoint = AsyncMock()
    prepared = await driver.prepare({"test": "plan"})
    await driver.apply(prepared, checkpoint)
    assert checkpoint.await_count == 3
    assert valid_readback(await driver.verify(prepared, {}))
    assert valid_readback(await driver.compensate(prepared, checkpoint), recovery=True)
    owned = False
    with pytest.raises(ValueError, match="ownership_lost"):
        await driver.apply(prepared, checkpoint)
    assert calls == ["write", "write", "write", "restore"]
