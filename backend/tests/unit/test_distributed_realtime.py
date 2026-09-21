import asyncio
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.events.bus import completion_key, process_entry
from app.events.distributed_realtime import DistributedRealtime, fenced_handlers
from app.events.fanout import FanoutPublisher, FanoutSubscriber, _publisher, push_realtime_delta
from app.events.fanout_contract import FanoutEnvelope, FanoutSettings
from app.events.realtime import ApiRealtimeLease
from app.websocket.delivery import DeliveryLimits
from app.websocket.manager import TopologyWSManager
from tests.unit.test_websocket_delivery import Socket, until
from tests.ws_auth_support import ws_identity as ws_identity  # noqa: PLC0414


def envelope(sequence=1, **changes):
    return FanoutEnvelope.model_validate({
        "kind": "delta", "epoch": "leader", "sequence": sequence,
        "published_at": time.time(), "delivery_id": str(sequence), "channel": "topology",
        "kwargs": {"network_id": "network", "workspace_id": "workspace", "event_type": "network.device.updated",
                   "delta_type": "update", "node": {}, "correlation_id": "c", "timestamp": "now"},
        **changes,
    })


def fields(item):
    return {b"body": item.model_dump_json().encode()}


async def test_subscriber_gap_epoch_duplicate_order_and_bounded_memory():
    delivered, availability = [], []
    subscriber = FanoutSubscriber(None, settings=FanoutSettings(dedup_entries=2),
                                  dispatch=AsyncMock(side_effect=lambda item: delivered.append(item.delivery_id)),
                                  availability=AsyncMock(side_effect=lambda value: availability.append(value)))
    for item in (envelope(1), envelope(2, delivery_id="1"), envelope(3), envelope(4)):
        await subscriber._accept(fields(item))
    assert delivered == ["1", "3", "4"]
    assert list(subscriber.seen) == ["3", "4"]
    await subscriber._accept(fields(envelope(6)))
    assert availability == [True, False, True]
    await subscriber._accept(fields(envelope(7, epoch="replacement")))
    assert availability[-2:] == [False, True]
    assert delivered == ["1", "3", "4", "6", "7"]


async def test_resuming_after_event_loop_stall_forces_reconciliation():
    availability = AsyncMock()
    subscriber = FanoutSubscriber(None, settings=FanoutSettings(), dispatch=AsyncMock(), availability=availability)
    await subscriber._accept(fields(envelope(1)))
    subscriber.last_received -= 6
    await subscriber._accept(fields(envelope(2)))
    assert [call.args[0] for call in availability.await_args_list] == [True, False, True]


@pytest.mark.parametrize("body", [b"not-json", b"\xff", b'{"version":2}', b"[]", b"x" * 1025])
async def test_malformed_and_oversized_entries_fail_closed(body):
    subscriber = FanoutSubscriber(None, settings=FanoutSettings(max_payload_bytes=1024),
                                  dispatch=AsyncMock(), availability=AsyncMock())
    with pytest.raises(ValueError):
        await subscriber._accept({b"body": body})
    subscriber.dispatch.assert_not_called()


async def test_publish_failure_cannot_ack_or_mark_durable_work():
    redis = AsyncMock()
    redis.exists.return_value = False
    redis.eval.side_effect = OSError("offline")
    publisher = FanoutPublisher(redis, token="leader", settings=FanoutSettings())
    async def handler(event):
        await publisher.publish(channel="topology", delivery_id=event["event_id"], kwargs=envelope().arguments())
    with pytest.raises(asyncio.CancelledError):
        await process_entry(redis, "stream:network", "group", "1-0", {
            "event_id": "00000000-0000-0000-0000-000000000001", "event_type": "event", "payload": "{}",
        }, {"event": handler})
    redis.xack.assert_not_called()
    redis.xadd.assert_not_called()
    redis.set.assert_not_called()


