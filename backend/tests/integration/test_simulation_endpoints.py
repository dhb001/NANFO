"""Integration tests for simulation handoff endpoint contract."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import fakeredis
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.core.security import create_access_token
from app.main import app


def _make_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="simulation@example.com",
        roles=["Admin"],
        permissions=["read:topology", "write:config"],
    )
    return token


@pytest.fixture
def client() -> TestClient:
    fake_r = fakeredis.FakeAsyncRedis(decode_responses=True)
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    async def _redis():
        yield fake_r

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_start_simulation_returns_envelope_and_handoff_payload(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    network_id = str(uuid.uuid4())
    handoff = {
        "simulation_id": str(uuid.uuid4()),
        "scenario_id": str(uuid.uuid4()),
        "network_id": network_id,
        "scene_object_id": "simulation-state",
        "state": "queued",
        "status": "queued",
        "risk_gate": "required",
        "scenario_name": "Campus baseline validation",
        "validation": {
            "pipeline_stage": "handoff_queued",
            "required_checks": ["simulation_before_deployment", "blast_radius_assessment"],
            "policy_reference": "ADR-008",
            "status": "pending",
            "queued_at": datetime.now(UTC).isoformat(),
            "requested_by_user_id": str(uuid.uuid4()),
        },
        "requested_at": datetime.now(UTC).isoformat(),
        "correlation_id": str(uuid.uuid4()),
    }

    with patch(
        "app.modules.simulation.service.SimulationStartService.start_simulation",
        new=AsyncMock(
            return_value={
                "handoff": handoff,
                "queue_status": "queued",
                "stream_entry_id": "1001-0",
                "warning": None,
            }
        ),
    ):
        response = client.post(
            "/api/v1/simulations/start",
            json={
                "network_id": network_id,
                "scenario_name": "Campus baseline validation",
                "validation_checks": ["simulation_before_deployment", "blast_radius_assessment"],
            },
            headers=headers,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["network_id"] == network_id
    assert body["data"]["state"] == "queued"
    assert body["data"]["risk_gate"] == "required"
    assert body["data"]["queue_status"] == "queued"
    assert body["data"]["stream_entry_id"] == "1001-0"
    assert body["data"]["validation"]["pipeline_stage"] == "handoff_queued"
    assert body["data"]["validation"]["policy_reference"] == "ADR-008"


def test_start_simulation_publish_failure_returns_deferred_warning(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    handoff = {
        "simulation_id": str(uuid.uuid4()),
        "scenario_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "scene_object_id": "simulation-state",
        "state": "queued",
        "status": "queued",
        "risk_gate": "required",
        "scenario_name": "High impact branch",
        "validation": {
            "pipeline_stage": "handoff_queued",
            "required_checks": ["simulation_before_deployment"],
            "policy_reference": "ADR-008",
            "status": "pending",
            "queued_at": datetime.now(UTC).isoformat(),
            "requested_by_user_id": str(uuid.uuid4()),
        },
        "requested_at": datetime.now(UTC).isoformat(),
        "correlation_id": str(uuid.uuid4()),
    }

    with patch(
        "app.modules.simulation.service.SimulationStartService.start_simulation",
        new=AsyncMock(
            return_value={
                "handoff": handoff,
                "queue_status": "deferred",
                "stream_entry_id": None,
                "warning": "event_queue_unavailable",
            }
        ),
    ):
        response = client.post(
            "/api/v1/simulations/start",
            json={
                "network_id": str(uuid.uuid4()),
                "scenario_name": "High impact branch",
                "validation_checks": ["simulation_before_deployment"],
            },
            headers=headers,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["data"]["queue_status"] == "deferred"
    assert body["data"]["stream_entry_id"] is None
    assert body["data"]["warning"] == "event_queue_unavailable"


def test_start_simulation_requires_auth(client):
    response = client.post(
        "/api/v1/simulations/start",
        json={
            "network_id": str(uuid.uuid4()),
            "scenario_name": "No auth",
            "validation_checks": ["simulation_before_deployment"],
        },
    )
    assert response.status_code in (401, 403)


def test_start_simulation_missing_network_returns_404(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.simulation.service.SimulationStartService.start_simulation",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Network not found.")),
    ):
        response = client.post(
            "/api/v1/simulations/start",
            json={
                "network_id": str(uuid.uuid4()),
                "scenario_name": "Missing network",
                "validation_checks": ["simulation_before_deployment"],
            },
            headers=headers,
        )

    assert response.status_code == 404


def test_pause_simulation_returns_envelope(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    simulation_id = str(uuid.uuid4())
    payload = {
        "simulation_id": simulation_id,
        "network_id": str(uuid.uuid4()),
        "scene_object_id": "simulation-state",
        "state": "paused",
        "status": "paused",
        "risk_gate": "required",
        "scenario_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
    }

    with patch(
        "app.modules.simulation.service.SimulationStartService.pause_simulation",
        new=AsyncMock(return_value=payload),
    ):
        response = client.post(
            "/api/v1/simulations/pause",
            json={"simulation_id": simulation_id},
            headers=headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["simulation_id"] == simulation_id
    assert body["data"]["state"] == "paused"


def test_start_simulation_resume_accepts_simulation_id(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    simulation_id = str(uuid.uuid4())
    handoff = {
        "simulation_id": simulation_id,
        "resumed_from_simulation_id": simulation_id,
        "scenario_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "scene_object_id": "simulation-state",
        "state": "queued",
        "status": "queued",
        "risk_gate": "required",
        "scenario_name": "Resume scenario",
        "validation": {
            "pipeline_stage": "handoff_queued",
            "required_checks": ["simulation_before_deployment"],
            "policy_reference": "ADR-008",
            "status": "pending",
            "queued_at": datetime.now(UTC).isoformat(),
            "requested_by_user_id": str(uuid.uuid4()),
        },
        "requested_at": datetime.now(UTC).isoformat(),
        "correlation_id": str(uuid.uuid4()),
    }

    with patch(
        "app.modules.simulation.service.SimulationStartService.start_simulation",
        new=AsyncMock(
            return_value={
                "handoff": handoff,
                "queue_status": "queued",
                "stream_entry_id": "2001-0",
                "warning": None,
            }
        ),
    ):
        response = client.post(
            "/api/v1/simulations/start",
            json={
                "network_id": str(uuid.uuid4()),
                "simulation_id": simulation_id,
                "scenario_name": "Resume scenario",
                "validation_checks": ["simulation_before_deployment"],
            },
            headers=headers,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["data"]["simulation_id"] == simulation_id
    assert body["data"]["resumed_from_simulation_id"] == simulation_id


def test_branch_simulation_returns_envelope_and_lineage_payload(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    payload = {
        "simulation_id": str(uuid.uuid4()),
        "parent_simulation_id": str(uuid.uuid4()),
        "scenario_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "scene_object_id": "simulation-state",
        "state": "draft",
        "status": "draft",
        "risk_gate": "required",
        "scenario_name": "Campus branch draft",
        "validation": {
            "pipeline_stage": "branch_draft",
            "required_checks": ["simulation_before_deployment"],
            "policy_reference": "ADR-008",
            "status": "pending",
            "queued_at": datetime.now(UTC).isoformat(),
            "requested_by_user_id": str(uuid.uuid4()),
        },
        "requested_at": datetime.now(UTC).isoformat(),
        "correlation_id": str(uuid.uuid4()),
    }

    with patch(
        "app.modules.simulation.service.SimulationStartService.branch_simulation",
        new=AsyncMock(return_value=payload),
    ):
        response = client.post(
            "/api/v1/simulations/branch",
            json={
                "parent_simulation_id": payload["parent_simulation_id"],
                "scenario_name": "Campus branch draft",
            },
            headers=headers,
        )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["simulation_id"] == payload["simulation_id"]
    assert body["data"]["parent_simulation_id"] == payload["parent_simulation_id"]
    assert body["data"]["state"] == "draft"
    assert body["data"]["validation"]["pipeline_stage"] == "branch_draft"


def test_branch_simulation_requires_auth(client):
    response = client.post(
        "/api/v1/simulations/branch",
        json={
            "parent_simulation_id": str(uuid.uuid4()),
            "scenario_name": "No auth branch",
        },
    )
    assert response.status_code in (401, 403)


def test_branch_simulation_missing_parent_returns_404(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.simulation.service.SimulationStartService.branch_simulation",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Simulation not found.")),
    ):
        response = client.post(
            "/api/v1/simulations/branch",
            json={
                "parent_simulation_id": str(uuid.uuid4()),
                "scenario_name": "Missing parent",
            },
            headers=headers,
        )

    assert response.status_code == 404


def test_get_simulation_detail_returns_envelope(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    simulation_id = str(uuid.uuid4())
    payload = {
        "simulation_id": simulation_id,
        "parent_simulation_id": str(uuid.uuid4()),
        "scenario_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "scene_object_id": "simulation-state",
        "state": "queued",
        "status": "queued",
        "risk_gate": "required",
        "scenario_name": "Campus baseline",
        "validation": {
            "pipeline_stage": "handoff_queued",
            "required_checks": ["simulation_before_deployment"],
        },
        "run_output": {"latency_ms": 0.0, "loss_pct": 0.0, "throughput_mbps": 0.0},
        "model_versions": {"physics_engine": "v1"},
        "audit_provenance": {"policy_reference": "ADR-008"},
        "queue_status": "queued",
        "stream_entry_id": "1001-0",
        "warning": None,
        "requested_by_user_id": str(uuid.uuid4()),
        "requested_at": datetime.now(UTC).isoformat(),
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }

    with patch(
        "app.modules.simulation.service.SimulationStartService.get_simulation_detail",
        new=AsyncMock(return_value=payload),
    ):
        response = client.get(
            f"/api/v1/simulations/{simulation_id}",
            headers=headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["simulation_id"] == simulation_id
    assert body["data"]["queue_status"] == "queued"
    assert body["data"]["validation"]["pipeline_stage"] == "handoff_queued"


def test_get_simulation_detail_requires_auth(client):
    response = client.get(f"/api/v1/simulations/{uuid.uuid4()}")
    assert response.status_code in (401, 403)


def test_get_simulation_detail_missing_returns_404(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.simulation.service.SimulationStartService.get_simulation_detail",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Simulation not found.")),
    ):
        response = client.get(
            f"/api/v1/simulations/{uuid.uuid4()}",
            headers=headers,
        )

    assert response.status_code == 404


def test_compare_simulations_returns_envelope_and_deltas(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    simulation_id = str(uuid.uuid4())
    baseline_id = str(uuid.uuid4())
    payload = {
        "simulation_id": simulation_id,
        "baseline_simulation_id": baseline_id,
        "scenario_id": str(uuid.uuid4()),
        "baseline_scenario_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "simulation_metrics": {
            "latency_ms": 11.0,
            "loss_pct": 0.2,
            "throughput_mbps": 90.0,
        },
        "baseline_metrics": {
            "latency_ms": 10.0,
            "loss_pct": 0.1,
            "throughput_mbps": 100.0,
        },
        "deltas": {
            "latency_ms": 1.0,
            "loss_pct": 0.1,
            "throughput_mbps": -10.0,
        },
    }

    with patch(
        "app.modules.simulation.service.SimulationStartService.compare_simulations",
        new=AsyncMock(return_value=payload),
    ):
        response = client.get(
            f"/api/v1/simulations/{simulation_id}/compare/{baseline_id}",
            headers=headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] is None
    assert body["data"]["simulation_id"] == simulation_id
    assert body["data"]["baseline_simulation_id"] == baseline_id
    assert body["data"]["deltas"]["latency_ms"] == 1.0
    assert body["data"]["deltas"]["throughput_mbps"] == -10.0


def test_compare_simulations_requires_auth(client):
    response = client.get(f"/api/v1/simulations/{uuid.uuid4()}/compare/{uuid.uuid4()}")
    assert response.status_code in (401, 403)


def test_compare_simulations_network_mismatch_returns_409(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}

    with patch(
        "app.modules.simulation.service.SimulationStartService.compare_simulations",
        new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Simulations belong to different networks.")),
    ):
        response = client.get(
            f"/api/v1/simulations/{uuid.uuid4()}/compare/{uuid.uuid4()}",
            headers=headers,
        )

    assert response.status_code == 409
