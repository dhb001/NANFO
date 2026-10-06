"""Telemetry rejects stale/missing session claims even with a valid signature."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from tests.integration.test_topology_ws_endpoint import app
from tests.jwt_support import jwt
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414


async def test_legacy_token_requires_relogin(ws_identity):
    claims = dict(ws_identity.claims)
    del claims["sid"]
    settings = get_settings()
    token = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"/ws/telemetry?token={token}"),
    ):
        pass
