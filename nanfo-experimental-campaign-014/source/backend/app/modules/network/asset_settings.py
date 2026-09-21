"""Network-owned local object-store settings; no shared config composition."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AssetSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NETWORK_ASSET_", extra="ignore")

    root: Path = Path("/var/lib/nanfo/network-assets")
    max_object_bytes: int = Field(default=8 * 1024 * 1024, ge=1, le=8 * 1024 * 1024)
    max_total_bytes: int = Field(default=1024 * 1024 * 1024, ge=1)
    max_objects: int = Field(default=10_000, ge=1, le=1_000_000)

    @field_validator("root")
    @classmethod
    def absolute_root(cls, value: Path) -> Path:
        if not value.is_absolute() or ".." in value.parts or value == Path("/"):
            raise ValueError("asset root must be an absolute non-root path without traversal")
        return value
