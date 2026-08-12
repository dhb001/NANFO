"""Unit tests for WebSocket push consumer routing and fail-open behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.events.consumers.ws_push_consumer import (
    WS_PUSH_HANDLERS,
    handle_ws_alert_event,
    handle_ws_digital_twin_event,
    handle_ws_push_event,
)


def _alert_event(event_type: str = "alert.generated", payload: object | None = None) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "correlation_id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "telemetry",
        "payload": payload if payload is not None else {"severity": "critical"},
    }


def _topology_event(event_type: str, payload: dict) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "correlation_id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "network",
        "payload": payload,
    }


@pytest.mark.asyncio
async def test_ws_alert_consumer_pushes_generated_event_to_alerts_channel():
    event = _alert_event("alert.generated", payload={"severity": "critical", "message": "degraded"})

    with (
        patch("app.events.consumers.ws_push_consumer.alerts_ws_manager") as mock_alerts_ws_manager,
        patch("app.events.consumers.ws_push_consumer.get_redis_client") as mock_get_redis,
    ):
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(return_value=1)
        mock_get_redis.return_value = fake_redis
        mock_alerts_ws_manager.push_delta = AsyncMock()
        await handle_ws_alert_event(event)

    mock_alerts_ws_manager.push_delta.assert_awaited_once()
    kwargs = mock_alerts_ws_manager.push_delta.await_args.kwargs
    assert kwargs["event_type"] == "alert.generated"
    assert kwargs["delta_type"] == "add"
    assert kwargs["correlation_id"] == event["correlation_id"]
    assert kwargs["alert"]["event_id"] == event["event_id"]
    assert kwargs["alert"]["source"] == "telemetry"
    assert kwargs["alert"]["payload"] == event["payload"]
    fake_redis.incr.assert_awaited_once_with("alerts:ws:fanout:generated:success")


@pytest.mark.asyncio
async def test_ws_alert_consumer_pushes_resolved_event_to_alerts_channel():
    event = _alert_event("alert.resolved", payload={"severity": "critical", "message": "recovered"})

    with (
        patch("app.events.consumers.ws_push_consumer.alerts_ws_manager") as mock_alerts_ws_manager,
        patch("app.events.consumers.ws_push_consumer.get_redis_client") as mock_get_redis,
    ):
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(return_value=1)
        mock_get_redis.return_value = fake_redis
        mock_alerts_ws_manager.push_delta = AsyncMock()
        await handle_ws_alert_event(event)

    kwargs = mock_alerts_ws_manager.push_delta.await_args.kwargs
    assert kwargs["event_type"] == "alert.resolved"
    assert kwargs["delta_type"] == "resolve"
    fake_redis.incr.assert_awaited_once_with("alerts:ws:fanout:resolved:success")


@pytest.mark.asyncio
async def test_ws_alert_consumer_falls_back_to_empty_payload_for_malformed_event_payload():
    event = _alert_event("alert.generated", payload="not-an-object")

    with (
        patch("app.events.consumers.ws_push_consumer.alerts_ws_manager") as mock_alerts_ws_manager,
        patch("app.events.consumers.ws_push_consumer.get_redis_client") as mock_get_redis,
    ):
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(return_value=1)
        mock_get_redis.return_value = fake_redis
        mock_alerts_ws_manager.push_delta = AsyncMock()
        await handle_ws_alert_event(event)

    kwargs = mock_alerts_ws_manager.push_delta.await_args.kwargs
    assert kwargs["alert"]["payload"] == {}


@pytest.mark.asyncio
async def test_ws_alert_consumer_unmapped_event_is_noop():
    event = _alert_event("alert.acknowledged")

    with patch("app.events.consumers.ws_push_consumer.alerts_ws_manager") as mock_alerts_ws_manager:
        mock_alerts_ws_manager.push_delta = AsyncMock()
        await handle_ws_alert_event(event)

    mock_alerts_ws_manager.push_delta.assert_not_awaited()


@pytest.mark.asyncio
async def test_ws_alert_consumer_push_failure_is_fail_open():
    event = _alert_event("alert.generated")

    with (
        patch("app.events.consumers.ws_push_consumer.alerts_ws_manager") as mock_alerts_ws_manager,
        patch("app.events.consumers.ws_push_consumer.get_redis_client") as mock_get_redis,
    ):
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(return_value=1)
        mock_get_redis.return_value = fake_redis
        mock_alerts_ws_manager.push_delta = AsyncMock(side_effect=RuntimeError("ws down"))
        await handle_ws_alert_event(event)

    mock_alerts_ws_manager.push_delta.assert_awaited_once()
    fake_redis.incr.assert_awaited_once_with("alerts:ws:fanout:generated:failure")


@pytest.mark.asyncio
async def test_ws_alert_consumer_counter_client_unavailable_is_fail_open():
    event = _alert_event("alert.generated")

    with (
        patch("app.events.consumers.ws_push_consumer.alerts_ws_manager") as mock_alerts_ws_manager,
        patch(
            "app.events.consumers.ws_push_consumer.get_redis_client",
            side_effect=RuntimeError("redis unavailable"),
        ),
    ):
        mock_alerts_ws_manager.push_delta = AsyncMock()
        await handle_ws_alert_event(event)

    mock_alerts_ws_manager.push_delta.assert_awaited_once()


@pytest.mark.asyncio
async def test_ws_alert_consumer_counter_increment_failure_is_fail_open():
    event = _alert_event("alert.generated")

    with (
        patch("app.events.consumers.ws_push_consumer.alerts_ws_manager") as mock_alerts_ws_manager,
        patch("app.events.consumers.ws_push_consumer.get_redis_client") as mock_get_redis,
    ):
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(side_effect=RuntimeError("redis write failed"))
        mock_get_redis.return_value = fake_redis
        mock_alerts_ws_manager.push_delta = AsyncMock()
        await handle_ws_alert_event(event)

    mock_alerts_ws_manager.push_delta.assert_awaited_once()
    fake_redis.incr.assert_awaited_once_with("alerts:ws:fanout:generated:success")


@pytest.mark.asyncio
async def test_ws_topology_update_delta_includes_changed_fields_for_spatial_ref_id():
    payload = {
        "device_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "changed_fields": {"spatial_ref_id": "campus-a/device-77"},
    }
    event = _topology_event("network.device.updated", payload)

    with patch("app.events.consumers.ws_push_consumer.topology_ws_manager") as mock_topology_ws_manager:
        mock_topology_ws_manager.push_delta = AsyncMock()
        await handle_ws_push_event(event)

    mock_topology_ws_manager.push_delta.assert_awaited_once()
    kwargs = mock_topology_ws_manager.push_delta.await_args.kwargs
    assert kwargs["event_type"] == "network.device.updated"
    assert kwargs["delta_type"] == "update"
    assert kwargs["network_id"] == payload["network_id"]
    assert kwargs["node"] == {
        "device_id": payload["device_id"],
        "spatial_ref_id": "campus-a/device-77",
    }


def test_ws_push_handlers_include_alert_lifecycle_events():
    assert "alert.generated" in WS_PUSH_HANDLERS
    assert "alert.resolved" in WS_PUSH_HANDLERS
    assert WS_PUSH_HANDLERS["alert.generated"] is handle_ws_alert_event
    assert WS_PUSH_HANDLERS["alert.resolved"] is handle_ws_alert_event


def _simulation_event(
    event_type: str = "simulation.started",
    payload: object | None = None,
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "correlation_id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "simulation",
        "payload": payload
        if payload is not None
        else {
            "network_id": str(uuid.uuid4()),
            "simulation_id": str(uuid.uuid4()),
            "scenario_id": str(uuid.uuid4()),
            "scene_object_id": "simulation-state",
            "state": "queued",
            "status": "queued",
            "risk_gate": "required",
        },
    }


@pytest.mark.asyncio
async def test_ws_digital_twin_consumer_pushes_simulation_started_delta():
    event = _simulation_event("simulation.started")

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_digital_twin_event(event)

    mock_digital_twin_ws_manager.push_delta.assert_awaited_once()
    kwargs = mock_digital_twin_ws_manager.push_delta.await_args.kwargs
    assert kwargs["network_id"] == event["payload"]["network_id"]
    assert kwargs["event_type"] == "simulation.started"
    assert kwargs["delta_type"] == "update"
    assert kwargs["scene_object"]["object_type"] == "simulation_state"
    assert kwargs["scene_object"]["simulation_id"] == event["payload"]["simulation_id"]


@pytest.mark.asyncio
async def test_ws_digital_twin_consumer_pushes_simulation_completed_delta():
    event = _simulation_event("simulation.completed")

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_digital_twin_event(event)

    kwargs = mock_digital_twin_ws_manager.push_delta.await_args.kwargs
    assert kwargs["event_type"] == "simulation.completed"
    assert kwargs["delta_type"] == "update"


@pytest.mark.asyncio
async def test_ws_digital_twin_consumer_unmapped_event_is_noop():
    event = _simulation_event("simulation.branch_created")

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_digital_twin_event(event)

    mock_digital_twin_ws_manager.push_delta.assert_not_awaited()


@pytest.mark.asyncio
async def test_ws_digital_twin_consumer_missing_network_id_is_noop():
    event = _simulation_event(payload={"simulation_id": str(uuid.uuid4())})

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_digital_twin_event(event)

    mock_digital_twin_ws_manager.push_delta.assert_not_awaited()


@pytest.mark.asyncio
async def test_ws_digital_twin_consumer_pushes_simulation_paused_delta():
    event = _simulation_event(
        "simulation.paused",
        payload={
            "network_id": str(uuid.uuid4()),
            "simulation_id": str(uuid.uuid4()),
            "scenario_id": str(uuid.uuid4()),
            "scene_object_id": "simulation-state",
            "state": "paused",
            "status": "paused",
            "risk_gate": "required",
        },
    )

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_digital_twin_event(event)

    kwargs = mock_digital_twin_ws_manager.push_delta.await_args.kwargs
    assert kwargs["event_type"] == "simulation.paused"
    assert kwargs["delta_type"] == "update"
    assert kwargs["scene_object"]["state"] == "paused"
    assert kwargs["scene_object"]["status"] == "paused"


@pytest.mark.asyncio
async def test_ws_digital_twin_consumer_pushes_simulation_cancelled_delta():
    event = _simulation_event(
        "simulation.cancelled",
        payload={
            "network_id": str(uuid.uuid4()),
            "simulation_id": str(uuid.uuid4()),
            "scenario_id": str(uuid.uuid4()),
            "scene_object_id": "simulation-state",
            "state": "cancelled",
            "status": "cancelled",
            "risk_gate": "blocked",
        },
    )

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_digital_twin_event(event)

    kwargs = mock_digital_twin_ws_manager.push_delta.await_args.kwargs
    assert kwargs["event_type"] == "simulation.cancelled"
    assert kwargs["delta_type"] == "update"
    assert kwargs["scene_object"]["state"] == "cancelled"
    assert kwargs["scene_object"]["status"] == "cancelled"


def test_ws_push_handlers_include_simulation_events_for_digital_twin():
    assert "simulation.started" in WS_PUSH_HANDLERS
    assert "simulation.completed" in WS_PUSH_HANDLERS
    assert "simulation.paused" in WS_PUSH_HANDLERS
    assert "simulation.cancelled" in WS_PUSH_HANDLERS
    assert WS_PUSH_HANDLERS["simulation.started"] is handle_ws_digital_twin_event
    assert WS_PUSH_HANDLERS["simulation.completed"] is handle_ws_digital_twin_event
    assert WS_PUSH_HANDLERS["simulation.paused"] is handle_ws_digital_twin_event
    assert WS_PUSH_HANDLERS["simulation.cancelled"] is handle_ws_digital_twin_event
