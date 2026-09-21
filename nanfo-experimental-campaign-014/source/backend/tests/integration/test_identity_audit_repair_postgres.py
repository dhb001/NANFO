"""ADR-026 real transactions. IDENTITY_TEST_DSN must name a disposable PostgreSQL.

Every test owns/migrates/drops a unique schema. Only Redis publication is faked;
Organization, Identity, locks, constraints and audit consumer use actual SQL.
"""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import httpx
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.events.consumers import audit_consumer
from app.api.v1.organizations import router as organization_router
from app.core.dependencies import get_db, get_redis
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.modules.identity.models import Role, User, UserRole
from app.modules.identity.repository import AuditLogRepository
from app.modules.identity.sessions import SessionRepository
from app.modules.network.schemas import CreateNetworkRequest
from app.modules.network.repository import NetworkRepository
from app.modules.network.service import NetworkService
from app.modules.organization.models import Organization, OrgMember
from app.modules.organization.repository import OrganizationRepository
from app.modules.organization.schemas import CreateOrgRequest, CreateWorkspaceRequest
from app.modules.organization.service import MemberService, OrgService, WorkspaceService

pytestmark = pytest.mark.skipif(not os.environ.get("IDENTITY_TEST_DSN"), reason="IDENTITY_TEST_DSN not configured")
ACTOR, TARGET, OTHER = (uuid.UUID(int=i) for i in (101, 102, 103))
CORRELATION = str(uuid.UUID(int=201))


@pytest.fixture
async def sessions():
    schema = "identity_repair_" + uuid.uuid4().hex
    url = make_url(os.environ["IDENTITY_TEST_DSN"])
    sync = create_engine(url.set(drivername="postgresql+psycopg2"))
    engine = None
    with sync.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
        scripts = ScriptDirectory.from_config(config)
        with sync.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            with EnvironmentContext(config, scripts, fn=lambda rev, _: scripts._upgrade_revs("head", rev)) as context:
                context.configure(connection=connection)
                context.run_migrations()
        engine = create_async_engine(url.set(drivername="postgresql+asyncpg"),
                                     connect_args={"server_settings": {"search_path": schema}})
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if engine:
            await engine.dispose()
        with sync.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        sync.dispose()


@pytest.fixture
async def org(sessions, fake_redis):
    async with sessions() as db:
        for user_id in (ACTOR, TARGET, OTHER):
            db.add(User(user_id=user_id, email=f"{user_id}@example.invalid", hashed_password="not-a-login"))
        await db.flush()
        role_id = await db.scalar(select(Role.role_id).where(Role.name == "Operator"))
        for user_id in (ACTOR, TARGET, OTHER):
            db.add(UserRole(user_id=user_id, role_id=role_id))
        await db.commit()
        return await OrgService(db, fake_redis).create_org(
            CreateOrgRequest(name="Repair fixture", slug="repair-fixture"), str(ACTOR), CORRELATION,
        )


async def add(sessions, redis, org_id, target=TARGET, actor=ACTOR, role="Operator"):
    async with sessions() as db:
        return await MemberService(db, redis).add_member(org_id, target, role, str(actor), str(actor), CORRELATION)


async def remove(sessions, redis, org_id, target=TARGET, actor=ACTOR):
    async with sessions() as db:
        await MemberService(db, redis).remove_member(org_id, target, str(actor), str(actor), CORRELATION)


async def test_restore_role_original_row_atomic_audit_and_consumer_replay(sessions, fake_redis, org, monkeypatch):
    original = await add(sessions, fake_redis, org.org_id)
    await remove(sessions, fake_redis, org.org_id)
    restored = await add(sessions, fake_redis, org.org_id, role="Read-Only")
    assert restored.created_at == original.created_at
    assert restored.org_role == "Read-Only"
    monkeypatch.setattr(audit_consumer, "AsyncSessionLocal", sessions)
    for _, envelope in await fake_redis.xrange("stream:org"):
        event = {**envelope, "payload": json.loads(envelope["payload"])}
        await audit_consumer.handle_audit_event(event)
        await audit_consumer.handle_audit_event(event)
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(OrgMember)) == 2
        logs, total = await AuditLogRepository(db).list_entries(org_id=org.org_id)
        assert total == 4
        member_logs = [log for log in logs if log.resource_type == "org_member"]
        assert len(member_logs) == 3
        assert all(log.actor_id == ACTOR and log.resource_id == TARGET for log in member_logs)
        assert sum(log.metadata_.get("restored", False) for log in member_logs) == 1
        assert len({log.event_id for log in logs}) == 4


