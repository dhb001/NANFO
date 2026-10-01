"""Verifier isolation/failure checks and actual measured-selector lifespan smoke.

These are offline tests. The opt-in script separately records actual live services.
"""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from scripts.verify_measured_twin import (
    AcceptanceFailure,
    DockerRedis,
    LocalLab,
    LocalSNMP,
    digest,
    environment,
    geometry_payload,
    main,
    migration_command,
    private_file,
    require,
    spatial_payload,
    verify_measured_payloads,
)


def test_requires_explicit_live_authorization():
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2


def test_current_schema_uses_complete_repository_chain():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from app.core.schema_version import CURRENT_SCHEMA

    from scripts.verify_measured_twin import ACCEPTANCE_SCHEMA, BACKEND

    config = Config()
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert ACCEPTANCE_SCHEMA == "0027"
    # ADR-028 migration 0030 is the single repository head (CURRENT_SCHEMA must follow it;
    # that equality is enforced by deploy/tests/test_schema_contract.py and readiness).
    assert scripts.get_heads() == ["0030"]
    assert scripts.get_revision("0030").down_revision == "0029"
    # The private experimental migration extends, rather than retargets, release0027, and
    # every current revision sits on the same contiguous chain.
    for top, target in ((30, "heads"), (int(CURRENT_SCHEMA), CURRENT_SCHEMA)):
        assert [rev.revision for rev in scripts.walk_revisions("base", target)] == [
            f"{revision:04d}" for revision in range(top, 0, -1)
        ]
    assert scripts.get_revision("0029").down_revision == "0028"
    assert [rev.revision for rev in scripts.walk_revisions("base", ACCEPTANCE_SCHEMA)] == [
        f"{revision:04d}" for revision in range(27, 0, -1)
    ]
    assert "'alembic'" in migration_command() and "command.upgrade(c, '0027')" in migration_command()
    assert "migration-0021" not in migration_command()


@pytest.mark.parametrize("image", ["redis:7-alpine", "sha256:1234", "127.0.0.1:6379", ""])
def test_docker_rejects_tags_and_external_addresses(tmp_path, image):
    with pytest.raises(AcceptanceFailure, match="exact_redis_image_id_required"):
        DockerRedis(LocalLab(tmp_path, None), image)


def test_docker_ownership_mismatch_prevents_stop(tmp_path, monkeypatch):
    docker = DockerRedis(LocalLab(tmp_path, None), "sha256:" + "a" * 64)
    docker.container_id = "b" * 64
    commands = []

    def run(*args, **kwargs):
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps([{
            "Id": docker.container_id, "Config": {"Labels": {docker.LABEL: "foreign-owner"}},
        }]))

    monkeypatch.setattr(docker, "docker", run)
    with pytest.raises(AcceptanceFailure, match="identity_mismatch"):
        docker.stop()
    assert commands == [("container", "inspect", docker.container_id)]


