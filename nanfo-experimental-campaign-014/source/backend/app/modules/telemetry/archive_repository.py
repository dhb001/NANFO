"""Telemetry-only retention SQL. Caller owns transaction and bounded row set."""

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.modules.telemetry.archive_models import TelemetryArchiveReceipt, TelemetryEventTombstone
from app.modules.telemetry.models import TelemetryRecord
from app.modules.telemetry.pin_models import TelemetryEvidencePin, TelemetryReferenceCoverage


class TelemetryArchiveRepository:
    def __init__(self, db):
        self.db = db

    async def lock_coverage(self, workspace_id):
        return list((await self.db.scalars(select(TelemetryReferenceCoverage).where(
            TelemetryReferenceCoverage.workspace_id == workspace_id
        ).order_by(TelemetryReferenceCoverage.owner).with_for_update(read=True))).all())

    async def lock_record(self, workspace_id, record_id):
        from app.modules.telemetry.dedup import TelemetryDedupRepository

        event_id = await self.db.scalar(select(TelemetryRecord.event_id).where(
            TelemetryRecord.workspace_id == workspace_id, TelemetryRecord.record_id == record_id))
        if event_id is None:
            return None
        await TelemetryDedupRepository(self.db).lock(event_id)
        return await self.db.scalar(select(TelemetryRecord).where(
            TelemetryRecord.workspace_id == workspace_id, TelemetryRecord.record_id == record_id
        ).with_for_update(skip_locked=True).execution_options(populate_existing=True))

    async def ever_pinned(self, record_id):
        # Separate statement AFTER exclusive lock: at READ COMMITTED this sees a
        # pin that committed while we waited. Released pins retain audit FK forever.
        return await self.db.scalar(select(exists().where(TelemetryEvidencePin.record_id == record_id)))

    async def archive_and_delete(self, record, digest, size):
        await self.db.execute(insert(TelemetryEventTombstone).values(event_id=record.event_id,
            record_id=record.record_id, workspace_id=record.workspace_id).on_conflict_do_nothing())
        await self.db.execute(insert(TelemetryArchiveReceipt).values(record_id=record.record_id,
            event_id=record.event_id, workspace_id=record.workspace_id, sha256=digest, size_bytes=size
        ).on_conflict_do_nothing())
        receipt = await self.receipt(record.workspace_id, record.record_id)
        if receipt.sha256 != digest or receipt.size_bytes != size:
            raise ValueError("immutable archive identity conflict")
        await self.db.delete(record)
        await self.db.flush()

    async def receipt(self, workspace_id, record_id):
        return await self.db.scalar(select(TelemetryArchiveReceipt).where(
            TelemetryArchiveReceipt.workspace_id == workspace_id,
            TelemetryArchiveReceipt.record_id == record_id))

    async def mark_restored(self, record_id):
        await self.db.execute(update(TelemetryArchiveReceipt).where(
            TelemetryArchiveReceipt.record_id == record_id).values(restored_at=func.clock_timestamp()))
