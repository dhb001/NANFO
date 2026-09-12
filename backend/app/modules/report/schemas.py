"""NANFO Backend - Report module Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ReportDateRangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: AwareDatetime
    end: AwareDatetime

    @field_validator("start", "end")
    @classmethod
    def utc(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bounded(self):
        if not self.start < self.end or self.end - self.start > timedelta(days=31):
            raise ValueError(
                "date_range must be increasing and at most 31 days; end is exclusive"
            )
        if self.end > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("date_range cannot extend into the future")
        return self


class ReportScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: Literal["all"] = "all"
    simulation_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    intent_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @field_validator("simulation_ids", "intent_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("duplicate source IDs")
        return sorted(value, key=str)


class ReportFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$"
    )
    alert_status: Literal["active", "acknowledged", "resolved"] | None = None
    alert_severity: (
        Literal["info", "warning", "critical", "low", "medium", "high"] | None
    ) = None
    max_rows: int = Field(default=100, ge=1, le=500, strict=True)


class GenerateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: uuid.UUID
    network_id: uuid.UUID | None = None
    report_type: Literal[
        "executive_summary",
        "operational_summary",
        "telemetry",
        "alerts",
        "simulation",
        "intent",
    ]
    format: Literal["pdf", "csv"]
    date_range: ReportDateRangeRequest
    scope: ReportScope = Field(default_factory=ReportScope)
    filters: ReportFilters = Field(default_factory=ReportFilters)

    @model_validator(mode="after")
    def relevant_filters(self):
        summary = self.report_type in {"executive_summary", "operational_summary"}
        if not summary:
            if self.scope.simulation_ids and self.report_type != "simulation":
                raise ValueError(
                    "simulation_ids require a simulation or summary report"
                )
            if self.scope.intent_ids and self.report_type != "intent":
                raise ValueError("intent_ids require an intent or summary report")
            if self.filters.metric and self.report_type != "telemetry":
                raise ValueError("metric requires a telemetry or summary report")
            if (
                self.filters.alert_status or self.filters.alert_severity
            ) and self.report_type != "alerts":
                raise ValueError("alert filters require an alerts or summary report")
        return self


class ReportArtifactRef(BaseModel):
    artifact_id: str
    uri: str
    media_type: str
    checksum_sha256: str
    size_bytes: int
    generated_at: datetime
    filename: str | None = None


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
    artifact_version: int = 0
    status_version: int = 0
    snapshot_sha256: str | None = None
    snapshot_summary: dict[str, Any] = Field(default_factory=dict)


class ReportGenerateResponse(ReportRecordResponse):
    idempotent_replay: bool


class ReportHistoryResponse(BaseModel):
    items: list[ReportRecordResponse]
    total: int
    page: int
    page_size: int
