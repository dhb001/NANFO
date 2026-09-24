"""ADR-028: bounded retention of Alert observation receipts (no database)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.alert.repository import AlertRepository
from app.modules.alert.retention import ObservationRetention, ObservationRetentionPolicy


class PurgeSession:
    def __init__(self, deleted):
        self.deleted, self.statements, self.commit = deleted, [], AsyncMock()

    async def execute(self, statement):
        self.statements.append(statement)
        result = MagicMock()
        result.all.return_value = [(index,) for index in range(self.deleted)]
        return result


async def test_purge_deletes_one_bounded_batch_and_protects_incident_windows_and_evidence():
    db = PurgeSession(deleted=7)
    assert await AlertRepository(db).purge_observations(retention_days=30, batch_size=500) == 7
    db.commit.assert_awaited_once()
    (statement,) = db.statements
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).split())
    assert sql.startswith("DELETE FROM alert_observations WHERE alert_observations.event_id IN (SELECT")
    assert "alert_observations.observed_at < now() - %(now_1)s" in sql
    assert "LIMIT %(param_1)s FOR UPDATE SKIP LOCKED" in sql and "ORDER BY" not in sql
    # Open incident window: an unresolved incident, or the detector's current phase run.
    assert ("NOT (EXISTS (SELECT 1 FROM alert_detector_states AS alert_detector_states_1 LEFT OUTER JOIN alerts "
            "AS alerts_1 ON alerts_1.alert_id = alert_detector_states_1.incident_id") in sql
    assert "alert_detector_states_1.detector_key = alert_observations.detector_key" in sql
    assert "alerts_1.alert_id IS NOT NULL AND alerts_1.status != %(status_1)s" in sql
    assert ("alert_detector_states_1.phase IS NOT NULL AND alert_detector_states_1.phase_since IS NOT NULL AND "
            "alert_observations.observed_at >= alert_detector_states_1.phase_since") in sql
    # Generating/resolving samples named by incident history are evidence, kept.
    assert ("NOT (EXISTS (SELECT 1 FROM alert_history WHERE (alert_history.payload ->> %(payload_1)s) = "
            "CAST(alert_observations.event_id AS VARCHAR)))") in sql
    assert "RETURNING alert_observations.event_id" in sql
    assert compiled.params["status_1"] == "resolved" and compiled.params["param_1"] == 500
    assert compiled.params["payload_1"] == "observation_event_id" and compiled.params["now_1"].days == 30


@pytest.mark.parametrize("kwargs", [dict(retention_days=0, batch_size=10), dict(retention_days=36501, batch_size=10),
                                    dict(retention_days=1, batch_size=0), dict(retention_days=1, batch_size=10001)])
async def test_purge_refuses_unbounded_parameters(kwargs):
    db = PurgeSession(deleted=0)
    with pytest.raises(ValueError):
        await AlertRepository(db).purge_observations(**kwargs)
    assert db.statements == []


def test_policy_reads_optional_settings_with_getattr_and_bounds_them():
    assert ObservationRetentionPolicy.from_settings(SimpleNamespace()) == ObservationRetentionPolicy(
        retention_days=30, batch_size=1000, max_batches=10, interval_seconds=300)
    clamped = ObservationRetentionPolicy.from_settings(SimpleNamespace(
        ALERT_OBSERVATION_RETENTION_DAYS=10**9, ALERT_OBSERVATION_PURGE_BATCH_SIZE=-5,
        ALERT_OBSERVATION_PURGE_MAX_BATCHES=True, ALERT_OBSERVATION_PURGE_INTERVAL_SECONDS="soon"))
    assert clamped == ObservationRetentionPolicy(retention_days=36500, batch_size=1, max_batches=10,
                                                 interval_seconds=300)
    assert not ObservationRetentionPolicy.from_settings(SimpleNamespace(ALERT_OBSERVATION_RETENTION_DAYS=0)).enabled


def _retention(*, clock, **settings):
    sessions = MagicMock()
    sessions.return_value.__aenter__ = AsyncMock(return_value=object())
    sessions.return_value.__aexit__ = AsyncMock(return_value=None)
    retention = ObservationRetention(sessions=sessions, clock=clock, settings=SimpleNamespace(**settings))
    return retention


async def test_retention_is_interval_gated_and_stops_at_a_short_or_capped_batch(monkeypatch):
    now = [1000.0]
    purge = AsyncMock(side_effect=[5, 5, 2, 5, 5, 5])
    monkeypatch.setattr(AlertRepository, "purge_observations", purge)
    retention = _retention(clock=lambda: now[0], ALERT_OBSERVATION_PURGE_BATCH_SIZE=5,
                           ALERT_OBSERVATION_PURGE_MAX_BATCHES=3, ALERT_OBSERVATION_PURGE_INTERVAL_SECONDS=60)
    assert await retention.maybe_purge() == {"deleted": 12, "batches": 3, "retention_days": 30}
    purge.assert_awaited_with(retention_days=30, batch_size=5)
    now[0] += 59
    assert await retention.maybe_purge() is None  # not due yet
    now[0] += 1
    # Full batches keep going only up to the per-run cap (bounded work per interval).
    assert await retention.maybe_purge() == {"deleted": 15, "batches": 3, "retention_days": 30}
    assert purge.await_count == 6


async def test_disabled_retention_never_touches_the_database(monkeypatch):
    purge = AsyncMock()
    monkeypatch.setattr(AlertRepository, "purge_observations", purge)
    retention = _retention(clock=lambda: 0.0, ALERT_OBSERVATION_RETENTION_DAYS=0)
    assert await retention.maybe_purge(force=True) is None
    purge.assert_not_awaited()


async def test_failed_purge_is_retried_next_interval_not_in_a_hot_loop(monkeypatch):
    now = [0.0]
    purge = AsyncMock(side_effect=[ConnectionError("db down"), 0])
    monkeypatch.setattr(AlertRepository, "purge_observations", purge)
    retention = _retention(clock=lambda: now[0])
    with pytest.raises(ConnectionError):
        await retention.maybe_purge()
    assert await retention.maybe_purge() is None
    now[0] += 300
    assert await retention.maybe_purge() == {"deleted": 0, "batches": 1, "retention_days": 30}


async def test_alert_worker_loop_publishes_and_purges_and_survives_failures(monkeypatch):
    from scripts import run_alert_worker

    publish = AsyncMock(side_effect=[True, False, ConnectionError("redis down"), False])
    monkeypatch.setattr(AlertRepository, "publish_one", publish)
    sessions = MagicMock()
    sessions.return_value.__aenter__ = AsyncMock(return_value=object())
    sessions.return_value.__aexit__ = AsyncMock(return_value=None)
    retention = SimpleNamespace(maybe_purge=AsyncMock(side_effect=[OSError("purge failed"), None, None]))
    warnings = []
    logger = SimpleNamespace(warning=lambda event, **fields: warnings.append(event))
    await run_alert_worker.run(sessions=sessions, redis=object(), retention=retention, iterations=3,
                               sleep=lambda seconds: asyncio.sleep(0), logger=logger)
    assert publish.await_count == 4 and retention.maybe_purge.await_count == 3
    assert warnings == ["alert_observation_retention_deferred", "alert_outbox_deferred"]
    # --once drains and exits without maintenance.
    once = SimpleNamespace(maybe_purge=AsyncMock())
    publish.side_effect = [False]
    await run_alert_worker.run(sessions=sessions, redis=object(), retention=once, once=True, logger=logger)
    once.maybe_purge.assert_not_awaited()
