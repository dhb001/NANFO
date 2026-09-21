"""Packaging-owned restore handoff tests, no Docker or database access."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from deploy import backup_restore, manage, verify


@pytest.fixture
def restored(tmp_path, monkeypatch):
    config = {
        "NANFO_PROJECT": "nanfo-deploy-target",
        "EMULATION_CONTROL_ENABLED": "false",
        "NANFO_BACKEND_IMAGE": "backend",
        "NANFO_FRONTEND_IMAGE": "frontend",
        "NANFO_NEO4J_IMAGE": "neo4j",
    }
    checkpoint = {
        "safe": True,
        "schema": "0029",
        "reports": {"verified_reports": 1},
        "model_references": {},
        "telemetry_archive": {name: {} for name in (
            "telemetry_archive_receipts", "telemetry_event_tombstones", "telemetry_evidence_pins",
            "telemetry_reference_coverage", "telemetry_reference_reconciliation")},
        "autonomous_execution": {"safe": True, "unreleased_executions": 0},
        "experimental_lab": {"safe": True, "unreleased_runs": 0, "owned_resources": 0, "pending_actions": 0},
    }
    manifest = {
        "project": "nanfo-deploy-source",
        "images": {"api": {"id": "exact"}},
        "mount_contract": {},
        "external_fingerprints": {},
        "volumes": [{"logical": "reports"}, {"logical": "telemetry_archive"}],
        "checkpoint": checkpoint,
    }
    deployment = Mock(spec=backup_restore.Deployment)
    deployment.run.return_value = b""
    deployment.images.return_value = manifest["images"]
    deployment.mount_contract.return_value = {}
    deployment.external_fingerprints.return_value = {}
    deployment.inventory.return_value = ({"reports": "nanfo-deploy-target_reports",
                                          "telemetry_archive": "nanfo-deploy-target_telemetry_archive"}, {})
    deployment.maintenance.return_value = checkpoint.copy()
    monkeypatch.setattr(manage, "load_config", lambda _: config)
    monkeypatch.setattr(backup_restore, "load_manifest", lambda *args: manifest)
    monkeypatch.setattr(backup_restore, "Deployment", lambda *args: deployment)
    monkeypatch.setattr(
        manage, "run", lambda *args, **kwargs: SimpleNamespace(stdout="sha256:image\n")
    )
    key = tmp_path / "key"
    key.write_bytes(b"x" * 32)
    key.chmod(0o600)
    return tmp_path, key, config, deployment


def test_verified_restore_records_marker_without_initializing(restored):
    state, key, _, deployment = restored
    manage.adopt_restored(state, state, key)
    assert (state / "initialized.json").exists()
    assert json.loads((state / "initialized.json").read_text())["schema"] == "0029"
    deployment.compose.assert_not_called()
    assert [call.args[0] for call in deployment.maintenance.call_args_list] == [
        "checkpoint",
        "restore-verify",
    ]


@pytest.mark.parametrize(
    "failure",
    [
        "source_running",
        "images",
        "checkpoint",
        "control",
        "existing_marker",
        "missing_volume",
    ],
)
def test_restore_proof_failure_never_creates_marker(restored, failure):
    state, key, config, deployment = restored
    if failure == "source_running":
        deployment.run.return_value = b"running-owner"
    elif failure == "images":
        deployment.images.return_value = {}
    elif failure == "checkpoint":
        deployment.maintenance.return_value = {"safe": True, "schema": "0018"}
    elif failure == "control":
        config["EMULATION_CONTROL_ENABLED"] = "true"
    elif failure == "existing_marker":
        (state / "initializing").touch()
    else:
        deployment.inventory.return_value = ({}, {})
    with pytest.raises(ValueError):
        manage.adopt_restored(state, state, key)
    assert not (state / "initialized.json").exists()


@pytest.mark.parametrize("schema", ["0019", "0027", "0028"])
def test_historical_backup_not_adopted_into_current_composition(restored, monkeypatch, schema):
    state, key, _, deployment = restored
    manifest = backup_restore.load_manifest(state, b"x" * 32)
    manifest["checkpoint"]["schema"] = schema
    monkeypatch.setattr(backup_restore, "load_manifest", lambda *args: manifest)
    deployment.maintenance.return_value = manifest["checkpoint"].copy()
    with pytest.raises(ValueError, match="requires schema 0029"):
        manage.adopt_restored(state, state, key)
    assert not (state / "initialized.json").exists()
    assert all(
        call.args != ("restore-verify",)
        for call in deployment.maintenance.call_args_list
    )


def test_network_worker_compose_and_lifecycle_contract():
    config = yaml.safe_load((Path(__file__).parent / "compose.yaml").read_text())
    worker = config["services"]["network-outbox-worker"]
    assert worker["command"] == ["python", "-m", "scripts.run_network_outbox_worker"]
    assert worker["healthcheck"]["test"][-3:] == [
        "scripts/check_worker_health.py",
        "--worker",
        "network",
    ]
    assert worker["read_only"] is True
    assert worker["volumes"] == ["runtime_secrets:/run/secrets:ro"]
    assert "ports" not in worker
    assert "network-outbox-worker" in manage.SERVICES


def test_neo4j_signal_forwarder_runs_after_privilege_drop():
    root = Path(__file__).parent
    script = (root / "neo4j-entrypoint.sh").read_text()
    dockerfile = (root / "Dockerfile.neo4j").read_text()
    assert (
        "exec su-exec neo4j:neo4j tini -g -- /startup/docker-entrypoint.sh neo4j"
        in script
    )
    assert 'ENTRYPOINT ["sh", "/startup/nanfo-entrypoint.sh"]' in dockerfile


def test_stop_includes_network_publisher_after_checkpoint(restored, monkeypatch):
    state, _, _, _ = restored
    commands = Mock(return_value=SimpleNamespace(stdout='{"safe":true}'))
    monkeypatch.setattr(manage, "compose", commands)
    monkeypatch.setattr("sys.argv", ["manage.py", "--state", str(state), "stop"])
    manage.main()
    calls = [call.args[1:] for call in commands.call_args_list]
    assert calls[0] == ("stop", "gateway", "api")
    assert calls[1][-1] == "checkpoint"
    assert "network-outbox-worker" in calls[2]
    assert calls[3] == ("stop", *manage.STORES)


@pytest.mark.parametrize("schema", [None, "0019", "0020", "0024", "0026", "0027", "0028"])
def test_start_refuses_old_marker_before_any_lifecycle(restored, monkeypatch, schema):
    state, _, config, _ = restored
    (state / "initialized.json").write_text(
        json.dumps({"project": config["NANFO_PROJECT"], "images": {}, "schema": schema})
    )
    commands = Mock()
    monkeypatch.setattr(manage, "compose", commands)
    monkeypatch.setattr("sys.argv", ["manage.py", "--state", str(state), "start"])
    with pytest.raises(ValueError, match="schema 0029"):
        manage.main()
    commands.assert_not_called()


def test_pending_work_restart_includes_and_checks_network_publisher(monkeypatch):
    stack, api = Mock(), Mock()
    services = ("api", *verify.WORKERS)
    stack.inspect_service.side_effect = [
        {"State": {"StartedAt": stamp}}
        for stamp in ("before", "after")
        for _ in services
    ]
    api.request.side_effect = [
        {"status": "requested", "report_id": "report"},
        {"state": "queued", "simulation_id": "simulation"},
    ]
    monkeypatch.setattr(
        verify, "download_report", Mock(return_value={"report_id": "report"})
    )
    monkeypatch.setattr(
        verify,
        "until",
        Mock(
            side_effect=[
                True,
                True,
                {
                    "simulation_id": "simulation",
                    "state": "completed",
                    "run_output": {"loss_pct": 45},
                },
            ]
        ),
    )
    result = verify.restart_with_pending_work(
        stack, api, "workspace", "network", "previous"
    )
    assert "network-outbox-worker" in result["restarted_services"]
    assert stack.compose.call_args.args == ("restart", "--timeout", "15", *services)
    assert [call.args[0] for call in stack.inspect_service.call_args_list].count(
        "network-outbox-worker"
    ) == 2
