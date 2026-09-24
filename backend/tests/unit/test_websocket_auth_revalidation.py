"""Every channel revalidates real sessions and current public service authorization.

ADR-028 C1: the full decision is cached per connection for <= WS_AUTH_CACHE_SECONDS
(15 s) and never past token exp; ``elapse`` moves a manager's clock past that window.
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.modules.identity.sessions import SessionRepository
from app.websocket.auth import authorized_workspaces
from app.websocket.manager import (
    AlertsWSManager,
    DigitalTwinWSManager,
    TelemetryWSManager,
    TopologyWSManager,
)
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414

MANAGERS = {
    "alerts": AlertsWSManager, "digital-twin": DigitalTwinWSManager,
    "telemetry": TelemetryWSManager, "topology": TopologyWSManager,
}
DENIALS = {("WS_UNAUTHORIZED", 1008), ("WS_UNAVAILABLE", 1013)}


def elapse(manager, seconds=16.0):
    """Advance the manager's monotonic clock beyond the authorization cache window."""
    previous = manager._clock
    manager._clock = lambda: previous() + seconds


async def subscribe(manager, ws, state, channel):
    kwargs = {"token": state.token, "token_exp": state.claims["exp"], "token_jti": state.claims["jti"]}
    if channel == "alerts":
        await manager.subscribe(ws, allowed_workspace_ids={state.workspace_id, state.other_workspace_id}, **kwargs)
    else:
        await manager.subscribe(state.network_id, ws, workspace_id=state.workspace_id, **kwargs)


async def push(manager, state, channel, workspace_id):
    kwargs = {"event_type": "test.delta", "correlation_id": "correlation", "timestamp": "timestamp", "workspace_id": workspace_id}
    if channel == "alerts":
        await manager.push_delta(delta_type="add", alert={"event_id": "event"}, **kwargs)
    elif channel == "digital-twin":
        await manager.push_delta(network_id=state.network_id, delta_type="update", scene_object={"id": "scene"}, **kwargs)
    elif channel == "topology":
        await manager.push_delta(network_id=state.network_id, delta_type="update", node={"id": "node"}, **kwargs)
    else:
        await manager.push_delta(network_id=state.network_id, metric={"value": 1}, **kwargs)


@pytest.mark.parametrize("channel", MANAGERS)
async def test_live_delivery_and_dead_socket_cleanup(ws_identity, channel):
    state = ws_identity
    manager = MANAGERS[channel]()
    live, dead = AsyncMock(), AsyncMock()
    dead.send_text.side_effect = RuntimeError("disconnected")
    for ws in (live, dead):
        await subscribe(manager, ws, state, channel)
    for _ in range(2):
        await push(manager, state, channel, state.workspace_id)
    assert live.send_text.await_count == 2
    assert dead.send_text.await_count == 1
    assert json.loads(live.send_text.await_args.args[0])["event"] == "test.delta"
    live.close.assert_not_awaited()


@pytest.mark.parametrize("channel", MANAGERS)
@pytest.mark.parametrize("revocation", ["logout", "inactive", "roles", "permissions", "membership", "redis", "expired"])
async def test_revocation_before_push_never_leaks(ws_identity, channel, revocation):
    state = ws_identity
    manager, ws = MANAGERS[channel](), AsyncMock()
    await subscribe(manager, ws, state, channel)
    await push(manager, state, channel, state.workspace_id)
    ws.send_text.reset_mock()
    if revocation == "logout":
        await SessionRepository(state.redis).revoke(state.claims["sid"])
    elif revocation == "inactive":
        state.user.is_active = False
    elif revocation == "roles":
        state.roles = []
    elif revocation == "permissions":
        state.permissions = []
    elif revocation == "membership":
        state.memberships.clear()
    elif revocation == "expired":
        await state.redis.expire(SessionRepository.key(state.claims["sid"]), 0)
    else:
        from redis.exceptions import ConnectionError
        state.redis.get = AsyncMock(side_effect=ConnectionError("unavailable"))
    elapse(manager)
    await push(manager, state, channel, state.workspace_id)
    code = json.loads(ws.send_text.await_args.args[0])["data"]["code"]
    [close] = ws.close.await_args_list
    if revocation == "redis":
        # Session-store outage: revoked (401) or unavailable (503) per identity; never delivered.
        assert (code, close.kwargs["code"]) in DENIALS
    else:
        assert code == "WS_UNAUTHORIZED" and close.kwargs == {"code": 1008}
    await push(manager, state, channel, state.workspace_id)
    ws.send_text.assert_awaited_once()


async def test_unscoped_multi_org_alert_filtering_and_membership_removal(ws_identity):
    state = ws_identity
    assert "org_id" not in state.claims and "workspace_id" not in state.claims
    assert await authorized_workspaces(token=state.token, channel="alerts", network_id=None) == {
        state.workspace_id, state.other_workspace_id,
    }
    manager, ws = AlertsWSManager(), AsyncMock()
    await subscribe(manager, ws, state, "alerts")
    for workspace in (state.workspace_id, state.other_workspace_id, str(uuid.UUID(int=99)), None):
        await push(manager, state, "alerts", workspace)
    assert ws.send_text.await_count == 2
    del state.memberships[uuid.UUID(state.org_id)]
    elapse(manager)
    await push(manager, state, "alerts", state.workspace_id)
    assert ws.send_text.await_count == 2
    await push(manager, state, "alerts", state.other_workspace_id)
    assert ws.send_text.await_count == 3


