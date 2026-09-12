"""Optional evidence checks run before idempotent replay or manual acceptance."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.intent.execution import accept_execution
from app.modules.intent.service import IntentExecutionService
from app.modules.simulation.modeled import current_network_state_hash
from app.modules.simulation.service import SimulationStartService


@pytest.mark.parametrize("mode", ["demo", "production"])
async def test_provided_reference_cannot_enter_legacy_or_production_path(
    mock_db, fake_redis, execution_mode, mode
):
    execution_mode(mode)
    with pytest.raises(HTTPException) as error:
        await IntentExecutionService(db=mock_db, redis=fake_redis).execute_intent(
            workspace_id=uuid.uuid4(),
            intent_id=uuid.uuid4(),
            simulation_id=uuid.uuid4(),
            idempotency_key=None,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
            requested_permissions=["write:config", "execute:rollback"],
            manual_approval=True,
        )
    assert error.value.status_code == 409
    mock_db.commit.assert_not_awaited()


@pytest.fixture
def acceptance(monkeypatch, mock_db, fake_redis):
    workspace_id, intent_id = uuid.uuid4(), uuid.uuid4()
    row = SimpleNamespace(
        workspace_id=workspace_id,
        intent_id=intent_id,
        network_id=uuid.uuid4(),
        intent_payload={"action": "test"},
        status="validated",
    )
    monkeypatch.setattr(
        "app.modules.intent.execution.WorkspaceService.get_active_workspace",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.modules.intent.execution.IntentRepository.lock_intent",
        AsyncMock(return_value=row),
    )
    existing = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "app.modules.intent.execution.ExecutionRepository.existing", existing
    )
    plan = SimpleNamespace(model_dump=lambda **_: {"normalized": True})
    binding = SimpleNamespace(
        model_dump=lambda **_: {"network_id": str(row.network_id)}
    )
    snapshot = SimpleNamespace(
        model_dump=lambda **_: {"observed_at": "now", "run_id": "actual", "sequence": 3}
    )
    prepare = AsyncMock(return_value=(plan, binding, snapshot))
    monkeypatch.setattr("app.modules.intent.execution.prepare_plan", prepare)
    gate = AsyncMock()
    monkeypatch.setattr(SimulationStartService, "validate_execution_reference", gate)
    args = {
        "db": mock_db,
        "redis": fake_redis,
        "workspace_id": workspace_id,
        "intent_id": intent_id,
        "simulation_id": uuid.uuid4(),
        "idempotency_key": None,
        "correlation_id": uuid.uuid4(),
        "actor_id": str(uuid.uuid4()),
        "permissions": ["write:config", "execute:rollback"],
        "manual_approval": False,
        "cancel": False,
    }
    return SimpleNamespace(
        args=args,
        gate=gate,
        prepare=prepare,
        existing=existing,
        row=row,
        binding=binding,
        snapshot=snapshot,
    )


async def test_fresh_actual_snapshot_passed_to_gate_but_manual_approval_still_required(
    acceptance,
):
    ctx = acceptance
    with pytest.raises(HTTPException) as error:
        await accept_execution(**ctx.args)
    assert error.value.detail["code"] == "MANUAL_APPROVAL_REQUIRED"
    assert ctx.gate.await_args.kwargs[
        "network_state_sha256"
    ] == current_network_state_hash(binding=ctx.binding, snapshot=ctx.snapshot)
    ctx.prepare.assert_awaited_once()


async def test_stale_reference_checked_before_idempotent_replay(acceptance):
    ctx = acceptance
    ctx.row.status = "execution_completed"
    ctx.gate.side_effect = HTTPException(409, detail="stale provided reference")
    with pytest.raises(HTTPException) as error:
        await accept_execution(**{**ctx.args, "manual_approval": True})
    assert error.value.status_code == 409
    ctx.existing.assert_not_awaited()


async def test_missing_current_snapshot_rejects_instead_of_trusting_request_hash(
    acceptance,
):
    ctx = acceptance
    ctx.prepare.side_effect = ValueError("No fresh current snapshot")
    with pytest.raises(HTTPException) as error:
        await accept_execution(**{**ctx.args, "manual_approval": True})
    assert error.value.status_code == 409
    ctx.gate.assert_not_awaited()
    ctx.existing.assert_not_awaited()
