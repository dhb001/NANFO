"""ADR023 operator-provisioned fleet manifest and independent worker settings."""

from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.modules.telemetry.snmp_config import StrictConfig


class FleetTarget(StrictConfig):
    device_id: UUID
    binding_path: Path
    credentials_path: Path
    interval_seconds: Annotated[float, Field(ge=1, le=3600, allow_inf_nan=False)] = 10.0
    backoff_max_seconds: Annotated[float, Field(ge=1, le=3600, allow_inf_nan=False)] = 300.0
    poll_timeout_seconds: Annotated[float, Field(ge=1, le=300, allow_inf_nan=False)] = 25.0

    @field_validator("binding_path", "credentials_path")
    @classmethod
    def absolute_path(cls, path: Path) -> Path:
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("absolute provisioned path required")
        return path

    @model_validator(mode="after")
    def backoff_bounds(self) -> Self:
        if self.backoff_max_seconds < self.interval_seconds:
            raise ValueError("backoff must cover interval")
        return self


class FleetManifest(StrictConfig):
    version: Literal[1]
    targets: Annotated[tuple[FleetTarget, ...], Field(min_length=1, max_length=256)]

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, version):
        if type(version) is not int:
            raise ValueError("integer manifest version required")
        return version

    @model_validator(mode="after")
    def unique_devices(self) -> Self:
        if len({target.device_id for target in self.targets}) != len(self.targets):
            raise ValueError("duplicate device")
        return self


class FleetSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NANFO_FLEET_", extra="ignore", hide_input_in_errors=True)

    manifest_path: Path
    concurrency: int = Field(default=4, ge=1, le=32)
    lease_seconds: float = Field(default=30, ge=3, le=300, allow_inf_nan=False)
    db_timeout_seconds: float = Field(default=2, ge=0.1, le=10, allow_inf_nan=False)
    publish_timeout_seconds: float = Field(default=3, ge=0.1, le=30, allow_inf_nan=False)
    scan_seconds: float = Field(default=1, ge=0.1, le=30, allow_inf_nan=False)
    health_ttl_seconds: int = Field(default=90, ge=10, le=900)

    @model_validator(mode="after")
    def watchdog_budget(self) -> Self:
        if self.db_timeout_seconds >= self.lease_seconds / 3:
            raise ValueError("database deadline must be below watchdog interval")
        return self
