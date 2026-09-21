"""NANFO Backend — Telemetry module repository.

Persistence operations for telemetry_records.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.telemetry.models import TelemetryRecord
from app.modules.telemetry.schemas import (
    TelemetryAggregateResponse,
    TelemetryAggregation,
    TelemetryHistoryQuery,
    TelemetryTimeRange,
)


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
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        aggregation: TelemetryAggregation | None = None,
        bucket_seconds: int | None = None,
    ) -> tuple[list[TelemetryRecord] | list[TelemetryAggregateResponse], int]:
        bounds = TelemetryHistoryQuery(
            metric=metric, start_time=start_time, end_time=end_time,
            aggregation=aggregation, bucket_seconds=bucket_seconds,
        )
        query = select(TelemetryRecord)
        if network_id is not None:
            query = query.where(TelemetryRecord.network_id == network_id)
        if workspace_id is not None:
            query = query.where(TelemetryRecord.workspace_id == workspace_id)
        if metric:
            query = query.where(TelemetryRecord.metric == metric)

        if bounds.start_time is not None:
            query = query.where(TelemetryRecord.observed_at >= bounds.start_time)
        if bounds.end_time is not None:
            query = query.where(TelemetryRecord.observed_at < bounds.end_time)

        if aggregation is not None:
            # Epoch-aligned UTC buckets need no Timescale extension. Count groups,
            # not samples, before pagination; absent buckets are never zero-filled.
            port = TelemetryRecord.tags["port_no"].astext.label("port_no")
            peer = TelemetryRecord.tags["peer_host"].astext.label("peer_host")
            run = TelemetryRecord.tags["run_id"].astext.label("run_id")
            bucket = func.to_timestamp(
                func.floor(func.extract("epoch", TelemetryRecord.observed_at) / bucket_seconds)
                * bucket_seconds
            ).label("bucket_start")
            dimensions = (
                TelemetryRecord.device_id, TelemetryRecord.metric,
                TelemetryRecord.unit, TelemetryRecord.source, port, peer, run, bucket,
            )
            aggregate = {"avg": func.avg, "min": func.min, "max": func.max, "sum": func.sum}[aggregation]
            grouped = query.with_only_columns(
                *dimensions, aggregate(TelemetryRecord.value).label("value"),
                func.count().label("sample_count"),
            ).group_by(*dimensions)
            total = (await self._db.execute(select(func.count()).select_from(grouped.subquery()))).scalar_one()
            result = await self._db.execute(
                grouped.order_by(
                    bucket.desc(), TelemetryRecord.device_id, TelemetryRecord.metric,
                    TelemetryRecord.unit.asc().nullsfirst(), TelemetryRecord.source, port.asc().nullsfirst(),
                    peer.asc().nullsfirst(), run.asc().nullsfirst(),
                ).offset((page - 1) * page_size).limit(page_size)
            )
            return [TelemetryAggregateResponse.model_validate(row) for row in result.mappings().all()], total

        query = query.order_by(TelemetryRecord.observed_at.desc(), TelemetryRecord.record_id.desc())
        count_query = select(func.count()).select_from(query.order_by(None).subquery())
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
        network_id: uuid.UUID,
        workspace_id: uuid.UUID,
        metric: str | None = None,
        page: int = 1,
        page_size: int = 50,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> tuple[list[TelemetryRecord], int]:
        bounds = TelemetryTimeRange(start_time=start_time, end_time=end_time)
        query = select(TelemetryRecord).where(
            TelemetryRecord.device_id == device_id,
            TelemetryRecord.network_id == network_id,
            TelemetryRecord.workspace_id == workspace_id,
        )
        if metric:
            query = query.where(TelemetryRecord.metric == metric)
        if bounds.start_time is not None:
            query = query.where(TelemetryRecord.observed_at >= bounds.start_time)
        if bounds.end_time is not None:
            query = query.where(TelemetryRecord.observed_at < bounds.end_time)

        query = query.order_by(TelemetryRecord.observed_at.desc(), TelemetryRecord.record_id.desc())
        count_query = select(func.count()).select_from(query.order_by(None).subquery())
        total = (await self._db.execute(count_query)).scalar_one()
        rows = (
            await self._db.execute(
                query.offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def list_history_keyset(
        self, *, workspace_id: uuid.UUID, network_id: uuid.UUID | None,
        query: TelemetryHistoryQuery, page_size: int, cutoff: datetime,
        upper: tuple[datetime, uuid.UUID] | None,
        after: tuple[datetime, uuid.UUID] | None,
    ) -> list[TelemetryRecord]:
        if workspace_id is None or not 1 <= page_size <= 200 or query.aggregation is not None:
            raise ValueError("keyset requires workspace-scoped bounded raw history")
        stmt = select(TelemetryRecord).where(
            TelemetryRecord.workspace_id == workspace_id,
            TelemetryRecord.created_at <= cutoff,
        )
        if network_id is not None:
            stmt = stmt.where(TelemetryRecord.network_id == network_id)
        if query.metric is not None:
            stmt = stmt.where(TelemetryRecord.metric == query.metric)
        if query.start_time is not None:
            stmt = stmt.where(TelemetryRecord.observed_at >= query.start_time)
        if query.end_time is not None:
            stmt = stmt.where(TelemetryRecord.observed_at < query.end_time)
        key = tuple_(TelemetryRecord.observed_at, TelemetryRecord.record_id)
        if upper is not None:
            stmt = stmt.where(key <= upper)
        if after is not None:
            stmt = stmt.where(key < after)
        rows = await self._db.scalars(stmt.order_by(
            TelemetryRecord.observed_at.desc(), TelemetryRecord.record_id.desc(),
        ).limit(page_size + 1))
        return list(rows.all())

    async def get_latest_observed_at(self) -> datetime | None:
        result = await self._db.execute(select(func.max(TelemetryRecord.observed_at)))
        return result.scalar_one_or_none()

    async def get_latest_scope(self) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        query = (
            select(TelemetryRecord.workspace_id, TelemetryRecord.network_id)
            .order_by(TelemetryRecord.observed_at.desc(), TelemetryRecord.record_id.desc())
            .limit(1)
        )
        result = await self._db.execute(query)
        row = result.first()
        if inspect.isawaitable(row):
            row = await row
        if row is None:
            return None, None
        return row[0], row[1]

    async def count_all(self) -> int:
        result = await self._db.execute(select(func.count()).select_from(TelemetryRecord))
        return result.scalar_one()
