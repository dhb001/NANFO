"""Integration tests for simulation event -> digital twin WS fanout flow."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.events.consumers.ws_push_consumer import handle_ws_digital_twin_event
from app.modules.simulation.service import queue_scenario_validation_handoff


@pytest.mark.asyncio
async def test_simulation_handoff_event_is_fanned_out_to_digital_twin_ws(integration_fake_redis):
    await integration_fake_redis.delete("stream:simulation")

    with patch("app.modules.simulation.service.publish_event", new_callable=AsyncMock) as mock_publish:
        mock_publish.return_value = "1200-0"
        handoff_result = await queue_scenario_validation_handoff(
            redis=integration_fake_redis,
            network_id=str(uuid.uuid4()),
            scenario_name="WS fanout scenario",
            validation_checks=["simulation_before_deployment"],
            correlation_id=str(uuid.uuid4()),
            requested_by_user_id=str(uuid.uuid4()),
        )

    handoff_payload = handoff_result["handoff"]
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "simulation.started",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "simulation",
        "correlation_id": str(uuid.uuid4()),
        "version": "1",
        "payload": handoff_payload,
    }

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_digital_twin_event(event)

    mock_digital_twin_ws_manager.push_delta.assert_awaited_once()
    kwargs = mock_digital_twin_ws_manager.push_delta.await_args.kwargs
    assert kwargs["event_type"] == "simulation.started"
    assert kwargs["delta_type"] == "update"
    assert kwargs["network_id"] == handoff_payload["network_id"]
    assert kwargs["scene_object"]["state"] == "queued"
    assert kwargs["scene_object"]["risk_gate"] == "required"
    assert kwargs["scene_object"]["scenario_id"] == handoff_payload["scenario_id"]


@pytest.mark.asyncio
async def test_simulation_completed_event_payload_is_translated_to_scene_delta():
    payload = {
        "network_id": str(uuid.uuid4()),
        "simulation_id": str(uuid.uuid4()),
        "scenario_id": str(uuid.uuid4()),
        "scene_object_id": "simulation-state",
        "state": "completed",
        "status": "completed",
        "risk_gate": "passed",
    }
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "simulation.completed",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "simulation",
        "correlation_id": str(uuid.uuid4()),
        "version": "1",
        "payload": payload,
    }

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_digital_twin_event(event)

    kwargs = mock_digital_twin_ws_manager.push_delta.await_args.kwargs
    wire_payload = {
        "event": kwargs["event_type"],
        "correlation_id": kwargs["correlation_id"],
        "timestamp": kwargs["timestamp"],
        "data": {
            "delta_type": kwargs["delta_type"],
            "scene_object": kwargs["scene_object"],
        },
    }
    encoded = json.dumps(wire_payload)
    decoded = json.loads(encoded)

    assert decoded["event"] == "simulation.completed"
    assert decoded["data"]["delta_type"] == "update"
    assert decoded["data"]["scene_object"]["state"] == "completed"
    assert decoded["data"]["scene_object"]["status"] == "completed"
    assert decoded["data"]["scene_object"]["risk_gate"] == "passed"


@pytest.mark.asyncio
async def test_simulation_paused_event_payload_is_translated_to_scene_delta():
    payload = {
        "network_id": str(uuid.uuid4()),
        "simulation_id": str(uuid.uuid4()),
        "scenario_id": str(uuid.uuid4()),
        "scene_object_id": "simulation-state",
        "state": "paused",
        "status": "paused",
        "risk_gate": "required",
    }
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "simulation.paused",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "simulation",
        "correlation_id": str(uuid.uuid4()),
        "version": "1",
        "payload": payload,
    }

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_digital_twin_event(event)

    kwargs = mock_digital_twin_ws_manager.push_delta.await_args.kwargs
    wire_payload = {
        "event": kwargs["event_type"],
        "correlation_id": kwargs["correlation_id"],
        "timestamp": kwargs["timestamp"],
        "data": {
            "delta_type": kwargs["delta_type"],
            "scene_object": kwargs["scene_object"],
        },
    }
    encoded = json.dumps(wire_payload)
    decoded = json.loads(encoded)

    assert decoded["event"] == "simulation.paused"
    assert decoded["data"]["delta_type"] == "update"
    assert decoded["data"]["scene_object"]["state"] == "paused"
    assert decoded["data"]["scene_object"]["status"] == "paused"


@pytest.mark.asyncio
async def test_simulation_cancelled_event_payload_is_translated_to_scene_delta():
    payload = {
        "network_id": str(uuid.uuid4()),
        "simulation_id": str(uuid.uuid4()),
        "scenario_id": str(uuid.uuid4()),
        "scene_object_id": "simulation-state",
        "state": "cancelled",
        "status": "cancelled",
        "risk_gate": "blocked",
    }
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "simulation.cancelled",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "simulation",
        "correlation_id": str(uuid.uuid4()),
        "version": "1",
        "payload": payload,
    }

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_digital_twin_event(event)

    kwargs = mock_digital_twin_ws_manager.push_delta.await_args.kwargs
    wire_payload = {
        "event": kwargs["event_type"],
        "correlation_id": kwargs["correlation_id"],
        "timestamp": kwargs["timestamp"],
        "data": {
            "delta_type": kwargs["delta_type"],
            "scene_object": kwargs["scene_object"],
        },
    }
    encoded = json.dumps(wire_payload)
    decoded = json.loads(encoded)

    assert decoded["event"] == "simulation.cancelled"
    assert decoded["data"]["delta_type"] == "update"
    assert decoded["data"]["scene_object"]["state"] == "cancelled"
    assert decoded["data"]["scene_object"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_simulation_event_with_spatial_metadata_is_translated_to_scene_delta():
    payload = {
        "network_id": str(uuid.uuid4()),
        "simulation_id": str(uuid.uuid4()),
        "scenario_id": str(uuid.uuid4()),
        "scene_object_id": "simulation-state",
        "state": "completed",
        "status": "completed",
        "risk_gate": "passed",
        "spatial_ref_id": "campus-a/building-1/floor-2/room-204/rack-3/device-router-01",
        "spatial_metadata": {
            "campus_id": "campus-a",
            "building_id": "building-1",
            "floor_id": "floor-2",
        },
    }
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "simulation.completed",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "simulation",
        "correlation_id": str(uuid.uuid4()),
        "version": "1",
        "payload": payload,
    }

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_digital_twin_event(event)

    kwargs = mock_digital_twin_ws_manager.push_delta.await_args.kwargs
    wire_payload = {
        "event": kwargs["event_type"],
        "correlation_id": kwargs["correlation_id"],
        "timestamp": kwargs["timestamp"],
        "data": {
            "delta_type": kwargs["delta_type"],
            "scene_object": kwargs["scene_object"],
        },
    }
    encoded = json.dumps(wire_payload)
    decoded = json.loads(encoded)

    scene_object = decoded["data"]["scene_object"]
    assert scene_object["spatial_ref_id"] == payload["spatial_ref_id"]
    assert scene_object["spatial_metadata"]["building_id"] == "building-1"
    assert scene_object["changed_fields"]["spatial_ref_id"] == payload["spatial_ref_id"]
    assert scene_object["changed_fields"]["spatial_metadata"]["campus_id"] == "campus-a"
