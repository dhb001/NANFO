"""HTTP dependency checks retain real signed JWTs and Redis session validation."""

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.dependencies import (
    TokenClaims,
    get_current_user,
    get_db,
    get_redis,
    require_permissions,
    require_roles,
)
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414


async def test_rest_rechecks_current_identity_and_rejects_refresh(ws_identity, mock_db):
    state = ws_identity
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: state.redis

    @app.get("/identity")
    async def identity(claims: Annotated[TokenClaims, Depends(get_current_user)]):
        return {"roles": claims.roles, "permissions": claims.permissions}

    @app.get("/admin")
    async def admin(claims: Annotated[TokenClaims, Depends(require_roles("Admin"))]):
        return {}

    @app.get("/read")
    async def read(claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))]):
        return {}

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {state.token}"}
        assert client.get("/identity").status_code == 401
        assert client.get("/identity", headers={"Authorization": f"Bearer {state.refresh}"}).status_code == 401
        assert client.get("/identity", headers=headers).json()["roles"] == ["Read-Only"]
        assert client.get("/admin", headers=headers).status_code == 403
        assert client.get("/read", headers=headers).status_code == 200
        state.roles, state.permissions = [], []
        assert client.get("/read", headers=headers).status_code == 403
        state.user.is_active = False
        assert client.get("/identity", headers=headers).status_code == 401
