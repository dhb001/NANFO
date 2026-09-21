"""Analytical physics, declared holdout and canonical snapshot checks (no services)."""

import copy
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.simulation.calibration import CalibrationRequest, evaluate_calibration
from app.modules.simulation.rf import RFRequest, RFScene, evaluate_rf, rf_config_hash
from app.modules.simulation.schemas import ScenarioConfig
from app.modules.simulation.snapshot import SnapshotRequest, build_snapshot
from scripts.evaluate_twin_physics import (
    MAX_INPUT_BYTES,
    evaluate,
    main,
    read_request,
    write_result,
)


def point(x=0.0, y=0.0, z=1.0):
    return dict(x=x, y=y, z=z)


def scene():
    return dict(
        scope=dict(workspace_id="workspace-1", network_id="network-1"),
        scene_id="scene-1",
        coordinate_frame_id="building-local-meters",
        geometry_source_id="survey-1",
        transmitter_id="ap-1",
        transmitter=point(),
        frequency_mhz=2400.0,
        tx_power_dbm=20.0,
        tx_gain_dbi=2.0,
        rx_gain_dbi=1.0,
        walls=[],
    )


def wall(wall_id="wall-1", x=5.0, y1=-2.0, y2=2.0, z=0.0, height=3.0):
    return dict(
        wall_id=wall_id,
        start=point(x, y1, z),
        end=point(x, y2, z),
        height_m=height,
        material="concrete",
    )


def rf(raw_scene=None, receiver=None):
    return evaluate_rf(
        RFRequest.model_validate(
            dict(
                scene=raw_scene or scene(),
                receiver_id="rx-1",
                receiver=receiver or point(10.0),
            )
        )
    )


def test_free_space_frequency_distance_and_gains():
    base = rf(receiver=point(1.0))
    expected_loss = 20 * math.log10(4 * math.pi * 2.4e9 / 299792458)
    assert base.reference_loss_db == pytest.approx(expected_loss)
    assert base.signal_dbm == pytest.approx(23 - expected_loss)
    assert rf().signal_dbm == pytest.approx(base.signal_dbm - 20)
    config = scene()
    config.update(frequency_mhz=4800.0)
    assert rf(config).signal_dbm == pytest.approx(rf().signal_dbm - 20 * math.log10(2))
    config.update(frequency_mhz=2400.0, path_loss_exponent=3.0, tx_gain_dbi=5.0)
    assert rf(config).signal_dbm == pytest.approx(rf().signal_dbm - 10 + 3)
    assert base.interference_dbm is base.sinr_db is base.congestion is None
    assert base.uncertainty_db is None


def test_reference_clamp_and_three_dimensional_distance():
    near = rf(receiver=point())
    assert near.distance_m == 0
    assert near.distance_clamped
    assert near.signal_dbm == rf(receiver=point(1.0)).signal_dbm
    result = rf(receiver=point(3.0, 4.0, 13.0))
    assert result.distance_m == 13
    config = scene()
    config["reference_distance_m"] = 10.0
    assert rf(config).signal_dbm == pytest.approx(rf().signal_dbm)


@pytest.mark.parametrize(
    "surface,receiver,expected",
    [
        (wall(), point(10.0), 12.0),
        (wall(y1=2.0, y2=4.0), point(10.0), 0.0),  # Infinite plane would be wrong.
        (wall(x=15.0), point(10.0), 0.0),
        (wall(height=0.5), point(10.0), 0.0),
        (wall(z=2.0), point(10.0), 0.0),
        (wall(x=0.0), point(10.0), 0.0),  # Transmitter on surface.
        (wall(x=10.0), point(10.0), 0.0),
        (wall(y1=0.0), point(10.0), 12.0),  # Wall edge convention.
        (wall(), point(10.0, 0.0, 9.0), 0.0),  # Ray passes above finite height.
    ],
)
def test_finite_wall_intersections(surface, receiver, expected):
    config = scene()
    config["walls"] = [surface]
    assert rf(config, receiver).wall_loss_db == expected


def test_oblique_collinear_and_material_crossings():
    config = scene()
    oblique = wall()
    oblique.update(start=point(3.0, -2.0, 0.0), end=point(7.0, 2.0, 0.0))
    collinear = wall("wall-2")
    collinear.update(start=point(2.0, 0.0, 0.0), end=point(8.0, 0.0, 0.0))
    custom = wall("wall-3", x=8.0)
    custom.update(material="custom", loss_db=7.5)
    config["walls"] = [oblique, collinear, custom]
    result = rf(config)
    assert result.wall_loss_db == 19.5
    assert [item.wall_id for item in result.crossings] == ["wall-1", "wall-3"]
    assert [item.loss_source for item in result.crossings] == [
        "nominal_default",
        "configured",
    ]
    config["walls"].reverse()
    assert rf(config) == result
    # Swapping endpoints of a surface leaves its intersection unchanged.
    oblique["start"], oblique["end"] = oblique["end"], oblique["start"]
    assert rf(config).signal_dbm == result.signal_dbm


