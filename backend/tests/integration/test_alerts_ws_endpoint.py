"""Integration tests for /ws/alerts WebSocket endpoint contract."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app


def _build_session_context() -> AsyncMock:
    db = AsyncMock()
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None
    return session_cm


def _make_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="alerts@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
    )
    return token


def _make_scoped_token(*, workspace_id: uuid.UUID, org_id: uuid.UUID) -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="alerts-scoped@example.com",
        roles=["Admin"],
        permissions=["read:telemetry"],
        workspace_id=str(workspace_id),
        org_id=str(org_id),
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


def test_ws_alerts_scoped_claim_rejected_when_workspace_scope_resolution_fails():
    token = _make_scoped_token(workspace_id=uuid.uuid4(), org_id=uuid.uuid4())
    session_cm = _build_session_context()

    with (
        patch("app.websocket.alerts.get_redis_client") as mock_get_redis,
        patch("app.websocket.alerts.AsyncSessionLocal", return_value=session_cm),
        patch("app.websocket.alerts._resolve_alert_subscription_workspaces", return_value=None),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/alerts?token={token}") as websocket:
            websocket.send_text(json.dumps({"action": "subscribe", "channel": "alerts", "filters": {}}))
            error = websocket.receive_json()

    assert error["event"] == "error"
    assert error["data"]["code"] == "WS_INVALID_FILTER"


def test_ws_alerts_scoped_claim_allows_subscription_when_scope_resolves():
    token = _make_scoped_token(workspace_id=uuid.uuid4(), org_id=uuid.uuid4())
    session_cm = _build_session_context()

    async def _resolve_scope(*, db, claims):
        return {str(claims["workspace_id"])}

    with (
        patch("app.websocket.alerts.get_redis_client") as mock_get_redis,
        patch("app.websocket.alerts.AsyncSessionLocal", return_value=session_cm),
        patch("app.websocket.alerts._resolve_alert_subscription_workspaces", side_effect=_resolve_scope),
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
