"""Sanitized ADR013-001 shapes and independent raw-metric refusal regressions.

Fixtures are synthetic measurements with the completed producer's exact field
shape, not qualified policies. Optional campaign test reads real bytes only.
"""

import copy
import hashlib
import json
import os

import pytest
from pydantic import ValidationError

from app.modules.autonomy.artifact_io import ArtifactStore, EvidenceError
from app.modules.autonomy.campaign_evidence import (
    CONTRACT_HASH,
    PORTS,
    RawData,
    RawRequest,
    digest,
    raw_calibration_diagnostics,
    reconstruct_measurement,
    relative_evidence_path,
)
from app.modules.autonomy.qualification import (
    ProducerQualification,
    import_qualification,
)
from app.modules.autonomy.readiness_cli import main
from tests.unit.test_autonomy_tooling import producer as producer_fixture


@pytest.fixture
def completed_producer_shape():
    """Actual rejected pilot41 values, stripped of machine/user identities only."""
    producer = producer_fixture.__wrapped__()
    producer["qualified"] = False
    producer["train_only_action_effects"] = {
        "path0": 2.7261530972494357,
        "path1": 2.1865122434627615,
    }
    producer["directional_dependence"] = {
        "path0": {
            "desired_route_fraction": 0,
            "pressure_swap_desired_route_fraction": 1,
            "swap_is_diagnostic_not_measured_reward": True,
        },
        "path1": {
            "desired_route_fraction": 1,
            "pressure_swap_desired_route_fraction": 0,
            "swap_is_diagnostic_not_measured_reward": True,
        },
    }
    producer["evidence_paths"] = {
        "checkpoint": "/reviewed/campaign/train-41/checkpoint.ptz",
        "training": "/reviewed/campaign/train-41/summary.json",
        "validation": [
            f"/reviewed/campaign/validation-{p}/summary.json"
            for p in ("41", "constant0", "constant1", "heuristic", "ospf")
        ],
        "calibration": [
            f"/reviewed/campaign/calibration-{p}/summary.json"
            for p in ("constant0", "constant1")
        ],
        "plan": "/reviewed/campaign/plan.json",
    }
    producer["checkpoint"]["manifest"]["client_source_files"] = {
        "contracts.py": "c71b8a3cd82420f1daf3972c976ddd933b79c975c17d24d36e3726260e8214f6"
    }
    return producer


def test_completed_schema_accepts_all_new_fields_without_discarding(
    completed_producer_shape,
):
    parsed = ProducerQualification.model_validate(completed_producer_shape)
    assert parsed.model_dump() == completed_producer_shape
    assert not parsed.qualified
    assert parsed.directional_dependence["path0"].desired_route_fraction == 0
    assert parsed.evidence_paths.training.endswith("train-41/summary.json")


@pytest.mark.parametrize(
    "key",
    ["train_only_action_effects", "calibration_evidence_sha256", "evidence_paths"],
)
def test_completed_schema_new_fields_required(completed_producer_shape, key):
    del completed_producer_shape[key]
    with pytest.raises(ValidationError):
        ProducerQualification.model_validate(completed_producer_shape)


def test_completed_schema_extra_or_unsafe_claim_refused(completed_producer_shape):
    completed_producer_shape["allow_execution"] = True
    with pytest.raises(ValidationError):
        ProducerQualification.model_validate(completed_producer_shape)


