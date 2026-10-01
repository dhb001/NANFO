"""Real transactions and receiver restart/revocation tests; unique disposable schema."""

import asyncio
import importlib.util
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.modules.autonomy.execution import AutonomousExecutor
from app.modules.autonomy.execution_models import AutonomousExecution, AutonomousProviderState
from app.modules.autonomy.execution_repository import ExecutionRepository
from app.modules.autonomy.models import AutonomyControl, AutonomyDecision, ConfigurationRevision, TimedOverride
from app.modules.autonomy.provider_state import ProviderStateRepository
from app.modules.autonomy.schemas import ExecutionReference
from tests.autonomous_execution_support import FakeDevice, fixture

pytestmark = pytest.mark.skipif(not os.environ.get("AUTONOMY_TEST_DSN"), reason="AUTONOMY_TEST_DSN not configured")


def migrate(connection, direction):
    path = Path(__file__).parents[2] / "alembic/versions/0027_autonomous_execution.py"
    spec = importlib.util.spec_from_file_location("autonomous_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0027" and module.down_revision == "0026"
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


@pytest.fixture
async def sessions():
    dsn = os.environ["AUTONOMY_TEST_DSN"]
    root = create_async_engine(dsn)
    schema = "autonomous_" + uuid.uuid4().hex
    async with root.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as conn:
            for model in (AutonomyControl, AutonomyDecision, ConfigurationRevision, TimedOverride):
                await conn.run_sync(model.__table__.create)
            await conn.run_sync(lambda sync: migrate(sync, "upgrade"))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with root.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await root.dispose()


async def setup_case(sessions, redis, monkeypatch, *, case=None, device=None):
    case = case or fixture()
    device = device or FakeDevice()
    executor = AutonomousExecutor(sessions, redis, case.installation, device, device.resource_id)
    authorized = AsyncMock(return_value=(None, ["write:config", "execute:rollback"]))
    monkeypatch.setattr("app.modules.autonomy.execution_authority.authorize", authorized)
    async with sessions() as db:
        db.add(case.control)
        await db.flush()
        db.add(AutonomyDecision(decision_id=case.auth.decision_id, network_id=case.control.network_id,
            workspace_id=case.control.workspace_id, actor_id=case.control.approved_by_user_id,
            mode="autonomous", control_revision=case.control.revision, status="observing", reasons=[], evidence=[],
            checkpoint_sha256=case.control.checkpoint_sha256, proposal=case.proposal.model_dump(mode="json"),
            observation=case.observation.model_dump(mode="json"), safety=case.safety.model_dump(mode="json")))
        state = ProviderStateRepository(db)
        await state.record_observation(case.observation, case.safety.binding.observation)
        await state.seed_history(installation=case.installation, state=case.safety.binding.state,
                                 evidence=["synthetic-test-baseline"])
        await db.commit()
    return case, device, executor, authorized


async def accept(sessions, case, executor):
    async with sessions() as db:
        await executor.accept(db, case.auth)
        control = await db.get(AutonomyControl, case.control.network_id)
        control.active_execution_id, control.active_intent_id = case.auth.execution_id, case.auth.intent_id
        control.active_decision_id = case.auth.decision_id
        await db.commit()


def reference(case, **changes):
    return ExecutionReference(**{key: getattr(case.auth, key) for key in (
        "network_id", "workspace_id", "intent_id", "execution_id", "decision_id", "control_revision", "claim_token")}, **changes)


async def test_acceptance_rollback_visibility_atomic_exclusion_and_fences(sessions):
    case = fixture()
    async with sessions() as first:
        repo = ExecutionRepository(first)
        await repo.stage(case.auth, case.installation, "unit-lab")
        async with sessions() as observer:
            assert await observer.scalar(select(func.count()).select_from(AutonomousExecution)) == 0
        await first.rollback()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AutonomousExecution)) == 0
    async with sessions() as first:
        row = await ExecutionRepository(first).stage(case.auth, case.installation, "unit-lab")
        assert row.fence == 1
        await first.commit()
    other = fixture()
    async with sessions() as db:
        with pytest.raises(ValueError, match="resource_owned"):
            await ExecutionRepository(db).stage(other.auth, other.installation, "unit-lab")
    async with sessions() as db:
        row = await ExecutionRepository(db).get(case.auth.execution_id, lock=True)
        row.phase, row.released = "cancelled", True
        await db.commit()
    async with sessions() as db:
        row = await ExecutionRepository(db).stage(other.auth, other.installation, "unit-lab")
        assert row.fence == 2
        await db.commit()


