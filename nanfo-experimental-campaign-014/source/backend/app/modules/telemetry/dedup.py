"""Global event identity exclusion shared by ingestion, archival and restore."""

from sqlalchemy import func, select

from app.modules.telemetry.archive_models import TelemetryEventTombstone


class TelemetryDedupRepository:
    def __init__(self, db):
        self.db = db

    async def lock(self, event_id):
        # A stable signed 64-bit advisory key; collisions only serialize extra work.
        key = int.from_bytes(event_id.bytes[:8], "big", signed=True)
        await self.db.execute(select(func.pg_advisory_xact_lock(key)))

    async def archived(self, event_id):
        return await self.db.scalar(select(TelemetryEventTombstone.event_id).where(
            TelemetryEventTombstone.event_id == event_id)) is not None
