"""Owner-only bounded retention assessment; age never proves evidence unreferenced."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.modules.telemetry.models import TelemetryRecord


async def retention_assessment(db, *, days=30, batch_size=1000):
    if not 1 <= days <= 3650 or not 1 <= batch_size <= 1000:
        raise ValueError("Telemetry retention assessment outside policy bounds")
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await db.scalars(
            select(TelemetryRecord.record_id)
            .where(TelemetryRecord.created_at < cutoff)
            .limit(batch_size + 1)
        )
    ).all()
    return {
        "status": "blocked",
        "policy_days": days,
        "deleted": 0,
        "aged_records_at_least": min(len(rows), batch_size),
        "assessment_truncated": len(rows) > batch_size,
        "reason": "No complete cross-owner evidence pin contract; age alone cannot prove safe deletion",
    }
