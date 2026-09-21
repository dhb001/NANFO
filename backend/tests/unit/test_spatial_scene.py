"""Spatial contract, transform convention and service transaction boundary tests."""

import asyncio
import math
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.network.spatial_schemas import (
    MAX_OBJECTS,
    MAX_REVISION,
    ReplaceSpatialSceneRequest,
    SpatialSceneInput,
)
from app.modules.network.spatial_service import SpatialSceneService, _correlation_uuid
from app.modules.network.spatial_transforms import world_matrices
from tests.spatial_support import ACTOR_ID, DEVICE_ID, NETWORK_ID, WORKSPACE_ID, replace_payload, scene_payload, spatial_object


@pytest.mark.parametrize("field,value", [
    ("x", float("inf")), ("y", float("-inf")), ("z", float("nan")),
    ("x", 1_000_001), ("y", -1_000_001), ("z", "2.5"), ("x", True),
])
def test_position_rejects_nonfinite_out_of_bounds_and_coercion(field, value):
    obj = spatial_object()
    obj["position"][field] = value
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload([obj]))


@pytest.mark.parametrize("value", [math.tau + 0.01, -math.tau - 0.01, math.inf, math.nan, "1", False])
def test_rotation_radian_bounds(value):
    obj = spatial_object()
    obj["rotation"]["x"] = value
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload([obj]))


@pytest.mark.parametrize("value", [-1, math.inf, math.nan, 1_000_001, "1", True])
def test_accuracy_bounds(value):
    obj = spatial_object(provenance={"source": "survey", "accuracy_m": value})
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload([obj]))


@pytest.mark.parametrize("field,value", [
    ("object_id", " "), ("object_id", "a" * 129), ("object_id", "a\x00b"),
    ("name", ""), ("name", "a" * 257), ("name", 123), ("object_type", "unknown"),
    ("device_id", "not-a-uuid"), ("parent_id", ""),
])
def test_object_fields(field, value):
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload([spatial_object(**{field: value})]))


@pytest.mark.parametrize("objects", [
    [spatial_object(), spatial_object()],
    [spatial_object(parent_id="missing")],
    [spatial_object(parent_id="ap")],
    [spatial_object("a", "building", "b"), spatial_object("b", "floor", "a")],
    [spatial_object("a", "rack"), spatial_object("b", "room", "a")],
    [spatial_object("a", "interface")],
    [spatial_object("a", "room"), spatial_object("b", "interface", "a")],
    [spatial_object("a", device_id=str(DEVICE_ID)), spatial_object("b", device_id=str(DEVICE_ID))],
    [spatial_object("a", "rack", device_id=str(DEVICE_ID))],
    [spatial_object(provenance={"source": "schematic-fallback", "accuracy_m": 0})],
])
def test_invalid_hierarchy_and_associations(objects):
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload(objects))


def test_bounded_object_count_and_full_depth_unordered_hierarchy():
    types = ["campus", "building", "floor", "room", "rack", "device", "interface"]
    objects = [spatial_object(kind, kind, types[index - 1] if index else None) for index, kind in enumerate(types)]
    scene = SpatialSceneInput.model_validate(scene_payload(list(reversed(objects))))
    assert len(world_matrices(scene)) == 7
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload([spatial_object(str(i)) for i in range(MAX_OBJECTS + 1)]))


@pytest.mark.parametrize("revision", [True, 1.0, "0", -1, MAX_REVISION + 1])
def test_revision_is_bounded_strict_integer(revision):
    with pytest.raises(ValidationError):
        ReplaceSpatialSceneRequest.model_validate(replace_payload(revision))


@pytest.mark.parametrize("version", [True, 1.0, "1", 2])
def test_version_is_integer_literal(version):
    payload = scene_payload()
    payload["version"] = version
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(payload)


@pytest.mark.parametrize("coordinate_system", [{"units": "ft", "up_axis": "y"}, {"units": "m", "up_axis": "z"}])
def test_coordinate_frame_cannot_silently_change(coordinate_system):
    payload = scene_payload()
    payload["coordinate_system"] = coordinate_system
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(payload)


