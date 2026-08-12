"""NANFO Backend - Simulation module repository.

Persistence operations for simulation lifecycle records.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.simulation.models import Simulation


class SimulationRepository:
    """Repository for simulation lifecycle persistence."""

    def __init__(self, db: AsyncSession):
        self._db = db

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
