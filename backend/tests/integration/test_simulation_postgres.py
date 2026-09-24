"""Opt-in real migrations and CAS races in a UUID-owned disposable schema."""

import asyncio
import copy
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.intent.execution import accept_execution, project_execution
from app.modules.intent.lab import LabIntent, digest
from app.modules.intent.models import Intent, IntentExecution
from app.modules.intent.repository import ExecutionRepository
from app.modules.intent.worker import ExecutionWorker, LeaseAuthority
from app.modules.simulation.evaluator import advance, output
from app.modules.simulation.modeled import (
    current_network_state_hash,
    transition_modeled,
)
from app.modules.simulation.models import Simulation, SimulationOutbox
from app.modules.simulation.repository import SimulationRepository
from app.modules.simulation.service import SimulationStartService
from app.modules.simulation.worker import SimulationWorker
from tests.simulation_support import completed, policy_scenario, record, scenario
from tests.unit.test_intent_lab import mailbox_settings, payload  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.environ.get("SIMULATION_TEST_DSN"),
    reason="SIMULATION_TEST_DSN not configured",
)


@pytest.fixture
async def sessions():
    schema = "simulation_test_" + uuid.uuid4().hex
    url = make_url(os.environ["SIMULATION_TEST_DSN"])
    sync = create_engine(url.set(drivername="postgresql+psycopg2"))
    engine = None
    with sync.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        config = Config()
        config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[2] / "alembic")
        )
        scripts = ScriptDirectory.from_config(config)
        with sync.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            # ORM models follow head (ADR-028 migration 0030: claim_attempts, outbox created_at).
            with EnvironmentContext(
                config, scripts, fn=lambda rev, _: scripts._upgrade_revs("head", rev)
            ) as context:
                context.configure(connection=connection)
                context.run_migrations()
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == scripts.get_current_head()
            )
        engine = create_async_engine(
            url.set(drivername="postgresql+asyncpg"),
            connect_args={"server_settings": {"search_path": schema}},
        )
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if engine:
            await engine.dispose()
        with sync.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        sync.dispose()


async def seed(sessions, row=None):
    row = row or record()
    async with sessions() as db:
        db.add(row)
        await db.commit()
    return row


async def claim(sessions):
    # ADR-028: the repository never commits; the caller (worker) owns the unit of work.
    async with sessions() as db:
        row = await SimulationRepository(db).claim()
        await db.commit()
        return row


async def test_concurrent_claim_expiry_and_stale_batch_fenced(sessions):
    await seed(sessions)
    results = await asyncio.gather(claim(sessions), claim(sessions))
    assert sum(row is not None for row in results) == 1
    old = next(row for row in results if row is not None)
    async with sessions() as db:
        await db.execute(
            update(Simulation).values(
                lease_expires_at=func.now() - timedelta(seconds=1)
            )
        )
        await db.commit()
    new = await claim(sessions)
    assert new.lease_token != old.lease_token
    checkpoint = advance(scenario(), old.checkpoint)
    async with sessions() as db:
        assert not await SimulationRepository(db).finish_batch(
            old, checkpoint=checkpoint, run_output=output(scenario(), checkpoint)
        )
        await db.rollback()
    async with sessions() as db:
        assert await SimulationRepository(db).finish_batch(
            new, checkpoint=checkpoint, run_output=output(scenario(), checkpoint)
        )
        await db.commit()
    async with sessions() as db:
        current = await db.get(Simulation, new.simulation_id)
        assert current.revision == new.revision + 1 and current.lease_token is None