def test_boundary_values_and_explicit_provenance_roundtrip():
    payload = replace_payload(MAX_REVISION - 1, [spatial_object(
        position={"x": -1_000_000, "y": 1_000_000, "z": 0},
        rotation={"x": -math.tau, "y": math.tau, "z": 0},
        device_id=str(DEVICE_ID), provenance={"source": "survey", "accuracy_m": 1_000_000},
    )])
    assert ReplaceSpatialSceneRequest.model_validate(payload).model_dump(mode="json") == payload


@pytest.mark.parametrize("path", [(), ("scene",), ("scene", "coordinate_system"),
                                 ("scene", "objects", 0), ("scene", "objects", 0, "position"),
                                 ("scene", "objects", 0, "rotation"), ("scene", "objects", 0, "provenance")])
def test_unknown_fields_rejected_at_every_level(path):
    payload = replace_payload(objects=[spatial_object()])
    target = payload
    for part in path:
        target = target[part]
    target["revision"] = 99
    with pytest.raises(ValidationError):
        ReplaceSpatialSceneRequest.model_validate(payload)


@pytest.mark.parametrize("field", ["parent_id", "device_id", "provenance", "rotation", "position"])
def test_nullable_and_transform_fields_still_required(field):
    obj = spatial_object()
    del obj[field]
    with pytest.raises(ValidationError):
        SpatialSceneInput.model_validate(scene_payload([obj]))


def test_transform_parent_rotation_and_translation_are_composed_not_added():
    parent = spatial_object("floor", "floor", position={"x": 10, "y": 3, "z": 20},
                            rotation={"x": 0, "y": math.pi / 2, "z": 0})
    child = spatial_object("ap", parent_id="floor", position={"x": 2, "y": 1, "z": 0})
    matrices = world_matrices(SpatialSceneInput.model_validate(scene_payload([child, parent])))
    assert [matrices["ap"][i][3] for i in range(3)] == pytest.approx([10, 4, 18])
    # Local +X points along world -Z in the declared right-handed Y-up frame.
    assert [matrices["ap"][i][0] for i in range(3)] == pytest.approx([0, 0, -1])


def test_transform_noncommuting_euler_order_and_explicit_origin():
    obj = spatial_object(rotation={"x": math.pi / 2, "y": math.pi / 2, "z": math.pi / 2})
    matrix = world_matrices(SpatialSceneInput.model_validate(scene_payload([obj])))["ap"]
    # +Y -> +Z (Rx), -> +X (Ry), -> +Y (Rz).
    assert [matrix[i][1] for i in range(3)] == pytest.approx([0, 1, 0])
    assert [matrix[i][3] for i in range(3)] == [0, 0, 0]


def test_transform_revalidates_internal_mutation():
    scene = SpatialSceneInput.model_validate(scene_payload([spatial_object()]))
    scene.objects[0].parent_id = "ap"
    with pytest.raises(ValidationError):
        world_matrices(scene)


@pytest.fixture
def service(mock_db, monkeypatch):
    mock_db.expire_all = MagicMock()
    svc = SpatialSceneService(mock_db, None)
    svc._network.assert_network_workspace_access = AsyncMock(return_value=SimpleNamespace(workspace_id=WORKSPACE_ID))
    svc._repo = AsyncMock()
    svc._repo.lock_active_network.return_value = True
    svc._repo.active_device_ids.return_value = {DEVICE_ID}
    svc._repo.replace.return_value = True
    audit = AsyncMock()
    monkeypatch.setattr("app.modules.network.spatial_service.append_audit_log", audit)
    return svc, audit


async def replace(svc, revision=0):
    return await svc.replace_scene(
        network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), correlation_id="human-request-id",
        req=ReplaceSpatialSceneRequest.model_validate(replace_payload(revision, [spatial_object(device_id=str(DEVICE_ID))])),
    )


