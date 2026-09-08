"""NANFO Backend — Telemetry module Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

TelemetryAggregation = Literal["avg", "min", "max", "sum"]


class TelemetryTimeRange(BaseModel):
    start_time: AwareDatetime | None = None
    end_time: AwareDatetime | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def normalize_utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.start_time is not None and self.end_time is not None and self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time (exclusive)")
        return self


class TelemetryHistoryQuery(TelemetryTimeRange):
    metric: str | None = None
    aggregation: TelemetryAggregation | None = None
    bucket_seconds: int | None = Field(default=None, ge=1, le=86400)

    @model_validator(mode="after")
    def validate_aggregation(self) -> Self:
        if self.aggregation is not None:
            if not self.metric or not self.metric.strip():
                raise ValueError("aggregation requires a metric")
            if self.metric.strip().startswith("flow_"):
                raise ValueError("flow_* aggregation is unavailable: snapshot v1 has no durable flow match identity; use raw history")
            if self.start_time is None or self.end_time is None or self.bucket_seconds is None:
                raise ValueError("aggregation requires start_time, end_time and bucket_seconds")
            if self.end_time - self.start_time > timedelta(days=7):
                raise ValueError("aggregation time range must not exceed seven days")
        elif self.bucket_seconds is not None:
            raise ValueError("bucket_seconds requires aggregation")
        return self


class TelemetryAggregateResponse(BaseModel):
    device_id: uuid.UUID
    metric: str
    unit: str | None
    source: str
    port_no: str | None
    peer_host: str | None
    run_id: str | None
    bucket_start: AwareDatetime
    value: float
    sample_count: int


class TelemetryAggregationResponse(BaseModel):
    items: list[TelemetryAggregateResponse]
    total: int
    page: int
    page_size: int


class TelemetryRecordResponse(BaseModel):
    record_id: uuid.UUID
    event_id: uuid.UUID
    correlation_id: uuid.UUID
    device_id: uuid.UUID
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    metric: str
    value: float
    unit: str | None
    observed_at: datetime
    source: str
    tags: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class TelemetryHistoryResponse(BaseModel):
    items: list[TelemetryRecordResponse]
    total: int
    page: int
    page_size: int


class TelemetryDeviceHistoryResponse(BaseModel):
    device_id: uuid.UUID
    items: list[TelemetryRecordResponse]
    total: int
    page: int
    page_size: int


class TelemetryHealthResponse(BaseModel):
    status: str
    ingest_lag_ms: int | None
    dropped_events: int
    latest_observed_at: datetime | None
    total_records: int