@pytest.fixture
def raw_window():
    request = {
        "version": 1,
        "command": "reset",
        "episode_id": None,
        "episode_steps": 4,
        "mode": "matched",
        "scenario": "path0",
        "seed": 1500,
        "step_index": None,
        "action": None,
        "window_seconds": 2.0,
    }
    spec = {"version": 3, "name": "sanitized-measurement-fixture"}
    provenance = {"source_sha256": "a" * 64, "lab_image_id": "sha256:" + "b" * 64}
    route = ["access1", "dist1", "access2"]
    manifest = {
        "environment_spec": spec,
        "spec_hash": digest(spec),
        "lab_provenance": provenance,
        "contract": {"action_map": [route, ["access1", "dist2", "access2"]]},
        "contract_hash": CONTRACT_HASH,
    }
    counters, queues = {}, {}
    for ports in PORTS:
        for port in ports:
            counters[port] = {
                "before": {"monotonic_seconds": 9.0, "rx_bytes": 0, "tx_bytes": 0},
                "after": {
                    "monotonic_seconds": 13.0,
                    "rx_bytes": 1200,
                    "tx_bytes": 1200,
                },
                "duration_seconds": 4.0,
            }
            queues[port] = {
                "monotonic_seconds": 11.0,
                "backlog_bytes": 1242,
                "backlog_packets": 1,
                "raw_leaf_qdiscs": [
                    {
                        "kind": "netem",
                        "handle": "10:",
                        "parent": "5:1",
                        "backlog": 1242,
                        "qlen": 1,
                    }
                ],
            }
    worker = {
        "bytes": 1200,
        "packets": 1,
        "highest_sequence": 0,
        "duration_seconds": 4.0,
        "started_monotonic_seconds": 9.0,
        "finished_monotonic_seconds": 13.0,
    }
    paths = {}
    for source, dest in (("h1", "h3"), ("h2", "h4")):
        nodes = [source, *route, dest]
        paths[f"{source}->{dest}"] = {
            "nodes": nodes,
            "kernel_routes": [
                {"node": n, "route": {"dev": f"{n}-eth1"}} for n in nodes[:-1]
            ],
        }
    owned = {}
    for node in route:
        for table in (19110, 19111):
            source, dest = (
                ("10.78.8.2", "10.78.10.2")
                if table == 19110
                else ("10.78.10.2", "10.78.8.2")
            )
            owned[f"{node}:{table}"] = {
                "rules": [
                    {"priority": table, "table": str(table), "src": source, "dst": dest}
                ],
                "routes": [
                    {
                        "dst": dest,
                        "protocol": "static",
                        "dev": f"{node}-eth1",
                        "gateway": "10.78.4.1",
                    }
                ],
            }
    route_info = {
        "path": route,
        "changed": False,
        "readback": {"paths": paths, "owned": owned},
        "policy": {"mode": "matched"},
    }
    observation = {
        "path_capacity_mbps": [20, 20],
        "path_utilization": [0.00012, 0.00012],
        "path_queue_packets": [1, 1],
        "latency_ms": 24.0,
        "loss_fraction": 0.0,
        "goodput_mbps": 0.0024,
        "offered_mbps": 0.0024,
        "actual_offered_mbps": 0.0024,
        "background_mbps": 0.0024,
        "previous_action": 0,
        "seconds_since_change": 2.0,
    }
    evidence = {
        "environment_spec": spec,
        "spec_hash": digest(spec),
        "provenance": provenance,
        "measurement_complete": True,
        "transition_traffic_included": True,
        "post_control_interval": {"start": 10.0, "end": 12.0},
        "control_start_monotonic_seconds": 10.0,
        "measured_window_seconds": 2.0,
        "phase": {"offered_mbps": 0.0024, "background_mbps": 0.0024},
        "udp_sent": [copy.deepcopy(worker), copy.deepcopy(worker)],
        "udp_received": [copy.deepcopy(worker), copy.deepcopy(worker)],
        "actual_offered_mbps": [0.0024, 0.0024],
        "ping": {"sent": 2, "received": 2, "rtt_avg_ms": 24.0},
        "service_outage": False,
        "counter_windows": counters,
        "queue_peaks": queues,
        "route": route_info,
        "route_end": copy.deepcopy(route_info),
    }
    data = {
        "episode_id": "sanitized-episode",
        "step_index": 0,
        "mode": "matched",
        "seed": 1500,
        "scenario": "path0",
        "terminated": False,
        "truncated": False,
        "observation": observation,
        "evidence": evidence,
    }
    return data, request, manifest


def reconstruct(window):
    data, request, manifest = window
    return reconstruct_measurement(
        RawData.model_validate(data), RawRequest.model_validate(request), manifest
    )


def test_raw_physical_bytes_not_packets_or_arbitrary_endpoints(raw_window):
    result = reconstruct(raw_window)
    assert result["queues"][0]["sampled_peak_backlog_bytes"] == 1242
    assert result["queues"][0]["tx_bytes_per_second"] == 300
    assert result["goodput_mbps"] == 0.0024
    result.update(action=0)
    diagnostics = raw_calibration_diagnostics([{"split": "train", "rows": [result]}])
    assert diagnostics["groups"][0]["max_sampled_peak_backlog_bytes"] == 1242
    assert not diagnostics["fit_performed"] and not diagnostics["qualified"]
    assert (
        diagnostics["holdout_coverage"] is None
        and diagnostics["trusted_calibration"] is None
    )
    assert "queue_endpoints_not_measured" in diagnostics["reasons"]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda d: d["observation"].update(goodput_mbps=999), "derived_measurement"),
        (lambda d: d["observation"].update(loss_fraction=0.5), "derived_measurement"),
        (
            lambda d: d["evidence"]["queue_peaks"]["access1-eth1"].update(
                backlog_bytes=0
            ),
            "derived_measurement",
        ),
        (lambda d: d["evidence"]["queue_peaks"].pop("access1-eth1"), "egress_scope"),
        (lambda d: d["evidence"]["udp_received"][0].update(bytes=2400), "packet_bytes"),
        (
            lambda d: d["evidence"]["counter_windows"]["access1-eth1"]["before"].update(
                tx_bytes=2400
            ),
            "counter_reset",
        ),
        (lambda d: d["evidence"]["route_end"].update(changed=True), "route_changed"),
        (lambda d: d["evidence"].update(measurement_complete=1), "incomplete"),
        (
            lambda d: d["evidence"]["queue_peaks"]["access1-eth1"].update(
                monotonic_seconds=20
            ),
            "queue_time",
        ),
        (
            lambda d: d["evidence"]["route"]["readback"]["owned"].pop("access1:19110"),
            "ownership_incomplete",
        ),
    ],
)
def test_raw_modifications_refuse_even_without_hash_gate(raw_window, change, reason):
    change(raw_window[0])
    with pytest.raises(EvidenceError, match=reason):
        reconstruct(raw_window)