@pytest.mark.parametrize(
    "field,value",
    [
        ("frequency_mhz", 0.0),
        ("frequency_mhz", "2400"),
        ("tx_power_dbm", float("nan")),
        ("rx_gain_dbi", float("inf")),
        ("path_loss_exponent", 7.0),
        ("walls", [wall()] * 257),
        ("walls", [wall(), wall()]),
        ("congestion", 0.5),
    ],
)
def test_rf_strict_bounds(field, value):
    config = scene()
    config[field] = value
    with pytest.raises(ValidationError):
        rf(config)


def calibration(kind="synthetic"):
    config = RFScene.model_validate(scene())
    samples = []
    for index, offset in enumerate([4.0, 6.0, 8.0, 10.0]):
        receiver = point(float(index + 1))
        samples.append(
            dict(
                sample_id=f"sample-{index}",
                capture_id=f"capture-{index}",
                source_record_id=f"record-{index}",
                source_id="survey-1",
                source_kind=kind,
                scope=config.scope.model_dump(),
                config_sha256=rf_config_hash(config),
                receiver_id=f"rx-{index}",
                receiver=receiver,
                observed_at="2026-09-19T12:00:00+00:00",
                signal_dbm=rf(receiver=receiver).signal_dbm + offset,
            )
        )
    return dict(
        scene=config.model_dump(),
        measurement_source_id="survey-1",
        measurement_source_kind=kind,
        measurements=samples,
        train_ids=["sample-0", "sample-1"],
        holdout_ids=["sample-2", "sample-3"],
    )


def test_train_only_analytical_metrics_and_holdout_changes_do_not_leak():
    data = calibration()
    result = evaluate_calibration(CalibrationRequest.model_validate(data))
    assert result.offset_db == pytest.approx(5)
    assert result.train.fitted.mae_db == pytest.approx(1)
    assert result.holdout.fitted.mae_db == pytest.approx(4)
    assert result.holdout.fitted.rmse_db == pytest.approx(math.sqrt(17))
    assert result.holdout.fitted.bias_db == pytest.approx(-4)
    assert result.holdout.fitted.max_absolute_error_db == pytest.approx(5)
    assert result.holdout.baseline.mae_db == pytest.approx(9)
    assert result.status == "synthetic_only" and not result.calibrated
    data["measurements"][2]["signal_dbm"] += 20
    changed = evaluate_calibration(CalibrationRequest.model_validate(data))
    assert changed.offset_db == result.offset_db
    assert changed.train == result.train
    assert changed.holdout != result.holdout


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", dict(workspace_id="other", network_id="network-1")),
        ("config_sha256", "0" * 64),
        ("source_id", "other"),
        ("source_kind", "measured"),
        ("source_record_id", "record-0"),
        ("capture_id", "capture-0"),
        ("observed_at", "2026-09-19T12:00:00"),
    ],
)
def test_mismatched_or_leaking_measurements_rejected(field, value):
    data = calibration()
    data["measurements"][2][field] = value
    with pytest.raises(ValidationError):
        CalibrationRequest.model_validate(data)


@pytest.mark.parametrize(
    "train,holdout",
    [
        (["sample-0", "sample-1"], ["sample-1", "sample-2", "sample-3"]),
        (["sample-0", "sample-0", "sample-1"], ["sample-2", "sample-3"]),
        (["sample-0"], ["sample-2", "sample-3"]),
        (["missing", "sample-0", "sample-1"], ["sample-2", "sample-3"]),
    ],
)
def test_split_requires_exact_disjoint_assignment(train, holdout):
    data = calibration()
    data.update(train_ids=train, holdout_ids=holdout)
    with pytest.raises(ValidationError):
        CalibrationRequest.model_validate(data)


def test_no_data_no_holdout_and_measured_results_do_not_claim_calibration():
    data = calibration("measured")
    result = evaluate_calibration(CalibrationRequest.model_validate(data))
    assert result.status == "measured_holdout_evaluated"
    assert not result.calibrated
    data.update(train_ids=data["train_ids"] + data["holdout_ids"], holdout_ids=[])
    result = evaluate_calibration(CalibrationRequest.model_validate(data))
    assert result.status == "unavailable" and result.offset_db is None
    data.update(train_ids=[], measurements=[])
    assert (
        evaluate_calibration(CalibrationRequest.model_validate(data)).status
        == "unavailable"
    )


