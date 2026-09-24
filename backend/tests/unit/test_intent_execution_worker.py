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


async def test_deferred_intent_sweep_runs_in_the_worker_and_is_isolated(worker_case, monkeypatch):
    worker, _, _ = worker_case
    sweep = AsyncMock(return_value=2)
    monkeypatch.setattr("app.modules.intent.worker.republish_deferred_intents", sweep)
    assert await worker.sweep_deferred() == 2
    assert sweep.await_args.kwargs["redis"] is worker.redis
    sweep.side_effect = RuntimeError("database unavailable")
    assert await worker.sweep_deferred() == 0  # never escapes into the outbox publish loop


class _Log:
    """Ordered log of session transactions and Redis calls (ADR-028 unit of work)."""

    def __init__(self):
        self.entries: list[str] = []
        self.open = 0

    def sessions(self):
        log = self

        class Session:
            async def __aenter__(self):
                log.open += 1
                log.entries.append("begin")
                return self

            async def __aexit__(self, *exc):
                log.open -= 1
                log.entries.append("end")

            async def commit(self):
                log.entries.append("commit")

            async def rollback(self):
                log.entries.append("rollback")

        return Session()


def _outbox_row():
    import uuid

    event_id = uuid.uuid4()
    return SimpleNamespace(event_id=event_id, envelope={"event_id": str(event_id), "event_type": "intent.execution_started"})


@pytest.mark.parametrize("acknowledged", [True, False])
async def test_outbox_publication_commits_the_lease_before_a_bounded_xadd(
    worker_case, monkeypatch, acknowledged,
):
    worker, _, _ = worker_case
    log, row = _Log(), _outbox_row()
    worker.sessions = log.sessions
    worker.settings.EMULATION_EXECUTION_LEASE_SECONDS = 15
    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.claim_event",
                        AsyncMock(side_effect=lambda owner, seconds: log.entries.append(f"claim:{seconds}") or row))
    ack = AsyncMock(side_effect=lambda event_id, owner: log.entries.append("ack") or acknowledged)
    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.acknowledge_event", ack)
    warnings = MagicMock()
    monkeypatch.setattr("app.modules.intent.worker.logger", warnings)

    async def xadd(stream, envelope):
        assert log.open == 0 and envelope == row.envelope and envelope is not row.envelope
        log.entries.append(f"xadd:{stream}")

    worker.redis = SimpleNamespace(xadd=AsyncMock(side_effect=xadd))
    assert await worker.publish_one() is True
    assert log.entries == ["begin", "claim:15", "commit", "end", "xadd:stream:intent", "begin", "ack", "commit", "end"]
    assert ack.await_args.args == (row.event_id, worker.owner)
    assert warnings.warning.called is (not acknowledged)
    if not acknowledged:
        assert warnings.warning.call_args.args[0] == "intent_outbox_lease_lost"
        assert warnings.warning.call_args.kwargs["event_id"] == str(row.event_id)


async def test_outbox_xadd_is_bounded_below_the_publication_lease(worker_case, monkeypatch):
    worker, _, _ = worker_case
    log = _Log()
    worker.sessions = log.sessions
    worker.settings.EMULATION_EXECUTION_LEASE_SECONDS = 0.1  # timeout = min(10 s, lease / 2)
    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.claim_event", AsyncMock(return_value=_outbox_row()))
    ack = AsyncMock(return_value=True)
    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.acknowledge_event", ack)

    async def hang(*args):
        await asyncio.Event().wait()

    worker.redis = SimpleNamespace(xadd=AsyncMock(side_effect=hang))
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        await worker.publish_one()
    assert time.monotonic() - started < 1
    ack.assert_not_awaited()


async def test_nothing_to_publish_opens_no_redis_call(worker_case, monkeypatch):
    worker, _, _ = worker_case
    log = _Log()
    worker.sessions = log.sessions
    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.claim_event", AsyncMock(return_value=None))
    worker.redis = SimpleNamespace(xadd=AsyncMock())
    assert await worker.publish_one() is False
    worker.redis.xadd.assert_not_awaited()
    assert log.entries == ["begin", "end"]


