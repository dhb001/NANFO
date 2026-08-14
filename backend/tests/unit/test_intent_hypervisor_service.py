"""Unit tests for VS9 hypervisor baseline execution service."""

from __future__ import annotations

import uuid

from app.modules.intent.hypervisor import HypervisorExecutionService


def test_hypervisor_execute_returns_completed_when_verification_passes():
    outcome = HypervisorExecutionService().execute(
        intent_id=uuid.uuid4(),
        intent_kind="reroute_path",
        validation_result={
            "simulation_required": True,
            "required_checks": ["simulation_before_deployment"],
        },
        correlation_id=uuid.uuid4(),
        requested_by_user_id=str(uuid.uuid4()),
    )

    assert outcome.terminal_status == "execution_completed"
    assert outcome.verification["status"] == "passed"
    assert outcome.rollback is None
    assert outcome.failure_reason is None


def test_hypervisor_execute_returns_failed_with_rollback_on_verification_failure():
    outcome = HypervisorExecutionService().execute(
        intent_id=uuid.uuid4(),
        intent_kind="isolate_vlan",
        validation_result={
            "simulation_required": True,
            "required_checks": ["simulation_before_deployment", "blast_radius_assessment"],
        },
        correlation_id=uuid.uuid4(),
        requested_by_user_id=str(uuid.uuid4()),
    )

    assert outcome.terminal_status == "execution_failed"
    assert outcome.verification["status"] == "failed"
    assert outcome.rollback is not None
    assert outcome.rollback["attempted"] is True
    assert outcome.rollback["status"] == "completed"
    assert outcome.failure_reason == "post_change_verification_failed"


def test_hypervisor_execute_fails_when_simulation_gate_missing():
    outcome = HypervisorExecutionService().execute(
        intent_id=uuid.uuid4(),
        intent_kind="reroute_path",
        validation_result={
            "simulation_required": True,
            "required_checks": ["blast_radius_assessment"],
        },
        correlation_id=uuid.uuid4(),
        requested_by_user_id=str(uuid.uuid4()),
    )

    assert outcome.terminal_status == "execution_failed"
    assert outcome.verification["status"] == "failed"
    assert outcome.failure_reason == "simulation_policy_gate_missing"
    assert outcome.rollback is None
