"""Simulation lifecycle event consumer.

Consumes `simulation.started` and advances persisted simulation records to a
bounded terminal state with corresponding lifecycle event publication.
"""

from __future__ import annotations

from app.db.postgres import AsyncSessionLocal
from app.db.redis import get_redis_client
from app.modules.simulation.service import SimulationTerminalEventService


async def handle_simulation_started_event(event: dict) -> None:
    """Process `simulation.started` into terminal lifecycle parity events."""
    async with AsyncSessionLocal() as db:
        service = SimulationTerminalEventService(db=db, redis=get_redis_client())
        await service.process_started_event(event=event)


SIMULATION_HANDLERS: dict[str, object] = {
    "simulation.started": handle_simulation_started_event,
}
