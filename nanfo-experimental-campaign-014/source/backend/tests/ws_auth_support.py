"""WS fixtures retain production JWT/session/RBAC checks; mock only external services."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.security import create_access_token, create_refresh_token, decode_token
from app.modules.identity.repository import UserRepository
from app.modules.identity.sessions import SessionRepository
from app.modules.network.service import NetworkService
from app.modules.organization.service import OrgService, WorkspaceService


@pytest.fixture
async def ws_identity(fake_redis, mock_db):
    user = SimpleNamespace(user_id=uuid.UUID(int=1), email="ws@example.com", is_active=True)
    org_a, org_b = uuid.UUID(int=2), uuid.UUID(int=3)
    ws_a, ws_b = uuid.UUID(int=4), uuid.UUID(int=5)
    network_id = uuid.UUID(int=6)
    state = SimpleNamespace(
        user=user, roles=["Read-Only"], permissions=["read:topology", "read:telemetry"],
        memberships={org_a: {ws_a}, org_b: {ws_b}},
        workspace_id=str(ws_a), other_workspace_id=str(ws_b), network_id=str(network_id),
        org_id=str(org_a), redis=fake_redis,
    )
    sid = str(uuid.UUID(int=7))
    state.token, _ = create_access_token(
        user_id=str(user.user_id), sid=sid, email=user.email,
        roles=["Admin"], permissions=["write:config"],
    )
    state.refresh, _ = create_refresh_token(user_id=str(user.user_id), sid=sid)
    await SessionRepository(fake_redis).create(decode_token(state.refresh, token_type="refresh"), state.refresh)
    state.claims = decode_token(state.token)

    async def get_org(org_id, user_id):
        from fastapi import HTTPException
        if org_id not in state.memberships:
            raise HTTPException(status_code=403)
        return SimpleNamespace(org_id=org_id)

    async def list_orgs(user_id, page, page_size):
        items = [SimpleNamespace(org_id=org) for org in state.memberships]
        return SimpleNamespace(items=items[(page - 1) * page_size:page * page_size], total=len(items))

    async def list_workspaces(org_id, user_id, page, page_size):
        await get_org(org_id, user_id)
        items = [SimpleNamespace(workspace_id=ws) for ws in state.memberships[org_id]]
        return SimpleNamespace(items=items[(page - 1) * page_size:page * page_size], total=len(items))

    async def get_workspace(workspace_id, user_id, claim_org_id=None):
        from fastapi import HTTPException
        for org, workspaces in state.memberships.items():
            if workspace_id in workspaces and (claim_org_id is None or claim_org_id == org):
                return SimpleNamespace(workspace_id=workspace_id, org_id=org)
        raise HTTPException(status_code=403)

    async def get_network(network_id, requested_workspace_id, actor_user_id, claim_org_id):
        from fastapi import HTTPException
        if str(network_id) != state.network_id or requested_workspace_id not in (None, ws_a):
            raise HTTPException(status_code=403)
        await get_workspace(ws_a, actor_user_id, claim_org_id)
        return SimpleNamespace(network_id=network_id, workspace_id=ws_a)

    cm = AsyncMock()
    cm.__aenter__.return_value = mock_db
    with (
        patch("app.websocket.auth.AsyncSessionLocal", return_value=cm),
        patch("app.websocket.auth.get_redis_client", return_value=fake_redis),
        patch("app.websocket.manager.get_redis_client", return_value=fake_redis),
        patch.object(UserRepository, "get_by_id", side_effect=lambda _: state.user),
        patch.object(UserRepository, "get_roles_for_user", side_effect=lambda _: state.roles),
        patch.object(UserRepository, "get_permissions_for_roles", side_effect=lambda _: state.permissions),
        patch.object(OrgService, "get_org", side_effect=get_org),
        patch.object(OrgService, "list_orgs", side_effect=list_orgs),
        patch.object(WorkspaceService, "get_active_workspace", side_effect=get_workspace),
        patch.object(WorkspaceService, "list_workspaces", side_effect=list_workspaces),
        patch.object(NetworkService, "assert_network_workspace_access", side_effect=get_network),
    ):
        yield state
