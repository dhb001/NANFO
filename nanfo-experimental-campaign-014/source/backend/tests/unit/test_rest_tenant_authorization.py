"""REST authorization regressions with real auth/services and repository-only doubles."""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.dialects import postgresql

from app.api.v1 import (
    alerts,
    audit,
    intents,
    networks,
    organizations,
    plugins,
    reports,
    simulation,
    telemetry,
    topology,
)
from app.core.dependencies import get_db, get_redis
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.modules.alert.repository import AlertRepository
from app.modules.alert.service import AlertService
from app.modules.identity.repository import AuditLogRepository, UserRepository
from app.modules.identity.sessions import SessionRepository
from app.modules.intent.repository import IntentRepository
from app.modules.intent.service import IntentExecutionService, IntentValidationService
from app.modules.network.repository import DeviceRepository, NetworkRepository
from app.modules.network.service import NetworkService
from app.modules.organization.repository import (
    OrganizationRepository,
    OrgMemberRepository,
    WorkspaceRepository,
)
from app.modules.organization.service import WorkspaceService
from app.modules.plugin.repository import PluginRepository
from app.modules.report.service import ReportService
from app.modules.simulation.repository import SimulationRepository

ORG_A, ORG_B, WS_A, WS_B, NET_A, NET_B, DEVICE_B = [UUID(int=n) for n in range(1, 8)]
ADMIN, READER, OUTSIDER = [UUID(int=n) for n in range(10, 13)]
ITEM = UUID(int=20)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
async def tenant_api(monkeypatch, mock_db, fake_redis):
    orgs = {
        org_id: SimpleNamespace(org_id=org_id, name=name, slug=name, created_at=NOW)
        for org_id, name in [(ORG_A, "org-a"), (ORG_B, "org-b")]
    }
    workspaces = {
        ws: SimpleNamespace(workspace_id=ws, org_id=org, name="Workspace", description=None, created_at=NOW)
        for ws, org in [(WS_A, ORG_A), (WS_B, ORG_B)]
    }
    members = {
        (ORG_A, ADMIN): SimpleNamespace(org_id=ORG_A, user_id=ADMIN, org_role="Admin", created_at=NOW),
        (ORG_A, READER): SimpleNamespace(org_id=ORG_A, user_id=READER, org_role="Read-Only", created_at=NOW),
    }
    roles = {ADMIN: ["Admin"], READER: ["Read-Only"], OUTSIDER: ["Admin"]}
    users = {
        user: SimpleNamespace(user_id=user, email=f"user-{user.int}@example.test", is_active=True)
        for user in roles
    }
    permissions = {
        "Admin": ["write:config", "read:topology", "read:telemetry", "execute:rollback"],
        "Operator": ["write:config", "read:topology", "read:telemetry", "execute:rollback"],
        "Read-Only": ["read:topology", "read:telemetry"],
    }

    def repo(cls, method, **kwargs):
        mock = AsyncMock(**kwargs)
        monkeypatch.setattr(cls, method, mock)
        return mock

    repo(UserRepository, "get_by_id", side_effect=users.get)
    repo(UserRepository, "get_roles_for_user", side_effect=lambda user: roles[user.user_id])
    repo(UserRepository, "get_permissions_for_roles", side_effect=lambda names: permissions[names[0]])
    repo(OrganizationRepository, "get_by_id", side_effect=orgs.get)
    repo(OrganizationRepository, "lock")
    repo(AuditLogRepository, "append")
    repo(OrgMemberRepository, "get_member", side_effect=lambda org, user: members.get((org, user)))
    repo(WorkspaceRepository, "get_by_id", side_effect=workspaces.get)
    repo(WorkspaceRepository, "get_by_org_and_id", side_effect=lambda org_id, workspace_id: (
        workspaces.get(workspace_id) if workspaces.get(workspace_id).org_id == org_id else None
    ))

    def list_orgs(user_id, page=1, page_size=20, org_id=None):
        rows = [org for key, org in orgs.items() if (key, user_id) in members and org_id in (None, key)]
        return rows[(page - 1) * page_size:page * page_size], len(rows)

    repo(OrganizationRepository, "list_for_user", side_effect=list_orgs)
    def list_workspaces(org, **kw):
        rows = [ws for ws in workspaces.values() if ws.org_id == org and kw.get("workspace_id") in (None, ws.workspace_id)]
        return rows, len(rows)

    repo(WorkspaceRepository, "list_for_org", side_effect=list_workspaces)
    repo(WorkspaceRepository, "soft_delete", side_effect=lambda ws: workspaces.pop(ws.workspace_id))
    repo(OrgMemberRepository, "list_members", side_effect=lambda org, **kw: (
        [member for (key, _), member in members.items() if key == org], 2,
    ))
    repo(OrgMemberRepository, "remove_member", side_effect=lambda member: members.pop((member.org_id, member.user_id)))
    repo(OrganizationRepository, "soft_delete", side_effect=lambda org: orgs.pop(org.org_id))
    repo(OrganizationRepository, "update", side_effect=lambda org, **kw: org)
    network_rows = {
        net: SimpleNamespace(network_id=net, workspace_id=ws)
        for net, ws in [(NET_A, WS_A), (NET_B, WS_B)]
    }
    repo(NetworkRepository, "get_by_id", side_effect=network_rows.get)
    repo(NetworkRepository, "list_for_workspace", return_value=([], 0))
    repo(DeviceRepository, "get_by_id", return_value=SimpleNamespace(device_id=DEVICE_B, network_id=NET_B))
    repo(SimulationRepository, "get_by_id", return_value=SimpleNamespace(network_id=NET_B, workspace_id=WS_B))
    audit_query = repo(AuditLogRepository, "list_entries", return_value=([], 0))
    plugin_query = repo(PluginRepository, "list_plugins", return_value=[])
    alert_query = repo(AlertRepository, "list_alerts", return_value=[])
    repo(AlertRepository, "get_by_id", return_value=SimpleNamespace(payload={"workspace_id": str(WS_B)}))

    app = FastAPI()
    for module in [organizations, networks, reports, intents, simulation, telemetry, topology, alerts, plugins, audit]:
        app.include_router(module.router)

    async def db_dependency():
        yield mock_db

    async def redis_dependency():
        yield fake_redis

    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_redis] = redis_dependency

    async def headers(user=ADMIN, org=None, workspace=None):
        sid = str(UUID(int=100 + user.int + (org.int if org else 0) + (workspace.int if workspace else 0)))
        scope = {"org_id": str(org) if org else None, "workspace_id": str(workspace) if workspace else None}
        refresh, _ = create_refresh_token(user_id=str(user), sid=sid, **scope)
        await SessionRepository(fake_redis).create(decode_token(refresh, token_type="refresh"), refresh)
        token, _ = create_access_token(
            user_id=str(user), email=users[user].email, roles=roles[user], permissions=permissions[roles[user][0]],
            sid=sid, **scope,
        )
        return {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(
            client=client, headers=headers, orgs=orgs, members=members, roles=roles,
            audit_query=audit_query, plugin_query=plugin_query, alert_query=alert_query,
        )


@pytest.mark.parametrize("user", [ADMIN, READER])
@pytest.mark.parametrize("path", [
    f"/organizations/{ORG_B}",
    f"/organizations/{ORG_B}/workspaces",
    f"/organizations/{ORG_B}/workspaces/{WS_B}",
    f"/organizations/{ORG_B}/members",
    f"/networks?workspace_id={WS_B}",
    f"/networks/{NET_B}/devices",
    f"/networks/{NET_B}/campus/buildings",
    f"/networks/{NET_B}/campus/model-assets",
    f"/networks/{NET_B}/device-groups",
    f"/telemetry/history?workspace_id={WS_B}",
    f"/telemetry/history?network_id={NET_B}",
    f"/telemetry/device/{DEVICE_B}",
    f"/topology/graph?network_id={NET_B}",
    f"/topology/nodes/{DEVICE_B}",
    f"/topology/device/{DEVICE_B}/neighbors",
    f"/topology/impact/{DEVICE_B}",
    f"/reports/{ITEM}?workspace_id={WS_B}",
    f"/intents/{ITEM}?workspace_id={WS_B}",
    f"/simulations/{ITEM}",
    f"/simulations/{ITEM}/compare/{UUID(int=21)}",
])
async def test_claimless_users_cannot_read_other_tenant(tenant_api, user, path):
    response = await tenant_api.client.get(f"/api/v1{path}", headers=await tenant_api.headers(user))
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("path,body", [
    ("/organizations", {"name": "New", "slug": "new"}),
    (f"/organizations/{ORG_A}/workspaces", {"name": "New"}),
    (f"/organizations/{ORG_A}/members", {"user_id": str(OUTSIDER), "org_role": "Admin"}),
    ("/simulations/start", {"network_id": str(NET_A), "scenario_name": "test"}),
    ("/simulations/pause", {"simulation_id": str(ITEM)}),
    ("/simulations/branch", {"parent_simulation_id": str(ITEM), "scenario_name": "test"}),
    ("/intents/validate", {"workspace_id": str(WS_A), "intent": {}}),
    ("/intents/execute", {"workspace_id": str(WS_A), "intent_id": str(ITEM)}),
    (f"/alerts/{ITEM}/ack", {}),
    (f"/alerts/{ITEM}/resolve", {}),
    (f"/plugins/{ITEM}/enable", {}),
    (f"/plugins/{ITEM}/disable", {}),
    ("/topology/reconcile", {"network_id": str(NET_A)}),
])
async def test_readonly_cannot_write_even_as_org_admin(tenant_api, path, body):
    tenant_api.members[(ORG_A, READER)].org_role = "Admin"
    response = await tenant_api.client.post(
        f"/api/v1{path}", json=body, headers=await tenant_api.headers(READER),
    )
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("method,path,body", [
    ("PATCH", f"/organizations/{ORG_A}", {"name": "Changed"}),
    ("DELETE", f"/organizations/{ORG_A}", None),
    ("POST", f"/organizations/{ORG_A}/workspaces", {"name": "New"}),
    ("PATCH", f"/organizations/{ORG_A}/workspaces/{WS_A}", {"name": "Changed"}),
    ("DELETE", f"/organizations/{ORG_A}/workspaces/{WS_A}", None),
    ("POST", f"/organizations/{ORG_A}/members", {"user_id": str(OUTSIDER), "org_role": "Admin"}),
    ("DELETE", f"/organizations/{ORG_A}/members/{READER}", None),
])
@pytest.mark.parametrize("membership", ["Read-Only", None])
async def test_global_admin_needs_org_admin_for_administration(tenant_api, method, path, body, membership):
    if membership is None:
        tenant_api.members.pop((ORG_A, ADMIN))
    else:
        tenant_api.members[(ORG_A, ADMIN)].org_role = membership
    response = await tenant_api.client.request(
        method, f"/api/v1{path}", json=body, headers=await tenant_api.headers(),
    )
    assert response.status_code == 403, response.text


async def test_membership_revocation_takes_effect_with_same_token(tenant_api):
    headers = await tenant_api.headers(READER)
    path = f"/api/v1/networks?workspace_id={WS_A}"
    assert (await tenant_api.client.get(path, headers=headers)).status_code == 200
    removal = await tenant_api.client.delete(
        f"/api/v1/organizations/{ORG_A}/members/{READER}", headers=await tenant_api.headers(),
    )
    assert removal.status_code == 204
    assert (await tenant_api.client.get(path, headers=headers)).status_code == 403


async def test_org_deletion_denies_descendants_with_same_token(tenant_api):
    headers = await tenant_api.headers()
    response = await tenant_api.client.delete(f"/api/v1/organizations/{ORG_A}", headers=headers)
    assert response.status_code == 409
    response = await tenant_api.client.delete(f"/api/v1/organizations/{ORG_A}/workspaces/{WS_A}", headers=headers)
    assert response.status_code == 204
    response = await tenant_api.client.delete(f"/api/v1/organizations/{ORG_A}", headers=headers)
    assert response.status_code == 204
    for path in [f"/organizations/{ORG_A}/workspaces", f"/organizations/{ORG_A}/members",
                 f"/networks?workspace_id={WS_A}", f"/telemetry/history?workspace_id={WS_A}"]:
        assert (await tenant_api.client.get(f"/api/v1{path}", headers=headers)).status_code == 404


@pytest.mark.parametrize("org,workspace", [(ORG_B, None), (None, WS_B), (ORG_A, WS_B)])
async def test_claims_only_narrow_report_and_intent_access(tenant_api, org, workspace):
    headers = await tenant_api.headers(org=org, workspace=workspace)
    for path, body in [
        ("/reports/generate", {"workspace_id": str(WS_A), "report_type": "operational_summary", "format": "csv",
                               "date_range": {"start": NOW.isoformat(), "end": "2026-01-02T00:00:00Z"}}),
        ("/intents/validate", {"workspace_id": str(WS_A)}),
        ("/intents/execute", {"workspace_id": str(WS_A), "intent_id": str(ITEM)}),
    ]:
        response = await tenant_api.client.post(f"/api/v1{path}", json=body, headers=headers)
        assert response.status_code == 403, response.text


@pytest.mark.parametrize("path,body", [
    ("/reports/generate", {"workspace_id": str(WS_B), "report_type": "operational_summary", "format": "csv",
                           "date_range": {"start": NOW.isoformat(), "end": "2026-01-02T00:00:00Z"}}),
    ("/intents/validate", {"workspace_id": str(WS_B)}),
    ("/intents/execute", {"workspace_id": str(WS_B), "intent_id": str(ITEM)}),
    ("/simulations/start", {"network_id": str(NET_B), "scenario_name": "test"}),
    ("/simulations/pause", {"simulation_id": str(ITEM)}),
    ("/simulations/branch", {"parent_simulation_id": str(ITEM), "scenario_name": "test"}),
    ("/topology/reconcile", {"network_id": str(NET_B)}),
    (f"/alerts/{ITEM}/ack", {}),
    (f"/alerts/{ITEM}/resolve", {}),
])
async def test_claimless_admin_cannot_mutate_other_tenant(tenant_api, path, body):
    response = await tenant_api.client.post(f"/api/v1{path}", json=body, headers=await tenant_api.headers())
    assert response.status_code == 403, response.text


async def test_org_reads_allow_readonly_and_writes_allow_local_admin(tenant_api):
    headers = await tenant_api.headers(READER)
    for path in [f"/organizations/{ORG_A}", f"/organizations/{ORG_A}/workspaces", f"/organizations/{ORG_A}/members"]:
        response = await tenant_api.client.get(f"/api/v1{path}", headers=headers)
        assert response.status_code == 200, response.text
    response = await tenant_api.client.patch(
        f"/api/v1/organizations/{ORG_A}", json={"name": "Updated"}, headers=await tenant_api.headers(),
    )
    assert response.status_code == 200, response.text


async def test_workspace_claim_cannot_access_other_org_administration(tenant_api):
    tenant_api.members[(ORG_B, ADMIN)] = SimpleNamespace(org_role="Admin")
    headers = await tenant_api.headers(workspace=WS_A)
    for method, path, body in [
        ("GET", f"/organizations/{ORG_B}/members", None),
        ("PATCH", f"/organizations/{ORG_B}", {"name": "Changed"}),
        ("GET", f"/organizations/{ORG_B}/workspaces", None),
    ]:
        response = await tenant_api.client.request(method, f"/api/v1{path}", json=body, headers=headers)
        assert response.status_code == 403, response.text


async def test_org_list_claims_filter_memberships(tenant_api):
    tenant_api.members[(ORG_B, ADMIN)] = SimpleNamespace(org_role="Admin")
    response = await tenant_api.client.get("/api/v1/organizations", headers=await tenant_api.headers(org=ORG_A))
    assert response.status_code == 200, response.text
    assert [item["org_id"] for item in response.json()["data"]["items"]] == [str(ORG_A)]


async def test_audit_is_always_org_scoped(tenant_api):
    headers = await tenant_api.headers()
    for query in ["", f"?org_id={ORG_B}", f"?actor_id={ADMIN}"]:
        response = await tenant_api.client.get(f"/api/v1/audit/logs{query}", headers=headers)
        assert response.status_code == 403
    tenant_api.audit_query.assert_not_awaited()
    response = await tenant_api.client.get(f"/api/v1/audit/logs?org_id={ORG_A}", headers=headers)
    assert response.status_code == 200
    assert tenant_api.audit_query.await_args.kwargs["org_id"] == ORG_A


@pytest.mark.parametrize("path", ["/plugins", "/telemetry/health"])
@pytest.mark.parametrize("user,org", [(READER, None), (OUTSIDER, None), (ADMIN, ORG_B)])
async def test_global_operational_surfaces_require_admin_and_membership(tenant_api, path, user, org):
    response = await tenant_api.client.get(f"/api/v1{path}", headers=await tenant_api.headers(user, org=org))
    assert response.status_code == 403, response.text
    tenant_api.plugin_query.assert_not_awaited()


async def test_plugin_member_admin_can_read_registry(tenant_api):
    response = await tenant_api.client.get("/api/v1/plugins", headers=await tenant_api.headers())
    assert response.status_code == 200
    tenant_api.plugin_query.assert_awaited_once()


async def test_alerts_fail_closed_without_tenant_and_check_org_membership(tenant_api, mock_db, fake_redis):
    service = AlertService(db=mock_db, redis=fake_redis)
    for payload, allowed in [({}, False), ({"org_id": str(ORG_B)}, False), ({"org_id": str(ORG_A)}, True),
                             ({"workspace_id": str(WS_B)}, False), ({"workspace_id": str(WS_A)}, True)]:
        call = service._assert_alert_access(
            alert=SimpleNamespace(payload=payload), actor_user_id=str(ADMIN),
            requested_workspace_id=None, claim_org_id=None,
        )
        if allowed:
            await call
        else:
            with pytest.raises(HTTPException) as exc:
                await call
            assert exc.value.status_code == 403


async def test_alert_list_excludes_deleted_revoked_and_unscoped_rows(tenant_api, monkeypatch):
    monkeypatch.setattr(WorkspaceRepository, "list_accessible_ids", AsyncMock(
        side_effect=lambda **kwargs: [WS_A] if ORG_A in tenant_api.orgs else []))
    def alert(payload):
        return SimpleNamespace(
            alert_id=ITEM, alert_key="test", source="telemetry", status="active", severity="critical",
            correlation_id=ITEM, payload=payload, acknowledged_by_user_id=None, resolved_by_user_id=None,
            acknowledged_at=None, resolved_at=None, created_at=NOW, updated_at=NOW,
        )

    tenant_api.alert_query.return_value = [
        alert({"workspace_id": str(WS_A)}), alert({"workspace_id": str(WS_B)}), alert({}),
    ]
    headers = await tenant_api.headers()
    response = await tenant_api.client.get("/api/v1/alerts", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["total"] == 1
    tenant_api.orgs.pop(ORG_A)
    response = await tenant_api.client.get("/api/v1/alerts", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["total"] == 0


async def test_workspace_id_helper_uses_only_organization_owned_active_memberships(mock_db):
    from unittest.mock import MagicMock

    result = MagicMock()
    result.scalars.return_value.all.return_value = [WS_A]
    mock_db.execute.return_value = result
    service = WorkspaceService(db=mock_db, redis=None)
    assert await service.list_accessible_workspace_ids(
        user_id=str(ADMIN), claim_org_id=ORG_A, claim_workspace_id=WS_A,
    ) == [WS_A]
    query = mock_db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(query)
    for table in ["organizations", "workspaces", "org_members"]:
        assert f"{table}.deleted_at IS NULL" in sql
    assert "org_members.user_id =" in sql
    assert "organizations.org_id =" in sql
    assert "workspaces.workspace_id =" in sql
    assert set(query.params.values()) == {ADMIN, ORG_A, WS_A}


@pytest.mark.parametrize("global_role", ["Admin", "Operator"])
@pytest.mark.parametrize("method,path,body", [
    ("POST", "/networks", {"workspace_id": str(WS_A), "name": "test"}),
    ("POST", f"/networks/{NET_A}/devices", {"hostname": "test", "device_type": "router"}),
    ("PATCH", f"/networks/{NET_A}/devices/{ITEM}", {"spatial_ref_id": "test"}),
    ("POST", f"/networks/{NET_A}/campus/buildings", {"buildings": []}),
    ("POST", f"/networks/{NET_A}/campus/model-assets", {
        "model_file_name": "test.gltf", "model_mime_type": "model/gltf+json", "model_data_base64": "e30=",
        "model_size_bytes": 2, "model_sha256": hashlib.sha256(b"{}").hexdigest(),
    }),
    ("POST", f"/networks/{NET_A}/device-groups", {"groups": []}),
    ("POST", "/intents/validate", {"workspace_id": str(WS_A), "network_id": str(NET_A), "intent": {}}),
    ("POST", "/intents/execute", {"workspace_id": str(WS_A), "intent_id": str(ITEM)}),
    ("POST", "/simulations/start", {"network_id": str(NET_A), "scenario_name": "test"}),
    ("POST", "/simulations/start", {"network_id": str(NET_A), "scenario_name": "test", "simulation_id": str(ITEM)}),
    ("POST", "/simulations/pause", {"simulation_id": str(ITEM)}),
    ("POST", "/simulations/branch", {"parent_simulation_id": str(ITEM), "scenario_name": "test"}),
    ("POST", f"/alerts/{ITEM}/ack", {}),
    ("POST", f"/alerts/{ITEM}/resolve", {}),
    ("POST", "/topology/reconcile", {"network_id": str(NET_A)}),
    ("POST", "/reports/generate", {"workspace_id": str(WS_A), "report_type": "executive_summary", "format": "csv",
                                     "date_range": {"start": NOW.isoformat(), "end": "2026-01-02T00:00:00Z"}}),
])
async def test_global_writer_org_readonly_denies_every_resource_mutation(
    tenant_api, monkeypatch, mock_db, global_role, method, path, body,
):
    tenant_api.roles[ADMIN] = [global_role]
    tenant_api.members[(ORG_A, ADMIN)].org_role = "Read-Only"
    monkeypatch.setattr(SimulationRepository, "get_by_id", AsyncMock(return_value=SimpleNamespace(workspace_id=WS_A)))
    monkeypatch.setattr(AlertRepository, "get_by_id", AsyncMock(return_value=SimpleNamespace(payload={"workspace_id": str(WS_A)})))
    response = await tenant_api.client.request(method, f"/api/v1{path}", json=body, headers=await tenant_api.headers())
    assert response.status_code == 403, response.text
    mock_db.commit.assert_not_awaited()
    mock_db.flush.assert_not_awaited()


@pytest.mark.parametrize("org_role", ["Admin", "Operator"])
async def test_org_role_downgrade_blocks_writes_with_same_global_admin_session(tenant_api, monkeypatch, org_role):
    tenant_api.members[(ORG_A, ADMIN)].org_role = org_role
    created = AsyncMock(return_value=SimpleNamespace(
        network_id=ITEM, workspace_id=WS_A, name="test", description=None, cidr=None, created_at=NOW,
    ))
    monkeypatch.setattr(NetworkRepository, "create", created)
    headers = await tenant_api.headers()
    body = {"workspace_id": str(WS_A), "name": "test"}
    response = await tenant_api.client.post("/api/v1/networks", json=body, headers=headers)
    assert response.status_code == 201, response.text
    tenant_api.members[(ORG_A, ADMIN)].org_role = "Read-Only"
    response = await tenant_api.client.post("/api/v1/networks", json=body, headers=headers)
    assert response.status_code == 403, response.text
    assert (await tenant_api.client.get(f"/api/v1/networks?workspace_id={WS_A}", headers=headers)).status_code == 200
    created.assert_awaited_once()


@pytest.mark.parametrize("scope", [{"org_id": str(ORG_A)}, {"workspace_id": str(WS_A)}, {"network_id": str(NET_A)}])
async def test_alert_mutation_scope_variants_use_current_org_role(tenant_api, mock_db, fake_redis, scope):
    service = AlertService(db=mock_db, redis=fake_redis)
    args = {"alert": SimpleNamespace(payload=scope), "actor_user_id": str(ADMIN),
            "requested_workspace_id": None, "claim_org_id": None}
    tenant_api.members[(ORG_A, ADMIN)].org_role = "Operator"
    await service._assert_alert_access(**args, require_write=True)
    tenant_api.members[(ORG_A, ADMIN)].org_role = "Read-Only"
    await service._assert_alert_access(**args)
    with pytest.raises(HTTPException) as exc:
        await service._assert_alert_access(**args, require_write=True)
    assert exc.value.status_code == 403


async def test_org_write_access_never_overrides_org_claim(tenant_api, mock_db, fake_redis):
    tenant_api.members[(ORG_A, ADMIN)].org_role = "Operator"
    service = NetworkService(db=mock_db, redis=fake_redis)
    with pytest.raises(HTTPException) as exc:
        await service.assert_network_workspace_access(
            network_id=NET_A, requested_workspace_id=WS_A, actor_user_id=str(ADMIN), claim_org_id=ORG_B, require_write=True,
        )
    assert exc.value.status_code == 403


async def test_org_operator_cannot_administer_memberships(tenant_api):
    tenant_api.members[(ORG_A, ADMIN)].org_role = "Operator"
    response = await tenant_api.client.delete(
        f"/api/v1/organizations/{ORG_A}/members/{READER}", headers=await tenant_api.headers(),
    )
    assert response.status_code == 403


@pytest.mark.parametrize("action", ["validate", "execute", "report"])
async def test_direct_service_writes_check_org_role_before_replay_or_validation(tenant_api, mock_db, fake_redis, action):
    tenant_api.members[(ORG_A, ADMIN)].org_role = "Read-Only"
    with pytest.raises(HTTPException) as exc:
        if action == "validate":
            await IntentValidationService(db=mock_db, redis=fake_redis).validate_intent(
                workspace_id=WS_A, network_id=NET_A, intent_payload={}, idempotency_key="replay",
                correlation_id=str(ITEM), requested_by_user_id=str(ADMIN),
            )
        elif action == "execute":
            await IntentExecutionService(db=mock_db, redis=fake_redis).execute_intent(
                workspace_id=WS_A, intent_id=ITEM, idempotency_key="replay", correlation_id=str(ITEM),
                requested_by_user_id=str(ADMIN), requested_permissions=["write:config", "execute:rollback"],
            )
        else:
            await ReportService(db=mock_db, redis=fake_redis).generate_report(
                workspace_id=WS_A, network_id=NET_A, report_type="summary", output_format="csv", date_range={},
                scope={}, filters={}, fail_generation=False, idempotency_key="replay", correlation_id=str(ITEM),
                requested_by_user_id=str(ADMIN),
            )
    assert exc.value.status_code == 403
    mock_db.execute.assert_not_awaited()


@pytest.mark.parametrize("role", ["Read-Only", "unknown", "admin", ""])
async def test_workspace_write_roles_fail_closed_but_members_can_read(tenant_api, mock_db, fake_redis, role):
    tenant_api.members[(ORG_A, ADMIN)].org_role = role
    service = WorkspaceService(db=mock_db, redis=fake_redis)
    assert (await service.get_active_workspace(WS_A, user_id=str(ADMIN))).workspace_id == WS_A
    with pytest.raises(HTTPException) as exc:
        await service.get_active_workspace(WS_A, user_id=str(ADMIN), require_write=True)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await service.get_active_workspace(WS_A, require_write=True)
    assert exc.value.status_code == 403


async def test_report_generation_requires_global_write_even_for_org_admin(tenant_api):
    tenant_api.members[(ORG_A, READER)].org_role = "Admin"
    response = await tenant_api.client.post(
        "/api/v1/reports/generate", headers=await tenant_api.headers(READER),
        json={"workspace_id": str(WS_A), "report_type": "summary", "format": "csv",
              "date_range": {"start": NOW.isoformat(), "end": NOW.isoformat()}},
    )
    assert response.status_code == 403, response.text


async def test_intent_authorized_workspace_foreign_network_denied_before_any_side_effect(
    tenant_api, mock_db, fake_redis, monkeypatch,
):
    create = AsyncMock()
    publish = AsyncMock()
    monkeypatch.setattr(IntentRepository, "create", create)
    monkeypatch.setattr("app.modules.intent.service.publish_event", publish)
    response = await tenant_api.client.post(
        "/api/v1/intents/validate", headers=await tenant_api.headers(),
        json={"workspace_id": str(WS_A), "network_id": str(NET_B),
              "intent": {"action": "reroute_path", "scope": {"network": str(NET_B)}}},
    )
    assert response.status_code == 403, response.text
    create.assert_not_awaited()
    publish.assert_not_awaited()
    mock_db.commit.assert_not_awaited()
    mock_db.flush.assert_not_awaited()
