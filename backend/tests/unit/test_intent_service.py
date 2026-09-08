"""Unit tests for intent validation service baseline behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.intent.service import IntentValidationService


@pytest.mark.asyncio
async def test_validate_intent_valid_payload_persists_validated_state(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    network_id = uuid.uuid4()
    network = AsyncMock()
    network.network_id = network_id
    network.workspace_id = workspace_id

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_ws,
        patch("app.modules.intent.service.NetworkRepository.get_by_id", new_callable=AsyncMock) as mock_get_network,
        patch("app.modules.intent.service.IntentRepository.create", new_callable=AsyncMock) as mock_create,
    ):
        mock_ws.return_value = AsyncMock()
        mock_get_network.return_value = network
        persisted = AsyncMock()
        persisted.intent_id = uuid.uuid4()
        persisted.workspace_id = workspace_id
        persisted.network_id = network_id
        persisted.status = "validated"
        persisted.intent_kind = "reroute_path"
        persisted.idempotency_key = None
        persisted.correlation_id = uuid.uuid4()
        persisted.requested_at = datetime(2026, 8, 13, tzinfo=UTC)
        persisted.queue_status = "validated"
        persisted.stream_entry_id = None
        persisted.warning = None
        mock_create.return_value = persisted

        svc = IntentValidationService(db=mock_db, redis=fake_redis)
        result = await svc.validate_intent(
            workspace_id=workspace_id,
            network_id=network_id,
            intent_payload={
                "intent": {
                    "action": "reroute_path",
                    "scope": {"building": "A"},
                    "constraints": {"max_downtime": 0},
                }
            },
            idempotency_key=None,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["status"] == "validated"
    assert result["validation"]["is_valid"] is True
    assert result["validation"]["reasons"] == []
    assert result["validation"]["required_checks"] == [
        "simulation_before_deployment",
        "blast_radius_assessment",
    ]
    assert result["explainability"]["summary"] == "Intent passed baseline UNIL validation checks."
    assert result["explainability"]["evidence"] == [
        "BASELINE_SCHEMA_CHECKS_PASSED", "MODEL_CONFIDENCE_UNAVAILABLE", "DEPENDENCY_EVALUATOR_UNAVAILABLE",
    ]
    assert result["explainability"]["alternatives_considered"] == ["manual_review"]
    assert result["explainability"]["policy_reference"] == "ADR-008"
    assert result["confidence"]["approval_required"] is True
    assert result["queue_status"] == "validated"
    assert result["warning"] is None
    mock_ws.assert_awaited_once_with(
        workspace_id, user_id=mock_create.await_args.kwargs["requested_by_user_id"], require_write=True,
    )
    assert result["confidence"]["score"] == 0.0
    assert result["confidence"]["band"] == "below_60"
    mock_get_network.assert_awaited_once_with(network_id)
    mock_create.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_intent_publishes_validated_event_and_sets_stream_metadata(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    network_id = uuid.uuid4()
    network = AsyncMock()
    network.network_id = network_id
    network.workspace_id = workspace_id

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.NetworkRepository.get_by_id", new_callable=AsyncMock) as mock_get_network,
        patch("app.modules.intent.service.IntentRepository.create", new_callable=AsyncMock) as mock_create,
        patch("app.modules.intent.service.IntentRepository.update_status", new_callable=AsyncMock) as mock_update_status,
        patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get_network.return_value = network
        mock_publish.return_value = "3007-0"
        persisted = AsyncMock()
        persisted.intent_id = uuid.uuid4()
        persisted.workspace_id = workspace_id
        persisted.network_id = network_id
        persisted.status = "validated"
        persisted.intent_kind = "reroute_path"
        persisted.idempotency_key = None
        persisted.correlation_id = uuid.uuid4()
        persisted.requested_at = datetime(2026, 8, 13, tzinfo=UTC)
        persisted.queue_status = "validated"
        persisted.stream_entry_id = None
        persisted.warning = None
        mock_create.return_value = persisted

        async def _update_status_side_effect(target, **kwargs):
            if "status" in kwargs:
                target.status = kwargs["status"]
            if "queue_status" in kwargs and kwargs["queue_status"] is not None:
                target.queue_status = kwargs["queue_status"]
            if "stream_entry_id" in kwargs:
                target.stream_entry_id = kwargs["stream_entry_id"]
            if "warning" in kwargs:
                target.warning = kwargs["warning"]
            return target

        mock_update_status.side_effect = _update_status_side_effect

        svc = IntentValidationService(db=mock_db, redis=fake_redis)
        result = await svc.validate_intent(
            workspace_id=workspace_id,
            network_id=network_id,
            intent_payload={"intent": {"action": "reroute_path", "scope": {"building": "A"}}},
            idempotency_key=None,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["queue_status"] == "validated"
    assert result["stream_entry_id"] == "3007-0"
    assert result["warning"] is None
    assert mock_publish.await_args.kwargs["event_type"] == "intent.validated"
    assert mock_publish.await_args.kwargs["source"] == "intent"
    assert mock_publish.await_args.kwargs["payload"]["status"] == "validated"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_intent_publish_failure_is_fail_open_deferred(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    network_id = uuid.uuid4()
    network = AsyncMock()
    network.network_id = network_id
    network.workspace_id = workspace_id

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.NetworkRepository.get_by_id", new_callable=AsyncMock) as mock_get_network,
        patch("app.modules.intent.service.IntentRepository.create", new_callable=AsyncMock) as mock_create,
        patch("app.modules.intent.service.IntentRepository.update_status", new_callable=AsyncMock) as mock_update_status,
        patch("app.modules.intent.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get_network.return_value = network
        mock_publish.side_effect = RuntimeError("stream unavailable")
        persisted = AsyncMock()
        persisted.intent_id = uuid.uuid4()
        persisted.workspace_id = workspace_id
        persisted.network_id = network_id
        persisted.status = "validated"
        persisted.intent_kind = "reroute_path"
        persisted.idempotency_key = None
        persisted.correlation_id = uuid.uuid4()
        persisted.requested_at = datetime(2026, 8, 13, tzinfo=UTC)
        persisted.queue_status = "validated"
        persisted.stream_entry_id = None
        persisted.warning = None
        mock_create.return_value = persisted

        async def _update_status_side_effect(target, **kwargs):
            if "status" in kwargs:
                target.status = kwargs["status"]
            if "queue_status" in kwargs and kwargs["queue_status"] is not None:
                target.queue_status = kwargs["queue_status"]
            if "stream_entry_id" in kwargs:
                target.stream_entry_id = kwargs["stream_entry_id"]
            if "warning" in kwargs:
                target.warning = kwargs["warning"]
            return target

        mock_update_status.side_effect = _update_status_side_effect

        svc = IntentValidationService(db=mock_db, redis=fake_redis)
        result = await svc.validate_intent(
            workspace_id=workspace_id,
            network_id=network_id,
            intent_payload={"intent": {"action": "reroute_path", "scope": {"building": "A"}}},
            idempotency_key=None,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["queue_status"] == "deferred"
    assert result["stream_entry_id"] is None
    assert result["warning"] == "event_queue_unavailable"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_intent_invalid_payload_returns_explicit_reasons(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    network_id = uuid.uuid4()

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_ws,
        patch("app.modules.intent.service.NetworkRepository.get_by_id", new_callable=AsyncMock) as mock_get_network,
        patch("app.modules.intent.service.IntentRepository.create", new_callable=AsyncMock) as mock_create,
    ):
        mock_ws.return_value = AsyncMock()
        mock_get_network.return_value = None
        persisted = AsyncMock()
        persisted.intent_id = uuid.uuid4()
        persisted.workspace_id = workspace_id
        persisted.network_id = network_id
        persisted.status = "rejected"
        persisted.intent_kind = "unknown"
        persisted.idempotency_key = None
        persisted.correlation_id = uuid.uuid4()
        persisted.requested_at = datetime(2026, 8, 13, tzinfo=UTC)
        persisted.queue_status = "validated"
        persisted.stream_entry_id = None
        persisted.warning = None
        mock_create.return_value = persisted

        svc = IntentValidationService(db=mock_db, redis=fake_redis)
        result = await svc.validate_intent(
            workspace_id=workspace_id,
            network_id=network_id,
            intent_payload={"intent": {"scope": {}}},
            idempotency_key=None,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    reason_codes = {reason["code"] for reason in result["validation"]["reasons"]}
    assert result["status"] == "rejected"
    assert result["validation"]["is_valid"] is False
    assert "ACTION_REQUIRED" in reason_codes
    assert "SCOPE_REQUIRED" in reason_codes
    assert "NETWORK_NOT_FOUND" in reason_codes
    evidence_codes = set(result["explainability"]["evidence"])
    assert "ACTION_REQUIRED" in evidence_codes
    assert "SCOPE_REQUIRED" in evidence_codes
    assert "NETWORK_NOT_FOUND" in evidence_codes
    assert result["explainability"]["policy_reference"] == "ADR-008"
    assert result["confidence"]["score"] == 0.0
    assert result["confidence"]["band"] == "below_60"
    mock_create.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_validate_intent_persists_normalized_idempotency_key(mock_db, fake_redis):
    workspace_id = uuid.uuid4()
    network_id = uuid.uuid4()
    network = AsyncMock()
    network.network_id = network_id
    network.workspace_id = workspace_id

    with (
        patch("app.modules.intent.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock),
        patch("app.modules.intent.service.NetworkRepository.get_by_id", new_callable=AsyncMock) as mock_get_network,
        patch("app.modules.intent.service.IntentRepository.create", new_callable=AsyncMock) as mock_create,
    ):
        mock_get_network.return_value = network
        persisted = AsyncMock()
        persisted.intent_id = uuid.uuid4()
        persisted.workspace_id = workspace_id
        persisted.network_id = network_id
        persisted.status = "validated"
        persisted.intent_kind = "reroute_path"
        persisted.idempotency_key = "idem-1"
        persisted.correlation_id = uuid.uuid4()
        persisted.requested_at = datetime(2026, 8, 13, tzinfo=UTC)
        persisted.queue_status = "validated"
        persisted.stream_entry_id = None
        persisted.warning = None
        mock_create.return_value = persisted

        svc = IntentValidationService(db=mock_db, redis=fake_redis)
        await svc.validate_intent(
            workspace_id=workspace_id,
            network_id=network_id,
            intent_payload={"intent": {"action": "reroute_path", "scope": {"building": "A"}}},
            idempotency_key="  idem-1  ",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert mock_create.await_args.kwargs["idempotency_key"] == "idem-1"