@pytest.mark.parametrize("persisted", [True, False])
async def test_telemetry_commit_or_replay_precedes_publish_without_follower_sideeffects(monkeypatch, persisted):
    from app.events.consumers import telemetry_consumer as consumer
    order = []
    db = AsyncMock()
    db.commit.side_effect = lambda: order.append("commit")
    session = AsyncMock()
    session.__aenter__.return_value = db
    monkeypatch.setattr(consumer, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(consumer.TelemetryPersistenceService, "persist_event", AsyncMock(return_value=persisted))
    from app.modules.telemetry.replay import TelemetryReplay
    monkeypatch.setattr(consumer.TelemetryPersistenceService, "replay_event", AsyncMock(return_value=TelemetryReplay(
        "active_exact", {"event_id": "id", "payload": {"network_id": "n"}},
    )))
    monkeypatch.setattr(consumer, "handle_persisted_metric_event", AsyncMock(side_effect=lambda _: order.append("detector")))
    monkeypatch.setattr(consumer, "_get_counter_service", lambda: None)
    publisher = AsyncMock()
    async def publish(**kwargs):
        order.append("publish")
        raise asyncio.CancelledError("uncertain publish")
    publisher.publish.side_effect = publish
    context = _publisher.set(publisher)
    try:
        with pytest.raises(asyncio.CancelledError):
            await consumer.handle_telemetry_event({"event_id": "id", "payload": {"network_id": "n"}})
    finally:
        _publisher.reset(context)
    assert order == (["commit"] if persisted else []) + ["detector", "publish"]


async def test_fencing_preserves_identity_and_blocks_stale_domain_effect():
    redis = AsyncMock()
    lease = ApiRealtimeLease(redis)
    calls = []
    async def effect(event):
        calls.append(event)
    wrapped = fenced_handlers({"event": [effect]}, lease)["event"][0]
    assert completion_key("s", "g", "id", wrapped) == completion_key("s", "g", "id", effect)
    with pytest.raises(asyncio.CancelledError):
        await wrapped({})
    assert not calls


async def test_legacy_bridge_and_distributed_no_local_double_send():
    manager = AsyncMock()
    args = envelope().arguments()
    await push_realtime_delta(manager, channel="topology", event={"event_id": "id"}, **args)
    manager.push_delta.assert_awaited_once_with(**args)
    publisher = AsyncMock()
    context = _publisher.set(publisher)
    try:
        await push_realtime_delta(manager, channel="topology", event={"event_id": "id"}, **args)
    finally:
        _publisher.reset(context)
    assert manager.push_delta.await_count == 1
    publisher.publish.assert_awaited_once_with(channel="topology", delivery_id="topology:id", kwargs=args)


async def test_loss_closes_idle_and_queued_sockets_and_rejects_new(ws_identity):
    state = ws_identity
    manager = TopologyWSManager(delivery_limits=DeliveryLimits(timeout_seconds=0.2))
    async def subscribe(ws):
        await manager.subscribe(state.network_id, ws, token=state.token, token_exp=state.claims["exp"],
                                workspace_id=state.workspace_id)
    idle, slow = Socket(), Socket(blocked=True)
    await subscribe(idle)
    await subscribe(slow)
    await manager.push_delta(network_id=state.network_id, event_type="test", delta_type="update", node={},
                             correlation_id="c", timestamp="t", workspace_id=state.workspace_id)
    await slow.started.wait()
    await manager.set_realtime_available(False)
    new = Socket()
    await subscribe(new)
    await until(lambda: not manager._connection_auth)
    for socket in (idle, slow, new):
        assert socket.frames[-1]["data"]["code"] == "WS_BACKPRESSURE"
        socket.close.assert_awaited_once_with(code=1013)
    assert not manager._deliveries


async def test_shutdown_drains_terminal_writers_before_returning(ws_identity):
    state = ws_identity
    manager = TopologyWSManager(delivery_limits=DeliveryLimits(timeout_seconds=0.02))
    ws = Socket(block_errors=True, block_close=True)
    await manager.subscribe(state.network_id, ws, token=state.token, token_exp=state.claims["exp"],
                            workspace_id=state.workspace_id)
    await manager.stop_realtime()
    assert not manager._deliveries and not manager._connection_auth
    assert not any(task.get_name() == "ws-connection-delivery" for task in asyncio.all_tasks())


async def test_supervisor_restarts_failed_child_and_stops_before_release(monkeypatch):
    active, starts, stopped = 0, [], []
    class Lease:
        def __init__(self, *args, **kwargs):
            self.token = "leader"
        async def __aenter__(self):
            self.task = asyncio.create_task(asyncio.Event().wait())
            return self
        async def verify(self):
            return True
        async def __aexit__(self, *args):
            assert active == 0
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
    monkeypatch.setattr("app.events.distributed_realtime.ApiRealtimeLease", Lease)
    @asynccontextmanager
    async def factory(lease):
        nonlocal active
        active += 1
        starts.append(lease)
        task = asyncio.create_task(asyncio.Event().wait())
        try:
            if len(starts) == 1:
                task.cancel()
            yield [task]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            active -= 1
            stopped.append(lease)
    runtime = DistributedRealtime(AsyncMock(), leader_factory=factory, managers={},
                                  settings=FanoutSettings(retry_seconds=0.01))
    async def heartbeat(_):
        await asyncio.Event().wait()
    runtime._heartbeat = heartbeat
    task = asyncio.create_task(runtime._supervise())
    await until(lambda: len(starts) == 2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert len(stopped) == 2 and active == 0


async def test_partial_leader_startup_timeout_notifies_supervisor_before_cleanup():
    entered = asyncio.Event()
    release = asyncio.Event()
    @asynccontextmanager
    async def factory(lease):
        try:
            entered.set()
            await asyncio.Event().wait()
            yield []
        finally:
            await release.wait()
    settings = FanoutSettings(heartbeat_seconds=0.01, io_timeout_seconds=0.01,
                              stale_seconds=0.05, lease_ttl_seconds=0.01)
    runtime = DistributedRealtime(AsyncMock(), leader_factory=factory, managers={}, settings=settings)
    failed = asyncio.Event()
    task = asyncio.create_task(runtime._work(type("Lease", (), {"token": "token"})(), failed))
    await entered.wait()
    await asyncio.wait_for(failed.wait(), 1)
    assert not task.done()
    release.set()
    await asyncio.wait_for(task, 1)
