"""Intent-owned read-only physical execution safety checkpoint for ADR020."""

from sqlalchemy import func, or_, select

from app.modules.intent.models import IntentExecution


async def maintenance_checkpoint(db):
    unresolved = await db.scalar(
        select(func.count())
        .select_from(IntentExecution)
        .where(
            or_(
                IntentExecution.blocks_lab.is_(True),
                IntentExecution.phase.not_in(["completed", "failed", "cancelled"]),
            )
        )
    )
    return {"safe": unresolved == 0, "unresolved_executions": unresolved}
