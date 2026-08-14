"""NANFO Backend - Report module Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ReportDateRangeRequest(BaseModel):
    start: datetime
    end: datetime


class GenerateReportRequest(BaseModel):
    workspace_id: uuid.UUID
    network_id: uuid.UUID | None = None
    report_type: str = Field(min_length=1, max_length=80)
    format: str = Field(min_length=1, max_length=16)
    date_range: ReportDateRangeRequest
    scope: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)


class ReportArtifactRef(BaseModel):
    artifact_id: str
    uri: str
    media_type: str
    checksum_sha256: str
    size_bytes: int
    generated_at: datetime


class ReportRecordResponse(BaseModel):
    report_id: uuid.UUID
    workspace_id: uuid.UUID
    network_id: uuid.UUID | None
    report_type: str
    format: str
    status: str
    date_range: dict[str, Any]
    scope: dict[str, Any]
    filters: dict[str, Any]
    artifacts: list[ReportArtifactRef] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    queue_status: str
    stream_entry_id: str | None
    warning: str | None
    idempotency_key: str | None
    correlation_id: uuid.UUID
    requested_by_user_id: str
    requested_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReportGenerateResponse(ReportRecordResponse):
    idempotent_replay: bool
