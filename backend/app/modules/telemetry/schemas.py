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
    # Additive (ADR-028): API totals are counted over at most HISTORY_COUNT_CAP+1
    # rows; ``total_capped`` means "at least ``total``". Prefer cursor mode.
    total_capped: bool = False


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
    total_capped: bool = False


class TelemetryCursorRequest(BaseModel):
    pagination: Literal["page", "cursor"] = "page"
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    aggregation: TelemetryAggregation | None = None
    bucket_seconds: int | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.pagination == "cursor":
            if self.page != 1 or self.aggregation is not None or self.bucket_seconds is not None:
                raise ValueError("cursor mode requires raw history and page=1")
        elif self.cursor is not None:
            raise ValueError("cursor requires pagination=cursor")
        return self


class TelemetryCursorResponse(BaseModel):
    items: list[TelemetryRecordResponse]
    page_size: int
    next_cursor: str | None
    upper_observed_at: AwareDatetime | None
    upper_record_id: uuid.UUID | None


class TelemetryDeviceHistoryResponse(BaseModel):
    device_id: uuid.UUID
    items: list[TelemetryRecordResponse]
    total: int
    page: int
    page_size: int
    total_capped: bool = False


class TelemetrySLOWindowHealth(BaseModel):
    """Counter deltas observed in the last closed evaluation window."""

    start: AwareDatetime | None
    end: AwareDatetime
    seconds: float
    ingest_attempts: int
    ingest_failures: int
    invalid_samples: int
    dropped_samples: int
    invalid_sample_ratio: float
    counter_reset: bool


class TelemetrySLOTrendHealth(BaseModel):
    window_size: int
    max_window_size: int
    severity_transition_counts: dict[str, int]
    anomaly_reason_frequency: dict[str, int]


class TelemetrySLOHealth(BaseModel):
    """Additive read-only view of the collector-evaluated SLO state (ADR-028 C12)."""

    status: Literal["ok", "degraded", "critical", "unavailable"]
    severity_reason: str | None = None
    alert_active: bool = False
    anomaly_reason_flags: list[str] = Field(default_factory=list)
    anomaly_streak: int = 0
    evaluated_at: AwareDatetime | None = None
    evaluation_interval_seconds: float
    stale: bool
    window: TelemetrySLOWindowHealth | None = None
    trend: TelemetrySLOTrendHealth | None = None
    thresholds: dict[str, float | int] = Field(default_factory=dict)


class TelemetryHealthResponse(BaseModel):
    status: str
    ingest_lag_ms: int | None
    dropped_events: int
    latest_observed_at: datetime | None
    total_records: int
    # Additive (ADR-028): total_records comes from the planner estimate / a
    # bounded count cached for at least 60 s, never a full count per request.
    total_records_estimated: bool = False
    slo: TelemetrySLOHealth | None = None
