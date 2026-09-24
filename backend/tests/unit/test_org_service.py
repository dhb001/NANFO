"""Unit tests for OrgService and WorkspaceService (app/modules/organization/service.py).

All external dependencies are mocked.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.organization.models import Organization, Workspace
from app.modules.organization.schemas import CreateOrgRequest, CreateWorkspaceRequest
from app.modules.organization.service import MemberService, OrgService, WorkspaceService


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


def _make_member(org_id: uuid.UUID, user_id: uuid.UUID, org_role: str = "Admin") -> MagicMock:
    member = MagicMock()
    member.org_id = org_id
    member.user_id = user_id
    member.org_role = org_role
    member.created_at = datetime.now(UTC)
    return member


@pytest.fixture
def audit_append():
    with patch("app.modules.organization.service.append_audit_log", new_callable=AsyncMock) as append:
        yield append


@pytest.fixture
def org_svc(mock_db, fake_redis, audit_append) -> OrgService:
    return OrgService(db=mock_db, redis=fake_redis)


@pytest.fixture
def ws_svc(mock_db, fake_redis, audit_append) -> WorkspaceService:
    svc = WorkspaceService(db=mock_db, redis=fake_redis)
    svc._org_repo.get_by_id = AsyncMock(return_value=_make_org())
    return svc


@pytest.fixture
def member_svc(mock_db, fake_redis, audit_append) -> MemberService:
    svc = MemberService(db=mock_db, redis=fake_redis)
    svc._org_repo.get_by_id = AsyncMock(return_value=_make_org())
    return svc


class TestOrgService:
    @pytest.mark.asyncio
    async def test_create_org_success(self, org_svc):
        org = _make_org()
        actor_id = str(uuid.uuid4())
        with (
            patch.object(org_svc._repo, "get_by_slug", return_value=None),
            patch.object(org_svc._repo, "create", return_value=org),
            patch.object(org_svc._member_repo, "add_member", new_callable=AsyncMock) as mock_add_member,
            patch("app.modules.organization.service.publish_event", new_callable=AsyncMock),
        ):
            result = await org_svc.create_org(
                req=CreateOrgRequest(name="Test Org", slug="test-org"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )
        assert result.slug == "test-org"
        assert mock_add_member.await_count == 1
        assert mock_add_member.await_args.kwargs["org_role"] == "Admin"

    @pytest.mark.asyncio
    async def test_create_org_event_publish_failure_is_fail_open(self, org_svc):
        org = _make_org()
        actor_id = str(uuid.uuid4())
        with (
            patch.object(org_svc._repo, "get_by_slug", return_value=None),
            patch.object(org_svc._repo, "create", return_value=org),
            patch.object(org_svc._member_repo, "add_member", new_callable=AsyncMock) as mock_add_member,
            patch(
                "app.modules.organization.service.publish_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("stream unavailable"),
            ),
        ):
            result = await org_svc.create_org(
                req=CreateOrgRequest(name="Test Org", slug="test-org"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert result.slug == "test-org"
        assert mock_add_member.await_count == 1

    @pytest.mark.asyncio
    async def test_create_org_slug_conflict_raises_409(self, org_svc):
        existing = _make_org(slug="taken-slug")
        with (
            patch.object(org_svc._repo, "get_by_slug", return_value=existing),
            pytest.raises(HTTPException) as exc_info,
        ):
            await org_svc.create_org(
                req=CreateOrgRequest(name="Any", slug="taken-slug"),
                actor_id="u1",
                correlation_id=str(uuid.uuid4()),
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_get_org_requires_membership(self, org_svc):
        """Non-member and absent orgs are indistinguishable (Organization.md §6, ADR-028 C6)."""
        org = _make_org()
        with (
            patch.object(org_svc._repo, "get_by_id", return_value=org),
            patch.object(org_svc._member_repo, "get_member", return_value=None),
            pytest.raises(HTTPException) as exc_info,
        ):
            await org_svc.get_org(org_id=org.org_id, user_id=str(uuid.uuid4()))
        with (
            patch.object(org_svc._repo, "get_by_id", return_value=None),
            pytest.raises(HTTPException) as absent,
        ):
            await org_svc.get_org(org_id=uuid.uuid4(), user_id=str(uuid.uuid4()))
        assert exc_info.value.status_code == 404
        assert (exc_info.value.status_code, exc_info.value.detail) == (absent.value.status_code, absent.value.detail)

    @pytest.mark.asyncio
    async def test_update_org_success_and_event_publish(self, org_svc):
        org = _make_org(slug="updatable-org")
        actor_id = str(uuid.uuid4())
        with (
            patch.object(org_svc._repo, "get_by_id", return_value=org),
            patch.object(org_svc._member_repo, "get_member", return_value=_make_member(org.org_id, uuid.UUID(actor_id))),
            patch.object(org_svc._repo, "update", return_value=org),
            patch("app.modules.organization.service.publish_event", new_callable=AsyncMock) as mock_publish,
        ):
            result = await org_svc.update_org(
                org_id=org.org_id,
                user_id=actor_id,
                name="Updated Org",
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert result.org_id == org.org_id
        assert mock_publish.await_count == 1
        assert mock_publish.await_args.kwargs["event_type"] == "org.organization.updated"

    @pytest.mark.asyncio
    async def test_delete_org_success_and_event_publish(self, org_svc):
        org = _make_org(slug="deletable-org")
        actor_id = str(uuid.uuid4())
        with (
            patch.object(org_svc._repo, "get_by_id", return_value=org),
            patch.object(org_svc._member_repo, "get_member", return_value=_make_member(org.org_id, uuid.UUID(actor_id))),
            patch.object(org_svc._repo, "soft_delete", new_callable=AsyncMock),
            patch("app.modules.organization.service.WorkspaceRepository.list_for_org", return_value=([], 0)),
            patch("app.modules.organization.service.publish_event", new_callable=AsyncMock) as mock_publish,
        ):
            await org_svc.delete_org(
                org_id=org.org_id,
                user_id=actor_id,
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert mock_publish.await_count == 1
        assert mock_publish.await_args.kwargs["event_type"] == "org.organization.deleted"


class TestWorkspaceService:
    @pytest.mark.asyncio
    async def test_create_workspace_success(self, ws_svc):
        org = _make_org()
        ws = _make_workspace(org_id=org.org_id)
        actor_user_id = str(uuid.uuid4())
        with (
            patch.object(ws_svc._org_repo, "get_by_id", return_value=org),
            patch.object(ws_svc._member_repo, "get_member", return_value=_make_member(org.org_id, uuid.UUID(actor_user_id))),
            patch.object(ws_svc._repo, "create", return_value=ws),
            patch("app.modules.organization.service.publish_event", new_callable=AsyncMock),
        ):
            result = await ws_svc.create_workspace(
                org_id=org.org_id,
                req=CreateWorkspaceRequest(name="WS1"),
                actor_id=actor_user_id,
                user_id=actor_user_id,
                correlation_id=str(uuid.uuid4()),
            )
        assert result.workspace_id == ws.workspace_id

    @pytest.mark.asyncio
    async def test_create_workspace_event_publish_failure_is_fail_open(self, ws_svc):
        org = _make_org()
        ws = _make_workspace(org_id=org.org_id)
        actor_user_id = str(uuid.uuid4())
        with (
            patch.object(ws_svc._org_repo, "get_by_id", return_value=org),
            patch.object(ws_svc._member_repo, "get_member", return_value=_make_member(org.org_id, uuid.UUID(actor_user_id))),
            patch.object(ws_svc._repo, "create", return_value=ws),
            patch(
                "app.modules.organization.service.publish_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("stream unavailable"),
            ),
        ):
            result = await ws_svc.create_workspace(
                org_id=org.org_id,
                req=CreateWorkspaceRequest(name="WS1"),
                actor_id=actor_user_id,
                user_id=actor_user_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert result.workspace_id == ws.workspace_id

    @pytest.mark.asyncio
    async def test_create_workspace_org_not_found_raises_404(self, ws_svc):
        with (
            patch.object(ws_svc._org_repo, "get_by_id", return_value=None),
            pytest.raises(HTTPException) as exc_info,
        ):
            await ws_svc.create_workspace(
                org_id=uuid.uuid4(),
                req=CreateWorkspaceRequest(name="WS1"),
                actor_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
                correlation_id=str(uuid.uuid4()),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_workspaces_requires_membership(self, ws_svc):
        org_id = uuid.uuid4()
        with (
            patch.object(ws_svc._member_repo, "get_member", return_value=None),
            pytest.raises(HTTPException) as exc_info,
        ):
            await ws_svc.list_workspaces(
                org_id=org_id,
                user_id=str(uuid.uuid4()),
                page=1,
                page_size=20,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_active_workspace_not_found_raises_404(self, ws_svc):
        """C5: get_active_workspace() is the contract NetworkService calls."""
        with (
            patch.object(ws_svc._repo, "get_by_id", return_value=None),
            pytest.raises(HTTPException) as exc_info,
        ):
            await ws_svc.get_active_workspace(uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_active_workspace_returns_workspace(self, ws_svc):
        ws = _make_workspace()
        with patch.object(ws_svc._repo, "get_by_id", return_value=ws):
            result = await ws_svc.get_active_workspace(ws.workspace_id)
        assert result is ws

    @pytest.mark.asyncio
    async def test_get_active_workspace_with_user_id_enforces_org_membership(self, ws_svc):
        ws = _make_workspace()
        user_id = str(uuid.uuid4())
        with (
            patch.object(ws_svc._repo, "get_by_id", return_value=ws),
            patch.object(ws_svc, "_assert_org_membership", new_callable=AsyncMock) as mock_assert,
        ):
            result = await ws_svc.get_active_workspace(ws.workspace_id, user_id=user_id)

        mock_assert.assert_awaited_once_with(org_id=ws.org_id, user_id=user_id, require_write=False)
        assert result is ws

    @pytest.mark.asyncio
    async def test_get_active_workspace_claim_org_mismatch_raises_403(self, ws_svc):
        ws = _make_workspace()
        with (
            patch.object(ws_svc._repo, "get_by_id", return_value=ws),
            pytest.raises(HTTPException) as exc_info,
        ):
            await ws_svc.get_active_workspace(ws.workspace_id, claim_org_id=uuid.uuid4())

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_assert_workspace_membership_returns_workspace(self, ws_svc):
        ws = _make_workspace()
        user_id = str(uuid.uuid4())
        with (
            patch.object(ws_svc, "get_active_workspace", new_callable=AsyncMock, return_value=ws) as mock_get,
        ):
            result = await ws_svc.assert_workspace_membership(workspace_id=ws.workspace_id, user_id=user_id)

        mock_get.assert_awaited_once_with(ws.workspace_id, user_id=user_id, require_write=False)
        assert result is ws

    @pytest.mark.asyncio
    async def test_get_workspace_for_org_returns_workspace(self, ws_svc):
        ws = _make_workspace()
        actor_user_id = str(uuid.uuid4())
        with (
            patch.object(ws_svc._member_repo, "get_member", return_value=_make_member(ws.org_id, uuid.UUID(actor_user_id))),
            patch.object(ws_svc._repo, "get_by_org_and_id", return_value=ws),
        ):
            result = await ws_svc.get_workspace_for_org(
                org_id=ws.org_id,
                workspace_id=ws.workspace_id,
                user_id=actor_user_id,
            )
        assert result.workspace_id == ws.workspace_id

    @pytest.mark.asyncio
    async def test_update_workspace_success_and_event_publish(self, ws_svc):
        ws = _make_workspace()
        actor_id = str(uuid.uuid4())
        with (
            patch.object(ws_svc._member_repo, "get_member", return_value=_make_member(ws.org_id, uuid.UUID(actor_id))),
            patch.object(ws_svc._repo, "get_by_org_and_id", return_value=ws),
            patch.object(ws_svc._repo, "update", return_value=ws),
            patch("app.modules.organization.service.publish_event", new_callable=AsyncMock) as mock_publish,
        ):
            result = await ws_svc.update_workspace(
                org_id=ws.org_id,
                workspace_id=ws.workspace_id,
                name="Updated Workspace",
                description="Updated description",
                actor_id=actor_id,
                user_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert result.workspace_id == ws.workspace_id
        assert mock_publish.await_count == 1
        assert mock_publish.await_args.kwargs["event_type"] == "org.workspace.updated"

    @pytest.mark.asyncio
    async def test_delete_workspace_success_and_event_publish(self, ws_svc):
        ws = _make_workspace()
        actor_id = str(uuid.uuid4())
        with (
            patch.object(ws_svc._member_repo, "get_member", return_value=_make_member(ws.org_id, uuid.UUID(actor_id))),
            patch.object(ws_svc._repo, "get_by_org_and_id", return_value=ws),
            patch.object(ws_svc._repo, "soft_delete", new_callable=AsyncMock),
            patch("app.modules.network.service.NetworkService.list_networks", return_value=SimpleNamespace(total=0)),
            patch("app.modules.organization.service.publish_event", new_callable=AsyncMock) as mock_publish,
        ):
            await ws_svc.delete_workspace(
                org_id=ws.org_id,
                workspace_id=ws.workspace_id,
                actor_id=actor_id,
                user_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert mock_publish.await_count == 1
        assert mock_publish.await_args.kwargs["event_type"] == "org.workspace.deleted"


class TestMemberService:
    @pytest.mark.asyncio
    async def test_add_member_validates_identity_user_exists(self, member_svc):
        org = _make_org()
        actor_user_id = str(uuid.uuid4())
        with (
            patch.object(member_svc._org_repo, "get_by_id", return_value=org),
            patch.object(member_svc._repo, "get_member", return_value=_make_member(org.org_id, uuid.UUID(actor_user_id))),
            patch.object(member_svc._identity_directory, "user_exists", return_value=False),
            pytest.raises(HTTPException) as exc_info,
        ):
            await member_svc.add_member(
                org_id=org.org_id,
                user_id=uuid.uuid4(),
                org_role="Operator",
                actor_id=actor_user_id,
                actor_user_id=actor_user_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["code"] == "USER_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_add_member_success(self, member_svc):
        org = _make_org()
        user_id = uuid.uuid4()
        member = _make_member(org.org_id, user_id)
        actor_user_id = str(uuid.uuid4())
        actor_member = _make_member(org.org_id, uuid.UUID(actor_user_id))

        with (
            patch.object(member_svc._org_repo, "get_by_id", return_value=org),
            patch.object(member_svc._identity_directory, "user_exists", return_value=True),
            patch.object(member_svc._repo, "get_member", side_effect=[actor_member, actor_member, None]),
            patch.object(member_svc._repo, "add_member", return_value=member),
            patch("app.modules.organization.service.publish_event", new_callable=AsyncMock),
        ):
            result = await member_svc.add_member(
                org_id=org.org_id,
                user_id=user_id,
                org_role="Admin",
                actor_id=actor_user_id,
                actor_user_id=actor_user_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert result.user_id == user_id
        assert result.org_role == "Admin"

    @pytest.mark.asyncio
    async def test_add_member_event_publish_failure_is_fail_open(self, member_svc):
        org = _make_org()
        user_id = uuid.uuid4()
        member = _make_member(org.org_id, user_id)
        actor_user_id = str(uuid.uuid4())
        actor_member = _make_member(org.org_id, uuid.UUID(actor_user_id))

        with (
            patch.object(member_svc._org_repo, "get_by_id", return_value=org),
            patch.object(member_svc._identity_directory, "user_exists", return_value=True),
            patch.object(member_svc._repo, "get_member", side_effect=[actor_member, actor_member, None]),
            patch.object(member_svc._repo, "add_member", return_value=member),
            patch(
                "app.modules.organization.service.publish_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("stream unavailable"),
            ),
        ):
            result = await member_svc.add_member(
                org_id=org.org_id,
                user_id=user_id,
                org_role="Admin",
                actor_id=actor_user_id,
                actor_user_id=actor_user_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert result.user_id == user_id

    @pytest.mark.asyncio
    async def test_list_members_requires_actor_membership(self, member_svc):
        org_id = uuid.uuid4()
        with (
            patch.object(member_svc._repo, "get_member", return_value=None),
            pytest.raises(HTTPException) as exc_info,
        ):
            await member_svc.list_members(
                org_id=org_id,
                actor_user_id=str(uuid.uuid4()),
                page=1,
                page_size=20,
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_remove_member_event_publish_failure_is_fail_open(self, member_svc):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        member = _make_member(org_id, user_id)
        actor_user_id = str(uuid.uuid4())
        actor_member = _make_member(org_id, uuid.UUID(actor_user_id))

        with (
            patch.object(member_svc._repo, "get_member", side_effect=[actor_member, actor_member, member]),
            patch.object(member_svc._repo, "remove_member", new_callable=AsyncMock),
            patch.object(member_svc._repo, "list_admin_ids", return_value=[uuid.UUID(actor_user_id)]),
            patch.object(member_svc._identity_directory, "can_administer_organization", return_value=True),
            patch(
                "app.modules.organization.service.publish_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("stream unavailable"),
            ),
        ):
            await member_svc.remove_member(
                org_id=org_id,
                user_id=user_id,
                actor_id=actor_user_id,
                actor_user_id=actor_user_id,
                correlation_id=str(uuid.uuid4()),
            )
