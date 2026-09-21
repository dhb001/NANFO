"""Canonical spatial-to-RF integration against Network's pure public contract."""

import copy
import json
import math
import sys

import pytest
from pydantic import ValidationError

from app.modules.network.spatial_schemas import SpatialSceneDocument
from app.modules.simulation.rf import RFRequest, evaluate_rf
from app.modules.simulation.snapshot import SnapshotRequest
from app.modules.simulation.spatial_rf import (
    SpatialRFRequest,
    build_spatial_rf,
    spatial_document_hash,
)
from scripts.evaluate_twin_physics import evaluate, main
from tests.unit.test_twin_physics import point, rf, scene, snapshot, wall
from tests.unit.test_spatial_geometry import wall_geometry
from tests.spatial_support import spatial_object

DEVICE_ID = "b02868da-5d90-4b67-b522-d8f751395624"


def evidence():
    return dict(
        kind="configured",
        source_id="operator-survey",
        record_id="survey-1",
        artifact_sha256="a" * 64,
    )


def spatial_input():
    parent = dict(
        object_id="canonical floor / 1",
        parent_id=None,
        object_type="floor",
        name="Floor",
        position=point(10.0, 3.0, 20.0),
        rotation=point(0.0, math.pi / 2, 0.0),
        device_id=None,
        provenance=dict(source="operator-survey", accuracy_m=0.1),
    )
    ap = dict(
        object_id="canonical AP / 1",
        parent_id=parent["object_id"],
        object_type="device",
        name="AP",
        position=point(2.0, 1.0, 0.0),
        rotation=point(0.0, math.pi / 2, 0.0),
        device_id=DEVICE_ID,
        provenance=dict(source="operator-survey", accuracy_m=0.05),
    )
    document = dict(
        version=1,
        revision=4,
        coordinate_system=dict(units="m", up_axis="y"),
        objects=[ap, parent],
    )
    source = evidence()
    source["artifact_sha256"] = spatial_document_hash(
        SpatialSceneDocument.model_validate(document)
    )
    return dict(
        scope=scene()["scope"],
        scene_id="registered-scene",
        coordinate_frame_id="rf-z-up",
        scene=document,
        scene_source=source,
        radio=dict(
            object_id=ap["object_id"],
            device_id=DEVICE_ID,
            transmitter_id="ap-1",
            local_offset_m=point(1.0, 0.0, 0.0),
            parameters=dict(
                frequency_mhz=2400.0,
                tx_power_dbm=20.0,
                tx_gain_dbi=2.0,
                rx_gain_dbi=1.0,
            ),
            source=evidence(),
        ),
        receiver=dict(
            receiver_id="rx-1",
            frame_object_id=parent["object_id"],
            local_position_m=point(12.0, 1.0, -1.0),
            source=evidence(),
        ),
        walls=[
            dict(
                wall_id="wall-1",
                frame_object_id=parent["object_id"],
                start=point(7.0, 0.0, -3.0),
                end=point(7.0, 0.0, 2.0),
                height_m=3.0,
                material="concrete",
                loss_db=12.0,
                source=evidence(),
            )
        ],
        wall_inventory_source=evidence(),
    )


def repin(data):
    data["scene_source"]["artifact_sha256"] = spatial_document_hash(
        SpatialSceneDocument.model_validate(data["scene"])
    )
    return data


def canonical_input():
    data = spatial_input()
    data["scene"]["objects"].append(spatial_object(
        "canonical wall / 1", "wall", "canonical floor / 1", geometry=wall_geometry(),
        position=point(7.0, 0.0, -3.0), rotation=point(0.0, -math.pi / 2, 0.0),
        provenance=dict(source="operator-survey", accuracy_m=0.02),
    ))
    data["walls"] = [dict(wall_id="wall-1", object_id="canonical wall / 1", source=evidence())]
    return repin(data)


def test_frozen_legacy_artifact_hashes_unchanged():
    request, provenance = build_spatial_rf(SpatialRFRequest.model_validate(spatial_input()))
    assert provenance.spatial_document_sha256 == "78ad10bb57bc51ecf96b6738509ce3d13d4439d10f8a3c0fa678be07c2aa4645"
    assert provenance.adapter_input_sha256 == "16ebd5485247d7a415cbe079d10284b54cedbf988aa29356a24c9c39d098dd61"
    assert provenance.rf_config_sha256 == "4a1b00f962d13024c10f344253aea572b1f1009a7f9b2328a170f27ea4779302"
    assert evaluate_rf(request).input_sha256 == "928bbac609e4ce30b1090c4ebcaf1ad9a82ba5e54187644680ab7c3e366155bb"


def test_canonical_wall_uses_composed_geometry_and_explicit_material():
    request, provenance = build_spatial_rf(SpatialRFRequest.model_validate(canonical_input()))
    surface = request.scene.walls[0]
    assert surface.start.model_dump() == pytest.approx(point(7, -13, 3))
    assert surface.end.model_dump() == pytest.approx(point(12, -13, 3))
    assert surface.height_m == 3
    assert surface.material == "custom"
    assert evaluate_rf(request).wall_loss_db == 7.5
    assert provenance.wall_frame_object_ids == {"wall-1": "canonical wall / 1"}
    assert provenance.placement_accuracy_m["canonical wall / 1"] == 0.02


