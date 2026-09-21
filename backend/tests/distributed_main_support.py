"""Spawn actual app.main; fixture SQL owner reads, real Redis/Neo4j/auth/lifespan."""

import asyncio
import os
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import uvicorn
from fastapi import HTTPException

from tests.distributed_realtime_support import NETWORK, ORG, USER, WORKSPACE


def run_main_api(sock, environment):
    os.environ.update(environment)
    from app.core.config import get_settings
    get_settings.cache_clear()
    import app.main as main
    from app.core.runtime_health import SCHEMA_HEAD
    from app.db.redis import get_redis_client
    from app.modules.identity.repository import AuditLogRepository, UserRepository
    from app.modules.network.service import NetworkService
    from app.modules.organization.service import OrgService, WorkspaceService

    # Only SQL boundaries have fixture implementations. Graph projection/backfill,
    # Redis, readiness probes, collectors, consumers and socket auth execute normally.
    db = AsyncMock()
    async def execute(statement, *args, **kwargs):
        result = MagicMock()
        result.scalar_one.return_value = 1
        result.scalars.return_value.all.return_value = [SCHEMA_HEAD]
        return result
    db.execute.side_effect = execute
    cm = AsyncMock()
    cm.__aenter__.return_value = db

    async def get_network(self, network_id, **kwargs):
        if str(network_id) != NETWORK:
            raise HTTPException(403)
        return SimpleNamespace(network_id=uuid.UUID(NETWORK), workspace_id=uuid.UUID(WORKSPACE))

    async def get_workspace(self, workspace_id, **kwargs):
        if str(workspace_id) != WORKSPACE:
            raise HTTPException(403)
        return SimpleNamespace(workspace_id=uuid.UUID(WORKSPACE), org_id=uuid.UUID(ORG))

    async def append(self, **kwargs):
        await get_redis_client().sadd("acceptance:audit-events", str(kwargs["event_id"]))

    # Administrative failure injection only: do not replace startup or routing.
    async def failures():
        while True:
            await asyncio.sleep(0.05)
            redis = get_redis_client()
            command = await redis.getdel(f"acceptance:fail:{os.getpid()}")
            if command == "consumer" and main.app.state.consumer_tasks:
                main.app.state.consumer_tasks[0].cancel()
            elif command == "collector" and main.app.state.telemetry_collector:
                main.app.state.telemetry_collector._runtime_exhausted_streak = 1
    class Server(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                self.failure_task = asyncio.create_task(failures())
        async def shutdown(self, sockets=None):
            if hasattr(self, "failure_task"):
                self.failure_task.cancel()
                await asyncio.gather(self.failure_task, return_exceptions=True)
            await super().shutdown(sockets=sockets)

    with ExitStack() as stack:
        for target in ("app.main.AsyncSessionLocal", "app.api.readiness.AsyncSessionLocal",
                       "app.websocket.auth.AsyncSessionLocal", "app.events.consumers.audit_consumer.AsyncSessionLocal"):
            stack.enter_context(patch(target, return_value=cm))
        stack.enter_context(patch.object(UserRepository, "get_by_id", AsyncMock(return_value=SimpleNamespace(
            user_id=uuid.UUID(USER), email="socket@example.com", is_active=True))))
        stack.enter_context(patch.object(UserRepository, "get_roles_for_user", AsyncMock(return_value=["Read-Only"])))
        stack.enter_context(patch.object(UserRepository, "get_permissions_for_roles", AsyncMock(return_value=["read:topology", "read:telemetry"])))
        stack.enter_context(patch.object(NetworkService, "assert_network_workspace_access", get_network))
        stack.enter_context(patch.object(WorkspaceService, "get_active_workspace", get_workspace))
        stack.enter_context(patch.object(OrgService, "get_org", AsyncMock(return_value=SimpleNamespace(org_id=uuid.UUID(ORG)))))
        stack.enter_context(patch.object(AuditLogRepository, "append", append))
        Server(uvicorn.Config(main.app, log_level="error", lifespan="on", timeout_graceful_shutdown=1)).run(sockets=[sock])
