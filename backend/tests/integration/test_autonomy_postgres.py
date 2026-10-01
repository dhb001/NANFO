"""Opt-in migration/transaction tests; only a UUID-owned disposable schema is touched."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.autonomy.models import AutonomyControl, AutonomyDecision
from app.modules.autonomy.repository import AutonomyRepository
from app.modules.autonomy.schemas import SetAutonomyRequest, Verification
from app.modules.autonomy.service import AutonomyService
from app.modules.autonomy.worker import AutonomyWorker
from tests.autonomy_support import control_record, qualified_providers

pytestmark = pytest.mark.skipif(not os.environ.get("AUTONOMY_TEST_DSN"), reason="AUTONOMY_TEST_DSN not configured")


@pytest.fixture
async def migrated_sessions():
    schema = "autonomy_test_" + uuid.uuid4().hex
    url = make_url(os.environ["AUTONOMY_TEST_DSN"])
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
            with EnvironmentContext(config, scripts, fn=lambda rev, _: scripts._upgrade_revs("0015", rev)) as context:
                context.configure(connection=connection)
                context.run_migrations()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0015"
            indexes = set(connection.scalars(text("SELECT indexname FROM pg_indexes WHERE schemaname = :schema"), {"schema": schema}))
            assert {"ix_autonomy_controls_due", "uq_autonomy_controls_execution", "ix_autonomy_decisions_observing"} <= indexes
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
async def context(migrated_sessions, monkeypatch):
    sessions = migrated_sessions
    control = control_record(claim_token=None, lease_expires_at=None)
    async with sessions() as db:
        db.add(control)
        await db.commit()
    providers = qualified_providers(control)
    auth = AsyncMock(return_value=(control, ["read:telemetry", "write:config", "execute:rollback"]))
    monkeypatch.setattr("app.modules.autonomy.worker.authorize", auth)
    monkeypatch.setattr("app.modules.autonomy.service.authorize", auth)
    # C25 four-eyes approval (Redis-backed) is covered by test_autonomy_endpoints; these races
    # concern the single confirmed PUT that re-validates the control after its provider wait.
    monkeypatch.setattr("app.modules.autonomy.governance.require_distinct_approver", lambda: False)
    return SimpleNamespace(sessions=sessions, control=control, providers=providers,
        claims=SimpleNamespace(user_id=control.approved_by_user_id, workspace_id=None, org_id=None),
        worker=AutonomyWorker(sessions=sessions, redis=None, providers=providers))


async def test_concurrent_claim_and_expired_callback_fence(context):
    async def claim():
        async with context.sessions() as db:
            return await AutonomyRepository(db).claim()
    results = await asyncio.gather(claim(), claim())
    assert sum(value is not None for value in results) == 1
    old, decision = next(value for value in results if value is not None)
    async with context.sessions() as db:
        await db.execute(update(AutonomyControl).values(lease_expires_at=func.now() - timedelta(seconds=1),
                                                       next_cycle_at=func.now() - timedelta(seconds=1)))
        await db.commit()
    new, _ = await claim()
    assert new.claim_token != old.claim_token
    await context.worker.finish(old, decision, status="verified", reasons=[])
    async with context.sessions() as db:
        row = await db.get(AutonomyDecision, decision.decision_id)
        assert row.status == "blocked" and row.reasons == ["cycle_lease_expired"]


async def test_accept_callback_expiry_rolls_back_enlisted_work(context):
    async with context.sessions() as db:
        control, decision = await AutonomyRepository(db).claim()
    marker = uuid.uuid4()
    async def accept(db, authorization):
        row = AutonomyRepository(db).record(control, status="accepted", reasons=["test_staged_only"])
        row.decision_id = marker
        await db.flush()
        # Real DB lock wait / callback time must not extend approval.
        current = await db.get(AutonomyControl, control.network_id)
        current.approval_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.flush()
    context.providers.executor.accept.side_effect = accept
    await context.worker.cycle(control, decision)
    async with context.sessions() as db:
        assert await db.get(AutonomyDecision, marker) is None
        assert (await db.get(AutonomyControl, control.network_id)).active_execution_id is None
        assert "approval_expired_or_missing" in (await db.get(AutonomyDecision, decision.decision_id)).reasons
    context.providers.executor.verify.assert_not_awaited()


async def test_stop_serializes_with_acceptance_and_persists_before_cancel(context):
    entered, release = asyncio.Event(), asyncio.Event()
    async def accept(db, authorization):
        entered.set()
        await release.wait()
    context.providers.executor.accept.side_effect = accept
    async def cancel(reference):
        async with context.sessions() as db:
            current = await db.get(AutonomyControl, context.control.network_id)
            assert current.emergency_stopped
            assert current.active_execution_id == reference.execution_id
        return Verification(execution_id=reference.execution_id, status="cancelled", safe_to_release=True,
                            evidence=["test:verified_no_mutation"])
    # STOP cancels the exact persisted execution through the recovery provider (never Intent).
    context.providers.recovery.cancel.side_effect = cancel
    async def stop():
        async with context.sessions() as db:
            return await AutonomyService(db, None, providers=context.providers).stop(
                claims=context.claims, network_id=context.control.network_id)
    cycle = asyncio.create_task(context.worker.run_one())
    await asyncio.wait_for(entered.wait(), 5)
    stopping = asyncio.create_task(stop())
    try:
        await asyncio.sleep(.1)
        assert not stopping.done()  # Stop cannot bypass the acceptance row lock.
    finally:
        release.set()
    _, result = await asyncio.wait_for(asyncio.gather(cycle, stopping), 5)
    assert result.emergency_stopped and result.active_execution_id is None
    context.providers.executor.accept.assert_awaited_once()
    context.providers.recovery.cancel.assert_awaited_once()
    async with context.sessions() as db:
        assert (await db.get(AutonomyControl, context.control.network_id)).cancellation_status == "verified"


async def test_stop_response_reports_the_committed_latch(context):
    """The latch is a Core upsert; the response must not serve the session's pre-STOP control."""
    async with context.sessions() as db:
        result = await AutonomyService(db, None, providers=context.providers).stop(
            claims=context.claims, network_id=context.control.network_id)
    assert result.emergency_stopped and result.status == "stopped" and result.stopped_at is not None
    assert result.revision == context.control.revision + 1
    async with context.sessions() as db:
        assert (await db.get(AutonomyControl, context.control.network_id)).revision == result.revision


