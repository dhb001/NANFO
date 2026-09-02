"""NANFO Backend — Network module Pydantic schemas.

Request/response schemas for network, device, and topology endpoints.
Topology analysis schemas for VS10 are included under this module ownership.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from math import isfinite

from pydantic import BaseModel, Field, field_validator

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
