"""NANFO Backend — Audit Log event consumer.

Consumes auth.*, network.*, org.*, and selected telemetry collector
runtime transition events, then writes to the audit_logs table.
Owned by Identity module (audit_logs is an Identity module table).
Idempotency is handled by the event bus consumer loop via event_id dedup.
"""

from __future__ import annotations

import uuid

from app.core.logging import get_logger
from app.db.postgres import AsyncSessionLocal
from app.modules.identity.repository import AuditLogRepository

logger = get_logger(__name__)

# Event types to audit and their resource_type labels
_AUDIT_MAP: dict[str, dict] = {
    "auth.user.logged_in":   {"resource_type": "user"},
    "auth.user.login_failed": {"resource_type": "user"},
    "auth.user.logged_out":   {"resource_type": "user"},
    "auth.token.refreshed":   {"resource_type": "user"},
    "intent.validated":        {"resource_type": "intent"},
    "intent.execution_started": {"resource_type": "intent"},
    "intent.execution_completed": {"resource_type": "intent"},
    "intent.execution_failed": {"resource_type": "intent"},
    "network.network.created": {"resource_type": "network"},
    "simulation.started":       {"resource_type": "simulation"},
    "simulation.completed":     {"resource_type": "simulation"},
    "simulation.paused":        {"resource_type": "simulation"},
    "simulation.cancelled":     {"resource_type": "simulation"},
    "simulation.branch_created": {"resource_type": "simulation"},
    "network.device.added":    {"resource_type": "device"},
    "network.device.updated":  {"resource_type": "device"},
    "network.device.deleted":  {"resource_type": "device"},
    "network.topology.reconcile_requested": {"resource_type": "network"},
    "network.topology.reconcile_completed": {"resource_type": "network"},
    "network.topology.reconcile_failed": {"resource_type": "network"},
    "org.organization.created": {"resource_type": "organization"},
    "org.workspace.created":    {"resource_type": "workspace"},
    "org.member.added":         {"resource_type": "org_member"},
    "org.member.removed":       {"resource_type": "org_member"},
    "telemetry.collector.sustained_failure_activated": {"resource_type": "telemetry_collector"},
    "telemetry.collector.sustained_failure_recovered": {"resource_type": "telemetry_collector"},
    "alert.generated": {"resource_type": "alert"},
    "alert.acknowledged": {"resource_type": "alert"},
    "alert.resolved": {"resource_type": "alert"},
}


async def handle_audit_event(event: dict) -> None:
    """Write an audit log entry for any mapped event type."""
    event_type = event.get("event_type", "")
    config = _AUDIT_MAP.get(event_type)
    if config is None:
        return

    payload_raw = event.get("payload")
    payload = payload_raw if isinstance(payload_raw, dict) else {}
    correlation_id_raw = event.get("correlation_id", str(uuid.uuid4()))
    try:
        correlation_id = uuid.UUID(str(correlation_id_raw))
    except (ValueError, TypeError, AttributeError):
        correlation_id = uuid.uuid4()

    actor_id_raw = (
        payload.get("user_id")
        or payload.get("actor_id")
        or payload.get("requested_by_user_id")
        or payload.get("acknowledged_by_user_id")
        or payload.get("resolved_by_user_id")
    )
    try:
        actor_id = uuid.UUID(str(actor_id_raw)) if actor_id_raw else None
    except (ValueError, TypeError, AttributeError):
        actor_id = None

    resource_id_raw = (
        payload.get("alert_id")
        or payload.get("alertId")
        or payload.get("intent_id")
        or payload.get("simulation_id")
        or payload.get("parent_simulation_id")
        or payload.get("device_id")
        or payload.get("network_id")
        or payload.get("org_id")
        or payload.get("workspace_id")
    )
    try:
        resource_id = uuid.UUID(str(resource_id_raw)) if resource_id_raw else None
    except (ValueError, TypeError, AttributeError):
        resource_id = None

    org_id_raw = payload.get("org_id")
    try:
        org_id = uuid.UUID(str(org_id_raw)) if org_id_raw else None
    except (ValueError, TypeError, AttributeError):
        org_id = None

    async with AsyncSessionLocal() as db:
        repo = AuditLogRepository(db)
        await repo.append(
            event_type=event_type,
            actor_id=actor_id,
            resource_type=config["resource_type"],
            resource_id=resource_id,
            org_id=org_id,
            correlation_id=correlation_id,
            metadata=payload,
        )
        await db.commit()

    logger.info("audit_log_written", event_type=event_type, correlation_id=str(correlation_id))


# Handler registry for the event bus consumer loop
AUDIT_HANDLERS: dict[str, object] = {event_type: handle_audit_event for event_type in _AUDIT_MAP}
