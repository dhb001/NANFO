"""Real JWT/session/permission/membership checks with substituted persistence only."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.spatial import router
from app.core.dependencies import get_db, get_redis
from app.main import app as main_app
from app.modules.network.repository import NetworkRepository
from app.modules.network.spatial_repository import SpatialSceneRepository
from app.modules.network.spatial_schemas import SpatialHistoryList, SpatialSceneDocument, empty_scene
from app.modules.organization.repository import OrgMemberRepository
from tests.auth_support import create_authorized_workspace
from tests.spatial_support import ACTOR_ID, NETWORK_ID, replace_payload, spatial_object
from tests.unit.test_spatial_geometry import dimensioned_objects


@pytest.fixture
def api(tenant_auth, mock_db, monkeypatch):
    mock_db.expire_all = MagicMock()
    workspace_id = create_authorized_workspace()
    network = SimpleNamespace(network_id=NETWORK_ID, workspace_id=workspace_id)
    monkeypatch.setattr(NetworkRepository, "get_by_id", AsyncMock(return_value=network))
    scene_get = AsyncMock(return_value=empty_scene())
    monkeypatch.setattr(SpatialSceneRepository, "get", scene_get)
    monkeypatch.setattr(SpatialSceneRepository, "append_revision", AsyncMock())
    history = AsyncMock(return_value=SpatialHistoryList(items=[], total=0, page=1, page_size=20))
    revision_get = AsyncMock(return_value=empty_scene().model_copy(update={"revision": 1}))
    monkeypatch.setattr(SpatialSceneRepository, "list_history", history)
    monkeypatch.setattr(SpatialSceneRepository, "get_revision", revision_get)
    monkeypatch.setattr(SpatialSceneRepository, "lock_active_network", AsyncMock(return_value=True))
    monkeypatch.setattr(SpatialSceneRepository, "lock_scene_for_write", AsyncMock())
    monkeypatch.setattr(SpatialSceneRepository, "active_device_ids", AsyncMock(return_value=set()))
    persist = AsyncMock(return_value=True)
    monkeypatch.setattr(SpatialSceneRepository, "replace", persist)
    audit = AsyncMock()
    monkeypatch.setattr("app.modules.network.spatial_service.append_audit_log", audit)
    app = FastAPI(exception_handlers=main_app.exception_handlers)
    app.include_router(router)

    async def database():
        yield mock_db

    async def redis():
        yield tenant_auth.redis

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_redis] = redis
    return SimpleNamespace(
        client=TestClient(app, raise_server_exceptions=False), identities=tenant_auth, workspace_id=workspace_id,
        get=scene_get, persist=persist, audit=audit, history=history, revision_get=revision_get,
    )


def headers(api, permissions=None, **scope):
    token, _ = api.identities.issue(
        user_id=str(ACTOR_ID), email="spatial@example.com", roles=["SpatialTest"],
        permissions=["read:topology", "write:config"] if permissions is None else permissions, **scope,
    )
    return {"Authorization": f"Bearer {token}", "X-Request-ID": "spatial-contract-test"}


URL = f"/api/v1/networks/{NETWORK_ID}/spatial-scene"


@pytest.mark.parametrize("method", ["get", "put"])
def test_missing_auth_and_current_permission_denied(api, method):
    kwargs = {"json": replace_payload()} if method == "put" else {}
    assert getattr(api.client, method)(URL, **kwargs).status_code == 401
    response = getattr(api.client, method)(URL, headers=headers(api, []), **kwargs)
    assert response.status_code == 403
    assert response.json()["errors"]["code"] == "FORBIDDEN"
    api.get.assert_not_awaited()
    api.persist.assert_not_awaited()


def test_initial_get_and_put_return_exact_canonical_document(api):
    auth = headers(api)
    result = api.client.get(URL, headers=auth)
    assert result.status_code == 200
    body = result.json()
    assert set(body) == {"success", "data", "meta", "errors"}
    assert body["data"] == {**replace_payload()["scene"], "revision": 0}
    assert body["meta"]["request_id"] == "spatial-contract-test"
    assert body["meta"]["execution_mode"] == "demo"
    api.persist.assert_not_awaited()
    result = api.client.put(URL, headers=auth, json=replace_payload())
    assert result.status_code == 200
    assert result.json()["data"]["revision"] == 1
    api.audit.assert_awaited_once()


def test_geometry_save_current_and_history_wire_contract_preserves_omission(api):
    auth = headers(api)
    payload = replace_payload(objects=[*dimensioned_objects(), spatial_object("legacy"), spatial_object("null", geometry=None)])
    response = api.client.put(URL, headers=auth, json=payload)
    assert response.status_code == 200
    expected = {**payload["scene"], "revision": 1}
    assert response.json()["data"] == expected
    assert api.persist.await_args.args[2] == payload["scene"]
    api.get.return_value = api.revision_get.return_value = SpatialSceneDocument.model_validate(expected)
    assert api.client.get(URL, headers=auth).json()["data"] == expected
    assert api.client.get(URL + "/history/1", headers=auth).json()["data"] == expected


def test_invalid_geometry_returns_422_without_persistence(api):
    objects = dimensioned_objects()
    objects[-1]["geometry"]["thickness"] = 0
    response = api.client.put(URL, headers=headers(api), json=replace_payload(objects=objects))
    assert response.status_code == 422
    assert response.json()["errors"]["code"] == "VALIDATION_ERROR"
    api.persist.assert_not_awaited()


@pytest.mark.parametrize("method", ["get", "put"])
@pytest.mark.parametrize("scope", ["workspace_id", "org_id"])
def test_claim_scope_narrows_membership(api, method, scope):
    auth = headers(api, **{scope: str(uuid.UUID(int=999))})
    kwargs = {"json": replace_payload()} if method == "put" else {}
    assert getattr(api.client, method)(URL, headers=auth, **kwargs).status_code == 403
    api.get.assert_not_awaited()
    api.persist.assert_not_awaited()


def test_current_membership_revocation_and_identity_permission_reload(api):
    auth = headers(api)
    assert api.client.get(URL, headers=auth).status_code == 200
    api.identities.memberships.clear()
    assert api.client.get(URL, headers=auth).status_code == 403
    assert api.client.put(URL, headers=auth, json=replace_payload()).status_code == 403
    api.identities.memberships.add((api.identities.org_id, ACTOR_ID))
    api.identities.permissions[("SpatialTest",)] = ["read:topology"]
    assert api.client.get(URL, headers=auth).status_code == 200
    assert api.client.put(URL, headers=auth, json=replace_payload()).status_code == 403
    api.identities.users[ACTOR_ID].is_active = False
    assert api.client.get(URL, headers=auth).status_code == 401


def test_readonly_member_with_write_permission_cannot_write(api, monkeypatch):
    auth = headers(api)
    monkeypatch.setattr(OrgMemberRepository, "get_member", AsyncMock(return_value=SimpleNamespace(org_role="Read-Only")))
    assert api.client.get(URL, headers=auth).status_code == 200
    assert api.client.put(URL, headers=auth, json=replace_payload()).status_code == 403
    api.persist.assert_not_awaited()


def test_conflict_and_invalid_body_envelopes(api):
    auth = headers(api)
    api.persist.return_value = False
    response = api.client.put(URL, headers=auth, json=replace_payload(5))
    assert response.status_code == 409
    assert response.json()["errors"]["code"] == "SPATIAL_REVISION_CONFLICT"
    assert response.json()["data"] is None
    invalid = replace_payload()
    invalid["scene"]["revision"] = 100
    response = api.client.put(URL, headers=auth, json=invalid)
    assert response.status_code == 422 and response.json()["errors"]["code"] == "VALIDATION_ERROR"
    api.audit.assert_not_awaited()


def test_missing_network(api, monkeypatch):
    monkeypatch.setattr(NetworkRepository, "get_by_id", AsyncMock(return_value=None))
    auth = headers(api)
    assert api.client.get(URL, headers=auth).status_code == 404
    assert api.client.put(URL, headers=auth, json=replace_payload()).status_code == 404


@pytest.mark.parametrize("suffix", ["/history", "/history/1"])
def test_history_current_auth_membership_and_scope(api, suffix):
    assert api.client.get(URL + suffix).status_code == 401
    auth = headers(api, ["read:topology"])
    response = api.client.get(URL + suffix, headers=auth)
    assert response.status_code == 200 and response.json()["success"] is True
    api.identities.memberships.clear()
    assert api.client.get(URL + suffix, headers=auth).status_code == 403
    api.identities.memberships.add((api.identities.org_id, ACTOR_ID))
    scoped = headers(api, ["read:topology"], workspace_id=str(uuid.UUID(int=999)))
    assert api.client.get(URL + suffix, headers=scoped).status_code == 403
    api.identities.permissions[("SpatialTest",)] = ["write:config"]
    assert api.client.get(URL + suffix, headers=auth).status_code == 403


def test_history_list_and_revision_contract(api):
    auth = headers(api)
    response = api.client.get(URL + "/history", headers=auth)
    assert response.json()["data"] == {"items": [], "total": 0, "page": 1, "page_size": 20}
    response = api.client.get(URL + "/history/1", headers=auth)
    assert response.json()["data"] == {**replace_payload()["scene"], "revision": 1}
    api.revision_get.return_value = None
    response = api.client.get(URL + "/history/999", headers=auth)
    assert response.status_code == 404
    assert response.json()["errors"]["code"] == "SPATIAL_REVISION_NOT_FOUND"


@pytest.mark.parametrize("suffix", [
    "/history?page=0", "/history?page=1000001", "/history?page_size=101", "/history?page_size=0",
    "/history?page=1.5", "/history/-1", "/history/9007199254740992", "/history/nope",
])
def test_history_query_and_path_bounds(api, suffix):
    response = api.client.get(URL + suffix, headers=headers(api))
    assert response.status_code == 422 and response.json()["errors"]["code"] == "VALIDATION_ERROR"
    api.history.assert_not_awaited()
    api.revision_get.assert_not_awaited()
