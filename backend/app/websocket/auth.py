"""Shared strict identity, capability and tenant checks for every WS channel."""

from __future__ import annotations

import uuid

from fastapi import HTTPException

from app.db.postgres import AsyncSessionLocal
from app.db.redis import get_redis_client
from app.modules.identity.service import AuthService
from app.modules.network.service import NetworkService
from app.modules.organization.service import OrgService, WorkspaceService

CHANNEL_PERMISSIONS = {
    "topology": "read:topology",
    "digital-twin": "read:topology",
    "telemetry": "read:telemetry",
    "alerts": "read:telemetry",
}


async def authenticate(token: str, channel: str) -> dict:
    async with AsyncSessionLocal() as db:
        claims = await AuthService(db, get_redis_client()).authenticate_access(token)
    if not claims["roles"] or CHANNEL_PERMISSIONS[channel] not in claims["permissions"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions.")
    return claims


async def alert_workspaces(*, db, claims: dict) -> set[str]:
    """Unscoped login tokens see only active workspaces in current memberships."""
    redis = get_redis_client()
    orgs = OrgService(db, redis)
    workspaces = WorkspaceService(db, redis)
    user_id = claims["sub"]
    org_id = uuid.UUID(claims["org_id"]) if claims.get("org_id") else None
    if claims.get("workspace_id"):
        workspace = await workspaces.get_active_workspace(
            uuid.UUID(claims["workspace_id"]), user_id=user_id, claim_org_id=org_id,
        )
        await orgs.get_org(workspace.org_id, user_id=user_id)
        return {str(workspace.workspace_id)}

    allowed: set[str] = set()
    page = 1
    while True:
        memberships = await orgs.list_orgs(user_id=user_id, page=page, page_size=100)
        for org in memberships.items:
            if org_id is not None and org.org_id != org_id:
                continue
            await orgs.get_org(org.org_id, user_id=user_id)
            workspace_page = 1
            while True:
                result = await workspaces.list_workspaces(
                    org_id=org.org_id, user_id=user_id, page=workspace_page, page_size=100,
                )
                allowed.update(str(item.workspace_id) for item in result.items)
                if not result.items or workspace_page * 100 >= result.total:
                    break
                workspace_page += 1
        if not memberships.items or page * 100 >= memberships.total:
            break
        page += 1
    return allowed


async def authorized_workspaces(*, token: str, channel: str, network_id: str | None) -> set[str]:
    claims = await authenticate(token, channel)
    async with AsyncSessionLocal() as db:
        if channel == "alerts":
            return await alert_workspaces(db=db, claims=claims)
        redis = get_redis_client()
        network = await NetworkService(db, redis).assert_network_workspace_access(
            network_id=uuid.UUID(network_id),
            requested_workspace_id=uuid.UUID(claims["workspace_id"]) if claims.get("workspace_id") else None,
            actor_user_id=claims["sub"],
            claim_org_id=uuid.UUID(claims["org_id"]) if claims.get("org_id") else None,
        )
        workspace = await WorkspaceService(db, redis).get_active_workspace(
            network.workspace_id, user_id=claims["sub"],
            claim_org_id=uuid.UUID(claims["org_id"]) if claims.get("org_id") else None,
        )
        await OrgService(db, redis).get_org(workspace.org_id, user_id=claims["sub"])
        return {str(workspace.workspace_id)}
