"""ADR-021/023 version-one spatial validation; units/limits are protocol constants."""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_serializer, model_validator

MAX_OBJECTS = 10_000
MAX_POSITION_M = 1_000_000
MAX_REVISION = 9_007_199_254_740_991
OBJECT_TYPES = ("campus", "building", "floor", "room", "rack", "device", "interface")
MIN_DIMENSION_M = 0.000001
MAX_WORLD_POSITION_M = 16_000_000

Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
Name = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
Revision = Annotated[int, Field(strict=True, ge=0, le=MAX_REVISION)]
Distance = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-MAX_POSITION_M, le=MAX_POSITION_M)]
Angle = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-math.tau, le=math.tau)]
Accuracy = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=MAX_POSITION_M)]
Dimension = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=MIN_DIMENSION_M, le=MAX_POSITION_M)]
Attenuation = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=100)]


class SpatialModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def reject_empty_or_nul_text(cls, value):
        if isinstance(value, str) and (not value.strip() or "\x00" in value):
            raise ValueError("Text must be nonblank and contain no NUL characters.")
        return value


class CoordinateSystem(SpatialModel):
    units: Literal["m"]
    up_axis: Literal["y"]


class Position(SpatialModel):
    x: Distance
    y: Distance
    z: Distance


class Rotation(SpatialModel):
    """Radians; column-vector local matrix is T @ Rz @ Ry @ Rx."""

    x: Angle
    y: Angle
    z: Angle


class Provenance(SpatialModel):
    source: Identifier
    accuracy_m: Accuracy | None

    @model_validator(mode="after")
    def fallback_is_unmeasured(self):
        if self.source == "schematic-fallback" and self.accuracy_m is not None:
            raise ValueError("Schematic fallback accuracy must be unknown (null).")
        return self


class BoxGeometry(SpatialModel):
    kind: Literal["box"]
    width: Dimension
    depth: Dimension
    height: Dimension


class SlabGeometry(SpatialModel):
    kind: Literal["slab"]
    width: Dimension
    depth: Dimension
    thickness: Dimension


class WallMaterial(SpatialModel):
    name: Name
    attenuation_db: Attenuation | None
    source: Identifier


class WallGeometry(SpatialModel):
    kind: Literal["wall"]
    length: Dimension
    height: Dimension
    thickness: Dimension
    material: WallMaterial


Geometry = Annotated[BoxGeometry | SlabGeometry | WallGeometry, Field(discriminator="kind")]


class SpatialObject(SpatialModel):
    object_id: Identifier
    parent_id: Identifier | None
    object_type: Literal["campus", "building", "floor", "room", "rack", "device", "interface", "wall"]
    name: Name
    position: Position
    rotation: Rotation
    device_id: uuid.UUID | None
    provenance: Provenance
    geometry: Geometry | None = None

    @model_serializer(mode="wrap")
    def preserve_geometry_omission(self, handler):
        value = handler(self)
        if self.geometry is None and "geometry" not in self.model_fields_set:
            value.pop("geometry", None)
        return value

    @model_validator(mode="after")
    def device_association(self):
        if self.device_id is not None and self.object_type != "device":
            raise ValueError("Only device objects may associate an inventory device.")
        if self.geometry is not None:
            allowed = {"building": "box", "room": "box", "rack": "box", "floor": "slab", "wall": "wall"}
            if allowed.get(self.object_type) != self.geometry.kind:
                raise ValueError("Geometry kind is not allowed for this object type.")
        return self


class SpatialSceneInput(SpatialModel):
    version: Literal[1]
    coordinate_system: CoordinateSystem
    objects: Annotated[list[SpatialObject], Field(max_length=MAX_OBJECTS)]

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("Scene version must be integer 1.")
        return value

    @model_validator(mode="after")
    def valid_hierarchy(self):
        objects = {obj.object_id: obj for obj in self.objects}
        if len(objects) != len(self.objects):
            raise ValueError("Scene object IDs must be unique.")
        devices = [obj.device_id for obj in self.objects if obj.device_id is not None]
        if len(set(devices)) != len(devices):
            raise ValueError("An inventory device may be associated only once.")

        # Strict type ordering proves acyclicity and bounds traversal to seven levels.
        ranks = {kind: index for index, kind in enumerate(OBJECT_TYPES)}
        for obj in self.objects:
            if obj.object_type == "wall":
                parent = objects.get(obj.parent_id)
                if parent is None or parent.object_type not in ("floor", "room"):
                    raise ValueError("A wall requires a direct floor or room parent.")
                continue
            if obj.parent_id is None:
                if obj.object_type == "interface":
                    raise ValueError("An interface requires a direct device parent.")
                continue
            parent = objects.get(obj.parent_id)
            if parent is None:
                raise ValueError("Every parent must exist in the replacement scene.")
            if parent.object_type == "wall" or ranks[parent.object_type] >= ranks[obj.object_type]:
                raise ValueError("Invalid containment hierarchy or cycle.")
            if obj.object_type == "interface" and parent.object_type != "device":
                raise ValueError("An interface requires a direct device parent.")
        return self


class SpatialSceneDocument(SpatialSceneInput):
    revision: Revision


class ReplaceSpatialSceneRequest(SpatialModel):
    expected_revision: Revision
    scene: SpatialSceneInput


class SpatialHistoryQuery(SpatialModel):
    page: Annotated[int, Field(strict=True, ge=1, le=1_000_000)] = 1
    page_size: Annotated[int, Field(strict=True, ge=1, le=100)] = 20


class SpatialHistoryEntry(SpatialModel):
    revision: Revision
    recorded_at: datetime
    actor_id: uuid.UUID | None
    origin: Literal["baseline", "replacement"]
    object_count: Annotated[int, Field(ge=0, le=MAX_OBJECTS)]


class SpatialHistoryList(SpatialModel):
    items: list[SpatialHistoryEntry]
    total: int
    page: int
    page_size: int


def empty_scene() -> SpatialSceneDocument:
    return SpatialSceneDocument(
        version=1, revision=0, coordinate_system=CoordinateSystem(units="m", up_axis="y"), objects=[],
    )