@pytest.mark.parametrize("field,value", [("length", 6), ("height", 4), ("thickness", 0.4),
                                          ("material", dict(name="other", attenuation_db=7.5, source="other-spec"))])
def test_geometry_and_material_changes_invalidate_pinned_scene(field, value):
    data = canonical_input()
    data["scene"]["objects"][-1]["geometry"][field] = value
    with pytest.raises(ValidationError, match="hash mismatch"):
        SpatialRFRequest.model_validate(data)


@pytest.mark.parametrize("case", ["missing_reference", "duplicate", "wrong_object", "missing_geometry", "unknown_loss",
                                   "unknown_accuracy", "override", "legacy_override", "fallback_material"])
def test_canonical_rf_requires_complete_geometry_and_evidence(case):
    data = canonical_input()
    obj = data["scene"]["objects"][-1]
    if case == "missing_reference":
        data["walls"] = []
    elif case == "duplicate":
        data["walls"].append({**data["walls"][0], "wall_id": "second"})
    elif case == "wrong_object":
        data["walls"][0]["object_id"] = "canonical floor / 1"
    elif case == "missing_geometry":
        obj["geometry"] = None
    elif case == "unknown_loss":
        obj["geometry"]["material"]["attenuation_db"] = None
    elif case == "unknown_accuracy":
        obj["provenance"]["accuracy_m"] = None
    elif case == "override":
        data["walls"][0]["start"] = point(0, 0, 0)
    elif case == "legacy_override":
        data["walls"].append({**spatial_input()["walls"][0], "wall_id": "second", "frame_object_id": obj["object_id"]})
    else:
        obj["geometry"]["material"]["source"] = "schematic-fallback"
    with pytest.raises(ValidationError):
        SpatialRFRequest.model_validate(repin(data))


@pytest.mark.parametrize("index,axis", [(1, "x"), (2, "z")])
def test_canonical_wall_rejects_parent_or_local_tilt(index, axis):
    data = canonical_input()
    data["scene"]["objects"][index]["rotation"][axis] = 0.1
    with pytest.raises(ValueError, match="tilted"):
        build_spatial_rf(SpatialRFRequest.model_validate(repin(data)))


def test_canonical_wall_top_and_height_must_fit_rf_limits():
    data = canonical_input()
    data["scene"]["objects"][-1]["geometry"]["height"] = 1001
    with pytest.raises(ValidationError):
        build_spatial_rf(SpatialRFRequest.model_validate(repin(data)))
    data = canonical_input()
    data["scene"]["objects"][-1]["position"]["y"] = 99996
    with pytest.raises(ValidationError):
        build_spatial_rf(SpatialRFRequest.model_validate(repin(data)))


def test_rotated_parent_and_radio_offset_compose_and_convert_axes():
    request = SpatialRFRequest.model_validate(spatial_input())
    result, provenance = build_spatial_rf(request)
    # AP world=(10,4,18); offset rotated by parent AND AP gives (-1,0,0).
    assert result.scene.transmitter.model_dump() == pytest.approx(
        point(9.0, -18.0, 4.0)
    )
    assert result.receiver.model_dump() == pytest.approx(point(9.0, -8.0, 4.0))
    assert result.scene.walls[0].start.model_dump() == pytest.approx(
        point(7.0, -13.0, 3.0)
    )
    assert result.scene.walls[0].end.model_dump() == pytest.approx(
        point(12.0, -13.0, 3.0)
    )
    evaluation = evaluate_rf(result)
    assert evaluation.distance_m == pytest.approx(10)
    assert evaluation.wall_loss_db == 12
    assert evaluation.signal_dbm == pytest.approx(rf().signal_dbm - 12)
    assert provenance.radio_object_id == "canonical AP / 1"
    assert provenance.radio_device_id == DEVICE_ID
    assert provenance.rf_config_sha256 == evaluation.config_sha256
    assert provenance.scene_revision == 4
    assert provenance.placement_accuracy_m == {
        "canonical AP / 1": 0.05,
        "canonical floor / 1": 0.1,
    }
    # Serialization does not change the existing direct RF request contract.
    assert RFRequest.model_validate(result.model_dump()) == result


def test_order_independent_adapter_and_provenance():
    data = spatial_input()
    original = build_spatial_rf(SpatialRFRequest.model_validate(data))
    data["scene"]["objects"].reverse()
    assert build_spatial_rf(SpatialRFRequest.model_validate(data)) == original
    data["radio"]["source"]["record_id"] = "other-record"
    changed = build_spatial_rf(SpatialRFRequest.model_validate(data))
    assert changed[0] == original[0]
    assert changed[1].adapter_input_sha256 != original[1].adapter_input_sha256


