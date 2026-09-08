"""Canonical and manually constructed response metadata expose the configured mode."""

import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.core.responses import error_response, success_response
from app.main import app
from app.modules.network.schemas import TopologyGraphResponse
from tests.auth_support import create_session_access_token


@pytest.mark.parametrize("mode", ["demo", "emulation", "production"])
def test_response_modes_include_topology_and_error_handlers(execution_mode, mode, session_auth, mock_db):
    execution_mode(mode)
    for envelope in (
        success_response({}, "request", time.monotonic(), "timestamp"),
        error_response("ERROR", "message", "request", "timestamp"),
    ):
        assert envelope.model_dump()["meta"]["execution_mode"] == mode

    token, _ = create_session_access_token(
        user_id=str(uuid.UUID(int=1)), email="mode@example.com", roles=["Admin"],
        permissions=["read:topology", "write:config"],
    )
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: session_auth.redis
    try:
        with (
            patch("app.api.v1.topology._resolve_network_scope", new=AsyncMock(return_value=(uuid.UUID(int=2), uuid.UUID(int=3)))),
            patch("app.api.v1.topology.get_neo4j_driver"),
            patch("app.api.v1.topology.TopologyQueryService.get_graph", new=AsyncMock(
                return_value=(TopologyGraphResponse(nodes=[], edges=[]), "next-page"),
            )),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            headers = {"Authorization": f"Bearer {token}"}
            response = client.get("/api/v1/topology/graph", params={"network_id": str(uuid.UUID(int=2))}, headers=headers)
            assert response.status_code == 200
            assert response.json()["meta"]["execution_mode"] == mode
            assert response.json()["meta"]["next_cursor"] == "next-page"
            for response in (
                client.get("/api/v1/auth/me"),
                client.post("/api/v1/auth/refresh", json={}),
                client.get("/api/v1/missing"),
            ):
                assert response.status_code in (401, 404, 422)
                assert "meta" in response.json(), (str(response.url), response.json())
                assert response.json()["meta"]["execution_mode"] == mode
            with patch("app.modules.organization.service.OrgService.create_org", side_effect=RuntimeError("failure")):
                response = client.post("/api/v1/organizations", json={"name": "Test", "slug": "test"}, headers=headers)
            assert response.status_code == 500
            assert response.json()["meta"]["execution_mode"] == mode
    finally:
        app.dependency_overrides.clear()
