"""Fail-closed intent execution until a real controller is installed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HypervisorExecutionOutcome:
    terminal_status: str
    verification: dict[str, Any]
    rollback: dict[str, Any] | None
    execution_summary: str
    failure_reason: str | None


class HypervisorExecutionService:
    """Execution mode is not evidence that a controller exists."""

    def execute(
        self,
        *,
        intent_id: uuid.UUID,
        intent_kind: str,
        validation_result: dict[str, Any],
        correlation_id: uuid.UUID,
        requested_by_user_id: str,
    ) -> HypervisorExecutionOutcome:
        return HypervisorExecutionOutcome(
            terminal_status="execution_failed",
            verification={
                "status": "not_performed",
                "checked_at": None,
                "checks": [],
                "policy_reference": "ADR-008",
                "failure_reason": "executor_unavailable",
            },
            rollback=None,
            execution_summary="No controller is installed. No change, verification, or rollback was performed.",
            failure_reason="executor_unavailable",
        )
