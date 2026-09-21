"""Independent analytical oracles and adversarial evidence/installation checks."""

import copy
import hashlib
import json
import math

import pytest
from pydantic import ValidationError

from app.modules.autonomy.artifact_io import ArtifactRef, ArtifactStore, EvidenceError
from app.modules.autonomy.calibration_verification import load_trusted_calibration, verify_network_campaign
from app.modules.autonomy.calibration_verification_models import CalibrationScope
from app.modules.simulation.qualification_protocol import AcquisitionProtocol, import_campaign
from app.modules.simulation.qualification_rf import qualify_rf, reference_prediction
from app.modules.simulation.rf import PointMeters, RFScene
from app.modules.simulation.qualification_acquisition import (
    LocalAcquisitionRecipe, LocalWindow, measure_window, prepare_local, verify_native_events,
)
from scripts.qualify_independent_validation import main


def put(root, name, value):
    data = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    (root / name).write_bytes(data)
    return dict(path=name, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))


def network_config():
    return dict(
        schema_version="nanfo.network-qualification-config.v1", provider_id="provider",
        egress_ids=["q"], demand_ids=["d"], actions=[dict(
            action_id="route", demand_egress_ids={"d": ["q"]}, bounds=[dict(
                egress_id="q", capacity_bytes_per_second=100.0,
                arrival_upper_bytes_per_second=10.0, service_lower_bytes_per_second=20.0,
                service_upper_bytes_per_second=30.0, error_upper_bytes=0.0,
            )],
        )], queue_units="bytes", rate_units="bytes/second", time_units="unix-seconds",
        dt_seconds=1.0, max_delay_seconds=0.25, queue_threshold_bytes=1000.0,
        drift_budget_bytes_squared=0.0, min_samples_per_action_per_split=2,
        required_transitions=[["route", "route"]],
    )


def network_reading(start):
    return dict(action_id="route", previous_action_id="route", start_unix_seconds=start,
                end_unix_seconds=start + 1.0, dispatch_unix_seconds=start,
                applied_unix_seconds=start + 0.125, transition_complete_unix_seconds=start + 0.125,
                queue_units="bytes", rate_units="bytes/second", time_units="unix-seconds",
                measurement_complete=True, attribution_complete=True, counter_reset=False,
                unknown_demand_ids=[], queues=[dict(
                    egress_id="q", queue_before_bytes=100.0, queue_after_bytes=90.0,
                    arrivals=dict(before=0, after=10), departures=dict(before=0, after=20),
                    drops=dict(before=0, after=0), demand_arrivals={"d": dict(before=0, after=10)},
                    unknown_arrival_bytes=0, measurement_error_bytes=0.0,
                )])


def rf_config():
    return dict(schema_version="nanfo.rf-qualification-config.v1", scene=dict(
        scope=dict(workspace_id="w", network_id="n"), scene_id="scene", coordinate_frame_id="frame",
        geometry_source_id="survey", transmitter_id="ap", transmitter=dict(x=0., y=0., z=1.),
        frequency_mhz=2400., tx_power_dbm=20., tx_gain_dbi=0., rx_gain_dbi=0., walls=[],
    ), coordinate_units="meters", coordinate_axes="local-z-up", signal_units="dBm",
        coordinate_registration_evidence_sha256="0" * 64, max_holdout_mae_db=1.,
        max_holdout_absolute_error_db=1., min_train_samples=2, min_holdout_samples=2)