async def test_concurrent_transactions_only_one_accepts_and_expired_lease_is_not_release(sessions):
    cases = [fixture(), fixture()]

    async def stage(case):
        async with sessions() as db:
            try:
                row = await ExecutionRepository(db).stage(case.auth, case.installation, "unit-lab")
                row.phase = "uncertain"
                row.lease_until = datetime.now(UTC) - timedelta(seconds=10)
                await asyncio.sleep(.02)
                await db.commit()
                return True
            except ValueError:
                return False
    assert sorted(await asyncio.gather(*(stage(c) for c in cases))) == [False, True]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AutonomousExecution)) == 1
        owner = await ExecutionRepository(db).claim("unit-lab")
        assert owner.phase == "uncertain" and not owner.released
        await db.commit()


async def test_same_acceptance_concurrent_retry_is_idempotent(sessions):
    case = fixture()
    async def stage():
        async with sessions() as db:
            row = await ExecutionRepository(db).stage(case.auth, case.installation, "unit-lab")
            await asyncio.sleep(.01)
            await db.commit()
            return row.fence
    assert await asyncio.gather(stage(), stage()) == [1, 1]


async def test_stale_worker_token_cannot_renew_or_mutate_successor_journal(sessions):
    case = fixture()
    async with sessions() as db:
        await ExecutionRepository(db).stage(case.auth, case.installation, "unit-lab")
        await db.commit()
    async with sessions() as db:
        first = await ExecutionRepository(db).claim("unit-lab")
        token = first.lease_token
        first.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    async with sessions() as db:
        successor = await ExecutionRepository(db).claim("unit-lab")
        assert successor.lease_token != token
        await db.commit()
    async with sessions() as db:
        with pytest.raises(ValueError, match="ownership_or_lease_lost"):
            await ExecutionRepository(db).owned(case.command, token)


async def test_stop_during_read_only_prepare_is_rechecked_before_write(sessions, fake_redis, monkeypatch):
    case, device, executor, _ = await setup_case(sessions, fake_redis, monkeypatch)
    await accept(sessions, case, executor)
    prepare = device.prepare

    async def stop_after_prepare(plan):
        value = await prepare(plan)
        async with sessions() as db:
            control = await db.get(AutonomyControl, case.control.network_id)
            control.emergency_stopped = True
            await db.commit()
        return value
    device.prepare = stop_after_prepare
    await executor.run_one()
    assert device.applied == device.restored == 0
    assert (await executor.verify(reference(case))).safe_to_release


async def test_full_receiver_committed_accept_readback_revocation_and_exact_recovery(sessions, fake_redis, monkeypatch):
    case, device, executor, authorized = await setup_case(sessions, fake_redis, monkeypatch)
    await accept(sessions, case, executor)
    assert device.applied == 0
    assert await executor.run_one()
    result = await executor.verify(reference(case))
    assert result.status == "verified" and not result.safe_to_release and device.applied == 1
    authorized.side_effect = ValueError("actor_revoked")
    assert await executor.run_one()
    result = await executor.verify(reference(case))
    assert result.status == "cancelled" and result.safe_to_release
    assert device.restored == 1 and device.actual == "baseline"
    foreign = reference(case).model_copy(update={"workspace_id": uuid.uuid4()})
    with pytest.raises(ValueError, match="identity_mismatch"):
        await executor.cancel(foreign)


