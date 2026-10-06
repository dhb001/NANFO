"""Source-only ADR023 deployment integration and fail-closed operator gates."""

import asyncio
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from deploy import adr023_checkpoint, backup_restore, check_fleet_health, manage, verify

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "backend"))


def test_archive_volume_is_protected_persistent_supervised_and_operator_writable():
    config = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text())
    services = config["services"]
    assert "telemetry_archive" in manage.VOLUMES
    assert "telemetry_archive:/volumes/telemetry_archive" in services["volume-init"]["volumes"]
    assert "telemetry_archive:/var/lib/nanfo/telemetry-archive:ro" in services["maintenance"]["volumes"]
    # ADR-028: the retention loop is a core supervised service; the finite operator
    # wrapper (dry-run/restore/reconcile/acceptance fixtures) stays opt-in.
    operator = services["telemetry-retention-cli"]
    assert operator["profiles"] == ["retention"] and operator["restart"] == "no"
    assert "telemetry-retention-cli" not in manage.SERVICES
    assert operator["command"] == ["python", "/opt/nanfo/deploy/telemetry_retention.py"]
    assert operator["read_only"] and operator["user"] == "10001:10001"
    supervised = services["telemetry-retention"]
    assert "telemetry-retention" in manage.SERVICES and "profiles" not in supervised
    assert supervised["restart"] == "unless-stopped" and supervised["read_only"]
    writers = {name for name, svc in services.items()
               if "telemetry_archive:/var/lib/nanfo/telemetry-archive" in svc.get("volumes", [])}
    assert writers == {"telemetry-retention", "telemetry-retention-cli"}


