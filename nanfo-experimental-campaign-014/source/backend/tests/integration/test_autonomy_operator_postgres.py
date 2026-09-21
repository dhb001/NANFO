"""ADR-018 real migration/CAS/Intent recovery tests in UUID-owned disposable schemas."""

import asyncio
import copy
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.modules.autonomy.configuration import ConfigurationService
from app.modules.autonomy.models import AutonomyControl, ConfigurationRevision, TimedOverride
from app.modules.autonomy.overrides import OverrideService, OverrideWorker
from app.modules.autonomy.repository import AutonomyRepository
from app.modules.autonomy.schemas import CreateOverrideRequest, ReturnOverrideRequest, SetConfigurationRequest
from app.modules.autonomy.service import AutonomyService
from app.modules.intent.lab import LabResult, digest
from app.modules.intent.models import Intent, IntentExecution, IntentOutbox
from app.modules.intent.overrides import IntentOverrideService
from tests.autonomy_support import control_record, qualified_providers
from tests.integration.test_autonomy_postgres import migrated_sessions  # noqa: F401
from tests.unit.test_intent_lab import command

pytestmark = pytest.mark.skipif(not os.environ.get("AUTONOMY_TEST_DSN"), reason="AUTONOMY_TEST_DSN not configured")


@pytest.fixture
async def context(migrated_sessions, monkeypatch):  # noqa: F811 - imported pytest fixture
    control = control_record(mode="monitor", claim_token=None, lease_expires_at=None)
    cmd = command()
    now = datetime.now(UTC)
    intent = Intent(intent_id=uuid.uuid4(), workspace_id=control.workspace_id, network_id=control.network_id,
        intent_kind="reroute_path", intent_payload={}, status="execution_completed", validation_result={},
        execution_provenance={}, explainability={}, correlation_id=uuid.uuid4(), requested_by_user_id=control.approved_by_user_id,
        requested_at=now)
    job = IntentExecution(execution_id=cmd.execution_id, intent_id=intent.intent_id, workspace_id=control.workspace_id,
        org_id=uuid.uuid4(), request_key="manual", request_hash="d" * 64, lab_key="test_lab", actor_id=control.approved_by_user_id,
        approved_at=now - timedelta(seconds=1), command=cmd.model_dump(mode="json"), phase="completed", blocks_lab=False,
        cancel_requested=False, dispatched_at=now, fence=1, outbox_sequence=0)
    async with migrated_sessions() as db:
        db.add(control)
        db.add(intent)
        await db.flush()
        db.add(job)
        await db.commit()
    auth = AsyncMock(return_value=(control, ["read:telemetry", "write:config", "execute:rollback"]))
    monkeypatch.setattr("app.modules.autonomy.service.authorize", auth)
    monkeypatch.setattr("app.modules.autonomy.overrides.authorize", auth)
    inspector = AsyncMock()
    async def inspect(**kwargs):
        return {**{key: str(kwargs[key]) for key in ("override_id", "network_id", "workspace_id", "intent_id", "execution_id")},
            "actor_id": kwargs["actor_id"], "command_sha256": digest(job.command), "plan_hash": cmd.plan_hash,
            "binding_digest": cmd.binding_digest, "run_id": str(cmd.run_id),
            "configuration_verified_at": datetime.now(UTC).isoformat(), "capability": uuid.uuid4().hex * 2}
    inspector.inspect_override_execution.side_effect = inspect
    return SimpleNamespace(sessions=migrated_sessions, control=control, cmd=cmd, job=job, auth=auth, inspector=inspector,
        claims=SimpleNamespace(user_id=control.approved_by_user_id, workspace_id=None, org_id=None),
        providers=qualified_providers(control))