@pytest.mark.parametrize("change", ["STOP", "revision", "actor", "deadline", "approval", "installation", "plan"])
async def test_receiver_current_checks_after_acceptance_before_mutation(sessions, fake_redis, monkeypatch, change):
    case, device, executor, authorized = await setup_case(sessions, fake_redis, monkeypatch)
    await accept(sessions, case, executor)
    if change == "actor":
        authorized.side_effect = ValueError("actor_revoked")
    async with sessions() as db:
        control = await db.get(AutonomyControl, case.control.network_id)
        row = await db.get(AutonomousExecution, case.auth.execution_id)
        if change == "STOP":
            control.emergency_stopped = True
        elif change == "revision":
            control.revision += 1
        elif change == "approval":
            control.approval_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif change == "deadline":
            await asyncio.sleep(max(0, case.auth.certificate_expires_at_unix_seconds - datetime.now(UTC).timestamp()) + .01)
        elif change == "installation":
            row.command = {**row.command, "installation_sha256": "b" * 64}
        elif change == "plan":
            row.command = {**row.command, "plan": {**row.command["plan"], "paths": [["s1", "s4", "s2"]]}}
        await db.commit()
    await executor.run_one()
    assert device.applied == 0
    assert (await executor.verify(reference(case))).safe_to_release


async def test_restart_after_dispatch_possibility_never_reexecutes(sessions, fake_redis, monkeypatch):
    case, device, executor, authorized = await setup_case(sessions, fake_redis, monkeypatch)
    await accept(sessions, case, executor)
    prepared = await device.prepare(case.command.plan.model_dump(mode="json"))
    device.actual = prepared["plan"]
    async with sessions() as db:
        row = await db.get(AutonomousExecution, case.auth.execution_id)
        row.phase, row.prepared = "applying", prepared
        row.dispatched_at = datetime.now(UTC)
        row.lease_token, row.lease_until = uuid.uuid4(), datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    device.fail_restore = True
    await executor.run_one()
    result = await executor.verify(reference(case))
    assert result.status == "uncertain" and not result.safe_to_release
    device.fail_restore = False
    executor = AutonomousExecutor(sessions, fake_redis, case.installation, device, device.resource_id)
    await executor.run_one()
    assert device.applied == 0 and device.restored == 1
    assert (await executor.verify(reference(case))).safe_to_release


async def test_two_receiver_process_connections_serialize_device_io(sessions, fake_redis, monkeypatch):
    case, device, executor, _ = await setup_case(sessions, fake_redis, monkeypatch)
    await accept(sessions, case, executor)
    entered, release = asyncio.Event(), asyncio.Event()
    original = device.apply

    async def slow(prepared, checkpoint):
        entered.set()
        await release.wait()
        await original(prepared, checkpoint)
    device.apply = slow
    first = asyncio.create_task(executor.run_one())
    await asyncio.wait_for(entered.wait(), 2)
    assert await executor.run_one() is False
    release.set()
    await first
    assert device.applied == 1


async def test_frames_immutable_history_not_reseedable_and_migration_downgrade_refused(sessions):
    case = fixture()
    async with sessions() as db:
        repo = ProviderStateRepository(db)
        await repo.record_observation(case.observation, case.safety.binding.observation)
        await repo.seed_history(installation=case.installation, state=case.safety.binding.state, evidence=["test"])
        await db.commit()
    async with sessions() as db:
        changed = case.safety.binding.observation.model_copy(update={"sequence": 999})
        with pytest.raises(ValueError, match="immutable"):
            await ProviderStateRepository(db).record_observation(case.observation, changed)
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AutonomousProviderState)) == 1
        conn = await db.connection()
        # ADR-028: the 0027 downgrade refuses (before any DDL) while frames/journals exist.
        with pytest.raises(RuntimeError, match="Downgrade below 0027 refused"):
            await conn.run_sync(lambda sync: migrate(sync, "downgrade"))
        assert await db.scalar(select(func.count()).select_from(AutonomousProviderState)) == 1
        await db.commit()


