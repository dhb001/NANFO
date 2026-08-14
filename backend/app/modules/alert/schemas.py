"""NANFO Backend - Alert module Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AlertRecordResponse(BaseModel):
    alert_id: uuid.UUID
    alert_key: str
    source: str
    status: str
    severity: str | None
    correlation_id: uuid.UUID
    payload: dict[str, Any]
    acknowledged_by_user_id: str | None
    resolved_by_user_id: str | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    items: list[AlertRecordResponse] = Field(default_factory=list)
    total: int
    status_counts: dict[str, int] = Field(default_factory=dict)


class AlertActionResponse(AlertRecordResponse):
    queue_status: str
    stream_entry_id: str | None = None
    warning: str | None = None
    idempotent_replay: bool
