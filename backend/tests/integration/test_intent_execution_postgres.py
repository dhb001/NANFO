"""Opt-in real migrations/CAS/crash tests, isolated in a disposable random schema.

INTENT_TEST_DSN is a SQLAlchemy psycopg2 DSN. Never prints credentials or modifies
the existing search path's tables. Schema cleanup drops only this fixture's UUID.
"""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.modules.intent.execution import accept_execution
from app.modules.intent.lab import LabResult, digest
from app.modules.intent.models import Intent, IntentExecution, IntentOutbox
from app.modules.intent.repository import ExecutionRepository
from app.modules.intent.worker import ExecutionWorker
from emulation.lab_contracts import verify_command
from tests.unit.test_intent_lab import LAB_KEY, command

pytestmark = pytest.mark.skipif(not os.environ.get("INTENT_TEST_DSN"), reason="INTENT_TEST_DSN not configured")


@pytest.fixture
async def migrated_sessions():
    schema = "intent_test_" + uuid.uuid4().hex
    url = make_url(os.environ["INTENT_TEST_DSN"])
    sync = create_engine(url.set(drivername="postgresql+psycopg2"))
    with sync.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = None
    try:
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
        scripts = ScriptDirectory.from_config(config)
        with sync.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            # ORM models follow head (ADR-028 migration 0030: unique intent keys).
            with EnvironmentContext(config, scripts, fn=lambda rev, _: scripts._upgrade_revs("head", rev)) as context:
                context.configure(connection=connection)
                context.run_migrations()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == scripts.get_current_head()
            assert connection.scalar(text("SELECT count(*) FROM intent_executions")) == 0
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
def runtime_settings(tmp_path, monkeypatch):
    for directory in ("commands", "results", "telemetry", "binding"):
        (tmp_path / directory).mkdir()
    # ADR-028 C15: the execution worker's protected mailbox HMAC key (owner-only 0400).
    key = tmp_path / "lab_command_key"
    key.write_bytes(LAB_KEY)
    key.chmod(0o400)
    monkeypatch.setenv("NANFO_LAB_COMMAND_KEY_FILE", str(key))
    return SimpleNamespace(**{**{key: value for key, value in get_settings().model_dump().items()
                               if key.startswith("EMULATION_")}, "EXECUTION_MODE": "emulation",
        "EMULATION_CONTROL_ENABLED": True, "EMULATION_EXECUTION_POLL_SECONDS": .01,
        "EMULATION_COMMANDS_PATH": str(tmp_path / "commands"), "EMULATION_RESULTS_PATH": str(tmp_path / "results"),
        "EMULATION_SNAPSHOT_PATH": str(tmp_path / "telemetry" / "snapshot.json"),
        "EMULATION_BINDING_PATH": str(tmp_path / "binding" / "binding.json")})


# ADR-028 four-eyes rule: the approver differs from the intent's requester.
APPROVER = str(uuid.uuid4())
# Filled by the ``authority`` fixture: the server's current lab identity to approve.
CURRENT = {}


async def seed(sessions, *, workspace_id=None):
    now = datetime.now(UTC)
    # Not a high-impact action: these CAS/outbox tests do not exercise C18 evidence.
    row = Intent(intent_id=uuid.uuid4(), workspace_id=workspace_id or uuid.uuid4(), network_id=uuid.uuid4(),
        intent_kind="throttle_qos", intent_payload={"action": "throttle_qos"}, status="validated",
        validation_result={"validation_kind": "manual_lab_plan"}, execution_provenance={}, explainability={},
        correlation_id=uuid.uuid4(), requested_by_user_id=str(uuid.uuid4()), requested_at=now)
    async with sessions() as db:
        db.add(row)
        await db.commit()
    return row


def acceptance(row):
    return {"workspace_id": row.workspace_id, "intent_id": row.intent_id, "idempotency_key": "request-1",
        "correlation_id": row.correlation_id, "actor_id": APPROVER,
        "permissions": ["write:config", "execute:rollback"], "manual_approval": True, "cancel": False,
        "approval_binding": dict(CURRENT["approval_binding"])}


