"""REST contract tests retain real JWT/session/current identity and ownership checks."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app
from tests.auth_support import create_authorized_workspace
from tests.autonomy_support import HASH, MemoryRepository


@pytest.fixture
def context(tenant_auth, mock_db, monkeypatch):
    workspace_id = create_authorized_workspace()
    network = SimpleNamespace(network_id=uuid.uuid4(), workspace_id=workspace_id)
    repo = MemoryRepository()
    monkeypatch.setattr("app.modules.autonomy.service.AutonomyRepository", lambda db: repo)
    monkeypatch.setattr("app.modules.network.repository.NetworkRepository.get_by_id",
                        AsyncMock(side_effect=lambda identity: network if identity == network.network_id else None))
    async def db():
        yield mock_db
    async def redis():
        yield tenant_auth.redis
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_redis] = redis
    yield SimpleNamespace(client=TestClient(app, raise_server_exceptions=False), auth=tenant_auth,
                          network=network, repo=repo)
    app.dependency_overrides.clear()


def headers(context, permissions=None, **scope):
    actor = str(uuid.uuid4())
    token, _ = context.auth.issue(user_id=actor, email="autonomy@example.com", roles=[actor],
        permissions=permissions if permissions is not None else ["read:telemetry", "write:config", "execute:rollback"], **scope)
    context.actor = actor
    return {"Authorization": f"Bearer {token}"}


def test_get_typed_fail_closed_status(context):
    response = context.client.get("/api/v1/autonomy", params={"network_id": str(context.network.network_id)}, headers=headers(context))
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True and body["errors"] is None
    data = body["data"]
    assert data["mode"] == "monitor" and data["status"] == "monitoring"
    assert data["ready"] is False and data["online_learning"] is False
    assert data["production_dispatch"] is False
    assert data["providers"]["observer"]["status"] == "incompatible"
    assert data["decisions"] == [] and data["last_observation"] is None


def test_autonomous_put_409_preserves_existing_mode(context):
    auth = headers(context)
    network_id = str(context.network.network_id)
    assert context.client.put("/api/v1/autonomy", json={"network_id": network_id, "expected_revision": 0, "mode": "recommend"}, headers=auth).status_code == 200
    response = context.client.put("/api/v1/autonomy", json={"network_id": network_id, "mode": "autonomous",
        "expected_revision": 1, "checkpoint_sha256": HASH, "approval_expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}, headers=auth)
    assert response.status_code == 409
    assert response.json()["errors"]["code"] == "AUTONOMY_NOT_READY"
    assert "autonomous_executor_unavailable" in response.json()["errors"]["message"]
    assert context.repo.control.mode == "recommend"


@pytest.mark.parametrize("permissions", [["write:config"], ["execute:rollback"], ["read:telemetry"]])
@pytest.mark.parametrize("method,path,payload", [
    ("put", "/api/v1/autonomy", {"mode": "monitor", "expected_revision": 0}), ("post", "/api/v1/autonomy/stop", {}),
    ("put", "/api/v1/autonomy/configuration", {"expected_revision": 0, "reason": "test", "operational": {}, "training": {}}),
    ("post", "/api/v1/autonomy/overrides", {"expected_revision": 0, "reason": "test", "duration_seconds": 10,
        "return_mode": "monitor", "intent_id": str(uuid.uuid4()), "execution_id": str(uuid.uuid4())}),
])
def test_writes_require_both_permissions(context, permissions, method, path, payload):
    response = getattr(context.client, method)(path, json={"network_id": str(context.network.network_id), **payload},
                                               headers=headers(context, permissions))
    assert response.status_code == 403
    assert context.repo.control is None


def test_current_permissions_not_token_permissions(context):
    auth = headers(context)
    context.auth.permissions[(context.actor,)] = ["read:telemetry"]
    response = context.client.put("/api/v1/autonomy", json={"network_id": str(context.network.network_id), "expected_revision": 0, "mode": "monitor"}, headers=auth)
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["configuration", "overrides"])
def test_operator_reads_require_telemetry_and_membership(context, path):
    route = f"/api/v1/autonomy/{path}"
    scope = {"network_id": str(context.network.network_id)}
    assert context.client.get(route, params=scope).status_code == 401
    auth = headers(context, ["write:config", "execute:rollback"])
    assert context.client.get(route, params=scope, headers=auth).status_code == 403
    auth = headers(context, ["read:telemetry"])
    response = context.client.get(route, params=scope, headers=auth)
    assert response.status_code == 200 and response.json()["success"]
    assert "capability" not in response.text
    context.auth.memberships.clear()
    assert context.client.get(route, params=scope, headers=auth).status_code == 403


@pytest.mark.parametrize("action", ["cancel", "return"])
def test_override_mutations_require_current_authority(context, monkeypatch, action):
    row = SimpleNamespace(override_id=uuid.uuid4(), network_id=context.network.network_id,
                          workspace_id=context.network.workspace_id)
    context.repo.override = AsyncMock(return_value=row)
    response = context.client.post(f"/api/v1/autonomy/overrides/{row.override_id}/{action}",
        json={"expected_revision": 0, "reason": "return"} if action == "return" else None,
        headers=headers(context, ["read:telemetry"]))
    assert response.status_code == 403


def test_global_admin_permissions_do_not_override_readonly_membership(context, monkeypatch):
    auth = headers(context)
    monkeypatch.setattr("app.modules.organization.repository.OrgMemberRepository.get_member",
        AsyncMock(return_value=SimpleNamespace(org_role="ReadOnly")))
    response = context.client.put("/api/v1/autonomy/configuration", headers=auth,
        json={"network_id": str(context.network.network_id), "expected_revision": 0, "reason": "denied", "operational": {}, "training": {}})
    assert response.status_code == 403


@pytest.mark.parametrize("scope", ["workspace_id", "org_id"])
def test_cross_scope_rejected(context, scope):
    response = context.client.get("/api/v1/autonomy", params={"network_id": str(context.network.network_id)},
                                  headers=headers(context, **{scope: str(uuid.uuid4())}))
    assert response.status_code == 403


def test_membership_revocation_denies_read(context):
    auth = headers(context)
    context.auth.memberships.clear()
    response = context.client.get("/api/v1/autonomy", params={"network_id": str(context.network.network_id)}, headers=auth)
    assert response.status_code == 403


def test_stop_latched_and_explicit_monitor_clears(context):
    auth = headers(context)
    payload = {"network_id": str(context.network.network_id)}
    response = context.client.post("/api/v1/autonomy/stop", json=payload, headers=auth)
    assert response.status_code == 200
    assert response.json()["data"]["emergency_stopped"] is True
    response = context.client.get("/api/v1/autonomy", params=payload, headers=auth)
    assert response.json()["data"]["status"] == "stopped"
    response = context.client.put("/api/v1/autonomy", json={**payload, "expected_revision": response.json()["data"]["revision"], "mode": "monitor"}, headers=auth)
    assert response.json()["data"]["emergency_stopped"] is False
    assert response.json()["data"]["last_decision"]["status"] == "control_changed"


def test_auth_and_bounded_history(context):
    params = {"network_id": str(context.network.network_id)}
    assert context.client.get("/api/v1/autonomy", params=params).status_code == 401
    auth = headers(context)
    assert context.client.get("/api/v1/autonomy", params={**params, "history_limit": 101}, headers=auth).status_code == 422


def test_openapi_concrete_schemas():
    schema = app.openapi()
    result = schema["paths"]["/api/v1/autonomy"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert "APIResponse_AutonomyResponse_" in result["$ref"]
    assert "AutonomyResponse" in schema["components"]["schemas"]
    assert "DecisionResponse" in schema["components"]["schemas"]
    assert "expected_revision" in schema["components"]["schemas"]["SetAutonomyRequest"]["required"]


def test_stale_put_preserves_stop_and_initial_revision(context):
    auth = headers(context)
    scope = {"network_id": str(context.network.network_id)}
    assert context.client.get("/api/v1/autonomy", params=scope, headers=auth).json()["data"]["revision"] == 0
    assert context.client.put("/api/v1/autonomy", json={**scope, "mode": "monitor"}, headers=auth).status_code == 422
    stopped = context.client.post("/api/v1/autonomy/stop", json=scope, headers=auth).json()["data"]
    result = context.client.put("/api/v1/autonomy", json={**scope, "mode": "monitor", "expected_revision": 0}, headers=auth)
    assert result.status_code == 409
    assert result.json()["errors"]["code"] == "AUTONOMY_REVISION_CONFLICT"
    current = context.client.get("/api/v1/autonomy", params=scope, headers=auth).json()["data"]
    assert current["revision"] == stopped["revision"] and current["emergency_stopped"]
