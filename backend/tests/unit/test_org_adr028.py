"""ADR-028 Organization regressions: C6 caller role/uniform 404, lock-before-authz, inventory port."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.core.dependencies import get_db, get_redis
from app.modules.organization.repository import MemberOrganization, OrganizationRepository
from app.modules.organization.schemas import CreateOrgRequest
from app.modules.organization.service import MemberService, OrgService, WorkspaceService
from tests.auth_support import create_session_access_token

ORG = uuid.UUID(int=900)
ACTOR = uuid.UUID(int=901)
NOW = datetime(2026, 9, 23, tzinfo=UTC)


def _org(org_id=ORG):
    return SimpleNamespace(org_id=org_id, name="Org", slug="org", created_at=NOW)


def _member(role):
    return SimpleNamespace(org_id=ORG, user_id=ACTOR, org_role=role, created_at=NOW, deleted_at=None)


@pytest.fixture
def audit_append():
    with patch("app.modules.organization.service.append_audit_log", new_callable=AsyncMock) as append:
        yield append


@pytest.fixture
def org_svc(mock_db, fake_redis, audit_append):
    svc = OrgService(mock_db, fake_redis)
    svc._repo.get_by_id = AsyncMock(return_value=_org())
    svc._repo.lock = AsyncMock()
    svc._repo.update = AsyncMock(side_effect=lambda org, **kw: org)
    return svc


# ── C6: caller role and uniform not-found ────────────────────────────────────

@pytest.mark.parametrize("role", ["Admin", "Operator", "Read-Only"])
async def test_get_org_reports_the_callers_role(org_svc, role):
    org_svc._member_repo.get_member = AsyncMock(return_value=_member(role))
    assert (await org_svc.get_org(ORG, str(ACTOR))).caller_role == role


async def test_absent_and_foreign_organizations_are_indistinguishable(org_svc):
    org_svc._member_repo.get_member = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as foreign:
        await org_svc.get_org(ORG, str(ACTOR))
    org_svc._repo.get_by_id = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as absent:
        await org_svc.get_org(uuid.uuid4(), str(ACTOR))
    assert (foreign.value.status_code, foreign.value.detail) == (absent.value.status_code, absent.value.detail)
    assert foreign.value.status_code == 404


async def test_list_orgs_carries_caller_role_from_the_single_listing_query(org_svc):
    rows = [MemberOrganization(org_id=ORG, name="Org", slug="org", created_at=NOW, caller_role="Operator")]
    org_svc._repo.list_for_user = AsyncMock(return_value=(rows, 1))
    org_svc._member_repo.get_member = AsyncMock(side_effect=AssertionError("per-row lookup"))
    listing = await org_svc.list_orgs(str(ACTOR), page=1, page_size=20, include_caller_role=True)
    assert [(item.org_id, item.caller_role) for item in listing.items] == [(ORG, "Operator")]


async def test_list_orgs_role_fallback_only_when_requested(org_svc):
    org_svc._repo.list_for_user = AsyncMock(return_value=([_org()], 1))
    org_svc._member_repo.get_member = AsyncMock(return_value=_member("Read-Only"))
    plain = await org_svc.list_orgs(str(ACTOR), page=1, page_size=20)
    org_svc._member_repo.get_member.assert_not_awaited()
    assert plain.items[0].caller_role is None
    detailed = await org_svc.list_orgs(str(ACTOR), page=1, page_size=20, include_caller_role=True)
    assert detailed.items[0].caller_role == "Read-Only"


async def test_listing_query_joins_membership_role_once(mock_db):
    statements = []

    async def execute(statement):
        statements.append(statement)
        result = MagicMock()
        result.scalar_one.return_value = 1
        result.all.return_value = [(SimpleNamespace(**vars(_org())), "Admin")]
        return result

    mock_db.execute = execute
    rows, total = await OrganizationRepository(mock_db).list_for_user(ACTOR, page=2, page_size=5)
    assert total == 1 and rows == [MemberOrganization(org_id=ORG, name="Org", slug="org", created_at=NOW,
                                                      caller_role="Admin")]
    sql = str(statements[-1].compile(dialect=postgresql.dialect()))
    assert "org_role" in sql and "JOIN" in sql and "org_members.deleted_at IS NULL" in sql
    assert "LIMIT" in sql and len(statements) == 2  # count + page, no per-row role queries


async def test_create_and_update_report_admin_caller_role(org_svc, mock_db):
    created = SimpleNamespace(org_id=ORG, name="Org", slug="org", created_at=NOW)
    org_svc._repo.get_by_slug = AsyncMock(return_value=None)
    org_svc._repo.create = AsyncMock(return_value=created)
    org_svc._member_repo.add_member = AsyncMock()
    assert (await org_svc.create_org(CreateOrgRequest(name="Org", slug="org"), str(ACTOR), "c")).caller_role == "Admin"
    org_svc._member_repo.get_member = AsyncMock(return_value=_member("Admin"))
    updated = await org_svc.update_org(org_id=ORG, user_id=str(ACTOR), name="New", actor_id=str(ACTOR),
                                       correlation_id="c")
    assert updated.caller_role == "Admin"


async def test_slug_conflicts_use_a_generic_message(org_svc, mock_db):
    org_svc._repo.get_by_slug = AsyncMock(return_value=_org())
    with pytest.raises(HTTPException) as existing:
        await org_svc.create_org(CreateOrgRequest(name="Org", slug="secret-slug"), str(ACTOR), "c")
    orig = SimpleNamespace(sqlstate="23505")
    org_svc._repo.get_by_slug = AsyncMock(side_effect=[None, _org()])
    org_svc._repo.create = AsyncMock(side_effect=IntegrityError("insert", {}, orig))
    with pytest.raises(HTTPException) as concurrent:
        await org_svc.create_org(CreateOrgRequest(name="Org", slug="secret-slug"), str(ACTOR), "c")
    for error in (existing.value, concurrent.value):
        assert error.status_code == 409 and error.detail["code"] == "ORG_SLUG_CONFLICT"
        assert "secret-slug" not in error.detail["message"]


async def test_require_membership_is_uniform_403(org_svc):
    org_svc._member_repo.get_member = AsyncMock(return_value=_member("Operator"))
    assert await org_svc.require_membership(org_id=ORG, user_id=str(ACTOR)) == "Operator"
    org_svc._member_repo.get_member = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as foreign:
        await org_svc.require_membership(org_id=ORG, user_id=str(ACTOR))
    org_svc._repo.get_by_id = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as absent:
        await org_svc.require_membership(org_id=ORG, user_id="not-a-uuid")
    assert foreign.value.status_code == absent.value.status_code == 403


# ── Authorize with plain reads before locking ────────────────────────────────

@pytest.mark.parametrize("member", [None, _member("Read-Only"), _member("Operator")])
@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_unauthorized_org_admin_never_takes_the_lock(org_svc, member, operation):
    org_svc._member_repo.get_member = AsyncMock(return_value=member)
    with pytest.raises(HTTPException) as error:
        if operation == "update":
            await org_svc.update_org(org_id=ORG, user_id=str(ACTOR), name="x", actor_id=str(ACTOR), correlation_id="c")
        else:
            await org_svc.delete_org(org_id=ORG, user_id=str(ACTOR), actor_id=str(ACTOR), correlation_id="c")
    assert error.value.status_code == 403
    org_svc._repo.lock.assert_not_awaited()


async def test_admin_authority_is_rechecked_after_waiting_for_the_lock(org_svc, audit_append):
    order = []
    org_svc._repo.lock = AsyncMock(side_effect=lambda *a, **k: order.append("lock"))

    async def member(org_id, user_id):
        order.append("read")
        # Revoked by a concurrent administrator while this caller waited.
        return _member("Admin") if "lock" not in order else None

    org_svc._member_repo.get_member = member
    with pytest.raises(HTTPException) as error:
        await org_svc.update_org(org_id=ORG, user_id=str(ACTOR), name="x", actor_id=str(ACTOR), correlation_id="c")
    assert error.value.status_code == 403
    assert order == ["read", "lock", "read"]
    audit_append.assert_not_awaited()


@pytest.mark.parametrize(("role", "require", "locked"), [
    (None, {"require_write": True}, False), ("Read-Only", {"require_write": True}, False),
    ("Operator", {"require_write": True}, True), ("Operator", {"require_admin": True}, False),
    ("Admin", {"require_admin": True}, True), ("Read-Only", {}, False),
])
async def test_workspace_authority_locks_only_after_plain_authorization(mock_db, fake_redis, role, require, locked):
    svc = WorkspaceService(mock_db, fake_redis)
    svc._org_repo.get_by_id = AsyncMock(return_value=_org())
    svc._org_repo.lock = AsyncMock()
    svc._member_repo.get_member = AsyncMock(return_value=_member(role) if role else None)
    authorized = role is not None and (
        not require or (require.get("require_write") and role in {"Admin", "Operator"})
        or (require.get("require_admin") and role == "Admin"))
    if authorized:
        await svc._assert_org_membership(org_id=ORG, user_id=str(ACTOR), **require)
    else:
        with pytest.raises(HTTPException):
            await svc._assert_org_membership(org_id=ORG, user_id=str(ACTOR), **require)
    assert svc._org_repo.lock.await_count == (1 if locked else 0)
    assert svc._member_repo.get_member.await_count == (2 if locked else 1)


async def test_member_administration_by_non_admin_never_locks(mock_db, fake_redis):
    svc = MemberService(mock_db, fake_redis)
    svc._org_repo.get_by_id = AsyncMock(return_value=_org())
    svc._org_repo.lock = AsyncMock()
    svc._repo.get_member = AsyncMock(return_value=_member("Operator"))
    with pytest.raises(HTTPException) as error:
        await svc.add_member(ORG, uuid.uuid4(), "Operator", str(ACTOR), str(ACTOR), "c")
    assert error.value.status_code == 403
    svc._org_repo.lock.assert_not_awaited()


# ── Narrow inventory port; no organization → network import cycle ───────────

async def test_workspace_deletion_asks_the_injected_inventory_port(mock_db, fake_redis, audit_append):
    inventory = SimpleNamespace(has_active_networks=AsyncMock(return_value=True))
    svc = WorkspaceService(mock_db, fake_redis, inventory=inventory)
    svc._org_repo.get_by_id = AsyncMock(return_value=_org())
    svc._org_repo.lock = AsyncMock()
    svc._member_repo.get_member = AsyncMock(return_value=_member("Admin"))
    workspace_id = uuid.uuid4()
    svc._repo.get_by_org_and_id = AsyncMock(return_value=SimpleNamespace(workspace_id=workspace_id, org_id=ORG))
    svc._repo.soft_delete = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await svc.delete_workspace(org_id=ORG, workspace_id=workspace_id, actor_id=str(ACTOR),
                                   user_id=str(ACTOR), correlation_id="c")
    assert error.value.detail["code"] == "WORKSPACE_HAS_NETWORKS"
    inventory.has_active_networks.assert_awaited_once_with(workspace_id=workspace_id, actor_user_id=str(ACTOR))
    svc._repo.soft_delete.assert_not_awaited()
    inventory.has_active_networks.return_value = False
    await svc.delete_workspace(org_id=ORG, workspace_id=workspace_id, actor_id=str(ACTOR),
                               user_id=str(ACTOR), correlation_id="c")
    svc._repo.soft_delete.assert_awaited_once()


def test_organization_service_does_not_import_network_at_import_time():
    backend = Path(__file__).resolve().parents[2]
    probe = ("import sys, app.modules.organization.service as s; "
             "print('app.modules.network.service' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", probe], cwd=backend, env=dict(os.environ),
                            capture_output=True, text=True, timeout=120, check=True)
    assert result.stdout.strip() == "False", result.stderr


def test_unauthenticated_workspace_accessor_was_removed():
    assert not hasattr(WorkspaceService, "get_workspace")


# ── HTTP: uniform 404 and caller_role over the real auth path ────────────────

@pytest.fixture
async def org_client(tenant_auth, mock_db):
    from app.main import app

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: tenant_auth.redis
    token, _ = create_session_access_token(user_id=str(ACTOR), email="member@example.com",
                                           roles=["Operator"], permissions=["write:config"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://test", headers={"Authorization": f"Bearer {token}"}) as client:
            yield SimpleNamespace(client=client, identities=tenant_auth)
    finally:
        app.dependency_overrides.clear()


async def test_http_org_get_and_list_expose_caller_role_and_hide_foreign_orgs(org_client):
    org_id = org_client.identities.org_id
    got = await org_client.client.get(f"/api/v1/organizations/{org_id}")
    listed = await org_client.client.get("/api/v1/organizations")
    assert got.status_code == listed.status_code == 200
    assert got.json()["data"]["caller_role"] == "Admin"  # the fixture's membership role
    assert [item["caller_role"] for item in listed.json()["data"]["items"]] == ["Admin"]
    absent = await org_client.client.get(f"/api/v1/organizations/{uuid.uuid4()}")
    org_client.identities.memberships.clear()
    foreign = await org_client.client.get(f"/api/v1/organizations/{org_id}")
    assert absent.status_code == foreign.status_code == 404
    assert absent.json()["errors"] == foreign.json()["errors"] == {"code": "NOT_FOUND",
                                                                   "message": "Organization not found."}


@pytest.mark.parametrize("suffix", ["", f"/{uuid.UUID(int=1)}/workspaces", f"/{uuid.UUID(int=1)}/members"])
async def test_http_org_list_pages_are_bounded(org_client, suffix):
    response = await org_client.client.get(f"/api/v1/organizations{suffix}?page=10001")
    assert response.status_code == 422
