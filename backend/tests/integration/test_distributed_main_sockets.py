"""Actual app.main two-process acceptance; disposable Redis + Neo4j, fixture SQL."""

import asyncio
import json
import multiprocessing
import os
import socket
import subprocess
import uuid
from contextlib import AsyncExitStack
from datetime import UTC, datetime

import httpx
import pytest
from neo4j import AsyncGraphDatabase
from redis.asyncio import Redis

from app.events.realtime import API_REALTIME_LEASE_KEY
from app.modules.identity.sessions import SessionRepository
from tests.distributed_main_support import run_main_api
from tests.distributed_realtime_support import NETWORK, WORKSPACE
from tests.integration.test_distributed_realtime_sockets import REDIS_IMAGE, frame, identity, subscribe, wait_for

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DISTRIBUTED_REALTIME") != "1", reason="isolated Docker acceptance opt-in")
NEO4J_IMAGE = "sha256:9f75e8df4325a24f00fdd7a8c0bcce650a58375049b1058e496e8b43d6c36b37"


@pytest.fixture
async def main_cluster(tmp_path):
    prefix = f"nanfo-realtime-main-{uuid.uuid4().hex}"
    containers, processes, sockets = [], [], []
    password = uuid.uuid4().hex
    redis = driver = None
    def container(suffix, port, image, options, command=()):
        name = f"{prefix}-{suffix}"
        subprocess.run(["docker", "run", "-d", "--rm", "--pull=never", "--name", name,
                        "-p", f"127.0.0.1::{port}", *options, image, *command], check=True, capture_output=True)
        containers.append(name)
        return subprocess.check_output(["docker", "port", name, f"{port}/tcp"], text=True).strip().rsplit(":", 1)[1]
    try:
        redis_port = container("redis", 6379, REDIS_IMAGE, [], ["redis-server", "--save", "", "--appendonly", "no", "--requirepass", password])
        neo_port = container("neo4j", 7687, NEO4J_IMAGE, [
            "-e", f"NEO4J_AUTH=neo4j/{password}", "-e", "NEO4J_server_memory_heap_initial__size=128m",
            "-e", "NEO4J_server_memory_heap_max__size=256m", "-e", "NEO4J_server_memory_pagecache_size=64m",
        ])
        redis = Redis(host="127.0.0.1", port=int(redis_port), password=password, decode_responses=True)
        driver = AsyncGraphDatabase.driver(f"bolt://127.0.0.1:{neo_port}", auth=("neo4j", password))
        async def available():
            try:
                await redis.ping()
                await driver.verify_connectivity()
                return True
            except Exception:
                await asyncio.sleep(0.5)
                return False
        await wait_for(available, 90)
        environment = {
            "REDIS_HOST": "127.0.0.1", "REDIS_PORT": redis_port, "REDIS_DB": "0", "REDIS_PASSWORD": password,
            "NEO4J_URI": f"bolt://127.0.0.1:{neo_port}", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": password,
            "API_REALTIME_DISTRIBUTED": "true", "API_REALTIME_LEASE_TTL_SECONDS": "3",
            "API_REALTIME_FANOUT_HEARTBEAT_SECONDS": "0.2", "API_REALTIME_FANOUT_IO_TIMEOUT_SECONDS": "0.3",
            "API_REALTIME_FANOUT_STALE_SECONDS": "1.5", "API_REALTIME_FANOUT_RETRY_SECONDS": "0.1",
            "API_REALTIME_COLLECTOR_WATCHDOG_SECONDS": "0.1", "TELEMETRY_FLEET_ENABLED": "false",
            "TELEMETRY_RUNTIME_ADAPTER_MODE": "stub", "REPORTS_STORAGE_PATH": str(tmp_path),
            "EVENT_RECLAIM_IDLE_MS": "1000", "LOG_LEVEL": "ERROR",
            # Immediate revocation assertions below; the <=15 s cache is unit-tested (C1).
            "WS_AUTH_CACHE_SECONDS": "0",
        }
        async def start():
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sock.listen(128)
            sockets.append(sock)
            process = multiprocessing.get_context("spawn").Process(target=run_main_api, args=(sock, environment))
            process.start()
            processes.append(process)
            port = sock.getsockname()[1]
            async def ready():
                async with httpx.AsyncClient() as client:
                    try:
                        return (await client.get(f"http://127.0.0.1:{port}/ready")).status_code == 200
                    except httpx.HTTPError:
                        return False
            await wait_for(ready, 20)
            return process, port
        apis = [await start(), await start()]
        yield redis, driver, apis, start
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            await asyncio.to_thread(process.join, 8)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join, 4)
            assert not process.is_alive()
            process.close()
        for sock in sockets:
            sock.close()
        if driver:
            await driver.close()
        if redis:
            await redis.aclose()
        for name in reversed(containers):
            subprocess.run(["docker", "rm", "-fv", name], check=True, capture_output=True)
            assert not subprocess.check_output(["docker", "ps", "-aq", "--filter", f"name=^{name}$"], text=True).strip()


