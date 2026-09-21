"""Canonical Network v1 scene -> RF request via its public pure transform contract.

Network world (X,Y,Z), Y-up, maps to RF (X,-Z,Y), Z-up. No ORM/SQL,
placement generation, asset fitting, inferred walls or RF-to-capacity mapping.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.modules.network.spatial_schemas import (
    Identifier as SpatialIdentifier,
    Position,
    SpatialSceneDocument,
    WallGeometry,
)
from app.modules.network.spatial_transforms import Matrix4, transform_point, world_matrices
from app.modules.simulation.evaluator import digest
from app.modules.simulation.rf import (
    Loss,
    PointMeters,
    RFParameters,
    RFRequest,
    RFScene,
    Scope,
    Wall,
    rf_config_hash,
)
from app.modules.simulation.schemas import Digest, Identifier, StrictModel
from app.modules.simulation.snapshot import ValueSource

ADAPTER_VERSION = "canonical-spatial-rf.v1"


class SpatialRadio(StrictModel):
    object_id: SpatialIdentifier
    device_id: Annotated[UUID, Field(strict=False)]
    # Explicit alias only because RF identifiers have a narrower syntax than spatial IDs.
    transmitter_id: Identifier
    local_offset_m: Position
    parameters: RFParameters
    source: ValueSource


class SpatialReceiver(StrictModel):
    receiver_id: Identifier
    frame_object_id: SpatialIdentifier
    local_position_m: Position
    source: ValueSource


class SpatialWall(StrictModel):
    wall_id: Identifier
    frame_object_id: SpatialIdentifier
    start: Position
    end: Position
    height_m: Annotated[float, Field(gt=0, le=1000, allow_inf_nan=False)]
    material: Literal["glass", "drywall", "concrete", "metal", "custom"]
    loss_db: Loss | None = None
    source: ValueSource

    @model_validator(mode="after")
    def horizontal_base(self) -> Self:
        if self.start.y != self.end.y:
            raise ValueError(
                "Canonical wall base must be horizontal in its local Y-up frame"
            )
        return self


class CanonicalWall(StrictModel):
    """Explicit RF alias/evidence; dimensions and material belong to Network."""

    wall_id: Identifier
    object_id: SpatialIdentifier
    source: ValueSource


def _wall_frame(wall: SpatialWall | CanonicalWall) -> str:
    return wall.object_id if isinstance(wall, CanonicalWall) else wall.frame_object_id


def spatial_document_hash(scene: SpatialSceneDocument) -> str:
    """Hash validated JSON including revision, sorting objects by their canonical IDs."""
    scene = SpatialSceneDocument.model_validate(scene.model_dump())
    value = scene.model_dump(mode="json")
    value["objects"].sort(key=lambda obj: obj["object_id"])
    return digest(value)


class SpatialRFRequest(StrictModel):
    version: Literal["canonical-spatial-rf.v1"] = ADAPTER_VERSION
    scope: Scope
    scene_id: Identifier
    coordinate_frame_id: Identifier
    scene: SpatialSceneDocument
    # Must pin spatial_document_hash(scene), not an unrelated file or network hash.
    scene_source: ValueSource
    radio: SpatialRadio
    receiver: SpatialReceiver
    walls: Annotated[list[SpatialWall | CanonicalWall], Field(max_length=256)]
    # Required even for [], so absent wall geometry cannot silently mean free space.
    wall_inventory_source: ValueSource

    @model_validator(mode="after")
    def matching_evidence(self) -> Self:
        if self.scene.revision == 0:
            raise ValueError("A persisted canonical scene revision is required")
        if self.scene_source.artifact_sha256 != spatial_document_hash(self.scene):
            raise ValueError("Spatial document evidence hash mismatch")
        if len({wall.wall_id for wall in self.walls}) != len(self.walls):
            raise ValueError("Duplicate wall ID")
        objects = {obj.object_id: obj for obj in self.scene.objects}
        references = [wall.object_id for wall in self.walls if isinstance(wall, CanonicalWall)]
        canonical_ids = {obj.object_id for obj in self.scene.objects if obj.object_type == "wall"}
        if len(set(references)) != len(references) or set(references) != canonical_ids:
            raise ValueError("Every canonical wall must be referenced exactly once")
        for wall in self.walls:
            if isinstance(wall, CanonicalWall):
                geometry = objects[wall.object_id].geometry
                if not isinstance(geometry, WallGeometry):
                    raise ValueError("Canonical RF wall requires explicit wall geometry")
                if geometry.material.attenuation_db is None:
                    raise ValueError("Canonical RF wall requires known material attenuation")
                if geometry.material.source == "schematic-fallback":
                    raise ValueError("Schematic fallback is not RF material evidence")
            elif wall.frame_object_id in canonical_ids:
                raise ValueError("Use a canonical wall reference, not geometry overrides")
        ap = objects.get(self.radio.object_id)
        if (
            ap is None
            or ap.object_type != "device"
            or ap.device_id != self.radio.device_id
        ):
            raise ValueError("AP must match an explicit canonical device association")
        referenced = [self.radio.object_id, self.receiver.frame_object_id]
        referenced.extend(_wall_frame(wall) for wall in self.walls)
        for object_id in referenced:
            while object_id is not None:
                obj = objects.get(object_id)
                if obj is None:
                    raise ValueError("Missing canonical geometry frame")
                if (
                    obj.provenance.source == "schematic-fallback"
                    or obj.provenance.accuracy_m is None
                ):
                    raise ValueError(
                        "Every referenced placement ancestor needs explicit accuracy evidence"
                    )
                object_id = obj.parent_id
        sources = [
            self.scene_source,
            self.wall_inventory_source,
            self.radio.source,
            self.receiver.source,
            *(wall.source for wall in self.walls),
        ]
        if any(source.source_id == "schematic-fallback" for source in sources):
            raise ValueError("Schematic fallback is not RF geometry evidence")
        return self


class SpatialRFProvenance(StrictModel):
    version: Literal["canonical-spatial-rf.v1"] = ADAPTER_VERSION
    scope: Scope
    scene_revision: int
    spatial_document_sha256: Digest
    adapter_input_sha256: Digest
    rf_config_sha256: Digest
    axis_conversion: Literal["network(X,Y,Z)->rf(X,-Z,Y)"] = (
        "network(X,Y,Z)->rf(X,-Z,Y)"
    )
    radio_object_id: SpatialIdentifier
    radio_device_id: str
    receiver_frame_object_id: SpatialIdentifier
    wall_frame_object_ids: dict[Identifier, SpatialIdentifier]
    scene_source: ValueSource
    radio_source: ValueSource
    receiver_source: ValueSource
    wall_inventory_source: ValueSource
    wall_sources: dict[Identifier, ValueSource]
    # Values are declared local positional accuracies, not propagated RF uncertainty.
    placement_accuracy_m: dict[SpatialIdentifier, float]
    physical_safety_authorized: Literal[False] = False


def _rf_point(matrix: Matrix4, position: Position) -> PointMeters:
    x, y, z = transform_point(matrix, (position.x, position.y, position.z))
    # Validation rejects composed positions beyond the RF bound; never clamp/rebase.
    return PointMeters(x=x, y=-z, z=y)


def build_spatial_rf(
    request: SpatialRFRequest,
) -> tuple[RFRequest, SpatialRFProvenance]:
    request = SpatialRFRequest.model_validate(request.model_dump())
    matrices = world_matrices(request.scene)
    objects = {obj.object_id: obj for obj in request.scene.objects}
    walls = []
    for wall in sorted(request.walls, key=lambda item: item.wall_id):
        matrix = matrices[_wall_frame(wall)]
        if isinstance(wall, CanonicalWall):
            geometry = objects[wall.object_id].geometry
            start_local = Position(x=0, y=0, z=0)
            end_local = Position(x=geometry.length, y=0, z=0)
            height = geometry.height
            material, loss = "custom", geometry.material.attenuation_db
        else:
            start_local, end_local = wall.start, wall.end
            height, material, loss = wall.height_m, wall.material, wall.loss_db
        # V1 RF supports vertical surfaces only. Do not discard parent pitch/roll.
        if any(
            abs(matrix[row][1] - expected) > 1e-12
            for row, expected in enumerate((0.0, 1.0, 0.0))
        ):
            raise ValueError(
                "Wall frame must preserve world up; tilted walls unsupported"
            )
        start, end = _rf_point(matrix, start_local), _rf_point(matrix, end_local)
        if abs(start.z - end.z) > 1e-8:
            raise ValueError("Transformed wall base is not horizontal")
        # Remove only floating rotation residue within the documented tolerance.
        end = PointMeters(x=end.x, y=end.y, z=start.z)
        if isinstance(wall, CanonicalWall):
            # Validate the top, too: bounded endpoints alone do not bound a volume.
            PointMeters(x=start.x, y=start.y, z=start.z + height)
            PointMeters(x=end.x, y=end.y, z=end.z + height)
        walls.append(
            Wall(
                wall_id=wall.wall_id,
                start=start,
                end=end,
                height_m=height,
                material=material,
                loss_db=loss,
            )
        )
    scene = RFScene(
        **request.radio.parameters.model_dump(),
        scope=request.scope,
        scene_id=request.scene_id,
        coordinate_frame_id=request.coordinate_frame_id,
        geometry_source_id=request.wall_inventory_source.source_id,
        transmitter_id=request.radio.transmitter_id,
        transmitter=_rf_point(
            matrices[request.radio.object_id], request.radio.local_offset_m
        ),
        walls=walls,
    )
    rf_request = RFRequest(
        scene=scene,
        receiver_id=request.receiver.receiver_id,
        receiver=_rf_point(
            matrices[request.receiver.frame_object_id],
            request.receiver.local_position_m,
        ),
    )
    canonical = request.model_dump(mode="json")
    canonical["scene"]["objects"].sort(key=lambda obj: obj["object_id"])
    canonical["walls"].sort(key=lambda wall: wall["wall_id"])
    accuracy = {}
    for object_id in [
        request.radio.object_id,
        request.receiver.frame_object_id,
        *(_wall_frame(wall) for wall in request.walls),
    ]:
        while object_id is not None:
            obj = objects[object_id]
            accuracy[object_id] = obj.provenance.accuracy_m
            object_id = obj.parent_id
    provenance = SpatialRFProvenance(
        scope=request.scope,
        scene_revision=request.scene.revision,
        spatial_document_sha256=spatial_document_hash(request.scene),
        adapter_input_sha256=digest(canonical),
        rf_config_sha256=rf_config_hash(scene),
        radio_object_id=request.radio.object_id,
        radio_device_id=str(request.radio.device_id),
        receiver_frame_object_id=request.receiver.frame_object_id,
        wall_frame_object_ids={
            wall.wall_id: _wall_frame(wall) for wall in request.walls
        },
        scene_source=request.scene_source,
        radio_source=request.radio.source,
        receiver_source=request.receiver.source,
        wall_inventory_source=request.wall_inventory_source,
        wall_sources={wall.wall_id: wall.source for wall in request.walls},
        placement_accuracy_m=accuracy,
    )
    return rf_request, provenance