def test_fit_bound_and_order_reproducibility():
    data = calibration()
    for sample in data["measurements"][:2]:
        sample["signal_dbm"] += 70
    result = evaluate_calibration(CalibrationRequest.model_validate(data))
    assert result.offset_db == 40 and result.offset_bound_hit
    data["measurements"].reverse()
    data["train_ids"].reverse()
    data["holdout_ids"].reverse()
    assert evaluate_calibration(CalibrationRequest.model_validate(data)) == result


def snapshot():
    source = dict(
        kind="configured",
        source_id="operator-1",
        record_id="config-1",
        artifact_sha256="a" * 64,
    )
    return dict(
        scope=scene()["scope"],
        snapshot_id="snapshot-1",
        network_config_sha256="b" * 64,
        node_ids=["node-a", "node-b"],
        seed=42,
        tick_ms=100,
        duration_ticks=10,
        links=[
            dict(
                config=dict(
                    link_id="link-ab",
                    source="node-a",
                    target="node-b",
                    capacity_mbps=10.0,
                    buffer_bytes=1e6,
                    delay_ms=0.0,
                    initial_queue_bytes=0.0,
                ),
                sources={
                    field: copy.deepcopy(source)
                    for field in (
                        "capacity_mbps",
                        "buffer_bytes",
                        "delay_ms",
                        "initial_queue_bytes",
                    )
                },
            )
        ],
        flows=[
            dict(
                config=dict(
                    flow_id="flow-1",
                    source="node-a",
                    target="node-b",
                    path=["link-ab"],
                    demand_mbps=[1.0],
                ),
                demand_source=copy.deepcopy(source),
                route_source=copy.deepcopy(source),
            )
        ],
        limits=dict(max_loss_pct=0.0, max_latency_ms=200.0, min_throughput_mbps=1.0),
    )


def test_snapshot_reuses_contract_and_preserves_explicit_values_and_provenance():
    data = snapshot()
    data["links"][0]["sources"]["capacity_mbps"]["kind"] = "measured"
    config, provenance = build_snapshot(SnapshotRequest.model_validate(data))
    assert isinstance(config, ScenarioConfig)
    assert config.links[0].model_dump() == data["links"][0]["config"]
    assert config.flows[0].model_dump() == data["flows"][0]["config"]
    assert config.action_binding is None
    assert provenance.link_sources["link-ab"].capacity_mbps.kind == "measured"
    result = evaluate("snapshot", SnapshotRequest.model_validate(data))
    assert result["evaluation"]["throughput_mbps"] == pytest.approx(1.0)
    assert result["evaluation"]["offered_bytes"] == 125000
    assert result["evaluation"]["loss_pct"] == 0
    data["node_ids"].reverse()
    assert build_snapshot(SnapshotRequest.model_validate(data)) == (config, provenance)
    data["flows"][0]["config"]["demand_mbps"] = [2.0]
    assert (
        build_snapshot(SnapshotRequest.model_validate(data))[1].workload_sha256
        != provenance.workload_sha256
    )


@pytest.mark.parametrize(
    "field", ["capacity_mbps", "buffer_bytes", "delay_ms", "initial_queue_bytes"]
)
def test_snapshot_never_invents_link_values_or_sources(field):
    data = snapshot()
    del data["links"][0]["config"][field]
    with pytest.raises(ValidationError):
        SnapshotRequest.model_validate(data)
    data = snapshot()
    del data["links"][0]["sources"][field]
    with pytest.raises(ValidationError):
        SnapshotRequest.model_validate(data)


def test_snapshot_missing_demand_invalid_identity_route_and_work_bound():
    data = snapshot()
    del data["flows"][0]["config"]["demand_mbps"]
    with pytest.raises(ValidationError):
        SnapshotRequest.model_validate(data)
    for mutation in [
        {"node_ids": ["node-a", "node-c"]},
        {"node_ids": ["node-a", "node-a"]},
        {"seed": True},
        {"tick_ms": "100"},
    ]:
        with pytest.raises(ValidationError):
            SnapshotRequest.model_validate({**snapshot(), **mutation})
    data = snapshot()
    data["flows"][0]["config"]["path"] = ["unknown"]
    with pytest.raises(ValidationError):
        SnapshotRequest.model_validate(data)
    data = snapshot()
    data["duration_ticks"] = 1000
    data["flows"] = [copy.deepcopy(data["flows"][0]) for _ in range(10)]
    for i, flow in enumerate(data["flows"]):
        flow["config"]["flow_id"] = f"flow-{i}"
    with pytest.raises(ValidationError):
        SnapshotRequest.model_validate(data)