def dossier(root, *, domain="network", environment="isolated-emulation", mutate=None):
    config = network_config() if domain == "network" else rf_config()
    registration = put(root, "registration.json", {"frame": "surveyed-z-up", "control_points": "TEST-ONLY"})
    if domain == "rf":
        config["coordinate_registration_evidence_sha256"] = registration["sha256"]
    cfg = put(root, "config.json", config)
    protocol = dict(schema_version="nanfo.independent-protocol.v1", campaign_id="campaign", dataset_id="dataset",
                    domain=domain, environment=environment, network_id="n", run_id="run",
                    declared_at_unix_seconds=1., configuration=cfg,
                    group_basis="Separate preregistered test-only capture sessions.",
                    groups=[dict(group_id="train", split="train", sample_ids=["s0", "s1"]),
                            dict(group_id="holdout", split="holdout", sample_ids=["s2", "s3"])],
                    instrument_ids=["instrument"])
    pref = put(root, "protocol.json", protocol)
    captures = []
    for group, indexes in (("train", [0, 1]), ("holdout", [2, 3])):
        records = []
        for index in indexes:
            start = 10. + index * 2
            if domain == "network":
                reading = network_reading(start)
            else:
                distance = float(index + 1)
                # Analytical free-space oracle, independent of both production and reference code.
                signal = 20 - 20 * math.log10(4 * math.pi * distance * 2.4e9 / 299792458) + 3
                reading = dict(receiver_id=f"rx{index}", transmitter_id="ap", coordinate_frame_id="frame",
                               receiver=dict(x=distance, y=0., z=1.), signal_dbm=signal,
                               signal_units="dBm", coordinate_units="meters", coordinate_axes="local-z-up")
            if mutate:
                mutate(index, reading)
            records.append(dict(sample_id=f"s{index}", source_record_id=f"raw{index}",
                                instrument_id="instrument", observed_at_unix_seconds=start, measurement=reading))
        native = put(root, f"{group}.native.json", dict(schema_version="nanfo.instrument-records.v1",
                     instrument_id="instrument", records=[{k: v for k, v in r.items() if k not in ("sample_id", "instrument_id")} for r in records]))
        captures.append(put(root, f"{group}.json", dict(schema_version="nanfo.raw-capture.v1",
                        protocol_sha256=pref["sha256"], dataset_id="dataset", group_id=group,
                        environment=environment, native_sources=[native] + ([registration] if domain == "rf" and group == "train" else []), records=records)))
    identity = put(root, "identity.json", {"operator": "test-only"})
    att = put(root, "attestation.json", dict(schema_version="nanfo.measurement-attestation.v1",
              protocol_sha256=pref["sha256"], dataset_id="dataset", operator_id="tester", method="operator-attested",
              identity_evidence=identity, instrument_ids=["instrument"], capture_sha256=[c["sha256"] for c in captures],
              attested_at_unix_seconds=30., statement="I attest these original measurements, identities, units, coordinates and complete capture groups; no fabricated or omitted observations."))
    manifest = put(root, "manifest.json", dict(schema_version="nanfo.independent-campaign.v1", protocol=pref,
                   captures=captures, attestation=att))
    trust = dict(trusted_preregistrations={pref["sha256"]: 2.}, trusted_attesters={att["sha256"]})
    return ArtifactStore(str(root)), ArtifactRef(**manifest), trust, cfg


def imported(root, **kwargs):
    store, manifest, trust, _ = dossier(root, **kwargs)
    return import_campaign(store, manifest, **trust)


def test_analytical_queue_drift_and_empirical_not_guarantee(tmp_path):
    report = verify_network_campaign(imported(tmp_path))
    assert report["empirical_acceptance_passed"]
    assert report["holdout_coverage"] == 1
    assert not report["physical_qualified"] and not report["guaranteed_physical_bound"]
    assert report["rows"][0]["queues"][0]["q_next_upper_bytes"] == 90
    assert report["rows"][0]["drift_upper_bytes_squared"] == -950


@pytest.mark.parametrize("field,value,reason", [
    ("unknown_demand_ids", ["unseen"], "incomplete_measurement_or_unknown_demand"),
    ("measurement_complete", False, "incomplete_measurement_or_unknown_demand"),
    ("attribution_complete", False, "incomplete_measurement_or_unknown_demand"),
    ("counter_reset", True, "incomplete_measurement_or_unknown_demand"),
    ("transition_complete_unix_seconds", 14.5, "delay_bound_exceeded"),
])
def test_refuses_incomplete_unknown_delayed_holdout(tmp_path, field, value, reason):
    campaign = imported(tmp_path, mutate=lambda i, r: r.update({field: value}) if i == 2 else None)
    result = verify_network_campaign(campaign)
    assert not result["empirical_acceptance_passed"]
    assert reason in result["rows"][2]["failures"]


