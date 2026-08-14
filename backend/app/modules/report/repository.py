"""NANFO Backend - Report module repository.

Persistence operations for report lifecycle records.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.report.models import ReportRecord


class ReportRepository:
    """Repository for report lifecycle persistence."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(
        self,
        *,
        report_id: uuid.UUID,
        workspace_id: uuid.UUID,
        network_id: uuid.UUID | None,
        report_type: str,
        output_format: str,
        status: str,
        date_range: dict,
        scope: dict,
        filters: dict,
        artifact_refs: list,
        error_context: dict,
        queue_status: str,
        stream_entry_id: str | None,
        warning: str | None,
        idempotency_key: str | None,
        correlation_id: uuid.UUID,
        requested_by_user_id: str,
        requested_at: datetime,
    ) -> ReportRecord:
        record = ReportRecord(
            report_id=report_id,
            workspace_id=workspace_id,
            network_id=network_id,
            report_type=report_type,
            output_format=output_format,
            status=status,
            date_range=date_range,
            scope=scope,
            filters=filters,
            artifact_refs=artifact_refs,
            error_context=error_context,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            requested_by_user_id=requested_by_user_id,
            requested_at=requested_at,
            completed_at=None,
        )
        self._db.add(record)
        await self._db.flush()
        return record

    async def get_by_id(self, report_id: uuid.UUID) -> ReportRecord | None:
        result = await self._db.execute(select(ReportRecord).where(ReportRecord.report_id == report_id))
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

    async def update_lifecycle(
        self,
        report: ReportRecord,
        *,
        status: str,
        queue_status: str,
        stream_entry_id: str | None,
        warning: str | None,
        artifact_refs: list | None = None,
        error_context: dict | None = None,
        completed_at: datetime | None = None,
    ) -> ReportRecord:
        report.status = status
        report.queue_status = queue_status
        report.stream_entry_id = stream_entry_id
        report.warning = warning
        if artifact_refs is not None:
            report.artifact_refs = artifact_refs
        if error_context is not None:
            report.error_context = error_context
        if completed_at is not None:
            report.completed_at = completed_at
        await self._db.flush()
        return report
