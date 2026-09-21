"""Opt-in two-process acceptance with UUID-owned disposable Redis; no shared DB/lab.

RUN_DISTRIBUTED_REALTIME=1 poetry run pytest tests/integration/test_distributed_realtime_sockets.py --no-cov -q
"""

import asyncio
import json
import multiprocessing
import os
import socket
import subprocess
import uuid
from contextlib import AsyncExitStack

import pytest
from redis.asyncio import Redis
from websockets.asyncio.client import connect

from app.core.security import create_access_token, create_refresh_token, decode_token
from app.events.fanout import FanoutPublisher
from app.events.fanout_contract import FanoutSettings
from app.modules.identity.sessions import SessionRepository
from tests.distributed_realtime_support import NETWORK, ORG, USER, WORKSPACE, run_api

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DISTRIBUTED_REALTIME") != "1", reason="isolated Docker acceptance opt-in")
REDIS_IMAGE = "sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2"


async def wait_for(predicate, timeout=10):
    async with asyncio.timeout(timeout):
        while not await predicate():
            await asyncio.sleep(0.02)


@pytest.fixture
async def isolated_runtime():
    name = f"nanfo-realtime-{uuid.uuid4().hex}"
    processes, sockets = [], []
    redis = None
    # Exact already-installed image, no pull, mounts, shared containers or fixed ports.
    subprocess.run(["docker", "run", "--detach", "--rm", "--pull=never", "--name", name,
                    "--publish", "127.0.0.1::6379", REDIS_IMAGE, "redis-server", "--save", "", "--appendonly", "no"],
                   check=True, capture_output=True, text=True)
    try:
        port = subprocess.check_output(["docker", "port", name, "6379/tcp"], text=True).strip().rsplit(":", 1)[1]
        url = f"redis://127.0.0.1:{port}/0"
        redis = Redis.from_url(url, decode_responses=True)
        async def ping():
            try:
                return await redis.ping()
            except Exception:
                return False
        await wait_for(ping)
        prefix = name
        async def start():
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sock.listen(128)
            sockets.append(sock)
            process = multiprocessing.get_context("spawn").Process(target=run_api, args=(sock, url, prefix))
            process.start()
            processes.append(process)
            await wait_for(lambda: redis.exists(f"{prefix}:ready:{process.pid}"))
            return process, sock.getsockname()[1]
        first, second = await start(), await start()
        yield redis, prefix, [first, second], start
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            await asyncio.to_thread(process.join, 4)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join, 4)
            assert not process.is_alive()
            process.close()
        for sock in sockets:
            sock.close()
        if redis is not None:
            await redis.aclose()
        subprocess.run(["docker", "rm", "--force", name], check=True, capture_output=True, text=True)
        remaining = subprocess.check_output(["docker", "ps", "-aq", "--filter", f"name=^{name}$"], text=True)
        assert not remaining.strip()


async def identity(redis):
    sid = str(uuid.uuid4())
    access, _ = create_access_token(user_id=USER, sid=sid, email="socket@example.com", roles=["Read-Only"],
                                    permissions=["read:topology", "read:telemetry"], org_id=ORG, workspace_id=WORKSPACE)
    refresh, _ = create_refresh_token(user_id=USER, sid=sid, org_id=ORG, workspace_id=WORKSPACE)
    await SessionRepository(redis).create(decode_token(refresh, token_type="refresh"), refresh)
    return access, sid


async def subscribe(stack, port, token, channel="topology"):
    ws = await stack.enter_async_context(connect(f"ws://127.0.0.1:{port}/ws/{channel}?token={token}"))
    await ws.send(json.dumps({"action": "subscribe", "channel": channel,
                              "filters": {} if channel == "alerts" else {"network_id": NETWORK}}))
    assert json.loads(await asyncio.wait_for(ws.recv(), 3))["event"] == "subscribed"
    return ws


async def frame(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), 4))


async def emit(redis, prefix, index, event_type="network.device.updated", event_id=None):
    event_id = event_id or str(uuid.uuid4())
    await redis.xadd(f"{prefix}:domain", {
        "event_id": event_id, "event_type": event_type, "source": "network", "correlation_id": str(index),
        "timestamp": "2026-09-20T00:00:00Z", "payload": json.dumps({
            "network_id": NETWORK, "workspace_id": WORKSPACE, "device_id": str(uuid.UUID(int=9)),
            "changed_fields": {"hostname": str(index)}, "metric": "cpu", "value": index,
        }),
    })
    return event_id


