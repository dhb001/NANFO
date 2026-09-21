"""NANFO Backend - Alert module Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, JsonValue


class LegacyAlertIdentity(BaseModel):
    org_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    network_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None
    port_no: int | None = Field(default=None, ge=0, le=2**32 - 1)
    peer_host: str | None = Field(default=None, max_length=256)
    run_id: str | None = Field(default=None, max_length=256)
    rule_version: str | None = Field(default=None, max_length=256)
    rule: dict[str, JsonValue] | None = None

    @classmethod
    def normalize(cls, payload):
        nested = payload.get("scope") or {}
        if not isinstance(nested, dict):
            raise ValueError("Invalid legacy scope")
        values = {key: payload.get(key) if payload.get(key) is not None else nested.get(key)
                  for key in cls.model_fields}
        normalized = cls.model_validate(values).model_dump(mode="json")
        for key in cls.model_fields:
            if payload.get(key) is not None and nested.get(key) is not None:
                other = cls.model_validate({**values, key: nested[key]}).model_dump(mode="json")
                if other[key] != normalized[key]:
                    raise ValueError("Conflicting legacy scope")
        return normalized


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


class AlertHistoryEntry(BaseModel):
    model_config = {"from_attributes": True}
    event_id: uuid.UUID
    alert_id: uuid.UUID
    event_type: str
    correlation_id: uuid.UUID
    occurred_at: datetime
    payload: dict[str, Any]


class AlertHistoryResponse(BaseModel):
    alert_id: uuid.UUID
    items: list[AlertHistoryEntry]
    total: int
