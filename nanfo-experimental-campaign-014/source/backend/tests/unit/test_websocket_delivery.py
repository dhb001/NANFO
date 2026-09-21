"""Failure/ordering gates using production session and current RBAC validation."""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.modules.identity.sessions import SessionRepository
from app.websocket import manager as managers
from app.websocket.delivery import DeliveryLimits
from tests.unit.test_websocket_auth_revalidation import MANAGERS, push, subscribe
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414


class Socket:
    def __init__(self, *, blocked=False, block_errors=False, block_close=False):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.blocked = blocked
        self.block_errors = block_errors
        self.block_close = block_close
        self.frames = []
        self.cancelled = 0
        self.close = AsyncMock(side_effect=self._close)

    async def _close(self, *, code):
        if self.block_close:
            await asyncio.Event().wait()

    async def send_text(self, text):
        frame = json.loads(text)
        if self.blocked and frame["event"] != "error":
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        if self.block_errors and frame["event"] == "error":
            await asyncio.Event().wait()
        self.frames.append(frame)


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0)


async def unsubscribe(manager, ws, state, channel):
    if channel == "alerts":
        await manager.unsubscribe(ws)
    else:
        await manager.unsubscribe(state.network_id, ws)


@pytest.mark.parametrize("channel", MANAGERS)
async def test_slow_client_does_not_block_peer_and_fifo_has_one_writer(ws_identity, channel):
    state = ws_identity
    manager = MANAGERS[channel](delivery_limits=DeliveryLimits(max_pending=8))
    slow, fast = Socket(blocked=True), Socket()
    for ws in (slow, fast):
        await subscribe(manager, ws, state, channel)
    for index in range(6):
        # Distinct envelope values expose ordering, not only delivery counts.
        kwargs = dict(event_type=f"delta.{index}", correlation_id=str(index), timestamp="time", workspace_id=state.workspace_id)
        if channel == "alerts":
            await manager.push_delta(delta_type="add", alert={}, **kwargs)
        elif channel == "digital-twin":
            await manager.push_delta(network_id=state.network_id, delta_type="update", scene_object={}, **kwargs)
        elif channel == "topology":
            await manager.push_delta(network_id=state.network_id, delta_type="update", node={}, **kwargs)
        else:
            await manager.push_delta(network_id=state.network_id, metric={}, **kwargs)
        await until(lambda: len(fast.frames) == index + 1)
        assert not slow.frames
    delivery = manager._deliveries[slow]
    writer = delivery.task
    assert writer is not None and delivery.current is not None
    assert len(delivery.pending) == 5
    assert sum(task.get_name() == "ws-connection-delivery" for task in asyncio.all_tasks()) == 1
    slow.release.set()
    await until(lambda: delivery.task is None)
    assert [frame["correlation_id"] for frame in slow.frames] == [str(i) for i in range(6)]
    assert slow.frames == fast.frames
    for ws in (slow, fast):
        await unsubscribe(manager, ws, state, channel)
    assert not manager._connection_auth and not manager._deliveries and not manager._subscriptions


@pytest.mark.parametrize("channel", MANAGERS)
@pytest.mark.parametrize("revocation", ["logout", "inactive", "roles", "permissions", "membership", "redis", "expired"])
async def test_queued_messages_revalidate_after_revocation(ws_identity, channel, revocation):
    state = ws_identity
    manager, ws = MANAGERS[channel](), Socket(blocked=True)
    await subscribe(manager, ws, state, channel)
    await push(manager, state, channel, state.workspace_id)
    await ws.started.wait()
    await push(manager, state, channel, state.workspace_id)
    await push(manager, state, channel, state.workspace_id)
    delivery = manager._deliveries[ws]
    assert len(delivery.pending) == 2
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
        manager._connection_auth[ws].token_exp = 1
    else:
        state.redis.get = AsyncMock(side_effect=RuntimeError("unavailable"))
    ws.release.set()
    await until(lambda: ws not in manager._deliveries)
    # Only the already-authorized in-flight transport may complete. No queued data.
    assert [frame["event"] for frame in ws.frames] == ["test.delta", "error"]
    assert ws.frames[-1]["data"]["code"] == "WS_UNAUTHORIZED"
    ws.close.assert_awaited_once_with(code=1008)
    assert not delivery.pending and delivery.pending_bytes == 0
    await push(manager, state, channel, state.workspace_id)
    assert len(ws.frames) == 2


@pytest.mark.parametrize("channel", MANAGERS)
async def test_overflow_cancels_send_discards_backlog_and_signals_reconciliation(ws_identity, channel):
    state = ws_identity
    manager = MANAGERS[channel](delivery_limits=DeliveryLimits(max_pending=2))
    ws = Socket(blocked=True)
    await subscribe(manager, ws, state, channel)
    await push(manager, state, channel, state.workspace_id)
    await ws.started.wait()
    delivery = manager._deliveries[ws]
    writer = delivery.task
    await push(manager, state, channel, state.workspace_id)
    await push(manager, state, channel, state.workspace_id)
    assert delivery.task is writer and len(delivery.pending) == 2
    await push(manager, state, channel, state.workspace_id)
    await until(lambda: ws not in manager._deliveries)
    assert ws.cancelled == 1
    assert len(ws.frames) == 1 and ws.frames[0]["data"]["code"] == "WS_BACKPRESSURE"
    ws.close.assert_awaited_once_with(code=1013)
    assert not delivery.pending and not manager._connection_auth


