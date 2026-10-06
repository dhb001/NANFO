"""C25 autonomy governance: two-person autonomous switch, Admin-only STOP clearing, audit.

* Switching to ``autonomous`` is two-person: the first ``PUT`` records a pending request in
  Redis (TTL <= 1 h, bound to the control revision and the exact requested mode/model/
  expiry); an identical ``PUT`` by a *different* user confirms it.
* Organization roles are answered by the Organization module's public services; this
  module never queries organization tables.
* Every mode request/approval, STOP, override and configuration change is written with
  Identity's ``append_audit_log`` in the caller's transaction (commits with the change).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.canonical import canonical_sha256
from app.core.logging import get_logger
from app.modules.autonomy.schemas import PendingApproval

logger = get_logger(__name__)

PENDING_TTL_SECONDS = 3600
_PENDING_KEY = "nanfo:autonomy:mode-approval:"
_DELETE_IF_EQUAL = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


def require_distinct_approver() -> bool:
    from app.core.config import get_settings

    return getattr(get_settings(), "AUTONOMY_REQUIRE_DISTINCT_APPROVER", True) is not False


def stop_allows_read_only() -> bool:
    from app.core.config import get_settings

    return getattr(get_settings(), "AUTONOMY_STOP_ALLOW_READ_ONLY", True) is not False


def pending_key(network_id) -> str:
    return f"{_PENDING_KEY}{network_id}"


def request_fingerprint(request) -> str:
    """Identity of an 'identical PUT': network, revision, mode, model and approval expiry."""
    return canonical_sha256({
        "network_id": str(request.network_id), "expected_revision": request.expected_revision,
        "mode": request.mode, "checkpoint_sha256": request.checkpoint_sha256,
        "approval_expires_at": request.approval_expires_at.isoformat() if request.approval_expires_at else None,
    })


@dataclass(frozen=True)
class PendingRequest:
    raw: str
    fingerprint: str
    workspace_id: uuid.UUID
    approval: PendingApproval

    @classmethod
    def parse(cls, raw):
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            body = json.loads(raw)
            return cls(raw=raw, fingerprint=body["fingerprint"], workspace_id=uuid.UUID(body["workspace_id"]),
                       approval=PendingApproval.model_validate(body["approval"]))
        except (ValueError, KeyError, TypeError):
            return None


async def read_pending(redis, network_id) -> PendingRequest | None:
    return PendingRequest.parse(await redis.get(pending_key(network_id)))


async def record_pending(redis, *, request, workspace_id, actor_id, correlation_id=None) -> PendingRequest:
    now = datetime.now(UTC)
    ttl = PENDING_TTL_SECONDS
    if request.approval_expires_at is not None:
        ttl = max(1, min(ttl, int((request.approval_expires_at - now).total_seconds())))
    approval = PendingApproval(requested_by_user_id=actor_id, mode=request.mode,
        expected_revision=request.expected_revision, checkpoint_sha256=request.checkpoint_sha256,
        approval_expires_at=request.approval_expires_at, requested_at=now, expires_at=now + timedelta(seconds=ttl))
    raw = json.dumps({"version": 1, "fingerprint": request_fingerprint(request), "workspace_id": str(workspace_id),
                      "correlation_id": str(correlation_id) if correlation_id else None,
                      "approval": approval.model_dump(mode="json")}, sort_keys=True, separators=(",", ":"))
    await redis.set(pending_key(request.network_id), raw, ex=ttl)
    return PendingRequest.parse(raw)


async def consume_pending(redis, network_id, pending: PendingRequest) -> None:
    """Best-effort compare-and-delete; a stale leftover is harmless (bound to an old revision)."""
    try:
        await redis.eval(_DELETE_IF_EQUAL, 1, pending_key(network_id), pending.raw)
    except Exception:  # noqa: BLE001 - revision fencing already prevents reuse
        logger.warning("autonomy_pending_approval_cleanup_failed", network_id=str(network_id))


async def discard_pending(redis, network_id) -> None:
    try:
        await redis.delete(pending_key(network_id))
    except Exception:  # noqa: BLE001 - a pending request is revision-bound; STOP already invalidated it
        logger.warning("autonomy_pending_approval_cleanup_failed", network_id=str(network_id))


async def workspace_org_id(db, redis, workspace_id) -> uuid.UUID | None:
    """The workspace's organization through Organization's public service (None if gone)."""
    from fastapi import HTTPException

    from app.modules.organization.service import WorkspaceService

    try:
        workspace = await WorkspaceService(db=db, redis=redis).get_active_workspace(workspace_id)
    except HTTPException:
        return None
    return workspace.org_id


async def caller_org_role(db, redis, *, workspace_id, user_id) -> str | None:
    """Caller's *current* org role for the workspace ('Admin'|'Operator'|'Read-Only'|None)."""
    from app.modules.organization.service import OrgService

    org_id = await workspace_org_id(db, redis, workspace_id)
    if org_id is None:
        return None
    return await OrgService(db, redis).get_caller_role(org_id=org_id, user_id=user_id)


def _actor_uuid(actor_id):
    try:
        return uuid.UUID(str(actor_id))
    except (TypeError, ValueError, AttributeError):
        return None


async def audit(db, redis, *, event_type, actor_id, network_id, workspace_id, correlation_id, metadata,
                resource_type="autonomy_control", resource_id=None, org_id=None):
    """Append an Identity audit row in the caller's transaction (never commits)."""
    from app.modules.identity.service import append_audit_log

    if org_id is None:
        org_id = await workspace_org_id(db, redis, workspace_id)
    await append_audit_log(
        db=db, event_type=event_type, actor_id=_actor_uuid(actor_id), resource_type=resource_type,
        resource_id=resource_id or network_id, org_id=org_id,
        correlation_id=correlation_id or uuid.uuid4(),
        metadata={"network_id": str(network_id), "workspace_id": str(workspace_id), **metadata},
    )
