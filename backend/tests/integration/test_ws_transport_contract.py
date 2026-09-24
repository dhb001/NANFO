"""ADR-028 C1 WebSocket transport/admission contract on the real channel endpoints.

Production JWT/session/RBAC checks run (tests.ws_auth_support); only owner-service
reads are fixtures. Outages are injected at the endpoint's auth boundary.
"""

import functools
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.errors import DependencyUnavailableError
from app.modules.identity.service import AuthService
from app.websocket import endpoint
from app.websocket.limits import connection_registry
from app.websocket.manager import topology_ws_manager
from tests.integration.test_topology_ws_endpoint import CHANNELS, app
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414


def protocols(token):
    return ["nanfo.v1", f"nanfo.bearer.{token}"]


def subscribe_frame(state, channel):
    return {"action": "subscribe", "channel": channel,
            "filters": {} if channel == "alerts" else {"network_id": state.network_id}}


def settings_with(monkeypatch, **changes):
    settings = get_settings().model_copy(update=changes)
    monkeypatch.setattr(endpoint, "get_settings", lambda: settings)
    return settings


def expect_terminal(ws, code, close_code):
    frame = ws.receive_json()
    assert frame["event"] == "error" and frame["data"]["code"] == code
    with pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_json()
    assert closed.value.code == close_code
    return frame


@pytest.mark.parametrize("channel", CHANNELS)
async def test_subprotocol_bearer_selects_only_versioned_protocol(ws_identity, channel):
    state = ws_identity
    with TestClient(app) as client, client.websocket_connect(f"/ws/{channel}", subprotocols=protocols(state.token)) as ws:
        assert ws.accepted_subprotocol == "nanfo.v1"
        ws.send_json(subscribe_frame(state, channel))
        assert ws.receive_json()["event"] == "subscribed"
    assert connection_registry.count(str(state.user.user_id)) == 0


async def test_legacy_query_token_remains_compatible_without_subprotocol(ws_identity):
    state = ws_identity
    with TestClient(app) as client, client.websocket_connect(f"/ws/topology?token={state.token}") as ws:
        assert ws.accepted_subprotocol is None
        ws.send_json(subscribe_frame(state, "topology"))
        assert ws.receive_json()["event"] == "subscribed"


@pytest.mark.parametrize("offered", [
    lambda token: [f"nanfo.bearer.{token}"],  # bearer outside the versioned protocol
    lambda token: ["nanfo.v1", f"nanfo.bearer.{token}", f"nanfo.bearer.{token}"],
    lambda token: ["nanfo.v1", "nanfo.bearer."],
    lambda token: ["nanfo.v1", "nanfo.bearer.not-a-jwt"],
    lambda token: ["nanfo.v1"],  # no credentials at all
])
async def test_invalid_or_missing_bearer_closes_1008_before_accept(ws_identity, offered):
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error, client.websocket_connect(
            "/ws/topology", subprotocols=offered(ws_identity.token),
        ):
            pass
    assert error.value.code == 1008


@pytest.mark.parametrize("failure", [
    DependencyUnavailableError("redis"), RedisConnectionError("down"),
    OperationalError("SELECT", {}, Exception("down")), ServiceUnavailable("down"), TimeoutError(),
], ids=lambda failure: type(failure).__name__)
async def test_auth_outage_accepts_then_closes_unavailable(ws_identity, failure):
    with (
        patch.object(endpoint, "authenticate", AsyncMock(side_effect=failure)),
        TestClient(app) as client,
        client.websocket_connect("/ws/telemetry", subprotocols=protocols(ws_identity.token)) as ws,
    ):
        frame = expect_terminal(ws, "WS_UNAVAILABLE", 1013)
    assert frame["data"]["message"] == "Realtime temporarily unavailable."


