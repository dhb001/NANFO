"""Unit tests for digital twin WebSocket manager behavior."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.websocket.manager import DigitalTwinWSManager


@pytest.mark.asyncio
async def test_digital_twin_ws_manager_pushes_delta_to_all_subscribers():
    manager = DigitalTwinWSManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()

    await manager.subscribe("network-1", ws1)
    await manager.subscribe("network-1", ws2)

    await manager.push_delta(
        network_id="network-1",
        event_type="simulation.started",
        delta_type="update",
        scene_object={"id": "simulation-state", "state": "queued"},
        correlation_id="corr-1",
        timestamp="2026-08-12T00:00:00+00:00",
    )

    ws1.send_text.assert_awaited_once()
    ws2.send_text.assert_awaited_once()

    payload = json.loads(ws1.send_text.await_args.args[0])
    assert payload["event"] == "simulation.started"
    assert payload["data"]["delta_type"] == "update"
    assert payload["data"]["scene_object"]["id"] == "simulation-state"


@pytest.mark.asyncio
async def test_digital_twin_ws_manager_unsubscribes_dead_connections():
    manager = DigitalTwinWSManager()
    alive = AsyncMock()
    dead = AsyncMock()
    dead.send_text.side_effect = RuntimeError("disconnected")

    await manager.subscribe("network-1", alive)
    await manager.subscribe("network-1", dead)

    await manager.push_delta(
        network_id="network-1",
        event_type="simulation.completed",
        delta_type="update",
        scene_object={"id": "simulation-state", "state": "completed"},
        correlation_id="corr-2",
        timestamp="2026-08-12T00:00:01+00:00",
    )

    alive.send_text.assert_awaited_once()
    dead.send_text.assert_awaited_once()

    await manager.push_delta(
        network_id="network-1",
        event_type="simulation.completed",
        delta_type="update",
        scene_object={"id": "simulation-state", "state": "completed"},
        correlation_id="corr-3",
        timestamp="2026-08-12T00:00:02+00:00",
    )

    assert dead.send_text.await_count == 1
    assert alive.send_text.await_count == 2


@pytest.mark.asyncio
async def test_digital_twin_ws_manager_filters_by_workspace_scope_when_present():
    manager = DigitalTwinWSManager()
    ws_workspace_a = AsyncMock()
    ws_workspace_b = AsyncMock()

    await manager.subscribe("network-1", ws_workspace_a, workspace_id="workspace-a")
    await manager.subscribe("network-1", ws_workspace_b, workspace_id="workspace-b")

    await manager.push_delta(
        network_id="network-1",
        event_type="simulation.completed",
        delta_type="update",
        scene_object={"id": "simulation-state", "state": "completed"},
        correlation_id="corr-workspace",
        timestamp="2026-08-12T00:00:03+00:00",
        workspace_id="workspace-a",
    )

    ws_workspace_a.send_text.assert_awaited_once()
    ws_workspace_b.send_text.assert_not_awaited()
