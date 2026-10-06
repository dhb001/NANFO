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
        intent_kind="test",
        status="validated",
        idempotency_key=None,
        requested_by_user_id=str(uuid.uuid4()),
        queue_status="validated",
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


# ---- ADR-028 C18 / contract 3 / four-eyes regressions -------------------------------

import json  # noqa: E402

from app.modules.intent.execution import outbox_event_id, project_execution  # noqa: E402
from app.modules.intent.lab import LabIntent, digest  # noqa: E402
from tests.unit.test_intent_lab import mailbox_settings, payload  # noqa: E402,F401


@pytest.fixture
def lab_acceptance(acceptance, monkeypatch, mailbox_settings):  # noqa: F811 - imported pytest fixture
    """Acceptance with a real normalized plan; auth/observation are deterministic doubles."""
    ctx = acceptance
    plan = LabIntent.model_validate(payload()).normalize()
    binding = SimpleNamespace(topology_id="campus-small-v1", model_dump=lambda **_: {"binding": "trusted"})
    snapshot = SimpleNamespace(run_id=uuid.UUID(int=77), model_dump=lambda **_: {"run_id": str(uuid.UUID(int=77))})
    ctx.prepare.return_value = (plan, binding, snapshot)
    ctx.row.intent_payload, ctx.row.intent_kind = payload(), "reroute_path"
    ctx.row.validation_result, ctx.row.explainability, ctx.row.correlation_id = {}, {}, uuid.uuid4()
    monkeypatch.setattr("app.modules.intent.execution.get_settings", lambda: mailbox_settings)
    monkeypatch.setattr("app.modules.intent.execution.WorkspaceService.get_active_workspace",
                        AsyncMock(return_value=SimpleNamespace(org_id=uuid.UUID(int=5))))
    evidence = {"simulation_id": str(ctx.args["simulation_id"]), "plan_sha256": digest(plan.model_dump(mode="json"))}
    ctx.gate.return_value = evidence
    ctx.binding_value = {"plan_hash": digest(plan.model_dump(mode="json")), "binding_digest": digest({"binding": "trusted"}),
                         "run_id": str(uuid.UUID(int=77))}
    ctx.args.update(manual_approval=True, approval_binding=dict(ctx.binding_value))
    ctx.evidence = evidence
    return ctx


async def test_high_impact_manual_lab_action_requires_simulation(lab_acceptance):
    """Regression C18: simulation evidence was optional for high-impact lab actions."""
    ctx = lab_acceptance
    with pytest.raises(HTTPException) as error:
        await accept_execution(**{**ctx.args, "simulation_id": None})
    assert error.value.status_code == 409 and error.value.detail["code"] == "SIMULATION_REQUIRED"
    ctx.args["db"].commit.assert_not_awaited()


async def test_non_high_impact_lab_action_keeps_simulation_optional(lab_acceptance):
    ctx = lab_acceptance
    ctx.row.intent_payload = {**payload("shape"), "action": "throttle_qos"}
    ctx.row.intent_kind = "throttle_qos"
    intent, replay = await accept_execution(**{**ctx.args, "simulation_id": None})
    assert replay is False and intent.status == "execution_started"


@pytest.mark.parametrize("binding", [None, "plan_hash", "binding_digest", "run_id"])
async def test_manual_lab_execution_requires_current_approval_binding(lab_acceptance, binding):
    ctx = lab_acceptance
    supplied = None if binding is None else {**ctx.binding_value, binding: (
        str(uuid.uuid4()) if binding == "run_id" else "0" * 64)}
    with pytest.raises(HTTPException) as error:
        await accept_execution(**{**ctx.args, "approval_binding": supplied})
    assert error.value.status_code == 409 and error.value.detail["code"] == "APPROVAL_BINDING_MISMATCH"
    ctx.args["db"].add.assert_not_called()


async def test_requester_cannot_approve_own_manual_lab_change(lab_acceptance):
    ctx = lab_acceptance
    with pytest.raises(HTTPException) as error:
        await accept_execution(**{**ctx.args, "actor_id": ctx.row.requested_by_user_id})
    assert error.value.status_code == 409 and error.value.detail["code"] == "DISTINCT_APPROVER_REQUIRED"


async def test_distinct_approver_rule_is_configurable(lab_acceptance, monkeypatch):
    ctx = lab_acceptance
    monkeypatch.setattr("app.modules.intent.service.get_settings",
                        lambda: SimpleNamespace(INTENT_REQUIRE_DISTINCT_APPROVER=False))
    intent, replay = await accept_execution(**{**ctx.args, "actor_id": ctx.row.requested_by_user_id})
    assert replay is False and intent.status == "execution_started"


