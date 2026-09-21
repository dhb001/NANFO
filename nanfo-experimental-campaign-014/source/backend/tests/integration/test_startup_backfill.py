"""Integration tests for startup backfill behavior in app lifespan.

Ensures the topology workspace backfill path runs on startup and does not
block service availability when it fails.
"""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def test_startup_runs_topology_workspace_backfill_once():
    with patch(
        "app.main._run_topology_workspace_backfill",
        new=AsyncMock(return_value=3),
    ) as backfill, TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")

    assert response.status_code == 200
    backfill.assert_awaited_once_with(correlation_id="startup-topology-workspace-backfill")


def test_startup_continues_when_topology_workspace_backfill_fails():
    with patch(
        "app.main._run_topology_workspace_backfill",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ) as backfill, TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")

    assert response.status_code == 200
    backfill.assert_awaited_once_with(correlation_id="startup-topology-workspace-backfill")
