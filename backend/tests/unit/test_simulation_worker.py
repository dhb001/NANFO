"""Simulation worker isolation and claim-attempt cap (ADR-028 C20)."""

import asyncio
import importlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.simulation import worker as worker_module
from app.modules.simulation.worker import SimulationWorker, max_claim_attempts


def _sessions(db):
    factory = MagicMock(return_value=db)
    db.__aenter__.return_value = db
    return factory


def test_claim_attempt_cap_defaults_to_five_and_is_configurable(monkeypatch):
    assert max_claim_attempts(SimpleNamespace()) == 5
    assert max_claim_attempts(SimpleNamespace(SIMULATION_MAX_CLAIM_ATTEMPTS=2)) == 2
    monkeypatch.setattr(worker_module, "get_settings", lambda: SimpleNamespace(SIMULATION_MAX_CLAIM_ATTEMPTS=3))
    assert SimulationWorker(sessions=None, redis=None).max_attempts == 3
    with pytest.raises(ValueError):
        SimulationWorker(sessions=None, redis=None, max_attempts=0)


async def test_worker_passes_cap_to_claim(monkeypatch):
    claim = AsyncMock(return_value=None)
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.claim", claim)
    worker = SimulationWorker(sessions=_sessions(AsyncMock()), redis=None, max_attempts=4)
    assert await worker.run_one() is False
    assert claim.await_args.kwargs == {"max_attempts": 4}


async def test_arithmetic_model_failure_is_deterministic_terminal(monkeypatch):
    from tests.simulation_support import record

    row = record()
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.claim", AsyncMock(return_value=row))
    finish = AsyncMock(return_value=True)
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.finish_batch", finish)
    monkeypatch.setattr("app.modules.simulation.worker.advance", MagicMock(side_effect=OverflowError("overflow")))
    assert await SimulationWorker(sessions=_sessions(AsyncMock()), redis=None).run_one() is True
    assert finish.await_args.kwargs["failure"] == "model_checkpoint_invalid"


async def test_script_iteration_isolates_job_and_outbox_failures(monkeypatch):
    script = importlib.import_module("scripts.run_simulation_worker")
    monkeypatch.setattr(script, "FAILURE_BACKOFF_SECONDS", 0)
    worker = SimpleNamespace(run_one=AsyncMock(side_effect=RuntimeError("poison job")),
                             publish_one=AsyncMock(side_effect=[True, ConnectionError("redis down")]))
    assert await script.iteration(worker) is False  # no exception escapes the loop body
    assert worker.publish_one.await_count == 2      # outbox still attempted after a job failure
    worker.run_one = AsyncMock(return_value=True)
    worker.publish_one = AsyncMock(return_value=False)
    assert await script.iteration(worker) is True


async def test_script_plugin_sweep_failure_is_isolated(monkeypatch):
    script = importlib.import_module("scripts.run_simulation_worker")
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(script, "AsyncSessionLocal", MagicMock(return_value=session))
    sweep = AsyncMock(side_effect=RuntimeError("db unavailable"))
    monkeypatch.setattr(script, "republish_deferred_plugin_events", sweep)
    await script.sweep_plugins(redis=object())
    sweep.assert_awaited_once()


class _RecordingSessions:
    """Session factory whose transactions and Redis calls land in one ordered log."""

    def __init__(self):
        self.log: list[str] = []
        self.open = 0

    def __call__(self):
        log, sessions = self.log, self

        class Session:
            async def __aenter__(self):
                sessions.open += 1
                log.append("begin")
                return self

            async def __aexit__(self, *exc):
                sessions.open -= 1
                log.append("end")

            async def commit(self):
                log.append("commit")

            async def rollback(self):
                log.append("rollback")

        return Session()


def _redis_recording(sessions, *, hang=False):
    redis = MagicMock()

    async def xadd(stream, envelope):
        # F28 regression: no session (hence no transaction/row lock) is open during XADD.
        assert sessions.open == 0
        sessions.log.append(f"xadd:{stream}:{envelope['event_id']}")
        if hang:
            await asyncio.Event().wait()

    redis.xadd = AsyncMock(side_effect=xadd)
    return redis


