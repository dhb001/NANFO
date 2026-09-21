"""Dimensioned volume validation, representation compatibility and rigid transforms."""

import json
import math

import pytest
from pydantic import ValidationError

from app.modules.network.spatial_schemas import SpatialSceneDocument, SpatialSceneInput
from app.modules.network.spatial_transforms import transform_point, world_geometry, world_matrices
from tests.spatial_support import DEVICE_ID, scene_payload, spatial_object


def box(**changes):
    return dict(kind="box", width=10.0, depth=6.0, height=3.0, **changes)


def wall_geometry():
    return dict(kind="wall", length=5.0, height=3.0, thickness=0.2,
                material=dict(name="supplied composite", attenuation_db=7.5, source="operator-spec"))


def dimensioned_objects():
    return [
        spatial_object("building", "building", geometry=box(),
                       position=dict(x=10.0, y=2.0, z=20.0), rotation=dict(x=0.0, y=math.pi / 2, z=0.0)),
        spatial_object("floor", "floor", "building", geometry=dict(kind="slab", width=8.0, depth=6.0, thickness=0.3)),
        spatial_object("room", "room", "floor", geometry=box()),
        spatial_object("wall", "wall", "room", geometry=wall_geometry()),
    ]


@pytest.mark.parametrize("geometry,field", [
    (box(), field) for field in ("width", "depth", "height")
] + [(dict(kind="slab", width=1, depth=2, thickness=0.1), field) for field in ("width", "depth", "thickness")]
  + [(wall_geometry(), field) for field in ("length", "height", "thickness")])
@pytest.mark.parametrize("value", [0, -1, 1e-7, math.ulp(0.0), 1_000_001, math.inf, math.nan, "1", True])
def test_all_dimensions_are_bounded_strict_finite(geometry, field, value):
    geometry = {**geometry, field: value}
    kind = {"box": "room", "slab": "floor", "wall": "wall"}[geometry["kind"]]
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload([
            spatial_object("parent", "floor"), spatial_object("shape", kind, "parent", geometry=geometry),
        ]))


@pytest.mark.parametrize("field,value", [
    ("name", " "), ("name", "a" * 257), ("source", ""), ("source", "x\x00y"),
    ("source", "a" * 129), ("attenuation_db", -1), ("attenuation_db", 101),
    ("attenuation_db", True), ("attenuation_db", "12"), ("attenuation_db", math.inf),
])
def test_material_validation(field, value):
    objects = dimensioned_objects()
    objects[-1]["geometry"]["material"][field] = value
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload(objects))


@pytest.mark.parametrize("parent", [None, "missing", "building", "rack", "device", "wall"])
def test_wall_parent_is_floor_or_room_only(parent):
    objects = [spatial_object("floor", "floor"), spatial_object("wall", "wall", parent)]
    if parent not in (None, "missing", "wall"):
        objects.append(spatial_object(parent, parent))
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload(objects))


def test_wall_is_leaf_and_cannot_associate_device():
    objects = dimensioned_objects()
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload([*objects, spatial_object(parent_id="wall")]))
    objects[-1]["device_id"] = str(DEVICE_ID)
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload(objects))


@pytest.mark.parametrize("object_type", ["campus", "floor", "wall", "device", "interface"])
def test_wrong_shape_type_rejected(object_type):
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload([spatial_object("shape", object_type, geometry=box())]))


@pytest.mark.parametrize("change", ["unknown_kind", "extra", "missing", "extra_material", "missing_material"])
def test_union_is_exact(change):
    objects = dimensioned_objects()
    geometry = objects[-1]["geometry"]
    if change == "unknown_kind":
        geometry["kind"] = "prism"
    elif change == "extra":
        geometry["width"] = 12
    elif change == "missing":
        del geometry["thickness"]
    elif change == "extra_material":
        geometry["material"]["accuracy"] = 1
    else:
        del geometry["material"]["attenuation_db"]
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload(objects))


