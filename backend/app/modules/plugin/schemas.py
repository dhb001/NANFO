"""NANFO Backend - Plugin module Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PluginInstallRequest(BaseModel):
    plugin_key: str = Field(min_length=3, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    signer: str = Field(min_length=1, max_length=120)
    signature: str = Field(min_length=8, max_length=256)
    dependencies: dict[str, Any] = Field(default_factory=dict)
    sandbox: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginRecordResponse(BaseModel):
    plugin_id: uuid.UUID
    plugin_key: str
    name: str
    version: str
    manifest: dict[str, Any]
    signature_status: str
    dependency_status: str
    sandbox_status: str
    status: str
    enabled: bool
    failure_reason: str | None
    queue_status: str
    stream_entry_id: str | None
    warning: str | None
    installed_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PluginListResponse(BaseModel):
    items: list[PluginRecordResponse] = Field(default_factory=list)
    total: int
    status_counts: dict[str, int] = Field(default_factory=dict)


class PluginActionResponse(PluginRecordResponse):
    idempotent_replay: bool
