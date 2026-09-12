"""NANFO Backend - Report module repository.

Persistence operations for report lifecycle records.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, true, update
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.report.models import ReportOutbox, ReportRecord


class ReportRepository:
    """Repository for report lifecycle persistence."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def history(self, workspace_id, user_id, page, page_size):
        scope = (
            ReportRecord.workspace_id == workspace_id,
            ReportRecord.requested_by_user_id == user_id,
        )
        # One statement supplies an exact total even when the requested page is empty.
        total = (
            select(func.count())
            .select_from(ReportRecord)
            .where(*scope)
            .scalar_subquery()
        )
        page_rows = (
            select(ReportRecord)
            .where(*scope)
            .order_by(ReportRecord.requested_at.desc(), ReportRecord.report_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .subquery()
        )
        record = aliased(ReportRecord, page_rows)
        rows = (
            await self._db.execute(
                select(record, total)
                .select_from(select(total.label("count")).subquery())
                .outerjoin(page_rows, true())
            )
        ).all()
        return [row[0] for row in rows if row[0] is not None], rows[0][1]

    def enqueue(self, record):
        event_type = f"report.{record.status}"
        event_id = uuid.uuid5(record.report_id, f"{record.status_version}:{event_type}")
        payload = {
            "report_id": str(record.report_id),
            "workspace_id": str(record.workspace_id),
            "network_id": str(record.network_id) if record.network_id else None,
            "report_type": record.report_type,
            "format": record.output_format,
            "status": record.status,
            "status_version": record.status_version,
            "snapshot_sha256": record.snapshot_sha256,
            "requested_by_user_id": record.requested_by_user_id,
            "requested_at": record.requested_at.isoformat(),
            "artifacts": record.artifact_refs,
            "error": record.error_context or None,
            "completed_at": record.completed_at.isoformat()
            if record.completed_at
            else None,
        }
        self._db.add(
            ReportOutbox(
                event_id=event_id,
                report_id=record.report_id,
                status_version=record.status_version,
                envelope={
                    "event_id": str(event_id),
                    "event_type": event_type,
                    "source": "report",
                    "version": "1",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "correlation_id": str(record.correlation_id),
                    "payload": json.dumps(
                        payload, sort_keys=True, separators=(",", ":")
                    ),
                },
            )
        )

    async def claim(self, lease_seconds):
        record = await self._db.scalar(
            select(ReportRecord)
            .where(
                ReportRecord.artifact_version == 1,
                ReportRecord.status.in_(["requested", "running"]),
                or_(
                    ReportRecord.lease_expires_at.is_(None),
                    ReportRecord.lease_expires_at < func.now(),
                ),
            )
            .order_by(ReportRecord.requested_at, ReportRecord.report_id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return None
        record.lease_token = uuid.uuid4()
        record.lease_expires_at = await self._db.scalar(
            select(func.now() + timedelta(seconds=lease_seconds))
        )
        record.status_version += 1
        record.status = "running"
        await self._db.commit()
        return record

    async def finish(self, claimed, *, receipt=None, error=None):
        from app.modules.report.artifacts import digest

        version = claimed.status_version + 1
        now = datetime.now(UTC)
        if receipt:
            receipt = {
                **receipt,
                "snapshot_sha256": claimed.snapshot_sha256,
                "status_version": version,
                "generated_at": now.isoformat(),
            }
            receipt["receipt_sha256"] = digest(receipt)
        artifacts = (
            [
                {
                    key: value
                    for key, value in receipt.items()
                    if key
                    not in {"receipt_sha256", "status_version", "snapshot_sha256"}
                }
            ]
            if receipt
            else []
        )
        if artifacts:
            artifacts[0]["uri"] = (
                f"/api/v1/reports/{claimed.report_id}/download?workspace_id={claimed.workspace_id}"
            )
        row = await self._db.scalar(
            update(ReportRecord)
            .where(
                ReportRecord.report_id == claimed.report_id,
                ReportRecord.status == "running",
                ReportRecord.status_version == claimed.status_version,
                ReportRecord.lease_token == claimed.lease_token,
                ReportRecord.lease_expires_at > func.now(),
            )
            .values(
                status="generated" if receipt else "failed",
                status_version=version,
                receipt=receipt,
                artifact_refs=artifacts,
                error_context=error or {},
                completed_at=now,
                lease_token=None,
                lease_expires_at=None,
                queue_status="outbox_pending",
            )
            .returning(ReportRecord)
        )
        if row is None:
            await self._db.rollback()
            return False
        self.enqueue(row)
        await self._db.commit()
        return True

    async def publish_one(self, redis):
        prior = aliased(ReportOutbox)
        row = await self._db.scalar(
            select(ReportOutbox)
            .where(
                ReportOutbox.published_at.is_(None),
                ~select(prior.event_id)
                .where(
                    prior.report_id == ReportOutbox.report_id,
                    prior.status_version < ReportOutbox.status_version,
                    prior.published_at.is_(None),
                )
                .exists(),
            )
            .order_by(ReportOutbox.report_id, ReportOutbox.status_version)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return False
        async with asyncio.timeout(10):
            entry = await redis.xadd("stream:report", row.envelope)
        row.stream_entry_id = entry.decode() if isinstance(entry, bytes) else entry
        row.published_at = datetime.now(UTC)
        await self._db.execute(
            update(ReportRecord)
            .where(
                ReportRecord.report_id == row.report_id,
                ReportRecord.status_version == row.status_version,
            )
            .values(queue_status="queued", stream_entry_id=row.stream_entry_id)
        )
        await self._db.commit()
        return True

    async def get_by_id(self, report_id: uuid.UUID) -> ReportRecord | None:
        result = await self._db.execute(
            select(ReportRecord).where(ReportRecord.report_id == report_id)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self,
        *,
        workspace_id: uuid.UUID,
        idempotency_key: str,
    ) -> ReportRecord | None:
        result = await self._db.execute(
            select(ReportRecord).where(
                ReportRecord.workspace_id == workspace_id,
                ReportRecord.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()
