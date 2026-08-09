"""NANFO Backend — Telemetry module repository.

Persistence operations for telemetry_records.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
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