@pytest.mark.parametrize("restart", [False, True])
async def test_frr_real_journal_actual_driver_readback_revoked_recovery(sessions, fake_redis, monkeypatch, restart):
    from emulation.autonomous_frr import LinuxFRRDriver
    from tests.autonomous_frr_support import FakeFRRNetwork, allow_dispatch

    # Lifecycle success needs room for24 real authority transactions under load.
    # Dedicated expiry-race tests retain the original subsecond certificate.
    case = fixture(runtime="frr", horizon_seconds=5.)
    network = FakeFRRNetwork()
    def driver():
        return LinuxFRRDriver(network, resource_id="unit-lab", run_id="run-1", binding_sha256="b" * 64,
            ownership_check=lambda *_: True, dispatch_guard=allow_dispatch)
    case, device, executor, authorized = await setup_case(sessions, fake_redis, monkeypatch, case=case, device=driver())
    await accept(sessions, case, executor)
    if restart:
        # Lost acknowledgement after kernel mutation; journal survives new driver.
        prepared = await device.prepare(case.command.plan.model_dump(mode="json"))
        async with sessions() as db:
            row = await db.get(AutonomousExecution, case.auth.execution_id)
            row.prepared, row.phase, row.dispatched_at = prepared, "applying", datetime.now(UTC)
            await db.commit()
        await device.apply(prepared, AsyncMock())
    else:
        await executor.run_one()
        result = await executor.verify(reference(case))
        assert result.status == "verified" and not result.safe_to_release
    assert len(network.writes) == 12
    authorized.side_effect = ValueError("requester_revoked")
    recovered = AutonomousExecutor(sessions, fake_redis, case.installation, driver(), "unit-lab")
    recovered.authority.runtime_guard = AsyncMock(side_effect=ValueError("model_expired"))
    await recovered.run_one()
    result = await recovered.verify(reference(case))
    assert result.status == "cancelled" and result.safe_to_release
    assert len(network.writes) == 24
    assert not any(network.rules.values()) and not any(network.routes.values())


