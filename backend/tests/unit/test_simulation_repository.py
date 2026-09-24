"""Unit tests for simulation repository persistence behavior."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.simulation.models import Simulation, SimulationOutbox
from app.modules.simulation.repository import SimulationRepository


@pytest.mark.asyncio
async def test_create_adds_and_flushes_simulation_record(mock_db):
    repo = SimulationRepository(mock_db)
    now = datetime.now(UTC)

    simulation = await repo.create(
        simulation_id=uuid.uuid4(),
        parent_simulation_id=None,
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        scenario_id=uuid.uuid4(),
        scenario_name="Campus baseline",
        state="queued",
        status="queued",
        risk_gate="required",
        validation={"pipeline_stage": "handoff_queued"},
        run_output={"latency_ms": 0.0, "loss_pct": 0.0, "throughput_mbps": 0.0},
        model_versions={"physics_engine": "v1"},
        audit_provenance={"policy_reference": "ADR-008"},
        queue_status="queued",
        stream_entry_id="1001-0",
        warning=None,
        requested_by_user_id=str(uuid.uuid4()),
        requested_at=now,
    )

    assert isinstance(simulation, Simulation)
    assert simulation.state == "queued"
    assert simulation.validation["pipeline_stage"] == "handoff_queued"
    mock_db.add.assert_called_once_with(simulation)
    mock_db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_by_id_executes_select_and_returns_row(mock_db):
    expected = MagicMock(spec=Simulation)
    result = MagicMock()
    result.scalar_one_or_none.return_value = expected
    mock_db.execute = AsyncMock(return_value=result)

    repo = SimulationRepository(mock_db)
    simulation = await repo.get_by_id(uuid.uuid4())

    assert simulation is expected
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_queue_outcome_mutates_record_and_flushes(mock_db):
    repo = SimulationRepository(mock_db)
    simulation = Simulation(
        simulation_id=uuid.uuid4(),
        parent_simulation_id=None,
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        scenario_id=uuid.uuid4(),
        scenario_name="Campus baseline",
        state="queued",
        status="queued",
        risk_gate="required",
        validation={},
        run_output={},
        model_versions={},
        audit_provenance={},
        queue_status="queued",
        stream_entry_id="1001-0",
        warning=None,
        requested_by_user_id=str(uuid.uuid4()),
        requested_at=datetime.now(UTC),
    )

    updated = await repo.update_queue_outcome(
        simulation,
        queue_status="deferred",
        stream_entry_id=None,
        warning="event_queue_unavailable",
    )

    assert updated is simulation
    assert simulation.queue_status == "deferred"
    assert simulation.stream_entry_id is None
    assert simulation.warning == "event_queue_unavailable"
    mock_db.flush.assert_awaited_once()


def test_unused_lineage_queries_removed():
    # ADR-028 dead code: no caller outside their own tests.
    assert not hasattr(SimulationRepository, "list_children")
    assert not hasattr(SimulationRepository, "list_by_scenario_id")


def test_claim_is_fair_across_workspaces_and_locks_only_simulations():
    """Regression: a global FIFO let one workspace's queue starve every other tenant."""
    sql = str(SimulationRepository.claim_statement().compile(dialect=postgresql.dialect()))
    assert "max(simulations.updated_at) OVER (PARTITION BY simulations.workspace_id)" in sql
    assert "ORDER BY anon_1.workspace_activity, simulations.updated_at" in sql
    assert sql.rstrip().endswith("FOR UPDATE OF simulations SKIP LOCKED")


def test_fair_order_serves_least_recently_active_workspace_first():
    """Model the ORDER BY on in-memory rows: round robin even with one worker."""
    def order(rows):
        activity = {}
        for row in rows:
            activity[row["ws"]] = max(activity.get(row["ws"], 0), row["updated"])
        runnable = [row for row in rows if not row["leased"]]
        return sorted(runnable, key=lambda row: (activity[row["ws"]], row["updated"]))[0]

    rows = [{"id": f"busy{i}", "ws": "busy", "updated": i, "leased": False} for i in (1, 2, 3)]
    rows.append({"id": "quiet", "ws": "quiet", "updated": 4, "leased": False})
    served, clock = [], 10
    for _ in range(6):
        job = order(rows)
        served.append(job["id"])
        job["updated"] = clock  # claim + finish_batch refresh updated_at
        clock += 1
    # Batches alternate between tenants instead of draining the busy queue first.
    assert served == ["busy1", "quiet", "busy2", "quiet", "busy3", "quiet"]