async def test_actual_main_leader_follower_restart_and_auth(main_cluster):
    redis, driver, apis, start = main_cluster
    async def status(port):
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://127.0.0.1:{port}/ready")
            return response.status_code, response.json()["data"]
    statuses = [await status(port) for _, port in apis]
    assert [code for code, _ in statuses] == [200, 200]
    roles = [data["realtime"]["role"] for _, data in statuses]
    assert sorted(roles) == ["follower", "leader"]
    leader_index, follower_index = roles.index("leader"), roles.index("follower")
    leader_data, follower_data = statuses[leader_index][1], statuses[follower_index][1]
    assert leader_data["realtime"]["local_collector"] is True
    assert leader_data["realtime"]["local_consumer_count"] == 9
    assert follower_data["realtime"]["local_collector"] is False
    assert follower_data["realtime"]["local_consumer_count"] == 0
    assert follower_data["checks"]["api_consumers"] == "delegated"
    assert all(data["checks"]["neo4j"] == "ok" and data["checks"]["schema"] == "ok" for _, data in statuses)
    token, sid = await identity(redis)
    device = str(uuid.uuid4())
    async def publish(index):
        event_id = str(uuid.uuid4())
        await redis.xadd("stream:network", {
            "event_id": event_id, "event_type": "network.device.added", "source": "network",
            "timestamp": datetime.now(UTC).isoformat(), "correlation_id": str(uuid.uuid4()),
            "payload": json.dumps({"network_id": NETWORK, "workspace_id": WORKSPACE,
                                   "device_id": device, "hostname": str(index), "device_type": "router"}),
        })
        return event_id
    async with AsyncExitStack() as stack:
        peers = [await subscribe(stack, port, token) for _, port in apis]
        event_id = await publish(1)
        assert [(await frame(ws))["data"]["node"]["hostname"] for ws in peers] == ["1", "1"]
        assert await redis.sismember("acceptance:audit-events", event_id)
        async with driver.session() as session:
            row = await (await session.run("MATCH (d:Device {device_id:$id}) RETURN count(d) AS n", id=device)).single()
            assert row["n"] == 1
        # Historical oversized event already accepted before request bounds:
        # quarantine/reset must finish it without cancelling/re-electing leadership.
        old_epoch = await redis.get(API_REALTIME_LEASE_KEY)
        poison_id = await publish("x" * 300000)
        assert [(await frame(ws))["data"]["code"] for ws in peers] == ["WS_BACKPRESSURE"] * 2
        async def poison_acknowledged():
            return (await redis.xpending("stream:network", "nanfo-consumers"))["pending"] == 0
        await wait_for(poison_acknowledged)
        assert await redis.get(API_REALTIME_LEASE_KEY) == old_epoch
        receipts = await redis.xrange("nanfo:{realtime}:v1:fanout:quarantine")
        assert len(receipts) == 1 and len(receipts[0][1]["receipt"]) < 512
        assert poison_id not in receipts[0][1]["receipt"]  # Diagnostic identity is hashed.
        await asyncio.sleep(0.3)
        peers = [await subscribe(stack, port, token) for _, port in apis]
        await publish("after-poison")
        assert [(await frame(ws))["data"]["node"]["hostname"] for ws in peers] == ["after-poison"] * 2
        # Longer than reclaim interval: poison stays complete and lease stays put.
        await asyncio.sleep(1.1)
        assert await redis.get(API_REALTIME_LEASE_KEY) == old_epoch
        assert await redis.xlen("nanfo:{realtime}:v1:fanout:quarantine") == 1
        await SessionRepository(redis).revoke(sid)
        await publish(2)
        assert [(await frame(ws))["data"]["code"] for ws in peers] == ["WS_UNAUTHORIZED"] * 2
        # Failure of actual app consumer and actual collector each renews lifecycle.
        for failure in ("consumer", "collector"):
            statuses = [await status(port) for _, port in apis]
            leader_index = next(i for i, (_, data) in enumerate(statuses) if data["realtime"]["role"] == "leader")
            old_epoch = await redis.get(API_REALTIME_LEASE_KEY)
            await redis.set(f"acceptance:fail:{apis[leader_index][0].pid}", failure)
            async def reacquired():
                epoch = await redis.get(API_REALTIME_LEASE_KEY)
                return epoch is not None and epoch != old_epoch and all([
                    (await status(port))[0] == 200 for _, port in apis
                ])
            await wait_for(reacquired, 15)
        statuses = [await status(port) for _, port in apis]
        leader_index = next(i for i, (_, data) in enumerate(statuses) if data["realtime"]["role"] == "leader")
        follower_index = 1 - leader_index
        apis[leader_index][0].kill()
        await asyncio.to_thread(apis[leader_index][0].join, 3)
        async def promoted():
            code, data = await status(apis[follower_index][1])
            return code == 200 and data["realtime"]["role"] == "leader"
        await wait_for(promoted, 15)
        replacement = await start()
        assert (await status(replacement[1]))[1]["realtime"]["role"] == "follower"
        token, _ = await identity(redis)
        peers = [await subscribe(stack, port, token) for port in (apis[follower_index][1], replacement[1])]
        await publish(3)
        assert [(await frame(ws))["data"]["node"]["hostname"] for ws in peers] == ["3"] * 2
        assert await redis.xlen("stream:dead_letter") == 0
