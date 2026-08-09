"""NANFO Backend — Telemetry module repository.

Persistence operations for telemetry_records.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.telemetry.models import TelemetryRecord


class TelemetryRecordRepository:
    """Repository for telemetry metric persistence with idempotent insert semantics."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_by_event_id(self, event_id: uuid.UUID) -> TelemetryRecord | None:
        result = await self._db.execute(select(TelemetryRecord).where(TelemetryRecord.event_id == event_id))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        event_id: uuid.UUID,
        correlation_id: uuid.UUID,
        device_id: uuid.UUID,
        network_id: uuid.UUID,
        workspace_id: uuid.UUID,
        metric: str,
        value: float,
        unit: str | None,
        observed_at: datetime,
        source: str,
        tags: dict,
    ) -> TelemetryRecord:
        record = TelemetryRecord(
            event_id=event_id,
            correlation_id=correlation_id,
            device_id=device_id,
            network_id=network_id,
            workspace_id=workspace_id,
            metric=metric,
            value=value,
            unit=unit,
            observed_at=observed_at,
            source=source,
            tags=tags,
        )
        self._db.add(record)
        await self._db.flush()
        return record

    async def list_history(
        self,
        *,
        network_id: uuid.UUID | None = None,
        workspace_id: uuid.UUID | None = None,
        metric: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[TelemetryRecord], int]:
        query = select(TelemetryRecord)
        if network_id is not None:
            query = query.where(TelemetryRecord.network_id == network_id)
        if workspace_id is not None:
            query = query.where(TelemetryRecord.workspace_id == workspace_id)
        if metric:
            query = query.where(TelemetryRecord.metric == metric)

        query = query.order_by(TelemetryRecord.observed_at.desc(), TelemetryRecord.record_id.desc())
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self._db.execute(count_query)).scalar_one()
        rows = (
            await self._db.execute(
                query.offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def list_for_device(
        self,
        *,
        device_id: uuid.UUID,
        metric: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[TelemetryRecord], int]:
        query = select(TelemetryRecord).where(TelemetryRecord.device_id == device_id)
        if metric:
            query = query.where(TelemetryRecord.metric == metric)

        query = query.order_by(TelemetryRecord.observed_at.desc(), TelemetryRecord.record_id.desc())
        count_query = select(func.count()).select_from(query.subquery())
        total = (await self._db.execute(count_query)).scalar_one()
        rows = (
            await self._db.execute(
                query.offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def get_latest_observed_at(self) -> datetime | None:
        result = await self._db.execute(select(func.max(TelemetryRecord.observed_at)))
        return result.scalar_one_or_none()

    async def count_all(self) -> int:
        result = await self._db.execute(select(func.count()).select_from(TelemetryRecord))
        return result.scalar_one()
