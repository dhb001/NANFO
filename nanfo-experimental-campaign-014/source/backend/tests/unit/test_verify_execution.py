"""Verifier contract/evidence checks; these tests do not claim live execution."""

import json
import os
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.modules.intent.lab import LabIntent
from scripts.verify_execution import (
    _DEADLINE,
    _READBACK,
    _TRAFFIC,
    VerificationError,
    assert_lab_idle,
    intent_payload,
    main,
    private_json,
    verify_no_flow_reinstall,
    verify_result,
)
from tests.unit.test_intent_lab import command


@pytest.mark.parametrize("operation", ["reroute", "multipath", "shape", "police", "restore"])
def test_live_payload_matches_backend_and_lab(operation):
    from emulation.mailbox import validatePlan

    plan = LabIntent.model_validate(intent_payload(operation)).normalize()
    assert validatePlan(plan.model_dump(mode="json"))


@pytest.mark.parametrize("fault", [None, "identity", "fence", "evidence", "status", "selector", "rollback"])
def test_verifier_never_accepts_fabricated_or_mismatched_result(fault):
    cmd = command().model_dump(mode="json")
    result = {key: cmd[key] for key in ("version", "execution_id", "run_id", "binding_digest", "plan_hash", "fence")}
    result.update(status="completed", verification={"readback_verified": True, "readback_sha256": "a" * 64,
        "config_readback_and_reachability": True, "traffic_effects_verified": False,
        "probe": {"sent": 3, "received": 3, "source_host": "h1", "destination_host": "h3"}},
        rollback=None, failure_reason=None, completed_at=datetime.now(UTC).isoformat())
    if fault == "identity":
        result["plan_hash"] = "b" * 64
    elif fault == "fence":
        result["fence"] = 2
    elif fault == "evidence":
        result["verification"] = {"status": "verified"}
    elif fault == "status":
        result["status"] = "uncertain"
    elif fault == "selector":
        result["verification"]["probe"]["source_host"] = "h2"
    elif fault == "rollback":
        result.update(status="cancelled", rollback={"verified": True})
    if fault is None:
        assert verify_result(cmd, result)["status"] == "completed"
    else:
        with pytest.raises(VerificationError):
            verify_result(cmd, result, status="cancelled" if fault == "rollback" else "completed")


async def test_busy_lab_preflight_refuses_lifecycle(monkeypatch):
    docker = AsyncMock(side_effect=["other-agent-container\n", ""])
    monkeypatch.setattr("scripts.verify_execution.external", docker)
    with pytest.raises(VerificationError, match="Lab busy"):
        await assert_lab_idle()
    assert all(call.args[1] == "ps" for call in docker.await_args_list)


async def test_explicit_live_opt_in_before_side_effects(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["verify_execution.py"])
    mkdir = AsyncMock()
    monkeypatch.setattr("scripts.verify_execution.tempfile.mkdtemp", mkdir)
    with pytest.raises(SystemExit) as error:
        await main()
    assert error.value.code == 2
    mkdir.assert_not_called()


def test_private_artifact_refuses_overwrite_or_symlink(tmp_path):
    path = tmp_path / "result.json"
    private_json(path, {"passed": False, "stage": "preflight"})
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert json.loads(path.read_bytes())["passed"] is False
    with pytest.raises(FileExistsError):
        private_json(path, {})
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(FileExistsError):
        private_json(link, {})


@pytest.mark.parametrize("source", [_READBACK, _TRAFFIC, _DEADLINE])
def test_trusted_container_scripts_compile(source):
    compile(source, "verifier-stdin", "exec")


def test_recovery_checks_actual_flow_age_and_counters():
    def snapshot(age, packets):
        return {"switches": {"access1": {"flows": f" cookie=0x4e414e4600000001, duration={age}s, n_packets={packets}, priority=30000,ip actions=output:1"}}}

    verify_no_flow_reinstall(snapshot(2, 10), snapshot(3, 11))
    for after in (snapshot(1, 11), snapshot(3, 0), {"switches": {}}):
        with pytest.raises(VerificationError):
            verify_no_flow_reinstall(snapshot(2, 10), after)
