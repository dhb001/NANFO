"""Integration tests for intent event -> digital twin WS fanout flow."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.events.consumers.ws_push_consumer import handle_ws_intent_event


@pytest.mark.asyncio
async def test_intent_execution_started_event_is_fanned_out_to_digital_twin_ws():
    payload = {
        "intent_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "intent_kind": "reroute_path",
        "status": "execution_started",
        "confidence": {
            "score": 0.84,
            "band": "80-94",
            "approval_required": True,
        },
    }
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "intent.execution_started",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "intent",
        "correlation_id": str(uuid.uuid4()),
        "version": "1",
        "payload": payload,
    }

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_intent_event(event)

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

    assert decoded["event"] == "intent.execution_started"
    assert decoded["data"]["delta_type"] == "update"
    assert decoded["data"]["scene_object"]["object_type"] == "intent_state"
    assert decoded["data"]["scene_object"]["status"] == "execution_started"
    assert decoded["data"]["scene_object"]["changed_fields"]["intent_kind"] == "reroute_path"


@pytest.mark.asyncio
async def test_intent_event_missing_network_id_is_ignored_for_ws_delta():
    payload = {
        "intent_id": str(uuid.uuid4()),
        "status": "validated",
    }
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "intent.validated",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "intent",
        "correlation_id": str(uuid.uuid4()),
        "version": "1",
        "payload": payload,
    }

    with patch("app.events.consumers.ws_push_consumer.digital_twin_ws_manager") as mock_digital_twin_ws_manager:
        mock_digital_twin_ws_manager.push_delta = AsyncMock()
        await handle_ws_intent_event(event)

    mock_digital_twin_ws_manager.push_delta.assert_not_awaited()