def test_late_arrivals_unused_service_not_safe(tmp_path):
    def late(index, reading):
        if index == 2:
            q = reading["queues"][0]
            q.update(queue_before_bytes=0., queue_after_bytes=10.)
            q["departures"]["after"] = 0
    result = verify_network_campaign(imported(tmp_path, mutate=late))
    row = result["rows"][2]
    assert row["queues"][0]["q_next_upper_bytes"] == 0
    assert {"queue_inequality_failed", "service_inequality_failed", "actual_drift_exceeds_bound"} <= set(row["failures"])


@pytest.mark.parametrize("mutation", [
    lambda r: r["queues"][0]["arrivals"].update(after=11),
    lambda r: r["queues"][0].update(queue_after_bytes=91.),
    lambda r: r["queues"][0].update(unknown_arrival_bytes=1),
    lambda r: r["queues"][0].update(measurement_error_bytes=1.),
])
def test_independent_inequalities_detect_violations(tmp_path, mutation):
    result = verify_network_campaign(imported(tmp_path, mutate=lambda i, r: mutation(r) if i == 2 else None))
    assert not result["empirical_acceptance_passed"]


def test_rf_train_bias_and_holdout_no_retuning(tmp_path):
    result = qualify_rf(imported(tmp_path, domain="rf"))
    assert result["offset_db"] == pytest.approx(3)
    assert result["holdout_mae_db"] == pytest.approx(0, abs=1e-12)
    assert result["empirical_acceptance_passed"]
    assert not result["physical_qualified"]
    other = tmp_path / "shifted"
    other.mkdir()
    shifted = qualify_rf(imported(other, domain="rf", mutate=lambda i, r: r.update(signal_dbm=r["signal_dbm"] + 10) if i >= 2 else None))
    assert shifted["offset_db"] == result["offset_db"]
    assert shifted["holdout_mae_db"] == pytest.approx(10)
    assert not shifted["empirical_acceptance_passed"]


def test_rf_independent_wall_geometry():
    raw = rf_config()["scene"]
    raw["walls"] = [dict(wall_id="w", start=dict(x=2., y=-1., z=0.), end=dict(x=2., y=1., z=0.), height_m=3., material="concrete")]
    scene = RFScene.model_validate(raw)
    with_wall = reference_prediction(scene, PointMeters(x=4., y=0., z=1.))
    raw["walls"] = []
    assert reference_prediction(RFScene.model_validate(raw), PointMeters(x=4., y=0., z=1.)) - with_wall == pytest.approx(12)
    assert math.isfinite(with_wall)


def test_external_protocol_and_attestation_required(tmp_path):
    store, manifest, trust, _ = dossier(tmp_path)
    with pytest.raises(EvidenceError, match="preregistered"):
        import_campaign(store, manifest, **{**trust, "trusted_preregistrations": {}})
    with pytest.raises(EvidenceError, match="attestation_not_trusted"):
        import_campaign(store, manifest, **{**trust, "trusted_attesters": {"tester"}})
    with pytest.raises(EvidenceError, match="preregistration_mismatch"):
        import_campaign(store, manifest, **{**trust, "trusted_preregistrations": {next(iter(trust["trusted_preregistrations"])): 10.}})


def test_native_bytes_tamper_refused(tmp_path):
    store, manifest, trust, _ = dossier(tmp_path)
    path = tmp_path / "train.native.json"
    path.write_bytes(path.read_bytes().replace(b'100.0', b'101.0'))
    with pytest.raises(EvidenceError, match="hash_mismatch"):
        import_campaign(store, manifest, **trust)