@pytest.mark.parametrize("overlays", [
    [], ["distributed"], ["fleet"], ["live-ai"], ["autonomous-client"],
    ["distributed", "autonomous-client", "distributed-autonomous-client"],
    ["distributed", "fleet", "distributed-fleet"],
    ["distributed", "fleet", "distributed-fleet", "live-ai", "distributed-live-ai"],
    ["distributed", "fleet", "distributed-fleet", "live-ai", "distributed-live-ai",
     "autonomous-client", "distributed-autonomous-client"],
])
def test_resolved_compose_contract_without_daemon(overlays):
    if shutil.which("docker") is None:
        pytest.skip("Compose CLI unavailable; no daemon required")
    env = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    env.update(
        NANFO_PROJECT="nanfo-deploy-source-check", NANFO_STATE_DIR="/tmp/opencode/unprovisioned",
        NANFO_BACKEND_IMAGE="source-check:backend", NANFO_FRONTEND_IMAGE="source-check:frontend",
        NANFO_NEO4J_IMAGE="source-check:neo4j", NANFO_REDIS_IMAGE="source-check:redis",
        NANFO_FLEET_IMAGE="source-check:fleet", NANFO_FLEET_EGRESS_SUBNET="10.231.9.0/24",
        NANFO_AI_IMAGE="source-check:ai", NANFO_BOOTSTRAP_EMAIL="test@example.com",
        NANFO_LIVE_MODEL_REGISTRY_SHA256="a" * 64,
        NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256="b" * 64,
    )
    command = ["docker", "compose", "--env-file", "/dev/null", "-f", str(ROOT / "deploy/compose.yaml")]
    for overlay in overlays:
        command += ["-f", str(ROOT / f"deploy/compose.{overlay}.yaml")]
    config = json.loads(subprocess.run(
        [*command, "--profile", "*", "config", "--format", "json"], env=env,
        capture_output=True, text=True, check=True, timeout=15,
    ).stdout)
    services = config["services"]
    apis = [services["api"], *([services["api2"]] if "distributed" in overlays else [])]
    if "distributed" in overlays:
        assert all(api["environment"]["API_REALTIME_DISTRIBUTED"] == "true" for api in apis)
        assert apis[0]["volumes"] == apis[1]["volumes"]
        assert services["gateway"]["depends_on"]["api2"]["condition"] == "service_healthy"
        # ADR-028: the upstream definition is baked into the gateway image, not bind-mounted.
        assert services["gateway"]["environment"]["NANFO_GATEWAY_UPSTREAM"] == "distributed"
        assert not services["gateway"].get("configs")
    if "fleet" in overlays:
        assert all(api["environment"]["TELEMETRY_FLEET_ENABLED"] == "true" for api in apis)
        assert all(api["environment"]["TELEMETRY_RUNTIME_ADAPTER_MODE"] == "stub" for api in apis)
        fleet = services["fleet-worker"]
        assert fleet["build"]["target"] == "with-fleet"
        assert fleet["profiles"] == ["fleet"]
        assert set(fleet["networks"]) == {"private", "fleet_egress"}
        assert config["networks"]["fleet_egress"]["ipam"]["config"][0]["subnet"] == "10.231.9.0/24"
        assert not fleet.get("ports") and fleet["read_only"] and fleet["user"] == "10001:10001"
        assert fleet["healthcheck"]["test"][-1] == "/opt/nanfo/deploy/check_fleet_health.py"
        # The merged scratch mounts keep the inherited /tmp and /run/nanfo exactly once.
        tmpfs = sorted(entry.split(":", 1)[0] for entry in fleet["tmpfs"])
        assert tmpfs == ["/run/nanfo", "/run/nanfo-snmp", "/tmp"]
        assert fleet["environment"]["NANFO_SNMP_RUNTIME_DIR"] == "/run/nanfo-snmp"
        for mount in fleet["volumes"]:
            assert mount["read_only"]
            if mount["type"] == "bind":
                assert mount["bind"].get("create_host_path", False) is False
    if "live-ai" in overlays:
        for service in [*apis, services["autonomy-worker"]]:
            assert service["image"] == "source-check:ai"
            assert service["environment"]["NANFO_LIVE_MODEL_REGISTRY_SHA256"] == "a" * 64
            assert service["environment"]["NANFO_MODEL_PYTHON"] == "/opt/nanfo/ai-runtime/bin/python"
            assert all(mount["read_only"] for mount in service["volumes"] if mount["type"] == "bind")
    for name, service in services.items():
        enabled = "autonomous-client" in overlays and name in {"api", "api2", "autonomy-worker"}
        environment = service.get("environment", {})
        mounts = {mount["target"]: mount for mount in service.get("volumes", [])}
        if enabled:
            assert environment["NANFO_AUTONOMOUS_PROVIDER_CONFIG"] == "/var/lib/nanfo/autonomous-config/provider.json"
            assert environment["NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256"] == "b" * 64
            assert environment["EXECUTION_MODE"] == "demo"  # Overlay never enables actuation mode.
            assert service["user"] == "10001:10001" and service["read_only"]
            assert service["cap_drop"] == ["ALL"] and not service.get("cap_add")
            assert not service.get("privileged") and not service.get("pid") and not service.get("devices")
            assert not service.get("command") if name.startswith("api") else service["command"] == ["python", "scripts/run_autonomy_worker.py"]
            for suffix in ("config", "evidence", "source"):
                mount = mounts[f"/var/lib/nanfo/autonomous-{suffix}"]
                assert mount["type"] == "bind" and mount["read_only"]
                assert mount["bind"].get("create_host_path", False) is False
        else:
            assert "NANFO_AUTONOMOUS_PROVIDER_CONFIG" not in environment
            assert "NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256" not in environment
            assert not any(target.startswith("/var/lib/nanfo/autonomous-") for target in mounts)


def test_autonomous_overlay_requires_explicit_hash_and_adds_no_driver():
    overlay = yaml.safe_load((ROOT / "deploy/compose.autonomous-client.yaml").read_text())
    assert set(overlay["services"]) == {"api", "autonomy-worker"}
    for service in overlay["services"].values():
        assert set(service) == {"environment", "volumes"}
        assert ":?" in service["environment"]["NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256"]
    for name in ("compose.autonomous-client.yaml", "compose.distributed-autonomous-client.yaml"):
        assert verify.runtime_source("deploy/" + name)


@pytest.fixture
def fleet():
    now = datetime(2026, 9, 20, tzinfo=UTC)
    settings = SimpleNamespace(health_ttl_seconds=90, scan_seconds=1)
    manifest = SimpleNamespace(targets=[SimpleNamespace(device_id="device", interval_seconds=10, poll_timeout_seconds=25)])
    document = {"version": 1, "worker_id": "worker", "observed_at": now.isoformat(),
                "devices": [{"device_id": "device", "outcome": "published", "fresh": True,
                             "last_published_at": now.isoformat()}]}
    redis = SimpleNamespace(scan=AsyncMock(return_value=(0, ["nanfo:fleet:health:v1:worker"])), get=AsyncMock())
    return now, settings, manifest, document, redis


