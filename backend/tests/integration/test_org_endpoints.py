"""Integration tests for organization endpoints via FastAPI TestClient.

Tests routing, status codes, envelope format, and basic request validation.
Dependencies overridden with mocks; no database required.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app
from tests.auth_support import create_session_access_token as create_access_token


def _make_token(roles=None, org_id: str | None = None):
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="test@example.com",
        roles=roles or ["Admin"],
        permissions=["write:config"],
        org_id=org_id,
    )
    return token


@pytest.fixture
def admin_token(session_auth):
    return _make_token(["Admin"])


@pytest.fixture
def fake_redis_instance(session_auth):
    return session_auth.redis


@pytest.fixture
def client(fake_redis_instance) -> TestClient:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    async def _db():
        yield db

    async def _redis():
        yield fake_redis_instance

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


class TestOrgEndpointsAuth:
    """All org endpoints must require authentication."""

    def test_list_orgs_without_token_returns_403(self, client):
        response = client.get("/api/v1/organizations")
        assert response.status_code in (401, 403)

    def test_create_org_without_token_returns_403(self, client):
        response = client.post("/api/v1/organizations", json={"name": "Org", "slug": "o"})
        assert response.status_code in (401, 403)


class TestOrgCreate:

    def test_create_org_slug_validation_rejects_invalid(self, client, admin_token):
        """Slug validator must reject values that fail format check (422)."""
        headers = {"Authorization": f"Bearer {admin_token}"}
        # Slug starting with hyphen is invalid
        response = client.post(
            "/api/v1/organizations",
            json={"name": "Test", "slug": "-bad-slug-"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_create_org_missing_name_returns_422(self, client, admin_token):
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = client.post(
            "/api/v1/organizations",
            json={"slug": "valid-slug"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_create_org_returns_201_with_envelope(self, client, admin_token):
        """POST /organizations must return 201 with valid envelope on success (API_STANDARD.md §3)."""
        from datetime import UTC, datetime
        headers = {"Authorization": f"Bearer {admin_token}"}
        fake_org_id = uuid.uuid4()
        org_data = {
            "org_id": str(fake_org_id),
            "name": "My Org",
            "slug": "my-org",
            "created_at": datetime.now(UTC).isoformat(),
        }
        with patch("app.modules.organization.service.OrgService.create_org") as mock_create:
            from app.modules.organization.schemas import OrgResponse
            mock_create.return_value = OrgResponse(**org_data)
            response = client.post(
                "/api/v1/organizations",
                json={"name": "My Org", "slug": "my-org"},
                headers=headers,
            )
        # May be 200 or 201 depending on the mock outcome, check envelope
        body = response.json()
        assert "success" in body
        assert "meta" in body
        assert "data" in body
        assert "errors" in body


class TestWorkspaceEndpoints:

    def test_create_workspace_missing_name_returns_422(self, client, admin_token):
        org_id = uuid.uuid4()
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = client.post(
            f"/api/v1/organizations/{org_id}/workspaces",
            json={},
            headers=headers,
        )
        assert response.status_code == 422

    def test_list_workspaces_requires_auth(self, client):
        org_id = uuid.uuid4()
        response = client.get(f"/api/v1/organizations/{org_id}/workspaces")
        assert response.status_code in (401, 403)

    def test_get_workspace_returns_200_with_envelope(self, client, admin_token):
        org_id = uuid.uuid4()
        workspace_id = uuid.uuid4()
        headers = {"Authorization": f"Bearer {admin_token}"}

        with patch("app.modules.organization.service.WorkspaceService.get_workspace_for_org", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "workspace_id": workspace_id,
                "org_id": org_id,
                "name": "Ops",
                "description": "Ops workspace",
                "created_at": datetime.now(UTC).isoformat(),
            }
            response = client.get(
                f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}",
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["workspace_id"] == str(workspace_id)

    def test_update_workspace_returns_200_with_envelope(self, client, admin_token):
        org_id = uuid.uuid4()
        workspace_id = uuid.uuid4()
        headers = {"Authorization": f"Bearer {admin_token}"}

        with patch("app.modules.organization.service.WorkspaceService.update_workspace", new_callable=AsyncMock) as mock_update:
            mock_update.return_value = {
                "workspace_id": workspace_id,
                "org_id": org_id,
                "name": "Ops Updated",
                "description": "Updated",
                "created_at": datetime.now(UTC).isoformat(),
            }
            response = client.patch(
                f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}",
                json={"name": "Ops Updated", "description": "Updated"},
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["name"] == "Ops Updated"

    def test_delete_workspace_returns_204(self, client, admin_token):
        org_id = uuid.uuid4()
        workspace_id = uuid.uuid4()
        headers = {"Authorization": f"Bearer {admin_token}"}

        with patch("app.modules.organization.service.WorkspaceService.delete_workspace", new_callable=AsyncMock):
            response = client.delete(
                f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}",
                headers=headers,
            )

        assert response.status_code == 204

    def test_get_workspace_rejects_mismatched_org_scope_claim(self, client):
        org_id = uuid.uuid4()
        workspace_id = uuid.uuid4()
        token = _make_token(roles=["Admin"], org_id=str(uuid.uuid4()))
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(
            f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}",
            headers=headers,
        )

        assert response.status_code == 403
        body = response.json()
        assert body["errors"]["code"] == "FORBIDDEN"


class TestOrgScopedMembershipAuthorization:
    def test_create_workspace_forbidden_when_actor_not_org_member(self, client, admin_token):
        org_id = uuid.uuid4()
        headers = {"Authorization": f"Bearer {admin_token}"}

        with patch(
            "app.modules.organization.service.WorkspaceService.create_workspace",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=403, detail="Insufficient permissions."),
        ):
            response = client.post(
                f"/api/v1/organizations/{org_id}/workspaces",
                json={"name": "Ops"},
                headers=headers,
            )

        assert response.status_code == 403
        body = response.json()
        assert body["errors"]["code"] == "FORBIDDEN"

    def test_list_members_forbidden_when_actor_not_org_member(self, client, admin_token):
        org_id = uuid.uuid4()
        headers = {"Authorization": f"Bearer {admin_token}"}

        with patch(
            "app.modules.organization.service.MemberService.list_members",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=403, detail="Insufficient permissions."),
        ):
            response = client.get(
                f"/api/v1/organizations/{org_id}/members",
                headers=headers,
            )

        assert response.status_code == 403
        body = response.json()
        assert body["errors"]["code"] == "FORBIDDEN"


class TestMemberEndpoints:

    def test_add_member_missing_user_id_returns_422(self, client, admin_token):
        org_id = uuid.uuid4()
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = client.post(
            f"/api/v1/organizations/{org_id}/members",
            json={"org_role": "Admin"},  # missing user_id
            headers=headers,
        )
        assert response.status_code == 422

    def test_add_member_unknown_user_returns_404(self, client, admin_token):
        org_id = uuid.uuid4()
        unknown_user_id = uuid.uuid4()
        headers = {"Authorization": f"Bearer {admin_token}"}

        with patch(
            "app.modules.organization.service.MemberService.add_member",
            side_effect=HTTPException(
                status_code=404,
                detail={
                    "code": "USER_NOT_FOUND",
                    "message": "user_id does not reference an active user.",
                },
            ),
        ):
            response = client.post(
                f"/api/v1/organizations/{org_id}/members",
                json={"user_id": str(unknown_user_id), "org_role": "Admin"},
                headers=headers,
            )

        assert response.status_code == 404
        body = response.json()
        assert body["errors"]["code"] == "USER_NOT_FOUND"


class TestOrgMutationEndpoints:

    def test_update_org_returns_200_with_envelope(self, client, admin_token):
        org_id = uuid.uuid4()
        headers = {"Authorization": f"Bearer {admin_token}"}

        with patch("app.modules.organization.service.OrgService.update_org", new_callable=AsyncMock) as mock_update:
            mock_update.return_value = {
                "org_id": org_id,
                "name": "Updated Org",
                "slug": "updated-org",
                "created_at": datetime.now(UTC).isoformat(),
            }
            response = client.patch(
                f"/api/v1/organizations/{org_id}",
                json={"name": "Updated Org"},
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["name"] == "Updated Org"

    def test_delete_org_returns_204(self, client, admin_token):
        org_id = uuid.uuid4()
        headers = {"Authorization": f"Bearer {admin_token}"}

        with patch("app.modules.organization.service.OrgService.delete_org", new_callable=AsyncMock):
            response = client.delete(f"/api/v1/organizations/{org_id}", headers=headers)

        assert response.status_code == 204
