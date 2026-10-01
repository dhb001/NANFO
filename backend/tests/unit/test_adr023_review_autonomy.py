"""Regression assertions for ADR023Review2/3/4/5; no calibrated evidence created."""

import hashlib
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.autonomy.calibration_verification import LoadedCalibration
from app.modules.autonomy.calibration_verification_models import CalibrationScope
from app.modules.autonomy.execution import ReceiverJournal
from app.modules.autonomy.execution_repository import ExecutionRepository
from app.modules.autonomy.provider_state import ProviderStateRepository
from app.modules.autonomy.safety_installation import IndependentInstallationValidator
from app.modules.autonomy.safety_provider import CalibratedSafetyProvider, ValidatedInstallation
from app.modules.autonomy.schemas import contract_digest
from app.modules.telemetry.pins import TelemetryEvidenceService
from tests.autonomous_execution_support import fixture, reviewed_config


def independent(runtime="ovs"):
    case = fixture(runtime=runtime)
    data = case.installation.data
    config = reviewed_config(data)
    scope = CalibrationScope(network_id=str(data.network_id), run_id=data.calibration.run_id,
        provider_id=data.calibration.provider_id, environment="isolated-emulation",
        configuration_sha256=data.configuration_sha256, egress_ids=data.calibration.egress_ids,
        demand_ids=data.calibration.demand_ids, action_ids=[a.action_id for a in data.actions],
        max_dt_seconds=data.dt_seconds, max_delay_seconds=config.max_delay_seconds)
    loaded = LoadedCalibration(data.calibration, scope, "a" * 64, False, config)
    return case, data, loaded, IndependentInstallationValidator(loaded)


@pytest.mark.parametrize("change", ["plan", "egress", "demand", "logical", "total_delay", "legacy"])
def test_reviewed_config_not_provider_self_hash_is_authority(change):
    case, data, loaded, validator = independent()
    assert validator.validate(data, {}, sha256="f" * 64) == "f" * 64
    altered = data.model_copy(deep=True)
    if change == "plan":
        altered.actions[0].plan.paths = [["s1", "s4", "s2"]]
    elif change == "egress":
        altered.execution = altered.execution.model_copy(update={"egresses": {
            **altered.execution.egresses, "a": altered.execution.egresses["a"].model_copy(update={"interface": "foreign-port"})}})
    elif change == "demand":
        altered.execution = altered.execution.model_copy(update={"demands": {
            "demand-1": altered.execution.demands["demand-1"].model_copy(update={"destination_address": "192.0.2.1"})}})
    elif change == "logical":
        altered.policy.allowed_paths[0].destination = "other-node"
    elif change == "total_delay":
        altered.policy.max_delay_seconds = 10.
    else:
        altered.execution = None
    # Rehashing a substituted provider document cannot bless it.
    content = altered.model_dump_json().encode()
    with pytest.raises(ValueError):
        validator.validate(altered, {}, sha256=hashlib.sha256(content).hexdigest())
    with pytest.raises(ValueError):
        ValidatedInstallation(content, hashlib.sha256(content).hexdigest(), case.installation.reviewed_configuration).assert_reviewed_execution()


def test_legacy_independent_campaign_without_executable_binding_cannot_install():
    _, data, loaded, _ = independent()
    legacy = loaded.configuration.model_copy(update={"execution": None})
    validator = IndependentInstallationValidator(LoadedCalibration(loaded.calibration, loaded.scope, "a" * 64, False, legacy))
    with pytest.raises(ValueError, match="binding_missing"):
        validator.validate(data, {}, sha256="f" * 64)