async def test_concurrent_restore_one_success_one_friendly_conflict(sessions, fake_redis, org):
    await add(sessions, fake_redis, org.org_id)
    await remove(sessions, fake_redis, org.org_id)
    results = await asyncio.gather(*[add(sessions, fake_redis, org.org_id) for _ in range(2)], return_exceptions=True)
    assert sum(not isinstance(item, Exception) for item in results) == 1
    errors = [item for item in results if isinstance(item, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], HTTPException) and errors[0].status_code == 409


async def test_revocation_winning_lock_denies_waiting_restore_with_stale_identity_map(sessions, fake_redis, org):
    await add(sessions, fake_redis, org.org_id, target=OTHER, role="Admin")
    await add(sessions, fake_redis, org.org_id)
    await remove(sessions, fake_redis, org.org_id)
    async with sessions() as revoker, sessions() as restorer:
        stale = await restorer.get(OrgMember, (org.org_id, ACTOR))
        assert stale.deleted_at is None
        await OrganizationRepository(revoker).lock(org.org_id)
        task = asyncio.create_task(MemberService(restorer, fake_redis).add_member(
            org.org_id, TARGET, "Operator", str(ACTOR), str(ACTOR), CORRELATION,
        ))
        await asyncio.sleep(0.05)
        assert not task.done()
        await MemberService(revoker, fake_redis).remove_member(
            org.org_id, ACTOR, str(OTHER), str(OTHER), CORRELATION,
        )
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(task, 3)
        assert error.value.status_code == 403
    async with sessions() as db:
        assert (await db.get(OrgMember, (org.org_id, TARGET))).deleted_at is not None


async def test_publication_failure_keeps_audit_and_audit_failure_rolls_back_mutation(sessions, fake_redis, org, monkeypatch):
    monkeypatch.setattr("app.modules.organization.service.publish_event", AsyncMock(side_effect=RuntimeError("offline")))
    await add(sessions, fake_redis, org.org_id)
    async with sessions() as db:
        logs, total = await AuditLogRepository(db).list_entries(org_id=org.org_id, resource_type="org_member")
        assert total == 1 and logs[0].resource_id == TARGET
    monkeypatch.setattr("app.modules.organization.service.append_audit_log", AsyncMock(side_effect=RuntimeError("audit failed")))
    with pytest.raises(RuntimeError, match="audit failed"):
        await add(sessions, fake_redis, org.org_id, target=OTHER)
    async with sessions() as db:
        assert await db.get(OrgMember, (org.org_id, OTHER)) is None


async def test_deleted_slug_reserved_and_concurrent_slug_creation(sessions, fake_redis, org):
    async with sessions() as db:
        await OrgService(db, fake_redis).delete_org(org_id=org.org_id, user_id=str(ACTOR), actor_id=str(ACTOR), correlation_id=CORRELATION)
        with pytest.raises(HTTPException) as error:
            await OrgService(db, fake_redis).create_org(CreateOrgRequest(name="Reuse", slug=org.slug), str(ACTOR), CORRELATION)
        assert error.value.status_code == 409 and error.value.detail["code"] == "ORG_SLUG_CONFLICT"

    async def create():
        async with sessions() as db:
            return await OrgService(db, fake_redis).create_org(CreateOrgRequest(name="Concurrent", slug="concurrent"), str(ACTOR), CORRELATION)

    results = await asyncio.gather(create(), create(), return_exceptions=True)
    assert sum(not isinstance(item, Exception) for item in results) == 1
    errors = [item for item in results if isinstance(item, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], HTTPException) and errors[0].status_code == 409


async def test_last_admin_and_descendant_deletion_guards(sessions, fake_redis, org):
    with pytest.raises(HTTPException) as error:
        await remove(sessions, fake_redis, org.org_id, target=ACTOR)
    assert error.value.detail["code"] == "ORG_LAST_ADMIN"
    async with sessions() as db:
        ws = await WorkspaceService(db, fake_redis).create_workspace(
            org.org_id, CreateWorkspaceRequest(name="Child"), str(ACTOR), str(ACTOR), CORRELATION,
        )
        with pytest.raises(HTTPException) as error:
            await OrgService(db, fake_redis).delete_org(org_id=org.org_id, user_id=str(ACTOR), actor_id=str(ACTOR), correlation_id=CORRELATION)
        assert error.value.detail["code"] == "ORG_HAS_WORKSPACES"
        await db.rollback()
        await WorkspaceService(db, fake_redis).delete_workspace(
            org_id=org.org_id, workspace_id=ws.workspace_id, actor_id=str(ACTOR), user_id=str(ACTOR), correlation_id=CORRELATION,
        )
        await OrgService(db, fake_redis).delete_org(org_id=org.org_id, user_id=str(ACTOR), actor_id=str(ACTOR), correlation_id=CORRELATION)


