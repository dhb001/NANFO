"""The common contract fixtures must exercise, not replace, authentication."""

import uuid

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.core.dependencies import get_current_user
from app.core.security import create_access_token, decode_token
from app.modules.identity.sessions import SessionRepository
from tests.auth_support import create_authorized_workspace, create_session_access_token


async def test_common_fixture_uses_current_identity_and_revocable_session(session_auth, mock_db):
    user_id = uuid.UUID(int=1)
    token, _ = create_session_access_token(
        user_id=str(user_id), email="fixture@example.com", roles=["Admin"], permissions=["write:config"],
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    claims = await get_current_user(credentials, session_auth.redis, mock_db)
    assert claims.roles == ["Admin"]

    session_auth.roles[user_id] = []
    claims = await get_current_user(credentials, session_auth.redis, mock_db)
    assert claims.roles == claims.permissions == []

    session_auth.users[user_id].is_active = False
    with pytest.raises(HTTPException) as denied:
        await get_current_user(credentials, session_auth.redis, mock_db)
    assert denied.value.status_code == 401

    session_auth.users[user_id].is_active = True
    await SessionRepository(session_auth.redis).revoke(decode_token(token)["sid"])
    with pytest.raises(HTTPException) as denied:
        await get_current_user(credentials, session_auth.redis, mock_db)
    assert denied.value.status_code == 401


async def test_common_fixture_does_not_authorize_unregistered_signed_token(session_auth, mock_db):
    token, _ = create_access_token(
        user_id=str(uuid.UUID(int=1)), email="unknown@example.com", roles=["Admin"], permissions=["write:config"],
    )
    with pytest.raises(HTTPException) as denied:
        await get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), session_auth.redis, mock_db,
        )
    assert denied.value.status_code == 401


async def test_tenant_fixture_requires_registered_workspace_and_current_membership(tenant_auth, mock_db):
    from app.modules.organization.service import WorkspaceService

    user_id = str(uuid.UUID(int=1))
    create_session_access_token(user_id=user_id, email="tenant@example.com", roles=["Admin"], permissions=[])
    workspace_id = create_authorized_workspace()
    service = WorkspaceService(mock_db, tenant_auth.redis)
    assert (await service.get_active_workspace(workspace_id, user_id=user_id)).workspace_id == workspace_id
    with pytest.raises(HTTPException):
        await service.get_active_workspace(uuid.UUID(int=99), user_id=user_id)
    tenant_auth.memberships.clear()
    with pytest.raises(HTTPException) as denied:
        await service.get_active_workspace(workspace_id, user_id=user_id)
    assert denied.value.status_code == 403
