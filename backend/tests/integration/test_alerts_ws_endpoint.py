"""Integration tests for /ws/alerts WebSocket endpoint contract."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app


def _make_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="alerts@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
    )
    return token


def test_ws_alerts_subscribe_ack():
    token = _make_token()

    with (
        patch("app.websocket.alerts.get_redis_client") as mock_get_redis,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/alerts?token={token}") as websocket:
            websocket.send_text(json.dumps({"action": "subscribe", "channel": "alerts", "filters": {}}))
            ack = websocket.receive_json()

    assert ack["event"] == "subscribed"
    assert ack["channel"] == "alerts"


def test_ws_alerts_unknown_channel_returns_error_and_closes():
    token = _make_token()

    with (
        patch("app.websocket.alerts.get_redis_client") as mock_get_redis,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/alerts?token={token}") as websocket:
            websocket.send_text(json.dumps({"action": "subscribe", "channel": "telemetry", "filters": {}}))
            error = websocket.receive_json()

    assert error["event"] == "error"
    assert error["data"]["code"] == "WS_UNKNOWN_CHANNEL"
