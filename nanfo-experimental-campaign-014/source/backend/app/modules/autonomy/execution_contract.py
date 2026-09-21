"""Private ADR023 v1 wire, separate from manual lab commands."""

import json
import uuid
from typing import Literal

from pydantic import Field, model_validator

from app.modules.autonomy.schemas import SHA256, Contract, ExecutionAuthorization, SafetyAssessment, contract_digest
from app.modules.intent.lab import LabPlan
from app.modules.autonomy.frr_contract import FRRPlan


class AutonomousCommand(Contract):
    version: Literal["nanfo.autonomous-lab/v1"] = "nanfo.autonomous-lab/v1"
    execution_id: uuid.UUID
    intent_id: uuid.UUID
    decision_id: uuid.UUID
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    resource_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_.:-]+$")
    fence: int = Field(strict=True, gt=0)
    authorization: ExecutionAuthorization
    installation_sha256: SHA256
    plan: LabPlan | FRRPlan
    operation: Literal["execute", "recover"] = "execute"

    def validate_installed_service(self, installation):
        """Read-only profile guard for callers holding an independently loaded pin.

        No new wire fields: the existing installation digest selects v1/v2. The
        receiver's authority re-evaluation also uses this same provider mapping.
        Recovery must not be refused solely because the dispatch certificate aged.
        """
        if self.installation_sha256 != installation.sha256:
            raise ValueError("autonomous_installation_pin_mismatch")
        installation.assert_reviewed_execution()
        data = installation.data
        if data.version.endswith("/v1"):
            return
        safety = SafetyAssessment.model_validate_json(self.authorization.safety_evidence_json)
        selected = safety.selected_action
        action = installation.action(selected.action_id)
        if selected.bounds.dt_seconds != data.dt_seconds or selected.bounds.dt_seconds < data.min_dt_seconds:
            raise ValueError("autonomous_service_horizon_mismatch")
        actual = {q.egress_id: q for q in selected.bounds.queues}
        if set(actual) != {q.egress_id for q in action.queues}:
            raise ValueError("autonomous_service_queue_scope_mismatch")
        for q in action.queues:
            lower, upper = installation.service_bounds(q, selected.bounds.dt_seconds)
            bound = actual[q.egress_id]
            if (bound.service_lower_bytes_per_second != lower or bound.service_upper_bytes_per_second != upper
                    or bound.arrival_upper_bytes_per_second != q.arrival_upper_bytes_per_second
                    or bound.error_upper_bytes != q.error_upper_bytes):
                raise ValueError("autonomous_service_profile_mismatch")

    @model_validator(mode="after")
    def bound(self):
        auth = self.authorization
        if any(getattr(self, key) != getattr(auth, key) for key in (
                "execution_id", "intent_id", "decision_id", "network_id", "workspace_id")):
            raise ValueError("autonomous_identity_mismatch")
        safety = SafetyAssessment.model_validate_json(auth.safety_evidence_json)
        if (not safety.admissible or not safety.selected_action or not safety.certificate or not safety.binding
                or contract_digest(safety) != auth.safety_sha256
                or contract_digest(safety.selected_action) != auth.selected_action_sha256
                or safety.selected_action.model_dump(mode="json") != json.loads(auth.selected_action_json)
                or auth.certificate_expires_at_unix_seconds != safety.certificate.expires_at_unix_seconds):
            raise ValueError("autonomous_safety_hash_mismatch")
        return self
