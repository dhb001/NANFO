"""Strict ADR-018 configuration and read-only exact enrollment tests."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.autonomy.schemas import OperationalSettings, ReturnOverrideRequest, TrainingSettings
from app.modules.autonomy.worker import operational_safety_reasons, validate_observation
from app.modules.intent.lab import LabResult
from app.modules.intent.overrides import IntentOverrideService
from tests.autonomy_support import control_record, qualified_providers
from tests.unit.test_intent_lab import command


@pytest.mark.parametrize("field,value", [
    ("max_observation_age_seconds", 31), ("decision_interval_seconds", 0),
    ("min_route_hold_seconds", 2), ("max_changes_per_minute", 11),
    ("max_changes_per_minute", True), ("decision_interval_seconds", "10"),
    ("max_observation_age_seconds", float("nan")),
])
def test_configuration_fixed_bounds(field, value):
    with pytest.raises(ValidationError):
        OperationalSettings(**{field: value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "1", 101, -101])
def test_reward_weights_finite(value):
    with pytest.raises(ValidationError):
        TrainingSettings(reward_weights={"delay": value})


def test_signed_requested_weights_and_explicit_return_revision():
    assert TrainingSettings(reward_weights={"delay": -.2}).reward_weights == {"delay": -.2}
    with pytest.raises(ValidationError):
        ReturnOverrideRequest(reason="return")


def test_operational_settings_gate_real_certificate_without_weakening():
    control = control_record()
    providers = qualified_providers(control)
    safety = providers.safety.assess.return_value
    assert operational_safety_reasons(OperationalSettings(), safety) == []
    assert "configured_route_hold" in operational_safety_reasons(OperationalSettings(min_route_hold_seconds=30), safety)
    assert "configured_change_rate_exceeded" in operational_safety_reasons(OperationalSettings(max_changes_per_minute=1), safety)
    obs = providers.observer.observe.return_value
    assert "observation_stale_or_missing" in validate_observation(obs, control,
        now=datetime.now(UTC) + timedelta(seconds=2), max_age_seconds=1)


@pytest.fixture
def enrollment(monkeypatch, mock_db, tmp_path):
    cmd = command()
    actor, workspace_id, network_id, intent_id = str(uuid.uuid4()), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    result = LabResult(**{key: value for key, value in cmd.model_dump().items() if key in LabResult.model_fields},
        status="completed", verification={"readback_verified": True, "readback_sha256": "b" * 64,
        "config_readback_and_reachability": True, "traffic_effects_verified": False,
        "probe": {"source_host": "h1", "destination_host": "h3", "sent": 1, "received": 1}},
        rollback=None, failure_reason=None, completed_at=datetime.now(UTC))
    job = SimpleNamespace(intent_id=intent_id, workspace_id=workspace_id, actor_id=actor, phase="completed",
        blocks_lab=False, cancel_requested=False, dispatched_at=datetime.now(UTC), command=cmd.model_dump(mode="json"),
        approved_at=datetime.now(UTC) - timedelta(seconds=1))
    intent = SimpleNamespace(workspace_id=workspace_id, network_id=network_id)
    monkeypatch.setattr("app.modules.intent.repository.IntentRepository.get_by_id", AsyncMock(return_value=intent))
    monkeypatch.setattr("app.modules.identity.service.AuthService.get_profile", AsyncMock(return_value=SimpleNamespace(
        permissions=["write:config", "execute:rollback"])))
    monkeypatch.setattr("app.modules.network.service.NetworkService.assert_network_workspace_access", AsyncMock())
    mailbox = SimpleNamespace(results=tmp_path, read=AsyncMock(return_value=result), write=AsyncMock())
    service = IntentOverrideService(mock_db, None, mailbox=mailbox)
    service.repo.get_execution = AsyncMock(return_value=job)
    journal = {"active": str(cmd.execution_id), "blocked": False, "records": {str(cmd.execution_id): {
        "phase": "terminal", "command": cmd.model_dump(mode="json"), "result": result.model_dump(mode="json")}}}
    monkeypatch.setattr("app.modules.intent.overrides.read_bounded_file", lambda *_: json.dumps(journal).encode())
    return SimpleNamespace(service=service, job=job, cmd=cmd, journal=journal, mailbox=mailbox,
        args=dict(network_id=network_id, workspace_id=workspace_id, intent_id=intent_id, execution_id=cmd.execution_id,
                  actor_id=actor, override_id=uuid.uuid4()))


async def test_enrollment_reads_only_current_exact_identity(enrollment):
    result = await enrollment.service.inspect_override_execution(**enrollment.args)
    assert len(result["capability"]) == 64
    assert result["execution_id"] == str(enrollment.cmd.execution_id)
    enrollment.mailbox.write.assert_not_called()


@pytest.mark.parametrize("mutation", ["actor", "network", "phase", "cancel", "inactive", "restored", "blocked", "stale", "hash"])
async def test_enrollment_rejects_noncurrent_or_unowned(enrollment, mutation):
    record = enrollment.journal["records"][str(enrollment.cmd.execution_id)]
    if mutation == "actor":
        enrollment.args["actor_id"] = str(uuid.uuid4())
    elif mutation == "network":
        enrollment.args["network_id"] = uuid.uuid4()
    elif mutation == "phase":
        enrollment.job.phase = "cancelled"
    elif mutation == "cancel":
        enrollment.job.cancel_requested = True
    elif mutation == "inactive":
        enrollment.journal["active"] = str(uuid.uuid4())
    elif mutation == "restored":
        record["restored_by"] = str(uuid.uuid4())
    elif mutation == "blocked":
        enrollment.journal["blocked"] = True
    elif mutation == "stale":
        result = enrollment.mailbox.read.return_value.model_copy(update={"completed_at": datetime.now(UTC) - timedelta(minutes=1)})
        enrollment.mailbox.read.return_value = result
        record["result"] = result.model_dump(mode="json")
    else:
        record["command"]["binding_digest"] = "c" * 64
    with pytest.raises(HTTPException):
        await enrollment.service.inspect_override_execution(**enrollment.args)
    enrollment.mailbox.write.assert_not_called()