async def test_audit_search_scoping_filters_and_deterministic_ties(sessions, fake_redis, org):
    await add(sessions, fake_redis, org.org_id)
    async with sessions() as db:
        other_org = await OrgService(db, fake_redis).create_org(CreateOrgRequest(name="Other", slug="other"), str(ACTOR), CORRELATION)
        repo = AuditLogRepository(db)
        logs, count = await repo.list_entries(org_id=org.org_id, search=str(TARGET), actor_id=ACTOR, resource_type="org_member")
        assert count == 1 and logs[0].resource_id == TARGET
        assert (await repo.list_entries(org_id=other_org.org_id, search=str(TARGET)))[1] == 0
        assert (await repo.list_entries(org_id=org.org_id, search="%"))[1] == 0
        assert (await repo.list_entries(org_id=org.org_id, search="ORG.MEMBER"))[1] == 1
        first, _ = await repo.list_entries(org_id=org.org_id, page_size=1)
        second, _ = await repo.list_entries(org_id=org.org_id, page=2, page_size=1)
        assert first[0].log_id != second[0].log_id


async def test_organization_list_order_when_creation_times_tie(sessions, fake_redis, org):
    async with sessions() as db:
        fixed = datetime(2026, 1, 1, tzinfo=UTC)
        for number in (305, 301, 303):
            db.add(Organization(org_id=uuid.UUID(int=number), name="Tie", slug=f"tie-{number}", created_at=fixed))
        await db.flush()
        for number in (305, 301, 303):
            db.add(OrgMember(org_id=uuid.UUID(int=number), user_id=ACTOR, org_role="Admin"))
        await db.commit()
        repo = OrganizationRepository(db)
        first, total = await repo.list_for_user(ACTOR, page=1, page_size=2)
        second, _ = await repo.list_for_user(ACTOR, page=2, page_size=2)
        assert total == 4
        assert [item.org_id.int for item in first + second][:3] == [301, 303, 305]


async def test_last_admin_requires_another_usable_identity_capability(sessions, fake_redis, org):
    await add(sessions, fake_redis, org.org_id, target=OTHER, role="Admin")
    async with sessions() as db:
        await db.execute(delete(UserRole).where(UserRole.user_id == OTHER))
        role_id = await db.scalar(select(Role.role_id).where(Role.name == "Read-Only"))
        db.add(UserRole(user_id=OTHER, role_id=role_id))
        await db.commit()
    with pytest.raises(HTTPException) as error:
        await remove(sessions, fake_redis, org.org_id, target=ACTOR)
    assert error.value.detail["code"] == "ORG_LAST_ADMIN"


async def test_workspace_deletion_rejects_active_network_and_clears_description(sessions, fake_redis, org):
    async with sessions() as db:
        ws = await WorkspaceService(db, fake_redis).create_workspace(
            org.org_id, CreateWorkspaceRequest(name="Child", description="Old"), str(ACTOR), str(ACTOR), CORRELATION,
        )
        updated = await WorkspaceService(db, fake_redis).update_workspace(
            org_id=org.org_id, workspace_id=ws.workspace_id, name=None, description=None,
            description_provided=True, actor_id=str(ACTOR), user_id=str(ACTOR), correlation_id=CORRELATION,
        )
        assert updated.description is None
        await NetworkService(db, fake_redis).create_network(
            CreateNetworkRequest(workspace_id=ws.workspace_id, name="Inventory"), str(ACTOR), CORRELATION,
        )
        with pytest.raises(HTTPException) as error:
            await WorkspaceService(db, fake_redis).delete_workspace(
                org_id=org.org_id, workspace_id=ws.workspace_id, actor_id=str(ACTOR), user_id=str(ACTOR), correlation_id=CORRELATION,
            )
        assert error.value.detail["code"] == "WORKSPACE_HAS_NETWORKS"


async def test_historical_unscoped_audit_replay_never_rewrites_evidence(sessions, org, monkeypatch):
    event_id = uuid.UUID(int=900)
    original_payload = {"user_id": str(TARGET), "actor_id": str(ACTOR)}
    async with sessions() as db:
        await AuditLogRepository(db).append(
            event_id=event_id, event_type="org.member.added", actor_id=TARGET,
            resource_id=org.org_id, resource_type="org_member", correlation_id=uuid.UUID(CORRELATION),
            metadata=original_payload,
        )
        await db.commit()
    monkeypatch.setattr(audit_consumer, "AsyncSessionLocal", sessions)
    await audit_consumer.handle_audit_event({
        "event_id": str(event_id), "event_type": "org.member.added", "correlation_id": CORRELATION,
        "payload": {**original_payload, "org_id": str(org.org_id)},
    })
    async with sessions() as db:
        logs, total = await AuditLogRepository(db).list_entries(resource_type="org_member")
        assert total == 1
        assert logs[0].actor_id == TARGET and logs[0].org_id is None
        assert logs[0].metadata_ == original_payload


