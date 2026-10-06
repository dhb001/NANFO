"""One Network authorization guard with an explicit lock policy (ADR-028).

Every Network-owned service authorizes through :class:`NetworkAccessGuard`:

1. Current authority is checked *before* any Network lock is requested, so a
   caller without authority can never queue on, or hold, a tenant's locks.
2. The requested :class:`LockPolicy` is acquired.
3. Authority is checked again against fresh READ COMMITTED state, because it may
   have been revoked (or the network deleted) while the caller waited.

Workspace/organization membership is resolved only through the Organization
module's public ``WorkspaceService`` (C5). It is imported lazily so importing the
Network module never imports the Organization module (no import cycle).
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from app.modules.network.outbox import NetworkOutboxRepository
from app.modules.network.repository import NetworkRepository


class LockPolicy(enum.Enum):
    """Network parent lock taken between the two authorization checks."""

    #: Reads: no Network lock.
    NONE = "none"
    #: ``FOR SHARE`` fence for write-authorized workflow creation (blocks deletion,
    #: compatible with other workflow creators).
    SHARE = "share"
    #: ``FOR UPDATE`` parent lock for campus-asset and device-group writers.
    EXCLUSIVE = "exclusive"
    #: Per-network advisory lock plus ``FOR UPDATE``: event-bearing inventory writes,
    #: campus buildings and inventory deletion (serializes outbox sequence allocation).
    INVENTORY = "inventory"


@dataclass(frozen=True, slots=True)
class NetworkGrant:
    """Authorized network plus the authoritative Organization-service tenant."""

    network: Any
    org_id: uuid.UUID

    @property
    def network_id(self) -> uuid.UUID:
        return self.network.network_id

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.network.workspace_id


def workspace_service(db, redis):
    """Organization's public workspace-membership service (lazy import, C5)."""
    from app.modules.organization.service import WorkspaceService

    return WorkspaceService(db=db, redis=redis)


def forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")


def network_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")


class NetworkAccessGuard:
    def __init__(self, db, *, networks: NetworkRepository | None = None, workspaces=None, redis=None):
        self._db = db
        self._networks = networks if networks is not None else NetworkRepository(db)
        self._workspaces = workspaces if workspaces is not None else workspace_service(db, redis)

    async def authorize(
        self, *, network_id: uuid.UUID, actor_user_id: str, requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None, require_write: bool = False, lock: LockPolicy = LockPolicy.NONE,
    ) -> NetworkGrant:
        """Check authority, then (optionally) lock and re-check under the lock."""
        grant = await self.check(
            network_id=network_id, actor_user_id=actor_user_id, requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id, require_write=require_write,
        )
        if lock is LockPolicy.NONE:
            return grant
        return await self.lock_and_check(
            network_id=network_id, actor_user_id=actor_user_id, requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id, require_write=require_write, lock=lock,
        )

    async def lock_and_check(
        self, *, network_id: uuid.UUID, actor_user_id: str, requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None, require_write: bool = True, lock: LockPolicy,
    ) -> NetworkGrant:
        """Acquire ``lock`` (the caller already authorized) and re-check authority."""
        if lock is LockPolicy.NONE or not require_write:
            raise ValueError("Network locks are only taken for already-authorized writes")
        if lock is LockPolicy.INVENTORY:
            await NetworkOutboxRepository(self._db).lock_inventory(network_id)
        elif lock is LockPolicy.EXCLUSIVE:
            await self._networks.lock_row(network_id)
        else:
            await self._networks.lock_active(network_id)
        return await self.check(
            network_id=network_id, actor_user_id=actor_user_id, requested_workspace_id=requested_workspace_id,
            claim_org_id=claim_org_id, require_write=require_write,
        )

    async def check(
        self, *, network_id: uuid.UUID, actor_user_id: str, requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None, require_write: bool = False,
    ) -> NetworkGrant:
        """Authorize against current state without taking any Network lock."""
        network = await self._networks.get_by_id(network_id)
        if network is None:
            raise network_not_found()
        workspace = await self.check_workspace(
            workspace_id=network.workspace_id, actor_user_id=actor_user_id,
            requested_workspace_id=requested_workspace_id, claim_org_id=claim_org_id, require_write=require_write,
        )
        return NetworkGrant(network=network, org_id=workspace.org_id)

    async def check_workspace(
        self, *, workspace_id: uuid.UUID, actor_user_id: str, requested_workspace_id: uuid.UUID | None = None,
        claim_org_id: uuid.UUID | None = None, require_write: bool = False,
    ):
        """Authorize a workspace-scoped operation (network creation/listing); no Network lock.

        Token scope claims only ever narrow access: a workspace claim must name this
        workspace and an organization claim must name its owning organization.
        """
        if requested_workspace_id is not None and workspace_id != requested_workspace_id:
            raise forbidden()
        workspace = await self._workspaces.assert_workspace_membership(
            workspace_id=workspace_id, user_id=actor_user_id, require_write=require_write,
        )
        if claim_org_id is not None and workspace.org_id != claim_org_id:
            raise forbidden()
        return workspace
