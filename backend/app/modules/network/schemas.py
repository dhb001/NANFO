"""NANFO Backend — Network module Pydantic schemas.

Request/response schemas for network, device, and topology endpoints.
Topology analysis schemas for VS10 are included under this module ownership.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

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

    model_config = {"from_attributes": True}


class DeviceListResponse(BaseModel):
    items: list[DeviceResponse]
    total: int
    page: int
    page_size: int


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
