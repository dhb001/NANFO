"""Unit tests for WebSocket push consumer routing and fail-open behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.events.consumers.ws_push_consumer import (
    WS_PUSH_HANDLERS,
    handle_ws_alert_event,
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


@pytest.mark.asyncio
async def test_ws_alert_consumer_pushes_generated_event_to_alerts_channel():
    event = _alert_event("alert.generated", payload={"severity": "critical", "message": "degraded"})

    with patch("app.events.consumers.ws_push_consumer.alerts_ws_manager") as mock_alerts_ws_manager:
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


@pytest.mark.asyncio
async def test_ws_alert_consumer_pushes_resolved_event_to_alerts_channel():
    event = _alert_event("alert.resolved", payload={"severity": "critical", "message": "recovered"})

    with patch("app.events.consumers.ws_push_consumer.alerts_ws_manager") as mock_alerts_ws_manager:
        mock_alerts_ws_manager.push_delta = AsyncMock()
        await handle_ws_alert_event(event)

    kwargs = mock_alerts_ws_manager.push_delta.await_args.kwargs
    assert kwargs["event_type"] == "alert.resolved"
    assert kwargs["delta_type"] == "resolve"


@pytest.mark.asyncio
async def test_ws_alert_consumer_falls_back_to_empty_payload_for_malformed_event_payload():
    event = _alert_event("alert.generated", payload="not-an-object")

    with patch("app.events.consumers.ws_push_consumer.alerts_ws_manager") as mock_alerts_ws_manager:
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

    with patch("app.events.consumers.ws_push_consumer.alerts_ws_manager") as mock_alerts_ws_manager:
        mock_alerts_ws_manager.push_delta = AsyncMock(side_effect=RuntimeError("ws down"))
        await handle_ws_alert_event(event)

    mock_alerts_ws_manager.push_delta.assert_awaited_once()


def test_ws_push_handlers_include_alert_lifecycle_events():
    assert "alert.generated" in WS_PUSH_HANDLERS
    assert "alert.resolved" in WS_PUSH_HANDLERS
    assert WS_PUSH_HANDLERS["alert.generated"] is handle_ws_alert_event
    assert WS_PUSH_HANDLERS["alert.resolved"] is handle_ws_alert_event