@pytest.mark.parametrize(
    "path",
    [
        ("scene",),
        ("scene_source",),
        ("wall_inventory_source",),
        ("walls",),
        ("radio", "source"),
        ("radio", "local_offset_m"),
        ("radio", "device_id"),
        ("radio", "parameters", "tx_power_dbm"),
        ("receiver", "source"),
        ("walls", 0, "source"),
        ("walls", 0, "start"),
    ],
)
def test_missing_evidence_or_geometry_is_rejected(path):
    data = spatial_input()
    target = data
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    with pytest.raises(ValidationError):
        SpatialRFRequest.model_validate(data)


@pytest.mark.parametrize("object_index", [0, 1])
@pytest.mark.parametrize("fallback", [False, True])
def test_unknown_accuracy_or_fallback_including_ancestors_rejects(
    object_index, fallback
):
    data = spatial_input()
    data["scene"]["objects"][object_index]["provenance"] = dict(
        source="schematic-fallback" if fallback else "operator-survey",
        accuracy_m=None,
    )
    with pytest.raises(ValidationError):
        SpatialRFRequest.model_validate(repin(data))


@pytest.mark.parametrize(
    "mutation",
    [
        ("radio", "object_id", "unknown"),
        ("radio", "device_id", "00000000-0000-4000-8000-000000000001"),
        ("receiver", "frame_object_id", "unknown"),
        ("scene_source", "artifact_sha256", "0" * 64),
    ],
)
def test_identity_frame_and_hash_mismatch_reject(mutation):
    data = spatial_input()
    section, key, value = mutation
    data[section][key] = value
    with pytest.raises(ValidationError):
        SpatialRFRequest.model_validate(data)


def test_no_wall_claim_requires_explicit_inventory_evidence():
    data = spatial_input()
    data["walls"] = []
    request, provenance = build_spatial_rf(SpatialRFRequest.model_validate(data))
    assert evaluate_rf(request).wall_loss_db == 0
    assert provenance.wall_inventory_source.source_id == "operator-survey"
    del data["wall_inventory_source"]
    with pytest.raises(ValidationError):
        SpatialRFRequest.model_validate(data)


def test_tilted_wall_and_out_of_rf_bounds_reject_instead_of_flattening():
    data = spatial_input()
    data["scene"]["objects"][1]["rotation"]["x"] = 0.1
    with pytest.raises(ValueError, match="tilted"):
        build_spatial_rf(SpatialRFRequest.model_validate(repin(data)))
    data = spatial_input()
    data["scene"]["objects"][1]["position"]["y"] = 100000.0
    with pytest.raises(ValidationError):
        build_spatial_rf(SpatialRFRequest.model_validate(repin(data)))


def test_subresolution_height_and_subnormal_capacity_budget_reject():
    config = scene()
    config["walls"] = [wall(z=10000.0, height=1e-15)]
    with pytest.raises(ValidationError, match="resolution"):
        rf(config)
    data = snapshot()
    data["links"][0]["config"]["capacity_mbps"] = math.ulp(0.0)
    with pytest.raises(ValidationError, match="normal positive"):
        SnapshotRequest.model_validate(data)
    data["links"][0]["config"]["capacity_mbps"] = sys.float_info.min
    result = evaluate("snapshot", SnapshotRequest.model_validate(data))
    assert math.isfinite(result["evaluation"]["throughput_mbps"])
    assert result["evaluation"]["throughput_mbps"] > 0


def test_spatial_cli_retains_full_provenance_and_replayable_rf_request(
    tmp_path, capsys
):
    path = tmp_path / "spatial.json"
    path.write_text(json.dumps(spatial_input()))
    for name in ["one.json", "two.json"]:
        assert (
            main(
                [
                    "spatial-rf",
                    "--input",
                    str(path),
                    "--output-dir",
                    str(tmp_path),
                    "--output-name",
                    name,
                ]
            )
            == 0
        )
    assert (tmp_path / "one.json").read_bytes() == (tmp_path / "two.json").read_bytes()
    result = json.loads((tmp_path / "one.json").read_text())
    direct = evaluate_rf(RFRequest.model_validate(result["rf_request"]))
    assert result["evaluation"] == direct.model_dump(mode="json")
    assert result["provenance"]["rf_config_sha256"] == direct.config_sha256
    assert result["provenance"]["radio_object_id"] == "canonical AP / 1"
    invalid = copy.deepcopy(spatial_input())
    del invalid["wall_inventory_source"]
    path.write_text(json.dumps(invalid))
    assert (
        main(
            [
                "spatial-rf",
                "--input",
                str(path),
                "--output-dir",
                str(tmp_path),
                "--output-name",
                "invalid.json",
            ]
        )
        == 2
    )
    assert not (tmp_path / "invalid.json").exists()
    capsys.readouterr()
    assert main(["spatial-rf", "--schema"]) == 0
    assert json.loads(capsys.readouterr().out)["additionalProperties"] is False
