"""History router contracts with real session authorization and owner boundaries."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app
from tests.auth_support import create_session_access_token


@pytest.fixture
def history_client(session_auth):
    async def db():
        yield AsyncMock()

    async def redis():
        yield session_auth.redis

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_redis] = redis
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def headers(workspace_id=None, permissions=None):
    token, _ = create_session_access_token(
        user_id=str(uuid.uuid4()), email="history@example.com", roles=["Operator"] if permissions is None else ["NoAccess"],
        permissions=["read:topology"] if permissions is None else permissions,
        workspace_id=str(workspace_id) if workspace_id else None,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("path,service", [
    ("simulations", "app.modules.simulation.history.SimulationHistoryService"),
    ("intents", "app.modules.intent.history.IntentHistoryService"),
])
def test_history_contract_and_claim_narrowing(history_client, path, service):
    workspace, network = uuid.uuid4(), uuid.uuid4()
    page = {"items": [], "total": 41, "page": 4, "page_size": 20}
    with patch(f"{service}.list_page", new=AsyncMock(return_value=page)) as listing:
        response = history_client.get(f"/api/v1/{path}", headers=headers(workspace), params={
            "workspace_id": str(workspace), "network_id": str(network), "page": 4,
        })
        assert response.status_code == 200, response.text
        assert response.json()["data"] == page
        assert response.json()["success"] is True
        assert listing.call_args.kwargs["network_id"] == network
        listing.reset_mock()
        denied = history_client.get(f"/api/v1/{path}", headers=headers(workspace),
                                    params={"workspace_id": str(uuid.uuid4())})
        assert denied.status_code == 403
        listing.assert_not_awaited()
        denied = history_client.get(f"/api/v1/{path}", headers=headers(permissions=[]),
                                    params={"workspace_id": str(workspace)})
        assert denied.status_code == 403
        listing.assert_not_awaited()


@pytest.mark.parametrize("path", ["simulations", "intents"])
@pytest.mark.parametrize("params", [
    {}, {"workspace_id": "invalid"}, {"page": 0}, {"page_size": 0},
    {"page_size": 201}, {"network_id": "invalid"},
])
def test_history_validates_required_scope_and_page_bounds(history_client, path, params):
    query = {"workspace_id": str(uuid.uuid4()), **params} if params else {}
    response = history_client.get(f"/api/v1/{path}", headers=headers(), params=query)
    assert response.status_code == 422
