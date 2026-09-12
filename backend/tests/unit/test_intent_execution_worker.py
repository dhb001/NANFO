"""Worker boundaries with deterministic services; real leases covered in PostgreSQL gate."""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.intent.lab import LabResult
from app.modules.intent.worker import ExecutionWorker, LeaseAuthority
from tests.unit.test_intent_lab import command, mailbox_settings  # noqa: F401


@pytest.fixture
def worker_case(monkeypatch, mailbox_settings, fake_redis):  # noqa: F811 - imported pytest fixture
    cmd = command()
    job = SimpleNamespace(execution_id=cmd.execution_id, command=cmd.model_dump(mode="json"),
        dispatched_at=datetime.now(UTC), approved_at=datetime.now(UTC) - timedelta(seconds=1),
        fence=5, cancel_requested=False)
    db = AsyncMock()
    factory = MagicMock(return_value=db)
    db.__aenter__.return_value = db
    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.owned", AsyncMock(return_value=job))
    worker = ExecutionWorker(settings=mailbox_settings, sessions=factory, redis=fake_redis)
    worker._transition = AsyncMock(return_value=True)
    worker.mailbox = MagicMock()
    worker.mailbox.read = AsyncMock()
    result = {key: value for key, value in cmd.model_dump(mode="json").items()
              if key not in {"deadline", "dispatch_expires_at", "operation", "plan"}}
    result.update(status="completed", verification={"readback_verified": True, "readback_sha256": "b" * 64,
        "config_readback_and_reachability": True, "traffic_effects_verified": False,
        "probe": {"sent": 3, "received": 3, "source_host": "h1", "destination_host": "h3"}},
        rollback=None, failure_reason=None, completed_at=datetime.now(UTC))
    return worker, job, result


