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


def _sql(statement):
    from sqlalchemy.dialects import postgresql

    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_locked_lookup_serializes_executes(mock_db):
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=result)
    await IntentRepository(mock_db).get_by_id(uuid.uuid4(), lock=True)
    assert _sql(mock_db.execute.await_args.args[0]).rstrip().endswith("FOR UPDATE")
    await IntentRepository(mock_db).get_by_id(uuid.uuid4())
    assert "FOR UPDATE" not in _sql(mock_db.execute.await_args.args[0])


@pytest.mark.asyncio
async def test_idempotency_lookup_is_deterministic_even_with_legacy_duplicates(mock_db):
    """Regression C3: scalar_one_or_none on a non-unique key raised MultipleResultsFound."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=result)
    await IntentRepository(mock_db).get_by_idempotency_key(workspace_id=uuid.uuid4(), idempotency_key="k")
    sql = _sql(mock_db.execute.await_args.args[0])
    assert "ORDER BY intents.requested_at, intents.intent_id" in sql and "LIMIT" in sql


@pytest.mark.asyncio
async def test_claim_for_execution_is_a_conditional_status_transition(mock_db):
    mock_db.scalar = AsyncMock(return_value=None)
    assert await IntentRepository(mock_db).claim_for_execution(intent_id=uuid.uuid4(), workspace_id=uuid.uuid4()) is False
    sql = _sql(mock_db.scalar.await_args.args[0])
    assert sql.startswith("UPDATE intents SET status=")
    assert "intents.status = %(status_1)s" in sql and "RETURNING intents.intent_id" in sql
    mock_db.scalar = AsyncMock(return_value=uuid.uuid4())
    assert await IntentRepository(mock_db).claim_for_execution(intent_id=uuid.uuid4(), workspace_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_deferred_sweep_claims_aged_rows_skip_locked(mock_db):
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=result)
    assert await IntentRepository(mock_db).claim_deferred(limit=5, older_than_seconds=30) == []
    sql = _sql(mock_db.execute.await_args.args[0])
    assert "intents.queue_status = %(queue_status_1)s" in sql and "FOR UPDATE SKIP LOCKED" in sql
    assert "intents.stream_entry_id IS NULL" in sql
    assert "intents.updated_at < now() - %(now_1)s" in sql


# ADR-028: ExecutionRepository never commits; the worker owns each unit of work. ----------

@pytest.mark.asyncio
async def test_execution_claim_flushes_and_refreshes_without_committing(mock_db):
    from types import SimpleNamespace

    from app.modules.intent.repository import ExecutionRepository

    job = SimpleNamespace(lease_owner=None, fence=2, lease_until=None)
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=job)))
    assert await ExecutionRepository(mock_db).claim("owner", 15) is job
    assert job.lease_owner == "owner" and job.fence == 3
    mock_db.flush.assert_awaited_once()
    mock_db.refresh.assert_awaited_once_with(job)
    mock_db.commit.assert_not_awaited()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    assert await ExecutionRepository(mock_db).claim("owner", 15) is None
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("rowcount", [0, 1])
async def test_execution_renew_and_acknowledge_report_ownership_without_committing(mock_db, rowcount):
    from app.modules.intent.repository import ExecutionRepository

    mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=rowcount))
    repo = ExecutionRepository(mock_db)
    assert await repo.renew(uuid.uuid4(), "owner", 3, 15) is bool(rowcount)
    assert await repo.acknowledge_event(uuid.uuid4(), "owner") is bool(rowcount)
    mock_db.commit.assert_not_awaited()
    mock_db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbox_event_claim_leases_without_committing(mock_db):
    from types import SimpleNamespace

    from app.modules.intent.repository import ExecutionRepository

    row = SimpleNamespace(lease_owner=None, lease_until=None)
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=row)))
    assert await ExecutionRepository(mock_db).claim_event("publisher", 15) is row
    assert row.lease_owner == "publisher"
    mock_db.flush.assert_awaited_once()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_intent_outbox_retention_deletes_only_old_published_rows(mock_db):
    from datetime import timedelta

    from sqlalchemy.dialects import postgresql

    from app.modules.intent.repository import ExecutionRepository

    mock_db.scalar = AsyncMock(return_value=4)
    assert await ExecutionRepository(mock_db).purge_published_events(older_than=timedelta(days=30), limit=500) == 4
    sql = str(mock_db.scalar.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "DELETE FROM intent_outbox" in sql and "FOR UPDATE SKIP LOCKED" in sql
    assert "intent_outbox.published_at IS NOT NULL" in sql and "intent_outbox.published_at < now()" in sql
    assert "intent_executions" not in sql  # execution records are never deleted by outbox retention
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("days", "limit"), [(0, 10), (30, 0), (30, 10001), (30, True)])
async def test_intent_outbox_retention_rejects_unbounded_requests(mock_db, days, limit):
    from datetime import timedelta

    from app.modules.intent.repository import ExecutionRepository

    with pytest.raises(ValueError):
        await ExecutionRepository(mock_db).purge_published_events(older_than=timedelta(days=days), limit=limit)