@pytest.mark.parametrize("operation,lock_target", [
    ("checkpoint", "execution"), ("begin_apply", "execution"), ("verified", "execution"),
    ("begin_apply", "history"), ("verified", "history"),
])
@pytest.mark.parametrize("race", ["revoke", "expire"])
async def test_final_owner_lock_wait_rechecks_real_identity_and_expiry(sessions, fake_redis, monkeypatch, operation, race, lock_target):
    from fastapi import HTTPException
    from sqlalchemy import delete
    from app.modules.autonomy.execution import ReceiverJournal
    from app.modules.autonomy.service import authorize
    from app.modules.identity.models import Permission, Role, User, UserRole
    from app.modules.network.service import NetworkService

    case, device, executor, _ = await setup_case(sessions, fake_redis, monkeypatch)
    await accept(sessions, case, executor)
    async with sessions() as db:
        conn = await db.connection()
        for model in (User, Role, Permission, UserRole):
            await conn.run_sync(model.__table__.create)
        actor = uuid.UUID(case.auth.actor_id)
        role_id = uuid.uuid4()
        db.add_all([User(user_id=actor, email="race@example.test", hashed_password="test-not-login", is_active=True),
                    Role(role_id=role_id, name="Admin"), Permission(name="write:config"), Permission(name="execute:rollback")])
        await db.flush()
        db.add(UserRole(user_id=actor, role_id=role_id))
        row = await ExecutionRepository(db).claim("unit-lab")
        token = row.lease_token
        row.phase = "prepared" if operation == "begin_apply" else "applying"
        row.prepared = {"before": "baseline"}
        if operation == "verified":
            row.dispatched_at = datetime.now(UTC)
        await db.commit()
    # Real current Identity service/profile/role SQL; only unrelated Network access
    # is stubbed. Role removal below commits in a separate database transaction.
    monkeypatch.setattr("app.modules.autonomy.execution_authority.authorize", authorize)
    monkeypatch.setattr(NetworkService, "assert_network_workspace_access", AsyncMock(return_value=None))
    arrived = asyncio.Event()
    waiting_pid = None
    original_owned = ExecutionRepository.owned
    async def owned(repo, command, claim):
        nonlocal waiting_pid
        waiting_pid = await repo.db.scalar(text("SELECT pg_backend_pid()"))
        arrived.set()
        return await original_owned(repo, command, claim)
    monkeypatch.setattr(ExecutionRepository, "owned", owned)
    journal = ReceiverJournal(sessions, executor.authority, case.command, token)
    async def attempt():
        if operation == "checkpoint":
            await journal.checkpoint(case.command, mutation=True)
        elif operation == "begin_apply":
            await journal.begin_apply(case.command)
        else:
            await journal.verified(case.command, {"readback_sha256": "a" * 64, "readback_verified": True,
                                                 "probe": {"sent": 3, "received": 3}})
        # Device I/O may only follow a successful receiver decision.
        device.applied += 1
    async with sessions() as blocker:
        if lock_target == "execution":
            await ExecutionRepository(blocker).get(case.auth.execution_id, lock=True)
        else:
            await ProviderStateRepository(blocker).history(case.auth.network_id, lock=True)
        task = asyncio.create_task(attempt())
        try:
            await asyncio.wait_for(arrived.wait(), 2)
            async with sessions() as probe:
                for _ in range(100):
                    waiting = await probe.scalar(text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"), {"pid": waiting_pid})
                    await probe.commit()
                    if waiting == "Lock":
                        break
                    await asyncio.sleep(.005)
                assert waiting == "Lock", "test must exercise actual PostgreSQL lock contention"
            if race == "revoke":
                async with sessions() as revoker:
                    await revoker.execute(delete(UserRole).where(UserRole.user_id == actor))
                    await revoker.commit()
            else:
                await asyncio.sleep(max(0, case.auth.certificate_expires_at_unix_seconds - datetime.now(UTC).timestamp()) + .02)
            await blocker.commit()
            with pytest.raises((ValueError, HTTPException)):
                await asyncio.wait_for(task, 3)
            assert device.applied == 0
        finally:
            await blocker.rollback()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    async with sessions() as db:
        row = await db.get(AutonomousExecution, case.auth.execution_id)
        assert row.phase == ("prepared" if operation == "begin_apply" else "applying")
        assert not row.released


@pytest.mark.parametrize("scope", ["same", "workspace", "network", "missing"])
async def test_core_frame_string_pins_exact_scope_atomic_rollback(sessions, scope):
    from app.modules.autonomy.execution_models import AutonomousObservation
    from app.modules.autonomy.schemas import contract_digest
    from app.modules.telemetry.models import TelemetryRecord
    from app.modules.telemetry.pin_models import TelemetryEvidencePin
    case = fixture()
    record_id = uuid.uuid4()
    case.observation.evidence = [f"telemetry_record:{record_id}", f"telemetry_record:{record_id}"]
    async with sessions() as db:
        conn = await db.connection()
        for model in (TelemetryRecord, TelemetryEvidencePin):
            await conn.run_sync(model.__table__.create)
        if scope != "missing":
            db.add(TelemetryRecord(record_id=record_id, event_id=uuid.uuid4(), correlation_id=uuid.uuid4(),
                device_id=uuid.uuid4(), workspace_id=uuid.uuid4() if scope == "workspace" else case.observation.workspace_id,
                network_id=uuid.uuid4() if scope == "network" else case.observation.network_id,
                metric="queue", value=10., observed_at=case.observation.observed_at, source="unit-only", tags={}))
        await db.commit()
    async with sessions() as db:
        if scope == "same":
            await ProviderStateRepository(db).record_observation(case.observation, case.safety.binding.observation)
            assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 1
            async with sessions() as independent:
                assert await independent.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 0
                assert await independent.get(AutonomousObservation, contract_digest(case.observation)) is None
        else:
            with pytest.raises(ValueError, match="owner scope"):
                await ProviderStateRepository(db).record_observation(case.observation, case.safety.binding.observation)
        await db.rollback()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 0
        assert await db.get(AutonomousObservation, contract_digest(case.observation)) is None
        if scope == "same":
            await ProviderStateRepository(db).record_observation(case.observation, case.safety.binding.observation)
            await db.commit()
    if scope == "same":
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(TelemetryEvidencePin)) == 1
            assert await db.get(AutonomousObservation, contract_digest(case.observation)) is not None


