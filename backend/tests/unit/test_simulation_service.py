"""Unit tests for simulation baseline handoff services."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.simulation.service import (
    ScenarioValidationHandoffService,
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