async def test_service_audits_assigned_revision_and_commits_after_audit(service, mock_db):
    svc, audit = service
    async def append(**kwargs):
        mock_db.commit.assert_not_awaited()
        svc._repo.replace.assert_awaited_once()
        svc._repo.append_revision.assert_awaited_once()
    audit.side_effect = append
    result = await replace(svc)
    assert result.revision == 1
    svc._repo.append_revision.assert_awaited_once_with(
        NETWORK_ID, 1, result.model_dump(mode="json", exclude={"revision"}), ACTOR_ID,
    )
    access = call(
        network_id=NETWORK_ID, actor_user_id=str(ACTOR_ID), require_write=True,
        requested_workspace_id=None, claim_org_id=None,
    )
    assert svc._network.assert_network_workspace_access.await_args_list == [access, access]
    mock_db.expire_all.assert_called_once_with()
    metadata = audit.call_args.kwargs["metadata"]
    assert metadata["previous_revision"] == 0 and metadata["revision"] == 1
    assert metadata["object_count"] == 1 and len(metadata["scene_sha256"]) == 64
    assert audit.call_args.kwargs["db"] is mock_db
    mock_db.commit.assert_awaited_once()


@pytest.mark.parametrize("failure", [RuntimeError("audit failed"), asyncio.CancelledError()])
async def test_audit_failure_and_cancellation_rollback(service, mock_db, failure):
    svc, audit = service
    audit.side_effect = failure
    with pytest.raises(type(failure)):
        await replace(svc)
    mock_db.rollback.assert_awaited_once()
    mock_db.commit.assert_not_awaited()


@pytest.mark.parametrize("case,status", [("conflict", 409), ("device", 422), ("deleted", 404), ("denied", 403)])
async def test_failed_writes_never_audit_or_commit(service, mock_db, case, status):
    svc, audit = service
    if case == "conflict":
        svc._repo.replace.return_value = False
    elif case == "device":
        svc._repo.active_device_ids.return_value = set()
    elif case == "deleted":
        svc._repo.lock_active_network.return_value = False
    else:
        svc._network.assert_network_workspace_access.side_effect = HTTPException(403)
    with pytest.raises(HTTPException) as error:
        await replace(svc)
    assert error.value.status_code == status
    audit.assert_not_awaited()
    mock_db.commit.assert_not_awaited()
    mock_db.rollback.assert_awaited_once()


async def test_revision_exhaustion_is_explicit(service):
    svc, audit = service
    with pytest.raises(HTTPException) as error:
        await replace(svc, MAX_REVISION)
    assert error.value.detail["code"] == "SPATIAL_REVISION_EXHAUSTED"
    svc._repo.replace.assert_not_awaited()
    svc._repo.append_revision.assert_not_awaited()
    audit.assert_not_awaited()


async def test_numerical_geometry_failure_is_handled_before_storage(service, monkeypatch):
    svc, audit = service
    monkeypatch.setattr("app.modules.network.spatial_service.world_geometry",
                        MagicMock(side_effect=ValueError("internal numerical detail")))
    with pytest.raises(HTTPException) as error:
        await replace(svc)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "SPATIAL_GEOMETRY_INVALID"
    assert "internal" not in error.value.detail["message"]
    svc._repo.lock_active_network.assert_not_awaited()
    svc._repo.replace.assert_not_awaited()
    audit.assert_not_awaited()


def test_correlation_mapping_is_stable_and_preserves_uuid():
    assert _correlation_uuid(str(ACTOR_ID)) == ACTOR_ID
    assert _correlation_uuid("human-request-id") == uuid.uuid5(uuid.NAMESPACE_URL, "human-request-id")


async def test_post_lock_authority_check_precedes_mutation_and_rolls_back_placeholder(service, mock_db):
    svc, audit = service

    async def check(**kwargs):
        if svc._repo.lock_scene_for_write.await_count:
            svc._repo.lock_active_network.assert_awaited_once()
            svc._repo.active_device_ids.assert_awaited_once()
            mock_db.expire_all.assert_called_once_with()
            svc._repo.replace.assert_not_awaited()
            raise HTTPException(403, "Insufficient permissions.")
        return SimpleNamespace(workspace_id=WORKSPACE_ID)

    svc._network.assert_network_workspace_access.side_effect = check
    with pytest.raises(HTTPException) as error:
        await replace(svc)
    assert error.value.status_code == 403
    svc._repo.replace.assert_not_awaited()
    audit.assert_not_awaited()
    mock_db.commit.assert_not_awaited()
    mock_db.rollback.assert_awaited_once()
