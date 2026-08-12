"""Unit tests for simulation repository persistence behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.simulation.models import Simulation
from app.modules.simulation.repository import SimulationRepository


@pytest.mark.asyncio
async def test_create_adds_and_flushes_simulation_record(mock_db):
    repo = SimulationRepository(mock_db)
    now = datetime.now(UTC)

    simulation = await repo.create(
        simulation_id=uuid.uuid4(),
        parent_simulation_id=None,
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        scenario_id=uuid.uuid4(),
        scenario_name="Campus baseline",
        state="queued",
        status="queued",
        risk_gate="required",
        validation={"pipeline_stage": "handoff_queued"},
        run_output={"latency_ms": 0.0, "loss_pct": 0.0, "throughput_mbps": 0.0},
        model_versions={"physics_engine": "v1"},
        audit_provenance={"policy_reference": "ADR-008"},
        queue_status="queued",
        stream_entry_id="1001-0",
        warning=None,
        requested_by_user_id=str(uuid.uuid4()),
        requested_at=now,
    )

    assert isinstance(simulation, Simulation)
    assert simulation.state == "queued"
    assert simulation.validation["pipeline_stage"] == "handoff_queued"
    mock_db.add.assert_called_once_with(simulation)
    mock_db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_by_id_executes_select_and_returns_row(mock_db):
    expected = MagicMock(spec=Simulation)
    result = MagicMock()
    result.scalar_one_or_none.return_value = expected
    mock_db.execute = AsyncMock(return_value=result)

    repo = SimulationRepository(mock_db)
    simulation = await repo.get_by_id(uuid.uuid4())

    assert simulation is expected
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_queue_outcome_mutates_record_and_flushes(mock_db):
    repo = SimulationRepository(mock_db)
    simulation = Simulation(
        simulation_id=uuid.uuid4(),
        parent_simulation_id=None,
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        scenario_id=uuid.uuid4(),
        scenario_name="Campus baseline",
        state="queued",
        status="queued",
        risk_gate="required",
        validation={},
        run_output={},
        model_versions={},
        audit_provenance={},
        queue_status="queued",
        stream_entry_id="1001-0",
        warning=None,
        requested_by_user_id=str(uuid.uuid4()),
        requested_at=datetime.now(UTC),
    )

    updated = await repo.update_queue_outcome(
        simulation,
        queue_status="deferred",
        stream_entry_id=None,
        warning="event_queue_unavailable",
    )

    assert updated is simulation
    assert simulation.queue_status == "deferred"
    assert simulation.stream_entry_id is None
    assert simulation.warning == "event_queue_unavailable"
    mock_db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_children_returns_rows_for_parent_simulation(mock_db):
    parent_simulation_id = uuid.uuid4()
    child = MagicMock(spec=Simulation)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [child]
    mock_db.execute = AsyncMock(return_value=result)

    repo = SimulationRepository(mock_db)
    children = await repo.list_children(parent_simulation_id=parent_simulation_id)

    assert children == [child]
    mock_db.execute.assert_awaited_once()