async def enroll(context, duration=1, return_mode="monitor"):
    async with context.sessions() as db:
        control = await db.get(AutonomyControl, context.control.network_id)
        request = CreateOverrideRequest(network_id=control.network_id, intent_id=context.job.intent_id,
            execution_id=context.job.execution_id, expected_revision=control.revision, reason="bounded operator test",
            duration_seconds=duration, return_mode=return_mode)
        return await OverrideService(db, None, intent=context.inspector, providers=context.providers).create(
            claims=context.claims, request=request)


async def due(context):
    async with context.sessions() as db:
        await db.execute(update(TimedOverride).values(next_check_at=func.now() - timedelta(seconds=1),
            lease_expires_at=func.now() - timedelta(seconds=1)))
        await db.commit()


async def verified_cancel(context):
    async with context.sessions() as db:
        job = await db.get(IntentExecution, context.job.execution_id)
        result = LabResult(**{key: value for key, value in context.cmd.model_dump().items() if key in LabResult.model_fields},
            status="cancelled", verification={}, rollback={"verified": True, "readback_sha256": "e" * 64},
            failure_reason=None, completed_at=datetime.now(UTC))
        job.result, job.phase, job.blocks_lab = result.model_dump(mode="json"), "cancelled", False
        await db.commit()


async def test_configuration_immutable_revision_conflict_and_actual_worker_interval(context):
    async with context.sessions() as db:
        service = ConfigurationService(db, None, providers=context.providers)
        request = SetConfigurationRequest(network_id=context.control.network_id, expected_revision=0,
            reason="slower safer decisions", operational={"decision_interval_seconds": 71, "max_observation_age_seconds": 2},
            training={"reward_weights": {"delay": -.3}})
        result = await service.put(claims=context.claims, request=request)
        assert result.revision == 1 and result.training_status == "retraining_required" and result.effective_training is None
        assert result.operational.decision_interval_seconds == 71
        with pytest.raises(HTTPException) as error:
            await service.put(claims=context.claims, request=request)
        assert error.value.status_code == 409
        current = await db.get(AutonomyControl, context.control.network_id)
        assert current.mode == "monitor"
        claimed, _ = await AutonomyRepository(db).claim()
        assert 69 < (claimed.next_cycle_at - datetime.now(UTC)).total_seconds() <= 71
        with pytest.raises(DBAPIError):
            await db.execute(update(ConfigurationRevision).values(reason="rewrite history"))
        await db.rollback()


async def test_expiry_restart_revocation_no_execution_replay(context):
    row = await enroll(context)
    context.auth.side_effect = HTTPException(403, "revoked")
    worker = OverrideWorker(sessions=context.sessions, redis=None, providers=context.providers)
    assert await worker.run_one()
    async with context.sessions() as db:
        stored = await db.get(TimedOverride, row.override_id)
        job = await db.get(IntentExecution, context.job.execution_id)
        assert stored.status == "restoring" and stored.restoration_attempts == 1
        assert job.cancel_requested and job.blocks_lab and job.cancelled_by_user_id is None
        assert job.command == context.job.command
        assert await db.scalar(select(func.count()).select_from(IntentExecution)) == 1
        events = await db.scalar(select(func.count()).select_from(IntentOutbox))
        reference = copy.deepcopy(stored.recovery_reference)
    await due(context)
    assert await OverrideWorker(sessions=context.sessions, redis=None, providers=context.providers).run_one()
    async with context.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(IntentOutbox)) == events
        reference["capability"] = "bad"
        with pytest.raises(HTTPException) as error:
            await IntentOverrideService(db, None).restore_override(reference)
        assert error.value.status_code == 403
    await verified_cancel(context)
    await due(context)
    await worker.run_one()
    async with context.sessions() as db:
        stored = await db.get(TimedOverride, row.override_id)
        assert stored.status == "return_blocked" and stored.restored_at
        assert "return_actor_unauthorized" in stored.reasons
        assert (await db.get(AutonomyControl, row.network_id)).mode == "monitor"
        assert await db.scalar(select(func.count()).select_from(IntentExecution)) == 1