def _event():
    from app.modules.simulation.repository import OutboxEvent

    event_id = uuid.uuid4()
    return OutboxEvent(event_id=event_id, envelope={"event_id": str(event_id), "event_type": "simulation.completed"})


async def test_publish_claims_commits_then_publishes_then_acknowledges(monkeypatch):
    sessions, event = _RecordingSessions(), _event()
    claim = AsyncMock(side_effect=lambda: sessions.log.append("claim") or event)
    ack = AsyncMock(side_effect=lambda event_id: sessions.log.append(f"ack:{event_id}") or True)
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.claim_next_event", claim)
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.acknowledge_event", ack)
    worker = SimulationWorker(sessions=sessions, redis=_redis_recording(sessions), max_attempts=5,
                              retention_days=None)
    assert await worker.publish_one() is True
    assert sessions.log == ["begin", "claim", "commit", "end", f"xadd:stream:simulation:{event.event_id}",
                            "begin", f"ack:{event.event_id}", "commit", "end"]


async def test_publish_timeout_leaves_the_event_unacknowledged_for_retry(monkeypatch):
    sessions, event = _RecordingSessions(), _event()
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.claim_next_event",
                        AsyncMock(return_value=event))
    ack = AsyncMock(return_value=True)
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.acknowledge_event", ack)
    worker = SimulationWorker(sessions=sessions, redis=_redis_recording(sessions, hang=True), max_attempts=5,
                              publish_timeout_seconds=0.05, retention_days=None)
    with pytest.raises(TimeoutError):
        await worker.publish_one()
    ack.assert_not_awaited()
    assert sessions.log[-1].startswith("xadd:") and sessions.open == 0


def test_default_publish_timeout_is_ten_seconds_and_bounded():
    from app.modules.simulation.worker import PUBLISH_TIMEOUT_SECONDS

    assert PUBLISH_TIMEOUT_SECONDS == 10.0
    assert SimulationWorker(sessions=None, redis=None, max_attempts=1).publish_timeout_seconds == 10.0
    for invalid in (0, -1, 61):
        with pytest.raises(ValueError):
            SimulationWorker(sessions=None, redis=None, max_attempts=1, publish_timeout_seconds=invalid)


async def test_nothing_to_publish_ends_the_claim_transaction_without_redis(monkeypatch):
    sessions = _RecordingSessions()
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.claim_next_event",
                        AsyncMock(return_value=None))
    redis = _redis_recording(sessions)
    worker = SimulationWorker(sessions=sessions, redis=redis, max_attempts=5, retention_days=None)
    assert await worker.publish_one() is False
    assert sessions.log == ["begin", "commit", "end"]
    redis.xadd.assert_not_awaited()


async def test_run_one_commits_the_claim_before_computing_and_the_fenced_result_after(monkeypatch):
    from tests.simulation_support import record

    sessions, row = _RecordingSessions(), record()
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.claim",
                        AsyncMock(side_effect=lambda **kw: sessions.log.append("claim") or row))

    def compute(*args, **kwargs):
        assert sessions.open == 0  # model work never runs inside a transaction
        sessions.log.append("advance")
        return row.checkpoint

    monkeypatch.setattr("app.modules.simulation.worker.advance", compute)
    monkeypatch.setattr("app.modules.simulation.worker.output",
                        lambda config, checkpoint: {"tick": 1, "duration_ticks": 10, "risk_gate": "blocked"})
    finish = AsyncMock(side_effect=lambda *a, **kw: sessions.log.append("finish") or True)
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.finish_batch", finish)
    assert await SimulationWorker(sessions=sessions, redis=None, max_attempts=5).run_one() is True
    assert sessions.log == ["begin", "claim", "commit", "end", "advance", "begin", "finish", "commit", "end"]