@pytest.mark.parametrize("fault", [None, "missing", "stale_worker", "stale_sample", "future", "failed", "empty", "malformed", "overflow", "scan_cap"])
def test_fleet_health_recomputes_freshness_and_bounds_existing_heartbeats(fleet, fault):
    now, settings, manifest, document, redis = fleet
    if fault == "missing":
        redis.scan.return_value = (0, [])
    elif fault == "stale_worker":
        document["observed_at"] = (now - timedelta(seconds=11)).isoformat()
    elif fault == "stale_sample":
        document["devices"][0]["last_published_at"] = (now - timedelta(seconds=37)).isoformat()
    elif fault == "future":
        document["observed_at"] = (now + timedelta(seconds=1)).isoformat()
    elif fault == "failed":
        document["devices"][0]["outcome"] = "collection_deferred"
    elif fault == "empty":
        document["devices"] = []
    elif fault == "scan_cap":
        redis.scan.return_value = (1, [])
    redis.get.return_value = "{" if fault == "malformed" else "x" * 262145 if fault == "overflow" else json.dumps(document)
    assert asyncio.run(check_fleet_health.heartbeat_check(redis, manifest, settings, now=now)) is (fault is None)
    assert redis.scan.await_count <= 16


def test_archive_checkpoint_validates_bytes_scope_tombstones_and_pins(backend, tmp_path):
    from app.modules.telemetry.archive import TelemetryArchiveStore

    tmp_path.chmod(0o700)
    body = json.dumps({"record_id": "record", "event_id": "event", "workspace_id": "workspace"}).encode()
    store = TelemetryArchiveStore(tmp_path)
    digest = store.write(body)
    receipt = {"record_id": "record", "event_id": "event", "workspace_id": "workspace", "sha256": digest, "size_bytes": len(body)}
    tables = [[receipt], [{"event_id": "event"}], [{"reference_id": "ref"}], [], []]

    def database():
        return SimpleNamespace(execute=AsyncMock(side_effect=[Mock(scalars=lambda rows=rows: Mock(all=lambda: rows)) for rows in tables]))

    result = asyncio.run(adr023_checkpoint.telemetry_archive_checkpoint(database(), root=tmp_path))
    assert result["telemetry_archive_receipts"]["verified_bytes"] == len(body)
    assert result["telemetry_event_tombstones"]["rows"] == 1
    tables[1].append({"event_id": "second"})
    assert asyncio.run(adr023_checkpoint.telemetry_archive_checkpoint(database(), root=tmp_path)) != result
    receipt["workspace_id"] = "foreign"
    with pytest.raises(ValueError, match="scope"):
        asyncio.run(adr023_checkpoint.telemetry_archive_checkpoint(database(), root=tmp_path))
    receipt["workspace_id"] = "workspace"
    (tmp_path / digest).write_bytes(b"x" * len(body))
    with pytest.raises(ValueError, match="checksum"):
        asyncio.run(adr023_checkpoint.telemetry_archive_checkpoint(database(), root=tmp_path))
    with pytest.raises(ValueError, match="cap"):
        asyncio.run(adr023_checkpoint.telemetry_archive_checkpoint(database(), root=tmp_path, max_rows=0))


@pytest.mark.parametrize("count", [0, 1, 2])
def test_maintenance_refuses_any_unreleased_execution_including_verified(backend, count):
    db = SimpleNamespace(scalar=AsyncMock(return_value=count))
    result = asyncio.run(adr023_checkpoint.autonomous_execution_checkpoint(db))
    assert result == {"safe": count == 0, "unreleased_executions": count}
    assert "released = false" in str(db.scalar.call_args.args[0])