@pytest.mark.parametrize("channel", MANAGERS)
async def test_missing_auth_metadata_denied_and_close_failure_safe(ws_identity, channel):
    state = ws_identity
    manager, ws = MANAGERS[channel](), AsyncMock()
    ws.send_text.side_effect = RuntimeError("disconnected")
    ws.close.side_effect = RuntimeError("already closed")
    if channel == "alerts":
        await manager.subscribe(ws)
    else:
        await manager.subscribe(state.network_id, ws)
    await push(manager, state, channel, state.workspace_id)
    ws.close.assert_awaited_once_with(code=1008)


@pytest.mark.parametrize("channel", ["topology", "telemetry", "digital-twin"])
async def test_network_event_workspace_mismatch_filtered(ws_identity, channel):
    manager, ws = MANAGERS[channel](), AsyncMock()
    await subscribe(manager, ws, ws_identity, channel)
    await push(manager, ws_identity, channel, ws_identity.other_workspace_id)
    ws.send_text.assert_not_awaited()


@pytest.mark.parametrize("channel", MANAGERS)
async def test_authorization_decision_is_cached_within_window_only(ws_identity, channel, monkeypatch):
    """C1: one full decision per <= 15 s window, not one per delta."""
    from app.websocket import manager as managers

    state = ws_identity
    calls = []
    original = managers.authorized_workspaces

    async def counted(**kwargs):
        calls.append(kwargs)
        return await original(**kwargs)

    monkeypatch.setattr(managers, "authorized_workspaces", counted)
    manager, ws = MANAGERS[channel](), AsyncMock()
    await subscribe(manager, ws, state, channel)
    for _ in range(5):
        await push(manager, state, channel, state.workspace_id)
    assert ws.send_text.await_count == 5 and len(calls) == 1
    elapse(manager, 14)
    await push(manager, state, channel, state.workspace_id)
    assert len(calls) == 1
    elapse(manager, 2)
    await push(manager, state, channel, state.workspace_id)
    assert len(calls) == 2 and ws.send_text.await_count == 7


@pytest.mark.parametrize("channel", MANAGERS)
async def test_cached_decision_never_outlives_token_expiry(ws_identity, channel):
    import time as clock

    state = ws_identity
    manager, ws = MANAGERS[channel](), AsyncMock()
    kwargs = {"token": state.token, "token_exp": int(clock.time()) + 3600,
              "authorized_until": manager._clock() + 15}
    if channel == "alerts":
        await manager.subscribe(ws, allowed_workspace_ids={state.workspace_id}, **kwargs)
    else:
        await manager.subscribe(state.network_id, ws, workspace_id=state.workspace_id, **kwargs)
    await push(manager, state, channel, state.workspace_id)
    assert ws.send_text.await_count == 1
    manager._connection_auth[ws].token_exp = 1  # expired while the cache window is still open
    await push(manager, state, channel, state.workspace_id)
    assert json.loads(ws.send_text.await_args.args[0])["data"]["code"] == "WS_UNAUTHORIZED"
    ws.close.assert_awaited_once_with(code=1008)
    assert manager._connection_auth.get(ws) is None
    # A fresh decision is bounded by the remaining token lifetime, not only 15 s.
    from app.websocket.manager import _ConnectionAuth

    near = _ConnectionAuth(token_exp=int(clock.time()) + 3, token_jti=None)
    assert manager.cache_deadline(near) <= manager._clock() + 3.01
    far = _ConnectionAuth(token_exp=int(clock.time()) + 3600, token_jti=None)
    assert manager.cache_deadline(far) <= manager._clock() + 15.0


@pytest.mark.parametrize("channel", MANAGERS)
@pytest.mark.parametrize("error", ["dependency", "redis", "postgres"])
async def test_revalidation_outage_closes_unavailable_not_unauthorized(ws_identity, channel, error, monkeypatch):
    from redis.exceptions import ConnectionError as RedisConnectionError
    from sqlalchemy.exc import OperationalError

    from app.core.errors import DependencyUnavailableError
    from app.websocket import manager as managers

    failure = {"dependency": DependencyUnavailableError("redis"), "redis": RedisConnectionError("down"),
               "postgres": OperationalError("SELECT", {}, Exception("down"))}[error]
    state = ws_identity
    manager, ws = MANAGERS[channel](), AsyncMock()
    await subscribe(manager, ws, state, channel)
    monkeypatch.setattr(managers, "authorized_workspaces", AsyncMock(side_effect=failure))
    await push(manager, state, channel, state.workspace_id)
    assert json.loads(ws.send_text.await_args.args[0])["data"] == {
        "code": "WS_UNAVAILABLE", "message": "Realtime temporarily unavailable.",
    }
    ws.close.assert_awaited_once_with(code=1013)
    await push(manager, state, channel, state.workspace_id)
    ws.send_text.assert_awaited_once()