async def test_lost_lease_batch_is_rolled_back_by_the_worker(monkeypatch):
    from tests.simulation_support import record

    sessions = _RecordingSessions()
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.claim", AsyncMock(return_value=record()))
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.finish_batch", AsyncMock(return_value=False))
    assert await SimulationWorker(sessions=sessions, redis=None, max_attempts=5).run_one() is True
    assert sessions.log[-3:] == ["begin", "rollback", "end"] and sessions.log.count("commit") == 1


async def test_empty_claim_still_commits_exhausted_jobs(monkeypatch):
    sessions = _RecordingSessions()
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.claim", AsyncMock(return_value=None))
    assert await SimulationWorker(sessions=sessions, redis=None, max_attempts=5).run_one() is False
    assert sessions.log == ["begin", "commit", "end"]


# Outbox retention (ADR-028): published rows older than SIMULATION_OUTBOX_RETENTION_DAYS. --------

class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


async def test_retention_runs_once_per_interval_and_drains_backlogs_in_short_batches(monkeypatch):
    from datetime import timedelta

    sessions, clock, calls = _RecordingSessions(), _Clock(), []
    results = iter([3, 3, 1, 0])

    async def purge(self, *, older_than, limit):
        assert sessions.open == 1  # inside its own short transaction
        calls.append((older_than, limit))
        sessions.log.append("purge")
        return next(results)

    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.purge_published_events", purge)
    worker = SimulationWorker(sessions=sessions, redis=None, max_attempts=1, retention_days=30, retention_batch=3,
                              retention_interval_seconds=60, clock=clock)
    assert await worker.purge_published() == 3  # full batch: backlog, due again immediately
    assert await worker.purge_published() == 3
    assert await worker.purge_published() == 1  # partial batch: next run after the interval
    assert await worker.purge_published() == 0 and len(calls) == 3
    clock.now += 60
    assert await worker.purge_published() == 0 and len(calls) == 4
    assert calls[0] == (timedelta(days=30), 3)
    assert sessions.log[:4] == ["begin", "purge", "commit", "end"]


@pytest.mark.parametrize(("configured", "expected"), [(30, 30), (0, None), (7, 7), (-1, None), (True, None),
                                                      ("30", None), (36501, None)])
def test_retention_days_setting_disables_on_zero_or_invalid(configured, expected):
    from app.modules.simulation.worker import outbox_retention_days

    assert outbox_retention_days(SimpleNamespace(SIMULATION_OUTBOX_RETENTION_DAYS=configured)) == expected
    assert outbox_retention_days(SimpleNamespace()) == 30  # documented default


async def test_disabled_retention_never_deletes(monkeypatch):
    purge = AsyncMock()
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.purge_published_events", purge)
    worker = SimulationWorker(sessions=_RecordingSessions(), redis=None, max_attempts=1, retention_days=None)
    assert await worker.purge_published() == 0
    purge.assert_not_awaited()


async def test_retention_failure_never_blocks_publication(monkeypatch):
    sessions, event = _RecordingSessions(), _event()
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.purge_published_events",
                        AsyncMock(side_effect=ConnectionError("db restarting")))
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.claim_next_event",
                        AsyncMock(return_value=event))
    monkeypatch.setattr("app.modules.simulation.worker.SimulationRepository.acknowledge_event",
                        AsyncMock(return_value=True))
    redis = _redis_recording(sessions)
    worker = SimulationWorker(sessions=sessions, redis=redis, max_attempts=1, retention_days=30)
    assert await worker.publish_one() is True
    redis.xadd.assert_awaited_once()


@pytest.mark.parametrize("kwargs", [{"retention_days": 0}, {"retention_days": 36501}, {"retention_batch": 0},
                                    {"retention_batch": 10001}, {"retention_interval_seconds": 0}])
def test_retention_parameters_are_bounded(kwargs):
    with pytest.raises(ValueError):
        SimulationWorker(sessions=None, redis=None, max_attempts=1, **kwargs)
