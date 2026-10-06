"""Identity-owned audit read model and event projection (ADR-028 C7, fix 10).

* ``AuditQueryService`` is the only read path for ``GET /api/v1/audit/logs``.
  Authorization (global Admin, current org membership, claim narrowing) is
  composed by the router; this service only shapes the scoped query.
* ``project_event_metadata`` turns a domain-event payload into the allowlisted,
  size-capped audit metadata persisted for that event type. The audit consumer
  and the Organization module's direct lifecycle append both use it, so direct
  append and consumer replay of one event store identical metadata.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.repository import AuditLogRepository
from app.modules.identity.schemas import AuditLogEntry, AuditLogPage, AuditScope

# ── Read model ────────────────────────────────────────────────────────────────


class AuditQueryService:
    """Scoped, paginated audit reads. ``platform`` = unscoped (``org_id IS NULL``) events."""

    def __init__(self, db: AsyncSession):
        self._repo = AuditLogRepository(db)

    async def list_logs(
        self,
        *,
        scope: AuditScope,
        org_id: uuid.UUID | None,
        actor_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
    ) -> AuditLogPage:
        if scope == "platform":
            if org_id is not None:
                raise ValueError("Platform scope selects unscoped events; org_id is not allowed.")
            entries, total = await self._repo.list_entries(
                org_id=None, platform_only=True, actor_id=actor_id, resource_type=resource_type,
                page=page, page_size=page_size, search=search,
            )
        else:
            if org_id is None:
                raise ValueError("Organization scope requires org_id.")
            entries, total = await self._repo.list_entries(
                org_id=org_id, actor_id=actor_id, resource_type=resource_type,
                page=page, page_size=page_size, search=search,
            )
        return AuditLogPage(
            items=[
                AuditLogEntry(
                    log_id=entry.log_id, event_type=entry.event_type, actor_id=entry.actor_id,
                    resource_type=entry.resource_type, resource_id=entry.resource_id, org_id=entry.org_id,
                    correlation_id=entry.correlation_id, timestamp=entry.timestamp, metadata=entry.metadata_,
                )
                for entry in entries
            ],
            total=total, page=page, page_size=page_size, scope=scope,
        )


# ── Event projection ──────────────────────────────────────────────────────────

MAX_TEXT_CHARS = 1024
MAX_CONTAINER_ITEMS = 32
MAX_DEPTH = 3
MAX_PROJECTION_BYTES = 8192
TRUNCATED_MARKER = "_truncated"

# Spec values: ``None`` = scalar or small JSON value (generically capped);
# a mapping = nested allowlist applied to a dict value.
_Spec = Mapping[str, Any]
_ANY = None

_ORG_EVENTS: dict[str, _Spec] = {
    "org.organization.created": {"org_id": _ANY, "name": _ANY, "slug": _ANY, "actor_id": _ANY},
    "org.organization.updated": {"org_id": _ANY, "changed_fields": {"name": _ANY}, "actor_id": _ANY},
    "org.organization.deleted": {"org_id": _ANY, "actor_id": _ANY},
    "org.workspace.created": {"workspace_id": _ANY, "org_id": _ANY, "name": _ANY, "actor_id": _ANY},
    "org.workspace.updated": {
        "workspace_id": _ANY, "org_id": _ANY, "changed_fields": {"name": _ANY, "description": _ANY},
        "actor_id": _ANY,
    },
    "org.workspace.deleted": {"workspace_id": _ANY, "org_id": _ANY, "actor_id": _ANY},
    "org.member.added": {
        "org_id": _ANY, "user_id": _ANY, "org_role": _ANY, "actor_id": _ANY, "restored": _ANY,
    },
    "org.member.removed": {"org_id": _ANY, "user_id": _ANY, "actor_id": _ANY},
}

_INVENTORY: _Spec = {
    "network_id": _ANY, "workspace_id": _ANY, "org_id": _ANY, "actor_id": _ANY,
    "requested_by_user_id": _ANY, "sequence": _ANY,
}
_DEVICE: _Spec = {
    **_INVENTORY, "device_id": _ANY, "hostname": _ANY, "ip_address": _ANY, "device_type": _ANY,
    "spatial_ref_id": _ANY,
}
_RECONCILE: _Spec = {
    "reconcile_id": _ANY, "network_id": _ANY, "workspace_id": _ANY, "status": _ANY, "actor_id": _ANY,
    "requested_at": _ANY, "completed_at": _ANY, "failed_at": _ANY, "error": _ANY, "warning": _ANY,
    "checked_nodes": _ANY, "checked_edges": _ANY, "missing_workspace_nodes": _ANY,
    "workspace_backfilled_nodes": _ANY,
}
_NETWORK_EVENTS: dict[str, _Spec] = {
    "network.network.created": {**_INVENTORY, "name": _ANY},
    "network.network.updated": {**_INVENTORY, "changed_fields": _ANY},
    "network.network.deleted": _INVENTORY,
    "network.device.added": _DEVICE,
    "network.device.updated": {**_DEVICE, "changed_fields": _ANY},
    "network.device.deleted": _DEVICE,
    "network.topology.reconcile_requested": _RECONCILE,
    "network.topology.reconcile_completed": _RECONCILE,
    "network.topology.reconcile_failed": _RECONCILE,
}

_INTENT: _Spec = {
    "intent_id": _ANY, "workspace_id": _ANY, "network_id": _ANY, "org_id": _ANY, "intent_kind": _ANY,
    "status": _ANY, "requested_by_user_id": _ANY, "actor_id": _ANY,
    "confidence": {"score": _ANY, "band": _ANY, "approval_required": _ANY},
    "validation_result": {
        "is_valid": _ANY, "validation_kind": _ANY, "policy_reference": _ANY, "capability_match": _ANY,
        "simulation_required": _ANY, "validated_at": _ANY,
    },
    "execution_provenance": {
        "executor": _ANY, "policy_reference": _ANY, "execution_id": _ANY, "status": _ANY, "phase": _ANY,
        "pipeline_stage": _ANY, "plan_hash": _ANY, "binding_digest": _ANY, "run_id": _ANY,
        "failure_reason": _ANY, "verification": _ANY, "rollback": _ANY, "uncertain": _ANY,
        "blocks_lab": _ANY, "cancel_requested": _ANY, "cancelled_by_user_id": _ANY,
        "approved_by_user_id": _ANY, "approved_at": _ANY, "completion_scope": _ANY,
        "validated_at": _ANY, "execution_started_at": _ANY, "execution_completed_at": _ANY,
        "execution_failed_at": _ANY, "completed_at": _ANY,
    },
}
_SIMULATION: _Spec = {
    "simulation_id": _ANY, "parent_simulation_id": _ANY, "scenario_id": _ANY, "network_id": _ANY,
    "workspace_id": _ANY, "org_id": _ANY, "state": _ANY, "status": _ANY, "risk_gate": _ANY,
    "revision": _ANY, "scenario_name": _ANY, "requested_at": _ANY, "requested_by_user_id": _ANY,
    "actor_id": _ANY, "user_id": _ANY,
    "validation": {
        "pipeline_stage": _ANY, "status": _ANY, "policy_reference": _ANY, "failure_reason": _ANY,
        "requested_by_user_id": _ANY, "evaluator_status": _ANY, "queued_at": _ANY,
    },
}
_PLUGIN: _Spec = {
    "plugin_id": _ANY, "plugin_key": _ANY, "name": _ANY, "version": _ANY, "status": _ANY, "enabled": _ANY,
    "signature_status": _ANY, "dependency_status": _ANY, "sandbox_status": _ANY, "failure_reason": _ANY,
    "failure_message": _ANY, "requested_by_user_id": _ANY, "actor_id": _ANY,
}
_REPORT: _Spec = {
    "report_id": _ANY, "workspace_id": _ANY, "network_id": _ANY, "org_id": _ANY, "report_type": _ANY,
    "format": _ANY, "status": _ANY, "status_version": _ANY, "snapshot_sha256": _ANY,
    "requested_by_user_id": _ANY, "actor_id": _ANY, "requested_at": _ANY, "completed_at": _ANY,
    "error": _ANY,
}
_ALERT: _Spec = {
    "alert_id": _ANY, "alertId": _ANY, "alert_key": _ANY, "status": _ANY, "severity": _ANY, "source": _ANY,
    "org_id": _ANY, "workspace_id": _ANY, "network_id": _ANY, "device_id": _ANY, "metric": _ANY,
    "actor_id": _ANY, "acknowledged_by_user_id": _ANY, "acknowledged_at": _ANY,
    "resolved_by_user_id": _ANY, "resolved_at": _ANY, "observed_at": _ANY,
}
_TELEMETRY_COLLECTOR: _Spec = {
    "exhausted_streak": _ANY, "sustained_failure_threshold": _ANY, "observed_at": _ANY, "actor_id": _ANY,
}

AUDIT_EVENT_PROJECTIONS: dict[str, _Spec] = {
    **_ORG_EVENTS,
    **_NETWORK_EVENTS,
    **{f"intent.{action}": _INTENT for action in (
        "validated", "execution_started", "execution_completed", "execution_failed")},
    **{f"simulation.{action}": _SIMULATION for action in (
        "started", "completed", "paused", "cancelled", "branch_created")},
    **{f"plugin.{action}": _PLUGIN for action in ("installed", "enabled", "disabled", "failed")},
    **{f"report.{action}": _REPORT for action in ("requested", "generated", "failed")},
    **{f"alert.{action}": _ALERT for action in ("generated", "acknowledged", "resolved")},
    "telemetry.collector.sustained_failure_activated": _TELEMETRY_COLLECTOR,
    "telemetry.collector.sustained_failure_recovered": _TELEMETRY_COLLECTOR,
}


def _cap_value(value: Any, depth: int) -> tuple[Any, bool]:
    """Bound a JSON value: text length, container width and nesting depth."""
    if value is None or isinstance(value, bool | int):
        return value, False
    if isinstance(value, float):
        return (value, False) if value == value and value not in (float("inf"), float("-inf")) else (None, True)
    if isinstance(value, str):
        return (value, False) if len(value) <= MAX_TEXT_CHARS else (value[:MAX_TEXT_CHARS], True)
    if depth >= MAX_DEPTH:
        return None, True
    if isinstance(value, Mapping):
        capped, truncated = {}, len(value) > MAX_CONTAINER_ITEMS
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_CONTAINER_ITEMS:
                break
            capped[str(key)[:MAX_TEXT_CHARS]], cut = _cap_value(item, depth + 1)
            truncated = truncated or cut
        return capped, truncated
    if isinstance(value, list | tuple):
        items, truncated = [], len(value) > MAX_CONTAINER_ITEMS
        for item in list(value)[:MAX_CONTAINER_ITEMS]:
            capped_item, cut = _cap_value(item, depth + 1)
            items.append(capped_item)
            truncated = truncated or cut
        return items, truncated
    # Non-JSON scalars (UUID, datetime, ...) are recorded by their text form.
    return _cap_value(str(value), depth)


def _project(payload: Mapping[str, Any], spec: _Spec, depth: int) -> tuple[dict, bool]:
    projected: dict[str, Any] = {}
    truncated = False
    for key, nested in spec.items():
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(nested, Mapping):
            if isinstance(value, Mapping):
                projected[key], cut = _project(value, nested, depth + 1)
            else:
                projected[key], cut = _cap_value(value, depth + 1)
        else:
            projected[key], cut = _cap_value(value, depth + 1)
        truncated = truncated or cut
    return projected, truncated


def _encoded_size(document: Mapping[str, Any]) -> int:
    return len(json.dumps(document, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8"))


def project_event_metadata(event_type: str, payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Allowlisted, size-capped audit metadata for ``event_type``.

    Unknown event types keep nothing. When bounded fields still exceed
    ``MAX_PROJECTION_BYTES``, only top-level scalars are kept. Any reduction is
    flagged with ``_truncated: true``; the full payload is never persisted.
    """
    spec = AUDIT_EVENT_PROJECTIONS.get(event_type)
    if spec is None or not isinstance(payload, Mapping):
        return {}
    projected, truncated = _project(payload, spec, 0)
    if _encoded_size(projected) > MAX_PROJECTION_BYTES:
        projected = {key: value for key, value in projected.items()
                     if value is None or isinstance(value, bool | int | float | str)}
        truncated = True
        while projected and _encoded_size(projected) > MAX_PROJECTION_BYTES:
            projected.pop(next(reversed(projected)))
    if truncated:
        projected[TRUNCATED_MARKER] = True
    return projected