def test_total_delay_and_exclusive_remaining_dispatch_budget():
    case, data, loaded, validator = independent()
    # Qualification total .7, actuation .1: exclusive issuance cutoff observed+.6.
    config = loaded.configuration.model_copy(update={"max_delay_seconds": .7})
    scope = loaded.scope.model_copy(update={"max_delay_seconds": .7})
    data.policy.max_delay_seconds = .7
    validator = IndependentInstallationValidator(LoadedCalibration(data.calibration, scope, "a" * 64, False, config))
    assert validator.validate(data, {}, sha256="f" * 64) == "f" * 64
    content = data.model_dump_json().encode()
    provider = CalibratedSafetyProvider(None, ValidatedInstallation(content, hashlib.sha256(content).hexdigest(), config.model_dump_json().encode()))
    observed = case.observation.observed_at.timestamp()
    args = case.observation, case.proposal, case.safety.binding.observation, case.safety.binding.state
    good = provider.evaluate(*args, now=observed + .5)
    assert good.admissible
    assert good.certificate.expires_at_unix_seconds <= observed + .6
    assert not provider.evaluate(*args, now=observed + .7).admissible
    data.policy.max_delay_seconds = 10.
    with pytest.raises(ValueError, match="total_delay"):
        validator.validate(data, {}, sha256="f" * 64)


def test_unaccepted_frr_runtime_descriptor_is_not_an_independent_signature():
    _, data, _, validator = independent("frr")
    with pytest.raises(ValueError, match="runtime_trust_missing"):
        validator.validate(data, {}, sha256="f" * 64)
    validator.runtime_trust = dict(accepted_runtime_sha256=set(), accepted_equivalence_sha256=set(), store=None, source_root=None)
    with pytest.raises(ValueError, match="not_independently_accepted"):
        validator.validate(data, {data.runtime_binding.path: b"unsigned"}, sha256="f" * 64)


async def test_core_insert_pins_exact_serialized_evidence_before_write(monkeypatch):
    case = fixture()
    record_id = uuid.uuid4()
    case.observation.evidence = [f"telemetry_record:{record_id}"]
    pin = AsyncMock()
    monkeypatch.setattr(TelemetryEvidenceService, "pin", pin)
    async def insert(_):
        pin.assert_awaited_once()
        assert pin.await_args.args[0].record_id == record_id
        assert pin.await_args.args[0].network_id == case.observation.network_id
    db = SimpleNamespace(execute=AsyncMock(side_effect=insert), get=AsyncMock(return_value=SimpleNamespace(
        safety_observation=case.safety.binding.observation.model_dump(mode="json"))))
    assert await ProviderStateRepository(db).record_observation(case.observation, case.safety.binding.observation) == contract_digest(case.observation)


async def test_core_insert_extracts_both_observation_and_safety_frame_references(monkeypatch):
    case = fixture()
    first, second = uuid.uuid4(), uuid.uuid4()
    case.observation.evidence = [f"telemetry_record:{first}"]
    frame = case.safety.binding.observation.model_copy(update={"snapshot_id": f"telemetry_record:{second}"})
    pin = AsyncMock()
    monkeypatch.setattr(TelemetryEvidenceService, "pin", pin)
    db = SimpleNamespace(execute=AsyncMock(), get=AsyncMock(return_value=SimpleNamespace(safety_observation=frame.model_dump(mode="json"))))
    await ProviderStateRepository(db).record_observation(case.observation, frame)
    assert {call.args[0].record_id for call in pin.await_args_list} == {first, second}


async def test_final_checkpoint_rechecks_revocation_after_contended_lock(monkeypatch):
    case = fixture()
    allowed, validations, guards = True, [], []
    async def validate(db, auth, accepted, runtime_guard=True):
        validations.append(allowed)
        guards.append(runtime_guard)
        if not allowed:
            raise ValueError("actor_revoked")
    async def lock(*_):
        nonlocal allowed
        allowed = False
        return SimpleNamespace(cancel_requested=False, phase="applying")
    monkeypatch.setattr(ExecutionRepository, "owned", lock)
    db = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())
    @asynccontextmanager
    async def sessions():
        yield db
    journal = ReceiverJournal(sessions, SimpleNamespace(safety=case.provider, check=validate), case.command, "token")
    with pytest.raises(ValueError, match="actor_revoked"):
        await journal.checkpoint(case.command, mutation=True)
    assert validations == [True, False]
    # ADR-028 fix 1: runtime-guard I/O runs only in the first check, before any row lock.
    assert guards == [True, False]
    db.commit.assert_not_awaited()
