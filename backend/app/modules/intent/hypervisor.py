"""Intent hypervisor baseline execution and rollback helpers.

VS9 scope:
- Vendor-neutral dispatch baseline for validated intents.
- Deterministic verification outcome shaping.
- Rollback-ready metadata when verification fails.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_VERIFICATION_FAILURE_ACTIONS = {
    "isolate_vlan",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class HypervisorExecutionOutcome:
    """Deterministic baseline outcome for a single hypervisor execution."""

    terminal_status: str
    verification: dict[str, Any]
    rollback: dict[str, Any] | None
    execution_summary: str
    failure_reason: str | None


class HypervisorExecutionService:
    """Vendor-neutral hypervisor baseline execution.

    This service is intentionally deterministic and in-process for VS9 baseline.
    """

    def execute(
        self,
        *,
        intent_id: uuid.UUID,
        intent_kind: str,
        validation_result: dict[str, Any],
        correlation_id: uuid.UUID,
        requested_by_user_id: str,
    ) -> HypervisorExecutionOutcome:
        required_checks_raw = validation_result.get("required_checks")
        required_checks = (
            [str(item) for item in required_checks_raw if str(item).strip()]
            if isinstance(required_checks_raw, list)
            else []
        )
        simulation_required = bool(validation_result.get("simulation_required", True))

        dispatched_at = _now_iso()

        if simulation_required and "simulation_before_deployment" not in required_checks:
            return HypervisorExecutionOutcome(
                terminal_status="execution_failed",
                verification={
                    "status": "failed",
                    "checked_at": _now_iso(),
                    "checks": ["simulation_before_deployment"],
                    "policy_reference": "ADR-008",
                    "failure_reason": "simulation_policy_gate_missing",
                },
                rollback=None,
                execution_summary=(
                    "Execution blocked by simulation-before-deployment policy gate before dispatch."
                ),
                failure_reason="simulation_policy_gate_missing",
            )

        verification_status = "failed" if intent_kind in _VERIFICATION_FAILURE_ACTIONS else "passed"
        verification = {
            "status": verification_status,
            "checked_at": _now_iso(),
            "checks": [
                "simulation_before_deployment",
                "post_change_health",
            ],
            "policy_reference": "ADR-008",
            "driver_profile": "vendor_neutral_baseline",
            "dispatched_at": dispatched_at,
            "requested_by_user_id": requested_by_user_id,
        }

        if verification_status == "passed":
            return HypervisorExecutionOutcome(
                terminal_status="execution_completed",
                verification=verification,
                rollback=None,
                execution_summary="Execution verified by hypervisor baseline checks.",
                failure_reason=None,
            )

        rollback_reference = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{intent_id}:{correlation_id}:rollback",
        )
        rollback = {
            "attempted": True,
            "status": "completed",
            "strategy": "compensating_transaction",
            "rollback_reference_id": str(rollback_reference),
            "rollback_started_at": _now_iso(),
            "rollback_completed_at": _now_iso(),
            "failure_reason": "post_change_verification_failed",
        }

        return HypervisorExecutionOutcome(
            terminal_status="execution_failed",
            verification=verification,
            rollback=rollback,
            execution_summary="Execution failed verification; rollback baseline completed.",
            failure_reason="post_change_verification_failed",
        )