async def wait_for_lock(sessions, pid):
    async with sessions() as observer:
        async with asyncio.timeout(5):
            while not await observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}):
                await asyncio.sleep(0.01)


async def test_opaque_request_header_endpoints_atomic_audit_and_replay(sessions, fake_redis, org, monkeypatch):
    """Actual headers, auth, routers, services, transactions and consumer; no DB doubles."""
    app = FastAPI()
    app.include_router(organization_router)

    async def database():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_redis] = lambda: fake_redis
    sid = str(uuid.uuid4())
    refresh, _ = create_refresh_token(user_id=str(ACTOR), sid=sid)
    await SessionRepository(fake_redis).create(decode_token(refresh, token_type="refresh"), refresh)
    token, _ = create_access_token(user_id=str(ACTOR), email=f"{ACTOR}@example.invalid",
                                   roles=["Operator"], permissions=["write:config"], sid=sid)
    request_id = "req_8f92a1b4"
    headers = {"Authorization": f"Bearer {token}", "X-Request-ID": request_id}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers) as client:
        created = await client.post("/api/v1/organizations", json={"name": "Header", "slug": "header"})
        assert created.status_code == 201, created.text
        org_id = uuid.UUID(created.json()["data"]["org_id"])
        updated = await client.patch(f"/api/v1/organizations/{org_id}", json={"name": "Updated"})
        added = await client.post(f"/api/v1/organizations/{org_id}/members", json={"user_id": str(TARGET), "org_role": "Operator"})
        assert updated.status_code == 200, updated.text
        assert added.status_code == 201, added.text
        for response in (created, updated, added):
            assert response.json()["meta"]["request_id"] == request_id

    expected = uuid.uuid5(uuid.NAMESPACE_URL, f"nanfo:audit-correlation:{request_id}")
    async with sessions() as db:
        logs, total = await AuditLogRepository(db).list_entries(org_id=org_id)
        assert total == 3
        assert all(log.correlation_id == expected and log.metadata_["request_id"] == request_id for log in logs)
        original = {log.event_id: (log.log_id, log.correlation_id, log.metadata_) for log in logs}
        assert (await db.get(Organization, org_id)).name == "Updated"
        assert (await db.get(OrgMember, (org_id, TARGET))).org_role == "Operator"

    monkeypatch.setattr(audit_consumer, "AsyncSessionLocal", sessions)
    events = []
    for _, envelope in await fake_redis.xrange("stream:org"):
        if envelope["correlation_id"] != request_id:
            continue
        event = {**envelope, "payload": json.loads(envelope["payload"])}
        events.append(event)
        assert uuid.UUID(event["event_id"]) in original
        await audit_consumer.handle_audit_event(event)
        await audit_consumer.handle_audit_event(event)
    assert len(events) == 3
    async with sessions() as db:
        logs, total = await AuditLogRepository(db).list_entries(org_id=org_id)
        assert total == 3
        assert {log.event_id: (log.log_id, log.correlation_id, log.metadata_) for log in logs} == original

    # Consumer-only delivery must independently derive the same correlation and metadata.
    consumer_event = {**events[0], "event_id": str(uuid.uuid4())}
    await audit_consumer.handle_audit_event(consumer_event)
    async with sessions() as db:
        logs, total = await AuditLogRepository(db).list_entries(org_id=org_id)
        assert total == 4
        delivered = next(log for log in logs if str(log.event_id) == consumer_event["event_id"])
        assert (delivered.correlation_id, delivered.metadata_) == original[uuid.UUID(events[0]["event_id"])][1:]

    # A failed audit still rolls back an opaque-correlated mutation.
    monkeypatch.setattr("app.modules.organization.service.append_audit_log", AsyncMock(side_effect=RuntimeError("audit failed")))
    async with sessions() as db:
        with pytest.raises(RuntimeError, match="audit failed"):
            await OrgService(db, fake_redis).update_org(org_id=org_id, user_id=str(ACTOR), name="Must roll back",
                                                       actor_id=str(ACTOR), correlation_id=request_id)
    async with sessions() as db:
        assert (await db.get(Organization, org_id)).name == "Updated"