async def test_concurrent_claim_and_fenced_expiry(context):
    row = await enroll(context, duration=30)
    async def claim():
        async with context.sessions() as db:
            return await AutonomyRepository(db).claim_override()
    results = await asyncio.gather(claim(), claim())
    assert sum(row is not None for row in results) == 1
    old = next(row for row in results if row)
    await due(context)
    new = await claim()
    async with context.sessions() as db:
        assert await AutonomyRepository(db).owned_override(row.override_id, old.claim_token) is None
        assert await AutonomyRepository(db).owned_override(row.override_id, new.claim_token)


async def test_expiry_stop_dominates_and_cancel_is_idempotent(context):
    row = await enroll(context)
    await asyncio.sleep(1.05)
    worker = OverrideWorker(sessions=context.sessions, redis=None, providers=context.providers)
    await worker.run_one()
    async with context.sessions() as db:
        stored = await db.get(TimedOverride, row.override_id)
        assert "override_expired" in stored.reasons and stored.status == "restoring"
        service = OverrideService(db, None, providers=context.providers)
        first = await service.cancel(claims=context.claims, override_id=row.override_id)
        second = await service.cancel(claims=context.claims, override_id=row.override_id)
        assert first.cancellation_requested_at == second.cancellation_requested_at
        await AutonomyService(db, None, providers=context.providers).stop(claims=context.claims, network_id=row.network_id)
    await verified_cancel(context)
    await due(context)
    await worker.run_one()
    async with context.sessions() as db:
        stored = await db.get(TimedOverride, row.override_id)
        control = await db.get(AutonomyControl, row.network_id)
        assert stored.status == "return_blocked" and control.emergency_stopped
        assert "emergency_stop_latched" in stored.reasons
        result = await OverrideService(db, None, providers=context.providers).return_mode(claims=context.claims,
            override_id=row.override_id, request=ReturnOverrideRequest(expected_revision=control.revision, reason="fresh request"))
        assert result.status == "return_blocked"
        assert control.emergency_stopped


async def test_cancelled_unknown_reopens_intent_gate_until_verified(context):
    row = await enroll(context)
    async with context.sessions() as db:
        await OverrideService(db, None, providers=context.providers).cancel(claims=context.claims, override_id=row.override_id)
        job = await db.get(IntentExecution, context.job.execution_id)
        job.phase, job.blocks_lab, job.cancel_requested = "cancelled", False, True
        await db.commit()
    await OverrideWorker(sessions=context.sessions, redis=None, providers=context.providers).run_one()
    async with context.sessions() as db:
        job = await db.get(IntentExecution, context.job.execution_id)
        assert job.blocks_lab and job.phase == "cancelling"
        assert (await db.get(TimedOverride, row.override_id)).status == "restoring"


async def test_enrollment_stop_race_never_mutates_execute(context):
    original = context.inspector.inspect_override_execution.side_effect
    async def inspect(**kwargs):
        reference = await original(**kwargs)
        async with context.sessions() as db:
            await AutonomyService(db, None, providers=context.providers).stop(claims=context.claims, network_id=context.control.network_id)
        return reference
    context.inspector.inspect_override_execution.side_effect = inspect
    with pytest.raises(HTTPException) as error:
        await enroll(context)
    assert error.value.status_code == 409
    async with context.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(TimedOverride)) == 0
        assert (await db.get(AutonomyControl, context.control.network_id)).emergency_stopped
        assert not (await db.get(IntentExecution, context.job.execution_id)).cancel_requested


async def test_recovery_capability_and_enrollment_are_immutable(context):
    row = await enroll(context)
    async with context.sessions() as db:
        stored = await db.get(TimedOverride, row.override_id)
        with pytest.raises(HTTPException):
            await IntentOverrideService(db, None).restore_override(stored.recovery_reference)
        with pytest.raises(DBAPIError):
            await db.execute(update(TimedOverride).values(execution_id=uuid.uuid4()))
        await db.rollback()
        assert await db.scalar(text("SELECT version_num FROM alembic_version")) == "0015"