def test_group_leakage_and_sample_omission_rejected():
    protocol = dict(schema_version="nanfo.independent-protocol.v1", campaign_id="c", dataset_id="d", domain="rf",
                    environment="synthetic", network_id="n", run_id="r", declared_at_unix_seconds=1.,
                    configuration=dict(path="c", sha256="0" * 64, size_bytes=1),
                    group_basis="A complete independent capture group.", instrument_ids=["i"],
                    groups=[dict(group_id="a", split="train", sample_ids=["s"]), dict(group_id="b", split="holdout", sample_ids=["s"])])
    with pytest.raises(ValidationError):
        AcquisitionProtocol.model_validate(protocol)


def installation(root, environment="isolated-emulation"):
    store, manifest, trust, config = dossier(root, environment=environment)
    scope = dict(network_id="n", run_id="run", provider_id="provider", environment="physical-network" if environment == "physical-network" else "isolated-emulation",
                 configuration_sha256=config["sha256"], egress_ids=["q"], demand_ids=["d"], action_ids=["route"],
                 max_dt_seconds=1., max_delay_seconds=0.25)
    evidence = put(root, "guarantee-evidence.json", {"TEST_ONLY": "not actual physical proof"})
    guarantee = dict(schema_version="nanfo.bound-guarantee.v1", scope=scope, campaign_sha256=manifest.sha256,
                     valid_from_unix_seconds=40., valid_until_unix_seconds=100., reviewer_id="reviewer",
                     assumptions="TEST ONLY reviewed conditions; no real calibration installed.")
    for key in ("arrival_enforcement", "service_curve", "within_interval_dynamics", "transition_and_delay", "complete_demand_attribution", "queue_sensor_error", "capacity_and_scheduler", "environment_identity"):
        guarantee[key] = evidence
    gref = put(root, "guarantee.json", guarantee)
    calibration = dict(calibration_id="cal", provider_id="provider", model_version="bounded-fluid-v1", network_id="n",
                       run_id="run", valid_from_unix_seconds=40., valid_until_unix_seconds=100., egress_ids=["q"], demand_ids=["d"],
                       min_error_upper_bytes=0., min_service_uncertainty_bytes_per_second=10.)
    iref = put(root, "installation.json", dict(schema_version="nanfo.trusted-calibration-installation.v1", scope=scope,
                campaign=manifest.model_dump(), calibration=calibration, guarantee=gref))
    args = dict(expected_installation_sha256=iref["sha256"], expected_scope=CalibrationScope(**scope), now=50.,
                **trust, accepted_guarantee_sha256={gref["sha256"]})
    return store, args


def test_explicit_scoped_installation_not_empirical_shortcut(tmp_path):
    store, args = installation(tmp_path)
    loaded = load_trusted_calibration(store, "installation.json", **args)
    assert loaded.calibration.calibration_id == "cal" and not loaded.physical_qualified
    with pytest.raises(EvidenceError, match="not_explicitly_accepted"):
        load_trusted_calibration(store, "installation.json", **{**args, "accepted_guarantee_sha256": set()})
    with pytest.raises(EvidenceError, match="expired"):
        load_trusted_calibration(store, "installation.json", **{**args, "now": 100.})
    changed = args["expected_scope"].model_copy(update={"action_ids": ["different"]})
    with pytest.raises(EvidenceError, match="scope_mismatch"):
        load_trusted_calibration(store, "installation.json", **{**args, "expected_scope": changed})


def test_synthetic_never_installed(tmp_path):
    store, args = installation(tmp_path, environment="synthetic")
    with pytest.raises(EvidenceError, match="campaign_installation_scope_mismatch"):
        load_trusted_calibration(store, "installation.json", **args)


