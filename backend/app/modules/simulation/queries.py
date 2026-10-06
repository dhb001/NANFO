"""Read-only Simulation answers for other modules (ADR-028 §1.2).

Owner-module query boundary: no writes, no locks, indexed ``simulations.network_id``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.simulation.models import Simulation

#: Only these statuses are safe from summary status alone (Network.md §3.2).
TERMINAL_STATUSES = frozenset({"completed", "cancelled", "failed"})


async def has_blocking_work(db: AsyncSession, *, network_id: uuid.UUID) -> bool:
    """Whether any simulation of ``network_id`` is not yet terminal."""
    return await db.scalar(select(Simulation.simulation_id).where(
        Simulation.network_id == network_id, Simulation.status.not_in(sorted(TERMINAL_STATUSES)),
    ).limit(1)) is not None