async def workspace_fixture(sessions, redis, org_id):
    async with sessions() as db:
        return await WorkspaceService(db, redis).create_workspace(
            org_id, CreateWorkspaceRequest(name="Lock fixture"), str(ACTOR), str(ACTOR), CORRELATION,
        )


async def test_observer_read_does_not_wait_on_queued_revoker_and_sees_committed_revocation(sessions, fake_redis, org):
    await add(sessions, fake_redis, org.org_id, target=OTHER, role="Admin")
    ws = await workspace_fixture(sessions, fake_redis, org.org_id)
    async with sessions() as writer, sessions() as revoker, sessions() as observer:
        await WorkspaceService(writer, fake_redis).get_active_workspace(ws.workspace_id, user_id=str(ACTOR), require_write=True)
        pid = await revoker.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(MemberService(revoker, fake_redis).remove_member(
            org.org_id, ACTOR, str(OTHER), str(OTHER), CORRELATION,
        ))
        try:
            await wait_for_lock(sessions, pid)
            service = WorkspaceService(observer, fake_redis)
            retained = await asyncio.wait_for(service.check_workspace_write_authority(ws.workspace_id, user_id=str(ACTOR)), 2)
            assert retained.org_id == org.org_id
            await writer.commit()
            await asyncio.wait_for(task, 3)
            with pytest.raises(HTTPException) as error:
                await service.check_workspace_write_authority(ws.workspace_id, user_id=str(ACTOR))
            assert error.value.status_code == 403
        finally:
            await writer.rollback()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_parent_delete_fence_denies_inventory_creation_during_and_after_delete(sessions, fake_redis, org):
    ws = await workspace_fixture(sessions, fake_redis, org.org_id)
    async with sessions() as deleter, sessions() as writer:
        await OrganizationRepository(deleter).lock(org.org_id)
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(NetworkService(writer, fake_redis).create_network(
                CreateNetworkRequest(workspace_id=ws.workspace_id, name="Blocked"), str(ACTOR), CORRELATION,
            ), 2)
        assert error.value.detail["code"] == "ORG_AUTHORITY_BUSY"
        await writer.rollback()
        await WorkspaceService(deleter, fake_redis).delete_workspace(
            org_id=org.org_id, workspace_id=ws.workspace_id, actor_id=str(ACTOR), user_id=str(ACTOR), correlation_id=CORRELATION,
        )
        with pytest.raises(HTTPException) as error:
            await NetworkService(writer, fake_redis).create_network(
                CreateNetworkRequest(workspace_id=ws.workspace_id, name="Deleted"), str(ACTOR), CORRELATION,
            )
        assert error.value.status_code == 404


@pytest.mark.parametrize("queued_admin", [False, True])
async def test_inverse_asset_inventory_parent_order_finishes_without_deadlock(sessions, fake_redis, org, queued_admin):
    ws = await workspace_fixture(sessions, fake_redis, org.org_id)
    async with sessions() as db:
        network = await NetworkService(db, fake_redis).create_network(
            CreateNetworkRequest(workspace_id=ws.workspace_id, name="Lock order"), str(ACTOR), CORRELATION,
        )
    async with sessions() as asset, sessions() as inventory, sessions() as admin:
        # Actual owner lock order: assets org->network; inventory/spatial network->org.
        await WorkspaceService(asset, fake_redis).get_active_workspace(ws.workspace_id, user_id=str(ACTOR), require_write=True)
        await NetworkRepository(inventory).lock(network.network_id)
        pid = await asset.scalar(text("SELECT pg_backend_pid()"))
        asset_task = asyncio.create_task(NetworkRepository(asset).lock(network.network_id))
        admin_task = None
        try:
            await wait_for_lock(sessions, pid)
            if queued_admin:
                admin_pid = await admin.scalar(text("SELECT pg_backend_pid()"))
                admin_task = asyncio.create_task(OrganizationRepository(admin).lock(org.org_id))
                await wait_for_lock(sessions, admin_pid)
            try:
                await asyncio.wait_for(WorkspaceService(inventory, fake_redis).get_active_workspace(
                    ws.workspace_id, user_id=str(ACTOR), require_write=True,
                ), 2)
            except HTTPException as error:
                assert queued_admin and error.detail["code"] == "ORG_AUTHORITY_BUSY"
            await inventory.rollback()
            await asyncio.wait_for(asset_task, 3)
            await asset.rollback()
            if admin_task:
                await asyncio.wait_for(admin_task, 3)
        finally:
            await inventory.rollback()
            asset_task.cancel()
            await asyncio.gather(asset_task, return_exceptions=True)
            await asset.rollback()
            if admin_task:
                admin_task.cancel()
                await asyncio.gather(admin_task, return_exceptions=True)
