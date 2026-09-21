"""NANFO Backend — Audit Log event consumer.

Consumes network.*, org.*, and selected telemetry collector
runtime transition events, then writes to the audit_logs table.
Owned by Identity module (audit_logs is an Identity module table).
Identity persists event_id atomically with the audit row for durable replay safety.
AuthService already appends auth audits synchronously; do not append them again.
"""

from __future__ import annotations

import uuid

from app.core.logging import get_logger
from app.db.postgres import AsyncSessionLocal
from app.modules.identity.repository import AuditLogRepository
from app.modules.identity.service import normalize_audit_correlation

logger = get_logger(__name__)

# Event types to audit and their resource_type labels
_AUDIT_MAP: dict[str, dict] = {
    "intent.validated":        {"resource_type": "intent"},
    "intent.execution_started": {"resource_type": "intent"},
    "intent.execution_completed": {"resource_type": "intent"},
    "intent.execution_failed": {"resource_type": "intent"},
    "network.network.created": {"resource_type": "network"},
    "network.network.updated": {"resource_type": "network"},
    "network.network.deleted": {"resource_type": "network"},
    "simulation.started":       {"resource_type": "simulation"},
    "simulation.completed":     {"resource_type": "simulation"},
    "simulation.paused":        {"resource_type": "simulation"},
    "simulation.cancelled":     {"resource_type": "simulation"},
    "simulation.branch_created": {"resource_type": "simulation"},
    "plugin.installed": {"resource_type": "plugin"},
    "plugin.enabled": {"resource_type": "plugin"},
    "plugin.disabled": {"resource_type": "plugin"},
    "plugin.failed": {"resource_type": "plugin"},
    "report.requested": {"resource_type": "report"},
    "report.generated": {"resource_type": "report"},
    "report.failed": {"resource_type": "report"},
    "network.device.added":    {"resource_type": "device"},
    "network.device.updated":  {"resource_type": "device"},
    "network.device.deleted":  {"resource_type": "device"},
    "network.topology.reconcile_requested": {"resource_type": "network"},
    "network.topology.reconcile_completed": {"resource_type": "network"},
    "network.topology.reconcile_failed": {"resource_type": "network"},
    "org.organization.created": {"resource_type": "organization"},
    "org.organization.updated": {"resource_type": "organization"},
    "org.organization.deleted": {"resource_type": "organization"},
    "org.workspace.created":    {"resource_type": "workspace"},
    "org.workspace.updated":    {"resource_type": "workspace"},
    "org.workspace.deleted":    {"resource_type": "workspace"},
    "org.member.added":         {"resource_type": "org_member"},
    "org.member.removed":       {"resource_type": "org_member"},
    "telemetry.collector.sustained_failure_activated": {"resource_type": "telemetry_collector"},
    "telemetry.collector.sustained_failure_recovered": {"resource_type": "telemetry_collector"},
    "alert.generated": {"resource_type": "alert"},
    "alert.acknowledged": {"resource_type": "alert"},
    "alert.resolved": {"resource_type": "alert"},
}

# Resource identity follows the event entity, not whichever payload ID is first.
_RESOURCE_KEYS = {
    "organization": ("org_id",), "workspace": ("workspace_id",),
    "org_member": ("user_id",), "network": ("network_id",), "device": ("device_id",),
    "intent": ("intent_id",), "simulation": ("simulation_id", "parent_simulation_id"),
    "plugin": ("plugin_id",), "report": ("report_id",), "alert": ("alert_id", "alertId"),
    "telemetry_collector": (),
}
_ACTOR_KEYS = {
    "org": ("actor_id",), "network": ("actor_id", "requested_by_user_id"),
    "intent": ("actor_id", "requested_by_user_id", "user_id"),
    "simulation": ("actor_id", "requested_by_user_id", "user_id"),
    "plugin": ("requested_by_user_id", "actor_id"), "report": ("requested_by_user_id", "actor_id"),
    "telemetry": ("actor_id",), "alert": ("actor_id",),
}
_EVENT_ACTOR_KEYS = {
    "alert.acknowledged": ("acknowledged_by_user_id", "actor_id"),
    "alert.resolved": ("resolved_by_user_id", "actor_id"),
}


def _first(payload: dict, keys: tuple[str, ...]):
    return next((payload[key] for key in keys if payload.get(key)), None)


async def handle_audit_event(event: dict) -> None:
    """Write an audit log entry for any mapped event type."""
    event_type = event.get("event_type", "")
    config = _AUDIT_MAP.get(event_type)
    if config is None:
        return

    payload_raw = event.get("payload")
    payload = payload_raw if isinstance(payload_raw, dict) else {}
    correlation_id, metadata = normalize_audit_correlation(
        event.get("correlation_id", event["event_id"]), payload,
    )

    actor_id_raw = _first(payload, _EVENT_ACTOR_KEYS.get(
        event_type, _ACTOR_KEYS[event_type.split(".")[0]],
    ))
    try:
        actor_id = uuid.UUID(str(actor_id_raw)) if actor_id_raw else None
    except (ValueError, TypeError, AttributeError):
        actor_id = None

    resource_id_raw = _first(payload, _RESOURCE_KEYS[config["resource_type"]])
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
            event_id=uuid.UUID(str(event["event_id"])),
            event_type=event_type,
            actor_id=actor_id,
            resource_type=config["resource_type"],
            resource_id=resource_id,
            org_id=org_id,
            correlation_id=correlation_id,
            metadata=metadata,
        )
        await db.commit()

    logger.info("audit_log_written", event_type=event_type, correlation_id=str(correlation_id))


# Handler registry for the event bus consumer loop
AUDIT_HANDLERS: dict[str, object] = {event_type: handle_audit_event for event_type in _AUDIT_MAP}