def test_legacy_omission_and_explicit_null_survive_all_serializers():
    objects = [spatial_object("old"), spatial_object("null", geometry=None)]
    document = dict(**scene_payload(objects), revision=7)
    parsed = SpatialSceneDocument.model_validate(document)
    for _ in range(3):
        assert parsed.model_dump(mode="json") == document
        assert json.loads(parsed.model_dump_json()) == document
        parsed = SpatialSceneDocument.model_validate(parsed.model_dump())
    assert world_geometry(parsed) == {}


def test_rotated_box_slab_wall_volumes_are_not_origin_only():
    scene = SpatialSceneInput.model_validate(scene_payload(list(reversed(dimensioned_objects()))))
    corners = world_geometry(scene)
    # Parent +90deg yaw maps local (x,y,z) to world (10+z,2+y,20-x).
    assert corners["building"][0] == pytest.approx((7, 2, 25))
    assert corners["building"][-1] == pytest.approx((13, 5, 15))
    assert corners["floor"][0] == pytest.approx((7, 2, 24))
    assert corners["floor"][-1] == pytest.approx((13, 2.3, 16))
    assert corners["wall"][0] == pytest.approx((9.9, 2, 20))
    assert corners["wall"][-1] == pytest.approx((10.1, 5, 15))


def test_noncommuting_rotations_preserve_dimensions_and_volume_edges():
    objects = dimensioned_objects()
    objects[0]["rotation"] = dict(x=0.3, y=-1.2, z=0.5)
    objects[2]["rotation"] = dict(x=-0.7, y=0.8, z=1.1)
    scene = SpatialSceneInput.model_validate(scene_payload(objects))
    corners = world_geometry(scene)["wall"]
    assert math.dist(corners[0], corners[4]) == pytest.approx(5)
    assert math.dist(corners[0], corners[2]) == pytest.approx(3)
    assert math.dist(corners[0], corners[1]) == pytest.approx(0.2)
    # The center of all corners transforms as a point in exactly the same frame.
    center = tuple(math.fsum(c[i] for c in corners) / 8 for i in range(3))
    assert center == pytest.approx(transform_point(world_matrices(scene)["wall"], (2.5, 1.5, 0)))


@pytest.mark.parametrize("dimension", [1e-6, 1_000_000])
def test_extreme_dimensions_remain_resolvable_at_full_depth(dimension):
    objects = []
    for kind in ("campus", "building", "floor", "room", "rack"):
        objects.append(spatial_object(kind, kind, objects[-1]["object_id"] if objects else None,
                                      position=dict(x=1_000_000, y=1_000_000, z=1_000_000)))
    objects[-1]["geometry"] = dict(kind="box", width=dimension, depth=dimension, height=dimension)
    assert len(world_geometry(SpatialSceneInput.model_validate(scene_payload(objects)))["rack"]) == 8


def test_geometry_helper_revalidates_mutation():
    scene = SpatialSceneInput.model_validate(scene_payload(dimensioned_objects()))
    scene.objects[0].geometry.width = math.nan
    with pytest.raises(ValidationError):
        world_geometry(scene)


def test_unknown_material_and_accuracy_are_retained_without_fabrication():
    objects = dimensioned_objects()
    objects[-1]["geometry"]["material"]["attenuation_db"] = None
    document = SpatialSceneInput.model_validate(scene_payload(objects)).model_dump(mode="json")
    assert document["objects"][-1]["geometry"]["material"]["attenuation_db"] is None
    assert all(obj["provenance"]["accuracy_m"] is None for obj in document["objects"])


@pytest.mark.parametrize("object_type", ["building", "room", "rack"])
def test_box_allowed_on_each_supported_volume_type(object_type):
    scene = SpatialSceneInput.model_validate(scene_payload([spatial_object("volume", object_type, geometry=box())]))
    assert len(world_geometry(scene)["volume"]) == 8


@pytest.mark.parametrize("value", [math.nan, math.inf, 16_000_001])
def test_transformed_point_rejects_invalid_world_coordinates(value):
    matrix = ((1, 0, 0, value), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1))
    with pytest.raises(ValueError, match="world coordinate"):
        transform_point(matrix, (0, 0, 0))
