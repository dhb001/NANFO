"""Verifier preparation/negative evidence tests only. No Docker or measured claims."""

import ast
import copy
import fcntl
import json
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from scripts import verify_measured_alerts as verifier
from scripts.verify_execution import VerificationError
from tests.alert_support import DEVICE, NETWORK, START, WORKSPACE, observation


def evidence():
    samples = []
    for seconds, value in [(0, 90), (5, 91), (10, 92), (15, 10), (20, 9), (25, 8)]:
        sample = observation(seconds, value).model_dump(mode="json")
        sample["tags"].update(dpid=verifier.DPID, capacity_mbps=20)
        samples.append(sample)
    correlation = samples[0]["correlation_id"]
    items = []
    for event_type, first, last in [("alert.generated", 0, 2), ("alert.resolved", 3, 5)]:
        sample = samples[last]
        payload = {"network_id": str(NETWORK), "workspace_id": str(WORKSPACE), "device_id": str(DEVICE),
            "port_no": 1, "metric": verifier.METRIC, "unit": "%", "synthetic": False,
            "quality": "measured", "run_id": sample["tags"]["run_id"], "value": sample["value"],
            "window_started_at": samples[first]["observed_at"], "observed_at": sample["observed_at"],
            "observation_event_id": sample["event_id"], "resolution_reason": "measured_recovery",
            "rule": {"version": "operator-v1", "breach": 85.0, "recover": 70.0, "min_samples": 3,
                     "duration_seconds": 10.0, "max_gap_seconds": 10.0, "max_age_seconds": 30.0}}
        items.append({"event_id": event_type, "event_type": event_type, "alert_id": "incident",
                      "correlation_id": correlation, "payload": payload})
    return {"total": 2, "alert_id": "incident", "items": items}, samples, {
        "network_id": str(NETWORK), "workspace_id": str(WORKSPACE), "device_id": str(DEVICE), "correlation_id": correlation}


def test_plan_has_no_infrastructure_or_lock_side_effects(monkeypatch, capsys):
    monkeypatch.setattr(verifier, "external", AsyncMock(side_effect=AssertionError("Must not run Docker")))
    monkeypatch.setattr(verifier.os, "open", lambda *a, **kw: pytest.fail("Plan opened a file"))
    assert verifier.main(["--plan"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["status"] == "prepared_not_run" and plan["live_capture"] is False
    assert plan["migration"] == "0019" and plan["detector"]["duration_seconds"] == 10
    assert plan["workload"]["seconds"] == 30 and plan["workload"]["recovery_seconds"] >= 15


@pytest.mark.parametrize("args", [[], ["--live"], ["--plan", "--image", "latest"], ["--plan", "--timeout-seconds", "20"],
    ["--live", "--slot-released", "--preserve-stopped-container", "1db3"]])
def test_explicit_admission_before_resources(args, monkeypatch):
    monkeypatch.setattr(verifier, "verify", AsyncMock(side_effect=AssertionError("No admission")))
    with pytest.raises(SystemExit) as error:
        verifier.main(args)
    assert error.value.code == 2


def test_parent_campaign_lock_blocks_without_creating_evidence(tmp_path, monkeypatch, capsys):
    lock = tmp_path / "lab.lock"
    monkeypatch.setattr(verifier, "LOCK", lock)
    monkeypatch.setattr(verifier, "verify", AsyncMock(side_effect=AssertionError("Parent still owns lab")))
    with lock.open("w") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert verifier.main(["--live", "--slot-released", "--output-parent", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "parent_campaign_lab_slot_busy"
    assert list(tmp_path.iterdir()) == [lock]


def test_child_is_importable_and_traffic_has_fixed_foreground_bounds():
    compile(verifier.TRAFFIC, "measured-alert-fixed-traffic", "exec")
    tree = ast.parse(verifier.TRAFFIC)
    literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)]
    assert "30" in literals and "22M" in literals and "10.77.0.3" in literals
    assert "shell" not in [node.arg for node in ast.walk(tree) if isinstance(node, ast.keyword)]
    assert "sys.argv" not in verifier.TRAFFIC
    assert "'-D'" not in verifier.TRAFFIC


def test_sandbox_cannot_write_source_or_access_docker(tmp_path):
    args = verifier.sandbox(tmp_path, evidence=True)
    assert args[:4] == ["bwrap", "--ro-bind", "/", "/"]
    assert "--unshare-user" in args and "--unshare-pid" in args
    assert args[-3:] == ["--bind", str(tmp_path / "collector"), str(tmp_path / "collector")]
    assert "/run" in args and "docker.sock" not in " ".join(args)


def test_independent_lifecycle_evidence_validation():
    history, samples, scope = evidence()
    result = verifier.validate_lifecycle(history, list(reversed(samples)), **scope)
    assert result["breach"]["samples"] == result["recovery"]["samples"] == 3
    assert result["breach"]["seconds"] == result["recovery"]["seconds"] == 10


@pytest.mark.parametrize("fault", ["value", "scope", "synthetic", "run", "correlation", "threshold", "time", "count", "id", "resolution", "duplicate", "gap"])
def test_rejects_false_measured_claims(fault):
    history, samples, scope = evidence()
    if fault == "value":
        samples[1]["value"] = 84
    elif fault == "scope":
        samples[1]["device_id"] = "foreign"
    elif fault == "synthetic":
        samples[1]["tags"]["synthetic"] = True
    elif fault == "run":
        samples[1]["tags"]["run_id"] = "another-run"
    elif fault == "correlation":
        history["items"][1]["correlation_id"] = "foreign"
    elif fault == "threshold":
        history["items"][0]["payload"]["rule"]["breach"] = 80
    elif fault == "time":
        history["items"][0]["payload"]["window_started_at"] = (START + timedelta(seconds=1)).isoformat()
    elif fault == "count":
        history["total"] = 3
    elif fault == "id":
        history["items"][1]["alert_id"] = "different-incident"
    elif fault == "resolution":
        history["items"][1]["payload"]["resolution_reason"] = "manual"
    elif fault == "duplicate":
        samples.append(copy.deepcopy(samples[0]))
    elif fault == "gap":
        samples[1]["observed_at"] = (START + timedelta(seconds=11)).isoformat()
        samples[2]["observed_at"] = (START + timedelta(seconds=12)).isoformat()
        history["items"][0]["payload"]["observed_at"] = samples[2]["observed_at"]
    with pytest.raises(VerificationError):
        verifier.validate_lifecycle(history, samples, **scope)
