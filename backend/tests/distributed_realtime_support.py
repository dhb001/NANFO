"""Isolated real-socket harness; production JWT/session/RBAC, fixture owner reads.

No application routes or runtime configuration are modified. Redis is disposable.
Only SQL/graph owner-service reads are replaced with deterministic scoped fixtures.
"""

import asyncio
import json
import os
import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import uvicorn
from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis
from starlette.websockets import WebSocket

from app.core.logging import configure_logging
from app.events.bus import run_consumer_loop
from app.events.consumers.telemetry_consumer import _push_telemetry_delta
from app.events.consumers.ws_push_consumer import WS_PUSH_HANDLERS
from app.events.distributed_realtime import DistributedRealtime, fenced_handlers, require_leadership
from app.events.fanout_contract import FanoutSettings
from app.modules.identity.repository import UserRepository
from app.modules.network.service import NetworkService
from app.modules.organization.service import OrgService, WorkspaceService
from app.websocket import alerts, digital_twin, telemetry, topology
from app.websocket.delivery import DeliveryLimits
from app.websocket.manager import alerts_ws_manager, digital_twin_ws_manager, telemetry_ws_manager, topology_ws_manager

USER, ORG, WORKSPACE, NETWORK = (str(uuid.UUID(int=i)) for i in range(1, 5))


def run_api(sock, redis_url, prefix):
    configure_logging("ERROR")
    redis = Redis.from_url(redis_url, decode_responses=True)
    settings = FanoutSettings(
        stream_key=f"{prefix}:fanout", sequence_key=f"{prefix}:sequence", lease_key=f"{prefix}:lease",
        max_entries=16, heartbeat_seconds=0.1, stale_seconds=0.8, io_timeout_seconds=0.3,
        lease_ttl_seconds=1.5, retry_seconds=0.05, shutdown_seconds=0.5,
    )
    pid = os.getpid()
    managers = {"topology": topology_ws_manager, "telemetry": telemetry_ws_manager,
                "digital-twin": digital_twin_ws_manager, "alerts": alerts_ws_manager}
    for manager in managers.values():
        manager._delivery_limits = DeliveryLimits(max_pending=4, timeout_seconds=0.2)
        # Revocation assertions are immediate; the <=15 s cache is unit-tested (ADR-028 C1).
        manager._auth_cache_seconds = 0

    class ReaderRedis:
        """Deterministic missed-read injection without stopping the API process."""
        async def execute_command(self, *args, **kwargs):
            if args[0] == "XREAD" and await redis.exists(f"{prefix}:pause:{pid}"):
                await asyncio.Event().wait()
            return await redis.execute_command(*args, **kwargs)
        async def ping(self):
            return await redis.ping()

    async def effects(event):
        # Fixture owning transaction: effect + idempotency atomically committed.
        await redis.eval("""
        if redis.call('SADD', KEYS[1], ARGV[1]) == 1 then redis.call('INCR', KEYS[2]) end
        return 1
        """, 2, f"{prefix}:effects:ids", f"{prefix}:effects:count", event["event_id"])
        if await redis.get(f"{prefix}:crash-event") == event["event_id"]:
            await redis.set(f"{prefix}:effect-committed", "1")
            await asyncio.Event().wait()

    async def metric(event):
        await _push_telemetry_delta(event, event["payload"])

    @asynccontextmanager
    async def leader(lease):
        await redis.set(f"{prefix}:leader-pid", pid)
        try:
            await redis.xgroup_create(f"{prefix}:domain", "domain", id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        handlers = {name: [effects, handler] for name, handler in WS_PUSH_HANDLERS.items()}
        handlers["telemetry.metric.ingested"] = [effects, metric]
        async def collector():
            while True:
                await require_leadership(lease)
                await redis.set(f"{prefix}:collector-pid", pid)
                await asyncio.sleep(0.1)
        tasks = [asyncio.create_task(run_consumer_loop(
            redis, f"{prefix}:domain", "domain", str(pid), fenced_handlers(handlers, lease),
            reclaim_idle_ms=200, batch_size=1, dead_letter_key=f"{prefix}:dlq",
        )), asyncio.create_task(collector())]
        try:
            yield tasks
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def get_network(self, network_id, **kwargs):
        if str(network_id) != NETWORK:
            raise HTTPException(403)
        return SimpleNamespace(network_id=uuid.UUID(NETWORK), workspace_id=uuid.UUID(WORKSPACE))

    async def get_workspace(self, workspace_id, **kwargs):
        if str(workspace_id) != WORKSPACE or await redis.exists(f"{prefix}:membership-revoked"):
            raise HTTPException(403)
        return SimpleNamespace(workspace_id=uuid.UUID(WORKSPACE), org_id=uuid.UUID(ORG))

    async def permissions(self, roles):
        if await redis.exists(f"{prefix}:permission-revoked"):
            return []
        return ["read:topology", "read:telemetry"]

    original_send = WebSocket.send_text
    async def throttled_send(ws, message):
        frame = json.loads(message)
        if (frame.get("event") not in {"error", "subscribed"}
                and ws.query_params.get("token") == await redis.get(f"{prefix}:slow-token")):
            await asyncio.sleep(5)
        await original_send(ws, message)

    @asynccontextmanager
    async def lifespan(app):
        cm = AsyncMock()
        async with AsyncExitStack() as stack:
            for target in ("app.websocket.auth.get_redis_client", "app.websocket.manager.get_redis_client",
                           "app.events.consumers.ws_push_consumer.get_redis_client"):
                stack.enter_context(patch(target, return_value=redis))
            stack.enter_context(patch("app.websocket.auth.AsyncSessionLocal", return_value=cm))
            stack.enter_context(patch.object(UserRepository, "get_by_id", AsyncMock(return_value=SimpleNamespace(
                user_id=uuid.UUID(USER), email="socket@example.com", is_active=True))))
            stack.enter_context(patch.object(UserRepository, "get_roles_for_user", AsyncMock(return_value=["Read-Only"])))
            stack.enter_context(patch.object(UserRepository, "get_permissions_for_roles", permissions))
            stack.enter_context(patch.object(NetworkService, "assert_network_workspace_access", get_network))
            stack.enter_context(patch.object(WorkspaceService, "get_active_workspace", get_workspace))
            stack.enter_context(patch.object(OrgService, "get_org", AsyncMock(return_value=SimpleNamespace(org_id=uuid.UUID(ORG)))))
            stack.enter_context(patch.object(WebSocket, "send_text", throttled_send))
            runtime = DistributedRealtime(redis, leader_factory=leader, settings=settings, managers=managers)
            runtime.subscriber.redis = ReaderRedis()
            await stack.enter_async_context(runtime)
            await redis.set(f"{prefix}:ready:{pid}", "1")
            yield
            await redis.delete(f"{prefix}:ready:{pid}")
        await redis.aclose()

    app = FastAPI(lifespan=lifespan)
    for module in (topology, telemetry, digital_twin, alerts):
        app.include_router(module.router)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on", timeout_graceful_shutdown=1))
    server.run(sockets=[sock])
