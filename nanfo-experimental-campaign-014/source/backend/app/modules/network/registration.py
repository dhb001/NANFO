"""ADR-022 asset-local to canonical scene registration schema.

Asset persistence owns the nullable registration field; null is not identity.
Column vectors use T @ Rz @ Ry @ Rx @ S, with explicit meter/Y-up target.
"""

from typing import Annotated, Literal

from pydantic import Field, field_validator

from app.modules.network.spatial_schemas import Identifier, Position, Rotation, SpatialModel

ScaleFactor = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0.000001, le=1_000_000)]


class RegistrationScale(SpatialModel):
    x: ScaleFactor
    y: ScaleFactor
    z: ScaleFactor


class AssetRegistration(SpatialModel):
    version: Literal[1]
    translation: Position
    rotation: Rotation
    scale: RegistrationScale
    target_units: Literal["m"]
    target_up_axis: Literal["y"]
    source: Identifier

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("Registration version must be integer 1.")
        return value
