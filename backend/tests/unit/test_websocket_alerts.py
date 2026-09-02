"""Unit tests for alerts WebSocket manager behavior."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.websocket.manager import AlertsWSManager


@pytest.mark.asyncio
async def test_alerts_ws_manager_pushes_delta_to_all_subscribers():
    manager = AlertsWSManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()

    await manager.subscribe(ws1)
    await manager.subscribe(ws2)

    await manager.push_delta(
        event_type="alert.generated",
        delta_type="add",
        alert={"event_id": "evt-1", "payload": {"severity": "critical"}},
        correlation_id="corr-1",
        timestamp="2026-08-10T00:00:00+00:00",
    )

    ws1.send_text.assert_awaited_once()
    ws2.send_text.assert_awaited_once()

    payload = json.loads(ws1.send_text.await_args.args[0])
    assert payload["event"] == "alert.generated"
    assert payload["data"]["delta_type"] == "add"
    assert payload["data"]["alert"]["event_id"] == "evt-1"


@pytest.mark.asyncio
async def test_alerts_ws_manager_unsubscribes_dead_connections():
    manager = AlertsWSManager()
    alive = AsyncMock()
    dead = AsyncMock()
    dead.send_text.side_effect = RuntimeError("disconnected")

    await manager.subscribe(alive)
    await manager.subscribe(dead)

    await manager.push_delta(
        event_type="alert.resolved",
        delta_type="resolve",
        alert={"event_id": "evt-2", "payload": {}},
        correlation_id="corr-2",
        timestamp="2026-08-10T00:00:01+00:00",
    )

    alive.send_text.assert_awaited_once()
    dead.send_text.assert_awaited_once()

    await manager.push_delta(
        event_type="alert.resolved",
        delta_type="resolve",
        alert={"event_id": "evt-3", "payload": {}},
        correlation_id="corr-3",
        timestamp="2026-08-10T00:00:02+00:00",
    )

    assert dead.send_text.await_count == 1
    assert alive.send_text.await_count == 2


@pytest.mark.asyncio
async def test_alerts_ws_manager_filters_delivery_by_workspace_scope_when_provided():
    manager = AlertsWSManager()
    ws_workspace_a = AsyncMock()
    ws_workspace_b = AsyncMock()

    await manager.subscribe(ws_workspace_a, allowed_workspace_ids={"workspace-a"})
    await manager.subscribe(ws_workspace_b, allowed_workspace_ids={"workspace-b"})

    await manager.push_delta(
        event_type="alert.generated",
        delta_type="add",
        alert={"event_id": "evt-4", "payload": {"severity": "critical"}},
        correlation_id="corr-4",
        timestamp="2026-08-10T00:00:03+00:00",
        workspace_id="workspace-a",
    )

    ws_workspace_a.send_text.assert_awaited_once()
    ws_workspace_b.send_text.assert_not_awaited()
