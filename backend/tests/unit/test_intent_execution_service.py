"""Unit tests for intent execution/read service baseline behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.intent.service import IntentExecutionService


def _intent_record(
    *,
    workspace_id: uuid.UUID,
    intent_id: uuid.UUID,
    status: str = "validated",
    idempotency_key: str | None = None,
    queue_status: str = "validated",
):
    row = AsyncMock()
    row.intent_id = intent_id
    row.workspace_id = workspace_id
    row.network_id = uuid.uuid4()
    row.intent_kind = "reroute_path"
    row.intent_payload = {"action": "reroute_path", "scope": {"building": "A"}}
    row.status = status
    row.validation_result = {"is_valid": True}
    row.execution_provenance = {"pipeline_stage": "intent_validated"}
    row.explainability = {"summary": "ok"}
    row.confidence_score = 0.84
    row.confidence_band = "80-94"
    row.approval_required = True
    row.idempotency_key = idempotency_key
    row.correlation_id = uuid.uuid4()
    row.queue_status = queue_status
    row.stream_entry_id = None
    row.warning = None
    row.requested_by_user_id = str(uuid.uuid4())
    row.requested_at = datetime(2026, 8, 13, tzinfo=UTC)
    row.created_at = datetime(2026, 8, 13, tzinfo=UTC)
    row.updated_at = datetime(2026, 8, 13, tzinfo=UTC)
    return row


async def _apply(target, **kwargs):
    for key, value in kwargs.items():
        if value is not None or key in {"stream_entry_id", "warning", "idempotency_key"}:
            setattr(target, key, value)
    return target


class Legacy:
    """Patched repository/publisher around the fail-closed (no controller) path."""

    def __init__(self, mock_db, fake_redis, intent, *, claimed=True, owner=None):
        self.intent, self.db = intent, mock_db
        self.operations = []
        mock_db.commit.side_effect = lambda: self.operations.append("commit")
        self.patches = [
            patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
            patch("app.modules.intent.service.IntentRepository.get_by_id", new=AsyncMock(return_value=intent)),
            patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key",
                  new=AsyncMock(return_value=owner)),
            patch("app.modules.intent.service.IntentRepository.claim_for_execution",
                  new=AsyncMock(return_value=claimed)),
            patch("app.modules.intent.service.IntentRepository.update_status", new=AsyncMock(side_effect=_apply)),
            patch("app.modules.intent.service.publish_event", new_callable=AsyncMock),
        ]
        self.service = IntentExecutionService(db=mock_db, redis=fake_redis)

    def __enter__(self):
        mocks = [item.start() for item in self.patches]
        self.ws, self.by_id, self.by_key, self.claim, self.update, self.publish = mocks
        self.publish.side_effect = self._publish
        self.fail_on = set()
        return self

    async def _publish(self, **kwargs):
        self.operations.append(("publish", kwargs["event_type"]))
        if kwargs["event_type"] in self.fail_on:
            raise RuntimeError("stream unavailable")
        return f"{len(self.operations)}-0"

    def __exit__(self, *exc):
        for item in self.patches:
            item.stop()

    async def execute(self, key="idem-1", **kwargs):
        return await self.service.execute_intent(
            workspace_id=self.intent.workspace_id, intent_id=self.intent.intent_id, idempotency_key=key,
            correlation_id=str(uuid.uuid4()), requested_by_user_id=str(uuid.uuid4()),
            requested_permissions=["write:config", "execute:rollback"], **kwargs)


def _new(**kwargs):
    return _intent_record(workspace_id=uuid.uuid4(), intent_id=uuid.uuid4(), **kwargs)


@pytest.mark.asyncio
async def test_execute_intent_fails_lifecycle_and_publishes_started_and_failed_events(mock_db, fake_redis):
    intent = _new()
    with Legacy(mock_db, fake_redis, intent) as ctx:
        result = await ctx.execute()

    assert result["status"] == "execution_failed"
    assert result["execution_provenance"]["verification"]["status"] == "not_performed"
    assert "rollback" not in result["execution_provenance"]
    assert result["queue_status"] == "queued"
    assert result["idempotent_replay"] is False
    assert result["warning"] is None
    # Regression (ADR-028): commit strictly precedes publication; ids are stable.
    assert ctx.operations == ["commit", ("publish", "intent.execution_started"),
                              ("publish", "intent.execution_failed"), "commit"]
    assert result["stream_entry_id"] == "3-0"
    assert [call.kwargs["event_id"] for call in ctx.publish.await_args_list] == [
        str(uuid.uuid5(intent.intent_id, "intent.execution_started")),
        str(uuid.uuid5(intent.intent_id, "intent.execution_failed"))]
    started = ctx.publish.await_args_list[0].kwargs["payload"]
    assert started["status"] == "execution_started"
    assert started["execution_provenance"]["pipeline_stage"] == "execution_started"
    assert "failure_reason" not in started["execution_provenance"]
    ctx.by_id.assert_awaited_once_with(intent.intent_id, lock=True)
    ctx.claim.assert_awaited_once_with(intent_id=intent.intent_id, workspace_id=intent.workspace_id)
    mock_db.refresh.assert_awaited_once_with(intent)


@pytest.mark.asyncio
async def test_execute_intent_terminal_publish_failure_stays_deferred(mock_db, fake_redis):
    intent = _new()
    with Legacy(mock_db, fake_redis, intent) as ctx:
        ctx.fail_on = {"intent.execution_failed"}
        result = await ctx.execute()
    assert result["status"] == "execution_failed"
    assert (result["queue_status"], result["warning"], result["stream_entry_id"]) == (
        "deferred", "event_queue_unavailable", None)
    assert ctx.operations == ["commit", ("publish", "intent.execution_started"),
                              ("publish", "intent.execution_failed")]


@pytest.mark.asyncio
async def test_execute_intent_started_publish_failure_never_publishes_terminal_out_of_order(mock_db, fake_redis):
    intent = _new()
    with Legacy(mock_db, fake_redis, intent) as ctx:
        ctx.fail_on = {"intent.execution_started"}
        result = await ctx.execute()
    assert result["status"] == "execution_failed"
    assert (result["queue_status"], result["warning"]) == ("deferred", "event_queue_unavailable")
    # The sweep republishes started then failed later, in order.
    assert ctx.operations == ["commit", ("publish", "intent.execution_started")]


@pytest.mark.asyncio
async def test_execute_publishes_pending_validated_event_first(mock_db, fake_redis):
    intent = _new(queue_status="deferred")
    with Legacy(mock_db, fake_redis, intent) as ctx:
        await ctx.execute()
    assert [op[1] for op in ctx.operations if isinstance(op, tuple)] == [
        "intent.validated", "intent.execution_started", "intent.execution_failed"]


@pytest.mark.asyncio
async def test_concurrent_execute_losing_the_conditional_update_cannot_transition(mock_db, fake_redis):
    """Regression C3: both concurrent legacy executes used to transition and publish."""
    intent = _new()
    with Legacy(mock_db, fake_redis, intent, claimed=False) as ctx:
        with pytest.raises(HTTPException) as err:
            await ctx.execute()
    assert err.value.status_code == 409 and err.value.detail["code"] == "INTENT_ALREADY_EXECUTING"
    ctx.update.assert_not_awaited()
    ctx.publish.assert_not_awaited()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_intent_idempotent_replay_returns_existing_result(mock_db, fake_redis):
    intent = _new(status="execution_started", idempotency_key="idem-1")
    with Legacy(mock_db, fake_redis, intent) as ctx:
        result = await ctx.execute("idem-1")
    assert result["status"] == "execution_started"
    assert result["idempotent_replay"] is True
    ctx.publish.assert_not_awaited()
    ctx.claim.assert_not_awaited()
    mock_db.refresh.assert_awaited_once_with(intent)
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_without_key_replays_with_the_intents_stored_key(mock_db, fake_redis):
    intent = _new(status="execution_failed", idempotency_key="validate-key")
    with Legacy(mock_db, fake_redis, intent) as ctx:
        result = await ctx.execute(None)
    assert result["idempotent_replay"] is True and result["idempotency_key"] == "validate-key"
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_intent_idempotent_replay_falls_back_confidence_band(mock_db, fake_redis):
    intent = _new(status="execution_completed", idempotency_key="idem-1")
    intent.confidence_score = 0.91
    intent.confidence_band = None
    with Legacy(mock_db, fake_redis, intent) as ctx:
        result = await ctx.execute("idem-1")
    assert result["status"] == "execution_failed"
    assert result["idempotent_replay"] is True
    assert result["confidence"] == {"score": 0.0, "band": "below_60", "approval_required": True}
    ctx.publish.assert_not_awaited()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_uses_stored_validate_key_and_never_overwrites_it(mock_db, fake_redis):
    intent = _new(idempotency_key="validate-key")
    with Legacy(mock_db, fake_redis, intent) as ctx:
        result = await ctx.execute("validate-key")
        assert "idempotency_key" not in ctx.update.await_args_list[0].kwargs
    assert result["status"] == "execution_failed" and result["idempotency_key"] == "validate-key"


@pytest.mark.asyncio
async def test_execute_without_stored_key_adopts_supplied_key(mock_db, fake_redis):
    intent = _new()
    with Legacy(mock_db, fake_redis, intent) as ctx:
        await ctx.execute("exec-key")
        assert ctx.update.await_args_list[0].kwargs["idempotency_key"] == "exec-key"
    assert intent.idempotency_key == "exec-key"


@pytest.mark.asyncio
async def test_execute_with_a_key_other_than_the_stored_key_is_409(mock_db, fake_redis):
    intent = _new(idempotency_key="validate-key")
    with Legacy(mock_db, fake_redis, intent) as ctx:
        with pytest.raises(HTTPException) as err:
            await ctx.execute("fresh-execute-key")
    assert err.value.status_code == 409 and err.value.detail["code"] == "INTENT_IDEMPOTENCY_CONFLICT"
    ctx.claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_intent_denies_without_execute_rollback_permission(mock_db, fake_redis):
    intent = _new()
    with Legacy(mock_db, fake_redis, intent) as ctx, patch(
        "app.modules.intent.service.HypervisorExecutionService.execute"
    ) as hypervisor:
        with pytest.raises(HTTPException) as exc_info:
            await ctx.service.execute_intent(
                workspace_id=intent.workspace_id, intent_id=intent.intent_id, idempotency_key="idem-1",
                correlation_id=str(uuid.uuid4()), requested_by_user_id=str(uuid.uuid4()),
                requested_permissions=["write:config"])
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "INTENT_EXECUTION_PERMISSION_DENIED"
    hypervisor.assert_not_called()
    ctx.publish.assert_not_awaited()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_intent_raises_409_for_non_validated_state(mock_db, fake_redis):
    intent = _new(status="rejected")
    with Legacy(mock_db, fake_redis, intent) as ctx:
        with pytest.raises(HTTPException) as exc_info:
            await ctx.execute("idem-2")
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "INTENT_NOT_EXECUTABLE"


@pytest.mark.asyncio
async def test_execute_intent_raises_409_for_idempotency_conflict(mock_db, fake_redis):
    intent = _new()
    other = _intent_record(workspace_id=intent.workspace_id, intent_id=uuid.uuid4(), status="execution_started",
                           idempotency_key="idem-1")
    with Legacy(mock_db, fake_redis, intent, owner=other) as ctx:
        with pytest.raises(HTTPException) as exc_info:
            await ctx.execute("idem-1")
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "INTENT_IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_execute_intent_raises_404_when_intent_missing(mock_db, fake_redis):
    intent = _new()
    with Legacy(mock_db, fake_redis, intent) as ctx:
        ctx.by_id.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await ctx.execute()
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_intent_detail_returns_record_for_workspace(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    intent = _intent_record(workspace_id=workspace_id, intent_id=intent_id)

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_id", new_callable=AsyncMock) as mock_by_id,
    ):
        mock_by_id.return_value = intent

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        result = await svc.get_intent_detail(
            user_id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            intent_id=intent_id,
        )

    assert result["intent_id"] == str(intent_id)
    assert result["workspace_id"] == str(workspace_id)
    assert result["status"] == "validated"
    assert result["confidence"]["approval_required"] is True
    assert result["approval_binding"] is None and result["simulation_action_binding"] is None
    mock_db.refresh.assert_awaited_once_with(intent)


@pytest.mark.asyncio
async def test_detail_exposes_validate_time_then_executed_approval_binding(mock_db, fake_redis):
    intent = _new()
    validate_binding = {"plan_hash": "a" * 64, "binding_digest": "b" * 64, "run_id": str(uuid.UUID(int=1))}
    action = {"intent_id": str(intent.intent_id), "plan_sha256": "a" * 64, "network_state_sha256": "c" * 64}
    intent.validation_result = {"validation_kind": "manual_lab_plan", "approval_binding": validate_binding,
                                "simulation_action_binding": action}
    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_id", new=AsyncMock(return_value=intent)),
    ):
        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        detail = await svc.get_intent_detail(user_id="u", workspace_id=intent.workspace_id, intent_id=intent.intent_id)
        assert detail["approval_binding"] == validate_binding
        assert detail["simulation_action_binding"] == action
        executed = {"plan_hash": "d" * 64, "binding_digest": "e" * 64, "run_id": str(uuid.UUID(int=2))}
        intent.execution_provenance = {"execution_id": str(uuid.uuid4()), **executed}
        detail = await svc.get_intent_detail(user_id="u", workspace_id=intent.workspace_id, intent_id=intent.intent_id)
        assert detail["approval_binding"] == executed  # the durable approved identity wins
        intent.execution_provenance = {"execution_id": "x", "plan_hash": "not-a-digest", "binding_digest": "e",
                                       "run_id": "r"}
        intent.validation_result = {}
        detail = await svc.get_intent_detail(user_id="u", workspace_id=intent.workspace_id, intent_id=intent.intent_id)
        assert detail["approval_binding"] is None  # malformed historical values never 500


@pytest.mark.asyncio
async def test_get_intent_detail_falls_back_for_missing_metadata(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    intent = _intent_record(workspace_id=workspace_id, intent_id=intent_id)
    intent.validation_result = "not-a-dict"
    intent.execution_provenance = None
    intent.explainability = "not-a-dict"
    intent.confidence_score = None
    intent.confidence_band = None
    intent.approval_required = False

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_id", new_callable=AsyncMock) as mock_by_id,
    ):
        mock_by_id.return_value = intent

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        result = await svc.get_intent_detail(
            user_id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            intent_id=intent_id,
        )

    assert result["validation_result"]["model_evidence"] == "unavailable"
    assert result["execution_provenance"] == {}
    assert "unavailable" in result["explainability"]["model_confidence"]
    assert result["confidence"]["score"] == 0.0
    assert result["confidence"]["band"] == "below_60"
    assert result["confidence"]["approval_required"] is True


@pytest.mark.asyncio
async def test_get_intent_detail_raises_404_for_workspace_mismatch(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    other_workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    intent = _intent_record(workspace_id=other_workspace_id, intent_id=intent_id)

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_id", new_callable=AsyncMock) as mock_by_id,
    ):
        mock_by_id.return_value = intent

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        with pytest.raises(HTTPException) as exc_info:
            await svc.get_intent_detail(
                user_id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                intent_id=intent_id,
            )

    assert exc_info.value.status_code == 404
