"""Real consumer/service/repository transitions never synthesize evaluation or files."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from app.events.consumers.report_consumer import handle_report_lifecycle_event
from app.events.consumers.simulation_consumer import handle_simulation_started_event
from app.modules.report.repository import ReportRepository
from app.modules.simulation.repository import SimulationRepository


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["demo", "emulation", "production"])
async def test_consumers_fail_closed_without_real_evaluator_or_renderer(mode, monkeypatch, mock_db, fake_redis):
    monkeypatch.setenv("EXECUTION_MODE", mode)
    item, workspace, network, actor = [UUID(int=n) for n in range(1, 5)]
    simulation = SimpleNamespace(
        simulation_id=item, workspace_id=workspace, network_id=network, scenario_id=item, state="queued", status="queued",
        queue_status="queued", warning=None, validation={}, run_output={}, risk_gate="required",
    )
    report = SimpleNamespace(
        report_id=item, workspace_id=workspace, network_id=network, status="requested", report_type="summary", output_format="pdf",
        requested_by_user_id=str(actor), requested_at=datetime.now(UTC), artifact_refs=[], error_context={},
    )
    monkeypatch.setattr(SimulationRepository, "get_by_id", AsyncMock(return_value=simulation))
    monkeypatch.setattr(ReportRepository, "get_by_id", AsyncMock(return_value=report))
    mock_db.__aenter__.return_value = mock_db
    with (
        patch("app.events.consumers.simulation_consumer.AsyncSessionLocal", return_value=mock_db),
        patch("app.events.consumers.simulation_consumer.get_redis_client", return_value=fake_redis),
        patch("app.events.consumers.report_consumer.AsyncSessionLocal", return_value=mock_db),
    ):
        await handle_simulation_started_event({
            "event_type": "simulation.started", "correlation_id": str(item), "payload": {"simulation_id": str(item)},
        })
        await handle_report_lifecycle_event({
            "event_type": "report.requested", "correlation_id": str(item), "payload": {"report_id": str(item)},
        })
    assert simulation.state == simulation.status == "cancelled"
    assert simulation.risk_gate == "blocked"
    assert all(value is None for value in simulation.run_output.values())
    assert simulation.validation["failure_reason"] == "evaluator_unavailable"
    assert report.status == "requested"
    assert report.artifact_refs == []
    assert report.error_context == {}
    assert "simulation.completed" not in str(await fake_redis.xrange("stream:simulation"))
    assert mock_db.commit.await_count == 1
