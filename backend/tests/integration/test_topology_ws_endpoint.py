"""Integration tests for /ws/topology WebSocket endpoint contract."""

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


def _make_token(*, workspace_id: uuid.UUID | None = None, org_id: uuid.UUID | None = None) -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="topology@example.com",
        roles=["Admin"],
        permissions=["read:topology", "write:config"],
        org_id=str(org_id) if org_id is not None else None,
        workspace_id=str(workspace_id) if workspace_id is not None else None,
    )
    return token


def test_ws_topology_subscribe_ack():
    token = _make_token()
    session_cm = _build_session_context()

    async def _resolve_scope(*, db, claims, network_id):
        return network_id, str(uuid.uuid4())

    with (
        patch("app.websocket.topology.get_redis_client") as mock_get_redis,
        patch("app.websocket.topology.AsyncSessionLocal", return_value=session_cm),
        patch("app.websocket.topology._resolve_topology_subscription_scope", side_effect=_resolve_scope),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/topology?token={token}") as websocket:
            websocket.send_text(
                json.dumps(
                    {
                        "action": "subscribe",
                        "channel": "topology",
                        "filters": {"network_id": str(uuid.uuid4())},
                    }
                )
            )
            ack = websocket.receive_json()

    assert ack["event"] == "subscribed"
    assert ack["channel"] == "topology"


def test_ws_topology_unknown_channel_returns_error_and_closes():
    token = _make_token()

    with (
        patch("app.websocket.topology.get_redis_client") as mock_get_redis,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/topology?token={token}") as websocket:
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


def test_ws_topology_missing_network_filter_returns_error_and_closes():
    token = _make_token()

    with (
        patch("app.websocket.topology.get_redis_client") as mock_get_redis,
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/topology?token={token}") as websocket:
            websocket.send_text(json.dumps({"action": "subscribe", "channel": "topology", "filters": {}}))
            error = websocket.receive_json()

    assert error["event"] == "error"
    assert error["data"]["code"] == "WS_INVALID_FILTER"


def test_ws_topology_scope_rejected_returns_invalid_filter_and_policy_close():
    token = _make_token(workspace_id=uuid.uuid4(), org_id=uuid.uuid4())
    session_cm = _build_session_context()

    with (
        patch("app.websocket.topology.get_redis_client") as mock_get_redis,
        patch("app.websocket.topology.AsyncSessionLocal", return_value=session_cm),
        patch("app.websocket.topology._resolve_topology_subscription_scope", return_value=None),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        fake_redis = AsyncMock()
        fake_redis.exists = AsyncMock(return_value=0)
        mock_get_redis.return_value = fake_redis

        with client.websocket_connect(f"/ws/topology?token={token}") as websocket:
            websocket.send_text(
                json.dumps(
                    {
                        "action": "subscribe",
                        "channel": "topology",
                        "filters": {"network_id": str(uuid.uuid4())},
                    }
                )
            )
            error = websocket.receive_json()

    assert error["event"] == "error"
    assert error["data"]["code"] == "WS_INVALID_FILTER"
