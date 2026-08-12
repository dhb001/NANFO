"""Unit tests for simulation baseline handoff services."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.simulation.service import (
    ScenarioValidationHandoffService,
    SimulationStartService,
    queue_scenario_validation_handoff,
)


def test_build_handoff_payload_derives_deterministic_scenario_id_and_defaults():
    network_id = str(uuid.uuid4())
    scenario_name = "Campus A Baseline"

    payload = ScenarioValidationHandoffService().build_handoff_payload(
        network_id=network_id,
        scenario_name=scenario_name,
        validation_checks=[],
        correlation_id="not-a-uuid",
        requested_by_user_id="operator-1",
    )

    expected_scenario_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{network_id}:{scenario_name}"))

    assert payload["scenario_id"] == expected_scenario_id
    assert payload["network_id"] == network_id
    assert payload["scene_object_id"] == "simulation-state"
    assert payload["state"] == "queued"
    assert payload["status"] == "queued"
    assert payload["risk_gate"] == "required"
    assert payload["validation"]["required_checks"] == ["simulation_before_deployment"]
    assert payload["validation"]["policy_reference"] == "ADR-008"
    assert payload["validation"]["requested_by_user_id"] == "operator-1"
    assert isinstance(uuid.UUID(payload["simulation_id"]), uuid.UUID)
    assert isinstance(uuid.UUID(payload["correlation_id"]), uuid.UUID)


@pytest.mark.asyncio
async def test_queue_scenario_validation_handoff_publishes_simulation_started_event():
    fake_redis = AsyncMock()

    with patch("app.modules.simulation.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "901-0"

        result = await queue_scenario_validation_handoff(
            redis=fake_redis,
            network_id=str(uuid.uuid4()),
            scenario_name="RF Expansion",
            validation_checks=["simulation_before_deployment", "blast_radius_assessment"],
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["queue_status"] == "queued"
    assert result["stream_entry_id"] == "901-0"
    assert result["warning"] is None
    mock_publish.assert_awaited_once()
    kwargs = mock_publish.await_args.kwargs
    assert kwargs["redis"] is fake_redis
    assert kwargs["event_type"] == "simulation.started"
    assert kwargs["source"] == "simulation"
    assert kwargs["payload"]["simulation_id"] == result["handoff"]["simulation_id"]
    assert kwargs["correlation_id"] == result["handoff"]["correlation_id"]


@pytest.mark.asyncio
async def test_queue_scenario_validation_handoff_publish_failure_is_fail_open():
    with patch(
        "app.modules.simulation.service.publish_event",
        new=AsyncMock(side_effect=RuntimeError("redis unavailable")),
    ):
        result = await queue_scenario_validation_handoff(
            redis=AsyncMock(),
            network_id=str(uuid.uuid4()),
            scenario_name="Risk Drill",
            validation_checks=["simulation_before_deployment"],
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["queue_status"] == "deferred"
    assert result["stream_entry_id"] is None
    assert result["warning"] == "event_queue_unavailable"
    assert result["handoff"]["state"] == "queued"


@pytest.mark.asyncio
async def test_start_simulation_persists_handoff_with_workspace_validation(mock_db, fake_redis):
    network_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    network = AsyncMock()
    network.network_id = network_id
    network.workspace_id = workspace_id

    handoff = {
        "simulation_id": str(uuid.uuid4()),
        "scenario_id": str(uuid.uuid4()),
        "network_id": str(network_id),
        "scene_object_id": "simulation-state",
        "state": "queued",
        "status": "queued",
        "risk_gate": "required",
        "scenario_name": "Campus baseline",
        "validation": {
            "pipeline_stage": "handoff_queued",
            "required_checks": ["simulation_before_deployment"],
            "policy_reference": "ADR-008",
            "status": "pending",
            "queued_at": "2026-08-12T00:00:00+00:00",
            "requested_by_user_id": str(uuid.uuid4()),
        },
        "requested_at": "2026-08-12T00:00:00+00:00",
        "correlation_id": str(uuid.uuid4()),
    }

    with (
        patch("app.modules.simulation.service.NetworkRepository.get_by_id", new_callable=AsyncMock) as mock_get_network,
        patch("app.modules.simulation.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_get_workspace,
        patch("app.modules.simulation.service.queue_scenario_validation_handoff", new_callable=AsyncMock) as mock_queue,
        patch("app.modules.simulation.service.SimulationRepository.create", new_callable=AsyncMock) as mock_create,
    ):
        mock_get_network.return_value = network
        mock_get_workspace.return_value = AsyncMock()
        mock_queue.return_value = {
            "handoff": handoff,
            "queue_status": "queued",
            "stream_entry_id": "1001-0",
            "warning": None,
        }

        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        result = await svc.start_simulation(
            network_id=network_id,
            scenario_name="Campus baseline",
            validation_checks=["simulation_before_deployment"],
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["queue_status"] == "queued"
    mock_get_network.assert_awaited_once_with(network_id)
    mock_get_workspace.assert_awaited_once_with(workspace_id)
    mock_queue.assert_awaited_once()
    create_kwargs = mock_create.await_args.kwargs
    assert create_kwargs["network_id"] == network_id
    assert create_kwargs["workspace_id"] == workspace_id
    assert create_kwargs["scenario_name"] == "Campus baseline"
    assert create_kwargs["queue_status"] == "queued"
    assert create_kwargs["stream_entry_id"] == "1001-0"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_simulation_persists_deferred_queue_outcome_fail_open(mock_db, fake_redis):
    network_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    network = AsyncMock()
    network.network_id = network_id
    network.workspace_id = workspace_id

    handoff = {
        "simulation_id": str(uuid.uuid4()),
        "scenario_id": str(uuid.uuid4()),
        "network_id": str(network_id),
        "scene_object_id": "simulation-state",
        "state": "queued",
        "status": "queued",
        "risk_gate": "required",
        "scenario_name": "Campus baseline",
        "validation": {
            "pipeline_stage": "handoff_queued",
            "required_checks": ["simulation_before_deployment"],
            "policy_reference": "ADR-008",
            "status": "pending",
            "queued_at": "2026-08-12T00:00:00+00:00",
            "requested_by_user_id": str(uuid.uuid4()),
        },
        "requested_at": "2026-08-12T00:00:00+00:00",
        "correlation_id": str(uuid.uuid4()),
    }

    with (
        patch("app.modules.simulation.service.NetworkRepository.get_by_id", new_callable=AsyncMock) as mock_get_network,
        patch("app.modules.simulation.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_get_workspace,
        patch("app.modules.simulation.service.queue_scenario_validation_handoff", new_callable=AsyncMock) as mock_queue,
        patch("app.modules.simulation.service.SimulationRepository.create", new_callable=AsyncMock) as mock_create,
    ):
        mock_get_network.return_value = network
        mock_get_workspace.return_value = AsyncMock()
        mock_queue.return_value = {
            "handoff": handoff,
            "queue_status": "deferred",
            "stream_entry_id": None,
            "warning": "event_queue_unavailable",
        }

        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        result = await svc.start_simulation(
            network_id=network_id,
            scenario_name="Campus baseline",
            validation_checks=["simulation_before_deployment"],
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["queue_status"] == "deferred"
    create_kwargs = mock_create.await_args.kwargs
    assert create_kwargs["queue_status"] == "deferred"
    assert create_kwargs["stream_entry_id"] is None
    assert create_kwargs["warning"] == "event_queue_unavailable"


@pytest.mark.asyncio
async def test_start_simulation_raises_404_when_network_missing(mock_db, fake_redis):
    with patch("app.modules.simulation.service.NetworkRepository.get_by_id", new_callable=AsyncMock) as mock_get_network:
        mock_get_network.return_value = None
        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        with pytest.raises(HTTPException) as exc_info:
            await svc.start_simulation(
                network_id=uuid.uuid4(),
                scenario_name="Campus baseline",
                validation_checks=["simulation_before_deployment"],
                correlation_id=str(uuid.uuid4()),
                requested_by_user_id=str(uuid.uuid4()),
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_start_simulation_raises_workspace_not_found_via_c5_boundary(mock_db, fake_redis):
    network_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    network = AsyncMock()
    network.network_id = network_id
    network.workspace_id = workspace_id

    with (
        patch("app.modules.simulation.service.NetworkRepository.get_by_id", new_callable=AsyncMock) as mock_get_network,
        patch("app.modules.simulation.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_get_workspace,
    ):
        mock_get_network.return_value = network
        mock_get_workspace.side_effect = HTTPException(status_code=404, detail="Workspace not found or has been deleted.")

        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        with pytest.raises(HTTPException) as exc_info:
            await svc.start_simulation(
                network_id=network_id,
                scenario_name="Campus baseline",
                validation_checks=["simulation_before_deployment"],
                correlation_id=str(uuid.uuid4()),
                requested_by_user_id=str(uuid.uuid4()),
            )

    assert exc_info.value.status_code == 404
