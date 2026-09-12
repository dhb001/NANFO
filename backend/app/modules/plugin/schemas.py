"""NANFO Backend - Plugin module Pydantic schemas."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class PluginInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    plugin_key: str = Field(min_length=3, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    signer: str = Field(min_length=1, max_length=120)
    signature: str = Field(min_length=8, max_length=256)
    dependencies: dict[str, JsonValue] = Field(default_factory=dict)
    sandbox: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("plugin_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return value.lower()

    @field_validator("dependencies", "sandbox", "metadata")
    @classmethod
    def bounded_json(cls, value: dict) -> dict:
        try:
            encoded = json.dumps(value, allow_nan=False)
        except (ValueError, RecursionError) as exc:
            raise ValueError("Declarations must contain finite, bounded JSON.") from exc
        if len(encoded.encode("utf-8")) > 65_536:
            raise ValueError("Each declaration object must not exceed 64 KiB.")
        return value


class RegistryCapabilities(BaseModel):
    registry_only: Literal[True] = True
    execution_supported: Literal[False] = False
    lifecycle_semantics: Literal["registry_flags_only"] = "registry_flags_only"


class PluginRecordResponse(RegistryCapabilities):
    plugin_id: uuid.UUID
    plugin_key: str
    name: str
    version: str
    manifest: dict[str, Any]
    signature_status: Literal["declared_unverified"] = "declared_unverified"
    dependency_status: Literal["declared_unverified"] = "declared_unverified"
    sandbox_status: Literal["not_executed"] = "not_executed"
    permissions_status: Literal["declared_unverified"] = "declared_unverified"
    status: Literal["installed", "enabled", "disabled", "failed", "uninstalled"]
    enabled: bool
    failure_reason: str | None
    queue_status: str
    stream_entry_id: str | None
    warning: str | None
    installed_at: datetime
    updated_at: datetime
    uninstalled_at: datetime | None = None

    @field_validator("signature_status", "dependency_status", "permissions_status", mode="before")
    @classmethod
    def mask_declaration_claims(cls, value: Any) -> str:
        return "declared_unverified"

    @field_validator("sandbox_status", mode="before")
    @classmethod
    def mask_execution_claims(cls, value: Any) -> str:
        return "not_executed"

    model_config = {"from_attributes": True}


class PluginListResponse(RegistryCapabilities):
    items: list[PluginRecordResponse] = Field(default_factory=list)
    total: int
    status_counts: dict[str, int] = Field(default_factory=dict)


class PluginActionResponse(PluginRecordResponse):
    idempotent_replay: bool
