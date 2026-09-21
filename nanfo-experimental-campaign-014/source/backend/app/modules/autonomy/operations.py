"""Autonomy-owned read-only maintenance gates; never force a restoration result."""

from sqlalchemy import func, or_, select

from app.modules.autonomy.model_diagnostic_models import ModelDiagnostic
from app.modules.autonomy.models import AutonomyControl, AutonomyDecision, TimedOverride


async def maintenance_checkpoint(db):
    controls = await db.scalar(
        select(func.count())
        .select_from(AutonomyControl)
        .where(
            or_(
                AutonomyControl.active_execution_id.is_not(None),
                AutonomyControl.cancellation_status.not_in(["none", "verified"]),
                AutonomyControl.mode == "autonomous",
                AutonomyControl.approved_by_user_id.is_not(None),
            )
        )
    )
    overrides = await db.scalar(
        select(func.count())
        .select_from(TimedOverride)
        .where(TimedOverride.status.not_in(["restored", "returned"]))
    )
    return {
        "safe": controls == 0 and overrides == 0,
        "active_controls": controls,
        "unresolved_overrides": overrides,
    }


async def model_reference_inventory(db):
    diagnostics = await db.scalar(select(func.count()).select_from(ModelDiagnostic))
    checkpoints = await db.scalar(
        select(func.count())
        .select_from(AutonomyDecision)
        .where(AutonomyDecision.checkpoint_sha256.is_not(None))
    )
    return {"diagnostic_records": diagnostics, "checkpoint_decisions": checkpoints}