async def test_pause_during_worker_batch_atomic_and_resume_equivalent(
    sessions, monkeypatch
):
    row = await seed(sessions)
    started, release = asyncio.Event(), asyncio.Event()
    actual_thread = asyncio.to_thread

    async def delayed(*args, **kwargs):
        started.set()
        await release.wait()
        return await actual_thread(*args, **kwargs)

    monkeypatch.setattr("app.modules.simulation.worker.asyncio.to_thread", delayed)
    worker = SimulationWorker(sessions=sessions, redis=None, batch_ticks=3)
    pending = asyncio.create_task(worker.run_one())
    await asyncio.wait_for(started.wait(), 5)
    async with sessions() as db:
        svc = SimulationStartService(db=db, redis=None)
        current = await svc._repo.lock(row.simulation_id)
        await transition_modeled(
            svc, record=current, state="paused", correlation_id=str(uuid.uuid4())
        )
    release.set()
    await asyncio.wait_for(pending, 5)
    async with sessions() as db:
        current = await db.get(Simulation, row.simulation_id)
        assert current.state == "paused" and current.checkpoint == row.checkpoint
        svc = SimulationStartService(db=db, redis=None)
        await svc._repo.lock(row.simulation_id)
        await transition_modeled(
            svc, record=current, state="queued", correlation_id=str(uuid.uuid4())
        )
    while await worker.run_one():
        pass
    async with sessions() as db:
        current = await db.get(Simulation, row.simulation_id)
        assert current.state == "completed"
        assert current.run_output == completed(scenario())[1]
        assert current.evidence_expires_at > current.completed_at


async def test_finished_batch_before_pause_preserves_committed_checkpoint(sessions):
    row = await seed(sessions)
    worker = SimulationWorker(sessions=sessions, redis=None, batch_ticks=3)
    await worker.run_one()
    async with sessions() as db:
        svc = SimulationStartService(db=db, redis=None)
        current = await svc._repo.lock(row.simulation_id)
        checkpoint = copy.deepcopy(current.checkpoint)
        await transition_modeled(
            svc, record=current, state="paused", correlation_id=str(uuid.uuid4())
        )
    assert not await worker.run_one()
    async with sessions() as db:
        current = await db.get(Simulation, row.simulation_id)
        assert current.checkpoint == checkpoint and checkpoint["state"]["tick"] == 3


async def test_corrupt_checkpoint_cancelled_and_terminal_outbox_atomic(sessions):
    row = record()
    row.checkpoint["state"]["tick"] = 8
    await seed(sessions, row)
    worker = SimulationWorker(sessions=sessions, redis=None)
    assert await worker.run_one()
    async with sessions() as db:
        current = await db.get(Simulation, row.simulation_id)
        assert current.state == "cancelled" and current.risk_gate == "blocked"
        assert current.warning == "model_checkpoint_invalid"
        events = list((await db.scalars(select(SimulationOutbox))).all())
        assert (
            len(events) == 1
            and events[0].envelope["event_type"] == "simulation.cancelled"
        )


async def test_outbox_crash_replays_entire_stable_envelope_in_order(sessions):
    row = await seed(sessions)
    async with sessions() as db:
        row = await db.get(Simulation, row.simulation_id)
        repo = SimulationRepository(db)
        repo.enqueue(row, "simulation.started", str(uuid.uuid4()))
        row.revision += 1
        repo.enqueue(row, "simulation.paused", str(uuid.uuid4()))
        await db.commit()
    published = []

    async def unlocked(envelope):
        # Persistence F28: the claim transaction committed before Redis I/O, so another
        # session can lock the row immediately (NOWAIT raises if a lock is still held).
        async with sessions() as probe:
            assert await probe.scalar(select(SimulationOutbox.event_id).where(
                SimulationOutbox.event_id == uuid.UUID(envelope["event_id"]),
            ).with_for_update(nowait=True)) is not None
            await probe.rollback()

    async def lost_ack(stream, envelope):
        await unlocked(envelope)
        published.append((stream, copy.deepcopy(envelope)))
        raise ConnectionError("Lost Redis ack")

    async def delivered(stream, envelope):
        await unlocked(envelope)
        published.append((stream, copy.deepcopy(envelope)))

    redis = AsyncMock()
    redis.xadd.side_effect = lost_ack
    worker = SimulationWorker(sessions=sessions, redis=redis)
    with pytest.raises(ConnectionError):
        await worker.publish_one()
    redis.xadd.side_effect = delivered
    assert await worker.publish_one()
    assert await worker.publish_one()
    assert published[0] == published[1]
    assert published[2][1]["event_type"] == "simulation.paused"
    assert not await worker.publish_one()
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SimulationOutbox).where(
            SimulationOutbox.published_at.is_(None))) == 0


