"""Actual loopback HTTP → production FastAPI routes → isolated PostgreSQL/Redis.

Only DB/Redis providers are replaced. Authentication, permissions, tenant checks,
service/repository calls, envelopes and sockets are real. No frontend fixtures.
"""

import asyncio
import os
import secrets
import socket
import uuid
from datetime import UTC, datetime

import tests.conftest  # noqa: F401 - settings before app imports
import httpx
import pytest
import uvicorn
from redis.asyncio import Redis
from sqlalchemy import select

from app.core.dependencies import get_db, get_redis
from app.core.security import hash_password
from app.main import app
from app.modules.identity.repository import UserRepository
from app.modules.network.models import Network
from app.modules.network.outbox_models import NetworkOutbox
from app.modules.organization.models import Organization, OrgMember, Workspace
from scripts.test_audit_role_profiles import EXPECTED, sessions  # noqa: F401

pytestmark = pytest.mark.skipif(
    not (os.environ.get("AUDIT_TEST_DSN") and os.environ.get("AUDIT_HTTP_TEST_REDIS_URL")),
    reason="owned AUDIT_TEST_DSN and AUDIT_HTTP_TEST_REDIS_URL required for real HTTP smoke",
)


@pytest.fixture
async def http_server(sessions):  # noqa: F811
    redis = Redis.from_url(os.environ["AUDIT_HTTP_TEST_REDIS_URL"], decode_responses=True,
                           socket_connect_timeout=5, socket_timeout=10)
    await redis.ping()

    async def database():
        async with sessions() as db:
            yield db

    async def cache():
        yield redis

    saved = dict(app.dependency_overrides)
    app.dependency_overrides.update({get_db: database, get_redis: cache})
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(64)
    port = listener.getsockname()[1]
    # Background Neo4j/worker lifespan belongs to other acceptance lanes.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                            lifespan="off", access_log=False, log_level="critical"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("HTTP server exited before ready")
                await asyncio.sleep(.01)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
            yield client
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 10)
        finally:
            listener.close()
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved)
            await redis.aclose()


def body(response, status):
    assert response.status_code == status
    value = response.json()
    assert value["success"] == (status < 400)
    assert "meta" in value and "errors" in value
    return value["data"]


@pytest.mark.parametrize("role", EXPECTED)
async def test_http_login_roles_refresh_inventory_and_revocation(sessions, http_server, role):  # noqa: F811
    client = http_server
    password = secrets.token_urlsafe(24)
    org, workspace, foreign_org, foreign_workspace = (uuid.uuid4() for _ in range(4))
    async with sessions() as db:
        repo = UserRepository(db)
        user = await repo.create(f"{uuid.uuid4().hex}@example.com", hash_password(password))
        await repo.assign_role(user.user_id, role)
        for oid, wid in ((org, workspace), (foreign_org, foreign_workspace)):
            db.add(Organization(org_id=oid, name="HTTP fixture", slug=uuid.uuid4().hex))
            await db.flush()
            db.add(Workspace(workspace_id=wid, org_id=oid, name="HTTP workspace"))
        db.add(OrgMember(org_id=org, user_id=user.user_id,
                         org_role="Read-Only" if role == "Read-Only" else "Operator"))
        await db.flush()
        db.add_all([Network(network_id=uuid.uuid4(), workspace_id=workspace, name=f"HTTP inventory {i:02d}")
                    for i in range(21)])
        await db.commit()
        email, user_id = user.email, user.user_id

    body(await client.get("/api/v1/auth/me"), 401)
    tokens = body(await client.post("/api/v1/auth/login", json={"email": email, "password": password}), 200)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    profile = body(await client.get("/api/v1/auth/me", headers=headers), 200)
    assert profile["roles"] == [role] and set(profile["permissions"]) == EXPECTED[role]
    refreshed = body(await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}), 200)
    assert refreshed["refresh_token"] != tokens["refresh_token"]
    headers = {"Authorization": f"Bearer {refreshed['access_token']}"}
    assert set(body(await client.get("/api/v1/auth/me", headers=headers), 200)["permissions"]) == EXPECTED[role]
    pages = [body(await client.get("/api/v1/networks", params={"workspace_id": str(workspace), "page": page},
                                   headers=headers), 200) for page in (1, 2)]
    assert [len(page["items"]) for page in pages] == [20, 1]
    assert all(page["total"] == 21 for page in pages)
    body(await client.get("/api/v1/networks", params={"workspace_id": str(foreign_workspace)}, headers=headers), 403)
    created = body(await client.post("/api/v1/networks", headers=headers,
                        json={"workspace_id": str(workspace), "name": "HTTP-created"}),
                   403 if role == "Read-Only" else 201)
    async with sessions() as db:
        pending = (await db.scalars(select(NetworkOutbox))).all()
        assert len(pending) == (0 if role == "Read-Only" else 1)
        if created:
            assert await db.get(Network, uuid.UUID(created["network_id"])) is not None
            assert pending[0].envelope["event_type"] == "network.network.created"
        member = await db.get(OrgMember, (org, user_id))
        member.deleted_at = datetime.now(UTC)
        await db.commit()
    # Existing signed token cannot retain revoked tenant membership.
    body(await client.get("/api/v1/networks", params={"workspace_id": str(workspace)}, headers=headers), 403)
    body(await client.post("/api/v1/auth/logout", headers=headers), 200)
    body(await client.get("/api/v1/auth/me", headers=headers), 401)
    body(await client.post("/api/v1/auth/refresh", json={"refresh_token": refreshed["refresh_token"]}), 401)
