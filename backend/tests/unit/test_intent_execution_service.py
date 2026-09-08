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
    row.queue_status = "validated"
    row.stream_entry_id = None
    row.warning = None
    row.requested_by_user_id = str(uuid.uuid4())
    row.requested_at = datetime(2026, 8, 13, tzinfo=UTC)
    row.created_at = datetime(2026, 8, 13, tzinfo=UTC)
    row.updated_at = datetime(2026, 8, 13, tzinfo=UTC)
    return row


@pytest.mark.asyncio
async def test_execute_intent_fails_lifecycle_and_publishes_started_and_failed_events(
    mock_db,
    fake_redis,
):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    intent = _intent_record(workspace_id=workspace_id, intent_id=intent_id)

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key", new_callable=AsyncMock) as mock_by_key,
        patch("app.modules.intent.service.IntentRepository.get_by_id", new_callable=AsyncMock) as mock_by_id,
        patch("app.modules.intent.service.IntentRepository.update_status", new_callable=AsyncMock) as mock_update,
        patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_by_key.return_value = None
        mock_by_id.return_value = intent
        mock_publish.side_effect = ["3001-0", "3002-0"]

        async def _update_status_side_effect(target, **kwargs):
            if "status" in kwargs:
                target.status = kwargs["status"]
            if "queue_status" in kwargs and kwargs["queue_status"] is not None:
                target.queue_status = kwargs["queue_status"]
            if "stream_entry_id" in kwargs:
                target.stream_entry_id = kwargs["stream_entry_id"]
            if "warning" in kwargs:
                target.warning = kwargs["warning"]
            if "execution_provenance" in kwargs and kwargs["execution_provenance"] is not None:
                target.execution_provenance = kwargs["execution_provenance"]
            if "explainability" in kwargs and kwargs["explainability"] is not None:
                target.explainability = kwargs["explainability"]
            if "idempotency_key" in kwargs and kwargs["idempotency_key"] is not None:
                target.idempotency_key = kwargs["idempotency_key"]
            return target

        mock_update.side_effect = _update_status_side_effect

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        result = await svc.execute_intent(
            workspace_id=workspace_id,
            intent_id=intent_id,
            idempotency_key="idem-1",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
            requested_permissions=["write:config", "execute:rollback"],
        )

    assert result["status"] == "execution_failed"
    assert result["execution_provenance"]["verification"]["status"] == "not_performed"
    assert "rollback" not in result["execution_provenance"]
    assert result["queue_status"] == "queued"
    assert result["idempotent_replay"] is False
    assert result["stream_entry_id"] == "3002-0"
    assert result["warning"] is None
    mock_update.assert_awaited()
    assert mock_publish.await_count == 2
    assert mock_publish.await_args_list[0].kwargs["event_type"] == "intent.execution_started"
    assert mock_publish.await_args_list[0].kwargs["source"] == "intent"
    assert mock_publish.await_args_list[1].kwargs["event_type"] == "intent.execution_failed"
    assert mock_publish.await_args_list[1].kwargs["source"] == "intent"
    mock_db.refresh.assert_awaited_once_with(intent)
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_intent_publish_failure_marks_execution_failed_fail_open(
    mock_db,
    fake_redis,
):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    intent = _intent_record(workspace_id=workspace_id, intent_id=intent_id)

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key", new_callable=AsyncMock) as mock_by_key,
        patch("app.modules.intent.service.IntentRepository.get_by_id", new_callable=AsyncMock) as mock_by_id,
        patch("app.modules.intent.service.IntentRepository.update_status", new_callable=AsyncMock) as mock_update,
        patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_by_key.return_value = None
        mock_by_id.return_value = intent
        mock_publish.side_effect = ["3001-0", "3002-0"]

        async def _update_status_side_effect(target, **kwargs):
            if "status" in kwargs:
                target.status = kwargs["status"]
            if "queue_status" in kwargs and kwargs["queue_status"] is not None:
                target.queue_status = kwargs["queue_status"]
            if "stream_entry_id" in kwargs:
                target.stream_entry_id = kwargs["stream_entry_id"]
            if "warning" in kwargs:
                target.warning = kwargs["warning"]
            if "execution_provenance" in kwargs and kwargs["execution_provenance"] is not None:
                target.execution_provenance = kwargs["execution_provenance"]
            if "explainability" in kwargs and kwargs["explainability"] is not None:
                target.explainability = kwargs["explainability"]
            if "idempotency_key" in kwargs and kwargs["idempotency_key"] is not None:
                target.idempotency_key = kwargs["idempotency_key"]
            return target

        mock_update.side_effect = _update_status_side_effect

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        result = await svc.execute_intent(
            workspace_id=workspace_id,
            intent_id=intent_id,
            idempotency_key="idem-1",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
            requested_permissions=["write:config", "execute:rollback"],
        )

    assert result["status"] == "execution_failed"
    assert result["queue_status"] == "queued"
    assert result["stream_entry_id"] == "3002-0"
    assert result["warning"] is None
    assert mock_publish.await_count == 2
    assert mock_publish.await_args_list[0].kwargs["event_type"] == "intent.execution_started"
    assert mock_publish.await_args_list[1].kwargs["event_type"] == "intent.execution_failed"
    assert "rollback" not in result["execution_provenance"]
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_intent_idempotent_replay_returns_existing_result(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    intent = _intent_record(
        workspace_id=workspace_id,
        intent_id=intent_id,
        status="execution_started",
        idempotency_key="idem-1",
    )

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key", new_callable=AsyncMock) as mock_by_key,
        patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_by_key.return_value = intent

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        result = await svc.execute_intent(
            workspace_id=workspace_id,
            intent_id=intent_id,
            idempotency_key="idem-1",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
            requested_permissions=["write:config", "execute:rollback"],
        )

    assert result["status"] == "execution_started"
    assert result["idempotent_replay"] is True
    mock_publish.assert_not_awaited()
    mock_db.refresh.assert_awaited_once_with(intent)
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_intent_idempotent_replay_falls_back_confidence_band(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    intent = _intent_record(
        workspace_id=workspace_id,
        intent_id=intent_id,
        status="execution_completed",
        idempotency_key="idem-1",
    )
    intent.confidence_score = 0.91
    intent.confidence_band = None

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key", new_callable=AsyncMock) as mock_by_key,
        patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_by_key.return_value = intent

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        result = await svc.execute_intent(
            workspace_id=workspace_id,
            intent_id=intent_id,
            idempotency_key="idem-1",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
            requested_permissions=["write:config", "execute:rollback"],
        )

    assert result["status"] == "execution_failed"
    assert result["idempotent_replay"] is True
    assert result["confidence"]["score"] == 0.0
    assert result["confidence"]["band"] == "below_60"
    assert result["confidence"]["approval_required"] is True
    mock_publish.assert_not_awaited()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_intent_existing_validated_idempotency_key_proceeds_to_terminal_state(
    mock_db,
    fake_redis,
):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    intent = _intent_record(
        workspace_id=workspace_id,
        intent_id=intent_id,
        status="validated",
        idempotency_key="idem-1",
    )

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key", new_callable=AsyncMock) as mock_by_key,
        patch("app.modules.intent.service.IntentRepository.get_by_id", new_callable=AsyncMock) as mock_by_id,
        patch("app.modules.intent.service.IntentRepository.update_status", new_callable=AsyncMock) as mock_update,
        patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_by_key.return_value = intent
        mock_by_id.return_value = None
        mock_publish.side_effect = ["3002-0", "3003-0"]

        async def _update_status_side_effect(target, **kwargs):
            if "status" in kwargs:
                target.status = kwargs["status"]
            if "queue_status" in kwargs and kwargs["queue_status"] is not None:
                target.queue_status = kwargs["queue_status"]
            if "stream_entry_id" in kwargs:
                target.stream_entry_id = kwargs["stream_entry_id"]
            return target

        mock_update.side_effect = _update_status_side_effect

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        result = await svc.execute_intent(
            workspace_id=workspace_id,
            intent_id=intent_id,
            idempotency_key="idem-1",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
            requested_permissions=["write:config", "execute:rollback"],
        )

    assert result["status"] == "execution_failed"
    assert result["idempotent_replay"] is False
    assert result["stream_entry_id"] == "3003-0"
    assert mock_publish.await_count == 2


@pytest.mark.asyncio
async def test_execute_intent_started_event_publish_failure_remains_fail_open(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    intent = _intent_record(workspace_id=workspace_id, intent_id=intent_id)

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key", new_callable=AsyncMock) as mock_by_key,
        patch("app.modules.intent.service.IntentRepository.get_by_id", new_callable=AsyncMock) as mock_by_id,
        patch("app.modules.intent.service.IntentRepository.update_status", new_callable=AsyncMock) as mock_update,
        patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_by_key.return_value = None
        mock_by_id.return_value = intent
        mock_publish.side_effect = [RuntimeError("stream unavailable"), "3002-0"]

        async def _update_status_side_effect(target, **kwargs):
            if "status" in kwargs:
                target.status = kwargs["status"]
            if "queue_status" in kwargs and kwargs["queue_status"] is not None:
                target.queue_status = kwargs["queue_status"]
            if "stream_entry_id" in kwargs:
                target.stream_entry_id = kwargs["stream_entry_id"]
            if "warning" in kwargs:
                target.warning = kwargs["warning"]
            if "execution_provenance" in kwargs and kwargs["execution_provenance"] is not None:
                target.execution_provenance = kwargs["execution_provenance"]
            if "explainability" in kwargs and kwargs["explainability"] is not None:
                target.explainability = kwargs["explainability"]
            return target

        mock_update.side_effect = _update_status_side_effect

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        result = await svc.execute_intent(
            workspace_id=workspace_id,
            intent_id=intent_id,
            idempotency_key="idem-1",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
            requested_permissions=["write:config", "execute:rollback"],
        )

    assert result["status"] == "execution_failed"
    assert result["queue_status"] == "deferred"
    assert result["warning"] == "event_queue_unavailable"
    assert result["stream_entry_id"] == "3002-0"
    assert mock_publish.await_count == 2
    assert mock_publish.await_args_list[0].kwargs["event_type"] == "intent.execution_started"
    assert mock_publish.await_args_list[1].kwargs["event_type"] == "intent.execution_failed"


@pytest.mark.asyncio
async def test_execute_intent_denies_without_execute_rollback_permission(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    intent = _intent_record(workspace_id=workspace_id, intent_id=intent_id)

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key", new_callable=AsyncMock) as mock_by_key,
        patch("app.modules.intent.service.IntentRepository.get_by_id", new_callable=AsyncMock) as mock_by_id,
        patch("app.modules.intent.service.HypervisorExecutionService.execute") as mock_hypervisor_execute,
        patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_by_key.return_value = None
        mock_by_id.return_value = intent

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        with pytest.raises(HTTPException) as exc_info:
            await svc.execute_intent(
                workspace_id=workspace_id,
                intent_id=intent_id,
                idempotency_key="idem-1",
                correlation_id=str(uuid.uuid4()),
                requested_by_user_id=str(uuid.uuid4()),
                requested_permissions=["write:config"],
            )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "INTENT_EXECUTION_PERMISSION_DENIED"
    mock_hypervisor_execute.assert_not_called()
    mock_publish.assert_not_awaited()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_intent_raises_409_for_non_validated_state(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    intent = _intent_record(workspace_id=workspace_id, intent_id=intent_id, status="rejected")

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key", new_callable=AsyncMock) as mock_by_key,
        patch("app.modules.intent.service.IntentRepository.get_by_id", new_callable=AsyncMock) as mock_by_id,
    ):
        mock_by_key.return_value = None
        mock_by_id.return_value = intent

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        with pytest.raises(HTTPException) as exc_info:
            await svc.execute_intent(
                workspace_id=workspace_id,
                intent_id=intent_id,
                idempotency_key="idem-2",
                correlation_id=str(uuid.uuid4()),
                requested_by_user_id=str(uuid.uuid4()),
                requested_permissions=["write:config", "execute:rollback"],
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_execute_intent_raises_409_for_idempotency_conflict(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    other_intent_id = uuid.uuid4()
    existing = _intent_record(
        workspace_id=workspace_id,
        intent_id=other_intent_id,
        status="execution_started",
        idempotency_key="idem-1",
    )

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key", new_callable=AsyncMock) as mock_by_key,
    ):
        mock_by_key.return_value = existing

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        with pytest.raises(HTTPException) as exc_info:
            await svc.execute_intent(
                workspace_id=workspace_id,
                intent_id=intent_id,
                idempotency_key="idem-1",
                correlation_id=str(uuid.uuid4()),
                requested_by_user_id=str(uuid.uuid4()),
                requested_permissions=["write:config", "execute:rollback"],
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_execute_intent_raises_404_when_intent_missing(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    intent_id = uuid.uuid4()

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.IntentRepository.get_by_idempotency_key", new_callable=AsyncMock) as mock_by_key,
        patch("app.modules.intent.service.IntentRepository.get_by_id", new_callable=AsyncMock) as mock_by_id,
    ):
        mock_by_key.return_value = None
        mock_by_id.return_value = None

        svc = IntentExecutionService(db=mock_db, redis=fake_redis)
        with pytest.raises(HTTPException) as exc_info:
            await svc.execute_intent(
                workspace_id=workspace_id,
                intent_id=intent_id,
                idempotency_key="idem-1",
                correlation_id=str(uuid.uuid4()),
                requested_by_user_id=str(uuid.uuid4()),
                requested_permissions=["write:config", "execute:rollback"],
            )

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
    mock_db.refresh.assert_awaited_once_with(intent)


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