async def test_stop_before_acceptance_invalidates_durable_cycle(context):
    async def safety(*args):
        async with context.sessions() as db:
            await AutonomyService(db, None, providers=context.providers).stop(
                claims=context.claims, network_id=context.control.network_id)
        return context.providers.safety.assess.return_value
    context.providers.safety.assess.side_effect = safety
    await context.worker.run_one()
    context.providers.executor.accept.assert_not_awaited()
    async with context.sessions() as db:
        rows = list((await db.scalars(select(AutonomyDecision))).all())
        assert not any(row.status in {"accepted", "verified", "observing"} for row in rows)
        assert (await db.get(AutonomyControl, context.control.network_id)).emergency_stopped


@pytest.mark.parametrize("initial", [False, True])
async def test_put_waiting_on_readiness_cannot_clear_new_stop(context, initial):
    from sqlalchemy import delete
    if initial:
        async with context.sessions() as db:
            await db.execute(delete(AutonomyControl))
            await db.commit()
    entered, release = asyncio.Event(), asyncio.Event()
    async def qualify(_):
        entered.set()
        await release.wait()
        return context.providers.model.qualify.return_value
    context.providers.model.qualify.side_effect = qualify
    async def put():
        async with context.sessions() as db:
            return await AutonomyService(db, None, providers=context.providers).set_mode(claims=context.claims,
                request=SetAutonomyRequest(network_id=context.control.network_id, expected_revision=0 if initial else 1,
                    mode="autonomous", checkpoint_sha256=context.control.checkpoint_sha256,
                    approval_expires_at=datetime.now(UTC) + timedelta(minutes=5)))
    pending = asyncio.create_task(put())
    await asyncio.wait_for(entered.wait(), 5)
    async with context.sessions() as db:
        service = AutonomyService(db, None, providers=context.providers)
        service.snapshot = AsyncMock()
        await service.stop(claims=context.claims, network_id=context.control.network_id)
    release.set()
    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(pending, 5)
    assert error.value.detail["code"] == "AUTONOMY_REVISION_CONFLICT"
    async with context.sessions() as db:
        current = await db.get(AutonomyControl, context.control.network_id)
        assert current.emergency_stopped and current.revision == (1 if initial else 2)
        assert await db.scalar(select(func.count()).select_from(AutonomyDecision)) == 1
