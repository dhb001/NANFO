"""NANFO Backend — Network module Pydantic schemas.

Request/response schemas for network, device, and topology endpoints.
Topology analysis schemas for VS10 are included under this module ownership.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import uuid
from datetime import datetime
from math import isfinite

from pydantic import BaseModel, Field, field_validator, model_validator

_ALLOWED_MODEL_MIME_TYPES = {
    "model/gltf-binary",
    "model/gltf+json",
    "application/octet-stream",
    "application/gltf-buffer",
    "application/gltf+json",
}
_MAX_MODEL_SIZE_BYTES = 8 * 1024 * 1024
_ALLOWED_DEVICE_GROUP_TYPES = {
    "site_hierarchy",
    "functional",
    "operational",
    "custom",
}

# ── Network schemas ───────────────────────────────────────────────────────────

class CreateNetworkRequest(BaseModel):
    workspace_id: uuid.UUID
    name: str
    description: str | None = None
    cidr: str | None = None


class NetworkResponse(BaseModel):
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    cidr: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NetworkListResponse(BaseModel):
    items: list[NetworkResponse]
    total: int
    page: int
    page_size: int


# ── Device schemas ────────────────────────────────────────────────────────────

class CreateDeviceRequest(BaseModel):
    hostname: str
    ip_address: str | None = None
    device_type: str
    vendor: str | None = None
    model: str | None = None
    location_hint: str | None = None
    spatial_ref_id: str | None = None


class UpdateDeviceRequest(BaseModel):
    spatial_ref_id: str | None


class DeviceResponse(BaseModel):
    device_id: uuid.UUID
    network_id: uuid.UUID
    hostname: str
    ip_address: str | None
    device_type: str
    vendor: str | None
    model: str | None
    location_hint: str | None
    spatial_ref_id: str | None
    status: str
    created_at: datetime

    @field_validator("ip_address", mode="before")
    @classmethod
    def stringify_ip_address(cls, value: object | None) -> str | None:
        if value is None:
            return None
        return str(value)

    model_config = {"from_attributes": True}


class DeviceListResponse(BaseModel):
    items: list[DeviceResponse]
    total: int
    page: int
    page_size: int


class UpsertCampusBuildingInput(BaseModel):
    building_id: str = Field(min_length=1, max_length=160)
    campus_key: str = Field(min_length=1, max_length=120)
    building_key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)
    geometry: str = Field(min_length=1, max_length=32)
    x: float
    z: float
    base_y: float
    width: float = Field(gt=0)
    depth: float = Field(gt=0)
    height: float = Field(gt=0)
    floors: int = Field(ge=1, le=128)
    footprint: list[list[float]]
    wall_material: str | None = Field(default=None, max_length=64)
    attenuation_db: float | None = None
    source: str | None = Field(default=None, max_length=32)

    @field_validator("geometry")
    @classmethod
    def validate_geometry(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"box", "extrude"}:
            raise ValueError("geometry must be one of: box, extrude")
        return normalized

    @field_validator("footprint")
    @classmethod
    def validate_footprint(cls, value: list[list[float]]) -> list[list[float]]:
        if len(value) < 3:
            raise ValueError("footprint must include at least three coordinate points")

        normalized: list[list[float]] = []
        for point in value:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("footprint points must be [x, z]")
            x = float(point[0])
            z = float(point[1])
            if not all(isfinite(coord) for coord in (x, z)):
                raise ValueError("footprint coordinates must be finite numbers")
            normalized.append([x, z])
        return normalized

    @field_validator("attenuation_db")
    @classmethod
    def validate_attenuation_db(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0 or value > 80:
            raise ValueError("attenuation_db must be within [0, 80]")
        return float(value)


class UpsertCampusBuildingsRequest(BaseModel):
    buildings: list[UpsertCampusBuildingInput] = Field(default_factory=list, max_length=1000)
    replace_existing: bool = True


class CampusBuildingResponse(BaseModel):
    campus_building_id: uuid.UUID
    network_id: uuid.UUID
    building_id: str
    campus_key: str
    building_key: str
    label: str
    geometry: str
    x: float
    z: float
    base_y: float
    width: float
    depth: float
    height: float
    floors: int
    footprint: list[list[float]]
    wall_material: str | None
    attenuation_db: float | None
    source: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CampusBuildingListResponse(BaseModel):
    items: list[CampusBuildingResponse]
    total: int


class UpsertCampusModelAssetRequest(BaseModel):
    model_file_name: str = Field(min_length=1, max_length=255)
    model_mime_type: str = Field(min_length=1, max_length=120)
    model_data_base64: str = Field(min_length=1, max_length=12_000_000)
    model_sha256: str = Field(min_length=64, max_length=64)
    model_size_bytes: int = Field(ge=1, le=_MAX_MODEL_SIZE_BYTES)
    mapping_by_device_id: dict[str, str] = Field(default_factory=dict)
    source: str | None = Field(default=None, max_length=64)
    replace_existing: bool = True

    @field_validator("model_file_name")
    @classmethod
    def validate_model_file_name(cls, value: str) -> str:
        normalized = value.strip()
        lowered = normalized.lower()
        if not normalized:
            raise ValueError("model_file_name cannot be empty")
        if not lowered.endswith((".glb", ".gltf")):
            raise ValueError("model_file_name must end with .glb or .gltf")
        return normalized

    @field_validator("model_mime_type")
    @classmethod
    def validate_model_mime_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_MODEL_MIME_TYPES:
            allowed = ", ".join(sorted(_ALLOWED_MODEL_MIME_TYPES))
            raise ValueError(f"model_mime_type must be one of: {allowed}")
        return normalized

    @field_validator("model_sha256")
    @classmethod
    def validate_model_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or not all(char in "0123456789abcdef" for char in normalized):
            raise ValueError("model_sha256 must be a 64-character lowercase hex digest")
        return normalized

    @field_validator("mapping_by_device_id")
    @classmethod
    def validate_mapping_by_device_id(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 10_000:
            raise ValueError("mapping_by_device_id supports at most 10000 items")

        normalized: dict[str, str] = {}
        for key, item in value.items():
            normalized_key = str(key).strip()
            normalized_value = str(item).strip()
            if not normalized_key:
                raise ValueError("mapping_by_device_id keys cannot be blank")
            if not normalized_value:
                raise ValueError("mapping_by_device_id values cannot be blank")
            if len(normalized_key) > 120:
                raise ValueError("mapping_by_device_id keys must be <= 120 characters")
            if len(normalized_value) > 240:
                raise ValueError("mapping_by_device_id values must be <= 240 characters")
            normalized[normalized_key] = normalized_value
        return normalized

    @model_validator(mode="after")
    def validate_model_payload_integrity(self) -> UpsertCampusModelAssetRequest:
        try:
            decoded = base64.b64decode(self.model_data_base64, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("model_data_base64 must be valid base64")

        if len(decoded) != self.model_size_bytes:
            raise ValueError("model_size_bytes must match decoded model_data_base64 length")

        digest = hashlib.sha256(decoded).hexdigest()
        if digest != self.model_sha256:
            raise ValueError("model_sha256 must match decoded model_data_base64 content")

        return self


class CampusModelAssetResponse(BaseModel):
    campus_model_asset_id: uuid.UUID
    network_id: uuid.UUID
    model_file_name: str
    model_mime_type: str
    model_data_base64: str
    model_sha256: str
    model_size_bytes: int
    mapping_by_device_id: dict[str, str]
    source: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CampusModelAssetListResponse(BaseModel):
    items: list[CampusModelAssetResponse]
    total: int


class UpsertDeviceGroupInput(BaseModel):
    group_key: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    group_type: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=400)
    selector: dict[str, str] = Field(default_factory=dict)
    device_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)

    @field_validator("group_key")
    @classmethod
    def validate_group_key(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "-")
        if not normalized:
            raise ValueError("group_key cannot be empty")
        if not all(char.isalnum() or char in {"-", "_", ":"} for char in normalized):
            raise ValueError("group_key contains invalid characters")
        return normalized

    @field_validator("group_type")
    @classmethod
    def validate_group_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_DEVICE_GROUP_TYPES:
            allowed = ", ".join(sorted(_ALLOWED_DEVICE_GROUP_TYPES))
            raise ValueError(f"group_type must be one of: {allowed}")
        return normalized

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be empty")
        return normalized

    @field_validator("selector")
    @classmethod
    def validate_selector(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, item in value.items():
            selector_key = str(key).strip().lower()
            selector_value = str(item).strip()
            if not selector_key:
                raise ValueError("selector keys cannot be blank")
            if not selector_value:
                raise ValueError("selector values cannot be blank")
            if len(selector_key) > 80:
                raise ValueError("selector keys must be <= 80 characters")
            if len(selector_value) > 240:
                raise ValueError("selector values must be <= 240 characters")
            normalized[selector_key] = selector_value
        return normalized

    @field_validator("device_ids")
    @classmethod
    def normalize_device_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        deduped: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for device_id in value:
            if device_id in seen:
                continue
            deduped.append(device_id)
            seen.add(device_id)
        return deduped

    @model_validator(mode="after")
    def validate_selector_or_devices_present(self) -> UpsertDeviceGroupInput:
        if len(self.device_ids) == 0 and len(self.selector) == 0:
            raise ValueError("either selector or device_ids must be provided")
        return self


class UpsertDeviceGroupsRequest(BaseModel):
    groups: list[UpsertDeviceGroupInput] = Field(default_factory=list, max_length=500)
    replace_existing: bool = False

    @field_validator("groups")
    @classmethod
    def validate_unique_group_keys(cls, value: list[UpsertDeviceGroupInput]) -> list[UpsertDeviceGroupInput]:
        seen: set[str] = set()
        for group in value:
            if group.group_key in seen:
                raise ValueError(f"duplicate group_key in request: {group.group_key}")
            seen.add(group.group_key)
        return value


class DeviceGroupResponse(BaseModel):
    device_group_id: uuid.UUID
    network_id: uuid.UUID
    group_key: str
    name: str
    group_type: str
    description: str | None
    selector: dict[str, str]
    device_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class DeviceGroupListResponse(BaseModel):
    items: list[DeviceGroupResponse]
    total: int


# ── Topology schemas ──────────────────────────────────────────────────────────

class TopologyNode(BaseModel):
    device_id: str
    hostname: str
    device_type: str
    status: str
    spatial_ref_id: str | None = None


class TopologyEdge(BaseModel):
    source_id: str
    target_id: str
    edge_type: str
    metadata: dict


class TopologyGraphResponse(BaseModel):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


class TopologyNeighbourEdge(BaseModel):
    device_id: str
    hostname: str
    device_type: str
    status: str
    spatial_ref_id: str | None = None
    edge_type: str
    edge_metadata: dict
    direction: str
    hop_depth: int


class TopologyDeviceNeighboursResponse(BaseModel):
    device: TopologyNode
    neighbours: list[TopologyNeighbourEdge]
    depth: int
    total: int


class TopologyImpactNode(BaseModel):
    device_id: str
    hostname: str
    device_type: str
    status: str
    spatial_ref_id: str | None = None
    hop_depth: int


class TopologyImpactResponse(BaseModel):
    device: TopologyNode
    impacts: list[TopologyImpactNode]
    max_hops: int
    total: int
