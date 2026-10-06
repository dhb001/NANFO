"""Telemetry-local SQL only; transaction commit belongs to the calling owner."""

import uuid
from datetime import datetime

from sqlalchemy import exists, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.telemetry.models import TelemetryRecord
from app.modules.telemetry.archive_models import TelemetryArchiveReceipt, TelemetryEventTombstone, TelemetryReconciliation
from app.modules.telemetry.pin_models import TelemetryEvidencePin, TelemetryReferenceCoverage


def _known_identity_query(record_id):
    """Is ``record_id`` a telemetry identity at all (active anywhere, archived or tombstoned)?"""
    return select(or_(
        exists().where(TelemetryRecord.record_id == record_id),
        exists().where(TelemetryArchiveReceipt.record_id == record_id),
        exists().where(TelemetryEventTombstone.record_id == record_id),
    ))


class TelemetryPinRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def known_identity(self, record_id) -> bool:
        return bool(await self._db.scalar(_known_identity_query(record_id)))

    @staticmethod
    def known_identity_sync(connection, record_id) -> bool:
        return bool(connection.scalar(_known_identity_query(record_id)))

    async def reconciled(self, *, workspace_id, owner):
        return await self._db.scalar(select(TelemetryReconciliation.complete).where(
            TelemetryReconciliation.workspace_id == workspace_id,
            TelemetryReconciliation.owner == owner)) is True

    async def reconciliation_progress(self, workspace_id, *, lock: bool = False):
        stmt = select(TelemetryReconciliation).where(TelemetryReconciliation.workspace_id == workspace_id)
        if lock:
            stmt = stmt.order_by(TelemetryReconciliation.owner).with_for_update(read=True)
        rows = (await self._db.scalars(stmt.execution_options(populate_existing=True))).all()
        return {row.owner: row for row in rows}

    async def event_record(self, *, workspace_id, network_id, event_id):
        return await self._db.scalar(select(TelemetryRecord.record_id).where(
            TelemetryRecord.workspace_id == workspace_id, TelemetryRecord.network_id == network_id,
            TelemetryRecord.event_id == event_id))

    @staticmethod
    def pin_sync(connection, *, workspace_id, network_id, owner, reference_id, record_id,
                 skip_unknown_identity=False) -> bool:
        """Pin inside the owner's flush transaction; ``False`` if skipped.

        With ``skip_unknown_identity`` a UUID that was never a telemetry identity
        (e.g. an unrelated id under a generic ``record_id`` key) is skipped instead
        of failing the owner's write. Known identities that are archived or belong
        to another scope always fail closed.
        """
        record = connection.scalar(select(TelemetryRecord.record_id).where(
            TelemetryRecord.record_id == record_id, TelemetryRecord.workspace_id == workspace_id,
            TelemetryRecord.network_id == network_id).with_for_update(read=True))
        if record is None:
            if skip_unknown_identity and not TelemetryPinRepository.known_identity_sync(connection, record_id):
                return False
            raise ValueError("Evidence record unavailable in owner scope")
        connection.execute(insert(TelemetryEvidencePin).values(workspace_id=workspace_id,
            network_id=network_id, owner=owner, reference_id=reference_id, record_id=record_id
        ).on_conflict_do_nothing())
        released = connection.scalar(select(TelemetryEvidencePin.released_at).where(
            TelemetryEvidencePin.workspace_id == workspace_id, TelemetryEvidencePin.owner == owner,
            TelemetryEvidencePin.reference_id == reference_id, TelemetryEvidencePin.record_id == record_id
        ).with_for_update())
        if released is not None:
            raise ValueError("Released evidence reference cannot be reused")
        return True

    async def register(self, *, workspace_id: uuid.UUID, owner: str) -> TelemetryReferenceCoverage:
        await self._db.execute(insert(TelemetryReferenceCoverage).values(
            workspace_id=workspace_id, owner=owner, version=1, contract="pin-before-reference/v1",
        ).on_conflict_do_nothing())
        return (await self._db.scalars(select(TelemetryReferenceCoverage).where(
            TelemetryReferenceCoverage.workspace_id == workspace_id,
            TelemetryReferenceCoverage.owner == owner,
        ).execution_options(populate_existing=True))).one()

    async def revoke(self, *, workspace_id: uuid.UUID, owner: str) -> None:
        await self._db.execute(update(TelemetryReferenceCoverage).where(
            TelemetryReferenceCoverage.workspace_id == workspace_id,
            TelemetryReferenceCoverage.owner == owner,
            TelemetryReferenceCoverage.revoked_at.is_(None),
        ).values(revoked_at=func.clock_timestamp()))

    async def pin(
        self, *, workspace_id: uuid.UUID, network_id: uuid.UUID, owner: str,
        reference_id: uuid.UUID, record_id: uuid.UUID,
    ) -> TelemetryEvidencePin:
        record = (await self._db.scalars(select(TelemetryRecord.record_id).where(
            TelemetryRecord.record_id == record_id,
            TelemetryRecord.workspace_id == workspace_id,
            TelemetryRecord.network_id == network_id,
        ).with_for_update(read=True))).one_or_none()
        if record is None:
            raise ValueError("Evidence record unavailable in owner scope")
        await self._db.execute(insert(TelemetryEvidencePin).values(
            workspace_id=workspace_id, network_id=network_id, owner=owner,
            reference_id=reference_id, record_id=record_id,
        ).on_conflict_do_nothing())
        # Serialize with concurrent release; never acknowledge a released pin.
        return (await self._db.scalars(select(TelemetryEvidencePin).where(
            TelemetryEvidencePin.workspace_id == workspace_id,
            TelemetryEvidencePin.owner == owner,
            TelemetryEvidencePin.reference_id == reference_id,
            TelemetryEvidencePin.record_id == record_id,
        ).with_for_update().execution_options(populate_existing=True))).one()

    async def release(
        self, *, workspace_id: uuid.UUID, network_id: uuid.UUID, owner: str,
        reference_id: uuid.UUID, record_id: uuid.UUID,
    ) -> bool:
        result = await self._db.execute(update(TelemetryEvidencePin).where(
            TelemetryEvidencePin.workspace_id == workspace_id,
            TelemetryEvidencePin.network_id == network_id,
            TelemetryEvidencePin.owner == owner,
            TelemetryEvidencePin.reference_id == reference_id,
            TelemetryEvidencePin.record_id == record_id,
            TelemetryEvidencePin.released_at.is_(None),
        ).values(released_at=func.clock_timestamp()).returning(TelemetryEvidencePin.record_id))
        return result.scalar_one_or_none() is not None

    async def coverage(self, workspace_id: uuid.UUID) -> list[TelemetryReferenceCoverage]:
        return list((await self._db.scalars(select(TelemetryReferenceCoverage).where(
            TelemetryReferenceCoverage.workspace_id == workspace_id,
        ).execution_options(populate_existing=True))).all())

    async def assessment_batch(
        self, *, workspace_id: uuid.UUID, start_time: datetime, end_time: datetime,
        batch_size: int, after: tuple[datetime, uuid.UUID] | None,
    ):
        pinned = exists().where(
            TelemetryEvidencePin.workspace_id == TelemetryRecord.workspace_id,
            TelemetryEvidencePin.record_id == TelemetryRecord.record_id,
        )
        stmt = select(
            TelemetryRecord.record_id, TelemetryRecord.observed_at,
            TelemetryRecord.created_at, pinned.label("pinned"),
        ).where(
            TelemetryRecord.workspace_id == workspace_id,
            TelemetryRecord.observed_at >= start_time,
            TelemetryRecord.observed_at < end_time,
        )
        if after is not None:
            stmt = stmt.where(tuple_(TelemetryRecord.observed_at, TelemetryRecord.record_id) > after)
        return (await self._db.execute(stmt.order_by(
            TelemetryRecord.observed_at, TelemetryRecord.record_id,
        ).limit(batch_size + 1))).all()
