"""NANFO Backend - Simulation module repository.

Persistence operations for simulation lifecycle records. The repository never
commits or rolls back (ADR-028): the owning service/worker decides the unit of work,
so no Redis or model I/O ever runs while a transaction (or row lock) is open.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.correlation import normalize_audit_correlation
from app.modules.simulation.models import Simulation, SimulationOutbox

ACTIVE_STATES = ("queued", "running")
ATTEMPTS_EXHAUSTED = "attempts_exhausted"
MAX_RETENTION_BATCH_ROWS = 10_000


@dataclass(frozen=True)
class OutboxEvent:
    """A claimed, immutable outbox envelope; published after the claim transaction ends."""

    event_id: uuid.UUID
    envelope: dict


def normalize_correlation(value) -> tuple[str, dict]:
    """ADR-028 C20: the shared request-id -> UUID mapping plus preserved original id."""
    correlation, extra = normalize_audit_correlation(value, None)
    return str(correlation), extra


def _revision(record) -> int:
    value = getattr(record, "revision", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _has_claim_attempts() -> bool:
    # Migration 0030 (BE-DB) adds the column; tolerate a model without it.
    return "claim_attempts" in Simulation.__table__.c


def _has_outbox_created_at() -> bool:
    # Migration 0030 (BE-DB) adds simulation_outbox.created_at; tolerate a model without it.
    return "created_at" in SimulationOutbox.__table__.c


def event_payload(record: Simulation, correlation_id: str, *, request_id: str | None = None) -> dict:
    """Versioned lifecycle payload shared by enqueued events and same-state no-op replies."""
    payload = {"simulation_id": str(record.simulation_id), "scenario_id": str(record.scenario_id),
        "network_id": str(record.network_id), "workspace_id": str(record.workspace_id),
        "scene_object_id": f"simulation:{record.simulation_id}", "state": record.state,
        "status": record.status, "risk_gate": record.risk_gate, "validation": record.validation,
        "revision": record.revision, "scenario_name": record.scenario_name,
        "requested_at": record.requested_at.isoformat(), "correlation_id": correlation_id,
        "parent_simulation_id": str(record.parent_simulation_id) if record.parent_simulation_id else None}
    if request_id:
        payload["request_id"] = request_id
    return payload


class SimulationRepository:
    """Repository for simulation lifecycle persistence."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def lock(self, simulation_id: uuid.UUID) -> Simulation | None:
        return await self._db.scalar(select(Simulation).where(Simulation.simulation_id == simulation_id)
            .with_for_update().execution_options(populate_existing=True))

    def add_modeled(self, record: Simulation) -> None:
        self._db.add(record)

    def _add_outbox(self, record, *, event_id: uuid.UUID, event_type: str, correlation_id: str,
                    payload: dict) -> SimulationOutbox:
        row = SimulationOutbox(event_id=event_id, simulation_id=record.simulation_id,
            workspace_id=record.workspace_id, revision=_revision(record), envelope={
                "event_id": str(event_id), "event_type": event_type, "source": "simulation", "version": "1",
                "timestamp": datetime.now(UTC).isoformat(), "correlation_id": correlation_id,
                "payload": json.dumps(payload, sort_keys=True, separators=(",", ":"))})
        self._db.add(row)
        return row

    def enqueue(self, record: Simulation, event_type: str, correlation_id: str) -> dict:
        correlation, extra = normalize_correlation(correlation_id)
        event_id = uuid.uuid5(record.simulation_id, f"{record.revision}:{event_type}")
        payload = event_payload(record, correlation, request_id=extra.get("request_id"))
        self._add_outbox(record, event_id=event_id, event_type=event_type, correlation_id=correlation,
                         payload=payload)
        return payload

    def enqueue_legacy(self, record, *, event_type: str, payload: dict, correlation_id: str,
                       event_id: uuid.UUID | str) -> SimulationOutbox:
        """Durably record an unversioned lifecycle event with the caller's exact payload.

        Committed together with the state change (ADR-028: commit before publish).
        A best-effort immediate publication may mark it published; otherwise the
        simulation worker republishes the stored envelope with the same event ID.
        """
        record.revision = _revision(record) + 1
        correlation, _ = normalize_correlation(correlation_id)
        return self._add_outbox(record, event_id=uuid.UUID(str(event_id)), event_type=event_type,
                                correlation_id=correlation, payload=payload)

    async def active_count(self, workspace_id: uuid.UUID) -> int:
        """Queued/running modeled runs, serialized per workspace for the transaction."""
        await self._db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                               {"key": f"simulation-quota:{workspace_id}"})
        return int(await self._db.scalar(select(func.count()).select_from(Simulation).where(
            Simulation.workspace_id == workspace_id, Simulation.scenario_config.is_not(None),
            Simulation.state.in_(ACTIVE_STATES))) or 0)

    @staticmethod
    def claim_statement():
        """Fair claim across workspaces instead of one global FIFO.

        Workspaces are served least-recently-active first: the per-workspace window
        ``max(updated_at)`` over its active (queued/running, including leased) jobs
        moves a workspace behind the others as soon as one of its jobs is claimed or
        advanced, so a tenant with many queued runs cannot starve the rest. Within a
        workspace the oldest runnable job goes first. The window lives in a subquery
        so the row lock applies to ``simulations`` only (``FOR UPDATE OF ... SKIP LOCKED``).
        """
        active = (Simulation.scenario_config.is_not(None), Simulation.state.in_(ACTIVE_STATES))
        runnable = or_(Simulation.lease_expires_at.is_(None), Simulation.lease_expires_at < func.now())
        activity = select(Simulation.simulation_id.label("simulation_id"), func.max(Simulation.updated_at).over(
            partition_by=Simulation.workspace_id,
        ).label("workspace_activity")).where(*active).subquery()
        return (select(Simulation).join(activity, activity.c.simulation_id == Simulation.simulation_id)
                .where(*active, runnable)
                .order_by(activity.c.workspace_activity, Simulation.updated_at, Simulation.simulation_id)
                .with_for_update(skip_locked=True, of=Simulation).limit(1))

    async def claim(self, *, max_attempts: int | None = None) -> Simulation | None:
        """Lease the next fair job; the caller commits (also when None: exhaustions persist).

        Bounded: exhausted jobs are terminated in the same transaction and the next fair
        candidate is tried. Flushed terminations are no longer active, so the claim
        query of this transaction never returns them again.
        """
        for _ in range(8):
            record = await self._db.scalar(self.claim_statement())
            if record is None:
                return None
            if _has_claim_attempts():
                attempts = record.claim_attempts or 0
                if max_attempts is not None and attempts >= max_attempts:
                    await self._exhaust(record)
                    continue
                record.claim_attempts = attempts + 1
            record.lease_token = uuid.uuid4()
            record.lease_expires_at = await self._db.scalar(select(func.now() + timedelta(seconds=30)))
            record.revision += 1
            record.state = record.status = "running"
            await self._db.flush()
            return record
        return None

    async def _exhaust(self, record: Simulation) -> None:
        """Terminal ``failed``/``attempts_exhausted`` (ADR-028 C20).

        No new event name is invented: the documented terminal failure event
        ``simulation.cancelled`` carries ``state="failed"`` and the reason.
        """
        record.state = record.status = "failed"
        record.risk_gate = "blocked"
        record.lease_token = record.lease_expires_at = None
        record.revision += 1
        record.warning = ATTEMPTS_EXHAUSTED
        record.validation = {**(record.validation or {}), "pipeline_stage": "terminal", "status": "failed",
                             "failure_reason": ATTEMPTS_EXHAUSTED}
        self.enqueue(record, "simulation.cancelled", (record.audit_provenance or {}).get("correlation_id"))
        await self._db.flush()

    async def finish_batch(self, claimed: Simulation, *, checkpoint: dict | None, run_output: dict | None,
                           failure: str | None = None) -> bool:
        """Fenced batch result; False when the lease was lost (nothing written).

        The caller commits on True and rolls back on False.
        """
        complete = run_output is not None and run_output["tick"] == run_output["duration_ticks"]
        state = "cancelled" if failure else "completed" if complete else "running"
        now = datetime.now(UTC)
        values = {"state": state, "status": state, "lease_token": None, "lease_expires_at": None,
                  "revision": claimed.revision + 1, "risk_gate": "blocked" if failure else run_output["risk_gate"],
                  "validation": {**claimed.validation, "pipeline_stage": "terminal" if complete or failure else "evaluating",
                                 "status": state, "failure_reason": failure}}
        if _has_claim_attempts():
            values["claim_attempts"] = 0  # attempts count claims without committed progress
        if failure:
            values.update(run_output={}, warning=failure)
        else:
            values.update(checkpoint=checkpoint, run_output=run_output)
        if complete:
            # Reusing a finished branch checkpoint must not refresh old evidence.
            values.update(completed_at=claimed.completed_at or now,
                          evidence_expires_at=claimed.evidence_expires_at or now + timedelta(minutes=5))
        row = await self._db.scalar(update(Simulation).where(Simulation.simulation_id == claimed.simulation_id,
            Simulation.state == "running", Simulation.revision == claimed.revision,
            Simulation.lease_token == claimed.lease_token, Simulation.lease_expires_at > func.now())
            .values(**values).returning(Simulation))
        if row is None:
            return False
        if failure or complete:
            self.enqueue(row, "simulation.cancelled" if failure else "simulation.completed",
                         str(claimed.audit_provenance["correlation_id"]))
        await self._db.flush()
        return True

    async def claim_next_event(self) -> OutboxEvent | None:
        """Next publishable envelope in per-simulation revision order (persistence F28).

        The row lock (SKIP LOCKED) lives only inside the caller's short claim
        transaction, which commits before any Redis I/O. The table has no lease
        columns, so two concurrent publishers may send the same stable event_id
        (at-least-once, deduplicated by consumers); a later revision is never
        claimable before every earlier one is acknowledged.
        """
        prior = aliased(SimulationOutbox)
        row = await self._db.scalar(select(SimulationOutbox).where(SimulationOutbox.published_at.is_(None))
            .where(~select(prior.event_id).where(prior.simulation_id == SimulationOutbox.simulation_id,
                prior.revision < SimulationOutbox.revision, prior.published_at.is_(None)).exists())
            .order_by(SimulationOutbox.simulation_id, SimulationOutbox.revision).with_for_update(skip_locked=True).limit(1))
        if row is None:
            return None
        # The stored envelope is immutable: replays keep the event ID, timestamp and bytes.
        return OutboxEvent(event_id=row.event_id, envelope=dict(row.envelope))

    async def acknowledge_event(self, event_id: uuid.UUID) -> bool:
        """Mark published after a successful XADD; False if already acknowledged."""
        result = await self._db.execute(update(SimulationOutbox).where(
            SimulationOutbox.event_id == event_id, SimulationOutbox.published_at.is_(None),
        ).values(published_at=func.now()))
        return result.rowcount == 1

    async def purge_published_events(self, *, older_than: timedelta, limit: int) -> int:
        """Delete at most ``limit`` rows published before ``now() - older_than``; one statement.

        Unpublished rows are never touched (at-least-once delivery is preserved), and
        publication order only ever consults unpublished rows, so removing old
        published ones cannot reorder or re-enable anything. Oldest rows go first
        (``created_at`` once migration 0030 adds it). ``SKIP LOCKED`` lets replicas
        share the work. The caller commits.
        """
        if type(limit) is not int or not 1 <= limit <= MAX_RETENTION_BATCH_ROWS:
            raise ValueError("Retention batch must be between 1 and 10000 rows")
        if older_than <= timedelta(0):
            raise ValueError("Retention age must be positive")
        cutoff = func.now() - older_than
        conditions = [SimulationOutbox.published_at.is_not(None), SimulationOutbox.published_at < cutoff]
        order = [SimulationOutbox.published_at, SimulationOutbox.event_id]
        if _has_outbox_created_at():
            conditions.append(SimulationOutbox.created_at < cutoff)
            order.insert(0, SimulationOutbox.created_at)
        victims = (select(SimulationOutbox.event_id).where(*conditions).order_by(*order).limit(limit)
                   .with_for_update(skip_locked=True))
        purged = delete(SimulationOutbox).where(SimulationOutbox.event_id.in_(victims)).returning(
            SimulationOutbox.event_id,
        ).cte("purged")
        return int(await self._db.scalar(select(func.count()).select_from(purged)) or 0)

    async def create(
        self,
        *,
        simulation_id: uuid.UUID,
        parent_simulation_id: uuid.UUID | None,
        network_id: uuid.UUID,
        workspace_id: uuid.UUID,
        scenario_id: uuid.UUID,
        scenario_name: str,
        state: str,
        status: str,
        risk_gate: str,
        validation: dict,
        run_output: dict,
        model_versions: dict,
        audit_provenance: dict,
        queue_status: str,
        stream_entry_id: str | None,
        warning: str | None,
        requested_by_user_id: str,
        requested_at: datetime,
    ) -> Simulation:
        simulation = Simulation(
            simulation_id=simulation_id,
            parent_simulation_id=parent_simulation_id,
            network_id=network_id,
            workspace_id=workspace_id,
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            state=state,
            status=status,
            risk_gate=risk_gate,
            validation=validation,
            run_output=run_output,
            model_versions=model_versions,
            audit_provenance=audit_provenance,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
            requested_by_user_id=requested_by_user_id,
            requested_at=requested_at,
        )
        self._db.add(simulation)
        await self._db.flush()
        return simulation

    async def get_by_id(self, simulation_id: uuid.UUID) -> Simulation | None:
        result = await self._db.execute(
            select(Simulation).where(Simulation.simulation_id == simulation_id)
        )
        return result.scalar_one_or_none()

    async def update_queue_outcome(
        self,
        simulation: Simulation,
        *,
        queue_status: str,
        stream_entry_id: str | None,
        warning: str | None,
    ) -> Simulation:
        simulation.queue_status = queue_status
        simulation.stream_entry_id = stream_entry_id
        simulation.warning = warning
        await self._db.flush()
        return simulation

    async def update_state(
        self,
        simulation: Simulation,
        *,
        state: str,
        status: str,
        risk_gate: str | None = None,
        validation: dict | None = None,
        run_output: dict | None = None,
    ) -> Simulation:
        simulation.state = state
        simulation.status = status
        if risk_gate is not None:
            simulation.risk_gate = risk_gate
        if validation is not None:
            simulation.validation = validation
        if run_output is not None:
            simulation.run_output = run_output
        await self._db.flush()
        return simulation
