"""Alert services.

Scope:
- Alerts list/read retrieval with contract-safe filtering
- Alert lifecycle transitions (acknowledge / resolve)
- Event-driven alert state ingestion for generated/acknowledged/resolved contracts
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import normalize_audit_correlation
from app.core.logging import get_logger
from app.modules.alert.repository import MAX_SEARCH_LENGTH, AlertRepository
from app.modules.alert.detector import identity_key
from app.modules.alert.scope import AlertListScope, InvalidAlertScope, is_platform_scoped, recorded_scope_value
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
_STATUS_ORDER = (_ALERT_STATUS_ACTIVE, _ALERT_STATUS_ACKNOWLEDGED, _ALERT_STATUS_RESOLVED)
# Owner listing page size (organizations / networks) used to resolve list scope.
_OWNER_PAGE_SIZE = 500
# Upper bound of distinct legacy network-only scopes resolved one by one through
# the Network owner; beyond it the authorized workspaces' networks are listed once.
_LEGACY_NETWORK_LOOKUPS = 200


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


class AlertEventRejected(ValueError):
    """A lifecycle event whose own content can never be ingested (poison).

    ``reason`` is a stable machine-readable code. The event consumer maps it to
    ``DeterministicEventError`` so the bus dead-letters the entry at once
    (ADR-028 C14). Well-formed events that merely do not apply are ignored.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AlertService:
    """List, transition, and ingest lifecycle state for alert records."""

    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis | None):
        self._db = db
        self._redis = redis
        self._repo = AlertRepository(db)
        self._network_svc = NetworkService(db=db, redis=redis)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)
        self._network_workspaces: dict[uuid.UUID, uuid.UUID | None] = {}
        self._listed_networks: dict[uuid.UUID, dict[uuid.UUID, uuid.UUID]] = {}

    async def _member_org_ids(self, actor_user_id: str, claim_org_id: uuid.UUID | None) -> list[uuid.UUID]:
        orgs, page, service = [], 1, OrgService(self._db, self._redis)
        while True:
            result = await service.list_orgs(user_id=actor_user_id, page=page, page_size=_OWNER_PAGE_SIZE,
                                             org_id=claim_org_id)
            orgs.extend(row.org_id for row in result.items)
            if len(orgs) >= result.total or not result.items:
                return orgs
            page += 1

    async def _network_workspace(self, network_id: uuid.UUID, *, actor_user_id, claim_org_id) -> uuid.UUID | None:
        """Workspace of an active network the actor may read (memoized; None if not)."""
        if network_id not in self._network_workspaces:
            try:
                network = await self._network_svc.assert_network_workspace_access(
                    network_id=network_id, requested_workspace_id=None,
                    actor_user_id=actor_user_id, claim_org_id=claim_org_id)
                self._network_workspaces[network_id] = network.workspace_id
            except HTTPException as exc:
                if exc.status_code not in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND):
                    raise
                self._network_workspaces[network_id] = None
        return self._network_workspaces[network_id]

    async def _workspace_networks(self, actor_user_id, workspace_ids) -> dict[uuid.UUID, uuid.UUID]:
        """Active networks of authorized workspaces: one owner listing per workspace.

        Memoized for this service instance (one request), so the legacy-scope
        resolution and the final recheck never list the same workspace twice.
        """
        networks = {}
        for workspace_id in sorted(workspace_ids):
            if workspace_id in self._listed_networks:
                networks.update(self._listed_networks[workspace_id])
                continue
            listed, page = {}, 1
            while True:
                try:
                    result = await self._network_svc.list_networks(
                        workspace_id=workspace_id, actor_user_id=actor_user_id, page=page,
                        page_size=_OWNER_PAGE_SIZE)
                except HTTPException as exc:
                    if exc.status_code not in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND):
                        raise
                    break  # revoked/deleted meanwhile: its networks stay unauthorized
                listed.update((row.network_id, workspace_id) for row in result.items)
                if page * _OWNER_PAGE_SIZE >= result.total or not result.items:
                    break
                page += 1
            self._listed_networks[workspace_id] = listed
            networks.update(listed)
        return networks

    async def _legacy_networks(self, actor_user_id, claim_org_id, workspace_orgs) -> dict[uuid.UUID, uuid.UUID]:
        """Authorized networks of rows that recorded a network but no workspace.

        Only distinct legacy network identities present in Alert-owned rows are
        resolved (normally none): one owner check each, or one network listing per
        authorized workspace when that is cheaper — never per row.
        """
        if not workspace_orgs:
            return {}
        candidates = await self._repo.legacy_network_ids(limit=_LEGACY_NETWORK_LOOKUPS + 1)
        if not candidates:
            return {}
        if len(candidates) > min(_LEGACY_NETWORK_LOOKUPS, len(workspace_orgs)):
            networks = await self._workspace_networks(actor_user_id, workspace_orgs)
            return {network: networks[network] for network in candidates if network in networks}
        resolved = {}
        for network_id in candidates:
            workspace_id = await self._network_workspace(
                network_id, actor_user_id=actor_user_id, claim_org_id=claim_org_id)
            if workspace_id in workspace_orgs:
                resolved[network_id] = workspace_id
        return resolved

    async def _accessible_scopes(self, actor_user_id, requested_workspace_id, claim_org_id, *,
                                 workspace_org_id=None, network_id=None, platform=False) -> AlertListScope:
        """Authorized list scope from live owner memberships.

        Costs O(organizations) owner calls (one when narrowed to a workspace) and is
        consumed by one SQL predicate; rows are never authorized one by one.
        Claims and selections only narrow live membership. ``platform`` (global
        Admin, unscoped token, no selection) adds platform-scoped alerts.
        """
        if requested_workspace_id is not None:
            if workspace_org_id is None:
                try:
                    workspace = await self._workspace_svc.get_active_workspace(
                        requested_workspace_id, user_id=actor_user_id, claim_org_id=claim_org_id)
                except HTTPException as exc:
                    # A claim-narrowed token without current access sees nothing.
                    if exc.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND):
                        return AlertListScope()
                    raise
                workspace_org_id = workspace.org_id
            workspace_orgs = {requested_workspace_id: workspace_org_id}
            member_orgs: frozenset[uuid.UUID] = frozenset()
            platform = False
        else:
            org_ids = await self._member_org_ids(actor_user_id, claim_org_id)
            workspace_orgs = {}
            for org_id in sorted(set(org_ids)):
                for workspace_id in await self._workspace_svc.list_accessible_workspace_ids(
                        user_id=actor_user_id, claim_org_id=org_id):
                    workspace_orgs[workspace_id] = org_id
            member_orgs = frozenset(org_ids)
        if network_id is not None:
            networks = {network_id: requested_workspace_id}
            platform = False
        else:
            networks = await self._legacy_networks(actor_user_id, claim_org_id, workspace_orgs)
        return AlertListScope(workspace_orgs=workspace_orgs, member_org_ids=member_orgs,
                              networks=networks, network_id=network_id, platform=platform)

    @staticmethod
    def _recorded(payload, key):
        try:
            return recorded_scope_value(payload if isinstance(payload, dict) else {}, key)
        except InvalidAlertScope:
            return None

    async def _recheck(self, rows, scope: AlertListScope, *, actor_user_id, requested_workspace_id, claim_org_id):
        """Batched final authorization of returned rows (no per-row owner calls).

        One live-membership read catches revocation during the request, and one
        network listing per distinct recorded workspace proves each row's network
        still exists inside that workspace. Every row is then checked in memory.
        """
        if not rows:
            return [], []
        current = set(await self._workspace_svc.list_accessible_workspace_ids(
            user_id=actor_user_id, claim_org_id=claim_org_id, claim_workspace_id=requested_workspace_id))
        workspace_orgs = {key: value for key, value in scope.workspace_orgs.items() if key in current}
        member_orgs = scope.member_org_ids
        recorded = [(self._recorded(row.payload, "workspace_id"), self._recorded(row.payload, "network_id"),
                     self._recorded(row.payload, "org_id")) for row in rows]
        if member_orgs and any(workspace is None and network is None and org is not None
                               for workspace, network, org in recorded):
            member_orgs = member_orgs & frozenset(await self._member_org_ids(actor_user_id, claim_org_id))
        networks = dict(scope.networks)
        unresolved = {workspace for workspace, network, _ in recorded
                      if network is not None and network not in networks and workspace in workspace_orgs}
        if unresolved:
            networks.update(await self._workspace_networks(actor_user_id, unresolved))
        final = AlertListScope(workspace_orgs=workspace_orgs, member_org_ids=member_orgs,
                               networks=networks, network_id=scope.network_id, platform=scope.platform)
        kept, dropped = [], []
        for row in rows:
            (kept if final.allows(row.payload) else dropped).append(row)
        return kept, dropped

    async def get_alert(self, *, alert_id, actor_user_id, requested_workspace_id=None, claim_org_id=None,
                        platform_reader=False):
        alert = await self._repo.get_by_id(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail={"code": "ALERT_NOT_FOUND", "message": "Alert not found."})
        await self._assert_alert_access(alert=alert, actor_user_id=actor_user_id,
            requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id,
            platform_reader=platform_reader)
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
        platform_reader: bool = False,
    ) -> None:
        payload = alert.payload if isinstance(alert.payload, dict) else {}
        if is_platform_scoped(payload):
            # Platform-scoped (runtime SLO) alerts carry no tenancy: only a global
            # Admin with an unscoped token may read them. Their lifecycle belongs
            # to the SLO evaluator, so no caller may acknowledge/resolve them.
            if (platform_reader and not require_write and requested_workspace_id is None
                    and claim_org_id is None):
                return
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
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
        created_from: datetime | None = None,
        created_before: datetime | None = None,
        platform_reader: bool = False,
    ) -> AlertListResponse:
        """Scoped list; ``total``/``status_counts`` count every match, ``items`` <= limit.

        ``created_from``/``created_before`` are internal (Report source) filters on
        the creation time, start-inclusive and end-exclusive. ``platform_reader``
        (the router's global-Admin, unscoped-token decision) adds platform-scoped
        alerts when nothing narrows the request; tenant users never see them.
        """
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
        if normalized_search is not None and len(normalized_search) > MAX_SEARCH_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "ALERT_SEARCH_INVALID",
                        "message": f"search must be at most {MAX_SEARCH_LENGTH} characters."},
            )
        bounded_limit = max(1, min(limit, 500))
        # A UI selection only narrows token authority. Resolve it through the
        # owning services before querying Alert-owned records.
        effective_workspace_id = requested_workspace_id
        workspace_org_id = None
        if workspace_id_filter is not None:
            if requested_workspace_id is not None and workspace_id_filter != requested_workspace_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
            workspace = await self._workspace_svc.get_active_workspace(
                workspace_id_filter, user_id=actor_user_id, claim_org_id=claim_org_id,
            )
            effective_workspace_id = workspace_id_filter
            workspace_org_id = workspace.org_id
        if network_id_filter is not None:
            network = await self._network_svc.assert_network_workspace_access(
                network_id=network_id_filter, requested_workspace_id=effective_workspace_id,
                actor_user_id=actor_user_id, claim_org_id=claim_org_id,
            )
            if network.workspace_id != effective_workspace_id:
                workspace_org_id = None
            effective_workspace_id = network.workspace_id
        platform = bool(platform_reader and requested_workspace_id is None and claim_org_id is None
                        and workspace_id_filter is None and network_id_filter is None)
        scope = await self._accessible_scopes(actor_user_id, effective_workspace_id, claim_org_id,
                                              workspace_org_id=workspace_org_id, network_id=network_id_filter,
                                              platform=platform)

        query = dict(
            status=normalized_status,
            severity=normalized_severity,
            source=normalized_source,
            correlation_id=correlation_id_filter,
            search=normalized_search,
            created_from=created_from,
            created_before=created_before,
        )
        rows = await self._repo.list_alerts(**query, limit=bounded_limit, scope=scope)
        counts = await self._repo.count_alerts(**query, scope=scope) if not scope.empty else {}
        kept, dropped = await self._recheck(rows, scope, actor_user_id=actor_user_id,
                                            requested_workspace_id=effective_workspace_id, claim_org_id=claim_org_id)

        def bucket(value):
            return _normalize_status(value) or _ALERT_STATUS_ACTIVE

        matched = Counter()
        for status_value, count in counts.items():
            matched[bucket(status_value)] += count
        returned = Counter(bucket(row.status) for row in kept)
        removed = Counter(bucket(row.status) for row in dropped)
        # Exact SQL counts over the authorized scope, minus rows the final recheck
        # removed from this page; never below what is actually returned.
        status_counts = {key: max(matched[key] - removed[key], returned[key]) for key in _STATUS_ORDER}
        total = max(sum(matched.values()) - len(dropped), len(kept))
        return AlertListResponse(
            items=[AlertRecordResponse.model_validate(row) for row in kept],
            total=total,
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

        correlation, request_metadata = normalize_audit_correlation(correlation_id, {})
        event_id = await self._repo.append_history(
            alert_id=alert.alert_id, event_type="alert.acknowledged",
            correlation_id=correlation,
            occurred_at=acknowledged_at, payload={**ack_payload, **request_metadata}, publish=True,
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

        correlation, request_metadata = normalize_audit_correlation(correlation_id, {})
        event_id = await self._repo.append_history(
            alert_id=alert.alert_id, event_type="alert.resolved",
            correlation_id=correlation,
            occurred_at=resolved_at, payload={**resolved_payload, **request_metadata}, publish=True,
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

        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise AlertEventRejected("payload_not_object")
        event_id = _coerce_uuid(event.get("event_id"))
        # Shared deterministic mapping; an opaque/non-canonical original stays in
        # the immutable history payload as ``request_id`` (never a random UUID).
        correlation_id, correlation_metadata = normalize_audit_correlation(event.get("correlation_id"), {})
        source = _coerce_text(event.get("source")) or "unknown"
        occurred_at = _coerce_timestamp(event.get("timestamp")) or datetime.now(UTC)
        try:
            LegacyAlertIdentity.normalize(payload)
        except ValueError:
            # Invalid or conflicting recorded scope: no redelivery can fix it.
            raise AlertEventRejected("invalid_alert_scope") from None

        if event_type == "alert.generated":
            await self._ingest_generated_event(
                payload=payload,
                source=source,
                event_id=event_id,
                correlation_id=correlation_id,
                occurred_at=occurred_at,
                correlation_metadata=correlation_metadata,
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
                    payload={**merged_payload, **correlation_metadata}, event_id=event_id)
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
            correlation_id=correlation_id, occurred_at=resolved_at,
            payload={**merged_payload, **correlation_metadata}, event_id=event_id)
        await self._db.commit()

    async def _ingest_generated_event(
        self,
        *,
        payload: dict[str, Any],
        source: str,
        event_id: uuid.UUID | None,
        correlation_id: uuid.UUID,
        occurred_at: datetime,
        correlation_metadata: dict[str, Any] | None = None,
    ) -> None:
        if payload.get("detector_key") is not None:
            return
        if event_id is None:
            # First-delivery receipts are keyed by event id; without one the
            # generation can never be deduplicated safely.
            raise AlertEventRejected("missing_event_id")
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
            correlation_id=correlation_id, occurred_at=occurred_at,
            payload={**merged_payload, **(correlation_metadata or {})}, event_id=event_id)
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