async def test_job_claim_is_committed_before_the_lab_lock_is_requested(worker_case, monkeypatch):
    worker, job, _ = worker_case
    job.lab_key = "campus"
    log = _Log()
    worker.sessions = log.sessions
    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.claim",
                        AsyncMock(side_effect=lambda owner, seconds: log.entries.append("claim") or job))

    async def lab_lock(*args, **kwargs):
        assert log.open == 0
        log.entries.append("lab_lock")
        return False  # another worker holds the lab: nothing else runs

    worker.redis = SimpleNamespace(set=AsyncMock(side_effect=lab_lock))
    assert await worker.run_one() is False
    assert log.entries == ["begin", "claim", "commit", "end", "lab_lock"]


@pytest.mark.parametrize("renewed", [True, False])
async def test_lease_renewal_commits_only_a_successful_fenced_update(worker_case, monkeypatch, renewed):
    worker, job, _ = worker_case
    worker.settings.EMULATION_EXECUTION_LEASE_SECONDS = 0.3
    log = _Log()
    worker.sessions = log.sessions
    calls = []

    async def renew(*args):
        calls.append(args)
        log.entries.append("renew")
        if len(calls) > 1:
            lost.set()
        return renewed

    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.renew", AsyncMock(side_effect=renew))
    worker.redis = SimpleNamespace(eval=AsyncMock(return_value=1))
    lost = LeaseAuthority(time.monotonic() + 5)
    async with asyncio.timeout(2):
        await worker._renew(job, "lab", "token", lost)
    assert lost.is_set()
    if renewed:
        assert log.entries[:4] == ["begin", "renew", "commit", "end"]
    else:
        assert log.entries == ["begin", "renew", "end"]  # lost lease: nothing committed


# Intent outbox retention (ADR-028): published rows older than INTENT_OUTBOX_RETENTION_DAYS. ----

class _Clock:
    def __init__(self):
        self.now = 500.0

    def __call__(self):
        return self.now


async def test_intent_outbox_retention_is_bounded_rate_limited_and_drains_backlogs(worker_case, monkeypatch):
    worker, _, _ = worker_case
    log, clock, calls = _Log(), _Clock(), []
    worker.sessions, worker._clock, worker.retention_batch = log.sessions, clock, 2
    results = iter([2, 1, 0])

    async def purge(self, *, older_than, limit):
        assert log.open == 1
        calls.append((older_than, limit))
        log.entries.append("purge")
        return next(results)

    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.purge_published_events", purge)
    assert worker.retention_days == 30  # documented default
    assert await worker.purge_published() == 2  # full batch: due again at once
    assert await worker.purge_published() == 1
    assert await worker.purge_published() == 0 and len(calls) == 2  # not due before the interval
    clock.now += worker.retention_interval_seconds
    assert await worker.purge_published() == 0 and len(calls) == 3
    assert calls[0] == (timedelta(days=30), 2)
    assert log.entries[:4] == ["begin", "purge", "commit", "end"]


@pytest.mark.parametrize("configured", [0, -3, "30", True])
async def test_intent_outbox_retention_zero_or_invalid_never_deletes(worker_case, monkeypatch, configured):
    worker, _, _ = worker_case
    worker.settings = SimpleNamespace(INTENT_OUTBOX_RETENTION_DAYS=configured)
    purge = AsyncMock()
    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.purge_published_events", purge)
    assert worker.retention_days is None
    assert await worker.purge_published() == 0
    purge.assert_not_awaited()


async def test_intent_outbox_retention_failure_is_isolated(worker_case, monkeypatch):
    worker, _, _ = worker_case
    log = _Log()
    worker.sessions = log.sessions
    monkeypatch.setattr("app.modules.intent.worker.ExecutionRepository.purge_published_events",
                        AsyncMock(side_effect=ConnectionError("db restarting")))
    warnings = MagicMock()
    monkeypatch.setattr("app.modules.intent.worker.logger", warnings)
    assert await worker.purge_published() == 0
    assert warnings.warning.call_args.args[0] == "intent_outbox_retention_deferred"
    assert warnings.warning.call_args.kwargs["error_type"] == "ConnectionError"


async def test_publish_loop_applies_retention_every_iteration(worker_case, monkeypatch):
    worker, _, _ = worker_case
    worker.publish_one = AsyncMock(return_value=False)
    worker.sweep_deferred = AsyncMock(return_value=0)
    worker.purge_published = AsyncMock(return_value=0)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await worker._publish_loop()
    worker.purge_published.assert_awaited_once()