@pytest.mark.parametrize("failure,close_code", [
    (DependencyUnavailableError("postgres"), 1013), (RedisConnectionError("down"), 1013),
    (RuntimeError("unexpected"), 1011),
])
async def test_subscribe_outage_is_retryable_not_a_filter_error(ws_identity, failure, close_code):
    state = ws_identity
    with (
        patch.object(endpoint, "authorize_claims", AsyncMock(side_effect=failure)),
        TestClient(app) as client,
        client.websocket_connect("/ws/topology", subprotocols=protocols(state.token)) as ws,
    ):
        ws.send_json(subscribe_frame(state, "topology"))
        expect_terminal(ws, "WS_UNAVAILABLE", close_code)


async def test_missing_subscribe_frame_times_out_with_retryable_close(ws_identity, monkeypatch):
    settings_with(monkeypatch, WS_SUBSCRIBE_TIMEOUT_SECONDS=0.2)
    with TestClient(app) as client, client.websocket_connect("/ws/alerts", subprotocols=protocols(ws_identity.token)) as ws:
        expect_terminal(ws, "WS_SUBSCRIBE_TIMEOUT", 1013)


async def test_per_user_socket_cap(ws_identity, monkeypatch):
    state = ws_identity
    settings_with(monkeypatch, WS_MAX_CONNECTIONS_PER_USER=1)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/topology", subprotocols=protocols(state.token)) as first:
            first.send_json(subscribe_frame(state, "topology"))
            assert first.receive_json()["event"] == "subscribed"
            with client.websocket_connect("/ws/alerts", subprotocols=protocols(state.token)) as second:
                expect_terminal(second, "WS_CONNECTION_LIMIT", 1008)
        # Slots are released on disconnect.
        with client.websocket_connect("/ws/alerts", subprotocols=protocols(state.token)) as third:
            third.send_json(subscribe_frame(state, "alerts"))
            assert third.receive_json()["event"] == "subscribed"
    assert connection_registry.count(str(state.user.user_id)) == 0


@pytest.mark.parametrize("phase", ["subscribe", "subscribed"])
async def test_oversized_inbound_frame_closes_1009(ws_identity, phase):
    state = ws_identity
    oversized = "x" * (get_settings().WS_MAX_FRAME_BYTES + 1)
    with TestClient(app) as client, client.websocket_connect("/ws/topology", subprotocols=protocols(state.token)) as ws:
        if phase == "subscribed":
            ws.send_json(subscribe_frame(state, "topology"))
            assert ws.receive_json()["event"] == "subscribed"
        ws.send_text(oversized)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1009


async def test_authenticates_once_and_reuses_the_decision_for_first_deltas(ws_identity):
    state = ws_identity
    original = AuthService.authenticate_access
    calls = []

    async def counted(self, token):
        calls.append(token)
        return await original(self, token)

    with (
        patch.object(AuthService, "authenticate_access", counted),
        TestClient(app) as client,
        client.websocket_connect("/ws/topology", subprotocols=protocols(state.token)) as ws,
    ):
        ws.send_json(subscribe_frame(state, "topology"))
        assert ws.receive_json()["event"] == "subscribed"
        for index in range(3):
            ws.portal.call(functools.partial(
                topology_ws_manager.push_delta, network_id=state.network_id, event_type="network.device.updated",
                delta_type="update", node={"device_id": str(index)}, correlation_id="c", timestamp="t",
                workspace_id=state.workspace_id,
            ))
            assert ws.receive_json()["data"]["node"] == {"device_id": str(index)}
    assert calls == [state.token]  # connect-time authentication seeds the <=15 s cache


async def test_token_expiry_closes_idle_subscribed_socket(ws_identity):
    state = ws_identity
    claims = {**state.claims, "exp": int(time.time()) + 1, "roles": ["Read-Only"],
              "permissions": ["read:topology"]}
    with (
        patch.object(endpoint, "authenticate", AsyncMock(return_value=claims)),
        TestClient(app) as client,
        client.websocket_connect("/ws/topology", subprotocols=protocols(state.token)) as ws,
    ):
        ws.send_json(subscribe_frame(state, "topology"))
        assert ws.receive_json()["event"] == "subscribed"
        started = time.monotonic()
        expect_terminal(ws, "WS_UNAUTHORIZED", 1008)
        assert time.monotonic() - started < 5
    assert not topology_ws_manager._connection_auth
