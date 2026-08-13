"""Unit tests for intent repository persistence behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.intent.models import Intent
from app.modules.intent.repository import IntentRepository


@pytest.mark.asyncio
async def test_create_adds_and_flushes_intent_record(mock_db):
    repo = IntentRepository(mock_db)
    now = datetime.now(UTC)

    intent = await repo.create(
        intent_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        network_id=uuid.uuid4(),
        intent_kind="routing_adjustment",
        intent_payload={"goal": "reduce latency"},
        status="validated",
        validation_result={"valid": True},
        execution_provenance={"workflow": "baseline"},
        explainability={"summary": "safe"},
        confidence_score=0.87,
        confidence_band="80-94",
        approval_required=True,
        idempotency_key="intent-123",
        correlation_id=uuid.uuid4(),
        queue_status="queued",
        stream_entry_id="2001-0",
        warning=None,
        requested_by_user_id=str(uuid.uuid4()),
        requested_at=now,
    )

    assert isinstance(intent, Intent)
    assert intent.status == "validated"
    assert intent.intent_payload["goal"] == "reduce latency"
    mock_db.add.assert_called_once_with(intent)
    mock_db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_by_id_executes_select_and_returns_row(mock_db):
    expected = MagicMock(spec=Intent)
    result = MagicMock()
    result.scalar_one_or_none.return_value = expected
    mock_db.execute = AsyncMock(return_value=result)

    repo = IntentRepository(mock_db)
    row = await repo.get_by_id(uuid.uuid4())

    assert row is expected
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_by_idempotency_key_executes_select(mock_db):
    expected = MagicMock(spec=Intent)
    result = MagicMock()
    result.scalar_one_or_none.return_value = expected
    mock_db.execute = AsyncMock(return_value=result)

    repo = IntentRepository(mock_db)
    row = await repo.get_by_idempotency_key(
        workspace_id=uuid.uuid4(),
        idempotency_key="intent-123",
    )

    assert row is expected
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_status_mutates_selected_fields_and_flushes(mock_db):
    repo = IntentRepository(mock_db)
    intent = Intent(
        intent_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        network_id=None,
        intent_kind="routing_adjustment",
        intent_payload={"goal": "reduce latency"},
        status="draft",
        validation_result={},
        execution_provenance={},
        explainability={},
        confidence_score=None,
        confidence_band=None,
        approval_required=True,
        idempotency_key=None,
        correlation_id=uuid.uuid4(),
        queue_status="pending",
        stream_entry_id="1001-0",
        warning="transient_warning",
        requested_by_user_id=str(uuid.uuid4()),
        requested_at=datetime.now(UTC),
    )

    updated = await repo.update_status(
        intent,
        status="execution_started",
        validation_result={"valid": True},
        execution_provenance={"step": "queued"},
        explainability={"summary": "meets policy"},
        confidence_score=0.91,
        confidence_band="80-94",
        approval_required=True,
        idempotency_key="intent-key",
        queue_status="queued",
        stream_entry_id=None,
        warning=None,
    )

    assert updated is intent
    assert intent.status == "execution_started"
    assert intent.validation_result == {"valid": True}
    assert intent.execution_provenance == {"step": "queued"}
    assert intent.explainability == {"summary": "meets policy"}
    assert intent.confidence_score == 0.91
    assert intent.confidence_band == "80-94"
    assert intent.approval_required is True
    assert intent.idempotency_key == "intent-key"
    assert intent.queue_status == "queued"
    assert intent.stream_entry_id is None
    assert intent.warning is None
    mock_db.flush.assert_awaited_once()