def test_physical_requires_same_explicit_guarantee_boundary(tmp_path):
    store, args = installation(tmp_path, environment="physical-network")
    # This tests only the external trust boundary with test data; no real trust file is written.
    assert load_trusted_calibration(store, "installation.json", **args).physical_qualified
    with pytest.raises(EvidenceError):
        load_trusted_calibration(store, "installation.json", **{**args, "accepted_guarantee_sha256": set()})


def test_exact_schema_cli(capsys):
    assert main(["--schema", "installation"]) == 0
    assert "nanfo.trusted-calibration-installation.v1" in capsys.readouterr().out


def test_incomplete_action_and_transition_coverage(tmp_path):
    campaign = imported(tmp_path)
    changed = copy.deepcopy(campaign.configuration)
    changed["min_samples_per_action_per_split"] = 3
    with pytest.raises(EvidenceError, match="coverage_incomplete"):
        verify_network_campaign(campaign.model_copy(update={"configuration": changed}))


def test_native_record_derivation_refuses_rehashed_normalization(tmp_path):
    store, manifest, trust, _ = dossier(tmp_path)
    capture = json.loads((tmp_path / "holdout.json").read_bytes())
    capture["records"][0]["measurement"]["queues"][0]["queue_after_bytes"] = 1.
    new_capture = put(tmp_path, "holdout.json", capture)
    att = json.loads((tmp_path / "attestation.json").read_bytes())
    old_manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    att["capture_sha256"][1] = new_capture["sha256"]
    new_att = put(tmp_path, "attestation.json", att)
    old_manifest["captures"][1] = new_capture
    old_manifest["attestation"] = new_att
    new_manifest = put(tmp_path, "manifest.json", old_manifest)
    with pytest.raises(EvidenceError, match="raw_instrument_record_mismatch"):
        import_campaign(store, ArtifactRef(**new_manifest), **{**trust, "trusted_attesters": {new_att["sha256"]}})


def test_acquisition_records_actual_socket_events_and_replays(tmp_path):
    prepared = prepare_local(tmp_path / "prepared", network_id="n", run_id="run")
    assert prepared["requires_external_preregistration"]
    recipe = LocalAcquisitionRecipe.model_validate_json((tmp_path / "prepared" / "recipe.json").read_bytes())
    window = LocalWindow(sample_id="actual", previous_action_id="slow", action_id="fast",
                         offered_packets=8, packet_bytes=64, dispatch_delay_seconds=0.1)
    reading, native = measure_window(window, recipe)
    verify_native_events(native, reading)
    assert reading["measurement_complete"]
    assert reading["queues"][0]["arrivals"]["after"] == 512
    assert len(native["events"]) > 16
    assert not native["physical_qualified"]
    changed = copy.deepcopy(reading)
    changed["queues"][0]["departures"]["after"] += 1
    with pytest.raises(EvidenceError, match="counter_mismatch"):
        verify_native_events(native, changed)


def test_runtime_bound_and_route_scope(tmp_path):
    from app.modules.autonomy.safety import SafetyAction

    store, args = installation(tmp_path)
    loaded = load_trusted_calibration(store, "installation.json", **args)
    action = SafetyAction.model_validate(dict(action_id="route", network_id="n", run_id="run", snapshot_id="s",
        routes=[dict(demand_id="d", route_id="path")], bounds=dict(network_id="n", run_id="run", snapshot_id="s",
        action_id="route", calibration_id="cal", provider_id="provider", model_version="bounded-fluid-v1",
        policy_version="p", input_sha256="0" * 64, observed_at_unix_seconds=50., valid_until_unix_seconds=60.,
        dt_seconds=1., actuation_delay_upper_seconds=0.125, queues=[dict(egress_id="q",
        arrival_lower_bytes_per_second=0., arrival_upper_bytes_per_second=10., service_lower_bytes_per_second=20.,
        service_upper_bytes_per_second=30., error_upper_bytes=0.)])))
    scope_args = dict(configuration_sha256=loaded.scope.configuration_sha256, now=50., route_egress_ids={"path": ["q"]}, previous_action_id="route")
    loaded.validate_action(action, **scope_args)
    with pytest.raises(EvidenceError, match="outside_installed"):
        loaded.validate_action(action, **{**scope_args, "previous_action_id": "unknown"})
    with pytest.raises(EvidenceError, match="routes_differ"):
        loaded.validate_action(action, **{**scope_args, "route_egress_ids": {"path": ["different"]}})
    action.bounds.queues[0].arrival_upper_bytes_per_second = 0.
    with pytest.raises(EvidenceError, match="bounds_differ"):
        loaded.validate_action(action, **scope_args)