def _claimable(**overrides):
    return SimpleNamespace(**({"simulation_id": uuid.uuid4(), "workspace_id": uuid.uuid4(), "scenario_id": uuid.uuid4(),
        "network_id": uuid.uuid4(), "parent_simulation_id": None, "scenario_name": "run", "state": "queued",
        "status": "queued", "risk_gate": "required", "validation": {"status": "pending"}, "revision": 3,
        "requested_at": datetime.now(UTC), "audit_provenance": {"correlation_id": str(uuid.uuid4())},
        "claim_attempts": 0, "lease_token": None, "lease_expires_at": None, "warning": None} | overrides))


@pytest.mark.asyncio
async def test_claim_counts_attempts_and_exhausted_job_becomes_terminal_failed(mock_db, monkeypatch):
    monkeypatch.setattr("app.modules.simulation.repository._has_claim_attempts", lambda: True)
    poison, healthy = _claimable(claim_attempts=5), _claimable(claim_attempts=2)
    lease = datetime.now(UTC)
    mock_db.scalar = AsyncMock(side_effect=[poison, healthy, lease])
    claimed = await SimulationRepository(mock_db).claim(max_attempts=5)
    assert claimed is healthy and healthy.claim_attempts == 3 and healthy.state == "running"
    assert healthy.lease_expires_at == lease and healthy.revision == 4
    assert (poison.state, poison.status, poison.risk_gate, poison.warning) == (
        "failed", "failed", "blocked", "attempts_exhausted")
    assert poison.validation["failure_reason"] == "attempts_exhausted"
    assert poison.lease_token is None and poison.revision == 4
    event = mock_db.add.call_args.args[0]
    assert event.envelope["event_type"] == "simulation.cancelled"  # documented terminal event; no new name
    assert json.loads(event.envelope["payload"])["state"] == "failed"
    # ADR-028: the worker owns the unit of work; the repository only flushes (exhaustion, then lease).
    assert mock_db.flush.await_count == 2
    mock_db.commit.assert_not_awaited()
    mock_db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_below_cap_leases_and_increments(mock_db, monkeypatch):
    monkeypatch.setattr("app.modules.simulation.repository._has_claim_attempts", lambda: True)
    job = _claimable(claim_attempts=4)
    mock_db.scalar = AsyncMock(side_effect=[job, datetime.now(UTC)])
    assert await SimulationRepository(mock_db).claim(max_attempts=5) is job
    assert job.claim_attempts == 5 and job.lease_token is not None
    mock_db.add.assert_not_called()
    mock_db.flush.assert_awaited_once()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_finish_batch_resets_attempts_after_committed_progress(mock_db):
    job = _claimable(state="running", lease_token=uuid.uuid4(), completed_at=None, evidence_expires_at=None)
    mock_db.scalar = AsyncMock(return_value=None)
    assert await SimulationRepository(mock_db).finish_batch(job, checkpoint={}, run_output={
        "tick": 1, "duration_ticks": 10, "risk_gate": "blocked"}) is False
    statement = mock_db.scalar.await_args.args[0]
    if "claim_attempts" in Simulation.__table__.c:
        compiled = statement.compile(dialect=postgresql.dialect())
        assert compiled.params["claim_attempts"] == 0
    else:  # Before migration 0030's model column lands, the statement must not reference it.
        assert "claim_attempts" not in str(statement)
    # Lost CAS: nothing written and no transaction control here (the worker rolls back).
    mock_db.rollback.assert_not_awaited()
    mock_db.commit.assert_not_awaited()
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_finish_batch_terminal_result_enqueues_event_without_committing(mock_db):
    job = _claimable(state="running", lease_token=uuid.uuid4(), completed_at=None, evidence_expires_at=None,
                     validation={"status": "running"})
    finished = _claimable(state="completed", revision=4)
    mock_db.scalar = AsyncMock(return_value=finished)
    assert await SimulationRepository(mock_db).finish_batch(job, checkpoint={}, run_output={
        "tick": 10, "duration_ticks": 10, "risk_gate": "passed"}) is True
    assert mock_db.add.call_args.args[0].envelope["event_type"] == "simulation.completed"
    mock_db.flush.assert_awaited_once()
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbox_claim_returns_an_immutable_copy_and_never_touches_redis_or_commits(mock_db):
    envelope = {"event_id": str(uuid.uuid4()), "event_type": "simulation.started", "payload": "{}"}
    row = SimpleNamespace(event_id=uuid.UUID(envelope["event_id"]), envelope=envelope)
    mock_db.scalar = AsyncMock(return_value=row)
    event = await SimulationRepository(mock_db).claim_next_event()
    assert event.event_id == row.event_id and event.envelope == envelope and event.envelope is not envelope
    statement = str(mock_db.scalar.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in statement
    mock_db.commit.assert_not_awaited()
    mock_db.scalar = AsyncMock(return_value=None)
    assert await SimulationRepository(mock_db).claim_next_event() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("rowcount", "acknowledged"), [(1, True), (0, False)])
