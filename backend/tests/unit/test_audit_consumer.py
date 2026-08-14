"""Unit tests for audit event consumer mapping and fail-open UUID handling."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.events.consumers.audit_consumer import AUDIT_HANDLERS, handle_audit_event


def _session_context_manager(db: AsyncMock) -> AsyncMock:
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None
    return session_cm


@pytest.mark.asyncio
async def test_audit_consumer_writes_telemetry_sustained_failure_event():
    db = AsyncMock()
    db.commit = AsyncMock()

    correlation_id = str(uuid.uuid4())
    payload = {
        "exhausted_streak": 3,
        "sustained_failure_threshold": 3,
        "observed_at": "2026-08-10T00:00:00+00:00",
    }
    event = {
        "event_type": "telemetry.collector.sustained_failure_activated",
        "correlation_id": correlation_id,
        "payload": payload,
    }

    repo = MagicMock()
    repo.append = AsyncMock()

    with (
        patch(
            "app.events.consumers.audit_consumer.AsyncSessionLocal",
            return_value=_session_context_manager(db),
        ),
        patch("app.events.consumers.audit_consumer.AuditLogRepository", return_value=repo),
    ):
        await handle_audit_event(event)

    repo.append.assert_awaited_once()
    append_kwargs = repo.append.await_args.kwargs
    assert append_kwargs["event_type"] == "telemetry.collector.sustained_failure_activated"
    assert append_kwargs["actor_id"] is None
    assert append_kwargs["resource_type"] == "telemetry_collector"
    assert append_kwargs["resource_id"] is None
    assert append_kwargs["org_id"] is None
    assert append_kwargs["correlation_id"] == uuid.UUID(correlation_id)
    assert append_kwargs["metadata"] == payload
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_audit_consumer_ignores_unmapped_event_type():
    with (
        patch("app.events.consumers.audit_consumer.AsyncSessionLocal") as mock_session,
        patch("app.events.consumers.audit_consumer.AuditLogRepository") as mock_repo,
    ):
        await handle_audit_event({"event_type": "telemetry.collector.runtime_unknown", "payload": {}})

    mock_session.assert_not_called()
    mock_repo.assert_not_called()


@pytest.mark.asyncio
async def test_audit_consumer_handles_invalid_uuid_fields_fail_open():
    db = AsyncMock()
    db.commit = AsyncMock()

    payload = {
        "actor_id": "not-a-uuid",
        "device_id": "also-not-a-uuid",
        "org_id": "still-not-a-uuid",
        "exhausted_streak": 3,
    }
    event = {
        "event_type": "telemetry.collector.sustained_failure_recovered",
        "correlation_id": "invalid-correlation-id",
        "payload": payload,
    }

    repo = MagicMock()
    repo.append = AsyncMock()

    with (
        patch(
            "app.events.consumers.audit_consumer.AsyncSessionLocal",
            return_value=_session_context_manager(db),
        ),
        patch("app.events.consumers.audit_consumer.AuditLogRepository", return_value=repo),
    ):
        await handle_audit_event(event)

    append_kwargs = repo.append.await_args.kwargs
    assert append_kwargs["actor_id"] is None
    assert append_kwargs["resource_id"] is None
    assert append_kwargs["org_id"] is None
    assert isinstance(append_kwargs["correlation_id"], uuid.UUID)
    db.commit.assert_awaited_once()


def test_audit_handlers_include_telemetry_sustained_failure_events():
    assert "telemetry.collector.sustained_failure_activated" in AUDIT_HANDLERS
    assert "telemetry.collector.sustained_failure_recovered" in AUDIT_HANDLERS
    assert AUDIT_HANDLERS["telemetry.collector.sustained_failure_activated"] is handle_audit_event
    assert AUDIT_HANDLERS["telemetry.collector.sustained_failure_recovered"] is handle_audit_event


@pytest.mark.asyncio
async def test_audit_consumer_writes_simulation_branch_created_event():
    db = AsyncMock()
    db.commit = AsyncMock()

    simulation_id = str(uuid.uuid4())
    parent_simulation_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    payload = {
        "simulation_id": simulation_id,
        "parent_simulation_id": parent_simulation_id,
        "network_id": str(uuid.uuid4()),
    }
    event = {
        "event_type": "simulation.branch_created",
        "correlation_id": correlation_id,
        "payload": payload,
    }

    repo = MagicMock()
    repo.append = AsyncMock()

    with (
        patch(
            "app.events.consumers.audit_consumer.AsyncSessionLocal",
            return_value=_session_context_manager(db),
        ),
        patch("app.events.consumers.audit_consumer.AuditLogRepository", return_value=repo),
    ):
        await handle_audit_event(event)

    append_kwargs = repo.append.await_args.kwargs
    assert append_kwargs["event_type"] == "simulation.branch_created"
    assert append_kwargs["resource_type"] == "simulation"
    assert append_kwargs["resource_id"] == uuid.UUID(simulation_id)
    assert append_kwargs["correlation_id"] == uuid.UUID(correlation_id)
    db.commit.assert_awaited_once()


def test_audit_handlers_include_simulation_lifecycle_events():
    assert "simulation.started" in AUDIT_HANDLERS
    assert "simulation.completed" in AUDIT_HANDLERS
    assert "simulation.paused" in AUDIT_HANDLERS
    assert "simulation.cancelled" in AUDIT_HANDLERS
    assert "simulation.branch_created" in AUDIT_HANDLERS


@pytest.mark.asyncio
async def test_audit_consumer_writes_intent_execution_started_event():
    db = AsyncMock()
    db.commit = AsyncMock()

    intent_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    payload = {
        "intent_id": intent_id,
        "workspace_id": str(uuid.uuid4()),
        "status": "execution_started",
    }
    event = {
        "event_type": "intent.execution_started",
        "correlation_id": correlation_id,
        "payload": payload,
    }

    repo = MagicMock()
    repo.append = AsyncMock()

    with (
        patch(
            "app.events.consumers.audit_consumer.AsyncSessionLocal",
            return_value=_session_context_manager(db),
        ),
        patch("app.events.consumers.audit_consumer.AuditLogRepository", return_value=repo),
    ):
        await handle_audit_event(event)

    append_kwargs = repo.append.await_args.kwargs
    assert append_kwargs["event_type"] == "intent.execution_started"
    assert append_kwargs["resource_type"] == "intent"
    assert append_kwargs["resource_id"] == uuid.UUID(intent_id)
    assert append_kwargs["correlation_id"] == uuid.UUID(correlation_id)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_audit_consumer_writes_intent_execution_failed_with_rollback_metadata():
    db = AsyncMock()
    db.commit = AsyncMock()

    intent_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    payload = {
        "intent_id": intent_id,
        "workspace_id": str(uuid.uuid4()),
        "status": "execution_failed",
        "execution_provenance": {
            "verification": {"status": "failed"},
            "rollback": {"attempted": True, "status": "completed"},
        },
    }
    event = {
        "event_type": "intent.execution_failed",
        "correlation_id": correlation_id,
        "payload": payload,
    }

    repo = MagicMock()
    repo.append = AsyncMock()

    with (
        patch(
            "app.events.consumers.audit_consumer.AsyncSessionLocal",
            return_value=_session_context_manager(db),
        ),
        patch("app.events.consumers.audit_consumer.AuditLogRepository", return_value=repo),
    ):
        await handle_audit_event(event)

    append_kwargs = repo.append.await_args.kwargs
    assert append_kwargs["event_type"] == "intent.execution_failed"
    assert append_kwargs["resource_type"] == "intent"
    assert append_kwargs["resource_id"] == uuid.UUID(intent_id)
    assert append_kwargs["metadata"]["execution_provenance"]["rollback"]["status"] == "completed"
    db.commit.assert_awaited_once()


def test_audit_handlers_include_intent_lifecycle_events():
    assert "intent.validated" in AUDIT_HANDLERS
    assert "intent.execution_started" in AUDIT_HANDLERS
    assert "intent.execution_completed" in AUDIT_HANDLERS
    assert "intent.execution_failed" in AUDIT_HANDLERS
