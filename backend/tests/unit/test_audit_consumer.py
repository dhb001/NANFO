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
        "event_id": str(uuid.uuid4()),
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
    assert append_kwargs["event_id"] == uuid.UUID(event["event_id"])
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
        "event_id": str(uuid.uuid4()),
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
        "event_id": str(uuid.uuid4()),
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
        "event_id": str(uuid.uuid4()),
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
        "event_id": str(uuid.uuid4()),
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


@pytest.mark.asyncio
async def test_audit_consumer_writes_topology_reconcile_completed_event():
    db = AsyncMock()
    db.commit = AsyncMock()

    network_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    payload = {
        "network_id": network_id,
        "status": "completed",
        "checked_nodes": 6,
        "checked_edges": 4,
    }
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "network.topology.reconcile_completed",
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
    assert append_kwargs["event_type"] == "network.topology.reconcile_completed"
    assert append_kwargs["resource_type"] == "network"
    assert append_kwargs["resource_id"] == uuid.UUID(network_id)
    assert append_kwargs["correlation_id"] == uuid.UUID(correlation_id)
    db.commit.assert_awaited_once()


def test_audit_handlers_include_topology_reconcile_events():
    assert "network.topology.reconcile_requested" in AUDIT_HANDLERS
    assert "network.topology.reconcile_completed" in AUDIT_HANDLERS
    assert "network.topology.reconcile_failed" in AUDIT_HANDLERS


@pytest.mark.asyncio
async def test_audit_consumer_writes_alert_acknowledged_event_with_actor_and_resource_id():
    db = AsyncMock()
    db.commit = AsyncMock()

    actor_id = str(uuid.uuid4())
    alert_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    payload = {
        "alert_id": alert_id,
        "acknowledged_by_user_id": actor_id,
        "status": "acknowledged",
    }
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "alert.acknowledged",
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
    assert append_kwargs["event_type"] == "alert.acknowledged"
    assert append_kwargs["resource_type"] == "alert"
    assert append_kwargs["actor_id"] == uuid.UUID(actor_id)
    assert append_kwargs["resource_id"] == uuid.UUID(alert_id)
    assert append_kwargs["correlation_id"] == uuid.UUID(correlation_id)
    db.commit.assert_awaited_once()


def test_audit_handlers_include_alert_lifecycle_events():
    assert "alert.generated" in AUDIT_HANDLERS
    assert "alert.acknowledged" in AUDIT_HANDLERS
    assert "alert.resolved" in AUDIT_HANDLERS


@pytest.mark.asyncio
async def test_audit_consumer_writes_plugin_enabled_event():
    db = AsyncMock()
    db.commit = AsyncMock()

    plugin_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    payload = {
        "plugin_id": plugin_id,
        "plugin_key": "safe-plugin",
        "status": "enabled",
    }
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "plugin.enabled",
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
    assert append_kwargs["event_type"] == "plugin.enabled"
    assert append_kwargs["resource_type"] == "plugin"
    assert append_kwargs["resource_id"] == uuid.UUID(plugin_id)
    assert append_kwargs["correlation_id"] == uuid.UUID(correlation_id)
    db.commit.assert_awaited_once()


def test_audit_handlers_include_plugin_lifecycle_events():
    assert "plugin.installed" in AUDIT_HANDLERS
    assert "plugin.enabled" in AUDIT_HANDLERS
    assert "plugin.disabled" in AUDIT_HANDLERS
    assert "plugin.failed" in AUDIT_HANDLERS


@pytest.mark.asyncio
async def test_audit_consumer_writes_report_generated_event():
    db = AsyncMock()
    db.commit = AsyncMock()

    report_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    payload = {
        "report_id": report_id,
        "report_type": "executive_summary",
        "status": "generated",
    }
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "report.generated",
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
    assert append_kwargs["event_type"] == "report.generated"
    assert append_kwargs["resource_type"] == "report"
    assert append_kwargs["resource_id"] == uuid.UUID(report_id)
    assert append_kwargs["correlation_id"] == uuid.UUID(correlation_id)
    db.commit.assert_awaited_once()


def test_audit_handlers_include_report_lifecycle_events():
    assert "report.requested" in AUDIT_HANDLERS
    assert "report.generated" in AUDIT_HANDLERS
    assert "report.failed" in AUDIT_HANDLERS


@pytest.mark.asyncio
async def test_audit_consumer_writes_org_workspace_and_org_lifecycle_events():
    db = AsyncMock()
    db.commit = AsyncMock()

    org_id = str(uuid.uuid4())
    workspace_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    payload = {
        "org_id": org_id,
        "workspace_id": workspace_id,
        "actor_id": str(uuid.uuid4()),
    }

    events = [
        {"event_type": "org.organization.updated", "correlation_id": correlation_id, "payload": payload},
        {"event_type": "org.organization.deleted", "correlation_id": correlation_id, "payload": payload},
        {"event_type": "org.workspace.updated", "correlation_id": correlation_id, "payload": payload},
        {"event_type": "org.workspace.deleted", "correlation_id": correlation_id, "payload": payload},
    ]

    repo = MagicMock()
    repo.append = AsyncMock()

    with (
        patch(
            "app.events.consumers.audit_consumer.AsyncSessionLocal",
            return_value=_session_context_manager(db),
        ),
        patch("app.events.consumers.audit_consumer.AuditLogRepository", return_value=repo),
    ):
        for event in events:
            event["event_id"] = str(uuid.uuid4())
            await handle_audit_event(event)

    assert repo.append.await_count == 4


def test_audit_handlers_include_org_update_delete_events():
    assert "org.organization.updated" in AUDIT_HANDLERS
    assert "org.organization.deleted" in AUDIT_HANDLERS
    assert "org.workspace.updated" in AUDIT_HANDLERS
    assert "org.workspace.deleted" in AUDIT_HANDLERS


@pytest.mark.asyncio
async def test_auth_audit_is_owned_by_direct_append_not_bus():
    with patch("app.events.consumers.audit_consumer.AsyncSessionLocal") as session:
        for event_type in ("auth.user.logged_in", "auth.user.login_failed",
                           "auth.user.logged_out", "auth.token.refreshed"):
            assert event_type not in AUDIT_HANDLERS
            await handle_audit_event({"event_type": event_type})
    session.assert_not_called()


@pytest.mark.asyncio
async def test_audit_rejects_missing_event_identity():
    with (
        patch("app.events.consumers.audit_consumer.AsyncSessionLocal", return_value=AsyncMock()),
        pytest.raises(KeyError),
    ):
        await handle_audit_event({"event_type": "intent.validated", "payload": {}})


@pytest.mark.asyncio
async def test_audit_commit_failure_propagates_to_bus():
    from sqlalchemy.exc import SQLAlchemyError

    db = AsyncMock()
    db.commit.side_effect = SQLAlchemyError("commit failed")
    with (
        patch("app.events.consumers.audit_consumer.AsyncSessionLocal", return_value=_session_context_manager(db)),
        patch("app.events.consumers.audit_consumer.AuditLogRepository") as repo,
        pytest.raises(SQLAlchemyError, match="commit failed"),
    ):
        repo.return_value.append = AsyncMock()
        await handle_audit_event({"event_type": "intent.validated", "event_id": str(uuid.uuid4()), "payload": {}})