async def test_completion_gate_failure_is_completed_not_cancelled(sessions):
    config = scenario(
        limits={
            "max_loss_pct": 1.0,
            "max_latency_ms": 1000.0,
            "min_throughput_mbps": 0.5,
        }
    )
    row = await seed(sessions, record(config))
    worker = SimulationWorker(sessions=sessions, redis=None, batch_ticks=32)
    await worker.run_one()
    async with sessions() as db:
        current = await db.get(Simulation, row.simulation_id)
        assert (
            current.state == current.status == "completed"
            and current.risk_gate == "blocked"
        )
        event = await db.scalar(select(SimulationOutbox))
        assert event.envelope["event_type"] == "simulation.completed"


@pytest.fixture
async def accepted_execution(sessions, monkeypatch, mailbox_settings, fake_redis):  # noqa: F811
    """Real acceptance/ORM/evidence service; trusted observation and auth are test doubles, no lab."""
    intent_id, workspace_id, network_id, actor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), str(uuid.uuid4())
    requester = str(uuid.uuid4())  # ADR-028 four-eyes: approver != requester
    plan = LabIntent.model_validate(payload()).normalize()
    binding = SimpleNamespace(topology_id="test-only", model_dump=lambda **_: {"network_id": str(network_id)})
    snapshot_value = {"run_id": str(uuid.uuid4()), "sequence": 7, "observed_at": "now",
                      "links": [{"src_dpid": "a", "src_port": 1, "dst_dpid": "b", "dst_port": 2}]}
    snapshot = SimpleNamespace(run_id=uuid.UUID(snapshot_value["run_id"]), model_dump=lambda **_: copy.deepcopy(snapshot_value))
    prepare = AsyncMock(return_value=(plan, binding, snapshot))
    monkeypatch.setattr("app.modules.intent.execution.prepare_plan", prepare)
    monkeypatch.setattr("app.modules.intent.worker.prepare_plan", prepare)
    monkeypatch.setattr("app.modules.intent.execution.get_settings", lambda: mailbox_settings)
    monkeypatch.setattr("app.modules.organization.service.WorkspaceService.get_active_workspace",
                        AsyncMock(return_value=SimpleNamespace(org_id=uuid.uuid4())))
    monkeypatch.setattr("app.modules.network.service.NetworkService.assert_network_workspace_access", AsyncMock())
    now = datetime.now(UTC)
    # C18: limits must respect the server policy floors to count as evidence.
    config = policy_scenario(action_binding={"intent_id": str(intent_id), "plan_sha256": digest(plan.model_dump(mode="json")),
        "network_state_sha256": current_network_state_hash(binding=binding, snapshot=snapshot)})
    simulation = record(config, complete=True, workspace_id=workspace_id, network_id=network_id)
    async with sessions() as db:
        db.add(Intent(intent_id=intent_id, workspace_id=workspace_id, network_id=network_id, intent_kind="reroute_path",
            intent_payload=payload(), status="validated", validation_result={}, execution_provenance={}, explainability={},
            correlation_id=uuid.uuid4(), requested_by_user_id=requester, requested_at=now))
        db.add(simulation)
        await db.commit()
    args = {"workspace_id": workspace_id, "intent_id": intent_id, "idempotency_key": "bound-test",
        "correlation_id": uuid.uuid4(), "actor_id": actor_id, "permissions": ["write:config", "execute:rollback"],
        "manual_approval": True, "cancel": False, "simulation_id": simulation.simulation_id,
        "approval_binding": {"plan_hash": digest(plan.model_dump(mode="json")),
                             "binding_digest": digest({"network_id": str(network_id)}),
                             "run_id": snapshot_value["run_id"]}}
    async with sessions() as db:
        await accept_execution(db=db, redis=fake_redis, **args)
        job = await db.scalar(select(IntentExecution))
        original_evidence = copy.deepcopy(job.simulation_evidence)
        assert original_evidence["network_state_sha256"] == config.action_binding.network_state_sha256
        assert original_evidence["evidence_expires_at"] == simulation.evidence_expires_at.isoformat()
        assert original_evidence["checkpoint_sha256"] == simulation.checkpoint["checkpoint_sha256"]
        provenance = (await db.get(Intent, intent_id)).execution_provenance
        assert provenance["approved_plan"] == job.command["plan"]
        assert provenance["simulation_id"] == str(simulation.simulation_id)
        assert original_evidence["policy_floors"]["max_loss_pct"] == 1.0
    worker = ExecutionWorker(settings=mailbox_settings, sessions=sessions, redis=fake_redis)
    worker.mailbox = MagicMock()
    worker.mailbox.read = AsyncMock(side_effect=OSError("test stops after publication, no lab"))
    return SimpleNamespace(worker=worker, args=args, job=job, snapshot=snapshot_value, evidence=original_evidence,
        sessions=sessions, redis=fake_redis, simulation=simulation, prepare=prepare)


