"""Actual migration/AsyncSession/fencing/STOP/restart tests in unique PG schemas."""

import asyncio
import importlib.util
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.modules.autonomy.experimental.controller import ExperimentalController
from app.modules.autonomy.experimental.models import LabAction, LabReceipt, LabResource, LabRun
from app.modules.autonomy.experimental.persistence import LabRepository
from app.modules.autonomy.experimental.schemas import utcnow
from tests.experimental_lab_support import case

pytestmark = pytest.mark.skipif(not os.environ.get("EXPERIMENTAL_TEST_DSN"), reason="EXPERIMENTAL_TEST_DSN unset")


def migrate(connection, direction):
    path = Path(__file__).parents[2] / "alembic/versions/0028_experimental_lab.py"
    spec = importlib.util.spec_from_file_location("experimental_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0028" and module.down_revision == "0027"
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


def downgrade_unless_evidence(connection):
    """0028's downgrade drops the lab tables only while no run/receipt exists (ADR-028 guard)."""
    evidence = connection.scalar(text("SELECT EXISTS (SELECT 1 FROM experimental_lab_runs) "
                                      "OR EXISTS (SELECT 1 FROM experimental_lab_receipts)"))
    if evidence:
        with pytest.raises(RuntimeError, match="Downgrade below 0028 refused"):
            migrate(connection, "downgrade")
    else:
        migrate(connection, "downgrade")


@pytest.fixture
async def sessions():
    root = create_async_engine(os.environ["EXPERIMENTAL_TEST_DSN"])
    schema = "experimental_" + uuid4().hex
    async with root.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(os.environ["EXPERIMENTAL_TEST_DSN"],
                                 connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: migrate(sync, "upgrade"))
        yield async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(downgrade_unless_evidence)
    finally:
        await engine.dispose()
        async with root.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await root.dispose()


def controller(sessions, c):
    return ExperimentalController(sessions, c.authority, c.ports, c.policy)


async def test_complete_join_committed_before_io_and_immutable_receipts(sessions):
    c = case()

    async def before(action):
        async with sessions.begin() as db:
            row = await db.get(LabAction, action.command.request_id)
            assert row.phase == "dispatching" and row.frame and row.inference and row.simulation and row.prepared
            # Lock acquisition from another connection proves the dispatch transaction ended.
            await db.execute(text("SET LOCAL lock_timeout = '100ms'"))
            await db.scalar(select(LabRun).where(LabRun.run_id == c.policy.run_id).with_for_update())
    c.transport.before_execute = before
    result = await controller(sessions, c).run()
    assert result["released"] and c.transport.executes == c.transport.recoveries == 1
    async with sessions() as db:
        receipts = (await db.scalars(select(LabReceipt))).all()
        assert {r.kind for r in receipts} >= {"admitted", "dispatching", "verified", "restored", "released"}
        receipts[0].payload = {"tampered": True}
        with pytest.raises(DBAPIError, match="immutable"):
            await db.commit()


async def test_concurrent_resource_exclusion_and_rollback(sessions):
    c, other = case(), case()
    async with sessions() as db:
        await LabRepository(db).create(c.policy, uuid4())
        async with sessions() as observer:
            assert await observer.scalar(select(func.count()).select_from(LabRun)) == 0
        await db.rollback()

    async def admit(policy):
        async with sessions.begin() as db:
            try:
                await LabRepository(db).create(policy, uuid4())
                return True
            except ValueError:
                return False
    assert sorted(await asyncio.gather(admit(c.policy), admit(other.policy))) == [False, True]


async def test_stop_before_run_is_durable(sessions):
    c = case()
    ctl = controller(sessions, c)
    await ctl.stop()
    with pytest.raises(ValueError, match="run_exists"):
        await ctl.run()
    assert not c.transport.executes
    async with sessions() as db:
        run = await db.get(LabRun, c.policy.run_id)
        run.stopped = False
        with pytest.raises(DBAPIError, match="immutable"):
            await db.commit()


@pytest.mark.parametrize("trigger", ["stop", "revoke", "stale"])
async def test_final_checkpoint_blocks_and_recovery_ignores_fresh_approval(sessions, trigger):
    c = case()
    ctl = controller(sessions, c)
    async def before(action):
        if trigger == "stop":
            await controller(sessions, c).stop()
        elif trigger == "revoke":
            c.authority.check.side_effect = ValueError("revoked")
        else:
            # Clock advances past the accepted frame; no frame editing allowed.
            from unittest.mock import patch
            with patch("app.modules.autonomy.experimental.authority.utcnow",
                       return_value=c.frame.snapshot.observed_at + timedelta(seconds=31)):
                await ctl.checkpoint(request_id=action.command.request_id, fresh_frame=True)
    c.transport.before_execute = before
    with pytest.raises(ValueError):
        await ctl.run()
    assert c.transport.executes == 0 and c.transport.recoveries == 1
    async with sessions() as db:
        assert (await db.get(LabRun, c.policy.run_id)).released


async def test_uncertain_dispatch_restores_never_reexecutes(sessions):
    c = case()
    c.transport.ambiguous = True
    with pytest.raises(TimeoutError):
        await controller(sessions, c).run()
    assert c.transport.executes == c.transport.recoveries == 1
    await controller(sessions, c).recover()
    assert c.transport.executes == c.transport.recoveries == 1


async def test_restart_uncertain_lease_expiry_does_not_release_or_replay(sessions):
    c = case()
    ctl = controller(sessions, c)
    c.transport.ambiguous = c.transport.recovery_uncertain = True
    with pytest.raises(ValueError, match="recovery_uncertain"):
        await ctl.run()
    async with sessions.begin() as db:
        run = await db.get(LabRun, c.policy.run_id)
        assert not run.released and run.phase == "uncertain"
        run.lease_until = utcnow() - timedelta(seconds=1)
    other = case()
    with pytest.raises(ValueError, match="resource_owned"):
        await controller(sessions, other).run()
    c.authority.check.side_effect = ValueError("actor revoked")
    c.transport.recovery_uncertain = False
    assert (await controller(sessions, c).recover())["released"]
    assert c.transport.executes == 1 and c.transport.recoveries == 2


async def test_negative_simulation_preserved_without_mutation(sessions):
    c = case()
    c.ports.simulator.simulate.return_value = c.simulation.model_copy(update={"admitted": False})
    with pytest.raises(ValueError, match="simulation_denied"):
        await controller(sessions, c).run()
    assert c.transport.executes == c.transport.recoveries == 0
    async with sessions() as db:
        action = await db.scalar(select(LabAction))
        assert action.phase == "rejected" and action.simulation["admitted"] is False
        assert (await db.get(LabResource, c.policy.runtime.resource_id)).owner_run_id is None


async def test_recovery_before_dispatch_and_expired_policy_without_authority(sessions):
    c = case()
    ctl = controller(sessions, c)
    async with sessions.begin() as db:
        await LabRepository(db).create(c.policy, ctl.token)
    request_id, _ = await ctl._begin_action()
    c.authority.check.side_effect = ValueError("revoked")
    from unittest.mock import patch
    # Recovery clock can be beyond policy expiry; durable lease is independently valid.
    with patch("app.modules.autonomy.experimental.authority.utcnow", return_value=c.policy.expires_at):
        await ctl.recover()
    async with sessions() as db:
        assert (await db.get(LabAction, request_id)).phase == "rejected"
    assert not c.transport.executes and not c.transport.recoveries


async def test_leases_are_granted_and_judged_on_the_database_clock(sessions):
    """ADR-028: lease_until derives from clock_timestamp(), not this process's clock."""
    c = case()
    ctl = controller(sessions, c)
    async with sessions.begin() as db:
        repo = LabRepository(db)
        run = await repo.create(c.policy, ctl.token)
        database_now = await db.scalar(select(func.clock_timestamp()))
        assert abs((run.lease_until - timedelta(seconds=c.policy.lease_seconds) - repo.clock).total_seconds()) < 1e-6
        assert repo.clock <= database_now and run.created_at == repo.clock
    async with sessions.begin() as db:
        repo = LabRepository(db)
        resource, run = await repo.lock(c.policy)
        run.lease_until = repo.clock - timedelta(microseconds=1)
        with pytest.raises(ValueError, match="ownership_or_lease_lost"):
            repo.owned(resource, run, ctl.token)
        repo.renew(run, c.policy.lease_seconds)
        repo.owned(resource, run, ctl.token)
    await ctl.recover()


async def test_live_recovery_lease_cannot_be_stolen(sessions):
    c = case()
    ctl = controller(sessions, c)
    async with sessions.begin() as db:
        await LabRepository(db).create(c.policy, ctl.token)
    with pytest.raises(ValueError, match="recovery_busy"):
        await controller(sessions, c).recover()
    await ctl.recover()


@pytest.mark.parametrize("guard", ["dwell", "total", "window"])
async def test_admission_budgets_are_durable(sessions, guard):
    c = case()
    c.policy = c.policy.model_copy(update={"min_dwell_seconds": 5})
    ctl = controller(sessions, c)
    async with sessions.begin() as db:
        run = await LabRepository(db).create(c.policy, ctl.token)
        if guard == "dwell":
            run.last_dispatched_at = utcnow()
        elif guard == "total":
            run.action_count = c.policy.max_actions
        else:
            db.add(LabAction(request_id=uuid4(), run_id=c.policy.run_id, phase="restored", dispatched_at=utcnow()))
    with pytest.raises(ValueError, match="budget_or_dwell"):
        await ctl._begin_action()
    assert not c.transport.executes
    await ctl.recover()


async def test_stop_racing_initial_admission_cannot_be_lost(sessions):
    c = case()
    first = controller(sessions, c)
    async def admit():
        async with sessions.begin() as db:
            await LabRepository(db).create(c.policy, first.token)
            await asyncio.sleep(.05)
    task = asyncio.create_task(admit())
    await asyncio.sleep(.01)
    await controller(sessions, c).stop()
    await task
    async with sessions() as db:
        run = await db.get(LabRun, c.policy.run_id)
        assert run.stopped and run.released


async def test_stop_supervision_cancels_blocked_verification_then_restores(sessions):
    c = case()
    c.policy = c.policy.model_copy(update={"max_action_duration_seconds": 3, "poll_seconds": .02})
    from app.modules.autonomy.experimental.schemas import contract_digest
    c.ports.simulator.simulate.return_value = c.simulation.model_copy(
        update={"policy_sha256": contract_digest(c.policy)})
    started = asyncio.Event()
    cancelled = asyncio.Event()
    async def blocked_verify(action):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    c.transport.verify = blocked_verify
    task = asyncio.create_task(controller(sessions, c).run())
    await asyncio.wait_for(started.wait(), timeout=5)
    await controller(sessions, c).stop()
    with pytest.raises(ValueError, match="stop_latched"):
        await asyncio.wait_for(task, timeout=5)
    assert cancelled.is_set() and c.transport.executes == c.transport.recoveries == 1


async def test_action_expiry_interrupts_blocked_verification(sessions):
    c = case()
    c.policy = c.policy.model_copy(update={"max_action_duration_seconds": 1., "poll_seconds": .02})
    from app.modules.autonomy.experimental.schemas import contract_digest
    c.ports.simulator.simulate.return_value = c.simulation.model_copy(
        update={"policy_sha256": contract_digest(c.policy)})
    entered = asyncio.Event()
    async def blocked_verify(action):
        entered.set()
        await asyncio.Event().wait()
    c.transport.verify = blocked_verify
    # Expiry can be detected on entry or after the final bounded authority read.
    with pytest.raises(ValueError, match="action_expired|checkpoint_elapsed"):
        await asyncio.wait_for(controller(sessions, c).run(), timeout=5)
    assert entered.is_set()
    assert c.transport.executes == c.transport.recoveries == 1


async def test_current_identity_revocation_after_resource_lock_wait(sessions, fake_redis, monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy import delete
    from unittest.mock import AsyncMock
    from app.modules.autonomy.experimental.authority import CurrentAuthority
    from app.modules.identity.models import Permission, Role, User, UserRole
    from app.modules.network.service import NetworkService
    c = case()
    actor, role = uuid4(), uuid4()
    c.policy = c.policy.model_copy(update={"actor_id": str(actor)})
    async with sessions.begin() as db:
        conn = await db.connection()
        for model in (User, Role, Permission, UserRole):
            await conn.run_sync(model.__table__.create)
        db.add_all([User(user_id=actor, email="experimental@example.test", hashed_password="test-only", is_active=True),
                    Role(role_id=role, name="Admin"), Permission(name="write:config"),
                    Permission(name="execute:rollback")])
        await db.flush()
        db.add(UserRole(user_id=actor, role_id=role))
    monkeypatch.setattr(NetworkService, "assert_network_workspace_access", AsyncMock(return_value=None))
    c.authority = CurrentAuthority(sessions, fake_redis)
    ctl = controller(sessions, c)
    async with sessions.begin() as db:
        await LabRepository(db).create(c.policy, ctl.token)
    await ctl.checkpoint()
    async with sessions.begin() as blocker:
        await blocker.scalar(select(LabResource).where(
            LabResource.resource_id == c.policy.runtime.resource_id).with_for_update())
        task = asyncio.create_task(ctl.checkpoint())
        await asyncio.sleep(.03)
        async with sessions.begin() as revoker:
            await revoker.execute(delete(UserRole).where(UserRole.user_id == actor))
    with pytest.raises(HTTPException) as denied:
        await task
    assert denied.value.status_code == 403
    assert (await ctl.recover())["released"]


@pytest.mark.parametrize("kind", ["fixed0", "fixed1", "heuristic"])
async def test_all_comparators_share_joined_controller(sessions, kind):
    from app.modules.autonomy.experimental.comparators import ComparatorAdapter
    from app.modules.autonomy.experimental.schemas import Route, SimulationRecord, contract_digest
    c = case()
    c.policy = c.policy.model_copy(update={"policy_kind": kind, "routes": (c.policy.routes[0],
        Route(action_id="route1", device_ids=("router",), path=("src", "r1", "dst")))})
    from app.modules.autonomy.experimental.ports import Ports
    async def simulate(frame, inference, policy):
        assert inference.qualification is None
        return SimulationRecord(frame_sha256=contract_digest(frame), inference_sha256=contract_digest(inference),
            policy_sha256=contract_digest(policy), action_id=inference.proposal.action_id, admitted=True,
            assumptions=policy.assumptions, objectives=policy.objectives, reasons=(),
            evaluator_sha256=policy.evaluator_sha256, result={"fixture": True})
    c.ports.simulator.simulate.side_effect = simulate
    c.ports = Ports(c.ports.observer, ComparatorAdapter(c.policy), c.ports.simulator, c.transport)
    assert (await controller(sessions, c).run())["released"]
    assert c.transport.executes == c.transport.recoveries == 1


async def test_bootstrap_recovery_without_prepared_action_or_fresh_approval(sessions):
    from app.modules.autonomy.experimental.schemas import (
        BootstrapCommand, BootstrapReceipt, BootstrapRecoveryReceipt, contract_digest,
    )
    c = case()
    ctl = controller(sessions, c)
    baseline = {"original": "receiver-owned-pre-reset"}
    command = BootstrapCommand(request_id=uuid4(), run_id=c.policy.run_id, runtime=c.policy.runtime,
        policy_sha256=contract_digest(c.policy), receiver_policy_sha256="b" * 64,
        baseline=baseline, baseline_sha256=contract_digest(baseline), ownership_sha256="c" * 64)
    await ctl.admit_bootstrap(command)
    async with sessions() as db:
        assert (await db.get(LabRun, c.policy.run_id)).phase == "bootstrap_prepared"
        assert await db.scalar(select(LabReceipt).where(LabReceipt.kind == "bootstrap_prepared"))
    episode = uuid4()
    receipt = BootstrapReceipt(request_id=command.request_id, command_sha256=contract_digest(command),
        measurement_run_id=episode, runtime=c.policy.runtime, registry_sha256=c.policy.registry_sha256,
        checkpoint_sha256=c.policy.checkpoint_sha256, weights_sha256=c.policy.weights_sha256,
        model_source_sha256=c.policy.model_source_sha256, baseline_sha256=command.baseline_sha256,
        ownership_sha256=command.ownership_sha256, evidence={"receiver": "fixture"})
    await ctl.complete_bootstrap(receipt)
    with pytest.raises(ValueError, match="receipt_mismatch"):
        await ctl.complete_bootstrap(receipt)
    await ctl.stop()
    async with sessions() as db:
        assert not (await db.get(LabRun, c.policy.run_id)).released
    c.authority.check.side_effect = ValueError("revoked")
    async def recover_bootstrap(actual, checkpoint):
        assert actual == command
        await checkpoint()
        return BootstrapRecoveryReceipt(request_id=command.request_id, command_sha256=contract_digest(command),
            baseline_sha256=command.baseline_sha256, ownership_sha256=command.ownership_sha256,
            status="restored", evidence={"readback": "original"})
    c.transport.recover_bootstrap = recover_bootstrap
    assert (await ctl.recover())["released"]
    assert c.transport.executes == c.transport.recoveries == 0


async def test_unknown_bootstrap_outcome_never_releases_without_receiver_recovery(sessions):
    from app.modules.autonomy.experimental.schemas import BootstrapCommand, contract_digest
    c = case()
    ctl = controller(sessions, c)
    command = BootstrapCommand(request_id=uuid4(), run_id=c.policy.run_id, runtime=c.policy.runtime,
        policy_sha256=contract_digest(c.policy), receiver_policy_sha256="b" * 64,
        baseline={"original": True}, baseline_sha256=contract_digest({"original": True}), ownership_sha256="c" * 64)
    await ctl.admit_bootstrap(command)
    with pytest.raises(AttributeError):
        await ctl.recover()
    async with sessions() as db:
        assert not (await db.get(LabRun, c.policy.run_id)).released


async def test_final_authority_read_is_after_last_journal_commit(sessions):
    from unittest.mock import AsyncMock
    c = case()
    ctl = controller(sessions, c)
    async with sessions.begin() as db:
        await LabRepository(db).create(c.policy, ctl.token)
    original = ctl._checkpoint_state
    count = 0
    async def state(**kwargs):
        nonlocal count
        result = await original(**kwargs)
        count += 1
        if count == 2:
            c.authority.check = AsyncMock(side_effect=ValueError("revoked at final commit"))
        return result
    ctl._checkpoint_state = state
    with pytest.raises(ValueError, match="final commit"):
        await ctl.checkpoint()
    await ctl.recover()


async def test_completed_bootstrap_binds_distinct_episode_through_join(sessions):
    from app.modules.autonomy.experimental.schemas import (
        BootstrapCommand, BootstrapReceipt, BootstrapRecoveryReceipt, contract_digest,
    )
    c = case()
    episode = c.frame.snapshot.run_id
    c.policy = c.policy.model_copy(update={"run_id": uuid4()})
    c.ports.simulator.simulate.return_value = c.simulation.model_copy(
        update={"policy_sha256": contract_digest(c.policy)})
    ctl = controller(sessions, c)
    command = BootstrapCommand(request_id=uuid4(), run_id=c.policy.run_id, runtime=c.policy.runtime,
        policy_sha256=contract_digest(c.policy), receiver_policy_sha256="b" * 64,
        baseline={"original": True}, baseline_sha256=contract_digest({"original": True}), ownership_sha256="c" * 64)
    await ctl.admit_bootstrap(command)
    with pytest.raises(ValueError, match="bootstrap_incomplete"):
        await ctl._begin_action()
    c.ports.observer.observe.assert_not_awaited()
    receipt = BootstrapReceipt(request_id=command.request_id, command_sha256=contract_digest(command),
        measurement_run_id=episode, runtime=c.policy.runtime, registry_sha256=c.policy.registry_sha256,
        checkpoint_sha256=c.policy.checkpoint_sha256, weights_sha256=c.policy.weights_sha256,
        model_source_sha256=c.policy.model_source_sha256, baseline_sha256=command.baseline_sha256,
        ownership_sha256=command.ownership_sha256, evidence={"receiver": "fixture"})
    await ctl.complete_bootstrap(receipt)
    restored = []
    async def recover_bootstrap(actual, checkpoint):
        await checkpoint()
        restored.append(actual)
        return BootstrapRecoveryReceipt(request_id=command.request_id, command_sha256=contract_digest(command),
            baseline_sha256=command.baseline_sha256, ownership_sha256=command.ownership_sha256,
            status="restored", evidence={"readback": "original"})
    c.transport.recover_bootstrap = recover_bootstrap
    assert (await ctl.run(admitted_bootstrap=True))["released"]
    assert restored == [command] and c.transport.executes == c.transport.recoveries == 1
    async with sessions() as db:
        action = await db.scalar(select(LabAction))
        assert action.run_id != episode
        assert action.frame["snapshot"]["run_id"] == str(episode)


async def test_cached_verification_cannot_refresh_its_age(sessions):
    from unittest.mock import patch
    from app.modules.autonomy.experimental.authority import verification_allowed
    from app.modules.autonomy.experimental.schemas import ActionCommand, contract_digest
    c = case()
    command = ActionCommand(request_id=uuid4(), run_id=c.policy.run_id, resource_id=c.policy.runtime.resource_id,
        fence=1, network_id=c.policy.network_id, workspace_id=c.policy.workspace_id, runtime=c.policy.runtime,
        route=c.policy.routes[0], policy_sha256=contract_digest(c.policy), frame_sha256=contract_digest(c.frame),
        inference_sha256=contract_digest(c.inference), simulation_sha256=contract_digest(c.simulation),
        created_at=utcnow(), expires_at=c.policy.expires_at)
    prepared = await c.transport.prepare(command)
    cached = await c.transport.verify(prepared)
    verification_allowed(c.policy, prepared, cached)
    with patch("app.modules.autonomy.experimental.authority.utcnow",
               return_value=cached.observed_at + timedelta(seconds=31)):
        with pytest.raises(ValueError, match="unavailable"):
            verification_allowed(c.policy, prepared, cached)


async def test_bootstrap_reset_is_committed_before_io_and_failed_reset_recovers(sessions):
    from app.modules.autonomy.experimental.schemas import BootstrapCommand, BootstrapRecoveryReceipt, contract_digest
    c = case()
    ctl = controller(sessions, c)
    command = BootstrapCommand(request_id=uuid4(), run_id=c.policy.run_id, runtime=c.policy.runtime,
        policy_sha256=contract_digest(c.policy), receiver_policy_sha256="b" * 64,
        baseline={"original": True}, baseline_sha256=contract_digest({"original": True}), ownership_sha256="c" * 64)
    calls = []
    async def reset(actual, checkpoint):
        await checkpoint()
        async with sessions() as db:
            receipt = await db.scalar(select(LabReceipt).where(LabReceipt.kind == "bootstrap_prepared"))
            assert receipt.payload == actual.model_dump(mode="json")
        calls.append("reset")
        raise TimeoutError("lost reset acknowledgement")
    async def recover(actual, checkpoint):
        await checkpoint()
        calls.append("recover")
        return BootstrapRecoveryReceipt(request_id=actual.request_id, command_sha256=contract_digest(actual),
            baseline_sha256=actual.baseline_sha256, ownership_sha256=actual.ownership_sha256,
            status="restored", evidence={"original": True})
    c.transport.recover_bootstrap = recover
    with pytest.raises(TimeoutError):
        await ctl.bootstrap(command, reset)
    assert calls == ["reset", "recover"]
    async with sessions() as db:
        assert (await db.get(LabRun, c.policy.run_id)).released


@pytest.mark.parametrize("authority_call", [1, 2])
async def test_acknowledged_stop_during_blocked_identity_denies_checkpoint(sessions, authority_call):
    """STOP commits on a separate connection before the blocking read returns."""
    c = case()
    ctl = controller(sessions, c)
    async with sessions.begin() as db:
        await LabRepository(db).create(c.policy, ctl.token)
    # Pending action keeps STOP from releasing ownership, isolating the latch gate.
    async with sessions.begin() as db:
        db.add(LabAction(request_id=uuid4(), run_id=c.policy.run_id, phase="observing"))
    entered, resume = asyncio.Event(), asyncio.Event()
    calls = 0
    async def authority(policy, **kwargs):
        nonlocal calls
        calls += 1
        if calls == authority_call:
            entered.set()
            await resume.wait()
    c.authority.check.side_effect = authority
    task = asyncio.create_task(ctl.checkpoint())
    await asyncio.wait_for(entered.wait(), 3)
    # Independent authority object: STOP is not stalled by the injected reader.
    stop_case = case()
    stop_case.policy = c.policy
    assert (await controller(sessions, stop_case).stop())["stopped"]
    async with sessions() as db:
        assert (await db.get(LabRun, c.policy.run_id)).stopped
    resume.set()
    with pytest.raises(ValueError, match="stop_latched"):
        await asyncio.wait_for(task, 3)
    assert c.transport.executes == 0
    await ctl.recover()


async def test_real_revocation_while_final_journal_flush_waits(sessions, fake_redis, monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import AsyncSession
    from unittest.mock import AsyncMock
    from app.modules.autonomy.experimental.authority import CurrentAuthority
    from app.modules.identity.models import Permission, Role, User, UserRole
    from app.modules.network.service import NetworkService
    c = case()
    actor, role = uuid4(), uuid4()
    c.policy = c.policy.model_copy(update={"actor_id": str(actor)})
    async with sessions.begin() as db:
        conn = await db.connection()
        for model in (User, Role, Permission, UserRole):
            await conn.run_sync(model.__table__.create)
        db.add_all([User(user_id=actor, email="final-check@example.test", hashed_password="test-only", is_active=True),
                    Role(role_id=role, name="Admin"), Permission(name="write:config"),
                    Permission(name="execute:rollback")])
        await db.flush()
        db.add(UserRole(user_id=actor, role_id=role))
    monkeypatch.setattr(NetworkService, "assert_network_workspace_access", AsyncMock(return_value=None))
    c.authority = CurrentAuthority(sessions, fake_redis)
    ctl = controller(sessions, c)
    async with sessions.begin() as db:
        await LabRepository(db).create(c.policy, ctl.token)
    entered, resume = asyncio.Event(), asyncio.Event()
    original_lock, original_flush = LabRepository.lock, AsyncSession.flush
    count = 0
    async def lock(repo, policy):
        nonlocal count
        result = await original_lock(repo, policy)
        count += 1
        if count == 3:
            repo.db.info["pause_final_flush"] = True
        return result
    async def flush(db, *args, **kwargs):
        if db.info.pop("pause_final_flush", False):
            entered.set()
            await resume.wait()
        return await original_flush(db, *args, **kwargs)
    monkeypatch.setattr(LabRepository, "lock", lock)
    monkeypatch.setattr(AsyncSession, "flush", flush)
    task = asyncio.create_task(ctl.checkpoint())
    await asyncio.wait_for(entered.wait(), 3)
    async with sessions.begin() as revoker:
        await revoker.execute(delete(UserRole).where(UserRole.user_id == actor))
    resume.set()
    with pytest.raises(HTTPException) as denied:
        await asyncio.wait_for(task, 3)
    assert denied.value.status_code == 403
    assert c.transport.executes == 0
    assert (await ctl.recover())["released"]


async def test_final_locked_authority_serializes_stop_and_times_out(sessions):
    c = case()
    c.policy = c.policy.model_copy(update={"io_timeout_seconds": .2})
    ctl = controller(sessions, c)
    async with sessions.begin() as db:
        await LabRepository(db).create(c.policy, ctl.token)
    entered = asyncio.Event()
    calls = 0
    async def authority(policy, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            entered.set()
            await asyncio.Event().wait()
    c.authority.check.side_effect = authority
    task = asyncio.create_task(ctl.checkpoint())
    await asyncio.wait_for(entered.wait(), 3)
    stop_case = case()
    stop_case.policy = c.policy
    stop = asyncio.create_task(controller(sessions, stop_case).stop())
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(task, 3)
    assert (await asyncio.wait_for(stop, 3))["stopped"]
    async with sessions() as db:
        assert (await db.get(LabRun, c.policy.run_id)).stopped