@pytest.fixture
async def fake_redis():
    """Exercise real Redis Lua in an isolated prefix, never a shared consumer group."""
    if not os.environ.get("INTENT_TEST_REDIS_URL"):
        pytest.skip("INTENT_TEST_REDIS_URL required for real fenced-lock tests")
    client = aioredis.from_url(os.environ["INTENT_TEST_REDIS_URL"], decode_responses=True)
    prefix = "intent-test:" + uuid.uuid4().hex + ":"

    class ScopedRedis:
        async def eval(self, script, count, key, *args):
            assert count == 1
            return await client.eval(script, count, prefix + key, *args)

        def __getattr__(self, name):
            async def call(key, *args, **kwargs):
                return await getattr(client, name)(prefix + key, *args, **kwargs)
            return call

    try:
        yield ScopedRedis()
    finally:
        keys = [key async for key in client.scan_iter(match=prefix + "*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


@pytest.fixture
def authority(monkeypatch, runtime_settings):
    cmd = command()
    binding = SimpleNamespace(topology_id="campus-small-v1", model_dump=lambda **_: {"approved_binding": True})
    result = (cmd.plan, binding, SimpleNamespace(run_id=cmd.run_id))
    monkeypatch.setattr("app.modules.intent.execution.get_settings", lambda: runtime_settings)
    monkeypatch.setattr("app.modules.intent.execution.WorkspaceService.get_active_workspace",
                        AsyncMock(return_value=SimpleNamespace(org_id=uuid.UUID(int=123))))
    prepare = AsyncMock(return_value=result)
    monkeypatch.setattr("app.modules.intent.execution.prepare_plan", prepare)
    monkeypatch.setattr("app.modules.intent.worker.prepare_plan", prepare)
    CURRENT["approval_binding"] = {"plan_hash": digest(cmd.plan.model_dump(mode="json")),
                                   "binding_digest": digest({"approved_binding": True}), "run_id": str(cmd.run_id)}
    return prepare


async def test_migrated_atomic_acceptance_concurrency_cas_and_outbox(migrated_sessions, runtime_settings, authority, fake_redis):
    sessions = migrated_sessions
    row = await seed(sessions)

    async def accept(params):
        async with sessions() as db:
            return await accept_execution(db=db, redis=fake_redis, **params)

    first, second = await asyncio.gather(accept(acceptance(row)), accept(acceptance(row)))
    assert {first[1], second[1]} == {False, True}
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(IntentExecution)) == 1
        assert await db.scalar(select(func.count()).select_from(IntentOutbox)) == 1
        assert (await db.get(Intent, row.intent_id)).status == "execution_started"
    for params in ({**acceptance(row), "manual_approval": False}, {**acceptance(row), "idempotency_key": "other"}):
        with pytest.raises(HTTPException) as error:
            await accept(params)
        assert error.value.status_code == 409
    another = await seed(sessions, workspace_id=row.workspace_id)
    with pytest.raises(HTTPException) as error:
        await accept({**acceptance(another), "idempotency_key": "other"})
    assert error.value.status_code == 409
    async with sessions() as db:
        assert (await db.get(Intent, another.intent_id)).status == "validated"
        claim = await ExecutionRepository(db).claim("old", 15)
        await db.commit()  # ADR-028: repositories never commit; the worker does
        original_command = dict(claim.command)
    async with sessions() as db:
        assert await ExecutionRepository(db).claim("new", 15) is None
        await db.execute(update(IntentExecution).values(lease_until=func.now() - timedelta(seconds=1)))
        await db.commit()
    async with sessions() as db:
        recovered = await ExecutionRepository(db).claim("new", 15)
        await db.commit()
        assert recovered.fence == claim.fence + 1
        assert recovered.command == original_command
        assert recovered.lease_until is not None  # server-computed expiry loaded by the claim
        assert not await ExecutionRepository(db).renew(claim.execution_id, "old", claim.fence, 15)
        assert await ExecutionRepository(db).renew(recovered.execution_id, "new", recovered.fence, 15)
        await db.commit()
    worker = ExecutionWorker(settings=runtime_settings, sessions=sessions, redis=fake_redis)
    assert await worker.publish_one()
    first_envelope = (await fake_redis.xrange("stream:intent"))[0][1]
    # XADD succeeded but database acknowledgement lost: same ID, timestamp and bytes.
    async with sessions() as db:
        await db.execute(update(IntentOutbox).values(published_at=None))
        await db.commit()
    assert await worker.publish_one()
    assert (await fake_redis.xrange("stream:intent"))[1][1] == first_envelope


async def test_worker_lost_result_recovery_and_verified_terminal(migrated_sessions, runtime_settings, authority, fake_redis):
    sessions = migrated_sessions
    row = await seed(sessions)
    async with sessions() as db:
        await accept_execution(db=db, redis=fake_redis, **acceptance(row))
        pending = (await db.execute(select(IntentExecution))).scalar_one()
        assert "dispatch_expires_at" not in pending.command
    worker = ExecutionWorker(settings=runtime_settings, sessions=sessions, redis=fake_redis)
    task = asyncio.create_task(worker.run_one())
    command_path = None
    for _ in range(200):
        files = list(Path(runtime_settings.EMULATION_COMMANDS_PATH).glob("*.json"))
        if files:
            command_path = files[0]
            break
        await asyncio.sleep(.01)
    assert command_path is not None
    original_bytes = command_path.read_bytes()
    # C15: the published envelope is MAC-authenticated; compare its verified content.
    original = verify_command(LAB_KEY, json.loads(original_bytes))
    async with sessions() as db:
        persisted = await db.get(IntentExecution, uuid.UUID(original["execution_id"]))
        expiry = datetime.fromisoformat(original["dispatch_expires_at"].replace("Z", "+00:00"))
        assert persisted.command == original
        assert 0 < (expiry - persisted.dispatched_at).total_seconds() <= 5
        assert expiry <= persisted.lease_until
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with sessions() as db:
        assert (await db.get(Intent, row.intent_id)).status == "execution_started"
        await db.execute(update(IntentExecution).values(lease_until=func.now() - timedelta(seconds=1)))
        await db.commit()
    result = {key: original[key] for key in ("version", "execution_id", "run_id", "binding_digest", "plan_hash", "fence")}
    result.update(status="completed", verification={"readback_verified": True, "readback_sha256": "b" * 64,
        "config_readback_and_reachability": True, "traffic_effects_verified": False,
        "probe": {"sent": 3, "received": 3, "source_host": "h1", "destination_host": "h3"}},
        rollback=None, failure_reason=None, completed_at=datetime.now(UTC).isoformat())
    LabResult.model_validate_json(json.dumps(result))
    Path(runtime_settings.EMULATION_RESULTS_PATH, command_path.name).write_text(json.dumps(result))
    restarted = ExecutionWorker(settings=runtime_settings, sessions=sessions, redis=fake_redis)
    assert await restarted.run_one()
    assert command_path.read_bytes() == original_bytes
    assert verify_command(LAB_KEY, json.loads(command_path.read_bytes())) == original
    assert authority.await_count == 2  # acceptance and first dispatch, never redispatch on recovery
    async with sessions() as db:
        intent = await db.get(Intent, row.intent_id)
        assert intent.status == "execution_completed"
        job = await db.get(IntentExecution, uuid.UUID(original["execution_id"]))
        assert not job.blocks_lab and job.result == LabResult.model_validate_json(json.dumps(result)).model_dump(mode="json")
        assert await db.scalar(select(func.count()).select_from(IntentOutbox)) == 2
    # Cancel after a durable success must not mistake the old completion for a
    # rollback acknowledgment. It reopens exclusion until new actual evidence.
    async with sessions() as db:
        await accept_execution(db=db, redis=fake_redis, **{**acceptance(row), "cancel": True, "manual_approval": False})
        await db.execute(update(IntentExecution).values(lease_until=func.now() - timedelta(seconds=1)))
        await db.commit()
    assert await restarted.run_one()
    async with sessions() as db:
        job = await db.get(IntentExecution, uuid.UUID(original["execution_id"]))
        assert job.blocks_lab and job.phase == "uncertain"
        assert (await db.get(Intent, row.intent_id)).status == "execution_started"
        await db.execute(update(IntentExecution).values(lease_until=func.now() - timedelta(seconds=1)))
        await db.commit()
    result.update(status="cancelled", rollback={"verified": True, "readback_sha256": "d" * 64},
                  completed_at=datetime.now(UTC).isoformat())
    Path(runtime_settings.EMULATION_RESULTS_PATH, command_path.name).write_text(json.dumps(result))
    assert await restarted.run_one()
    async with sessions() as db:
        job = await db.get(IntentExecution, uuid.UUID(original["execution_id"]))
        assert not job.blocks_lab and job.phase == "cancelled"
        assert (await db.get(Intent, row.intent_id)).status == "execution_failed"
        cancellation_time = job.cancellation_requested_at
        event_count = await db.scalar(select(func.count()).select_from(IntentOutbox))
    async with sessions() as db:
        await accept_execution(db=db, redis=fake_redis, **{**acceptance(row), "cancel": True, "manual_approval": False})
        job = await db.get(IntentExecution, uuid.UUID(original["execution_id"]))
        assert job.phase == "cancelled" and job.cancellation_requested_at == cancellation_time
        assert await db.scalar(select(func.count()).select_from(IntentOutbox)) == event_count


async def test_revocation_prevents_dispatch_and_silence_never_releases_lab(migrated_sessions, runtime_settings, authority, fake_redis):
    sessions = migrated_sessions
    row = await seed(sessions)
    async with sessions() as db:
        await accept_execution(db=db, redis=fake_redis, **acceptance(row))
    authority.side_effect = ValueError("actor revoked")
    worker = ExecutionWorker(settings=runtime_settings, sessions=sessions, redis=fake_redis)
    await worker.run_one()
    assert not list(Path(runtime_settings.EMULATION_COMMANDS_PATH).iterdir())
    async with sessions() as db:
        assert (await db.get(Intent, row.intent_id)).status == "execution_failed"
    authority.side_effect = None
    row2 = await seed(sessions)
    async with sessions() as db:
        await accept_execution(db=db, redis=fake_redis, **acceptance(row2))
        job = (await db.execute(select(IntentExecution).where(IntentExecution.intent_id == row2.intent_id))).scalar_one()
        job.command = {**job.command, "deadline": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                       "dispatch_expires_at": (datetime.now(UTC) - timedelta(seconds=2)).isoformat()}
        job.dispatched_at = datetime.now(UTC) - timedelta(seconds=5)
        await db.commit()
    await worker.run_one()
    async with sessions() as db:
        job = (await db.execute(select(IntentExecution).where(IntentExecution.intent_id == row2.intent_id))).scalar_one()
        assert job.blocks_lab and job.phase == "uncertain"
        assert (await db.get(Intent, row2.intent_id)).status == "execution_started"
        wire = verify_command(LAB_KEY, json.loads(
            Path(runtime_settings.EMULATION_COMMANDS_PATH, f"{job.execution_id}.json").read_bytes()))
        assert wire["operation"] == "cancel" and wire["fence"] == job.command["fence"]
        assert digest(wire["plan"]) == wire["plan_hash"]


async def test_started_publish_failure_blocks_concurrent_terminal_and_audits_canceller(
    migrated_sessions, runtime_settings, authority, fake_redis,
):
    sessions = migrated_sessions
    row = await seed(sessions)
    async with sessions() as db:
        await accept_execution(db=db, redis=fake_redis, **acceptance(row))
        job = (await db.execute(select(IntentExecution))).scalar_one()
        execution_id = job.execution_id
    # A publisher holds the earlier event lease when a different actor cancels.
    async with sessions() as db:
        started = await ExecutionRepository(db).claim_event("failed-publisher", 15)
        await db.commit()
        assert started.sequence == 1
    canceller = str(uuid.uuid4())
    async with sessions() as db:
        await accept_execution(db=db, redis=fake_redis,
            **{**acceptance(row), "cancel": True, "manual_approval": False, "actor_id": canceller})
    worker = ExecutionWorker(settings=runtime_settings, sessions=sessions, redis=fake_redis)
    await worker.run_one()  # No command was dispatched, so cancellation is safe.
    async with sessions() as db:
        assert await ExecutionRepository(db).claim_event("successor", 15) is None
        job = await db.get(IntentExecution, execution_id)
        assert job.org_id == uuid.UUID(int=123)
        assert job.actor_id == APPROVER != row.requested_by_user_id
        assert job.cancelled_by_user_id == canceller and job.cancellation_requested_at is not None
        assert not job.blocks_lab and job.phase == "cancelled"
        events = list((await db.execute(select(IntentOutbox).order_by(IntentOutbox.sequence))).scalars())
        assert [event.sequence for event in events] == [1, 2, 3]
        assert all(json.loads(event.envelope["payload"])["org_id"] == str(uuid.UUID(int=123)) for event in events)
        terminal_payload = json.loads(events[-1].envelope["payload"])
        assert terminal_payload["actor_id"] == canceller
        assert terminal_payload["execution_provenance"]["approved_by_user_id"] == APPROVER
        # ADR-028: deterministic per-transition event IDs and distinguishable phases.
        assert [json.loads(event.envelope["payload"])["phase"] for event in events] == [
            "accepted", "cancelling", "cancelled"]
        assert all(event.event_id == uuid.uuid5(execution_id, f"intent-outbox:{event.sequence}") for event in events)
        await db.execute(update(IntentOutbox).where(IntentOutbox.event_id == started.event_id).values(
            lease_until=func.now() - timedelta(seconds=1)))
        await db.commit()
    # Concurrent workers may only claim the earliest unpublished event, even
    # with SKIP LOCKED. A failed attempt cannot make terminal overtake started.
    async def claim(owner):
        async with sessions() as db:
            event = await ExecutionRepository(db).claim_event(owner, 15)
            await db.commit()
            return event

    claimed = await asyncio.gather(claim("a"), claim("b"))
    winners = [event for event in claimed if event is not None]
    assert len(winners) == 1 and winners[0].sequence == 1
    async with sessions() as db:
        assert await ExecutionRepository(db).acknowledge_event(winners[0].event_id, winners[0].lease_owner)
        await db.commit()
    assert await worker.publish_one()
    assert await worker.publish_one()
    delivered = await fake_redis.xrange("stream:intent")
    assert [json.loads(fields["payload"])["execution_provenance"]["phase"] for _, fields in delivered] == ["cancelling", "cancelled"]


async def test_requester_cannot_approve_and_binding_must_match(migrated_sessions, runtime_settings, authority, fake_redis):
    sessions = migrated_sessions
    row = await seed(sessions)
    for params, code in (({**acceptance(row), "actor_id": row.requested_by_user_id}, "DISTINCT_APPROVER_REQUIRED"),
                         ({**acceptance(row), "approval_binding": None}, "APPROVAL_BINDING_MISMATCH"),
                         ({**acceptance(row), "approval_binding": {**CURRENT["approval_binding"], "run_id": str(uuid.uuid4())}},
                          "APPROVAL_BINDING_MISMATCH")):
        async with sessions() as db:
            with pytest.raises(HTTPException) as error:
                await accept_execution(db=db, redis=fake_redis, **params)
        assert error.value.detail["code"] == code
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(IntentExecution)) == 0
        assert (await db.get(Intent, row.intent_id)).status == "validated"


