"""Integration tests for network and device endpoints via FastAPI TestClient.

Tests: routing, status codes, envelope format, C6 constraint (deferred endpoints absent).
Dependencies overridden with mocks.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.core.security import create_access_token
from app.main import app
from app.modules.network.schemas import (
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


def _make_token_with_workspace(*, permissions: list[str], workspace_id: uuid.UUID) -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="test@example.com",
        roles=["Admin"],
        permissions=permissions,
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
        from fastapi import HTTPException
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
        from fastapi import HTTPException

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
