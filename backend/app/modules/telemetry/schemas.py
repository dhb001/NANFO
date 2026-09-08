"""NANFO Backend — Telemetry module Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


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
