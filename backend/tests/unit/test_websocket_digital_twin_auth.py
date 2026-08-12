"""Unit tests for DigitalTwinWSManager token expiry behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.websocket.manager import DigitalTwinWSManager


@pytest.mark.asyncio
async def test_digital_twin_push_sends_unauthorized_and_closes_when_token_expired():
    manager = DigitalTwinWSManager()
    expired_ws = AsyncMock()
    live_ws = AsyncMock()
    now = datetime.now(UTC)

    await manager.subscribe(
        "network-1",
        expired_ws,
        token_exp=int((now - timedelta(seconds=5)).timestamp()),
    )
    await manager.subscribe(
        "network-1",
        live_ws,
        token_exp=int((now + timedelta(seconds=60)).timestamp()),
    )

    await manager.push_delta(
        network_id="network-1",
        event_type="simulation.started",
        delta_type="update",
        scene_object={"id": "simulation-state", "state": "queued"},
        correlation_id="corr-1",
        timestamp="2026-08-12T00:00:00+00:00",
    )

    expired_ws.send_text.assert_awaited_once()
    expired_payload = expired_ws.send_text.await_args.args[0]
    assert "WS_UNAUTHORIZED" in expired_payload
    expired_ws.close.assert_awaited_once()

    live_ws.send_text.assert_awaited_once()
    live_ws.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_digital_twin_push_without_expiry_metadata_does_not_force_close():
    manager = DigitalTwinWSManager()
    ws = AsyncMock()

    await manager.subscribe("network-1", ws)

    await manager.push_delta(
        network_id="network-1",
        event_type="simulation.completed",
        delta_type="update",
        scene_object={"id": "simulation-state", "state": "completed"},
        correlation_id="corr-2",
        timestamp="2026-08-12T00:00:01+00:00",
    )

    ws.send_text.assert_awaited_once()
    ws.close.assert_not_awaited()
