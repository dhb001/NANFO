from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app
from app.modules.network.asset_storage import LocalAssetStore
from app.modules.network.repository import CampusModelAssetRepository, NetworkRepository
from tests.asset_support import ACTOR_ID, NETWORK_ID, WORKSPACE_ID, row


@pytest.fixture
def assets(tenant_auth, monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    monkeypatch.setenv("NETWORK_ASSET_ROOT", str(tmp_path))
    tenant_auth.workspaces[WORKSPACE_ID] = SimpleNamespace(workspace_id=WORKSPACE_ID, org_id=tenant_auth.org_id)
    token, _ = tenant_auth.issue(user_id=str(ACTOR_ID), email="asset@test.example", roles=["Admin"],
                                permissions=["read:topology", "write:config"],
                                workspace_id=str(WORKSPACE_ID), org_id=str(tenant_auth.org_id))
    asset = row()
    monkeypatch.setattr(NetworkRepository, "get_by_id", AsyncMock(return_value=SimpleNamespace(workspace_id=WORKSPACE_ID)))
    monkeypatch.setattr(CampusModelAssetRepository, "get_scoped", AsyncMock(
        side_effect=lambda network, identity: asset if network == NETWORK_ID
        and identity == asset.campus_model_asset_id and asset.deleted_at is None else None,
    ))
    monkeypatch.setattr(CampusModelAssetRepository, "list_for_network", AsyncMock(return_value=[asset]))
    db = AsyncMock()
    db.expire_all = MagicMock()

    async def database():
        yield db

    async def redis():
        yield tenant_auth.redis

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_redis] = redis
    try:
        yield TestClient(app, raise_server_exceptions=False), {
            "Authorization": f"Bearer {token}", "X-Request-ID": "asset-endpoint-test",
        }, asset, tenant_auth
    finally:
        app.dependency_overrides.clear()


def test_verified_download_headers_and_legacy_list(assets):
    client, headers, asset, _ = assets
    listed = client.get(f"/api/v1/networks/{NETWORK_ID}/campus/model-assets", headers=headers)
    assert listed.status_code == 200
    item = listed.json()["data"]["items"][0]
    assert item["registration"] is None and item["storage_backend"] == "inline"
    assert item["model_data_base64"] == asset.model_data_base64
    response = client.get(item["download_path"], headers=headers)
    assert response.status_code == 200 and response.content == b"campus-model"
    assert response.headers["etag"] == f'"sha256:{asset.model_sha256}"'
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("case,code", [("missing-auth", 401), ("permission", 403), ("revoked", 403),
                                      ("foreign", 404), ("deleted", 404), ("tamper", 503), ("missing", 503)])
def test_download_errors_are_enveloped(assets, case, code):
    client, headers, asset, auth = assets
    path = f"/api/v1/networks/{NETWORK_ID}/campus-model-assets/{asset.campus_model_asset_id}/download"
    if case == "missing-auth":
        headers = {"X-Request-ID": "asset-endpoint-test"}
    elif case == "permission":
        auth.permissions[("Admin",)] = ["write:config"]
    elif case == "revoked":
        auth.memberships.clear()
    elif case == "foreign":
        path = path.replace(str(NETWORK_ID), str(WORKSPACE_ID))
    elif case == "deleted":
        asset.deleted_at = asset.created_at
    elif case == "tamper":
        asset.model_data_base64 = "dGFtcGVy"
    elif case == "missing":
        asset.storage_backend, asset.model_data_base64 = "local_cas", None
    response = client.get(path, headers=headers)
    assert response.status_code == code
    envelope = response.json()
    assert envelope["success"] is False and envelope["data"] is None
    assert envelope["errors"]["code"] and envelope["meta"]["request_id"]
    assert "Traceback" not in response.text


def test_cas_download_verifies_disk_before_response(assets):
    client, headers, asset, _ = assets
    store = LocalAssetStore()
    store.put(b"campus-model", asset.model_sha256, asset.model_size_bytes)
    asset.storage_backend, asset.model_data_base64 = "local_cas", None
    path = f"/api/v1/networks/{NETWORK_ID}/campus-model-assets/{asset.campus_model_asset_id}/download"
    assert client.get(path, headers=headers).content == b"campus-model"
    body_path = store.settings.root / asset.model_sha256
    body_path.chmod(0o600)
    body_path.write_bytes(b"tampered!!!!")
    response = client.get(path, headers=headers)
    assert response.status_code == 503
    assert response.json()["errors"]["code"] == "CAMPUS_MODEL_ASSET_INTEGRITY_FAILED"
    assert "tampered" not in response.text


def test_retire_asset_204_repeat_and_download_404(assets):
    client, headers, asset, _ = assets
    path = f"/api/v1/networks/{NETWORK_ID}/campus/model-assets/{asset.campus_model_asset_id}"
    original_body = asset.model_data_base64
    response = client.delete(path, headers=headers)
    assert response.status_code == 204 and response.content == b""
    assert asset.deleted_at is not None and asset.model_data_base64 == original_body
    assert client.delete(path, headers=headers).status_code == 404
    assert client.get(f"/api/v1/networks/{NETWORK_ID}/campus-model-assets/{asset.campus_model_asset_id}/download",
                      headers=headers).status_code == 404


@pytest.mark.parametrize("case,code", [("permission", 403), ("revoked", 403), ("foreign", 404), ("invalid", 422)])
def test_retire_asset_scope_denials(assets, case, code):
    client, headers, asset, auth = assets
    identity = str(asset.campus_model_asset_id)
    if case == "permission":
        auth.permissions[("Admin",)] = ["read:topology"]
    elif case == "revoked":
        auth.memberships.clear()
    elif case == "foreign":
        identity = str(WORKSPACE_ID)
    else:
        identity = "invalid"
    response = client.delete(f"/api/v1/networks/{NETWORK_ID}/campus/model-assets/{identity}", headers=headers)
    assert response.status_code == code and response.json()["success"] is False
    assert asset.deleted_at is None


def test_conflicting_equivalent_mapping_keys_returns_422(assets):
    from tests.asset_support import request

    client, headers, _, _ = assets
    identity = "abcdefab-1234-5678-9abc-abcdef123456"
    payload = request().model_dump(mode="json")
    payload["mapping_by_device_id"] = {identity: "room-a", identity.upper(): "room-b"}
    response = client.post(f"/api/v1/networks/{NETWORK_ID}/campus/model-assets", headers=headers, json=payload)
    assert response.status_code == 422 and response.json()["success"] is False
