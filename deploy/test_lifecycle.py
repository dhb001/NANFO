"""Packaging-owned restore handoff tests, no Docker or database access."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deploy import backup_restore, manage


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
        "schema": "0019",
        "reports": {"verified_reports": 1},
        "model_references": {},
    }
    manifest = {
        "project": "nanfo-deploy-source",
        "images": {"api": {"id": "exact"}},
        "mount_contract": {},
        "external_fingerprints": {},
        "volumes": [{"logical": "reports"}],
        "checkpoint": checkpoint,
    }
    deployment = Mock(spec=backup_restore.Deployment)
    deployment.run.return_value = b""
    deployment.images.return_value = manifest["images"]
    deployment.mount_contract.return_value = {}
    deployment.external_fingerprints.return_value = {}
    deployment.inventory.return_value = ({"reports": "nanfo-deploy-target_reports"}, {})
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