@pytest.mark.parametrize("readiness_fault", ["missing", "stale", "stop_race", "ready"])
async def test_autonomous_return_requires_current_live_readiness_and_stop_dominates(context, readiness_fault):
    async with context.sessions() as db:
        control = await db.get(AutonomyControl, context.control.network_id)
        control.mode = "autonomous"
        await db.commit()
    row = await enroll(context, duration=10, return_mode="autonomous")
    async with context.sessions() as db:
        await OverrideService(db, None, providers=context.providers).cancel(claims=context.claims, override_id=row.override_id)
    worker = OverrideWorker(sessions=context.sessions, redis=None, providers=context.providers)
    await worker.run_one()
    await verified_cancel(context)
    if readiness_fault == "missing":
        context.providers.model.qualify.side_effect = RuntimeError("unavailable")
    elif readiness_fault == "stale":
        context.providers.observer.observe.return_value = context.providers.observer.observe.return_value.model_copy(
            update={"observed_at": datetime.now(UTC) - timedelta(minutes=2)})
    elif readiness_fault == "stop_race":
        async def observe(*_):
            async with context.sessions() as db:
                service = AutonomyService(db, None, providers=context.providers)
                service.snapshot = AsyncMock()
                await service.stop(claims=context.claims, network_id=row.network_id)
            return context.providers.observer.observe.return_value
        context.providers.observer.observe.side_effect = observe
    await due(context)
    await worker.run_one()
    async with context.sessions() as db:
        stored = await db.get(TimedOverride, row.override_id)
        control = await db.get(AutonomyControl, row.network_id)
        assert stored.restored_at
        if readiness_fault == "ready":
            assert stored.status == "returned" and control.mode == "autonomous"
        else:
            assert stored.status == "return_blocked" and control.mode == "monitor"
        if readiness_fault == "stop_race":
            assert control.emergency_stopped and "emergency_stop_latched" in stored.reasons
        assert await db.scalar(select(func.count()).select_from(IntentExecution)) == 1
    context.providers.executor.accept.assert_not_awaited()


async def test_enrollment_replay_and_mode_change_cannot_bypass_exclusion(context):
    from app.modules.autonomy.schemas import SetAutonomyRequest

    row = await enroll(context, duration=30)
    with pytest.raises(HTTPException):
        await enroll(context, duration=30)
    async with context.sessions() as db:
        with pytest.raises(HTTPException):
            await AutonomyService(db, None, providers=context.providers).set_mode(claims=context.claims,
                request=SetAutonomyRequest(network_id=row.network_id, expected_revision=row.hold_revision, mode="monitor"))
        assert await db.scalar(select(func.count()).select_from(TimedOverride)) == 1
        assert await db.scalar(select(func.count()).select_from(IntentOutbox)) == 0


async def test_restart_between_restoration_and_return_recovers(context):
    row = await enroll(context)
    async with context.sessions() as db:
        stored = await db.get(TimedOverride, row.override_id)
        stored.status, stored.restored_at = "restored", datetime.now(UTC)
        stored.claim_token, stored.lease_expires_at = None, None
        await db.commit()
    await OverrideWorker(sessions=context.sessions, redis=None, providers=context.providers).run_one()
    async with context.sessions() as db:
        assert (await db.get(TimedOverride, row.override_id)).status == "returned"


async def test_explicit_return_revision_conflict_has_no_mutation(context):
    row = await enroll(context)
    async with context.sessions() as db:
        with pytest.raises(HTTPException) as error:
            await OverrideService(db, None, providers=context.providers).return_mode(claims=context.claims,
                override_id=row.override_id, request=ReturnOverrideRequest(expected_revision=0, reason="stale"))
        assert error.value.status_code == 409
        assert (await db.get(TimedOverride, row.override_id)).status == "holding"