async def test_accepted_execution_binds_simulation_plan_and_deterministic_event(lab_acceptance):
    ctx = lab_acceptance
    ctx.row.queue_status = "deferred"  # validated event never confirmed: it must ride the outbox first
    ctx.row.validation_result, ctx.row.explainability = {"is_valid": True}, {"summary": "ok"}
    ctx.row.correlation_id = uuid.uuid4()
    intent, replay = await accept_execution(**ctx.args)
    added = [call.args[0] for call in ctx.args["db"].add.call_args_list]
    job, validated, started = added
    assert job.simulation_evidence == ctx.evidence and job.command["plan_hash"] == ctx.binding_value["plan_hash"]
    assert intent.execution_provenance["simulation_id"] == ctx.evidence["simulation_id"]
    assert intent.execution_provenance["simulation_evidence"] == ctx.evidence
    assert intent.idempotency_key == f"intent:{ctx.row.intent_id}" and intent.queue_status == "outbox_pending"
    assert validated.envelope["event_type"] == "intent.validated" and validated.sequence == 1
    assert validated.event_id == uuid.uuid5(ctx.row.intent_id, "intent.validated")
    assert started.sequence == 2 and started.event_id == outbox_event_id(job.execution_id, 2)
    event = json.loads(started.envelope["payload"])
    assert (event["phase"], event["sequence"], event["status"]) == ("accepted", 2, "execution_started")


async def test_cancelling_transition_has_distinct_phase_and_stable_event_id():
    """Regression: every blocking transition re-emitted execution_started with a fresh uuid4."""
    from datetime import UTC, datetime

    db = SimpleNamespace(added=[], add=lambda row: db.added.append(row))
    job = SimpleNamespace(execution_id=uuid.uuid4(), result=None, blocks_lab=True, phase="cancelling", command={},
        simulation_evidence=None, actor_id="a", approved_at=datetime.now(UTC), failure_reason=None,
        cancel_requested=True, cancelled_by_user_id="b", cancellation_requested_at=datetime.now(UTC),
        outbox_sequence=1, org_id=uuid.uuid4())
    intent = SimpleNamespace(intent_id=uuid.uuid4(), workspace_id=uuid.uuid4(), network_id=uuid.uuid4(),
        intent_kind="reroute_path", validation_result={}, explainability={}, correlation_id=uuid.uuid4())
    project_execution(intent, job, event=True, db=db)
    project_execution(intent, SimpleNamespace(**{**vars(job), "phase": "uncertain"}), event=True, db=db)
    first, second = db.added
    assert first.event_id == outbox_event_id(job.execution_id, 2) != second.event_id
    assert [json.loads(row.envelope["payload"])["phase"] for row in db.added] == ["cancelling", "uncertain"]
    assert {row.envelope["event_type"] for row in db.added} == {"intent.execution_started"}


async def test_replay_checks_supplied_binding_against_the_accepted_command(lab_acceptance):
    ctx = lab_acceptance
    accepted = SimpleNamespace(intent_id=ctx.row.intent_id, request_key=f"intent:{ctx.row.intent_id}",
        request_hash=None, simulation_evidence=ctx.evidence,
        command={"plan_hash": ctx.binding_value["plan_hash"], "binding_digest": ctx.binding_value["binding_digest"],
                 "run_id": ctx.binding_value["run_id"]})
    from app.modules.intent.lab import digest as lab_digest

    accepted.request_hash = lab_digest({"intent_id": str(ctx.row.intent_id), "workspace_id": str(ctx.row.workspace_id),
        "actor_id": ctx.args["actor_id"], "manual_approval": True, "intent": ctx.row.intent_payload,
        "simulation_id": str(ctx.args["simulation_id"])})
    ctx.existing.return_value = [accepted]
    _, replay = await accept_execution(**ctx.args)
    assert replay is True
    with pytest.raises(HTTPException) as error:
        await accept_execution(**{**ctx.args, "approval_binding": {**ctx.binding_value, "plan_hash": "f" * 64}})
    assert error.value.detail["code"] == "APPROVAL_BINDING_MISMATCH"


async def test_long_stored_dedup_key_is_the_execution_identity(lab_acceptance):
    """Migration 0030 renames duplicate keys to '<key>~dup~<intent_id>' (>120 chars possible)."""
    ctx = lab_acceptance
    ctx.row.idempotency_key = "k" * 120 + "~dup~" + str(ctx.row.intent_id)
    await accept_execution(**ctx.args)
    job = ctx.args["db"].add.call_args_list[0].args[0]
    assert job.request_key == ctx.row.idempotency_key
    with pytest.raises(HTTPException) as error:
        await accept_execution(**{**ctx.args, "idempotency_key": "x" * 121})
    assert error.value.status_code == 400 and error.value.detail["code"] == "IDEMPOTENCY_KEY_INVALID"