@pytest.mark.parametrize("channel", MANAGERS)
async def test_unsubscribe_cancels_pending_and_inflight_and_is_idempotent(ws_identity, channel):
    state = ws_identity
    manager, ws = MANAGERS[channel](), Socket(blocked=True)
    await subscribe(manager, ws, state, channel)
    await push(manager, state, channel, state.workspace_id)
    await ws.started.wait()
    await push(manager, state, channel, state.workspace_id)
    delivery = manager._deliveries[ws]
    writer = delivery.task
    await unsubscribe(manager, ws, state, channel)
    await unsubscribe(manager, ws, state, channel)
    ws.release.set()
    assert writer.done() and not delivery.pending and not ws.frames
    assert not manager._deliveries and not manager._connection_auth and not manager._subscriptions
    # Reusing a socket must not let an old writer clean up its new generation.
    await subscribe(manager, ws, state, channel)
    await push(manager, state, channel, state.workspace_id)
    await until(lambda: len(ws.frames) == 1)
    assert ws in manager._connection_auth
    await unsubscribe(manager, ws, state, channel)


@pytest.mark.parametrize("block_errors,block_close", [(False, False), (True, False), (True, True)])
async def test_send_timeout_and_blocked_terminal_io_have_bounded_cleanup(ws_identity, block_errors, block_close):
    manager = managers.TelemetryWSManager(delivery_limits=DeliveryLimits(timeout_seconds=0.01))
    ws = Socket(blocked=True, block_errors=block_errors, block_close=block_close)
    await subscribe(manager, ws, ws_identity, "telemetry")
    await push(manager, ws_identity, "telemetry", ws_identity.workspace_id)
    await until(lambda: ws not in manager._deliveries)
    assert ws.cancelled == 1
    ws.close.assert_awaited_once_with(code=1013)
    assert not manager._connection_auth


async def test_byte_limit_rejects_oversized_frame_before_writer_starts(ws_identity):
    manager = managers.TelemetryWSManager(delivery_limits=DeliveryLimits(max_pending_bytes=1))
    ws = Socket()
    await subscribe(manager, ws, ws_identity, "telemetry")
    await push(manager, ws_identity, "telemetry", ws_identity.workspace_id)
    await until(lambda: ws not in manager._deliveries)
    assert [frame["data"]["code"] for frame in ws.frames] == ["WS_BACKPRESSURE"]


async def test_alert_queue_uses_updated_workspace_membership(ws_identity):
    state = ws_identity
    manager, ws = managers.AlertsWSManager(), Socket(blocked=True)
    await subscribe(manager, ws, state, "alerts")
    await push(manager, state, "alerts", state.other_workspace_id)
    await ws.started.wait()
    for workspace in (state.workspace_id, None, state.other_workspace_id):
        await push(manager, state, "alerts", workspace)
    del state.memberships[uuid.UUID(state.org_id)]
    ws.release.set()
    await until(lambda: manager._deliveries[ws].task is None)
    assert len(ws.frames) == 2
    ws.close.assert_not_awaited()
    # The fresh membership set also narrows subsequent admission, not just sends.
    for _ in range(70):
        await push(manager, state, "alerts", state.workspace_id)
    assert manager._deliveries[ws].task is None
    assert not manager._deliveries[ws].pending
    assert len(ws.frames) == 2
    ws.close.assert_not_awaited()
    await manager.unsubscribe(ws)


@pytest.mark.parametrize("blocked_operation", ["authorization", "send"])
async def test_foreign_alert_flood_cannot_consume_queue_but_own_overflow_still_closes(
    ws_identity, monkeypatch, blocked_operation,
):
    state = ws_identity
    manager = managers.AlertsWSManager(delivery_limits=DeliveryLimits(max_pending=2))
    ws = Socket(blocked=blocked_operation == "send")
    unrelated = Socket()
    await manager.subscribe(ws, token=state.token, token_exp=state.claims["exp"],
                            allowed_workspace_ids={state.workspace_id})
    await manager.subscribe(unrelated, token=state.token, token_exp=state.claims["exp"],
                            allowed_workspace_ids={state.other_workspace_id})
    original = managers.authorized_workspaces
    entered = asyncio.Event()

    async def authorize(**kwargs):
        if blocked_operation == "authorization" and not entered.is_set():
            entered.set()
            await asyncio.Event().wait()
        return await original(**kwargs)

    authorization = AsyncMock(side_effect=authorize)
    monkeypatch.setattr(managers, "authorized_workspaces", authorization)
    foreign = str(uuid.UUID(int=99))
    try:
        # Includes the review's idle-subscriber case: even the first foreign
        # event must not start a writer or an authorization request.
        for _ in range(70):
            for workspace in (foreign, None):
                await push(manager, state, "alerts", workspace)
        assert not manager._deliveries
        authorization.assert_not_awaited()

        await push(manager, state, "alerts", state.workspace_id)
        await until(lambda: entered.is_set() if blocked_operation == "authorization" else ws.started.is_set())
        delivery = manager._deliveries[ws]
        writer = delivery.task
        await push(manager, state, "alerts", state.workspace_id)
        pending_bytes = delivery.pending_bytes
        for _ in range(70):
            for workspace in (foreign, None):
                await push(manager, state, "alerts", workspace)
        assert delivery.task is writer and len(delivery.pending) == 1
        assert delivery.pending_bytes == pending_bytes and not delivery.overflowed
        assert not ws.frames
        ws.close.assert_not_awaited()

        # Only this subscriber's own traffic consumes the remaining queue slot.
        await push(manager, state, "alerts", state.workspace_id)
        await push(manager, state, "alerts", state.workspace_id)
        await until(lambda: ws not in manager._deliveries)
        assert [frame["data"]["code"] for frame in ws.frames] == ["WS_BACKPRESSURE"]
        ws.close.assert_awaited_once_with(code=1013)
        assert unrelated in manager._subscribers and unrelated not in manager._deliveries
        assert not unrelated.frames
        unrelated.close.assert_not_awaited()
    finally:
        await manager.unsubscribe(ws)
        await manager.unsubscribe(unrelated)


