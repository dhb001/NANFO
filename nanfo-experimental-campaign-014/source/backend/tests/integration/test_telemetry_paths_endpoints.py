"""Authenticated HTTP provider tests with raw pcaps and current authority checks."""

import json
import os
import shutil
import uuid
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.dependencies import get_db, get_redis
from app.main import app
from tests.unit.test_telemetry_paths import NOW
from tests.unit.test_telemetry_paths import path_evidence as evidence_fixture  # noqa: F401


@pytest.fixture
def paths_http(request, session_auth, tenant_auth, monkeypatch):
    e = request.getfixturevalue("evidence_fixture")
    settings = get_settings().model_copy(update={"EXECUTION_MODE": "emulation",
        "EMULATION_SNAPSHOT_PATH": str(e.snapshot_path), "EMULATION_BINDING_PATH": str(e.binding_path)})
    monkeypatch.setattr("app.api.v1.telemetry_paths.get_settings", lambda: settings)
    clock = SimpleNamespace(now=lambda tz: NOW)
    monkeypatch.setattr("app.modules.telemetry.paths.datetime", clock)
    network_access = AsyncMock(return_value=SimpleNamespace(network_id=e.binding.network_id,
                                                           workspace_id=e.binding.workspace_id))
    monkeypatch.setattr("app.api.v1.telemetry_paths.NetworkService.assert_network_workspace_access", network_access)
    # Keep real binding validation and device lookup logic, replace only persistence.
    devices = {device_id: SimpleNamespace(network_id=e.binding.network_id, status="active", deleted_at=None)
               for device_id in (*e.binding.switches.values(), *e.binding.hosts.values())}
    monkeypatch.setattr("app.modules.network.repository.DeviceRepository.get_by_id",
                        AsyncMock(side_effect=devices.get))
    owner_profile = AsyncMock(return_value=SimpleNamespace(permissions=["write:config", "read:topology"]))
    monkeypatch.setattr("app.modules.identity.service.AuthService.get_profile", owner_profile)

    async def db():
        yield AsyncMock()

    async def redis():
        yield session_auth.redis

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_redis] = redis
    token, _ = session_auth.issue(user_id=str(uuid.uuid4()), email="paths@example.com",
                                  roles=["Viewer"], permissions=["read:telemetry"])
    e.headers = {"Authorization": f"Bearer {token}"}
    e.url = f"/api/v1/telemetry/paths?network_id={e.binding.network_id}"
    e.client = TestClient(app, raise_server_exceptions=False)
    e.network_access, e.owner_profile, e.devices, e.clock = network_access, owner_profile, devices, clock
    yield e
    app.dependency_overrides.clear()


def test_paths_http_replays_pcaps_and_returns_canonical_ids(paths_http):
    e = paths_http
    response = e.client.get(e.url, headers=e.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] and body["errors"] is None and body["meta"]["request_id"]
    data = body["data"]
    assert data["status"] == "measured" and data["measured_path_count"] == 3
    assert data["captured_packet_count"] == 24 and data["evidence_verification"] == "raw_pcap_replayed"
    assert data["paths"][0]["source_device_id"] == str(e.binding.hosts["h1"])
    assert e.owner_profile.await_args.args[0] == str(e.binding.actor_user_id)
    assert any(call.kwargs.get("require_write") for call in e.network_access.await_args_list)


def test_paths_http_authentication_and_current_permission(paths_http, session_auth):
    e = paths_http
    assert e.client.get(e.url).status_code == 401
    token, _ = session_auth.issue(user_id=str(uuid.uuid4()), email="denied@example.com",
                                  roles=["Guest"], permissions=[])
    assert e.client.get(e.url, headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_paths_http_denies_current_network_access(paths_http):
    e = paths_http
    e.network_access.side_effect = HTTPException(403, "Insufficient permissions.")
    response = e.client.get(e.url, headers=e.headers)
    assert response.status_code == 403 and not response.json()["success"]
    assert e.owner_profile.await_count == 0


@pytest.mark.parametrize("fault", ["owner_revoked", "deleted_device", "foreign_device", "binding_scope"])
def test_paths_http_current_binding_ownership_fail_closed(paths_http, fault):
    e = paths_http
    if fault == "owner_revoked":
        e.owner_profile.return_value.permissions = ["read:topology"]
    elif fault == "deleted_device":
        next(iter(e.devices.values())).deleted_at = NOW
    elif fault == "foreign_device":
        next(iter(e.devices.values())).network_id = uuid.uuid4()
    else:
        e.network_access.return_value.network_id = uuid.uuid4()
    response = e.client.get(e.url, headers=e.headers)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "unavailable"
    assert not response.json()["data"]["paths"]


def test_paths_http_rejects_json_self_attestation_and_reports_stale_snapshot(paths_http):
    e = paths_http
    e.artifact["paths"][0]["observed_hops"][0]["egress_port"] = 2
    e.publish()
    response = e.client.get(e.url, headers=e.headers)
    assert response.json()["data"]["status"] == "invalid"
    e.clock.now = lambda tz: NOW + timedelta(seconds=60)
    response = e.client.get(e.url, headers=e.headers)
    assert response.json()["data"]["reason"] == "current_snapshot_unavailable"


@pytest.mark.parametrize("query", ["", "?network_id=not-a-uuid"])
def test_paths_http_network_id_required_and_validated(paths_http, query):
    response = paths_http.client.get("/api/v1/telemetry/paths" + query, headers=paths_http.headers)
    assert response.status_code == 422


@pytest.mark.skipif(os.environ.get("NANFO_REPLAY_PROBE_CAPTURE") != "1",
                    reason="Opt-in replay of local real lab captures, not live tenant authorization")
def test_recorded_real_lab_pcaps_through_http_provider(paths_http):
    """Replay captured time explicitly; never relabel old evidence as live/current."""
    e = paths_http
    output = Path(__file__).resolve().parents[3] / "emulation" / "output"
    snapshot = json.loads((output / "snapshot.json").read_bytes())
    artifact = json.loads((output / "probe-paths.json").read_bytes())
    window = str(uuid.UUID(artifact["window_id"]))
    capture_dir = "probe-capture-" + window
    shutil.copytree(output / capture_dir, e.output / capture_dir)
    shutil.copyfile(output / "snapshot.json", e.snapshot_path)
    shutil.copyfile(output / "probe-paths.json", e.artifact_path)
    replay_time = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
    e.clock.now = lambda tz: replay_time
    response = e.client.get(e.url, headers=e.headers)
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["status"] == "measured", result
    assert result["run_id"] == artifact["run_id"] and result["measured_path_count"] == 3
    assert result["evidence_sha256"] == artifact["evidence_sha256"]
    assert result["evidence_verification"] == "raw_pcap_replayed"
    # Retain the real window, advance only the current snapshot in this replay fixture.
    later = replay_time + timedelta(seconds=31)
    snapshot["observed_at"] = later.isoformat()
    for kind in ("switches", "queues", "probes"):
        for row in snapshot[kind]:
            row["observed_at"] = later.isoformat()
    e.snapshot_path.write_text(json.dumps(snapshot))
    e.clock.now = lambda tz: later
    stale = e.client.get(e.url, headers=e.headers).json()["data"]
    assert stale["status"] == "stale" and stale["freshness"] == "stale"
    assert stale["evidence_sha256"] == artifact["evidence_sha256"]
    assert stale["window_end"] == result["window_end"]