@pytest.mark.parametrize("receiver,expected_loss", [
    (dict(x=4., y=0., z=4.), 0.),  # Above the finite wall.
    (dict(x=4., y=4., z=1.), 0.),  # Beyond the finite segment.
    (dict(x=4., y=2., z=1.), 12.),  # Exact segment edge.
    (dict(x=2., y=0., z=1.), 0.),  # Receiver touching wall is not crossing.
])
def test_rf_reference_finite_surface_edges(receiver, expected_loss):
    raw = rf_config()["scene"]
    raw["walls"] = [dict(wall_id="w", start=dict(x=2., y=-1., z=0.), end=dict(x=2., y=1., z=0.), height_m=2., material="concrete")]
    obstructed = reference_prediction(RFScene.model_validate(raw), PointMeters(**receiver))
    raw["walls"] = []
    clear = reference_prediction(RFScene.model_validate(raw), PointMeters(**receiver))
    assert clear - obstructed == pytest.approx(expected_loss)


def test_rf_train_offset_bounded_not_expanded_after_failure(tmp_path):
    campaign = imported(tmp_path, domain="rf", mutate=lambda i, r: r.update(signal_dbm=r["signal_dbm"] + 60))
    result = qualify_rf(campaign)
    assert result["offset_db"] == 40
    assert result["holdout_mae_db"] == pytest.approx(23)
    assert not result["empirical_acceptance_passed"]


def test_cross_group_overlapping_windows_refuse(tmp_path):
    campaign = imported(tmp_path)
    captures = copy.deepcopy(campaign.captures)
    # Bypass importer solely to exercise the independent verifier's window checks.
    row = captures[1].records[0]
    data = row.model_dump()
    data["observed_at_unix_seconds"] = 10.5
    data["measurement"] = network_reading(10.5)
    captures[1].records[0] = type(row).model_validate(data)
    with pytest.raises(EvidenceError, match="windows_overlap"):
        verify_network_campaign(campaign.model_copy(update={"captures": captures}))


def test_missing_native_file_and_symlink_refuse(tmp_path):
    store, manifest, trust, _ = dossier(tmp_path)
    original = tmp_path / "train.native.json"
    moved = tmp_path / "moved.json"
    original.rename(moved)
    with pytest.raises(EvidenceError, match="artifact_missing"):
        import_campaign(store, manifest, **trust)
    original.symlink_to(moved)
    with pytest.raises(EvidenceError, match="symlink"):
        import_campaign(store, manifest, **trust)


def test_measurement_completed_before_attestation_required(tmp_path):
    campaign = imported(tmp_path)
    with pytest.raises(EvidenceError, match="attestation_precedes"):
        verify_network_campaign(campaign.model_copy(update={"attested_at_unix_seconds": 16.5}))


def test_duplicate_omitted_counter_scope_and_wrong_units_refuse(tmp_path):
    for index, mutation in enumerate((
        lambda r: r["queues"][0].update(demand_arrivals={}),
        lambda r: r.update(queue_units="packets"),
        lambda r: r.update(measurement_complete=1),
        lambda r: r["queues"][0]["arrivals"].update(before=20),
    )):
        root = tmp_path / str(index)
        root.mkdir()
        with pytest.raises((ValidationError, EvidenceError)):
            verify_network_campaign(imported(root, mutate=lambda i, r: mutation(r) if i == 2 else None))