async def test_configured_factory_worker_stages_then_separate_receiver_executes(sessions, fake_redis, monkeypatch, tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace
    from app.modules.autonomy.execution_settings import CONFIG_PATH, CONFIG_HASH
    from app.modules.autonomy.health_secret import PUBLIC_KEY_ENV, ReceiptSigner
    from app.modules.autonomy.providers import installed_providers
    from app.modules.autonomy.receiver_health import ReceiverHealth
    from app.modules.autonomy.worker import AutonomyWorker
    from tests.autonomy_support import qualified_providers
    from tests.unit.test_receiver_health_review import write_keys

    case, device, receiver, _ = await setup_case(sessions, fake_redis, monkeypatch)
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(EXECUTION_MODE="emulation"))
    monkeypatch.setattr("app.modules.autonomy.worker.get_settings", lambda: SimpleNamespace(EXECUTION_MODE="emulation"))
    monkeypatch.setenv(CONFIG_PATH, "/test-only/not-real-installation.json")
    monkeypatch.setenv(CONFIG_HASH, "f" * 64)
    # C21: verifiers hold only the receiver's Ed25519 public key; legacy HMAC stays disabled.
    signing_key, _, public_key_path = write_keys(tmp_path)
    monkeypatch.setenv(PUBLIC_KEY_ENV, str(public_key_path))
    # Independent calibration loader seam only; no genuine calibration exists.
    config = SimpleNamespace(resource_id="unit-lab", health_max_age_seconds=10,
                             load=lambda: (case.installation, b"a" * 32),
                             model_dump=lambda **_: {"resource_id": "unit-lab", "health_max_age_seconds": 10})
    monkeypatch.setattr("app.modules.autonomy.execution_settings.load_config", lambda: config)
    providers = installed_providers(sessions, fake_redis)
    # STOP/recovery use the persisted journal identity of the configured client (never Intent).
    assert providers.recovery is providers.executor
    assert not hasattr(providers.executor, "run") and not hasattr(providers.executor, "driver")
    assert (await providers.executor.refresh_status()).status == "unavailable"
    receiver.health_publisher = ReceiverHealth(fake_redis, case.installation, "unit-lab", signer=ReceiptSigner(signing_key))
    device.healthcheck = AsyncMock()
    assert await receiver.run_one() is False  # Real journal poll, independent receiver instance.
    device.healthcheck.assert_awaited_once()
    assert (await providers.executor.refresh_status()).status == "ready"
    base = qualified_providers(case.control)
    base.observer.observe.return_value = case.observation
    base.model.infer.return_value = case.proposal
    providers = replace(providers, observer=base.observer, model=base.model)
    async with sessions() as db:
        current = await db.get(AutonomyControl, case.auth.network_id)
        current.claim_token, current.lease_expires_at = None, None
        await db.commit()
    monkeypatch.setattr("app.modules.autonomy.worker.authorize", AsyncMock(return_value=(case.control, [])))
    worker = AutonomyWorker(sessions=sessions, redis=fake_redis, providers=providers)
    assert await worker.run_one()
    async with sessions() as db:
        current = await db.get(AutonomyControl, case.auth.network_id)
        assert current.active_execution_id is not None
        row = await db.get(AutonomousExecution, current.active_execution_id)
        assert row.phase == "accepted" and row.prepared is None
        ref = ExecutionReference(network_id=current.network_id, workspace_id=current.workspace_id,
            intent_id=current.active_intent_id, execution_id=current.active_execution_id,
            decision_id=current.active_decision_id, control_revision=current.revision, claim_token=uuid.uuid4())
    assert device.applied == 0
    assert (await providers.executor.verify(ref)).status == "pending"
    from app.modules.autonomy.service import AutonomyService
    monkeypatch.setattr("app.modules.autonomy.service.authorize", AsyncMock(return_value=(case.control, [])))
    async with sessions() as db:
        # Existing API uses this exact scoped snapshot/readiness path.
        status = await AutonomyService(db, fake_redis, providers=providers, sessions=sessions).snapshot(
            case.auth.network_id, case.auth.workspace_id)
        assert status.providers.executor.status == "ready"
    await receiver.run_one()
    assert device.applied == 1
    assert (await providers.executor.verify(ref)).status == "verified"
    await fake_redis.delete(receiver.health_publisher.redis_key)
    await providers.recovery.cancel(ref)  # Request works while receiver liveness missing.
    await receiver.run_one(execution_id=ref.execution_id, recovery_only=True)
    assert (await providers.executor.verify(ref)).safe_to_release


