"""Network-owned local object-store settings; no shared config composition."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AssetSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NETWORK_ASSET_", extra="ignore")

    root: Path = Path("/var/lib/nanfo/network-assets")
    max_object_bytes: int = Field(default=8 * 1024 * 1024, ge=1, le=8 * 1024 * 1024)
    #: Global safety cap over every stored object (all tenants, retained history).
    max_total_bytes: int = Field(default=1024 * 1024 * 1024, ge=1)
    max_objects: int = Field(default=10_000, ge=1, le=1_000_000)
    #: Per-network quota, accounted from ACTIVE asset rows in PostgreSQL (C4).
    network_max_active_bytes: int = Field(default=256 * 1024 * 1024, ge=1)
    network_max_active_assets: int = Field(default=64, ge=1, le=100_000)
    #: Single-link ``.upload-*`` temporaries older than this are abandoned.
    stale_upload_seconds: int = Field(default=15 * 60, ge=60, le=7 * 24 * 3600)

    @field_validator("root")
    @classmethod
    def absolute_root(cls, value: Path) -> Path:
        if not value.is_absolute() or ".." in value.parts or value == Path("/"):
            raise ValueError("asset root must be an absolute non-root path without traversal")
        return value
