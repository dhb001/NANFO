"""Pure right-handed, meter-based local-to-world transforms (no external engine)."""

from __future__ import annotations

import math
from itertools import product

from app.modules.network.spatial_schemas import (
    MAX_WORLD_POSITION_M,
    BoxGeometry,
    Geometry,
    SpatialObject,
    SpatialSceneInput,
    WallGeometry,
)

Matrix4 = tuple[tuple[float, ...], ...]
Point3 = tuple[float, float, float]


def transform_point(matrix: Matrix4, point: Point3) -> Point3:
    """Transform a local meter point without clamping or discarding rotation."""
    vector = (*point, 1.0)
    result = tuple(math.fsum(matrix[row][col] * vector[col] for col in range(4)) for row in range(3))
    if any(not math.isfinite(value) or abs(value) > MAX_WORLD_POSITION_M for value in result):
        raise ValueError("Transformed geometry exceeds finite world coordinate bounds.")
    return result


def geometry_corners(geometry: Geometry) -> tuple[Point3, ...]:
    """Eight local corners, ordered by X then Y then Z (min before max)."""
    if isinstance(geometry, WallGeometry):
        axes = ((0.0, geometry.length), (0.0, geometry.height),
                (-geometry.thickness / 2, geometry.thickness / 2))
    else:
        height = geometry.height if isinstance(geometry, BoxGeometry) else geometry.thickness
        axes = ((-geometry.width / 2, geometry.width / 2), (0.0, height),
                (-geometry.depth / 2, geometry.depth / 2))
    return tuple(product(*axes))


def multiply(left: Matrix4, right: Matrix4) -> Matrix4:
    return tuple(
        tuple(sum(left[row][k] * right[k][column] for k in range(4)) for column in range(4))
        for row in range(4)
    )


def local_matrix(obj: SpatialObject) -> Matrix4:
    """T @ Rz @ Ry @ Rx, angles in radians, position in the parent's frame."""
    cx, cy, cz = (math.cos(value) for value in (obj.rotation.x, obj.rotation.y, obj.rotation.z))
    sx, sy, sz = (math.sin(value) for value in (obj.rotation.x, obj.rotation.y, obj.rotation.z))
    return (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx, obj.position.x),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx, obj.position.y),
        (-sy, cy * sx, cy * cx, obj.position.z),
        (0.0, 0.0, 0.0, 1.0),
    )


def world_matrices(scene: SpatialSceneInput) -> dict[str, Matrix4]:
    """Validate at the public boundary, then resolve unordered parents iteratively."""
    # Also reject mutated/model_construct inputs from internal callers.
    validated = SpatialSceneInput.model_validate({
        "version": scene.version,
        "coordinate_system": scene.coordinate_system.model_dump(),
        "objects": [obj.model_dump() for obj in scene.objects],
    })
    objects = {obj.object_id: obj for obj in validated.objects}
    result: dict[str, Matrix4] = {}
    for object_id in objects:
        chain = []
        current = object_id
        while current is not None and current not in result:
            obj = objects[current]
            chain.append(obj)
            current = obj.parent_id
        for obj in reversed(chain):
            local = local_matrix(obj)
            result[obj.object_id] = local if obj.parent_id is None else multiply(result[obj.parent_id], local)
    return result


def world_geometry(scene: SpatialSceneInput) -> dict[str, tuple[Point3, ...]]:
    """Public explicit volume contract; geometry-free objects have no derived shape."""
    validated = SpatialSceneInput.model_validate(scene.model_dump(exclude={"revision"}))
    matrices = world_matrices(validated)
    result = {}
    for obj in validated.objects:
        if obj.geometry is None:
            continue
        corners = tuple(transform_point(matrices[obj.object_id], point) for point in geometry_corners(obj.geometry))
        # Each binary corner-index bit selects one local dimension. All twelve
        # edges must survive floating-point composition at their world placement.
        if any(math.dist(corners[index], corners[index ^ bit]) == 0
               for index in range(8) for bit in (1, 2, 4) if not index & bit):
            raise ValueError("Geometry edge is below world coordinate numerical resolution.")
        result[obj.object_id] = corners
    return result