@pytest.mark.parametrize("fault", ["topology", "expiry", "state", "output", "command", "missing_command", "lost_lease",
                                   "none", "counters_only"])
async def test_bound_execution_revalidates_before_first_mailbox(accepted_execution, fault):
    ctx = accepted_execution
    if fault == "topology":
        ctx.snapshot["links"].append({"src_dpid": "b", "src_port": 2, "dst_dpid": "c", "dst_port": 3})
    elif fault == "counters_only":
        # ADR-028: the v2 state hash is a stable projection; new samples do not stale evidence.
        ctx.snapshot.update(sequence=ctx.snapshot["sequence"] + 5, observed_at="later")
    async with ctx.sessions() as db:
        simulation = await db.get(Simulation, ctx.simulation.simulation_id)
        job = await db.get(IntentExecution, ctx.job.execution_id)
        if fault == "expiry":
            simulation.evidence_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif fault == "state":
            simulation.state = "paused"
        elif fault == "output":
            simulation.run_output = {**simulation.run_output, "output_sha256": "0" * 64}
        elif fault == "command":
            changed = copy.deepcopy(job.command)
            changed["plan"]["paths"] = [["different"]]
            job.command = changed
        elif fault == "missing_command":
            job.command = {}
        await db.commit()
        claimed = await ExecutionRepository(db).claim(ctx.worker.owner, 15)
        await db.commit()
    lost = LeaseAuthority(time.monotonic() + 10)
    if fault == "lost_lease":
        lost.set()
    await ctx.worker._reconcile(claimed, lost)
    async with ctx.sessions() as db:
        job = await db.get(IntentExecution, ctx.job.execution_id)
        assert job.simulation_evidence == ctx.evidence
        if fault in {"none", "counters_only"}:
            ctx.worker.mailbox.write.assert_called_once()
            sent = ctx.worker.mailbox.write.call_args.args[0]
            assert sent.dispatch_expires_at <= datetime.fromisoformat(ctx.evidence["evidence_expires_at"])
            assert job.dispatched_at is not None
        else:
            ctx.worker.mailbox.write.assert_not_called()
            assert job.dispatched_at is None
            assert job.phase == ("accepted" if fault == "lost_lease" else "failed")
        if fault in {"command", "missing_command"}:
            assert (await db.get(Intent, job.intent_id)).execution_provenance["approved_plan"] is None


async def test_evidence_database_immutable_and_replay_reference_identity(accepted_execution):
    ctx = accepted_execution
    async with ctx.sessions() as db:
        with pytest.raises(DBAPIError, match="immutable"):
            await db.execute(update(IntentExecution).values(simulation_evidence=None))
        await db.rollback()
    async with ctx.sessions() as db:
        _, replay = await accept_execution(db=db, redis=ctx.redis, **ctx.args)
        assert replay
    async with ctx.sessions() as db:
        with pytest.raises(HTTPException) as error:
            await accept_execution(db=db, redis=ctx.redis, **{**ctx.args, "simulation_id": None})
        assert error.value.status_code == 409
    replacement = record(scenario(action_binding=ctx.simulation.scenario_config["action_binding"]), complete=True,
                         workspace_id=ctx.simulation.workspace_id, network_id=ctx.simulation.network_id)
    await seed(ctx.sessions, replacement)
    async with ctx.sessions() as db:
        with pytest.raises(HTTPException) as error:
            await accept_execution(db=db, redis=ctx.redis, **{**ctx.args, "simulation_id": replacement.simulation_id})
        assert error.value.status_code == 409


