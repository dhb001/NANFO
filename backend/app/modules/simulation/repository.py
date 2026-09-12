"""NANFO Backend - Simulation module repository.

Persistence operations for simulation lifecycle records.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.simulation.models import Simulation, SimulationOutbox


class SimulationRepository:
    """Repository for simulation lifecycle persistence."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def lock(self, simulation_id: uuid.UUID) -> Simulation | None:
        return await self._db.scalar(select(Simulation).where(Simulation.simulation_id == simulation_id)
            .with_for_update().execution_options(populate_existing=True))

    def add_modeled(self, record: Simulation) -> None:
        self._db.add(record)

    def enqueue(self, record: Simulation, event_type: str, correlation_id: str) -> dict:
        event_id = uuid.uuid5(record.simulation_id, f"{record.revision}:{event_type}")
        payload = {"simulation_id": str(record.simulation_id), "scenario_id": str(record.scenario_id),
            "network_id": str(record.network_id), "workspace_id": str(record.workspace_id),
            "scene_object_id": f"simulation:{record.simulation_id}", "state": record.state,
            "status": record.status, "risk_gate": record.risk_gate, "validation": record.validation,
            "revision": record.revision, "scenario_name": record.scenario_name,
            "requested_at": record.requested_at.isoformat(), "correlation_id": correlation_id,
            "parent_simulation_id": str(record.parent_simulation_id) if record.parent_simulation_id else None}
        self._db.add(SimulationOutbox(event_id=event_id, simulation_id=record.simulation_id,
            workspace_id=record.workspace_id, revision=record.revision, envelope={
                "event_id": str(event_id), "event_type": event_type, "source": "simulation", "version": "1",
                "timestamp": datetime.now(UTC).isoformat(), "correlation_id": correlation_id,
                "payload": json.dumps(payload, sort_keys=True, separators=(",", ":"))}))
        return payload

    async def claim(self) -> Simulation | None:
        record = await self._db.scalar(select(Simulation).where(Simulation.scenario_config.is_not(None),
            Simulation.state.in_(["queued", "running"]),
            or_(Simulation.lease_expires_at.is_(None), Simulation.lease_expires_at < func.now()))
            .order_by(Simulation.updated_at, Simulation.simulation_id).with_for_update(skip_locked=True).limit(1))
        if record is None:
            return None
        record.lease_token = uuid.uuid4()
        record.lease_expires_at = await self._db.scalar(select(func.now() + timedelta(seconds=30)))
        record.revision += 1
        record.state = record.status = "running"
        await self._db.commit()
        return record

    async def finish_batch(self, claimed: Simulation, *, checkpoint: dict | None, run_output: dict | None,
                           failure: str | None = None) -> bool:
        complete = run_output is not None and run_output["tick"] == run_output["duration_ticks"]
        state = "cancelled" if failure else "completed" if complete else "running"
        now = datetime.now(UTC)
        values = {"state": state, "status": state, "lease_token": None, "lease_expires_at": None,
                  "revision": claimed.revision + 1, "risk_gate": "blocked" if failure else run_output["risk_gate"],
                  "validation": {**claimed.validation, "pipeline_stage": "terminal" if complete or failure else "evaluating",
                                 "status": state, "failure_reason": failure}}
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
            await self._db.rollback()
            return False
        if failure or complete:
            self.enqueue(row, "simulation.cancelled" if failure else "simulation.completed",
                         str(claimed.audit_provenance["correlation_id"]))
        await self._db.commit()
        return True

    async def publish_one(self, redis) -> bool:
        prior = aliased(SimulationOutbox)
        row = await self._db.scalar(select(SimulationOutbox).where(SimulationOutbox.published_at.is_(None))
            .where(~select(prior.event_id).where(prior.simulation_id == SimulationOutbox.simulation_id,
                prior.revision < SimulationOutbox.revision, prior.published_at.is_(None)).exists())
            .order_by(SimulationOutbox.simulation_id, SimulationOutbox.revision).with_for_update(skip_locked=True).limit(1))
        if row is None:
            return False
        await redis.xadd("stream:simulation", row.envelope)
        row.published_at = datetime.now(UTC)
        await self._db.commit()
        return True

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

    async def list_by_scenario_id(
        self,
        *,
        scenario_id: uuid.UUID,
    ) -> list[Simulation]:
        result = await self._db.execute(
            select(Simulation).where(Simulation.scenario_id == scenario_id)
        )
        return list(result.scalars().all())

    async def list_children(
        self,
        *,
        parent_simulation_id: uuid.UUID,
    ) -> list[Simulation]:
        result = await self._db.execute(
            select(Simulation).where(Simulation.parent_simulation_id == parent_simulation_id)
        )
        return list(result.scalars().all())