async def test_execute_keeps_the_validate_key_and_rejects_another(migrated_sessions, runtime_settings, authority, fake_redis):
    sessions = migrated_sessions
    row = await seed(sessions)
    async with sessions() as db:
        await db.execute(update(Intent).where(Intent.intent_id == row.intent_id).values(idempotency_key="validate-1"))
        await db.commit()
    async with sessions() as db:
        with pytest.raises(HTTPException) as error:
            await accept_execution(db=db, redis=fake_redis, **acceptance(row))  # supplies "request-1"
    assert error.value.detail["code"] == "INTENT_IDEMPOTENCY_CONFLICT"
    async with sessions() as db:
        _, replay = await accept_execution(db=db, redis=fake_redis, **{**acceptance(row), "idempotency_key": None})
        assert replay is False
        job = (await db.execute(select(IntentExecution))).scalar_one()
        assert job.request_key == "validate-1"
        assert (await db.get(Intent, row.intent_id)).idempotency_key == "validate-1"


async def test_outbox_retention_deletes_only_old_published_rows_and_keeps_order(
    migrated_sessions, runtime_settings, authority, fake_redis,
):
    """ADR-028: published intent_outbox rows older than the retention age are deleted in a
    bounded statement; unpublished rows, recent rows and execution records stay."""
    sessions = migrated_sessions
    row = await seed(sessions)
    async with sessions() as db:
        await accept_execution(db=db, redis=fake_redis, **acceptance(row))
    async with sessions() as db:
        await accept_execution(db=db, redis=fake_redis, **{**acceptance(row), "cancel": True, "manual_approval": False})
    async with sessions() as db:
        accepted, cancelling = list((await db.execute(select(IntentOutbox).order_by(IntentOutbox.sequence))).scalars())
        await db.execute(update(IntentOutbox).where(IntentOutbox.event_id == accepted.event_id).values(
            published_at=func.now() - timedelta(days=31), created_at=func.now() - timedelta(days=31)))
        await db.commit()
    worker = ExecutionWorker(settings=runtime_settings, sessions=sessions, redis=fake_redis)
    worker.retention_batch = 10
    assert worker.retention_days == 30
    assert await worker.purge_published() == 1
    assert await worker.purge_published() == 0  # rate limited until the next interval
    async with sessions() as db:
        remaining = list((await db.execute(select(IntentOutbox))).scalars())
        assert [event.event_id for event in remaining] == [cancelling.event_id]
        assert await db.scalar(select(func.count()).select_from(IntentExecution)) == 1
        # Deleting published history never unblocks or reorders the unpublished tail.
        claimed = await ExecutionRepository(db).claim_event("retention-probe", 15)
        await db.commit()
        assert claimed.event_id == cancelling.event_id
