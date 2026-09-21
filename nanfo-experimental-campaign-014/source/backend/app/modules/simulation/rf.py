"""Pure log-distance RF propagation in aligned local meters (ADR-021).

Walls are finite vertical surfaces, not infinite planes or axis-aligned boxes.
See docs/project/CompletionProgram/Physics.md for assumptions and limits.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.modules.simulation.evaluator import digest
from app.modules.simulation.schemas import Digest, Identifier, StrictModel

RF_VERSION = "log-distance-segment-walls.v1"
Coordinate = Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)]
Loss = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Gain = Annotated[float, Field(ge=-30, le=60, allow_inf_nan=False)]


class Scope(StrictModel):
    workspace_id: Identifier
    network_id: Identifier


class PointMeters(StrictModel):
    x: Coordinate
    y: Coordinate
    z: Coordinate


class Wall(StrictModel):
    wall_id: Identifier
    start: PointMeters
    end: PointMeters
    height_m: Annotated[float, Field(gt=0, le=1000, allow_inf_nan=False)]
    material: Literal["glass", "drywall", "concrete", "metal", "custom"]
    # Explicit overrides take precedence over the versioned illustrative defaults.
    loss_db: Loss | None = None

    @model_validator(mode="after")
    def valid_surface(self) -> Self:
        if (
            self.start.z != self.end.z
            or math.hypot(self.end.x - self.start.x, self.end.y - self.start.y) < 1e-6
        ):
            raise ValueError(
                "Wall needs a horizontal base segment of at least 1 micrometer"
            )
        if self.material == "custom" and self.loss_db is None:
            raise ValueError("Custom material requires explicit loss_db")
        if self.start.z + self.height_m <= self.start.z:
            raise ValueError(
                "Wall height is below coordinate floating-point resolution"
            )
        return self


# Nominal single-crossing dB values, not measured frequency-dependent coefficients.
DEFAULT_MATERIAL_LOSS_DB = {
    "glass": 3.0,
    "drywall": 4.0,
    "concrete": 12.0,
    "metal": 20.0,
}


class RFParameters(StrictModel):
    """Explicit radio parameters shared by direct RF and spatial adapters."""

    frequency_mhz: Annotated[float, Field(ge=100, le=100000, allow_inf_nan=False)]
    tx_power_dbm: Annotated[float, Field(ge=-100, le=60, allow_inf_nan=False)]
    tx_gain_dbi: Gain
    rx_gain_dbi: Gain
    path_loss_exponent: Annotated[float, Field(ge=1, le=6, allow_inf_nan=False)] = 2.0
    reference_distance_m: Annotated[float, Field(ge=1, le=100, allow_inf_nan=False)] = (
        1.0
    )
    # Optional operator assumption, never presented as a statistical confidence interval.
    uncertainty_db: (
        Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)] | None
    ) = None


class RFScene(RFParameters):
    model_version: Literal["log-distance-segment-walls.v1"] = RF_VERSION
    scope: Scope
    scene_id: Identifier
    coordinate_frame_id: Identifier
    geometry_source_id: Identifier
    transmitter_id: Identifier
    transmitter: PointMeters
    walls: Annotated[list[Wall], Field(max_length=256)]

    @model_validator(mode="after")
    def unique_walls(self) -> Self:
        if len({wall.wall_id for wall in self.walls}) != len(self.walls):
            raise ValueError("Duplicate wall ID")
        return self


class RFRequest(StrictModel):
    scene: RFScene
    receiver_id: Identifier
    receiver: PointMeters


class WallCrossing(StrictModel):
    wall_id: Identifier
    material: str
    loss_db: Loss
    loss_source: Literal["configured", "nominal_default"]


class RFResult(StrictModel):
    model_version: Literal["log-distance-segment-walls.v1"] = RF_VERSION
    source: Literal["operator_configured_model"] = "operator_configured_model"
    physical_safety_authorized: Literal[False] = False
    scope: Scope
    config_sha256: Digest
    input_sha256: Digest
    receiver_id: Identifier
    distance_m: float
    effective_distance_m: float
    distance_clamped: bool
    reference_loss_db: float
    distance_loss_db: float
    wall_loss_db: float
    signal_dbm: float
    crossings: list[WallCrossing]
    uncertainty_db: float | None
    interference_dbm: None = None
    sinr_db: None = None
    congestion: None = None


def canonical_scene(scene: RFScene) -> dict:
    value = scene.model_dump(mode="json")
    value["walls"].sort(key=lambda wall: wall["wall_id"])
    return value


def rf_config_hash(scene: RFScene) -> str:
    return digest(canonical_scene(scene))


def wall_intersects(start: PointMeters, end: PointMeters, wall: Wall) -> bool:
    """Interior ray crossing; include wall edges, exclude collinear/touching rays.

    A radio on a wall is not treated as passing through it. A corner shared by
    distinct wall IDs counts both surfaces; geometry must represent real surfaces.
    """
    dx, dy = end.x - start.x, end.y - start.y
    wx, wy = wall.end.x - wall.start.x, wall.end.y - wall.start.y
    denominator = dx * wy - dy * wx
    if abs(denominator) <= 1e-12 * math.hypot(dx, dy) * math.hypot(wx, wy):
        return False
    ax, ay = wall.start.x - start.x, wall.start.y - start.y
    t = (ax * wy - ay * wx) / denominator
    u = (ax * dy - ay * dx) / denominator
    if not (0 < t < 1 and 0 <= u <= 1):
        return False
    height = start.z + t * (end.z - start.z)
    return wall.start.z <= height <= wall.start.z + wall.height_m


def evaluate_rf(request: RFRequest) -> RFResult:
    # Revalidate at the pure boundary, including potentially mutated nested models.
    request = RFRequest.model_validate(request.model_dump())
    scene = request.scene
    distance = math.dist(
        (scene.transmitter.x, scene.transmitter.y, scene.transmitter.z),
        (request.receiver.x, request.receiver.y, request.receiver.z),
    )
    effective = max(distance, scene.reference_distance_m)
    reference_loss = 20 * math.log10(
        4 * math.pi * scene.reference_distance_m * scene.frequency_mhz * 1e6 / 299792458
    )
    distance_loss = (
        10
        * scene.path_loss_exponent
        * math.log10(effective / scene.reference_distance_m)
    )
    crossings = [
        WallCrossing(
            wall_id=wall.wall_id,
            material=wall.material,
            loss_db=wall.loss_db
            if wall.loss_db is not None
            else DEFAULT_MATERIAL_LOSS_DB[wall.material],
            loss_source="configured" if wall.loss_db is not None else "nominal_default",
        )
        for wall in sorted(scene.walls, key=lambda item: item.wall_id)
        if wall_intersects(scene.transmitter, request.receiver, wall)
    ]
    wall_loss = math.fsum(crossing.loss_db for crossing in crossings)
    return RFResult(
        scope=scene.scope,
        config_sha256=rf_config_hash(scene),
        input_sha256=digest(
            {**request.model_dump(mode="json"), "scene": canonical_scene(scene)}
        ),
        receiver_id=request.receiver_id,
        distance_m=distance,
        effective_distance_m=effective,
        distance_clamped=distance < scene.reference_distance_m,
        reference_loss_db=reference_loss,
        distance_loss_db=distance_loss,
        wall_loss_db=wall_loss,
        signal_dbm=scene.tx_power_dbm
        + scene.tx_gain_dbi
        + scene.rx_gain_dbi
        - reference_loss
        - distance_loss
        - wall_loss,
        crossings=crossings,
        uncertainty_db=scene.uncertainty_db,
    )