def test_validation_not_used_for_calibration(raw_window):
    row = reconstruct(raw_window)
    row["action"] = 0
    assert (
        raw_calibration_diagnostics([{"split": "validation", "rows": [row]}])["groups"]
        == []
    )


def test_absolute_producer_paths_require_operator_root():
    store = ArtifactStore("/reviewed")
    assert (
        relative_evidence_path(store, "/reviewed/campaign/plan.json")
        == "campaign/plan.json"
    )
    with pytest.raises(EvidenceError, match="outside_operator_root"):
        relative_evidence_path(store, "/reviewed-foreign/secrets")


def test_output_never_overwrites_input_or_existing_file(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("NANFO_AUTONOMY_ARTIFACT_ROOT", str(root))
    with pytest.raises(SystemExit):
        main(["--output", str(root / "new.json")])
    output = tmp_path / "assessment.json"
    assert main(["--output", str(output)]) == 2
    before = output.read_bytes()
    with pytest.raises(SystemExit):
        main(["--output", str(output)])
    assert before == output.read_bytes()


@pytest.mark.skipif(
    not os.environ.get("NANFO_TEST_ADR013_CAMPAIGN_ROOT"),
    reason="opt-in immutable measured campaign",
)
@pytest.mark.parametrize("pilot", [41, 42])
def test_real_campaign_reconstruction_and_immutability(pilot, monkeypatch, tmp_path):
    root = os.environ["NANFO_TEST_ADR013_CAMPAIGN_ROOT"]
    store = ArtifactStore(root)
    path = f"qualification-{pilot}.json"
    before = store.read(path)
    monkeypatch.setenv(
        "NANFO_AUTONOMY_QUALIFICATION_SHA256", hashlib.sha256(before).hexdigest()
    )
    monkeypatch.setenv(
        "NANFO_AUTONOMY_CAMPAIGN_INDEX_SHA256",
        hashlib.sha256(store.read("artifact-hashes.json")).hexdigest(),
    )
    result = import_qualification(store, path)
    assert result["raw_metrics_reconstructed"]
    assert result["validation_action_counts"] == [16, 0]
    assert result["measured_directional_fractions"] == {"path0": 0, "path1": 1}
    assert result["test_attempt_count"] == 0
    assert result["inventory_files_verified"] == 122
    assert {
        "useful_model_unqualified",
        "directional_dependence_failed_path0",
        "producer_pressure_swap_failed_path1",
    } <= set(result["reasons"])
    assert not result["qualified"] and not result["installed"]
    assert store.read(path) == before
    # A forged true qualification flag is never sufficient, even when explicitly pinned.
    raw = json.loads(before)
    raw["qualified"] = True
    from app.modules.autonomy.campaign_evidence import assess_producer_campaign

    forged = assess_producer_campaign(
        store, path, raw, hashlib.sha256(before).hexdigest()
    )
    assert not forged["qualified"] and "useful_model_unqualified" in forged["reasons"]
    # Alter an in-memory raw record, not historical files: independent derivation refuses.
    content = store.read(f"train-{pilot}/evidence.jsonl")
    ipc = json.loads(content.splitlines()[1])
    raw = json.loads(before)
    ipc["response"]["data"]["evidence"]["queue_peaks"]["access1-eth1"][
        "backlog_bytes"
    ] += 1
    with pytest.raises(EvidenceError):
        reconstruct_measurement(
            RawData.model_validate(ipc["response"]["data"]),
            RawRequest.model_validate(ipc["request"]),
            raw["checkpoint"]["manifest"],
        )