async def test_expired_reference_does_not_block_cancellation(accepted_execution):
    ctx = accepted_execution
    async with ctx.sessions() as db:
        row = await db.get(Simulation, ctx.simulation.simulation_id)
        row.evidence_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    async with ctx.sessions() as db:
        await accept_execution(db=db, redis=ctx.redis, **{**ctx.args, "cancel": True})
        job = await ExecutionRepository(db).claim(ctx.worker.owner, 15)
        await db.commit()
    await ctx.worker._reconcile(job, LeaseAuthority(time.monotonic() + 10))
    ctx.worker.mailbox.write.assert_not_called()
    async with ctx.sessions() as db:
        assert (await db.get(IntentExecution, ctx.job.execution_id)).phase == "cancelled"


async def test_approved_plan_projection_is_deep_copy_not_editable_intent(accepted_execution):
    ctx = accepted_execution
    async with ctx.sessions() as db:
        job = await db.get(IntentExecution, ctx.job.execution_id)
        intent = await db.get(Intent, job.intent_id)
        intent.intent_payload = {"arbitrary": "edited intent"}
        project_execution(intent, job)
        expected = copy.deepcopy(job.command["plan"])
        assert intent.execution_provenance["approved_plan"] == expected
        intent.execution_provenance["approved_plan"]["paths"][0][0] = "edited projection"
        assert job.command["plan"] == expected


async def test_stale_reference_also_blocks_same_idempotent_replay(accepted_execution):
    ctx = accepted_execution
    ctx.snapshot["links"].clear()  # topology changed since the evidence was produced
    async with ctx.sessions() as db:
        with pytest.raises(HTTPException) as error:
            await accept_execution(db=db, redis=ctx.redis, **ctx.args)
        assert error.value.status_code == 409
    ctx.worker.mailbox.write.assert_not_called()


async def test_delayed_mailbox_callback_cannot_outlive_evidence(accepted_execution, monkeypatch):
    ctx = accepted_execution
    async with ctx.sessions() as db:
        claimed = await ExecutionRepository(db).claim(ctx.worker.owner, 15)
        await db.commit()
    observed = []

    async def delayed_thread(function, command, *, can_publish):
        observed.append(can_publish())
        # Model a scheduling pause after dispatch authority is committed but before
        # the filesystem thread can publish. No real sleeping/lab mutation needed.
        class Later:
            @staticmethod
            def now(tz):
                return datetime.fromisoformat(ctx.evidence["evidence_expires_at"]) + timedelta(seconds=1)
        monkeypatch.setattr("app.modules.intent.worker.datetime", Later)
        observed.append(can_publish())
        raise ValueError("publication authority expired")

    monkeypatch.setattr("app.modules.intent.worker.asyncio.to_thread", delayed_thread)
    with pytest.raises(ValueError, match="expired"):
        await ctx.worker._reconcile(claimed, LeaseAuthority(time.monotonic() + 10))
    assert observed == [True, False]
    ctx.worker.mailbox.write.assert_not_called()
    # Dispatch possibility was committed before I/O; recovery must not resubmit.
    async with ctx.sessions() as db:
        job = await db.get(IntentExecution, claimed.execution_id)
        assert job.dispatched_at is not None and job.phase == "dispatching"


async def test_fair_claim_interleaves_workspaces(sessions):
    busy, quiet = uuid.uuid4(), uuid.uuid4()
    for _ in range(3):
        await seed(sessions, record(workspace_id=busy))
    lone = await seed(sessions, record(workspace_id=quiet))
    first, second = await claim(sessions), await claim(sessions)
    # Global FIFO would have served all three busy-workspace jobs first.
    assert {first.workspace_id, second.workspace_id} == {busy, quiet}
    assert lone.simulation_id in {first.simulation_id, second.simulation_id}


async def test_claim_attempts_cap_marks_poison_job_failed(sessions):
    row = await seed(sessions)
    async with sessions() as db:
        await db.execute(update(Simulation).values(claim_attempts=5))
        await db.commit()
    async with sessions() as db:
        assert await SimulationRepository(db).claim(max_attempts=5) is None
        await db.commit()  # the worker persists exhaustions even when nothing is runnable
    async with sessions() as db:
        current = await db.get(Simulation, row.simulation_id)
        assert (current.state, current.warning) == ("failed", "attempts_exhausted")
        event = await db.scalar(select(SimulationOutbox))
        assert event.envelope["event_type"] == "simulation.cancelled"