def test_docker_configuration_has_no_secrets_in_commands_or_shared_mounts(tmp_path, monkeypatch):
    lab = LocalLab(tmp_path, None, "sha256:" + "a" * 64)
    docker = lab.docker_redis
    commands = []
    record = {"Id": "b" * 64, "Image": docker.image_id, "Config": {"Labels": {docker.LABEL: docker.owner}},
              "Mounts": [{"Name": docker.volume}], "State": {"Running": True, "ExitCode": 0},
              "HostConfig": {"PortBindings": {
                  "6379/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(lab.redis_port)}]}}}

    def run(*args, **kwargs):
        commands.append(args)
        if args[:2] == ("image", "inspect"):
            output = json.dumps([{"Id": docker.image_id, "Os": "linux"}])
        elif args[:2] == ("container", "inspect"):
            output = json.dumps([record])
        elif args[0] == "create":
            output = "b" * 64
        else:
            output = ""
        return subprocess.CompletedProcess(args, 0, output)

    monkeypatch.setattr(docker, "docker", run)
    monkeypatch.setattr("scripts.verify_measured_twin.port_free", lambda _: False)
    probe = Mock()
    probe.__enter__ = Mock(return_value=probe)
    probe.__exit__ = Mock(return_value=False)
    probe.ping.return_value = True
    monkeypatch.setattr("redis.Redis", Mock(return_value=probe))
    docker.start()
    created = next(args for args in commands if args[0] == "create")
    assert "--pull=never" in created and "--read-only" in created
    assert created[created.index("--publish") + 1] == f"127.0.0.1:{lab.redis_port}:6379"
    assert created[created.index("--mount") + 1] == f"type=volume,source={docker.volume},target=/data"
    assert lab.env["REDIS_PASSWORD"] not in repr(commands) + repr(docker.env) + repr(docker.evidence())
    assert "docker.sock" not in repr(commands)
    assert created[created.index("--cap-add") + 1] == "DAC_OVERRIDE"
    probe.ping.assert_called_once()
    assert (tmp_path / "redis-container.conf").stat().st_mode & 0o777 == 0o600


def test_docker_cleanup_removes_only_exact_owned_resources(tmp_path, monkeypatch):
    lab = LocalLab(tmp_path, None, "sha256:" + "a" * 64)
    docker = lab.docker_redis
    docker.container_id = "b" * 64
    docker.volume_created = True
    monkeypatch.setattr(docker, "stop", Mock(return_value=True))
    commands = []

    def run(*args, check=True):
        commands.append(args)
        output = json.dumps([{"Labels": {docker.LABEL: docker.owner}}])
        return subprocess.CompletedProcess(args, 0 if check else 1, output)

    monkeypatch.setattr(docker, "docker", run)
    assert all(docker.cleanup().values())
    assert ("rm", docker.container_id) in commands
    assert ("volume", "rm", docker.volume) in commands
    assert all("prune" not in args and "--force" not in args and "-f" not in args for args in commands)


def test_private_credentials_and_environment_do_not_use_shared_stores(tmp_path):
    lab = LocalLab(tmp_path, None)
    assert lab.pg_port != lab.redis_port
    assert min(lab.pg_port, lab.redis_port) > 1024
    assert lab.env["POSTGRES_HOST"] == lab.env["REDIS_HOST"] == "127.0.0.1"
    assert lab.env["POSTGRES_PASSWORD"] != os.environ["POSTGRES_PASSWORD"]
    assert lab.env["REDIS_PASSWORD"] != os.environ["REDIS_PASSWORD"]
    assert lab.env["JWT_SECRET_KEY"] != os.environ["JWT_SECRET_KEY"]
    assert lab.env["NETWORK_ASSET_ROOT"] == str(tmp_path / "network-assets")
    assert lab.asset_root.stat().st_mode & 0o777 == 0o700
    path = tmp_path / "secret"
    private_file(path, lab.env["REDIS_PASSWORD"])
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        private_file(path, "replacement")
    old = dict(os.environ)
    with pytest.raises(RuntimeError), environment(lab.env):
        assert os.environ["REDIS_PORT"] == str(lab.redis_port)
        raise RuntimeError
    assert dict(os.environ) == old


def test_cleanup_owns_only_allocated_tree_and_exact_child_handles(tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    sentinel = unrelated / "keep"
    sentinel.write_text("keep")
    owned = tmp_path / "owned"
    owned.mkdir()
    lab = LocalLab(owned, None)
    lab.pg = Mock()
    lab.pg.poll.side_effect = [None, 0]
    lab.redis = Mock()
    lab.redis.poll.side_effect = [None, 0]
    result = lab.cleanup()
    assert result["children_reaped"] and result["private_tree_removed"]
    lab.pg.terminate.assert_called_once()
    lab.redis.terminate.assert_called_once()
    lab.pg.wait.assert_called_once_with(timeout=15)
    assert sentinel.read_text() == "keep"


def test_cleanup_escalation_reaps_but_does_not_claim_graceful():
    child = Mock()
    child.poll.return_value = None
    child.wait.side_effect = [subprocess.TimeoutExpired("owned", 15), -9]
    assert LocalLab.stop(child) is False
    child.kill.assert_called_once()
    assert child.wait.call_count == 2


def test_fixed_code_failures_and_canonical_hash():
    with pytest.raises(AcceptanceFailure, match="^check_failed$"):
        require(False, "check_failed")
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    assert digest({"a": 1}) != digest({"a": 2})
    from app.modules.network.spatial_schemas import ReplaceSpatialSceneRequest

    req = ReplaceSpatialSceneRequest.model_validate(spatial_payload("00000000-0000-4000-8000-000000000001"))
    assert req.scene.objects[0].provenance.source == "acceptance-fixture"


def test_generated_geometry_preserves_unknown_material_and_legacy_device_shape():
    from app.modules.network.spatial_schemas import ReplaceSpatialSceneRequest

    payload = geometry_payload("00000000-0000-4000-8000-000000000001")
    validated = ReplaceSpatialSceneRequest.model_validate(payload).model_dump(mode="json")
    assert validated == payload
    assert validated["scene"]["objects"][3]["geometry"]["material"]["attenuation_db"] is None
    assert "geometry" not in validated["scene"]["objects"][4]


def test_measured_evidence_rejects_synthetic_or_incorrect_rate():
    from copy import deepcopy

    tags = {"synthetic": False, "protocol": "SNMPv3", "security_level": "authPriv", "rate_quality": "measured"}
    raw = [{"source": "measured_snmp", "metric": "port_rx_bytes", "observed_at": str(i),
            "tags": {**tags, "counter_decimal": str(100 + i * 10)}} for i in range(3)]
    rate = {"source": "measured_snmp", "metric": "port_rx_bps", "value": 40.0,
            "tags": {**tags, "direction": "rx", "rx_counter_start_decimal": "100",
                     "rx_counter_end_decimal": "110", "interval_seconds": 2.0}}
    assert verify_measured_payloads([*raw, rate])["rx_counter_growth"] == 20
    changed = deepcopy(rate)
    changed["value"] = 41
    with pytest.raises(AcceptanceFailure, match="rate_reconstruction"):
        verify_measured_payloads([*raw, changed])
    changed = deepcopy(raw)
    changed[0]["tags"]["synthetic"] = True
    with pytest.raises(AcceptanceFailure, match="provenance"):
        verify_measured_payloads(changed)


async def test_snmp_agent_is_private_readonly_and_no_credential_argv(tmp_path, monkeypatch):
    import scripts.verify_measured_twin as verifier

    agent = LocalSNMP(LocalLab(tmp_path, None))
    child = Mock(pid=123456)
    child.poll.return_value = None
    spawn = Mock(return_value=child)
    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(verifier.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(verifier, "owned_udp_addresses", lambda _: [
        {"family": "udp", "local": f"0100007F:{agent.port:04X}"}])
    original = Path.read_bytes

    def proc_bytes(path):
        return b"private-agent" if str(path).startswith("/proc/123456/") else original(path)

    monkeypatch.setattr(Path, "read_bytes", proc_bytes)
    await agent.start()
    args, kwargs = spawn.call_args
    assert args[0][:3] == ["/usr/bin/snmpd", "-f", "-C"]
    assert kwargs["umask"] == 0o077
    assert kwargs["env"]["SNMP_PERSISTENT_DIR"] == str(agent.root / "state")
    assert all(secret not in repr(spawn.call_args) for secret in agent.credentials.values())
    config = agent.root / "config/snmpd.conf"
    assert config.stat().st_mode & 0o777 == 0o600
    assert "rouser " in config.read_text() and "rwuser " not in config.read_text()
    assert f"agentaddress udp:127.0.0.1:{agent.port}" in config.read_text()


def test_campaign_failure_retains_safe_summary_and_cleans(tmp_path, monkeypatch, capsys):
    import scripts.verify_measured_twin as verifier

    original_mkdtemp = verifier.tempfile.mkdtemp

    def allocated(*, prefix, dir):
        return original_mkdtemp(prefix=prefix, dir=tmp_path if str(dir) == "/tmp/opencode" else dir)

    monkeypatch.setattr(verifier.tempfile, "mkdtemp", allocated)
    monkeypatch.setattr(verifier.shutil, "which", lambda name: None if name == "redis-server" else "/installed/" + name)
    monkeypatch.setattr(LocalLab, "start_postgres", lambda self: None)
    monkeypatch.setattr(verifier, "command", lambda *args, **kwargs: 0)
    monkeypatch.setattr(verifier, "source_hashes", lambda: {"source.py": "a" * 64})

    async def fail(lab, result):
        raise RuntimeError("credential-canary-postgres://password@host")

    monkeypatch.setattr(verifier, "exercise", fail)
    assert main(["--live"]) == 2
    output = capsys.readouterr().out
    summary = json.loads(output)
    evidence = Path(summary["evidence"])
    stored = evidence.read_text()
    assert "credential-canary" not in stored + output
    result = json.loads(stored)
    assert result["failure"] == "RuntimeError"
    assert result["status"] == "partial" and result["cleanup"]["private_tree_removed"]
    assert result["topology"] == "unavailable_not_exercised"
    assert all(status == "blocked" for status in result["cases"].values())
    import hashlib

    assert summary["sha256"] == hashlib.sha256(stored.encode()).hexdigest()


@pytest.fixture
def startup(monkeypatch, fake_redis):
    import app.main as main_module
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={
        "EXECUTION_MODE": "emulation", "TELEMETRY_RUNTIME_ADAPTER_MODE": " measured_snmp ",
        "TELEMETRY_MEASURED_SNMP_BINDING_PATH": Path("/private/binding.json"),
        "TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH": Path("/private/credentials.json"),
        "TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS": 1.0,
    })
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    for name in ("init_redis", "close_redis", "init_neo4j", "close_neo4j"):
        monkeypatch.setattr(main_module, name, AsyncMock())
    monkeypatch.setattr(main_module, "get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(main_module, "_run_topology_workspace_backfill", AsyncMock(return_value=0))
    lease = AsyncMock()
    lease.__aenter__.return_value = Mock(healthy=True)
    monkeypatch.setattr(main_module, "ApiRealtimeLease", Mock(return_value=lease))
    # Real Redis group creation/consumption semantics have their own live lane;
    # these consumers block until cancellation so lifespan cleanup is observable.
    async def consumer(**kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(main_module, "run_consumer_loop", consumer)
    legacy = Mock(side_effect=AssertionError("measured selection fell through to legacy adapter"))
    generic = Mock(side_effect=AssertionError("measured action used generic authority-free wrapper"))
    monkeypatch.setattr(main_module, "build_production_runtime_adapter", legacy)
    monkeypatch.setattr(main_module, "build_runtime_poll_action", generic)
    return main_module, settings, fake_redis, legacy, generic


async def test_actual_lifespan_selects_measured_helper_polls_and_stops(startup, monkeypatch):
    module, settings, redis, legacy, generic = startup
    import app.modules.telemetry.snmp_composition as composition

    polled = asyncio.Event()
    async def action():
        polled.set()

    build = AsyncMock(return_value=action)
    monkeypatch.setattr(composition, "build_measured_snmp_poll_action", build)
    actual_start = module.TelemetryCollectorRunner.start_runtime_loop
    captured = {}

    async def record_start(self, **kwargs):
        captured.update(kwargs)
        await actual_start(self, **kwargs)

    monkeypatch.setattr(module.TelemetryCollectorRunner, "start_runtime_loop", record_start)
    async with module.app.router.lifespan_context(module.app):
        await asyncio.wait_for(polled.wait(), 2)
        collector = module.app.state.telemetry_collector
        assert collector.running and collector.runtime_healthy
        build.assert_awaited_once_with(settings=settings, session_factory=module.AsyncSessionLocal,
                                       redis=redis, ingestion_service=collector._ingestion_service)
        assert captured["poll_action"] is action
        assert captured["interval_seconds"] == 1.0
        assert captured["poll_max_attempts"] == module._TELEMETRY_COLLECTOR_RUNTIME_POLL_MAX_ATTEMPTS
        tasks = list(module.app.state.consumer_tasks)
    assert not collector.running and collector._runtime_loop_task is None
    assert all(task.done() for task in tasks)
    legacy.assert_not_called()
    generic.assert_not_called()
    module.close_redis.assert_awaited_once()
    module.close_neo4j.assert_awaited_once()


@pytest.mark.parametrize("error", [RuntimeError("unavailable"), ValueError("invalid_binding")])
async def test_actual_lifespan_measured_build_failure_stops_without_fallback(startup, monkeypatch, error):
    module, _, _, legacy, generic = startup
    import app.modules.telemetry.snmp_composition as composition

    monkeypatch.setattr(composition, "build_measured_snmp_poll_action", AsyncMock(side_effect=error))
    actual_stop = module.TelemetryCollectorRunner.stop
    stopped = []

    async def record_stop(self):
        await actual_stop(self)
        stopped.append(self)

    monkeypatch.setattr(module.TelemetryCollectorRunner, "stop", record_stop)
    async with module.app.router.lifespan_context(module.app):
        assert module.app.state.telemetry_collector is None
        assert len(stopped) == 1 and not stopped[0].running
        assert stopped[0]._runtime_loop_task is None
    legacy.assert_not_called()
    generic.assert_not_called()
