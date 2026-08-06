"""Unit tests for OrgService and WorkspaceService (app/modules/organization/service.py).

All external dependencies are mocked.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.organization.models import Organization, Workspace
from app.modules.organization.schemas import CreateOrgRequest, CreateWorkspaceRequest
from app.modules.organization.service import OrgService, WorkspaceService


def _make_org(slug: str = "test-org") -> Organization:
    org = MagicMock(spec=Organization)
    org.org_id = uuid.uuid4()
    org.name = "Test Org"
    org.slug = slug
    org.created_at = MagicMock()
    return org


def _make_workspace(org_id: uuid.UUID | None = None) -> Workspace:
    ws = MagicMock(spec=Workspace)
    ws.workspace_id = uuid.uuid4()
    ws.org_id = org_id or uuid.uuid4()
    ws.name = "Test Workspace"
    ws.description = None
    ws.created_at = MagicMock()
    return ws


@pytest.fixture
def org_svc(mock_db, fake_redis) -> OrgService:
    return OrgService(db=mock_db, redis=fake_redis)


@pytest.fixture
def ws_svc(mock_db, fake_redis) -> WorkspaceService:
    return WorkspaceService(db=mock_db, redis=fake_redis)


class TestOrgService:
    @pytest.mark.asyncio
    async def test_create_org_success(self, org_svc):
        org = _make_org()
        with (
            patch.object(org_svc._repo, "get_by_slug", return_value=None),
            patch.object(org_svc._repo, "create", return_value=org),
            patch("app.modules.organization.service.publish_event", new_callable=AsyncMock),
        ):
            result = await org_svc.create_org(
                req=CreateOrgRequest(name="Test Org", slug="test-org"),
                actor_id=str(uuid.uuid4()),
                correlation_id=str(uuid.uuid4()),
            )
        assert result.slug == "test-org"

    @pytest.mark.asyncio
    async def test_create_org_slug_conflict_raises_409(self, org_svc):
        existing = _make_org(slug="taken-slug")
        with patch.object(org_svc._repo, "get_by_slug", return_value=existing):
            with pytest.raises(HTTPException) as exc_info:
                await org_svc.create_org(
                    req=CreateOrgRequest(name="Any", slug="taken-slug"),
                    actor_id="u1",
                    correlation_id=str(uuid.uuid4()),
                )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_get_org_requires_membership(self, org_svc):
        """Non-member requesting an org must get 403 (Organization.md §6: cross-org leakage)."""
        org = _make_org()
        with (
            patch.object(org_svc._repo, "get_by_id", return_value=org),
            patch.object(org_svc._member_repo, "get_member", return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await org_svc.get_org(org_id=org.org_id, user_id=str(uuid.uuid4()))
        assert exc_info.value.status_code == 403


class TestWorkspaceService:
    @pytest.mark.asyncio
    async def test_create_workspace_success(self, ws_svc):
        org = _make_org()
        ws = _make_workspace(org_id=org.org_id)
        with (
            patch.object(ws_svc._org_repo, "get_by_id", return_value=org),
            patch.object(ws_svc._repo, "create", return_value=ws),
            patch("app.modules.organization.service.publish_event", new_callable=AsyncMock),
        ):
            result = await ws_svc.create_workspace(
                org_id=org.org_id,
                req=CreateWorkspaceRequest(name="WS1"),
                actor_id="u1",
                correlation_id=str(uuid.uuid4()),
            )
        assert result.workspace_id == ws.workspace_id

    @pytest.mark.asyncio
    async def test_create_workspace_org_not_found_raises_404(self, ws_svc):
        with patch.object(ws_svc._org_repo, "get_by_id", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await ws_svc.create_workspace(
                    org_id=uuid.uuid4(),
                    req=CreateWorkspaceRequest(name="WS1"),
                    actor_id="u1",
                    correlation_id=str(uuid.uuid4()),
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_active_workspace_not_found_raises_404(self, ws_svc):
        """C5: get_active_workspace() is the contract NetworkService calls."""
        with patch.object(ws_svc._repo, "get_by_id", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await ws_svc.get_active_workspace(uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_active_workspace_returns_workspace(self, ws_svc):
        ws = _make_workspace()
        with patch.object(ws_svc._repo, "get_by_id", return_value=ws):
            result = await ws_svc.get_active_workspace(ws.workspace_id)
        assert result is ws
