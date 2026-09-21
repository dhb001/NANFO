// Captured from the real offline CLI evaluate("spatial-rf", SpatialRFRequest(...))
// using backend/tests/unit/test_spatial_rf.py::spatial_input; no live RF measurement.
import type { SpatialSceneSnapshot } from "../../shared/types/spatial";
const source = { kind: "configured", source_id: "operator-survey", record_id: "survey-1", artifact_sha256: "a".repeat(64) };
const scope = { workspace_id: "workspace-1", network_id: "network-1" };
export const rfFixtureScene: SpatialSceneSnapshot = {
  version: 1, revision: 4, coordinate_system: { units: "m", up_axis: "y" }, objects: [
    { object_id: "canonical AP / 1", parent_id: "canonical floor / 1", object_type: "device", name: "AP", position: { x: 2, y: 1, z: 0 }, rotation: { x: 0, y: Math.PI / 2, z: 0 }, device_id: "b02868da-5d90-4b67-b522-d8f751395624", provenance: { source: "operator-survey", accuracy_m: 0.05 } },
    { object_id: "canonical floor / 1", parent_id: null, object_type: "floor", name: "Floor", position: { x: 10, y: 3, z: 20 }, rotation: { x: 0, y: Math.PI / 2, z: 0 }, device_id: null, provenance: { source: "operator-survey", accuracy_m: 0.1 } },
  ],
};
const sceneHash = "78ad10bb57bc51ecf96b6738509ce3d13d4439d10f8a3c0fa678be07c2aa4645";
const configHash = "4a1b00f962d13024c10f344253aea572b1f1009a7f9b2328a170f27ea4779302";
export const rfFixture = {
  rf_request: { scene: { frequency_mhz: 2400, tx_power_dbm: 20, tx_gain_dbi: 2, rx_gain_dbi: 1, path_loss_exponent: 2, reference_distance_m: 1, uncertainty_db: null,
    model_version: "log-distance-segment-walls.v1", scope, scene_id: "registered-scene", coordinate_frame_id: "rf-z-up", geometry_source_id: "operator-survey", transmitter_id: "ap-1",
    transmitter: { x: 9, y: -18, z: 4 }, walls: [{ wall_id: "wall-1", start: { x: 7, y: -13, z: 3 }, end: { x: 12, y: -13, z: 3 }, height_m: 3, material: "concrete", loss_db: 12 }] },
    receiver_id: "rx-1", receiver: { x: 9, y: -8, z: 4 } },
  provenance: { version: "canonical-spatial-rf.v1", scope, scene_revision: 4, spatial_document_sha256: sceneHash, adapter_input_sha256: "16ebd5485247d7a415cbe079d10284b54cedbf988aa29356a24c9c39d098dd61",
    rf_config_sha256: configHash, axis_conversion: "network(X,Y,Z)->rf(X,-Z,Y)", radio_object_id: "canonical AP / 1", radio_device_id: "b02868da-5d90-4b67-b522-d8f751395624", receiver_frame_object_id: "canonical floor / 1",
    wall_frame_object_ids: { "wall-1": "canonical floor / 1" }, scene_source: { ...source, artifact_sha256: sceneHash }, radio_source: source, receiver_source: source, wall_inventory_source: source,
    wall_sources: { "wall-1": source }, placement_accuracy_m: { "canonical AP / 1": 0.05, "canonical floor / 1": 0.1 }, physical_safety_authorized: false },
  evaluation: { model_version: "log-distance-segment-walls.v1", source: "operator_configured_model", physical_safety_authorized: false, scope, config_sha256: configHash,
    input_sha256: "928bbac609e4ce30b1090c4ebcaf1ad9a82ba5e54187644680ab7c3e366155bb", receiver_id: "rx-1", distance_m: 10, effective_distance_m: 10, distance_clamped: false,
    reference_loss_db: 40.0520080561155, distance_loss_db: 20, wall_loss_db: 12, signal_dbm: -49.0520080561155,
    crossings: [{ wall_id: "wall-1", material: "concrete", loss_db: 12, loss_source: "configured" }], uncertainty_db: null, interference_dbm: null, sinr_db: null, congestion: null },
};