async def test_exact_recovery_never_claims_other_work_or_executes(sessions, fake_redis, monkeypatch):
    case, device, receiver, _ = await setup_case(sessions, fake_redis, monkeypatch)
    await accept(sessions, case, receiver)
    assert await receiver.run_one(execution_id=uuid.uuid4(), recovery_only=True) is False
    assert await receiver.run_one(execution_id=case.auth.execution_id, recovery_only=True) is False
    assert device.applied == 0
    async with sessions() as db:
        row = await db.get(AutonomousExecution, case.auth.execution_id)
        assert row.phase == "accepted" and row.lease_token is None
    await receiver.cancel(reference(case))
    assert await receiver.run_one(execution_id=case.auth.execution_id, recovery_only=True)
    assert device.applied == device.restored == 0
    assert (await receiver.verify(reference(case))).safe_to_release


async def test_receiver_does_not_publish_health_for_failed_device_probe(sessions, fake_redis, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from app.modules.autonomy.health_secret import ReceiptSigner
    from app.modules.autonomy.receiver_health import ReceiverHealth
    case, device, receiver, _ = await setup_case(sessions, fake_redis, monkeypatch)
    receiver.health_publisher = ReceiverHealth(fake_redis, case.installation, "unit-lab",
                                               signer=ReceiptSigner(Ed25519PrivateKey.generate()))
    device.healthcheck = AsyncMock(side_effect=ValueError("device_unreachable"))
    with pytest.raises(ValueError, match="device_unreachable"):
        await receiver.run_one()
    assert await fake_redis.get(receiver.health_publisher.redis_key) is None


async def test_journal_client_accept_requires_live_receiver_and_enlists_without_commit(sessions, fake_redis, monkeypatch):
    from types import SimpleNamespace
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from app.modules.autonomy.execution_client import JournalExecutionClient
    from app.modules.autonomy.health_secret import ReceiptSigner, ReceiptVerifier
    from app.modules.autonomy.receiver_health import ReceiverHealth
    case, device, receiver, _ = await setup_case(sessions, fake_redis, monkeypatch)
    monkeypatch.setattr("app.core.config.get_settings", lambda: SimpleNamespace(EXECUTION_MODE="emulation"))
    # C21: the receiver signs; the client verifies with the public key only.
    key = Ed25519PrivateKey.generate()
    health = ReceiverHealth(fake_redis, case.installation, "unit-lab", verifier=ReceiptVerifier(key.public_key()))
    client = JournalExecutionClient(sessions, fake_redis, case.installation, "unit-lab", health)
    async with sessions() as db:
        with pytest.raises(ValueError, match="not_ready"):
            await client.accept(db, case.auth)
    receiver.health_publisher = ReceiverHealth(fake_redis, case.installation, "unit-lab", signer=ReceiptSigner(key))
    device.healthcheck = AsyncMock()
    await receiver.run_one()
    async with sessions() as db:
        # A receipt alone is not readiness: accept only consults the preceding refresh (ADR-028 fix 1).
        with pytest.raises(ValueError, match="not_ready"):
            await client.accept(db, case.auth)
    assert (await client.refresh_status()).status == "ready"
    async with sessions() as db:
        await client.accept(db, case.auth)
        async with sessions() as independent:
            assert await independent.get(AutonomousExecution, case.auth.execution_id) is None
        await db.rollback()
    assert device.applied == 0
    async with sessions() as db:
        assert await db.get(AutonomousExecution, case.auth.execution_id) is None