@pytest.mark.parametrize("fault", [None, "leader", "singleton", "local_consumer", "local_collector", "stale_subscription", "delegated_dependency"])
def test_verifier_accepts_only_correct_follower_delegation(fault):
    data = {"ready": True, "checks": {"postgres": "ok", "realtime_subscription": "ok", "api_consumers": "delegated"},
            "realtime": {"mode": "distributed", "role": "follower", "local_consumer_count": 0, "local_collector": False}}
    if fault == "leader":
        data["realtime"]["role"] = "leader"
    if fault == "singleton":
        data["realtime"]["mode"] = "singleton"
    if fault == "local_consumer":
        data["realtime"]["local_consumer_count"] = 1
    if fault == "local_collector":
        data["realtime"]["local_collector"] = True
    if fault == "stale_subscription":
        data["checks"]["realtime_subscription"] = "unavailable"
    if fault == "delegated_dependency":
        data["checks"]["postgres"] = "delegated"
    # ADR-028: readiness is probed inside the API container; the gateway 404s /ready.
    stack = Mock(config={"services": {"api": {}}})
    stack.compose.return_value = json.dumps(
        {"status": 200, "body": json.dumps({"success": True, "data": data})}).encode()
    if fault:
        with pytest.raises(verify.VerificationError):
            verify.stack_ready(stack)
    else:
        assert verify.stack_ready(stack)


def test_new_deployment_inputs_participate_in_source_quiet_gate():
    for name in ("adr023_checkpoint.py", "check_fleet_health.py", "telemetry_retention.py", "compose.distributed.yaml",
                 "compose.fleet.yaml", "compose.live-ai.yaml", "nginx-upstream.conf", "nginx-distributed-upstream.conf", "fleet.sources"):
        assert verify.runtime_source("deploy/" + name)
    assert verify.runtime_source("frontend/src/shared/state/auth-store.ts")
    assert not verify.runtime_source("deploy/state/credentials.json")


def test_current_archive_requires_bytes_and_execution_proof_but_preserves_history():
    backup_restore.require_current_archive_checkpoint({"schema": "0024"}, ["reports"])
    with pytest.raises(backup_restore.OperationError):
        backup_restore.require_current_archive_checkpoint({"schema": "0027"}, ["telemetry_archive"])
    checkpoint = {"schema": "0027", "autonomous_execution": {"safe": True, "unreleased_executions": 0},
                  "telemetry_archive": {name: {} for name in (
                      "telemetry_archive_receipts", "telemetry_event_tombstones", "telemetry_evidence_pins",
                      "telemetry_reference_coverage", "telemetry_reference_reconciliation")}}
    backup_restore.require_current_archive_checkpoint(checkpoint, ["telemetry_archive"])
    with pytest.raises(backup_restore.OperationError):
        backup_restore.require_current_archive_checkpoint(checkpoint, [])
    checkpoint["autonomous_execution"]["unreleased_executions"] = 1
    with pytest.raises(backup_restore.OperationError):
        backup_restore.require_current_archive_checkpoint(checkpoint, ["telemetry_archive"])


def test_archive_export_preserves_previous_0024_matrix():
    from deploy.release_manifest import project_result

    # Existing evidence stays exportable after the live migration gate advances.
    value = {"cases": {"migration_0024": {"status": "passed"}}, "core_passed": True}
    assert json.loads(project_result(json.dumps(value).encode()))["cases"]["migration_0024"]["status"] == "passed"


@pytest.mark.parametrize("operation", ["apply", "restore", "dry-run", "reconcile"])
def test_retention_wrapper_uses_existing_bounded_cli_and_secret_dsn(backend, monkeypatch, capsys, operation):
    from app.core import config

    from deploy import telemetry_retention
    from scripts import telemetry_retention as owner

    args = SimpleNamespace(operation=operation, archive_root=None, timeout_seconds=30)
    monkeypatch.setattr(owner, "parser", lambda: SimpleNamespace(parse_args=lambda: args))
    run = AsyncMock(return_value={"bounded": True})
    monkeypatch.setattr(owner, "run", run)
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(POSTGRES_DSN="test-only-secret-dsn"))
    monkeypatch.setenv("TELEMETRY_RETENTION_DSN", "old")
    assert telemetry_retention.main() == 0
    assert os.environ["TELEMETRY_RETENTION_DSN"] == "test-only-secret-dsn"
    assert args.archive_root == ("/var/lib/nanfo/telemetry-archive" if operation in {"apply", "restore"} else None)
    run.assert_awaited_once_with(args)
    run.reset_mock()
    args.timeout_seconds = 301
    assert telemetry_retention.main() == 1
    run.assert_not_awaited()
    args.timeout_seconds = 30
    run.side_effect = ValueError("test-only-secret-dsn")
    assert telemetry_retention.main() == 1
    assert "test-only-secret-dsn" not in capsys.readouterr().out