@pytest.mark.parametrize(
    "mode,data",
    [
        ("rf", dict(scene=scene(), receiver_id="rx-1", receiver=point(10.0))),
        ("calibration", calibration()),
        ("snapshot", snapshot()),
    ],
)
def test_cli_fresh_process_reproducibility(tmp_path, mode, data):
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(data))
    backend = Path(__file__).resolve().parents[2]
    for index in range(2):
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.evaluate_twin_physics",
                mode,
                "--input",
                str(input_path),
                "--output-dir",
                str(tmp_path),
                "--output-name",
                f"result-{index}.json",
            ],
            cwd=backend,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PYTHONHASHSEED": str(index)},
        )
        assert process.returncode == 0, process.stderr
    assert (tmp_path / "result-0.json").read_bytes() == (
        tmp_path / "result-1.json"
    ).read_bytes()
    assert (tmp_path / "result-0.json").stat().st_mode & 0o777 == 0o600


def test_cli_rejects_duplicate_nonfinite_oversized_json_and_bad_types(tmp_path):
    path = tmp_path / "input.json"
    for text in [
        '{"scene":{},"scene":{}}',
        '{"x":NaN}',
        '{"x":Infinity}',
        "[" * 2000,
        " " * (MAX_INPUT_BYTES + 1),
        '{"scene":1}',
    ]:
        path.write_text(text)
        assert main(["rf", "--input", str(path), "--output-dir", str(tmp_path)]) == 2
        assert not (tmp_path / "result.json").exists()


def test_cli_safe_paths_no_overwrite_or_symlink_following(tmp_path):
    write_result(tmp_path, "result.json", {"value": 1})
    with pytest.raises(FileExistsError):
        write_result(tmp_path, "result.json", {})
    assert json.loads((tmp_path / "result.json").read_text()) == {"value": 1}
    for name in ["../escape.json", "/absolute.json", "bad.txt", ".hidden.json"]:
        with pytest.raises(ValueError):
            write_result(tmp_path, name, {})
    (tmp_path / "link.json").symlink_to(tmp_path / "result.json")
    with pytest.raises(OSError):
        write_result(tmp_path, "link.json", {})
    with pytest.raises(OSError):
        read_request(tmp_path / "link.json", "rf")
    (tmp_path / "linked-dir").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        write_result(tmp_path / "linked-dir", "new.json", {})
    with pytest.raises(ValueError):
        write_result(tmp_path / "..", "new.json", {})


def test_cli_schema_is_available_for_each_mode(capsys):
    for mode in ["rf", "calibration", "snapshot"]:
        assert main([mode, "--schema"]) == 0
        assert json.loads(capsys.readouterr().out)["additionalProperties"] is False


def test_geometry_rotation_translation_and_ray_reversal():
    config = scene()
    config["walls"] = [wall()]
    original = rf(config)

    # Rigid transform (x,y,z) -> (-y+30,x-20,z+10) preserves distance/crossing.
    def transform(value):
        return point(-value["y"] + 30, value["x"] - 20, value["z"] + 10)

    config["transmitter"] = transform(config["transmitter"])
    for surface in config["walls"]:
        surface["start"] = transform(surface["start"])
        surface["end"] = transform(surface["end"])
    receiver = transform(point(10.0))
    assert rf(config, receiver).signal_dbm == original.signal_dbm
    transmitter = config["transmitter"]
    config["transmitter"] = receiver
    assert rf(config, transmitter).signal_dbm == original.signal_dbm


def test_invalid_wall_geometry_and_mutated_boundary_rejected():
    for changes in [
        {"material": "custom"},
        {"end": point(5.0, -2.0, 0.0)},
        {"end": point(5.0, 2.0, 1.0)},
        {"height_m": 0.0},
    ]:
        config = scene()
        config["walls"] = [{**wall(), **changes}]
        with pytest.raises(ValidationError):
            rf(config)
    request = RFRequest.model_validate(
        dict(scene=scene(), receiver_id="rx-1", receiver=point(10.0))
    )
    request.scene.frequency_mhz = float("nan")
    with pytest.raises(ValidationError):
        evaluate_rf(request)


def test_same_observation_cannot_be_relabeled_across_holdout():
    data = calibration()
    data["measurements"][2]["receiver_id"] = "rx-0"
    # Same instant expressed in another timezone must still be caught.
    data["measurements"][2]["observed_at"] = "2026-09-19T15:00:00+03:00"
    with pytest.raises(ValidationError):
        CalibrationRequest.model_validate(data)


def test_cli_nonregular_input_rejected_without_blocking(tmp_path):
    fifo = tmp_path / "input.json"
    os.mkfifo(fifo)
    with pytest.raises(ValueError):
        read_request(fifo, "rf")
