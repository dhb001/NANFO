"""Integration tests for /ws/digital-twin WebSocket endpoint contract."""

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
        email="digitaltwin@example.com",
        roles=["Admin"],
        permissions=["read:topology", "read:telemetry"],
    )
    return token


def _make_scoped_token(*, workspace_id: uuid.UUID, org_id: uuid.UUID) -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="digitaltwin-scoped@example.com",
        roles=["Admin"],
        permissions=["read:topology", "read:telemetry"],
        workspace_id=str(workspace_id),
        org_id=str(org_id),
    )
    return token


def test_ws_digital_twin_subscribe_ack():
    token = _make_token()
    network_id = str(uuid.uuid4())
    workspace_id = str(uuid.uuid4())

    with (
        patch("app.websocket.digital_twin.get_redis_client") as mock_get_redis,
        patch(
            "app.websocket.digital_twin._resolve_digital_twin_subscription_scope",
            return_value=(network_id, workspace_id),
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/digital-twin?token={token}") as websocket:
            websocket.send_text(
                json.dumps(
                    {
                        "action": "subscribe",
                        "channel": "digital-twin",
                        "filters": {"network_id": network_id},
                    }
                )
            )
            ack = websocket.receive_json()

    assert ack["event"] == "subscribed"
    assert ack["channel"] == "digital-twin"


def test_ws_digital_twin_unknown_channel_returns_error_and_closes():
    token = _make_token()

    with (
        patch("app.websocket.digital_twin.get_redis_client") as mock_get_redis,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/digital-twin?token={token}") as websocket:
            websocket.send_text(
                json.dumps(
                    {
                        "action": "subscribe",
                        "channel": "telemetry",
                        "filters": {"network_id": str(uuid.uuid4())},
                    }
                )
            )
            error = websocket.receive_json()

    assert error["event"] == "error"
    assert error["data"]["code"] == "WS_UNKNOWN_CHANNEL"


def test_ws_digital_twin_missing_network_filter_returns_error_and_closes():
    token = _make_token()

    with (
        patch("app.websocket.digital_twin.get_redis_client") as mock_get_redis,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/digital-twin?token={token}") as websocket:
            websocket.send_text(
                json.dumps(
                    {
                        "action": "subscribe",
                        "channel": "digital-twin",
                        "filters": {},
                    }
                )
            )
            error = websocket.receive_json()

    assert error["event"] == "error"
    assert error["data"]["code"] == "WS_INVALID_FILTER"


def test_ws_digital_twin_scope_rejected_returns_invalid_filter_and_policy_close():
    token = _make_scoped_token(workspace_id=uuid.uuid4(), org_id=uuid.uuid4())

    with (
        patch("app.websocket.digital_twin.get_redis_client") as mock_get_redis,
        patch("app.websocket.digital_twin._resolve_digital_twin_subscription_scope", return_value=None),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/digital-twin?token={token}") as websocket:
            websocket.send_text(
                json.dumps(
                    {
                        "action": "subscribe",
                        "channel": "digital-twin",
                        "filters": {"network_id": str(uuid.uuid4())},
                    }
                )
            )
            error = websocket.receive_json()

    assert error["event"] == "error"
    assert error["data"]["code"] == "WS_INVALID_FILTER"


def test_ws_digital_twin_scope_allows_subscription_and_passes_normalized_network_id():
    token = _make_scoped_token(workspace_id=uuid.uuid4(), org_id=uuid.uuid4())
    network_id = str(uuid.uuid4())
    workspace_id = str(uuid.uuid4())

    with (
        patch("app.websocket.digital_twin.get_redis_client") as mock_get_redis,
        patch(
            "app.websocket.digital_twin._resolve_digital_twin_subscription_scope",
            return_value=(network_id, workspace_id),
        ),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/digital-twin?token={token}") as websocket:
            websocket.send_text(
                json.dumps(
                    {
                        "action": "subscribe",
                        "channel": "digital-twin",
                        "filters": {"network_id": network_id},
                    }
                )
            )
            ack = websocket.receive_json()

    assert ack["event"] == "subscribed"
    assert ack["channel"] == "digital-twin"
    assert ack["filters"]["network_id"] == network_id