async def test_outbox_acknowledge_is_idempotent_and_does_not_commit(mock_db, rowcount, acknowledged):
    mock_db.execute = AsyncMock(return_value=SimpleNamespace(rowcount=rowcount))
    assert await SimulationRepository(mock_db).acknowledge_event(uuid.uuid4()) is acknowledged
    compiled = str(mock_db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "published_at IS NULL" in compiled and "now()" in compiled
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_enqueue_normalizes_opaque_correlation_and_keeps_original(mock_db):
    row = _claimable()
    payload = SimulationRepository(mock_db).enqueue(row, "simulation.started", "client trace 7")
    from app.core.correlation import correlation_uuid

    envelope = mock_db.add.call_args.args[0].envelope
    assert envelope["correlation_id"] == payload["correlation_id"] == str(correlation_uuid("client trace 7"))
    assert payload["request_id"] == "client trace 7"
    assert json.loads(envelope["payload"]) == payload


@pytest.mark.asyncio
async def test_enqueue_legacy_bumps_revision_and_stores_exact_payload(mock_db):
    row = _claimable(revision=0)
    event_id = uuid.uuid5(row.simulation_id, "simulation.paused")
    outbox = SimulationRepository(mock_db).enqueue_legacy(row, event_type="simulation.paused",
        payload={"state": "paused", "scene_object_id": "simulation-state"},
        correlation_id=str(uuid.UUID(int=5)), event_id=str(event_id))
    assert row.revision == outbox.revision == 1 and outbox.event_id == event_id and outbox.published_at is None
    assert outbox.envelope["event_id"] == str(event_id)
    assert json.loads(outbox.envelope["payload"]) == {"state": "paused", "scene_object_id": "simulation-state"}


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["current", "without_created_at"])
async def test_outbox_retention_deletes_only_old_published_rows_in_one_bounded_statement(
    mock_db, monkeypatch, model,
):
    from datetime import timedelta

    # created_at arrives with migration 0030; the guard must hold for models with and without it.
    if model == "without_created_at":
        monkeypatch.setattr("app.modules.simulation.repository._has_outbox_created_at", lambda: False)
    expects_created_at = model == "current" and "created_at" in SimulationOutbox.__table__.c
    mock_db.scalar = AsyncMock(return_value=7)
    assert await SimulationRepository(mock_db).purge_published_events(older_than=timedelta(days=30), limit=500) == 7
    sql = str(mock_db.scalar.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "DELETE FROM simulation_outbox" in sql and "FOR UPDATE SKIP LOCKED" in sql
    assert "simulation_outbox.published_at IS NOT NULL" in sql and "simulation_outbox.published_at < now()" in sql
    assert ("simulation_outbox.created_at" in sql) is expects_created_at
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("older_than_days", "limit"), [(0, 10), (-1, 10), (30, 0), (30, 10001), (30, True)])
async def test_outbox_retention_rejects_unbounded_requests(mock_db, older_than_days, limit):
    from datetime import timedelta

    with pytest.raises(ValueError):
        await SimulationRepository(mock_db).purge_published_events(older_than=timedelta(days=older_than_days),
                                                                  limit=limit)
    mock_db.scalar.assert_not_called()
