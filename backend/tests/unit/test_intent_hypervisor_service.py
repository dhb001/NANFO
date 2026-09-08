"""Unit tests for VS9 hypervisor baseline execution service."""

from __future__ import annotations

import uuid

import pytest

from app.modules.intent.hypervisor import HypervisorExecutionService


@pytest.mark.parametrize("mode", ["demo", "emulation", "production"])
def test_hypervisor_execute_fails_without_executor_in_all_modes(monkeypatch, mode):
    monkeypatch.setenv("EXECUTION_MODE", mode)
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

    assert outcome.terminal_status == "execution_failed"
    assert outcome.verification["status"] == "not_performed"
    assert outcome.rollback is None
    assert outcome.failure_reason == "executor_unavailable"


def test_hypervisor_execute_never_fabricates_rollback():
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
    assert outcome.verification["status"] == "not_performed"
    assert outcome.verification["checked_at"] is None
    assert outcome.rollback is None
    assert outcome.failure_reason == "executor_unavailable"


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
    assert outcome.verification["status"] == "not_performed"
    assert outcome.failure_reason == "executor_unavailable"
    assert outcome.rollback is None
