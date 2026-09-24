"""Read-side telemetry service: history pages, device history and health."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.health import TelemetryHealthReader
from app.modules.telemetry.repository import TelemetryRecordRepository
from app.modules.telemetry.schemas import (
    TelemetryAggregation,
    TelemetryAggregationResponse,
    TelemetryDeviceHistoryResponse,
    TelemetryHealthResponse,
    TelemetryHistoryResponse,
    TelemetryRecordResponse,
)


def _bounded_total(total: int, count_cap: int | None) -> tuple[int, bool]:
    if count_cap is not None and total > count_cap:
        return count_cap, True
    return total, False


class TelemetryQueryService:
    """Read-side service for telemetry history, device metrics, and health.

    ``event_redis`` is accepted for signature compatibility only: health is
    read-only and never publishes (ADR-028 C12).
    """

    def __init__(
        self,
        db: AsyncSession,
        counter_service: TelemetryHealthCounterService | None = None,
        event_redis: aioredis.Redis | None = None,
    ):
        self._repo = TelemetryRecordRepository(db)
        self._counter_service = counter_service
        del event_redis

    async def get_history(
        self,
        *,
        network_id: uuid.UUID | None,
        workspace_id: uuid.UUID | None,
        metric: str | None,
        page: int,
        page_size: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        aggregation: TelemetryAggregation | None = None,
        bucket_seconds: int | None = None,
        count_cap: int | None = None,
    ) -> TelemetryHistoryResponse | TelemetryAggregationResponse:
        options: dict[str, Any] = {} if count_cap is None else {"count_cap": count_cap}
        rows, total = await self._repo.list_history(
            network_id=network_id,
            workspace_id=workspace_id,
            metric=metric,
            page=page,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
            aggregation=aggregation,
            bucket_seconds=bucket_seconds,
            **options,
        )
        total, capped = _bounded_total(total, count_cap)
        if aggregation is not None:
            return TelemetryAggregationResponse(items=rows, total=total, page=page, page_size=page_size,
                                                total_capped=capped)
        return TelemetryHistoryResponse(
            items=[TelemetryRecordResponse.model_validate(row) for row in rows],
            total=total, page=page, page_size=page_size, total_capped=capped,
        )

    async def get_device_history(
        self,
        *,
        device_id: uuid.UUID,
        network_id: uuid.UUID,
        workspace_id: uuid.UUID,
        metric: str | None,
        page: int,
        page_size: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        count_cap: int | None = None,
    ) -> TelemetryDeviceHistoryResponse:
        options: dict[str, Any] = {} if count_cap is None else {"count_cap": count_cap}
        rows, total = await self._repo.list_for_device(
            device_id=device_id,
            network_id=network_id,
            workspace_id=workspace_id,
            metric=metric,
            page=page,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
            **options,
        )
        total, capped = _bounded_total(total, count_cap)
        return TelemetryDeviceHistoryResponse(
            device_id=device_id,
            items=[TelemetryRecordResponse.model_validate(row) for row in rows],
            total=total, page=page, page_size=page_size, total_capped=capped,
        )

    async def get_health(self) -> TelemetryHealthResponse:
        return await TelemetryHealthReader(self._repo, self._counter_service).read()
