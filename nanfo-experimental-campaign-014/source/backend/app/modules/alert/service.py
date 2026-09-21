"""Alert services.

Scope:
- Alerts list/read retrieval with contract-safe filtering
- Alert lifecycle transitions (acknowledge / resolve)
- Event-driven alert state ingestion for generated/acknowledged/resolved contracts
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.alert.repository import AlertRepository
from app.modules.alert.detector import identity_key
from app.modules.alert.schemas import (
    AlertActionResponse,
    AlertListResponse,
    AlertRecordResponse,
    AlertHistoryResponse,
    LegacyAlertIdentity,
)
from app.modules.network.service import NetworkService
from app.modules.organization.service import WorkspaceService as OrgWorkspaceService
from app.modules.organization.service import OrgService

logger = get_logger(__name__)

_ALERT_STATUS_ACTIVE = "active"
_ALERT_STATUS_ACKNOWLEDGED = "acknowledged"
_ALERT_STATUS_RESOLVED = "resolved"
_ALERT_STATUSES = {
    _ALERT_STATUS_ACTIVE,
    _ALERT_STATUS_ACKNOWLEDGED,
    _ALERT_STATUS_RESOLVED,
}


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _coerce_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    text = _coerce_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_status(status_value: str | None) -> str | None:
    if status_value is None:
        return None
    normalized = status_value.strip().lower()
    return normalized or None


class AlertService:
    """List, transition, and ingest lifecycle state for alert records."""

    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis | None):
        self._db = db
        self._redis = redis
        self._repo = AlertRepository(db)
        self._network_svc = NetworkService(db=db, redis=redis)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def _accessible_scopes(self, actor_user_id, requested_workspace_id, claim_org_id):
        workspaces = await self._workspace_svc.list_accessible_workspace_ids(
            user_id=actor_user_id, claim_org_id=claim_org_id, claim_workspace_id=requested_workspace_id)
        scopes = []
        for workspace_id in workspaces:
            workspace = await self._workspace_svc.get_active_workspace(
                workspace_id, user_id=actor_user_id, claim_org_id=claim_org_id)
            networks, page = [], 1
            while True:
                result = await self._network_svc.list_networks(workspace_id=workspace_id,
                    actor_user_id=actor_user_id, page=page, page_size=500, claim_org_id=claim_org_id)
                networks.extend(row.network_id for row in result.items)
                if len(networks) >= result.total or not result.items:
                    break
                page += 1
            scopes.append((workspace_id, workspace.org_id, networks))
        org_ids = []
        if requested_workspace_id is None:
            page = 1
            while True:
                result = await OrgService(self._db, self._redis).list_orgs(
                    user_id=actor_user_id, page=page, page_size=500, org_id=claim_org_id)
                org_ids.extend(row.org_id for row in result.items)
                if len(org_ids) >= result.total or not result.items:
                    break
                page += 1
        return scopes, org_ids

    async def get_alert(self, *, alert_id, actor_user_id, requested_workspace_id=None, claim_org_id=None):
        alert = await self._repo.get_by_id(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail={"code": "ALERT_NOT_FOUND", "message": "Alert not found."})
        await self._assert_alert_access(alert=alert, actor_user_id=actor_user_id,
            requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id)
        return AlertRecordResponse.model_validate(alert)

    async def get_history(self, **scope):
        alert = await self.get_alert(**scope)
        rows = await self._repo.history(alert.alert_id)
        return AlertHistoryResponse(alert_id=alert.alert_id, items=rows, total=len(rows))

    @staticmethod
    def _extract_alert_scope_uuid(payload: dict[str, Any], key: str) -> uuid.UUID | None:
        raw_value = payload.get(key)
        if raw_value is None:
            scope = payload.get("scope")
            if isinstance(scope, dict):
                raw_value = scope.get(key)

        if raw_value is None:
            return None

        parsed = _coerce_uuid(raw_value)
        if parsed is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return parsed

    async def _assert_alert_access(
        self,
        *,
        alert,
        actor_user_id: str,
        requested_workspace_id: uuid.UUID | None,
        claim_org_id: uuid.UUID | None,
        require_write: bool = False,
    ) -> None:
        payload = alert.payload if isinstance(alert.payload, dict) else {}
        payload_network_id = self._extract_alert_scope_uuid(payload, "network_id")
        payload_workspace_id = self._extract_alert_scope_uuid(payload, "workspace_id")
        payload_org_id = self._extract_alert_scope_uuid(payload, "org_id")

        if payload_network_id is not None:
            network = await self._network_svc.assert_network_workspace_access(
                network_id=payload_network_id,
                requested_workspace_id=requested_workspace_id,
                actor_user_id=actor_user_id,
                claim_org_id=claim_org_id,
                require_write=require_write,
            )
            if payload_workspace_id is not None and network.workspace_id != payload_workspace_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
            if payload_org_id is not None:
                await self._workspace_svc.get_active_workspace(
                    network.workspace_id, user_id=actor_user_id, claim_org_id=payload_org_id,
                )
            return

        if payload_workspace_id is not None:
            if requested_workspace_id is not None and payload_workspace_id != requested_workspace_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
            workspace = await self._workspace_svc.get_active_workspace(
                payload_workspace_id,
                user_id=actor_user_id,
                claim_org_id=claim_org_id,
                require_write=require_write,
            )
            if payload_org_id is not None and workspace.org_id != payload_org_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
            return

        if claim_org_id is not None and payload_org_id is not None and payload_org_id != claim_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        if requested_workspace_id is not None or payload_org_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        if require_write:
            await self._workspace_svc.assert_org_write_access(org_id=payload_org_id, user_id=actor_user_id)
        else:
            await self._workspace_svc.list_workspaces(
                org_id=payload_org_id, user_id=actor_user_id, page=1, page_size=1,
            )

    async def list_alerts(
        self,
        *,
        status_filter: str | None,
        severity_filter: str | None,
        source_filter: str | None,
        correlation_id_filter: uuid.UUID | None,
        search_filter: str | None,
        limit: int,
        actor_user_id: str | None = None,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
        workspace_id_filter: uuid.UUID | None = None,
        network_id_filter: uuid.UUID | None = None,
    ) -> AlertListResponse:
        normalized_status = _normalize_status(status_filter)
        if normalized_status is not None and normalized_status not in _ALERT_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "ALERT_STATUS_INVALID",
                    "message": "status must be one of: active, acknowledged, resolved.",
                },
            )

        normalized_severity = _normalize_status(severity_filter)
        if actor_user_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        normalized_source = _normalize_status(source_filter)
        normalized_search = _coerce_text(search_filter) or None
        bounded_limit = max(1, min(limit, 500))
        # A UI selection only narrows token authority. Resolve it through the
        # owning services before querying Alert-owned records.
        effective_workspace_id = requested_workspace_id
        if workspace_id_filter is not None:
            if requested_workspace_id is not None and workspace_id_filter != requested_workspace_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
            await self._workspace_svc.get_active_workspace(
                workspace_id_filter, user_id=actor_user_id, claim_org_id=claim_org_id,
            )
            effective_workspace_id = workspace_id_filter
        if network_id_filter is not None:
            network = await self._network_svc.assert_network_workspace_access(
                network_id=network_id_filter, requested_workspace_id=effective_workspace_id,
                actor_user_id=actor_user_id, claim_org_id=claim_org_id,
            )
            effective_workspace_id = network.workspace_id
        scopes, org_ids = await self._accessible_scopes(actor_user_id, effective_workspace_id, claim_org_id)

        rows = await self._repo.list_alerts(
            status=normalized_status,
            severity=normalized_severity,
            source=normalized_source,
            correlation_id=correlation_id_filter,
            search=normalized_search,
            limit=bounded_limit,
            scopes=scopes,
            org_ids=org_ids,
            network_id=network_id_filter,
        )

        scoped_rows = rows
        if actor_user_id is not None:
            scoped_rows = []
            for row in rows:
                try:
                    await self._assert_alert_access(
                        alert=row,
                        actor_user_id=actor_user_id,
                        requested_workspace_id=effective_workspace_id,
                        claim_org_id=claim_org_id,
                    )
                except HTTPException as exc:
                    if exc.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND):
                        continue
                    raise
                scoped_rows.append(row)

        status_counts = {
            _ALERT_STATUS_ACTIVE: 0,
            _ALERT_STATUS_ACKNOWLEDGED: 0,
            _ALERT_STATUS_RESOLVED: 0,
        }
        items: list[AlertRecordResponse] = []
        for row in scoped_rows:
            status_value = _normalize_status(row.status) or _ALERT_STATUS_ACTIVE
            if status_value in status_counts:
                status_counts[status_value] += 1
            items.append(AlertRecordResponse.model_validate(row))

        return AlertListResponse(
            items=items,
            total=len(items),
            status_counts=status_counts,
        )

    async def acknowledge_alert(
        self,
        *,
        alert_id: uuid.UUID,
        correlation_id: str,
        requested_by_user_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> AlertActionResponse:
        alert = await self._repo.get_by_id(alert_id, lock=True)
        if alert is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "ALERT_NOT_FOUND", "message": "Alert not found."},
            )

        await self._assert_alert_access(
            alert=alert,
            actor_user_id=requested_by_user_id,
            requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id,
            require_write=True,
        )

        current_status = _normalize_status(alert.status) or _ALERT_STATUS_ACTIVE
        if current_status == _ALERT_STATUS_RESOLVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ALERT_ALREADY_RESOLVED",
                    "message": "Resolved alerts cannot be acknowledged.",
                },
            )

        if current_status == _ALERT_STATUS_ACKNOWLEDGED:
            return self._serialize_action_response(
                alert,
                queue_status="replayed",
                stream_entry_id=None,
                warning=None,
                idempotent_replay=True,
            )

        acknowledged_at = datetime.now(UTC)
        ack_payload = self._build_lifecycle_payload(
            alert_payload=alert.payload,
            alert_id=alert.alert_id,
            alert_key=alert.alert_key,
            severity=alert.severity,
            status_value=_ALERT_STATUS_ACKNOWLEDGED,
            actor_id=requested_by_user_id,
            occurred_at=acknowledged_at,
        )

        event_id = await self._repo.append_history(
            alert_id=alert.alert_id, event_type="alert.acknowledged",
            correlation_id=_coerce_uuid(correlation_id) or uuid.uuid4(),
            occurred_at=acknowledged_at, payload=ack_payload, publish=True,
        )
        await self._repo.mark_acknowledged(
            alert,
            acknowledged_by_user_id=requested_by_user_id,
            acknowledged_at=acknowledged_at,
            payload=ack_payload,
            acknowledged_event_id=event_id,
        )
        await self._db.commit()
        await self._db.refresh(alert)

        return self._serialize_action_response(
            alert,
            queue_status="deferred",
            stream_entry_id=None,
            warning="event_delivery_pending",
            idempotent_replay=False,
        )

    async def resolve_alert(
        self,
        *,
        alert_id: uuid.UUID,
        correlation_id: str,
        requested_by_user_id: str,
        requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None,
    ) -> AlertActionResponse:
        alert = await self._repo.get_by_id(alert_id, lock=True)
        if alert is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "ALERT_NOT_FOUND", "message": "Alert not found."},
            )

        await self._assert_alert_access(
            alert=alert,
            actor_user_id=requested_by_user_id,
            requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id,
            require_write=True,
        )

        current_status = _normalize_status(alert.status) or _ALERT_STATUS_ACTIVE
        if current_status == _ALERT_STATUS_RESOLVED:
            return self._serialize_action_response(
                alert,
                queue_status="replayed",
                stream_entry_id=None,
                warning=None,
                idempotent_replay=True,
            )

        resolved_at = datetime.now(UTC)
        resolved_payload = self._build_lifecycle_payload(
            alert_payload=alert.payload,
            alert_id=alert.alert_id,
            alert_key=alert.alert_key,
            severity=alert.severity,
            status_value=_ALERT_STATUS_RESOLVED,
            actor_id=requested_by_user_id,
            occurred_at=resolved_at,
        )

        event_id = await self._repo.append_history(
            alert_id=alert.alert_id, event_type="alert.resolved",
            correlation_id=_coerce_uuid(correlation_id) or uuid.uuid4(),
            occurred_at=resolved_at, payload=resolved_payload, publish=True,
        )
        await self._repo.mark_resolved(
            alert,
            resolved_by_user_id=requested_by_user_id,
            resolved_at=resolved_at,
            payload=resolved_payload,
            resolved_event_id=event_id,
        )
        await self._db.commit()
        await self._db.refresh(alert)

        return self._serialize_action_response(
            alert,
            queue_status="deferred",
            stream_entry_id=None,
            warning="event_delivery_pending",
            idempotent_replay=False,
        )

    async def ingest_alert_event(self, event: dict[str, Any]) -> None:
        event_type = _coerce_text(event.get("event_type")).lower()
        if event_type not in {
            "alert.generated",
            "alert.acknowledged",
            "alert.resolved",
        }:
            return

        payload_raw = event.get("payload")
        payload = payload_raw if isinstance(payload_raw, dict) else {}
        event_id = _coerce_uuid(event.get("event_id"))
        correlation_id = _coerce_uuid(event.get("correlation_id")) or uuid.uuid4()
        source = _coerce_text(event.get("source")) or "unknown"
        occurred_at = _coerce_timestamp(event.get("timestamp")) or datetime.now(UTC)
        try:
            LegacyAlertIdentity.normalize(payload)
        except ValueError:
            return

        if event_type == "alert.generated":
            await self._ingest_generated_event(
                payload=payload,
                source=source,
                event_id=event_id,
                correlation_id=correlation_id,
                occurred_at=occurred_at,
            )
            return

        target = await self._resolve_lifecycle_target(payload)
        if target is None:
            logger.warning(
                "alert_lifecycle_target_not_found",
                event_type=event_type,
                alert_id=payload.get("alert_id"),
                alert_key=payload.get("alert_key"),
            )
            return

        # Measured lifecycle is authoritative in Alert transactions, not inbound
        # lifecycle messages. Outbox replay must never resurrect or resolve it.
        if target.payload.get("detector_key") is not None:
            return
        try:
            if LegacyAlertIdentity.normalize(target.payload) != LegacyAlertIdentity.normalize(payload):
                return
        except ValueError:
            return
        if occurred_at < target.created_at:
            return

        actor_id = (
            _coerce_text(payload.get("acknowledged_by_user_id"))
            or _coerce_text(payload.get("resolved_by_user_id"))
            or _coerce_text(payload.get("actor_id"))
            or _coerce_text(payload.get("user_id"))
            or None
        )

        if event_type == "alert.acknowledged":
            if _normalize_status(target.status) == _ALERT_STATUS_RESOLVED:
                return
            if _normalize_status(target.status) != _ALERT_STATUS_ACKNOWLEDGED:
                acknowledged_at = _coerce_timestamp(payload.get("acknowledged_at")) or occurred_at
                merged_payload = self._merge_lifecycle_payload(
                    existing_payload=target.payload,
                    incoming_payload=payload,
                    alert_id=target.alert_id,
                    alert_key=target.alert_key,
                    severity=target.severity,
                    status_value=_ALERT_STATUS_ACKNOWLEDGED,
                    actor_id=actor_id,
                    occurred_at=acknowledged_at,
                )
                await self._repo.mark_acknowledged(
                    target,
                    acknowledged_by_user_id=actor_id,
                    acknowledged_at=acknowledged_at,
                    payload=merged_payload,
                    acknowledged_event_id=event_id,
                )
                await self._repo.append_history(alert_id=target.alert_id, event_type=event_type,
                    correlation_id=correlation_id, occurred_at=acknowledged_at,
                    payload=merged_payload, event_id=event_id)
                await self._db.commit()
            return

        if _normalize_status(target.status) == _ALERT_STATUS_RESOLVED:
            return

        resolved_at = _coerce_timestamp(payload.get("resolved_at")) or occurred_at
        merged_payload = self._merge_lifecycle_payload(
            existing_payload=target.payload,
            incoming_payload=payload,
            alert_id=target.alert_id,
            alert_key=target.alert_key,
            severity=target.severity,
            status_value=_ALERT_STATUS_RESOLVED,
            actor_id=actor_id,
            occurred_at=resolved_at,
        )
        await self._repo.mark_resolved(
            target,
            resolved_by_user_id=actor_id,
            resolved_at=resolved_at,
            payload=merged_payload,
            resolved_event_id=event_id,
        )
        await self._repo.append_history(alert_id=target.alert_id, event_type=event_type,
            correlation_id=correlation_id, occurred_at=resolved_at, payload=merged_payload, event_id=event_id)
        await self._db.commit()

    async def _ingest_generated_event(
        self,
        *,
        payload: dict[str, Any],
        source: str,
        event_id: uuid.UUID | None,
        correlation_id: uuid.UUID,
        occurred_at: datetime,
    ) -> None:
        if payload.get("detector_key") is not None:
            return
        if event_id is None:
            return
        if not await self._repo.consume_generation(event_id, identity_key({"source": source, "payload": payload})):
            await self._db.rollback()
            return
        existing = await self._repo.get_by_generated_event_id(event_id)
        if existing is not None:
            await self._repo.link_consumed_generation(event_id, existing.alert_id)
            await self._db.commit()
            return

        alert_id = _coerce_uuid(payload.get("alert_id")) or uuid.uuid4()
        alert_key = _coerce_text(payload.get("alert_key")) or f"{source}:{alert_id}"
        identity = LegacyAlertIdentity.normalize(payload)
        await self._repo.lock_legacy_identity(identity_key({"alert_key": alert_key, **identity}))
        existing_unresolved = await self._repo.get_latest_unresolved_by_key(alert_key, identity=identity)
        if existing_unresolved is not None:
            await self._repo.link_consumed_generation(event_id, existing_unresolved.alert_id)
            await self._db.commit()
            return

        severity = _normalize_status(_coerce_text(payload.get("severity")))
        merged_payload = self._merge_lifecycle_payload(
            existing_payload={},
            incoming_payload={**payload, **identity},
            alert_id=alert_id,
            alert_key=alert_key,
            severity=severity,
            status_value=_ALERT_STATUS_ACTIVE,
            actor_id=None,
            occurred_at=occurred_at,
        )

        await self._repo.create_generated(
            alert_id=alert_id,
            alert_key=alert_key,
            source=source,
            severity=severity,
            correlation_id=correlation_id,
            payload=merged_payload,
            generated_event_id=event_id,
            created_at=occurred_at,
        )
        await self._repo.append_history(alert_id=alert_id, event_type="alert.generated",
            correlation_id=correlation_id, occurred_at=occurred_at, payload=merged_payload, event_id=event_id)
        await self._repo.link_consumed_generation(event_id, alert_id)
        await self._db.commit()

    async def _resolve_lifecycle_target(self, payload: dict[str, Any]):
        alert_id = _coerce_uuid(payload.get("alert_id"))
        if alert_id is not None:
            return await self._repo.get_by_id(alert_id, lock=True)

        alert_key = _coerce_text(payload.get("alert_key"))
        if not alert_key:
            return None
        return await self._repo.get_latest_unresolved_by_key(alert_key, identity=LegacyAlertIdentity.normalize(payload))

    @staticmethod
    def _merge_lifecycle_payload(
        *,
        existing_payload: dict[str, Any] | None,
        incoming_payload: dict[str, Any] | None,
        alert_id: uuid.UUID,
        alert_key: str,
        severity: str | None,
        status_value: str,
        actor_id: str | None,
        occurred_at: datetime,
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        if isinstance(existing_payload, dict):
            merged.update(existing_payload)
        if isinstance(incoming_payload, dict):
            merged.update(incoming_payload)

        merged["alert_id"] = str(alert_id)
        merged["alert_key"] = alert_key
        merged["status"] = status_value
        if severity is not None:
            merged["severity"] = severity

        if status_value == _ALERT_STATUS_ACKNOWLEDGED:
            if actor_id is not None:
                merged["acknowledged_by_user_id"] = actor_id
            merged["acknowledged_at"] = occurred_at.isoformat()

        if status_value == _ALERT_STATUS_RESOLVED:
            if actor_id is not None:
                merged["resolved_by_user_id"] = actor_id
            merged["resolved_at"] = occurred_at.isoformat()

        return merged

    def _build_lifecycle_payload(
        self,
        *,
        alert_payload: dict[str, Any] | None,
        alert_id: uuid.UUID,
        alert_key: str,
        severity: str | None,
        status_value: str,
        actor_id: str,
        occurred_at: datetime,
    ) -> dict[str, Any]:
        return self._merge_lifecycle_payload(
            existing_payload=alert_payload,
            incoming_payload={},
            alert_id=alert_id,
            alert_key=alert_key,
            severity=severity,
            status_value=status_value,
            actor_id=actor_id,
            occurred_at=occurred_at,
        )

    @staticmethod
    def _serialize_action_response(
        alert,
        *,
        queue_status: str,
        stream_entry_id: str | None,
        warning: str | None,
        idempotent_replay: bool,
    ) -> AlertActionResponse:
        payload = AlertRecordResponse.model_validate(alert).model_dump()
        payload.update(
            {
                "queue_status": queue_status,
                "stream_entry_id": stream_entry_id,
                "warning": warning,
                "idempotent_replay": idempotent_replay,
            }
        )
        return AlertActionResponse.model_validate(payload)
