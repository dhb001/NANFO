"""All registered WS endpoints exercise production authentication and tenant checks."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.websocket.alerts import router as alerts_router
from app.websocket.digital_twin import router as twin_router
from app.websocket.telemetry import router as telemetry_router
from app.websocket.topology import router as topology_router
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414

app = FastAPI()
for router in (alerts_router, twin_router, telemetry_router, topology_router):
    app.include_router(router)

CHANNELS = ["alerts", "topology", "telemetry", "digital-twin"]


@pytest.mark.parametrize("channel", CHANNELS)
async def test_subscribe_ack_with_unscoped_login_and_current_readonly_role(ws_identity, channel):
    state = ws_identity
    with TestClient(app) as client, client.websocket_connect(f"/ws/{channel}?token={state.token}") as ws:
        filters = {} if channel == "alerts" else {"network_id": state.network_id}
        ws.send_json({"action": "subscribe", "channel": channel, "filters": filters})
        ack = ws.receive_json()
        assert ack["event"] == "subscribed"
        assert ack["channel"] == channel and ack["filters"] == filters


@pytest.mark.parametrize("channel", CHANNELS)
@pytest.mark.parametrize("invalid", ["refresh", "missing", "roles", "permissions", "inactive", "session"])
async def test_upgrade_denials(ws_identity, channel, invalid):
    state = ws_identity
    token = state.token
    if invalid == "refresh":
        token = state.refresh
    elif invalid == "missing":
        token = ""
    elif invalid == "roles":
        state.roles = []
    elif invalid == "permissions":
        state.permissions = []
    elif invalid == "inactive":
        state.user.is_active = False
    else:
        await state.redis.flushdb()
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error, client.websocket_connect(f"/ws/{channel}?token={token}"):
            pass
        assert error.value.code == 1008


@pytest.mark.parametrize("channel", CHANNELS)
@pytest.mark.parametrize("invalid", ["unknown_channel", "malformed", "membership", "filter"])
async def test_subscription_denials(ws_identity, channel, invalid):
    state = ws_identity
    frame = {"action": "subscribe", "channel": channel,
             "filters": {} if channel == "alerts" else {"network_id": state.network_id}}
    if invalid == "unknown_channel":
        frame["channel"] = "unknown"
    elif invalid == "malformed":
        frame["filters"] = []
    elif invalid == "membership":
        state.memberships.clear()
    else:
        frame["filters"] = {"unexpected": "filter"}
    with TestClient(app) as client, client.websocket_connect(f"/ws/{channel}?token={state.token}") as ws:
        ws.send_json(frame)
        error = ws.receive_json()
        expected = "WS_UNKNOWN_CHANNEL" if invalid == "unknown_channel" else "WS_INVALID_FILTER"
        assert error["data"]["code"] == expected
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1008