@pytest.mark.parametrize("fault", ["identity", "fence", "missing_readback", "failed_rollback", "cancel", "late"])
async def test_uncertainty_and_cancel_never_promote_completion(worker_case, fault):
    worker, job, result = worker_case
    if fault == "identity":
        result["plan_hash"] = "c" * 64
    elif fault == "fence":
        result["fence"] = 2
    elif fault == "missing_readback":
        result["verification"] = {"status": "verified"}
    elif fault == "failed_rollback":
        result.update(status="failed", rollback={"verified": False})
    elif fault == "cancel":
        job.cancel_requested = True
    elif fault == "late":
        job.command["deadline"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        job.command["dispatch_expires_at"] = (datetime.now(UTC) - timedelta(seconds=2)).isoformat()
    worker.mailbox.read.return_value = LabResult.model_validate_json(json.dumps(
        {**result, "completed_at": result["completed_at"].isoformat()}))
    await worker._reconcile(job, asyncio.Event())
    assert worker._transition.await_args.kwargs["phase"] == "uncertain"
    assert not worker._transition.await_args.kwargs.get("safe", False)
    if fault in {"cancel", "late"}:
        sent = worker.mailbox.write.call_args.args[0]
        assert sent.operation == "cancel" and sent.fence == 1
        assert sent.plan_hash == job.command["plan_hash"]
    else:
        worker.mailbox.write.assert_not_called()


async def test_verified_compensation_is_terminal(worker_case):
    worker, job, result = worker_case
    result.update(status="cancelled", rollback={"verified": True, "readback_sha256": "d" * 64})
    worker.mailbox.read.return_value = LabResult.model_validate_json(json.dumps(
        {**result, "completed_at": result["completed_at"].isoformat()}))
    await worker._reconcile(job, asyncio.Event())
    assert worker._transition.await_args.kwargs["phase"] == "cancelled"
    assert worker._transition.await_args.kwargs["safe"] is True
    worker.mailbox.write.assert_not_called()


@pytest.mark.parametrize("verified", [True, False])
async def test_deadline_cancel_accepts_already_failed_compensation(worker_case, verified):
    worker, job, result = worker_case
    job.cancel_requested = True
    job.command["deadline"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    job.command["dispatch_expires_at"] = (datetime.now(UTC) - timedelta(seconds=2)).isoformat()
    result.update(status="failed", verification={},
                  rollback={"verified": verified, "readback_sha256": "d" * 64})
    worker.mailbox.read.return_value = LabResult.model_validate_json(json.dumps(
        {**result, "completed_at": result["completed_at"].isoformat()}))
    await worker._reconcile(job, asyncio.Event())
    if verified:
        assert worker._transition.await_args.kwargs["phase"] == "failed"
        assert worker._transition.await_args.kwargs["safe"] is True
        worker.mailbox.write.assert_not_called()
    else:
        assert worker._transition.await_args.kwargs["phase"] == "uncertain"
        assert worker.mailbox.write.call_args.args[0].operation == "cancel"


async def test_cancelled_unknown_retries_exact_cancellation_not_execute(worker_case):
    worker, job, result = worker_case
    job.cancel_requested = True
    result.update(status="cancelled", verification={}, rollback={"verified": False})
    worker.mailbox.read.return_value = LabResult.model_validate_json(json.dumps(
        {**result, "completed_at": result["completed_at"].isoformat()}))
    await worker._reconcile(job, asyncio.Event())
    sent = worker.mailbox.write.call_args.args[0]
    assert sent.operation == "cancel" and sent.execution_id == job.execution_id
    assert sent.model_dump(mode="json") == {**job.command, "operation": "cancel"}
    assert worker._transition.await_args.kwargs["phase"] == "uncertain"


async def test_lost_lease_does_not_publish_or_dispatch(worker_case):
    worker, job, _ = worker_case
    lost = asyncio.Event()
    lost.set()
    await worker._reconcile(job, lost)
    worker.mailbox.write.assert_not_called()
    worker.mailbox.read.assert_not_awaited()
    worker._transition.assert_not_awaited()


@pytest.mark.parametrize("proof", [
    {"mutated": False}, {"no_mutation_verified": True},
    {"no_mutation_verified": True, "readback_verified": True, "readback_sha256": "invalid"},
    {"no_mutation_verified": True, "readback_verified": True, "readback_sha256": "a" * 64,
     "mutated": False, "deadline_expired": False},
])
@pytest.mark.parametrize("status", ["failed", "cancelled"])
async def test_no_mutation_requires_independent_readback(worker_case, proof, status):
    worker, job, result = worker_case
    result.update(status=status, verification=proof)
    worker.mailbox.read.return_value = LabResult.model_validate_json(json.dumps(
        {**result, "completed_at": result["completed_at"].isoformat()}))
    await worker._reconcile(job, asyncio.Event())
    safe = proof.get("readback_sha256") == "a" * 64
    assert worker._transition.await_args.kwargs["safe"] is safe
    assert worker._transition.await_args.kwargs["phase"] == (status if safe else "uncertain")


@pytest.mark.parametrize("blocked", ["redis", "db"])
async def test_stalled_renewal_loses_local_authority(worker_case, monkeypatch, blocked):
    worker, job, _ = worker_case
    worker.settings.EMULATION_EXECUTION_LEASE_SECONDS = .15

    async def stall(*args, **kwargs):
        await asyncio.Event().wait()

    worker.redis = AsyncMock()
    worker.redis.eval = AsyncMock(side_effect=stall if blocked == "redis" else None, return_value=1)
    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.renew", AsyncMock(side_effect=stall))
    lost = LeaseAuthority(time.monotonic() + .15)
    async with asyncio.timeout(.5):
        await worker._renew(job, "lab", "owner", lost)
    assert lost.is_set()


async def test_watchdog_cancels_reconciliation_on_renewal_loss(worker_case, monkeypatch):
    worker, job, _ = worker_case
    worker.settings.EMULATION_EXECUTION_LEASE_SECONDS = .15
    job.lab_key = "test"
    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.claim", AsyncMock(return_value=job))
    worker.redis = AsyncMock()
    worker.redis.set.return_value = True
    worker.redis.eval.return_value = 0
    cancelled = asyncio.Event()

    async def wait(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    worker._reconcile = wait
    async with asyncio.timeout(.5):
        await worker.run_one()
    assert cancelled.is_set()


async def test_cancel_before_dispatch_needs_no_lab_mutation(worker_case, monkeypatch):
    worker, job, _ = worker_case
    job.dispatched_at = None
    job.command.pop("dispatch_expires_at")
    job.cancel_requested = True
    job.intent_id = command().execution_id
    monkeypatch.setattr("app.modules.intent.worker.IntentRepository.get_by_id", AsyncMock(return_value=SimpleNamespace(
        intent_payload={}, network_id=None, workspace_id=None)))
    await worker._reconcile(job, asyncio.Event())
    assert worker._transition.await_args.kwargs == {
        "phase": "cancelled", "reason": "cancelled_before_dispatch", "safe": True,
    }
    worker.mailbox.write.assert_not_called()


async def test_recovery_accepts_prepared_completion_after_dispatch_expiry_without_resubmit(worker_case):
    worker, job, result = worker_case
    job.command["dispatch_expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    worker.mailbox.read.return_value = LabResult.model_validate_json(json.dumps(
        {**result, "completed_at": result["completed_at"].isoformat()}))
    await worker._reconcile(job, asyncio.Event())
    assert worker._transition.await_args.kwargs["phase"] == "completed"
    assert worker._transition.await_args.kwargs["safe"] is True
    worker.mailbox.write.assert_not_called()


async def test_recovery_cancellation_preserves_expired_dispatch_authorization(worker_case):
    worker, job, _ = worker_case
    expiry = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    job.command["dispatch_expires_at"] = expiry
    job.cancel_requested = True
    worker.mailbox.read.return_value = None
    await worker._reconcile(job, asyncio.Event())
    sent = worker.mailbox.write.call_args.args[0]
    assert sent.operation == "cancel"
    assert sent.dispatch_expires_at == datetime.fromisoformat(expiry)
    assert sent.fence == job.command["fence"]
    assert worker._transition.await_args.kwargs["phase"] == "uncertain"
