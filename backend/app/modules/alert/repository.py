"""NANFO Backend - Alert module repository.

Persistence operations for alert lifecycle records.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, cast, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alert.models import AlertRecord


class AlertRepository:
    """Repository for alert lifecycle persistence."""

    def __init__(self, db: AsyncSession):
        self._db = db

    @staticmethod
    def _apply_filters(
        query,
        *,
        status: str | None,
        severity: str | None,
        source: str | None,
        correlation_id: uuid.UUID | None,
        search: str | None,
    ):
        if status is not None:
            query = query.where(AlertRecord.status == status)
        if severity is not None:
            query = query.where(AlertRecord.severity == severity)
        if source is not None:
            query = query.where(AlertRecord.source == source)
        if correlation_id is not None:
            query = query.where(AlertRecord.correlation_id == correlation_id)
        if search:
            normalized = search.strip()
            if normalized:
                pattern = f"%{normalized}%"
                query = query.where(
                    or_(
                        AlertRecord.alert_key.ilike(pattern),
                        AlertRecord.source.ilike(pattern),
                        cast(AlertRecord.correlation_id, String).ilike(pattern),
                        cast(AlertRecord.payload, String).ilike(pattern),
                    )
                )
        return query

    async def list_alerts(
        self,
        *,
        status: str | None,
        severity: str | None,
        source: str | None,
        correlation_id: uuid.UUID | None,
        search: str | None,
        limit: int,
    ) -> list[AlertRecord]:
        query = select(AlertRecord)
        query = self._apply_filters(
            query,
            status=status,
            severity=severity,
            source=source,
            correlation_id=correlation_id,
            search=search,
        )
        query = query.order_by(desc(AlertRecord.updated_at), desc(AlertRecord.created_at)).limit(limit)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, alert_id: uuid.UUID) -> AlertRecord | None:
        result = await self._db.execute(select(AlertRecord).where(AlertRecord.alert_id == alert_id))
        return result.scalar_one_or_none()

    async def get_by_generated_event_id(self, event_id: uuid.UUID) -> AlertRecord | None:
        result = await self._db.execute(
            select(AlertRecord).where(AlertRecord.generated_event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_unresolved_by_key(self, alert_key: str) -> AlertRecord | None:
        result = await self._db.execute(
            select(AlertRecord)
            .where(
                AlertRecord.alert_key == alert_key,
                AlertRecord.status != "resolved",
            )
            .order_by(desc(AlertRecord.updated_at), desc(AlertRecord.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_generated(
        self,
        *,
        alert_id: uuid.UUID,
        alert_key: str,
        source: str,
        severity: str | None,
        correlation_id: uuid.UUID,
        payload: dict,
        generated_event_id: uuid.UUID | None,
        created_at: datetime,
    ) -> AlertRecord:
        alert = AlertRecord(
            alert_id=alert_id,
            alert_key=alert_key,
            source=source,
            status="active",
            severity=severity,
            correlation_id=correlation_id,
            payload=payload,
            generated_event_id=generated_event_id,
            created_at=created_at,
            updated_at=created_at,
        )
        self._db.add(alert)
        await self._db.flush()
        return alert

    async def mark_acknowledged(
        self,
        alert: AlertRecord,
        *,
        acknowledged_by_user_id: str | None,
        acknowledged_at: datetime,
        payload: dict,
        acknowledged_event_id: uuid.UUID | None,
    ) -> AlertRecord:
        alert.status = "acknowledged"
        alert.acknowledged_by_user_id = acknowledged_by_user_id
        alert.acknowledged_at = acknowledged_at
        alert.payload = payload
        if acknowledged_event_id is not None:
            alert.acknowledged_event_id = acknowledged_event_id
        await self._db.flush()
        return alert

    async def mark_resolved(
        self,
        alert: AlertRecord,
        *,
        resolved_by_user_id: str | None,
        resolved_at: datetime,
        payload: dict,
        resolved_event_id: uuid.UUID | None,
    ) -> AlertRecord:
        alert.status = "resolved"
        alert.resolved_by_user_id = resolved_by_user_id
        alert.resolved_at = resolved_at
        alert.payload = payload
        if resolved_event_id is not None:
            alert.resolved_event_id = resolved_event_id
        await self._db.flush()
        return alert