async def test_two_process_broadcast_loss_order_revocation_restart_and_slow_client(isolated_runtime):
    redis, prefix, apis, start = isolated_runtime
    token, sid = await identity(redis)
    settings = FanoutSettings(stream_key=f"{prefix}:fanout", sequence_key=f"{prefix}:sequence", lease_key=f"{prefix}:lease", max_entries=16)
    async with AsyncExitStack() as stack:
        sockets = [await subscribe(stack, port, token) for _, port in apis]
        # Both independent API processes receive every delta, once and in order.
        ids = []
        for index in range(8):
            ids.append(await emit(redis, prefix, index))
            assert [item["correlation_id"] for item in await asyncio.gather(*(frame(ws) for ws in sockets))] == [str(index)] * 2
        await emit(redis, prefix, 7, event_id=ids[-1])
        await emit(redis, prefix, 8)
        assert [item["correlation_id"] for item in await asyncio.gather(*(frame(ws) for ws in sockets))] == ["8", "8"]
        assert await redis.get(f"{prefix}:effects:count") == "9"
        # Duplicate publication after commit/publish crash is deduped at each API.
        publisher = FanoutPublisher(redis, token=await redis.get(settings.lease_key), settings=settings)
        args = dict(network_id=NETWORK, workspace_id=WORKSPACE, event_type="network.device.updated",
                    delta_type="update", node={"device_id": "fixture"}, correlation_id="retry", timestamp="now")
        await publisher.publish(channel="topology", delivery_id="crash-window", kwargs=args)
        await asyncio.gather(*(frame(ws) for ws in sockets))
        await publisher.publish(channel="topology", delivery_id="crash-window", kwargs=args)
        await emit(redis, prefix, 9)
        assert [item["correlation_id"] for item in await asyncio.gather(*(frame(ws) for ws in sockets))] == ["9", "9"]
        # Existing telemetry/alert/twin bridges also cross the process boundary.
        for channel, event_type in (("telemetry", "telemetry.metric.ingested"), ("alerts", "alert.generated"),
                                    ("digital-twin", "simulation.started")):
            peers = [await subscribe(stack, port, token, channel) for _, port in apis]
            await emit(redis, prefix, 10, event_type)
            assert [item["event"] for item in await asyncio.gather(*(frame(ws) for ws in peers))] == [event_type] * 2
            for peer in peers:
                await peer.close()
        # Real shared session revocation checked afresh on both socket writers.
        await SessionRepository(redis).revoke(sid)
        await emit(redis, prefix, 11)
        assert [item["data"]["code"] for item in await asyncio.gather(*(frame(ws) for ws in sockets))] == ["WS_UNAUTHORIZED"] * 2
        token, _ = await identity(redis)
        sockets = [await subscribe(stack, port, token) for _, port in apis]
        await redis.set(f"{prefix}:membership-revoked", "1")
        await emit(redis, prefix, 12)
        assert [item["data"]["code"] for item in await asyncio.gather(*(frame(ws) for ws in sockets))] == ["WS_UNAUTHORIZED"] * 2
        await redis.delete(f"{prefix}:membership-revoked")
        sockets = [await subscribe(stack, port, token) for _, port in apis]
        await redis.set(f"{prefix}:permission-revoked", "1")
        await emit(redis, prefix, "permission")
        assert [item["data"]["code"] for item in await asyncio.gather(*(frame(ws) for ws in sockets))] == ["WS_UNAUTHORIZED"] * 2
        await redis.delete(f"{prefix}:permission-revoked")
        sockets = [await subscribe(stack, port, token) for _, port in apis]
        # Malformed transport forces loss on both, never silently skipped.
        await redis.xadd(settings.stream_key, {"body": "not-json"}, maxlen=16, approximate=False)
        assert [item["data"]["code"] for item in await asyncio.gather(*(frame(ws) for ws in sockets))] == ["WS_BACKPRESSURE"] * 2
        await asyncio.sleep(0.2)
        sockets = [await subscribe(stack, port, token) for _, port in apis]
        # One missed subscriber: trim its backlog; the peer remains current.
        await redis.set(f"{prefix}:pause:{apis[1][0].pid}", "1")
        for index in range(30):
            await publisher.publish(channel="topology", delivery_id=f"trim-{index}", kwargs={**args, "correlation_id": f"trim-{index}"})
            assert (await frame(sockets[0]))["correlation_id"] == f"trim-{index}"
        async def backpressure(ws):
            while True:
                item = await frame(ws)
                if item["event"] == "error":
                    return item["data"]["code"]
        assert await backpressure(sockets[1]) == "WS_BACKPRESSURE"
        await redis.delete(f"{prefix}:pause:{apis[1][0].pid}")
        await asyncio.sleep(0.5)
        sockets[1] = await subscribe(stack, apis[1][1], token)
        await emit(redis, prefix, 13)
        assert [item["correlation_id"] for item in await asyncio.gather(*(frame(ws) for ws in sockets))] == ["13"] * 2
        # Deterministic slow transport on a real socket, bounded writer deadline.
        slow_token, _ = await identity(redis)
        await redis.set(f"{prefix}:slow-token", slow_token)
        slow = await subscribe(stack, apis[0][1], slow_token)
        await emit(redis, prefix, 14)
        assert [item["correlation_id"] for item in await asyncio.gather(*(frame(ws) for ws in sockets))] == ["14"] * 2
        assert (await frame(slow))["data"]["code"] == "WS_BACKPRESSURE"
        await redis.delete(f"{prefix}:slow-token")
        # Kill the leader: follower serves, detects epoch loss, then takes over.
        leader_pid = int(await redis.get(f"{prefix}:leader-pid"))
        leader_index = next(i for i, (process, _) in enumerate(apis) if process.pid == leader_pid)
        follower_index = 1 - leader_index
        # Crash after owning commit, before its marker/fanout/ACK: pending must
        # replay, durable fixture effect remains once, follower gets recovered delta.
        crash_id = str(uuid.uuid4())
        await redis.set(f"{prefix}:crash-event", crash_id)
        effect_count = int(await redis.get(f"{prefix}:effects:count"))
        await emit(redis, prefix, "crash-replay", event_id=crash_id)
        await wait_for(lambda: redis.exists(f"{prefix}:effect-committed"))
        assert (await redis.xpending(f"{prefix}:domain", "domain"))["pending"] == 1
        apis[leader_index][0].kill()
        await asyncio.to_thread(apis[leader_index][0].join, 3)
        await redis.delete(f"{prefix}:crash-event")
        assert await backpressure(sockets[follower_index]) == "WS_BACKPRESSURE"
        async def promoted():
            return await redis.get(f"{prefix}:leader-pid") == str(apis[follower_index][0].pid)
        await wait_for(promoted)
        assert await redis.get(f"{prefix}:collector-pid") == str(apis[follower_index][0].pid)
        async def drained():
            return (await redis.xpending(f"{prefix}:domain", "domain"))["pending"] == 0
        await wait_for(drained)
        assert int(await redis.get(f"{prefix}:effects:count")) == effect_count + 1
        await asyncio.sleep(0.2)
        replacement = await start()
        peers = [await subscribe(stack, apis[follower_index][1], token), await subscribe(stack, replacement[1], token)]
        await emit(redis, prefix, 15)
        assert [item["correlation_id"] for item in await asyncio.gather(*(frame(ws) for ws in peers))] == ["15"] * 2
        # Stale publisher cannot append under the successor's lease.
        before = await redis.xlen(settings.stream_key)
        with pytest.raises(asyncio.CancelledError):
            await publisher.publish(channel="topology", delivery_id="stale-leader", kwargs=args)
        assert await redis.xlen(settings.stream_key) <= max(before, 16)
        assert not await redis.exists(f"{prefix}:dlq")


async def test_live_lease_loss_terminates_old_leader_and_follower_recovers(isolated_runtime):
    redis, prefix, apis, _ = isolated_runtime
    token, _ = await identity(redis)
    old_leader = int(await redis.get(f"{prefix}:leader-pid"))
    leader = next(process for process, _ in apis if process.pid == old_leader)
    follower, port = next(pair for pair in apis if pair[0].pid != old_leader)
    async with AsyncExitStack() as stack:
        ws = await subscribe(stack, port, token)
        # Deliberately steal only this test's lease. Production renewal must exit(1).
        await redis.set(f"{prefix}:lease", "injected-owner", px=900)
        async def dead():
            return not leader.is_alive()
        await wait_for(dead)
        assert leader.exitcode == 1
        assert (await frame(ws))["data"]["code"] == "WS_BACKPRESSURE"
        async def promoted():
            return await redis.get(f"{prefix}:leader-pid") == str(follower.pid)
        await wait_for(promoted)
        await asyncio.sleep(0.2)
        ws = await subscribe(stack, port, token)
        await emit(redis, prefix, "fenced-recovery")
        assert (await frame(ws))["correlation_id"] == "fenced-recovery"
