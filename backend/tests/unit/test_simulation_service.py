"""Unit tests for simulation baseline handoff services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
            simulation_id=None,
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
            simulation_id=None,
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
                simulation_id=None,
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
                simulation_id=None,
                validation_checks=["simulation_before_deployment"],
                correlation_id=str(uuid.uuid4()),
                requested_by_user_id=str(uuid.uuid4()),
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_start_simulation_resume_uses_existing_simulation_record(mock_db, fake_redis):
    simulation_id = uuid.uuid4()
    existing = AsyncMock()
    existing.simulation_id = simulation_id
    existing.scenario_id = uuid.uuid4()
    existing.network_id = uuid.uuid4()
    existing.workspace_id = uuid.uuid4()
    existing.scenario_name = "Campus baseline"
    existing.state = "paused"
    existing.validation = {"required_checks": ["simulation_before_deployment"]}

    with (
        patch("app.modules.simulation.service.SimulationRepository.get_by_id", new_callable=AsyncMock) as mock_get,
        patch("app.modules.simulation.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_ws,
        patch("app.modules.simulation.service.SimulationRepository.update_state", new_callable=AsyncMock) as mock_update_state,
        patch("app.modules.simulation.service.SimulationRepository.update_queue_outcome", new_callable=AsyncMock) as mock_update_queue,
        patch("app.modules.simulation.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get.return_value = existing
        mock_ws.return_value = AsyncMock()
        mock_publish.return_value = "1300-0"

        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        result = await svc.start_simulation(
            network_id=uuid.uuid4(),
            scenario_name="Ignored on resume",
            simulation_id=simulation_id,
            validation_checks=["simulation_before_deployment"],
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["handoff"]["simulation_id"] == str(simulation_id)
    assert result["handoff"]["resumed_from_simulation_id"] == str(simulation_id)
    assert result["queue_status"] == "queued"
    mock_update_state.assert_awaited_once()
    mock_update_queue.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pause_simulation_updates_state_and_publishes_event(mock_db, fake_redis):
    simulation_id = uuid.uuid4()
    existing = AsyncMock()
    existing.simulation_id = simulation_id
    existing.scenario_id = uuid.uuid4()
    existing.network_id = uuid.uuid4()
    existing.workspace_id = uuid.uuid4()
    existing.state = "queued"
    existing.risk_gate = "required"
    existing.validation = {"pipeline_stage": "handoff_queued"}

    with (
        patch("app.modules.simulation.service.SimulationRepository.get_by_id", new_callable=AsyncMock) as mock_get,
        patch("app.modules.simulation.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_ws,
        patch("app.modules.simulation.service.SimulationRepository.update_state", new_callable=AsyncMock) as mock_update,
        patch("app.modules.simulation.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get.return_value = existing
        mock_ws.return_value = AsyncMock()

        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        result = await svc.pause_simulation(
            simulation_id=simulation_id,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["simulation_id"] == str(simulation_id)
    assert result["state"] == "paused"
    mock_update.assert_awaited_once()
    mock_publish.assert_awaited_once()
    assert mock_publish.await_args.kwargs["event_type"] == "simulation.paused"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pause_simulation_event_publish_failure_is_fail_open(mock_db, fake_redis):
    simulation_id = uuid.uuid4()
    existing = AsyncMock()
    existing.simulation_id = simulation_id
    existing.scenario_id = uuid.uuid4()
    existing.network_id = uuid.uuid4()
    existing.workspace_id = uuid.uuid4()
    existing.state = "running"
    existing.risk_gate = "required"
    existing.validation = {}

    with (
        patch("app.modules.simulation.service.SimulationRepository.get_by_id", new_callable=AsyncMock) as mock_get,
        patch("app.modules.simulation.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_ws,
        patch("app.modules.simulation.service.SimulationRepository.update_state", new_callable=AsyncMock),
        patch("app.modules.simulation.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get.return_value = existing
        mock_ws.return_value = AsyncMock()
        mock_publish.side_effect = RuntimeError("stream unavailable")

        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        result = await svc.pause_simulation(
            simulation_id=simulation_id,
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["state"] == "paused"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_branch_simulation_creates_draft_lineage_record(mock_db, fake_redis):
    parent_simulation_id = uuid.uuid4()
    parent = AsyncMock()
    parent.simulation_id = parent_simulation_id
    parent.scenario_id = uuid.uuid4()
    parent.network_id = uuid.uuid4()
    parent.workspace_id = uuid.uuid4()
    parent.scenario_name = "Campus baseline"
    parent.state = "completed"
    parent.validation = {
        "required_checks": ["simulation_before_deployment", "blast_radius_assessment"],
        "policy_reference": "ADR-008",
    }
    parent.run_output = {"latency_ms": 12.0, "loss_pct": 0.2, "throughput_mbps": 110.0}
    parent.model_versions = {"physics_engine": "v1"}
    parent.audit_provenance = {"policy_reference": "ADR-008"}

    branch = AsyncMock()
    branch.simulation_id = uuid.uuid4()
    branch.scenario_id = uuid.uuid4()
    branch.network_id = parent.network_id
    branch.state = "draft"
    branch.status = "draft"
    branch.risk_gate = "required"
    branch.scenario_name = "Campus branch draft"

    with (
        patch("app.modules.simulation.service.SimulationRepository.get_by_id", new_callable=AsyncMock) as mock_get,
        patch("app.modules.simulation.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_ws,
        patch("app.modules.simulation.service.SimulationRepository.create", new_callable=AsyncMock) as mock_create,
        patch("app.modules.simulation.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get.return_value = parent
        mock_ws.return_value = AsyncMock()
        mock_create.return_value = branch
        mock_publish.return_value = "1400-0"

        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        result = await svc.branch_simulation(
            parent_simulation_id=parent_simulation_id,
            scenario_name="Campus branch draft",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["simulation_id"] == str(branch.simulation_id)
    assert result["parent_simulation_id"] == str(parent.simulation_id)
    assert result["state"] == "draft"
    assert result["status"] == "draft"
    assert result["validation"]["pipeline_stage"] == "branch_draft"
    assert result["validation"]["required_checks"] == ["simulation_before_deployment", "blast_radius_assessment"]
    mock_ws.assert_awaited_once_with(parent.workspace_id)
    create_kwargs = mock_create.await_args.kwargs
    assert create_kwargs["parent_simulation_id"] == parent.simulation_id
    assert create_kwargs["network_id"] == parent.network_id
    assert create_kwargs["workspace_id"] == parent.workspace_id
    assert create_kwargs["scenario_name"] == "Campus branch draft"
    assert create_kwargs["state"] == "draft"
    assert create_kwargs["status"] == "draft"
    assert create_kwargs["queue_status"] == "draft"
    assert result["validation"]["pipeline_stage"] == "branch_draft"
    mock_publish.assert_awaited_once()
    assert mock_publish.await_args.kwargs["event_type"] == "simulation.branch_created"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_branch_simulation_raises_404_when_parent_missing(mock_db, fake_redis):
    with patch("app.modules.simulation.service.SimulationRepository.get_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        with pytest.raises(HTTPException) as exc_info:
            await svc.branch_simulation(
                parent_simulation_id=uuid.uuid4(),
                scenario_name="Branch candidate",
                correlation_id=str(uuid.uuid4()),
                requested_by_user_id=str(uuid.uuid4()),
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_simulation_detail_returns_persisted_record(mock_db, fake_redis):
    simulation_id = uuid.uuid4()
    now = datetime.now(UTC)
    existing = AsyncMock()
    existing.simulation_id = simulation_id
    existing.parent_simulation_id = uuid.uuid4()
    existing.scenario_id = uuid.uuid4()
    existing.network_id = uuid.uuid4()
    existing.workspace_id = uuid.uuid4()
    existing.state = "queued"
    existing.status = "queued"
    existing.risk_gate = "required"
    existing.scenario_name = "Campus baseline"
    existing.validation = {"pipeline_stage": "handoff_queued"}
    existing.run_output = {"latency_ms": 1.0}
    existing.model_versions = {"physics_engine": "v1"}
    existing.audit_provenance = {"policy_reference": "ADR-008"}
    existing.queue_status = "queued"
    existing.stream_entry_id = "1001-0"
    existing.warning = None
    existing.requested_by_user_id = str(uuid.uuid4())
    existing.requested_at = now
    existing.created_at = now
    existing.updated_at = now

    with (
        patch("app.modules.simulation.service.SimulationRepository.get_by_id", new_callable=AsyncMock) as mock_get,
        patch("app.modules.simulation.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_ws,
    ):
        mock_get.return_value = existing
        mock_ws.return_value = AsyncMock()

        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        result = await svc.get_simulation_detail(
            simulation_id=simulation_id,
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["simulation_id"] == str(simulation_id)
    assert result["parent_simulation_id"] == str(existing.parent_simulation_id)
    assert result["scenario_name"] == "Campus baseline"
    assert result["queue_status"] == "queued"
    assert result["validation"]["pipeline_stage"] == "handoff_queued"
    mock_ws.assert_awaited_once_with(existing.workspace_id)


@pytest.mark.asyncio
async def test_get_simulation_detail_raises_404_when_missing(mock_db, fake_redis):
    with patch("app.modules.simulation.service.SimulationRepository.get_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        with pytest.raises(HTTPException) as exc_info:
            await svc.get_simulation_detail(
                simulation_id=uuid.uuid4(),
                requested_by_user_id=str(uuid.uuid4()),
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_compare_simulations_returns_deterministic_metric_deltas(mock_db, fake_redis):
    simulation = AsyncMock()
    simulation.simulation_id = uuid.uuid4()
    simulation.scenario_id = uuid.uuid4()
    simulation.network_id = uuid.uuid4()
    simulation.workspace_id = uuid.uuid4()
    simulation.run_output = {
        "latency_ms": 12.5,
        "loss_pct": 0.4,
        "throughput_mbps": 98.0,
    }

    baseline = AsyncMock()
    baseline.simulation_id = uuid.uuid4()
    baseline.scenario_id = uuid.uuid4()
    baseline.network_id = simulation.network_id
    baseline.workspace_id = simulation.workspace_id
    baseline.run_output = {
        "latency_ms": 10.0,
        "loss_pct": 0.1,
        "throughput_mbps": 100.0,
    }

    with (
        patch("app.modules.simulation.service.SimulationRepository.get_by_id", new_callable=AsyncMock) as mock_get,
        patch("app.modules.simulation.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_ws,
    ):
        mock_get.side_effect = [simulation, baseline]
        mock_ws.return_value = AsyncMock()

        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        result = await svc.compare_simulations(
            simulation_id=simulation.simulation_id,
            baseline_simulation_id=baseline.simulation_id,
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["simulation_id"] == str(simulation.simulation_id)
    assert result["baseline_simulation_id"] == str(baseline.simulation_id)
    assert result["simulation_metrics"]["latency_ms"] == 12.5
    assert result["baseline_metrics"]["latency_ms"] == 10.0
    assert result["deltas"]["latency_ms"] == 2.5
    assert result["deltas"]["loss_pct"] == 0.30000000000000004
    assert result["deltas"]["throughput_mbps"] == -2.0
    assert mock_ws.await_count == 2


@pytest.mark.asyncio
async def test_compare_simulations_raises_409_for_network_mismatch(mock_db, fake_redis):
    simulation = AsyncMock()
    simulation.simulation_id = uuid.uuid4()
    simulation.scenario_id = uuid.uuid4()
    simulation.network_id = uuid.uuid4()
    simulation.workspace_id = uuid.uuid4()
    simulation.run_output = {}

    baseline = AsyncMock()
    baseline.simulation_id = uuid.uuid4()
    baseline.scenario_id = uuid.uuid4()
    baseline.network_id = uuid.uuid4()
    baseline.workspace_id = uuid.uuid4()
    baseline.run_output = {}

    with (
        patch("app.modules.simulation.service.SimulationRepository.get_by_id", new_callable=AsyncMock) as mock_get,
        patch("app.modules.simulation.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_ws,
    ):
        mock_get.side_effect = [simulation, baseline]
        mock_ws.return_value = AsyncMock()

        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        with pytest.raises(HTTPException) as exc_info:
            await svc.compare_simulations(
                simulation_id=simulation.simulation_id,
                baseline_simulation_id=baseline.simulation_id,
                requested_by_user_id=str(uuid.uuid4()),
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_compare_simulations_raises_404_when_baseline_missing(mock_db, fake_redis):
    simulation = AsyncMock()
    simulation.simulation_id = uuid.uuid4()

    with patch("app.modules.simulation.service.SimulationRepository.get_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [simulation, None]
        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        with pytest.raises(HTTPException) as exc_info:
            await svc.compare_simulations(
                simulation_id=simulation.simulation_id,
                baseline_simulation_id=uuid.uuid4(),
                requested_by_user_id=str(uuid.uuid4()),
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_branch_simulation_event_publish_failure_is_fail_open(mock_db, fake_redis):
    parent_simulation_id = uuid.uuid4()
    parent = AsyncMock()
    parent.simulation_id = parent_simulation_id
    parent.scenario_id = uuid.uuid4()
    parent.network_id = uuid.uuid4()
    parent.workspace_id = uuid.uuid4()
    parent.scenario_name = "Campus baseline"
    parent.validation = {"required_checks": ["simulation_before_deployment"]}
    parent.run_output = {}
    parent.model_versions = {}
    parent.audit_provenance = {}

    branch = AsyncMock()
    branch.simulation_id = uuid.uuid4()
    branch.scenario_id = uuid.uuid4()
    branch.network_id = parent.network_id
    branch.state = "draft"
    branch.status = "draft"
    branch.risk_gate = "required"
    branch.scenario_name = "Draft"

    with (
        patch("app.modules.simulation.service.SimulationRepository.get_by_id", new_callable=AsyncMock) as mock_get,
        patch("app.modules.simulation.service.OrgWorkspaceService.get_active_workspace", new_callable=AsyncMock) as mock_ws,
        patch("app.modules.simulation.service.SimulationRepository.create", new_callable=AsyncMock) as mock_create,
        patch("app.modules.simulation.service.publish_event", new_callable=AsyncMock) as mock_publish,
    ):
        mock_get.return_value = parent
        mock_ws.return_value = AsyncMock()
        mock_create.return_value = branch
        mock_publish.side_effect = RuntimeError("stream unavailable")

        svc = SimulationStartService(db=mock_db, redis=fake_redis)
        result = await svc.branch_simulation(
            parent_simulation_id=parent_simulation_id,
            scenario_name="Draft",
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    assert result["simulation_id"] == str(branch.simulation_id)
    assert result["state"] == "draft"
    mock_db.commit.assert_awaited_once()
