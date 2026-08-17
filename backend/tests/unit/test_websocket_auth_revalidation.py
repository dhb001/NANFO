"""Unit tests for per-push websocket auth revalidation on non-digital-twin channels."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.websocket.manager import AlertsWSManager, TelemetryWSManager, TopologyWSManager


@pytest.mark.asyncio
async def test_topology_ws_manager_closes_connection_on_expired_token_before_push():
    manager = TopologyWSManager()
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

    with patch("app.websocket.manager.get_redis_client") as mock_get_redis:
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        await manager.push_delta(
            network_id="network-1",
            event_type="network.device.updated",
            delta_type="update",
            node={"device_id": "device-1", "status": "offline"},
            correlation_id="corr-1",
            timestamp="2026-08-16T00:00:00+00:00",
        )

    expired_ws.send_text.assert_awaited_once()
    expired_ws.close.assert_awaited_once_with(code=1008)
    live_ws.send_text.assert_awaited_once()
    live_ws.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_telemetry_ws_manager_closes_connection_on_revoked_token_before_push():
    manager = TelemetryWSManager()
    revoked_ws = AsyncMock()
    live_ws = AsyncMock()

    await manager.subscribe("network-1", revoked_ws, token_jti="revoked-jti")
    await manager.subscribe("network-1", live_ws, token_jti="live-jti")

    with patch("app.websocket.manager.get_redis_client") as mock_get_redis:
        fake_redis = AsyncMock()

        async def exists_side_effect(key: str) -> int:
            return 1 if key == "jti:deny:revoked-jti" else 0

        fake_redis.exists = AsyncMock(side_effect=exists_side_effect)
        mock_get_redis.return_value = fake_redis

        await manager.push_delta(
            network_id="network-1",
            event_type="telemetry.metric.ingested",
            metric={"device_id": "device-1", "metric": "cpu", "value": 81},
            correlation_id="corr-2",
            timestamp="2026-08-16T00:00:01+00:00",
        )

    revoked_ws.send_text.assert_awaited_once()
    revoked_ws.close.assert_awaited_once_with(code=1008)
    live_ws.send_text.assert_awaited_once()
    live_ws.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_alerts_ws_manager_closes_connection_on_expired_token_before_push():
    manager = AlertsWSManager()
    expired_ws = AsyncMock()
    live_ws = AsyncMock()
    now = datetime.now(UTC)

    await manager.subscribe(
        expired_ws,
        token_exp=int((now - timedelta(seconds=1)).timestamp()),
    )
    await manager.subscribe(
        live_ws,
        token_exp=int((now + timedelta(seconds=60)).timestamp()),
    )

    with patch("app.websocket.manager.get_redis_client") as mock_get_redis:
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        await manager.push_delta(
            event_type="alert.generated",
            delta_type="add",
            alert={"event_id": "evt-1", "payload": {"severity": "warning"}},
            correlation_id="corr-3",
            timestamp="2026-08-16T00:00:02+00:00",
        )

    expired_ws.send_text.assert_awaited_once()
    expired_ws.close.assert_awaited_once_with(code=1008)
    live_ws.send_text.assert_awaited_once()
    live_ws.close.assert_not_awaited()
