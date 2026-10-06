"""Read-only Autonomy answers for other modules (ADR-028 §1.2).

Owner-module query boundary: no writes, no locks, no provider I/O. Uses the
``autonomy_controls`` primary key, the unresolved-override partial index and the
unreleased-execution partial index (``released = false``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.autonomy.execution_models import AutonomousExecution
from app.modules.autonomy.models import AutonomyControl, TimedOverride

#: Cancellation outcomes that still require verified reconciliation.
UNSETTLED_CANCELLATION = frozenset({"requested", "uncertain"})
#: Timed-override statuses that are not yet resolved.
UNRESOLVED_OVERRIDE_STATUSES = ("holding", "restoring")


async def has_unresolved_execution(db: AsyncSession, *, network_id: uuid.UUID) -> bool:
    """Whether an autonomous execution of ``network_id`` still owns device state.

    An execution is released only after verified compensation (phase
    ``cancelled``). Accepted, in-flight, uncertain and *verified* executions keep
    ``released = false``: a verified policy remains applied on the device
    ("policy_remains_owned"), so the network's inventory must not disappear
    underneath it. Served by the ``released = false`` partial index.
    """
    return await db.scalar(select(AutonomousExecution.execution_id).where(
        AutonomousExecution.network_id == network_id, AutonomousExecution.released.is_(False),
    ).limit(1)) is not None


async def has_blocking_work(db: AsyncSession, *, network_id: uuid.UUID) -> bool:
    """Whether autonomy is anything but idle monitoring for ``network_id``."""
    control = (await db.execute(select(
        AutonomyControl.mode, AutonomyControl.active_execution_id, AutonomyControl.cancellation_status,
    ).where(AutonomyControl.network_id == network_id))).one_or_none()
    if control is not None and (
        control.mode != "monitor" or control.active_execution_id is not None
        or control.cancellation_status in UNSETTLED_CANCELLATION
    ):
        return True
    if await db.scalar(select(TimedOverride.override_id).where(
        TimedOverride.network_id == network_id, TimedOverride.status.in_(UNRESOLVED_OVERRIDE_STATUSES),
    ).limit(1)) is not None:
        return True
    return await has_unresolved_execution(db, network_id=network_id)
