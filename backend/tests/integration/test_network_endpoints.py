"""Integration tests for network and device endpoints via FastAPI TestClient.

Tests: routing, status codes, envelope format, C6 constraint (deferred endpoints absent).
Dependencies overridden with mocks.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.core.security import create_access_token
from app.main import app
from app.modules.network.schemas import (
    CampusBuildingListResponse,
    CampusModelAssetListResponse,
    DeviceGroupListResponse,
    TopologyDeviceNeighboursResponse,
    TopologyGraphResponse,
    TopologyImpactResponse,
)


def _make_token():
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="test@example.com",
        roles=["Admin"],
        permissions=["write:config", "read:topology"],
    )
    return token


def _make_token_with_workspace(*, permissions: list[str], workspace_id: uuid.UUID, org_id: uuid.UUID | None = None) -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="test@example.com",
        roles=["Admin"],
        permissions=permissions,
        org_id=str(org_id) if org_id is not None else None,
        workspace_id=str(workspace_id),
    )
    return token


def _make_token_without_permission() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="test@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
    )
    return token


@pytest.fixture
def client() -> TestClient:
    import fakeredis
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    fake_r = fakeredis.FakeAsyncRedis(decode_responses=True)

    async def _db():
        yield db

    async def _redis():
        yield fake_r

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture
def token():
    return _make_token()


@pytest.fixture
def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _patch_topology_scope_resolution():
    async def _resolve_network_scope(*, network_id, claims, db, redis):
        return network_id, uuid.uuid4()

    async def _resolve_device_scope(*, device_id, claims, db, redis):
        return uuid.uuid4(), uuid.uuid4()

    with (
        patch("app.api.v1.topology._resolve_network_scope", side_effect=_resolve_network_scope),
        patch("app.api.v1.topology._resolve_device_scope", side_effect=_resolve_device_scope),
    ):
        yield


class TestNetworkEndpointsAuth:
    def test_create_network_without_auth_returns_403(self, client):
        response = client.post("/api/v1/networks", json={})
        assert response.status_code in (401, 403)

    def test_list_networks_without_auth_returns_403(self, client):
        response = client.get("/api/v1/networks", params={"workspace_id": str(uuid.uuid4())})
        assert response.status_code in (401, 403)

    def test_create_network_missing_write_permission_returns_403(self, client):
        token = _make_token_without_permission()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            "/api/v1/networks",
            json={"workspace_id": str(uuid.uuid4()), "name": "Denied"},
            headers=headers,
        )
        assert response.status_code == 403

    def test_list_networks_missing_read_topology_permission_returns_403(self, client):
        token = _make_token_without_permission()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get(
            "/api/v1/networks",
            params={"workspace_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert response.status_code == 403

    def test_add_device_missing_write_permission_returns_403(self, client):
        token = _make_token_without_permission()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            f"/api/v1/networks/{uuid.uuid4()}/devices",
            json={"hostname": "r1", "device_type": "router"},
            headers=headers,
        )
        assert response.status_code == 403

    def test_list_devices_missing_read_topology_permission_returns_403(self, client):
        token = _make_token_without_permission()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get(
            f"/api/v1/networks/{uuid.uuid4()}/devices",
            headers=headers,
        )
        assert response.status_code == 403

    def test_update_device_missing_write_permission_returns_403(self, client):
        token = _make_token_without_permission()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.patch(
            f"/api/v1/networks/{uuid.uuid4()}/devices/{uuid.uuid4()}",
            json={"spatial_ref_id": "campus-a/device"},
            headers=headers,
        )
        assert response.status_code == 403

    def test_list_campus_buildings_missing_read_topology_permission_returns_403(self, client):
        token = _make_token_without_permission()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get(
            f"/api/v1/networks/{uuid.uuid4()}/campus/buildings",
            headers=headers,
        )
        assert response.status_code == 403

    def test_upsert_campus_buildings_missing_write_permission_returns_403(self, client):
        token = _make_token_without_permission()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            f"/api/v1/networks/{uuid.uuid4()}/campus/buildings",
            json={"buildings": []},
            headers=headers,
        )
        assert response.status_code == 403

    def test_list_campus_model_assets_missing_read_topology_permission_returns_403(self, client):
        token = _make_token_without_permission()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get(
            f"/api/v1/networks/{uuid.uuid4()}/campus/model-assets",
            headers=headers,
        )
        assert response.status_code == 403

    def test_upsert_campus_model_assets_missing_write_permission_returns_403(self, client):
        token = _make_token_without_permission()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            f"/api/v1/networks/{uuid.uuid4()}/campus/model-assets",
            json={
                "model_file_name": "campus.glb",
                "model_mime_type": "model/gltf-binary",
                "model_data_base64": "YQ==",
                "model_sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                "model_size_bytes": 1,
                "mapping_by_device_id": {},
            },
            headers=headers,
        )
        assert response.status_code == 403

    def test_list_device_groups_missing_read_topology_permission_returns_403(self, client):
        token = _make_token_without_permission()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get(
            f"/api/v1/networks/{uuid.uuid4()}/device-groups",
            headers=headers,
        )
        assert response.status_code == 403

    def test_upsert_device_groups_missing_write_permission_returns_403(self, client):
        token = _make_token_without_permission()
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            f"/api/v1/networks/{uuid.uuid4()}/device-groups",
            json={"groups": []},
            headers=headers,
        )
        assert response.status_code == 403

    def test_list_networks_workspace_scope_mismatch_returns_403(self, client):
        token_workspace_id = uuid.uuid4()
        request_workspace_id = uuid.uuid4()
        token = _make_token_with_workspace(
            permissions=["write:config", "read:topology"],
            workspace_id=token_workspace_id,
        )
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get(
            "/api/v1/networks",
            params={"workspace_id": str(request_workspace_id)},
            headers=headers,
        )
        assert response.status_code == 403

    def test_create_network_workspace_scope_mismatch_returns_403(self, client):
        token_workspace_id = uuid.uuid4()
        request_workspace_id = uuid.uuid4()
        token = _make_token_with_workspace(
            permissions=["write:config", "read:topology"],
            workspace_id=token_workspace_id,
        )
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            "/api/v1/networks",
            json={"workspace_id": str(request_workspace_id), "name": "Mismatch"},
            headers=headers,
        )
        assert response.status_code == 403

    def test_list_networks_org_claim_mismatch_returns_403(self, client):
        token_workspace_id = uuid.uuid4()
        token_org_id = uuid.uuid4()
        token = _make_token_with_workspace(
            permissions=["write:config", "read:topology"],
            workspace_id=token_workspace_id,
            org_id=token_org_id,
        )
        headers = {"Authorization": f"Bearer {token}"}

        with patch(
            "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(workspace_id=token_workspace_id, org_id=uuid.uuid4()),
        ):
            response = client.get(
                "/api/v1/networks",
                params={"workspace_id": str(token_workspace_id)},
                headers=headers,
            )

        assert response.status_code == 403

    def test_create_network_org_claim_mismatch_returns_403(self, client):
        token_workspace_id = uuid.uuid4()
        token_org_id = uuid.uuid4()
        token = _make_token_with_workspace(
            permissions=["write:config", "read:topology"],
            workspace_id=token_workspace_id,
            org_id=token_org_id,
        )
        headers = {"Authorization": f"Bearer {token}"}

        with patch(
            "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(workspace_id=token_workspace_id, org_id=uuid.uuid4()),
        ):
            response = client.post(
                "/api/v1/networks",
                json={"workspace_id": str(token_workspace_id), "name": "DeniedOrg"},
                headers=headers,
            )

        assert response.status_code == 403


class TestCreateNetwork:
    def test_create_network_missing_workspace_id_returns_422(self, client, headers):
        response = client.post(
            "/api/v1/networks",
            json={"name": "Net"},  # missing workspace_id
            headers=headers,
        )
        assert response.status_code == 422

    def test_create_network_missing_name_returns_422(self, client, headers):
        response = client.post(
            "/api/v1/networks",
            json={"workspace_id": str(uuid.uuid4())},  # missing name
            headers=headers,
        )
        assert response.status_code == 422

    def test_create_network_invalid_workspace_returns_404(self, client, headers):
        """C5: invalid workspace_id must propagate 404 from WorkspaceService."""
        ws_id = uuid.uuid4()
        with patch(
            "app.modules.network.service.NetworkService.create_network",
            side_effect=HTTPException(status_code=404, detail="Workspace not found or has been deleted."),
        ):
            response = client.post(
                "/api/v1/networks",
                json={"workspace_id": str(ws_id), "name": "X"},
                headers=headers,
            )
        assert response.status_code == 404


class TestDeviceEndpoints:
    def test_add_device_missing_required_fields_returns_422(self, client, headers):
        network_id = uuid.uuid4()
        response = client.post(
            f"/api/v1/networks/{network_id}/devices",
            json={"hostname": "r1"},  # missing device_type
            headers=headers,
        )
        assert response.status_code == 422

    def test_update_device_missing_spatial_ref_id_returns_422(self, client, headers):
        response = client.patch(
            f"/api/v1/networks/{uuid.uuid4()}/devices/{uuid.uuid4()}",
            json={},
            headers=headers,
        )
        assert response.status_code == 422

    def test_add_device_returns_envelope(self, client, headers):
        """POST /networks/{id}/devices must return API_STANDARD.md §2 envelope."""
        from datetime import UTC, datetime
        network_id = uuid.uuid4()
        device_data = {
            "device_id": str(uuid.uuid4()),
            "network_id": str(network_id),
            "hostname": "router-01",
            "ip_address": "10.0.0.1",
            "device_type": "router",
            "vendor": None,
            "model": None,
            "location_hint": None,
            "spatial_ref_id": "campus-a/building-1/floor-2/room-204/rack-3/device-router-01",
            "status": "active",
            "created_at": datetime.now(UTC).isoformat(),
        }
        from app.modules.network.schemas import DeviceResponse
        with patch(
            "app.modules.network.service.DeviceService.add_device",
            return_value=DeviceResponse(**device_data),
        ):
            response = client.post(
                f"/api/v1/networks/{network_id}/devices",
                json={
                    "hostname": "router-01",
                    "device_type": "router",
                    "spatial_ref_id": "campus-a/building-1/floor-2/room-204/rack-3/device-router-01",
                },
                headers=headers,
            )
        body = response.json()
        assert "success" in body
        assert "data" in body
        assert "meta" in body
        assert "errors" in body
        assert body["data"]["spatial_ref_id"] == "campus-a/building-1/floor-2/room-204/rack-3/device-router-01"

    def test_update_device_spatial_ref_returns_envelope(self, client, headers):
        """PATCH /networks/{id}/devices/{id} must return API_STANDARD.md §2 envelope."""
        from datetime import UTC, datetime

        network_id = uuid.uuid4()
        device_id = uuid.uuid4()
        device_data = {
            "device_id": str(device_id),
            "network_id": str(network_id),
            "hostname": "router-01",
            "ip_address": "10.0.0.1",
            "device_type": "router",
            "vendor": None,
            "model": None,
            "location_hint": None,
            "spatial_ref_id": "campus-a/building-1/floor-2/room-204/rack-3/device-router-01",
            "status": "active",
            "created_at": datetime.now(UTC).isoformat(),
        }
        from app.modules.network.schemas import DeviceResponse

        with patch(
            "app.modules.network.service.DeviceService.update_device_spatial_ref",
            return_value=DeviceResponse(**device_data),
        ):
            response = client.patch(
                f"/api/v1/networks/{network_id}/devices/{device_id}",
                json={
                    "spatial_ref_id": "campus-a/building-1/floor-2/room-204/rack-3/device-router-01",
                },
                headers=headers,
            )

        body = response.json()
        assert response.status_code == 200
        assert "success" in body
        assert "data" in body
        assert "meta" in body
        assert "errors" in body
        assert body["data"]["spatial_ref_id"] == "campus-a/building-1/floor-2/room-204/rack-3/device-router-01"

    def test_update_device_spatial_ref_not_found_propagates_404(self, client, headers):
        network_id = uuid.uuid4()
        device_id = uuid.uuid4()

        with patch(
            "app.modules.network.service.DeviceService.update_device_spatial_ref",
            side_effect=HTTPException(status_code=404, detail="Device not found."),
        ):
            response = client.patch(
                f"/api/v1/networks/{network_id}/devices/{device_id}",
                json={"spatial_ref_id": "campus-a/device-404"},
                headers=headers,
            )

        assert response.status_code == 404


class TestCampusBuildingEndpoints:
    def test_list_campus_buildings_returns_envelope(self, client, headers):
        from datetime import UTC, datetime

        network_id = uuid.uuid4()
        payload = CampusBuildingListResponse(
            items=[
                {
                    "campus_building_id": str(uuid.uuid4()),
                    "network_id": str(network_id),
                    "building_id": "campus-a:building-1",
                    "campus_key": "campus-a",
                    "building_key": "building-1",
                    "label": "Building 1",
                    "geometry": "box",
                    "x": 4.0,
                    "z": -3.0,
                    "base_y": -2.3,
                    "width": 12.0,
                    "depth": 9.0,
                    "height": 8.5,
                    "floors": 3,
                    "footprint": [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0]],
                    "wall_material": "concrete",
                    "attenuation_db": 14.0,
                    "source": "geojson",
                    "created_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ],
            total=1,
        )

        with patch(
            "app.modules.network.service.CampusBuildingService.list_buildings",
            return_value=payload,
        ):
            response = client.get(
                f"/api/v1/networks/{network_id}/campus/buildings",
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "data" in body
        assert "meta" in body
        assert "errors" in body
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["building_id"] == "campus-a:building-1"

    def test_upsert_campus_buildings_returns_envelope(self, client, headers):
        from datetime import UTC, datetime

        network_id = uuid.uuid4()
        payload = CampusBuildingListResponse(
            items=[
                {
                    "campus_building_id": str(uuid.uuid4()),
                    "network_id": str(network_id),
                    "building_id": "campus-a:building-1",
                    "campus_key": "campus-a",
                    "building_key": "building-1",
                    "label": "Building 1",
                    "geometry": "box",
                    "x": 4.0,
                    "z": -3.0,
                    "base_y": -2.3,
                    "width": 12.0,
                    "depth": 9.0,
                    "height": 8.5,
                    "floors": 3,
                    "footprint": [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0]],
                    "wall_material": "concrete",
                    "attenuation_db": 14.0,
                    "source": "geojson",
                    "created_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ],
            total=1,
        )

        with patch(
            "app.modules.network.service.CampusBuildingService.upsert_buildings",
            return_value=payload,
        ):
            response = client.post(
                f"/api/v1/networks/{network_id}/campus/buildings",
                json={
                    "replace_existing": True,
                    "buildings": [
                        {
                            "building_id": "campus-a:building-1",
                            "campus_key": "campus-a",
                            "building_key": "building-1",
                            "label": "Building 1",
                            "geometry": "box",
                            "x": 4.0,
                            "z": -3.0,
                            "base_y": -2.3,
                            "width": 12.0,
                            "depth": 9.0,
                            "height": 8.5,
                            "floors": 3,
                            "footprint": [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0]],
                            "wall_material": "concrete",
                            "attenuation_db": 14.0,
                            "source": "geojson",
                        }
                    ],
                },
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "data" in body
        assert "meta" in body
        assert "errors" in body
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["geometry"] == "box"

    def test_upsert_campus_buildings_invalid_geometry_returns_422(self, client, headers):
        response = client.post(
            f"/api/v1/networks/{uuid.uuid4()}/campus/buildings",
            json={
                "replace_existing": True,
                "buildings": [
                    {
                        "building_id": "campus-a:building-1",
                        "campus_key": "campus-a",
                        "building_key": "building-1",
                        "label": "Building 1",
                        "geometry": "invalid-shape",
                        "x": 4.0,
                        "z": -3.0,
                        "base_y": -2.3,
                        "width": 12.0,
                        "depth": 9.0,
                        "height": 8.5,
                        "floors": 3,
                        "footprint": [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0]],
                    }
                ],
            },
            headers=headers,
        )

        assert response.status_code == 422

    def test_upsert_campus_buildings_not_found_propagates_404(self, client, headers):
        network_id = uuid.uuid4()
        with patch(
            "app.modules.network.service.CampusBuildingService.upsert_buildings",
            side_effect=HTTPException(status_code=404, detail="Network not found."),
        ):
            response = client.post(
                f"/api/v1/networks/{network_id}/campus/buildings",
                json={"buildings": []},
                headers=headers,
            )

        assert response.status_code == 404


class TestCampusModelAssetEndpoints:
    def test_list_campus_model_assets_returns_envelope(self, client, headers):
        from datetime import UTC, datetime

        network_id = uuid.uuid4()
        payload = CampusModelAssetListResponse(
            items=[
                {
                    "campus_model_asset_id": str(uuid.uuid4()),
                    "network_id": str(network_id),
                    "model_file_name": "campus.glb",
                    "model_mime_type": "model/gltf-binary",
                    "model_data_base64": "YQ==",
                    "model_sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                    "model_size_bytes": 1,
                    "mapping_by_device_id": {},
                    "source": "manual_upload",
                    "created_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ],
            total=1,
        )

        with patch(
            "app.modules.network.service.CampusModelAssetService.list_assets",
            return_value=payload,
        ):
            response = client.get(
                f"/api/v1/networks/{network_id}/campus/model-assets",
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "data" in body
        assert "meta" in body
        assert "errors" in body
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["model_file_name"] == "campus.glb"

    def test_upsert_campus_model_assets_returns_envelope(self, client, headers):
        from datetime import UTC, datetime

        network_id = uuid.uuid4()
        payload = CampusModelAssetListResponse(
            items=[
                {
                    "campus_model_asset_id": str(uuid.uuid4()),
                    "network_id": str(network_id),
                    "model_file_name": "campus.glb",
                    "model_mime_type": "model/gltf-binary",
                    "model_data_base64": "YQ==",
                    "model_sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                    "model_size_bytes": 1,
                    "mapping_by_device_id": {},
                    "source": "manual_upload",
                    "created_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ],
            total=1,
        )

        with patch(
            "app.modules.network.service.CampusModelAssetService.upsert_asset",
            return_value=payload,
        ):
            response = client.post(
                f"/api/v1/networks/{network_id}/campus/model-assets",
                json={
                    "model_file_name": "campus.glb",
                    "model_mime_type": "model/gltf-binary",
                    "model_data_base64": "YQ==",
                    "model_sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                    "model_size_bytes": 1,
                    "mapping_by_device_id": {},
                    "replace_existing": True,
                },
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "data" in body
        assert "meta" in body
        assert "errors" in body
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["model_mime_type"] == "model/gltf-binary"

    def test_upsert_campus_model_assets_invalid_payload_returns_422(self, client, headers):
        response = client.post(
            f"/api/v1/networks/{uuid.uuid4()}/campus/model-assets",
            json={
                "model_file_name": "campus.txt",
                "model_mime_type": "model/gltf-binary",
                "model_data_base64": "YQ==",
                "model_sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                "model_size_bytes": 1,
                "mapping_by_device_id": {},
            },
            headers=headers,
        )

        assert response.status_code == 422

    def test_upsert_campus_model_assets_not_found_propagates_404(self, client, headers):
        network_id = uuid.uuid4()
        with patch(
            "app.modules.network.service.CampusModelAssetService.upsert_asset",
            side_effect=HTTPException(status_code=404, detail="Network not found."),
        ):
            response = client.post(
                f"/api/v1/networks/{network_id}/campus/model-assets",
                json={
                    "model_file_name": "campus.glb",
                    "model_mime_type": "model/gltf-binary",
                    "model_data_base64": "YQ==",
                    "model_sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                    "model_size_bytes": 1,
                    "mapping_by_device_id": {},
                },
                headers=headers,
            )

        assert response.status_code == 404


class TestDeviceGroupEndpoints:
    def test_list_device_groups_returns_envelope(self, client, headers):
        from datetime import UTC, datetime

        network_id = uuid.uuid4()
        payload = DeviceGroupListResponse(
            items=[
                {
                    "device_group_id": str(uuid.uuid4()),
                    "network_id": str(network_id),
                    "group_key": "ssc-f02-wireless",
                    "name": "SSC F02 Wireless",
                    "group_type": "functional",
                    "description": "Wireless access points on floor 2",
                    "selector": {
                        "site_prefix": "strathmore/ssc/f02",
                        "functional_group": "wireless",
                    },
                    "device_ids": [str(uuid.uuid4())],
                    "created_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ],
            total=1,
        )

        with patch(
            "app.modules.network.service.DeviceGroupService.list_groups",
            return_value=payload,
        ):
            response = client.get(
                f"/api/v1/networks/{network_id}/device-groups",
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "data" in body
        assert "meta" in body
        assert "errors" in body
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["group_key"] == "ssc-f02-wireless"

    def test_upsert_device_groups_returns_envelope(self, client, headers):
        from datetime import UTC, datetime

        network_id = uuid.uuid4()
        payload = DeviceGroupListResponse(
            items=[
                {
                    "device_group_id": str(uuid.uuid4()),
                    "network_id": str(network_id),
                    "group_key": "ssc-f02-wireless",
                    "name": "SSC F02 Wireless",
                    "group_type": "functional",
                    "description": "Wireless access points on floor 2",
                    "selector": {
                        "site_prefix": "strathmore/ssc/f02",
                        "functional_group": "wireless",
                    },
                    "device_ids": [str(uuid.uuid4())],
                    "created_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ],
            total=1,
        )

        with patch(
            "app.modules.network.service.DeviceGroupService.upsert_groups",
            return_value=payload,
        ):
            response = client.post(
                f"/api/v1/networks/{network_id}/device-groups",
                json={
                    "replace_existing": True,
                    "groups": [
                        {
                            "group_key": "ssc-f02-wireless",
                            "name": "SSC F02 Wireless",
                            "group_type": "functional",
                            "selector": {
                                "site_prefix": "strathmore/ssc/f02",
                                "functional_group": "wireless",
                            },
                            "device_ids": [str(uuid.uuid4())],
                        }
                    ],
                },
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "data" in body
        assert "meta" in body
        assert "errors" in body
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["group_type"] == "functional"

    def test_upsert_device_groups_invalid_payload_returns_422(self, client, headers):
        response = client.post(
            f"/api/v1/networks/{uuid.uuid4()}/device-groups",
            json={
                "replace_existing": False,
                "groups": [
                    {
                        "group_key": "empty-group",
                        "name": "Empty Group",
                        "group_type": "custom",
                        "selector": {},
                        "device_ids": [],
                    }
                ],
            },
            headers=headers,
        )

        assert response.status_code == 422

    def test_upsert_device_groups_not_found_propagates_404(self, client, headers):
        network_id = uuid.uuid4()
        with patch(
            "app.modules.network.service.DeviceGroupService.upsert_groups",
            side_effect=HTTPException(status_code=404, detail="Network not found."),
        ):
            response = client.post(
                f"/api/v1/networks/{network_id}/device-groups",
                json={"groups": []},
                headers=headers,
            )

        assert response.status_code == 404


class TestTopologyRouteSurface:
    """VS10: topology analysis route surface is enabled while legacy paths stay non-routable."""

    def test_neighbors_endpoint_does_not_exist(self, client, headers):
        network_id = uuid.uuid4()
        response = client.get("/api/v1/topology/neighbors", params={"network_id": str(network_id)}, headers=headers)
        assert response.status_code == 404

    def test_impact_endpoint_does_not_exist(self, client, headers):
        network_id = uuid.uuid4()
        response = client.get("/api/v1/topology/impact", params={"network_id": str(network_id)}, headers=headers)
        assert response.status_code == 404

    def test_reconcile_subpath_pattern_still_not_routable(self, client, headers):
        response = client.post("/api/v1/topology/reconcile/full", headers=headers)
        assert response.status_code == 404

    def test_reconcile_get_method_still_not_routable(self, client, headers):
        response = client.get("/api/v1/topology/reconcile", headers=headers)
        assert response.status_code == 405

    def test_impact_path_post_method_still_not_routable(self, client, headers):
        response = client.post(f"/api/v1/topology/impact/{uuid.uuid4()}", headers=headers)
        assert response.status_code == 405

    def test_topology_read_routes_require_read_topology_permission(self, client):
        token, _ = create_access_token(
            user_id=str(uuid.uuid4()),
            email="topology-no-read@example.com",
            roles=["Admin"],
            permissions=["read:telemetry", "write:config"],
        )
        headers = {"Authorization": f"Bearer {token}"}

        graph_response = client.get(
            "/api/v1/topology/graph",
            params={"network_id": str(uuid.uuid4())},
            headers=headers,
        )
        node_response = client.get(f"/api/v1/topology/nodes/{uuid.uuid4()}", headers=headers)
        neighbors_response = client.get(
            f"/api/v1/topology/device/{uuid.uuid4()}/neighbors",
            headers=headers,
        )
        impact_response = client.get(
            f"/api/v1/topology/impact/{uuid.uuid4()}",
            headers=headers,
        )

        assert graph_response.status_code == 403
        assert node_response.status_code == 403
        assert neighbors_response.status_code == 403
        assert impact_response.status_code == 403

    def test_topology_reconcile_requires_write_config_permission(self, client):
        token, _ = create_access_token(
            user_id=str(uuid.uuid4()),
            email="topology-no-write@example.com",
            roles=["Admin"],
            permissions=["read:topology"],
        )
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post(
            "/api/v1/topology/reconcile",
            json={"network_id": str(uuid.uuid4())},
            headers=headers,
        )

        assert response.status_code == 403

    def test_topology_graph_endpoint_exists(self, client, headers):
        """Confirm GET /topology/graph IS registered (not blocked by C6)."""
        # Will fail with 500 if Neo4j isn't running — that's expected without infrastructure
        # The key check is that it's NOT a 404
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_graph",
                return_value=(TopologyGraphResponse(nodes=[], edges=[]), None),
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                "/api/v1/topology/graph",
                params={"network_id": str(uuid.uuid4())},
                headers=headers,
            )
        assert response.status_code != 404

    def test_topology_neighbors_endpoint_exists(self, client, headers):
        payload = TopologyDeviceNeighboursResponse(
            device={
                "device_id": "device-1",
                "hostname": "core-1",
                "device_type": "router",
                "status": "active",
                "spatial_ref_id": None,
            },
            neighbours=[],
            depth=1,
            total=0,
        )
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_device_neighbours",
                return_value=payload,
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/device/{uuid.uuid4()}/neighbors",
                headers=headers,
            )

        assert response.status_code != 404

    def test_topology_impact_endpoint_exists(self, client, headers):
        payload = TopologyImpactResponse(
            device={
                "device_id": "device-1",
                "hostname": "core-1",
                "device_type": "router",
                "status": "active",
                "spatial_ref_id": None,
            },
            impacts=[],
            max_hops=3,
            total=0,
        )
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_impact_analysis",
                return_value=payload,
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/impact/{uuid.uuid4()}",
                headers=headers,
            )

        assert response.status_code != 404

    def test_topology_reconcile_endpoint_exists(self, client, headers):
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.reconcile_network",
                return_value={
                    "reconcile_id": str(uuid.uuid4()),
                    "network_id": str(uuid.uuid4()),
                    "status": "completed",
                    "checked_nodes": 2,
                    "checked_edges": 1,
                    "missing_workspace_nodes": 0,
                    "workspace_backfilled_nodes": 0,
                    "warning": None,
                },
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.post(
                "/api/v1/topology/reconcile",
                json={"network_id": str(uuid.uuid4())},
                headers=headers,
            )

        assert response.status_code != 404

    def test_topology_graph_denied_on_unresolved_scope_returns_403(self, client, headers):
        with (
            patch(
            "app.api.v1.topology._resolve_network_scope",
            side_effect=HTTPException(status_code=403, detail="Insufficient scope."),
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                "/api/v1/topology/graph",
                params={"network_id": str(uuid.uuid4())},
                headers=headers,
            )

        assert response.status_code == 403

    def test_topology_node_denied_on_unresolved_scope_returns_403(self, client, headers):
        with (
            patch(
            "app.api.v1.topology._resolve_device_scope",
            side_effect=HTTPException(status_code=403, detail="Insufficient scope."),
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/nodes/{uuid.uuid4()}",
                headers=headers,
            )

        assert response.status_code == 403

    def test_topology_neighbors_denied_on_unresolved_scope_returns_403(self, client, headers):
        with (
            patch(
            "app.api.v1.topology._resolve_device_scope",
            side_effect=HTTPException(status_code=403, detail="Insufficient scope."),
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/device/{uuid.uuid4()}/neighbors",
                headers=headers,
            )

        assert response.status_code == 403

    def test_topology_impact_denied_on_unresolved_scope_returns_403(self, client, headers):
        with (
            patch(
            "app.api.v1.topology._resolve_device_scope",
            side_effect=HTTPException(status_code=403, detail="Insufficient scope."),
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/impact/{uuid.uuid4()}",
                headers=headers,
            )

        assert response.status_code == 403

    def test_topology_reconcile_denied_on_unresolved_scope_returns_403(self, client, headers):
        with (
            patch(
            "app.api.v1.topology._resolve_network_scope",
            side_effect=HTTPException(status_code=403, detail="Insufficient scope."),
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.post(
                "/api/v1/topology/reconcile",
                json={"network_id": str(uuid.uuid4())},
                headers=headers,
            )

        assert response.status_code == 403

    def test_topology_graph_scope_resolution_includes_claim_org_and_workspace(self, client):
        token_workspace_id = uuid.uuid4()
        token_org_id = uuid.uuid4()
        token = _make_token_with_workspace(
            permissions=["read:topology", "write:config"],
            workspace_id=token_workspace_id,
            org_id=token_org_id,
        )
        headers = {"Authorization": f"Bearer {token}"}

        request_network_id = uuid.uuid4()

        async def _resolve_scope(*, network_id, claims, db, redis):
            assert claims.workspace_id == str(token_workspace_id)
            assert claims.org_id == str(token_org_id)
            return network_id, token_workspace_id

        with (
            patch("app.api.v1.topology._resolve_network_scope", side_effect=_resolve_scope),
            patch(
                "app.modules.network.topology.TopologyQueryService.get_graph",
                return_value=(TopologyGraphResponse(nodes=[], edges=[]), None),
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                "/api/v1/topology/graph",
                params={"network_id": str(request_network_id)},
                headers=headers,
            )

        assert response.status_code != 403
        assert response.status_code == 200

    def test_topology_node_scope_resolution_includes_claim_org_and_workspace(self, client):
        token_workspace_id = uuid.uuid4()
        token_org_id = uuid.uuid4()
        token = _make_token_with_workspace(
            permissions=["read:topology", "write:config"],
            workspace_id=token_workspace_id,
            org_id=token_org_id,
        )
        headers = {"Authorization": f"Bearer {token}"}

        request_device_id = uuid.uuid4()

        async def _resolve_scope(*, device_id, claims, db, redis):
            assert device_id == request_device_id
            assert claims.workspace_id == str(token_workspace_id)
            assert claims.org_id == str(token_org_id)
            return uuid.uuid4(), token_workspace_id

        with (
            patch("app.api.v1.topology._resolve_device_scope", side_effect=_resolve_scope),
            patch(
                "app.modules.network.topology.TopologyQueryService.get_node_with_neighbours",
                return_value={
                    "node": {
                        "device_id": str(request_device_id),
                        "hostname": "n1",
                        "device_type": "router",
                        "status": "active",
                        "spatial_ref_id": None,
                    },
                    "neighbours": [],
                },
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/nodes/{request_device_id}",
                headers=headers,
            )

        assert response.status_code != 403
        assert response.status_code == 200


class TestTopologyGraphPagination:
    def test_topology_graph_accepts_limit_and_cursor(self, client, headers):
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_graph",
                return_value=(TopologyGraphResponse(nodes=[], edges=[]), "node-2"),
            ) as mock_get_graph,
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                "/api/v1/topology/graph",
                params={
                    "network_id": str(uuid.uuid4()),
                    "limit": 2,
                    "cursor": "node-1",
                },
                headers=headers,
            )

        assert response.status_code == 200
        call_kwargs = mock_get_graph.call_args.kwargs
        assert call_kwargs["limit"] == 2
        assert call_kwargs["cursor"] == "node-1"

        body = response.json()
        assert body["meta"]["next_cursor"] == "node-2"

    def test_topology_graph_omits_next_cursor_when_last_page(self, client, headers):
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_graph",
                return_value=(TopologyGraphResponse(nodes=[], edges=[]), None),
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                "/api/v1/topology/graph",
                params={"network_id": str(uuid.uuid4()), "limit": 2},
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["next_cursor"] is None


class TestTopologyNodeEndpoint:
    def test_topology_nodes_endpoint_exists_and_returns_envelope(self, client, headers):
        payload = {
            "node": {
                "device_id": "device-1",
                "hostname": "core-1",
                "device_type": "router",
                "status": "active",
                "spatial_ref_id": "campus-a/core-1",
            },
            "neighbours": [
                {
                    "device_id": "device-2",
                    "hostname": "edge-2",
                    "device_type": "switch",
                    "status": "active",
                    "spatial_ref_id": "campus-a/edge-2",
                    "edge_type": "connected_to",
                    "direction": "inbound",
                },
                {
                    "device_id": "device-3",
                    "hostname": "edge-3",
                    "device_type": "switch",
                    "status": "active",
                    "spatial_ref_id": None,
                    "edge_type": "connected_to",
                    "direction": "outbound",
                },
            ],
        }

        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_node_with_neighbours",
                return_value=payload,
            ) as mock_get_node,
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/nodes/{uuid.uuid4()}",
                headers=headers,
            )

        assert response.status_code == 200
        call_kwargs = mock_get_node.call_args.kwargs
        assert call_kwargs["depth"] == 1

        body = response.json()
        assert body["success"] is True
        assert "data" in body
        assert "meta" in body
        assert "errors" in body
        assert body["data"]["node"]["spatial_ref_id"] == "campus-a/core-1"
        assert body["data"]["neighbours"][0]["spatial_ref_id"] == "campus-a/edge-2"
        assert body["data"]["neighbours"][0]["edge_type"] == "connected_to"
        assert body["data"]["neighbours"][0]["direction"] == "inbound"

    def test_topology_nodes_success_with_origin_returns_cors_header(self, client, headers):
        payload = {
            "node": {
                "device_id": "device-1",
                "hostname": "core-1",
                "device_type": "router",
                "status": "active",
                "spatial_ref_id": "campus-a/core-1",
            },
            "neighbours": [],
        }

        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_node_with_neighbours",
                return_value=payload,
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/nodes/{uuid.uuid4()}",
                headers={
                    **headers,
                    "Origin": "http://127.0.0.1:5173",
                },
            )

        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"

    def test_topology_graph_envelope_can_carry_spatial_ref_id_when_present(self, client, headers):
        payload = TopologyGraphResponse(
            nodes=[
                {
                    "device_id": "device-1",
                    "hostname": "core-1",
                    "device_type": "router",
                    "status": "active",
                    "spatial_ref_id": "campus-a/core-1",
                },
                {
                    "device_id": "device-2",
                    "hostname": "edge-2",
                    "device_type": "switch",
                    "status": "active",
                    "spatial_ref_id": None,
                },
            ],
            edges=[],
        )

        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_graph",
                return_value=(payload, None),
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                "/api/v1/topology/graph",
                params={"network_id": str(uuid.uuid4())},
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["nodes"][0]["spatial_ref_id"] == "campus-a/core-1"
        assert body["data"]["nodes"][1]["spatial_ref_id"] is None

    def test_topology_nodes_endpoint_accepts_depth_parameter(self, client, headers):
        payload = {
            "node": {
                "device_id": "device-1",
                "hostname": "core-1",
                "device_type": "router",
                "status": "active",
            },
            "neighbours": [],
        }
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_node_with_neighbours",
                return_value=payload,
            ) as mock_get_node,
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/nodes/{uuid.uuid4()}?depth=4",
                headers=headers,
            )

        assert response.status_code == 200
        call_kwargs = mock_get_node.call_args.kwargs
        assert call_kwargs["depth"] == 4

    def test_topology_nodes_endpoint_not_found_returns_404(self, client, headers):
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_node_with_neighbours",
                return_value=None,
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/nodes/{uuid.uuid4()}",
                headers=headers,
            )

        assert response.status_code == 404

    def test_topology_nodes_endpoint_unhandled_error_returns_500_with_cors_header(self, client, headers):
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_node_with_neighbours",
                side_effect=RuntimeError("unexpected topology failure"),
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/nodes/{uuid.uuid4()}",
                headers={
                    **headers,
                    "Origin": "http://127.0.0.1:5173",
                },
            )

        assert response.status_code == 500
        body = response.json()
        assert body["success"] is False
        assert body["errors"]["code"] == "INTERNAL_ERROR"
        assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"


class TestTopologyAnalysisEndpoints:
    def test_topology_neighbors_endpoint_returns_envelope(self, client, headers):
        payload = TopologyDeviceNeighboursResponse(
            device={
                "device_id": "device-1",
                "hostname": "core-1",
                "device_type": "router",
                "status": "active",
                "spatial_ref_id": "campus-a/core-1",
            },
            neighbours=[
                {
                    "device_id": "device-2",
                    "hostname": "dist-2",
                    "device_type": "switch",
                    "status": "active",
                    "spatial_ref_id": "campus-a/dist-2",
                    "edge_type": "connected_to",
                    "edge_metadata": {"link_quality": "good"},
                    "direction": "outbound",
                    "hop_depth": 1,
                },
                {
                    "device_id": "device-3",
                    "hostname": "edge-3",
                    "device_type": "switch",
                    "status": "active",
                    "spatial_ref_id": None,
                    "edge_type": "connected_to",
                    "edge_metadata": {},
                    "direction": "inbound",
                    "hop_depth": 2,
                },
            ],
            depth=2,
            total=2,
        )
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_device_neighbours",
                return_value=payload,
            ) as mock_get_neighbours,
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/device/{uuid.uuid4()}/neighbors?depth=2&limit=25",
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["errors"] is None
        assert body["data"]["depth"] == 2
        assert body["data"]["total"] == 2
        assert body["data"]["neighbours"][0]["edge_metadata"]["link_quality"] == "good"

        call_kwargs = mock_get_neighbours.call_args.kwargs
        assert call_kwargs["depth"] == 2
        assert call_kwargs["limit"] == 25

    def test_topology_neighbors_endpoint_not_found_returns_404(self, client, headers):
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_device_neighbours",
                return_value=None,
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/device/{uuid.uuid4()}/neighbors",
                headers=headers,
            )

        assert response.status_code == 404

    def test_topology_impact_endpoint_returns_envelope(self, client, headers):
        payload = TopologyImpactResponse(
            device={
                "device_id": "device-1",
                "hostname": "core-1",
                "device_type": "router",
                "status": "active",
                "spatial_ref_id": "campus-a/core-1",
            },
            impacts=[
                {
                    "device_id": "device-2",
                    "hostname": "dist-2",
                    "device_type": "switch",
                    "status": "active",
                    "spatial_ref_id": "campus-a/dist-2",
                    "hop_depth": 1,
                },
                {
                    "device_id": "device-3",
                    "hostname": "edge-3",
                    "device_type": "switch",
                    "status": "active",
                    "spatial_ref_id": None,
                    "hop_depth": 2,
                },
            ],
            max_hops=4,
            total=2,
        )
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_impact_analysis",
                return_value=payload,
            ) as mock_get_impact,
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/impact/{uuid.uuid4()}?max_hops=4&limit=12",
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["errors"] is None
        assert body["data"]["max_hops"] == 4
        assert body["data"]["total"] == 2
        assert body["data"]["impacts"][1]["hop_depth"] == 2

        call_kwargs = mock_get_impact.call_args.kwargs
        assert call_kwargs["max_hops"] == 4
        assert call_kwargs["limit"] == 12

    def test_topology_impact_endpoint_not_found_returns_404(self, client, headers):
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.get_impact_analysis",
                return_value=None,
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.get(
                f"/api/v1/topology/impact/{uuid.uuid4()}",
                headers=headers,
            )

        assert response.status_code == 404

    def test_topology_reconcile_endpoint_returns_envelope(self, client, headers):
        network_id = uuid.uuid4()
        reconcile_id = uuid.uuid4()
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.reconcile_network",
                return_value={
                    "reconcile_id": str(reconcile_id),
                    "network_id": str(network_id),
                    "status": "completed",
                    "checked_nodes": 8,
                    "checked_edges": 7,
                    "missing_workspace_nodes": 2,
                    "workspace_backfilled_nodes": 2,
                    "warning": None,
                },
            ) as mock_reconcile,
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.post(
                "/api/v1/topology/reconcile",
                json={"network_id": str(network_id)},
                headers=headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["errors"] is None
        assert body["data"]["reconcile_id"] == str(reconcile_id)
        assert body["data"]["status"] == "completed"
        assert body["data"]["checked_nodes"] == 8
        assert body["data"]["workspace_backfilled_nodes"] == 2

        call_kwargs = mock_reconcile.call_args.kwargs
        assert call_kwargs["network_id"] == network_id
        assert isinstance(call_kwargs["correlation_id"], str)
        assert call_kwargs["actor_id"]

    def test_topology_reconcile_endpoint_not_found_returns_404(self, client, headers):
        with (
            patch(
                "app.modules.network.topology.TopologyQueryService.reconcile_network",
                return_value=None,
            ),
            patch("app.api.v1.topology.get_neo4j_driver") as mock_driver,
        ):
            mock_driver.return_value = AsyncMock()
            response = client.post(
                "/api/v1/topology/reconcile",
                json={"network_id": str(uuid.uuid4())},
                headers=headers,
            )

        assert response.status_code == 404
