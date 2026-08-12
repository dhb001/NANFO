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
from app.modules.network.schemas import TopologyGraphResponse


def _make_token():
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="test@example.com",
        roles=["Admin"],
        permissions=["write:config", "read:topology"],
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


class TestC6DeferredEndpointsAbsent:
    """C6: deferred topology endpoints must NOT be routable."""

    def test_neighbors_endpoint_does_not_exist(self, client, headers):
        network_id = uuid.uuid4()
        response = client.get("/api/v1/topology/neighbors", params={"network_id": str(network_id)}, headers=headers)
        assert response.status_code == 404

    def test_impact_endpoint_does_not_exist(self, client, headers):
        network_id = uuid.uuid4()
        response = client.get("/api/v1/topology/impact", params={"network_id": str(network_id)}, headers=headers)
        assert response.status_code == 404

    def test_reconcile_endpoint_does_not_exist(self, client, headers):
        response = client.post("/api/v1/topology/reconcile", headers=headers)
        assert response.status_code == 404

    def test_neighbors_path_pattern_still_not_routable(self, client, headers):
        response = client.get(f"/api/v1/topology/device/{uuid.uuid4()}/neighbors", headers=headers)
        assert response.status_code == 404

    def test_impact_path_pattern_still_not_routable(self, client, headers):
        response = client.get(f"/api/v1/topology/impact/{uuid.uuid4()}", headers=headers)
        assert response.status_code == 404

    def test_reconcile_subpath_pattern_still_not_routable(self, client, headers):
        response = client.post("/api/v1/topology/reconcile/full", headers=headers)
        assert response.status_code == 404

    def test_reconcile_get_method_still_not_routable(self, client, headers):
        response = client.get("/api/v1/topology/reconcile", headers=headers)
        assert response.status_code == 404

    def test_impact_path_post_method_still_not_routable(self, client, headers):
        response = client.post(f"/api/v1/topology/impact/{uuid.uuid4()}", headers=headers)
        assert response.status_code == 404

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
            },
            "neighbours": [
                {
                    "device_id": "device-2",
                    "hostname": "edge-2",
                    "device_type": "switch",
                    "status": "active",
                    "edge_type": "connected_to",
                    "direction": "inbound",
                },
                {
                    "device_id": "device-3",
                    "hostname": "edge-3",
                    "device_type": "switch",
                    "status": "active",
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
        assert body["data"]["neighbours"][0]["edge_type"] == "connected_to"
        assert body["data"]["neighbours"][0]["direction"] == "inbound"

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
