"""Deterministic autonomy persistence/provider doubles; not installed application adapters."""

import copy
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.modules.autonomy.models import AutonomyControl, AutonomyDecision
from app.modules.autonomy.providers import Providers
from app.modules.autonomy.safety import SafetyShield, safety_input_digest
from app.modules.autonomy.schemas import (
    Observation,
    OperationalSettings,
    Proposal,
    ProviderStatus,
    Qualification,
    SafetyAssessment,
    SafetyBinding,
    Verification,
    contract_digest,
)

HASH = "a" * 64


def control_record(**changes):
    values = {
        "network_id": uuid.uuid4(), "workspace_id": uuid.uuid4(), "mode": "autonomous",
        "checkpoint_sha256": HASH, "approval_expires_at": datetime.now(UTC) + timedelta(minutes=10),
        "approved_by_user_id": str(uuid.uuid4()), "emergency_stopped": False, "stopped_at": None,
        "stopped_by_user_id": None, "active_execution_id": None, "active_intent_id": None,
        "active_decision_id": None, "cancellation_status": "none", "revision": 1, "claim_token": uuid.uuid4(),
        "lease_expires_at": datetime.now(UTC) + timedelta(seconds=30), "next_cycle_at": datetime.now(UTC),
        "last_observation": None, "last_accepted_observed_at": None, "updated_at": datetime.now(UTC),
    }
    return AutonomyControl(**(values | changes))


class MemoryRepository:
    def __init__(self, control=None):
        self.control, self.rows = control, []

    async def get(self, network_id, *, lock=False):
        return self.control if self.control and self.control.network_id == network_id else None

    async def ensure(self, network_id, workspace_id):
        if self.control is None:
            self.control = control_record(network_id=network_id, workspace_id=workspace_id, mode="monitor",
                checkpoint_sha256=None, approval_expires_at=None, approved_by_user_id=None, revision=0)
        return self.control

    async def history(self, network_id, limit=20):
        return [row for row in reversed(self.rows) if row.network_id == network_id][:limit]

    async def operational(self, network_id):
        return OperationalSettings()

    async def unresolved_override(self, network_id):
        return None

    async def configurations(self, network_id, limit=100):
        return []

    async def overrides(self, network_id):
        return []

    def record(self, control, *, status, reasons, actor_id=None):
        now = datetime.now(UTC)
        row = AutonomyDecision(decision_id=uuid.uuid4(), network_id=control.network_id, workspace_id=control.workspace_id,
            actor_id=actor_id or control.approved_by_user_id, mode=control.mode, control_revision=control.revision,
            status=status, reasons=reasons, checkpoint_sha256=control.checkpoint_sha256, evidence=[],
            created_at=now, updated_at=now)
        self.rows.append(row)
        return row

    async def owned(self, network_id, token):
        row = await self.get(network_id)
        return row if row and row.claim_token == token and row.lease_expires_at and row.lease_expires_at > datetime.now(UTC) else None

    async def decision(self, decision_id):
        return next(row for row in self.rows if row.decision_id == decision_id)

    async def invalidate_observing(self, network_id, reason):
        for row in self.rows:
            if row.network_id == network_id and row.status == "observing":
                row.status, row.reasons = "blocked", [reason]

    async def claim(self, **kwargs):
        if self.control is None:
            return None
        self.control.claim_token = uuid.uuid4()
        self.control.lease_expires_at = datetime.now(UTC) + timedelta(seconds=kwargs.get("lease_seconds", 30))
        if self.control.active_execution_id and not self.control.active_decision_id:
            self.control.active_decision_id = uuid.uuid4()
        return copy.copy(self.control), self.record(self.control, status="observing", reasons=[])


def sessions_for(db):
    @asynccontextmanager
    async def sessions():
        yield db
    return sessions


def qualified_providers(control):
    ready = ProviderStatus(provider_id="test_only", status="ready")
    observation = Observation(network_id=control.network_id, workspace_id=control.workspace_id,
        provider_id="test_only", contract="test.measured.v1", observed_at=datetime.now(UTC),
        collected_at=datetime.now(UTC), age_seconds=0, fresh=True, compatible=True, evidence=["test:measurement"])
    qualification = Qualification(qualified=True, checkpoint_sha256=HASH, observation_contract=observation.contract,
                                manifest_sha256="b" * 64, evidence=["test:immutable_manifest"])
    proposal = Proposal(action_id="test-action", checkpoint_sha256=HASH, observation_contract=observation.contract,
                        evidence=["test:inference"])
    safety = certified_assessment(observation, proposal)
    return Providers(
        SimpleNamespace(status=ready, observe=AsyncMock(return_value=observation)),
        SimpleNamespace(qualification_status=ready, inference_status=ready,
                        qualify=AsyncMock(return_value=qualification), infer=AsyncMock(return_value=proposal)),
        SimpleNamespace(status=ready, assess=AsyncMock(return_value=safety)),
        SimpleNamespace(status=ready, accept=AsyncMock(), verify=AsyncMock(side_effect=lambda reference:
            Verification(execution_id=reference.execution_id, status="pending", reasons=["test_pending"]))),
        SimpleNamespace(cancel=AsyncMock()),
        SimpleNamespace(cancel=AsyncMock(side_effect=lambda reference: Verification(
            execution_id=reference.execution_id, status="pending", reasons=["test_recovery_pending"]))),
    )


def certified_assessment(observation, proposal):
    from tests.unit.test_autonomy_safety import inputs

    data = inputs.__wrapped__()
    now = observation.observed_at.timestamp()
    for key in ("policy", "calibration", "observation", "state", "action"):
        data[key]["network_id"] = str(observation.network_id)
    for key in ("observation", "state"):
        data[key]["observed_at_unix_seconds"] = now
    data["calibration"]["valid_until_unix_seconds"] = now + 100
    data["state"].update(route_since_unix_seconds=now - 20, history_complete_since_unix_seconds=now - 120,
                         last_applied_at_unix_seconds=now - 20, recent_dispatch_at_unix_seconds=[now - 20])
    data["action"]["action_id"] = proposal.action_id
    data["action"]["bounds"].update(network_id=str(observation.network_id), action_id=proposal.action_id,
        observed_at_unix_seconds=now, valid_until_unix_seconds=now + 10,
        input_sha256=safety_input_digest(data["observation"], data["action"]["routes"]))
    result = SafetyShield(data["policy"], data["calibration"]).evaluate(
        data["observation"], data["action"], state=data["state"], now=now)
    from app.modules.autonomy.safety import SafetyAction, TrustedCalibration
    binding = SafetyBinding(workspace_id=observation.workspace_id, observation_sha256=contract_digest(observation),
        proposal_sha256=contract_digest(proposal), calibration_sha256=contract_digest(TrustedCalibration.model_validate(data["calibration"])),
        selected_action_sha256=contract_digest(SafetyAction.model_validate(data["action"])), evaluated_at_unix_seconds=now,
        observation=data["observation"], policy=data["policy"], calibration=data["calibration"], state=data["state"])
    return SafetyAssessment(admissible=True, action_id=proposal.action_id, model_version="bounded-fluid-v1",
        evidence=["test:bounds"], selected_action=result["selected_action"], certificate=result["certificate"], binding=binding)
