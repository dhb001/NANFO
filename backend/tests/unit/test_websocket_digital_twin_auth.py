"""Unit tests for DigitalTwinWSManager token expiry behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

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


@pytest.mark.asyncio
async def test_digital_twin_push_sends_unauthorized_and_closes_when_jti_revoked():
    manager = DigitalTwinWSManager()
    revoked_ws = AsyncMock()

    await manager.subscribe(
        "network-1",
        revoked_ws,
        token_jti="revoked-jti",
    )

    with patch("app.websocket.manager.get_redis_client") as mock_get_redis:
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=1)
        mock_get_redis.return_value = fake_redis

        await manager.push_delta(
            network_id="network-1",
            event_type="simulation.completed",
            delta_type="update",
            scene_object={"id": "simulation-state", "state": "completed"},
            correlation_id="corr-3",
            timestamp="2026-08-12T00:00:02+00:00",
        )

    revoked_ws.send_text.assert_awaited_once()
    revoked_payload = revoked_ws.send_text.await_args.args[0]
    assert "WS_UNAUTHORIZED" in revoked_payload
    revoked_ws.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_digital_twin_push_with_denylist_unavailable_is_fail_open():
    manager = DigitalTwinWSManager()
    ws = AsyncMock()

    await manager.subscribe(
        "network-1",
        ws,
        token_jti="token-jti",
    )

    with patch(
        "app.websocket.manager.get_redis_client",
        side_effect=RuntimeError("redis unavailable"),
    ):
        await manager.push_delta(
            network_id="network-1",
            event_type="simulation.started",
            delta_type="update",
            scene_object={"id": "simulation-state", "state": "queued"},
            correlation_id="corr-4",
            timestamp="2026-08-12T00:00:03+00:00",
        )

    ws.send_text.assert_awaited_once()
    ws.close.assert_not_awaited()