async def test_auth_wait_does_not_block_peer_and_expiry_during_auth_denies(ws_identity, monkeypatch):
    original = managers.authorized_workspaces
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(**kwargs):
        if not entered.is_set():
            entered.set()
            await release.wait()
        return await original(**kwargs)

    monkeypatch.setattr(managers, "authorized_workspaces", delayed)
    manager, slow, fast = managers.TelemetryWSManager(), Socket(), Socket()
    await subscribe(manager, slow, ws_identity, "telemetry")
    await push(manager, ws_identity, "telemetry", ws_identity.workspace_id)
    await entered.wait()
    await subscribe(manager, fast, ws_identity, "telemetry")
    await push(manager, ws_identity, "telemetry", ws_identity.workspace_id)
    await until(lambda: len(fast.frames) == 1)
    manager._connection_auth[slow].token_exp = 1
    release.set()
    await until(lambda: slow not in manager._deliveries)
    assert len(slow.frames) == 1 and slow.frames[0]["data"]["code"] == "WS_UNAUTHORIZED"
    await manager.unsubscribe(ws_identity.network_id, fast)


async def test_overflow_after_revocation_prefers_unauthorized(ws_identity):
    manager = managers.TelemetryWSManager(delivery_limits=DeliveryLimits(max_pending=1))
    ws = Socket(blocked=True)
    await subscribe(manager, ws, ws_identity, "telemetry")
    await push(manager, ws_identity, "telemetry", ws_identity.workspace_id)
    await ws.started.wait()
    await push(manager, ws_identity, "telemetry", ws_identity.workspace_id)
    ws_identity.permissions = []
    await push(manager, ws_identity, "telemetry", ws_identity.workspace_id)
    await until(lambda: ws not in manager._deliveries)
    assert [frame["data"]["code"] for frame in ws.frames] == ["WS_UNAUTHORIZED"]
    ws.close.assert_awaited_once_with(code=1008)


async def test_auth_timeout_fails_closed_and_unsubscribes(ws_identity, monkeypatch):
    async def unavailable(**kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(managers, "authorized_workspaces", unavailable)
    manager = managers.TelemetryWSManager(delivery_limits=DeliveryLimits(timeout_seconds=0.01))
    ws = Socket()
    await subscribe(manager, ws, ws_identity, "telemetry")
    await push(manager, ws_identity, "telemetry", ws_identity.workspace_id)
    await until(lambda: ws not in manager._deliveries)
    assert [frame["data"]["code"] for frame in ws.frames] == ["WS_UNAUTHORIZED"]
    ws.close.assert_awaited_once_with(code=1008)


async def test_external_writer_cancellation_cleans_up_instead_of_restarting(ws_identity):
    manager, ws = managers.TelemetryWSManager(), Socket(blocked=True)
    await subscribe(manager, ws, ws_identity, "telemetry")
    await push(manager, ws_identity, "telemetry", ws_identity.workspace_id)
    await ws.started.wait()
    await push(manager, ws_identity, "telemetry", ws_identity.workspace_id)
    delivery = manager._deliveries[ws]
    delivery.task.cancel()
    await until(lambda: ws not in manager._deliveries)
    assert not delivery.pending and not ws.frames


async def test_expired_connection_with_blocked_error_still_attempts_security_close(ws_identity):
    manager = managers.TelemetryWSManager(delivery_limits=DeliveryLimits(timeout_seconds=0.01))
    ws = Socket(block_errors=True)
    await subscribe(manager, ws, ws_identity, "telemetry")
    manager._connection_auth[ws].token_exp = 1
    await push(manager, ws_identity, "telemetry", ws_identity.workspace_id)
    await until(lambda: ws not in manager._deliveries)
    ws.close.assert_awaited_once_with(code=1008)
    assert not ws.frames
