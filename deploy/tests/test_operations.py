"""Isolated ADR020 operator safety regressions; no Docker or live stores."""

import asyncio
import copy
import hashlib
import hmac
import io
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from deploy import backup_restore
from deploy.backup_restore import (
    Deployment,
    OperationError,
    backup,
    canonical,
    decrypt_stream,
    encrypt_stream,
    file_hash,
    load_manifest,
    protected_file,
    restore,
    validate_tar,
    write_json,
)
from deploy.diagnostics import diagnose

GRAPH = {
    "nodes": 4,
    "relationships": 2,
    "revisions": 2,
    "revision_tombstones": 1,
    "node_labels": [
        {"identity": "Device", "count": 2},
        {"identity": "DeviceEventRevision", "count": 2},
    ],
    "relationship_types": [{"identity": "CONNECTED_TO", "count": 2}],
    "revisions_sha256": "a" * 64,
}


def test_validated_unbuffered_archive_descriptor_starts_at_header(tmp_path):
    data = archive(("file", tarfile.REGTYPE, "")).getvalue()
    with tempfile.TemporaryFile(dir=tmp_path, buffering=0) as plain:
        plain.write(data)
        plain.seek(0)
        validate_tar(plain, max_bytes=10**6)
        result = subprocess.run(
            ["tar", "-tf", "-"], stdin=plain, capture_output=True, check=True
        )
    assert result.stdout == b"file\n"


def test_restore_dependency_wait_only_retries_typed_unavailable(monkeypatch):
    dep = object.__new__(Deployment)
    dep._maintenance_result = Mock(
        side_effect=[
            {"safe": False, "dependencies": {"neo4j": "unavailable", "schema": "ok"}},
            {"safe": True, "schema": "0021"},
        ]
    )
    monkeypatch.setattr(backup_restore.time, "sleep", Mock())
    assert dep.maintenance("checkpoint", wait_dependencies=True)["schema"] == "0021"
    assert dep._maintenance_result.call_count == 2
    dep._maintenance_result = Mock(
        return_value={"safe": False, "intent": {"safe": False}}
    )
    with pytest.raises(OperationError):
        dep.maintenance("checkpoint", wait_dependencies=True)
    assert dep._maintenance_result.call_count == 1


def test_failed_process_cannot_claim_safe_checkpoint():
    dep = object.__new__(Deployment)
    dep.runner = Mock(
        return_value=SimpleNamespace(
            returncode=1, stdout=b'{"safe":true}', stderr=b"secret-canary"
        )
    )
    with pytest.raises(OperationError):
        dep.run("command", allow_failure=True)


def archive(*entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as output:
        for name, kind, link in entries:
            member = tarfile.TarInfo(name)
            member.mode = 0o600
            member.type = kind
            member.linkname = link
            if kind == tarfile.REGTYPE:
                member.size = 4
                output.addfile(member, io.BytesIO(b"data"))
            else:
                output.addfile(member)
    stream.seek(0)
    return stream


def encrypted(data, *, key=b"x" * 32, aad=b"identity"):
    output = io.BytesIO()
    encrypt_stream(io.BytesIO(data), output, key, aad, max_bytes=10**7)
    output.seek(0)
    return output


def test_streaming_authenticated_encryption_roundtrip():
    data = b"sensitive" * 300_000
    source = encrypted(data)
    target = io.BytesIO()
    decrypt_stream(source, target, b"x" * 32, b"identity", max_bytes=10**7)
    assert target.read() == data
    assert b"sensitive" not in source.getvalue()


@pytest.mark.parametrize("tamper", ["ciphertext", "tag", "key", "identity"])
def test_encryption_tamper_never_authenticates(tamper):
    blob = bytearray(encrypted(b"sensitive").getvalue())
    if tamper == "ciphertext":
        blob[-20] ^= 1
    if tamper == "tag":
        blob[-1] ^= 1
    with pytest.raises(OperationError, match="authentication failed"):
        decrypt_stream(
            io.BytesIO(blob),
            io.BytesIO(),
            b"y" * 32 if tamper == "key" else b"x" * 32,
            b"wrong" if tamper == "identity" else b"identity",
            max_bytes=1024,
        )


def test_encryption_caps():
    with pytest.raises(OperationError, match="cap"):
        encrypt_stream(
            io.BytesIO(b"012345"), io.BytesIO(), b"x" * 32, b"a", max_bytes=5
        )
    with pytest.raises(OperationError, match="cap"):
        decrypt_stream(
            encrypted(b"012345"), io.BytesIO(), b"x" * 32, b"identity", max_bytes=5
        )


@pytest.mark.parametrize(
    "entries",
    [
        [("../escape", tarfile.REGTYPE, "")],
        [("/escape", tarfile.REGTYPE, "")],
        [("a\\escape", tarfile.REGTYPE, "")],
        [("link", tarfile.SYMTYPE, "/outside")],
        [("link", tarfile.SYMTYPE, "../outside")],
        [("link", tarfile.SYMTYPE, "safe"), ("link/child", tarfile.REGTYPE, "")],
        [("link/child", tarfile.REGTYPE, ""), ("link", tarfile.SYMTYPE, "safe")],
        [("same", tarfile.REGTYPE, ""), ("./same", tarfile.REGTYPE, "")],
        [("fifo", tarfile.FIFOTYPE, "")],
        [("device", tarfile.CHRTYPE, "")],
        [("hard", tarfile.LNKTYPE, "missing")],
    ],
)
def test_archive_escape_and_special_entries_rejected(entries):
    with pytest.raises(OperationError):
        validate_tar(archive(*entries), max_bytes=10**6)


def test_archive_regular_and_internal_links_supported():
    value = archive(
        (".", tarfile.DIRTYPE, ""),
        ("file", tarfile.REGTYPE, ""),
        ("soft", tarfile.SYMTYPE, "file"),
        ("hard", tarfile.LNKTYPE, "file"),
    )
    assert validate_tar(value, max_bytes=100) == {"entries": 4, "bytes": 4}
    assert value.tell() == 0


def test_archive_caps():
    with pytest.raises(OperationError, match="byte cap"):
        validate_tar(archive(("file", tarfile.REGTYPE, "")), max_bytes=3)
    with pytest.raises(OperationError, match="entry cap"):
        validate_tar(
            archive(("file", tarfile.REGTYPE, "")), max_bytes=10, max_entries=0
        )


@pytest.mark.parametrize(
    "project", ["nanfo", "nanfo_test", "other", "nanfo-deploy-", "nanfo-deploy-a/../b"]
)
def test_project_requires_explicit_owned_prefix(project):
    runner = Mock()
    with pytest.raises(OperationError):
        Deployment(project, ["compose.yml"], "env", runner=runner)
    runner.assert_not_called()


def test_backup_config_includes_init_profile_without_activating_lifecycle():
    runner = Mock(
        return_value=SimpleNamespace(
            returncode=0,
            stdout=canonical(
                {
                    "services": {
                        name: {}
                        for name in ("api", "postgres", "redis", "neo4j", "initialize")
                    },
                    "volumes": {"init_secrets": {}},
                }
            ),
        )
    )
    deployment = Deployment("nanfo-deploy-test", ["compose.yml"], "env", runner=runner)
    assert "--profile" in runner.call_args.args[0]
    assert "init_secrets" in deployment.config["volumes"]
    deployment.compose("stop", "api")
    assert "--profile" not in runner.call_args.args[0]


def test_secret_key_permissions_and_symlinks(tmp_path):
    key = tmp_path / "key"
    key.write_bytes(b"x" * 32)
    key.chmod(0o644)
    with pytest.raises(OperationError):
        protected_file(key, size=32)
    key.chmod(0o600)
    with protected_file(key, size=32) as source:
        assert source.read() == b"x" * 32
    link = tmp_path / "link"
    link.symlink_to(key)
    with pytest.raises(OSError):
        protected_file(link, size=32)
    with pytest.raises(OperationError):
        protected_file(key, size=31)


def fake_deployment():
    dep = Mock(spec=Deployment)
    dep.project = "nanfo-deploy-source"
    dep.config = {
        "volumes": {"postgresdata": {}},
        "services": {
            name: {
                "volumes": [
                    {"type": "volume", "source": "postgresdata", "target": "/data"}
                ]
            }
            for name in [
                "postgres",
                "redis",
                "neo4j",
                "api",
                "report-worker",
                "network-outbox-worker",
                "lab",
            ]
        },
    }
    dep.images.return_value = {
        name: {"id": "sha256:" + "a" * 64, "os": "linux", "architecture": "amd64"}
        for name in dep.config["services"]
    }
    dep.containers.return_value = [
        {
            "Image": "sha256:" + "a" * 64,
            "Config": {"Labels": {"com.docker.compose.service": "api"}},
        }
    ]
    dep.inventory.return_value = (
        {"postgresdata": "nanfo-deploy-source_postgresdata"},
        {},
    )
    dep.binds.return_value = {}
    dep.mount_contract.return_value = {}
    dep.volume_usage.return_value = {"bytes": 512, "entries": 1}
    dep.maintenance.return_value = {"safe": True, "schema": "0019", "neo4j_graph": copy.deepcopy(GRAPH)}
    return dep


def test_unresolved_execution_refuses_before_any_stop(tmp_path):
    tmp_path.chmod(0o700)
    dep = fake_deployment()
    dep.maintenance.side_effect = OperationError("Unresolved execution")
    with pytest.raises(OperationError):
        backup(dep, tmp_path, b"x" * 32, max_bytes=1000)
    dep.compose.assert_called_once_with("stop", "--timeout", "120", "gateway", "api")
    assert not list(tmp_path.iterdir())


def test_distributed_backup_closes_both_admissions_before_recovery_checkpoint(tmp_path):
    tmp_path.chmod(0o700)
    dep = fake_deployment()
    dep.config["services"]["api2"] = copy.deepcopy(dep.config["services"]["api"])
    dep.maintenance.side_effect = OperationError("Unreleased autonomous resource")
    with pytest.raises(OperationError):
        backup(dep, tmp_path, b"x" * 32, max_bytes=1000)
    dep.compose.assert_called_once_with("stop", "--timeout", "120", "gateway", "api", "api2")
    dep.maintenance.assert_called_once_with("quiesce")
    assert not list(tmp_path.iterdir())


def test_checkpoint_failure_leaves_recovery_stores_and_no_archive(tmp_path):
    tmp_path.chmod(0o700)
    dep = fake_deployment()
    dep.maintenance.side_effect = [{"safe": True}, OperationError("boundary changed")]
    with pytest.raises(OperationError):
        backup(dep, tmp_path, b"x" * 32, max_bytes=1000)
    assert dep.compose.call_count == 2
    stopped = dep.compose.call_args.args
    assert "api" in stopped and "lab" in stopped and "report-worker" in stopped
    assert "network-outbox-worker" in stopped
    assert "postgres" not in stopped
    assert not list(tmp_path.iterdir())


def make_manifest(tmp_path, *, corrupt_archive=False):
    tmp_path.chmod(0o700)
    key = b"x" * 32
    item = {"logical": "postgresdata", "file": "volume-0000.tar.gcm"}
    aad = canonical(
        {
            "project": "nanfo-deploy-source",
            "volume": item["logical"],
            "file": item["file"],
        }
    )
    data = archive(
        ("../escape" if corrupt_archive else "file", tarfile.REGTYPE, "")
    ).getvalue()
    path = tmp_path / item["file"]
    path.write_bytes(encrypted(data, key=key, aad=aad).getvalue())
    path.chmod(0o600)
    item["sha256"] = file_hash(path)
    manifest = {
        "format": 1,
        "complete": True,
        "project": "nanfo-deploy-source",
        "images": {},
        "external_fingerprints": {},
        "volumes": [item],
        "checkpoint": {"safe": True, "schema": "0019", "neo4j_graph": copy.deepcopy(GRAPH)},
    }
    write_json(tmp_path / "manifest.json", manifest)
    signature = tmp_path / "manifest.hmac"
    signature.write_text(hmac.new(key, canonical(manifest), hashlib.sha256).hexdigest())
    signature.chmod(0o600)
    return manifest, key


def test_manifest_integrity_and_archive_hash(tmp_path):
    manifest, key = make_manifest(tmp_path)
    assert load_manifest(tmp_path, key) == manifest
    (tmp_path / "volume-0000.tar.gcm").write_bytes(b"corrupt")
    with pytest.raises(OperationError, match="checksum"):
        load_manifest(tmp_path, key)


@pytest.mark.parametrize("schema", ["0019", "0021"])
def test_authenticated_archive_validation_preserves_historical_schema(tmp_path, schema):
    manifest, key = make_manifest(tmp_path)
    manifest["checkpoint"]["schema"] = schema
    (tmp_path / "manifest.json").write_bytes(canonical(manifest))
    (tmp_path / "manifest.hmac").write_text(
        hmac.new(key, canonical(manifest), hashlib.sha256).hexdigest()
    )
    assert load_manifest(tmp_path, key)["checkpoint"]["schema"] == schema


def test_manifest_tamper(tmp_path):
    _, key = make_manifest(tmp_path)
    (tmp_path / "manifest.json").write_text("{}")
    with pytest.raises(OperationError, match="authentication"):
        load_manifest(tmp_path, key)


@pytest.mark.parametrize("existing", ["containers", "volumes"])
def test_restore_rejects_existing_target(tmp_path, existing):
    _, key = make_manifest(tmp_path)
    dep = fake_deployment()
    dep.project = "nanfo-deploy-target"
    dep.containers.return_value = []
    dep.volumes.return_value = []
    getattr(dep, existing).return_value = ["existing"]
    with pytest.raises(OperationError, match="fresh"):
        restore(dep, tmp_path, key, max_bytes=10**6)
    dep.run.assert_not_called()
    dep.compose.assert_not_called()


def test_restore_validates_all_before_creating_volume(tmp_path):
    _, key = make_manifest(tmp_path, corrupt_archive=True)
    dep = fake_deployment()
    dep.project = "nanfo-deploy-target"
    dep.containers.return_value = dep.volumes.return_value = []
    dep.images.return_value = {}
    dep.external_fingerprints.return_value = {}
    dep.run.return_value = b""
    dep.volume_name.return_value = "nanfo-deploy-target_postgresdata"
    with pytest.raises(OperationError, match="Unsafe archive path"):
        restore(dep, tmp_path, key, max_bytes=10**6)
    assert all("create" not in call.args for call in dep.run.call_args_list)
    dep.compose.assert_not_called()


def test_helper_is_pinned_offline_and_readonly():
    dep = object.__new__(Deployment)
    dep.project = "nanfo-deploy-test"
    args = dep.helper_args(
        "sha256:" + "a" * 64, "nanfo-deploy-test_data", readonly=True
    )
    assert "none" in args and "--read-only" in args and "ALL" in args
    assert "type=volume,src=nanfo-deploy-test_data,dst=/volume,readonly" in args
    with pytest.raises(OperationError):
        dep.helper_args("alpine:latest", "data", readonly=True)


def test_diagnostics_never_emits_inspect_secrets():
    dep = fake_deployment()
    dep.containers.return_value = [
        {
            "Config": {
                "Env": ["PASSWORD=supersecret"],
                "Labels": {"com.docker.compose.service": "api"},
            },
            "State": {"Running": False, "Error": "supersecret"},
            "Image": "id",
        }
    ]
    result = diagnose(dep)
    assert "supersecret" not in json.dumps(result)
    dep.compose.assert_not_called()


@pytest.fixture
def backend_path(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "backend"))


def test_session_invalidation_preserves_streams_and_other_keys(backend_path):
    from app.modules.identity.operations import invalidate_restored_sessions

    redis = SimpleNamespace(
        scan=AsyncMock(side_effect=[(4, ["auth:session:a"]), (0, ["auth:session:b"])]),
        unlink=AsyncMock(return_value=1),
    )
    assert asyncio.run(invalidate_restored_sessions(redis)) == 2
    assert redis.unlink.call_args_list[0].args == ("auth:session:a",)
    assert all(
        call.kwargs["match"] == "auth:session:*" for call in redis.scan.call_args_list
    )


def test_session_invalidation_bounded_and_prefix_checked(backend_path):
    from app.modules.identity.operations import invalidate_restored_sessions

    redis = SimpleNamespace(
        scan=AsyncMock(return_value=(0, ["auth:session:a", "auth:session:b"])),
        unlink=AsyncMock(),
    )
    with pytest.raises(ValueError, match="cap"):
        asyncio.run(invalidate_restored_sessions(redis, max_keys=1))
    redis.unlink.assert_not_called()
    redis.scan.return_value = (0, ["durable.stream"])
    with pytest.raises(ValueError, match="Unexpected"):
        asyncio.run(invalidate_restored_sessions(redis))
    redis.unlink.assert_not_called()


def report_service(tmp_path):
    from app.modules.report.operations import ReportOperationsService

    store = SimpleNamespace(
        _directory=lambda: os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    )
    service = object.__new__(ReportOperationsService)
    service.store = store
    service.inventory = AsyncMock(
        return_value={
            "active_jobs": 0,
            "legacy_reports": 0,
            "registered_files": [],
            "verified_reports": 0,
        }
    )
    return service


def test_report_cleanup_dryrun_apply_pins_symlinks_grace(backend_path, tmp_path):
    service = report_service(tmp_path)
    orphan = (
        "00000000-0000-0000-0000-000000000001-00000000-0000-0000-0000-000000000002.csv"
    )
    pinned = orphan.replace("0002.csv", "0003.csv")
    link = orphan.replace("0002.csv", "0004.csv")
    for name in (orphan, pinned, "unknown.csv"):
        (tmp_path / name).write_bytes(b"report")
        (tmp_path / name).chmod(0o600)
    (tmp_path / link).symlink_to(tmp_path / orphan)
    service.inventory.return_value["registered_files"] = [pinned]
    now = (tmp_path / orphan).stat().st_ctime + 86401
    recent = asyncio.run(service.cleanup(now=now - 10))
    assert recent["candidates"] == 0
    dry = asyncio.run(service.cleanup(now=now))
    assert dry["candidates"] == 1 and dry["removed"] == 0
    assert (tmp_path / orphan).exists()
    result = asyncio.run(service.cleanup(now=now, apply=True))
    assert result["removed"] == 1
    assert (tmp_path / pinned).exists() and (tmp_path / "unknown.csv").exists()
    assert (tmp_path / link).is_symlink()


@pytest.mark.parametrize("blocker", ["active_jobs", "legacy_reports"])
def test_report_cleanup_refuses_uncertain_inventory(backend_path, tmp_path, blocker):
    service = report_service(tmp_path)
    service.inventory.return_value[blocker] = 1
    with pytest.raises(ValueError, match="prevent"):
        asyncio.run(service.cleanup(apply=True))


def test_report_cleanup_policy_and_scan_caps(backend_path, tmp_path):
    service = report_service(tmp_path)
    with pytest.raises(ValueError, match="Grace"):
        asyncio.run(service.cleanup(grace_seconds=1))
    (tmp_path / "anything").write_text("preserve")
    with pytest.raises(ValueError, match="cap"):
        asyncio.run(service.cleanup(apply=True, max_scan=0))
    assert (tmp_path / "anything").exists()


def test_owner_execution_and_override_gates_are_read_only(backend_path):
    from app.modules.autonomy.operations import maintenance_checkpoint as autonomy
    from app.modules.intent.operations import maintenance_checkpoint as intent

    db = SimpleNamespace(scalar=AsyncMock(return_value=1))
    assert asyncio.run(intent(db)) == {"safe": False, "unresolved_executions": 1}
    db.scalar.side_effect = [0, 1]
    assert asyncio.run(autonomy(db)) == {
        "safe": False,
        "active_controls": 0,
        "unresolved_overrides": 1,
    }


def test_external_bind_inventory_includes_models_and_binding(tmp_path):
    dep = object.__new__(Deployment)
    dep.project = "nanfo-deploy-test"
    models = tmp_path / "models"
    models.mkdir()
    dep.config = {
        "services": {
            "api": {
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(models),
                        "target": "/models",
                        "read_only": True,
                    }
                ]
            }
        },
        "volumes": {},
    }
    binds = dep.binds()
    assert len(binds) == 1
    assert next(iter(binds.values()))["references"] == ["api:/models"]
    assert dep.external_fingerprints(b"x" * 32) == {}
    dep.config["services"]["api"]["volumes"][0]["read_only"] = False
    with pytest.raises(OperationError):
        dep.binds()


def test_telemetry_assessment_never_deletes_and_is_bounded(backend_path):
    from app.modules.telemetry.operations import retention_assessment

    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [1, 2, 3]))
    )
    result = asyncio.run(retention_assessment(db, batch_size=2))
    assert result["deleted"] == 0 and result["status"] == "blocked"
    assert result["assessment_truncated"] and result["aged_records_at_least"] == 2
    assert "LIMIT" in str(db.scalars.call_args.args[0])


def test_stopped_store_requires_clean_exit():
    dep = object.__new__(Deployment)
    dep.containers = Mock(
        return_value=[
            {
                "Config": {"Labels": {"com.docker.compose.service": "postgres"}},
                "State": {"Running": False, "ExitCode": 137},
            }
        ]
    )
    with pytest.raises(OperationError, match="cleanly"):
        dep.assert_stopped()


def test_backup_requires_referenced_model_roots(tmp_path):
    tmp_path.chmod(0o700)
    dep = fake_deployment()
    dep.maintenance.return_value = {
        "safe": True,
        "model_references": {"diagnostic_records": 1},
    }
    with pytest.raises(OperationError, match="model references"):
        backup(dep, tmp_path, b"x" * 32, max_bytes=1000)
    assert dep.compose.call_count == 1


def test_maintenance_cli_uses_deployment_entrypoint():
    dep = object.__new__(Deployment)
    dep.config = {"services": {"api": {}}}
    dep.compose = Mock(return_value=b'{"safe": true}')
    assert dep.maintenance("checkpoint") == {"safe": True}
    args = dep.compose.call_args.args
    assert "--no-deps" in args and "/opt/nanfo/deploy/maintenance.py" in args
    dep.compose.return_value = b'{"safe": false}'
    with pytest.raises(OperationError, match="checkpoint refused"):
        dep.maintenance("checkpoint")


@pytest.mark.parametrize(
    "graph_change",
    [None, "nodes", "relationships", "revision_tombstones", "revisions_sha256"],
)
def test_cold_backup_complete_and_fresh_restore_lifecycle(
    tmp_path, monkeypatch, graph_change
):
    tmp_path.chmod(0o700)
    source = fake_deployment()
    source.run.return_value = b""
    source.helper_args.return_value = ["unused-helper"]
    process = SimpleNamespace(
        stdout=archive((".", tarfile.DIRTYPE, ""), ("data", tarfile.REGTYPE, "")),
        wait=Mock(return_value=0),
        poll=Mock(return_value=0),
    )
    monkeypatch.setattr(
        "deploy.backup_restore.subprocess.Popen", Mock(return_value=process)
    )
    key = b"x" * 32
    result = backup(source, tmp_path, key, max_bytes=10**6)
    assert result["status"] == "backed_up"
    assert source.compose.call_args_list[-1].args == (
        "stop",
        "--timeout",
        "120",
        "neo4j",
        "postgres",
        "redis",
    )
    manifest = load_manifest(tmp_path, key)
    assert len(manifest["volumes"]) == 1
    target = fake_deployment()
    target.project = "nanfo-deploy-target"
    target.containers.return_value = target.volumes.return_value = []
    target.external_fingerprints.return_value = {}
    restored_bytes = []

    def stream_into(args, reader):
        # Format 2 restore decrypts straight into the extraction helper's stdin.
        assert args == ["helper-restore"]
        with tarfile.open(fileobj=reader, mode="r|") as stream:
            for member in stream:
                if member.name == "data":
                    restored_bytes.append(stream.extractfile(member).read())
        reader.drain()
        return 0

    target.run.return_value = b""
    target.stream_into.side_effect = stream_into
    target.volume_name.return_value = "nanfo-deploy-target_postgresdata"
    target.helper_args.return_value = ["helper-restore"]
    if graph_change:
        target.maintenance.return_value["neo4j_graph"][graph_change] = 0
        with pytest.raises(OperationError, match="Neo4j checkpoint differs"):
            restore(target, tmp_path, key, max_bytes=10**6)
        target.maintenance.assert_called_once_with("checkpoint", wait_dependencies=True)
    else:
        result = restore(target, tmp_path, key, max_bytes=10**6)
        assert result["status"] == "restored_verified"
        assert [call.args for call in target.maintenance.call_args_list] == [
            ("checkpoint",),
            ("restore-verify",),
        ]
    assert restored_bytes == [b"data"]
    assert target.compose.call_count == 1
    assert target.compose.call_args.args == (
        "up",
        "-d",
        "--no-deps",
        "--wait",
        "--wait-timeout",
        "180",
        "neo4j",
        "postgres",
        "redis",
    )


def test_backup_rejects_unsafe_tar_before_manifest(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    source = fake_deployment()
    source.helper_args.return_value = ["unused-helper"]
    process = SimpleNamespace(
        stdout=archive(("../unsafe", tarfile.REGTYPE, "")),
        wait=Mock(return_value=0),
        poll=Mock(return_value=0),
    )
    monkeypatch.setattr(
        "deploy.backup_restore.subprocess.Popen", Mock(return_value=process)
    )
    with pytest.raises(OperationError, match="Unsafe archive path"):
        backup(source, tmp_path, b"x" * 32, max_bytes=10**6)
    assert not (tmp_path / "manifest.json").exists()


def mounted_deployment():
    dep = object.__new__(Deployment)
    dep.project = "nanfo-deploy-source"
    dep.config = {"services": {}, "volumes": {}}
    containers, volumes = [], []
    for service, destination in (
        ("postgres", "/var/lib/postgresql/data"),
        ("redis", "/data"),
        ("neo4j", "/data"),
        ("api", "/reports"),
    ):
        logical = service + "data"
        name = dep.project + "_" + logical
        dep.config["volumes"][logical] = {}
        dep.config["services"][service] = {
            "volumes": [
                {
                    "type": "volume",
                    "source": logical,
                    "target": destination,
                    "read_only": service == "api",
                }
            ]
        }
        volumes.append(
            {
                "Name": name,
                "Driver": "local",
                "Options": None,
                "Labels": {"com.docker.compose.volume": logical},
            }
        )
        containers.append(
            {
                "Config": {"Labels": {"com.docker.compose.service": service}},
                "Image": "sha256:" + "a" * 64,
                "Mounts": [
                    {
                        "Type": "volume",
                        "Name": name,
                        "Destination": destination,
                        "RW": service != "api",
                    }
                ],
            }
        )
    dep.containers = Mock(return_value=containers)
    dep.volumes = Mock(return_value=volumes)
    dep.compose = Mock()
    dep.maintenance = Mock()
    dep.images = Mock(
        return_value={
            service: {"id": "sha256:" + "a" * 64} for service in dep.config["services"]
        }
    )
    return dep


def test_actual_mount_inventory_matches_each_service():
    dep = mounted_deployment()
    volumes, _ = dep.inventory(b"x" * 32)
    assert set(volumes) == set(dep.config["volumes"])
    dep.compose.assert_not_called()


@pytest.mark.parametrize(
    "mismatch",
    [
        "source_peer",
        "destination",
        "read_only",
        "missing_mount",
        "extra_mount",
        "missing_peer_volume",
        "missing_store",
        "new_declared_volume",
    ],
)
def test_backup_mount_mismatch_refused_before_stop(tmp_path, mismatch):
    tmp_path.chmod(0o700)
    dep = mounted_deployment()
    neo4j = dep.containers.return_value[2]
    if mismatch == "source_peer":
        neo4j["Mounts"][0]["Name"] = "nanfo-deploy-source_redisdata"
    elif mismatch == "destination":
        neo4j["Mounts"][0]["Destination"] = "/old-data"
    elif mismatch == "read_only":
        neo4j["Mounts"][0]["RW"] = False
    elif mismatch == "missing_mount":
        neo4j["Mounts"] = []
    elif mismatch == "extra_mount":
        neo4j["Mounts"].append(
            {
                "Type": "volume",
                "Name": "nanfo-deploy-source_redisdata",
                "Destination": "/extra",
                "RW": True,
            }
        )
    elif mismatch == "missing_peer_volume":
        dep.volumes.return_value.pop(1)
    elif mismatch == "missing_store":
        dep.containers.return_value.pop(1)
    else:
        # Both old/new declarations exist, but only the old volume/container exists.
        dep.config["volumes"]["newneo4j"] = {}
        dep.config["services"]["neo4j"]["volumes"][0]["source"] = "newneo4j"
    with pytest.raises(OperationError):
        backup(dep, tmp_path, b"x" * 32, max_bytes=10**6)
    dep.compose.assert_not_called()
    dep.maintenance.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_bind_service_destination_is_not_interchangeable(tmp_path):
    dep = mounted_deployment()
    spec = {
        "type": "bind",
        "source": str(tmp_path),
        "target": "/binding",
        "read_only": True,
    }
    dep.config["services"]["api"]["volumes"].append(spec)
    dep.containers.return_value[3]["Mounts"].append(
        {"Type": "bind", "Source": str(tmp_path), "Destination": "/models", "RW": False}
    )
    with pytest.raises(OperationError, match="persistent mounts differ"):
        dep.inventory(b"x" * 32)


def test_restore_missing_declared_archive_refuses_before_any_docker_mutation(tmp_path):
    _, key = make_manifest(tmp_path)
    dep = fake_deployment()
    dep.config["volumes"]["neo4jdata"] = {}
    with pytest.raises(OperationError, match="empty creation forbidden"):
        restore(dep, tmp_path, key, max_bytes=10**6)
    dep.run.assert_not_called()
    dep.compose.assert_not_called()
    dep.maintenance.assert_not_called()


@pytest.mark.parametrize(
    "mounts", [[], [{"type": "volume", "source": "missing", "target": "/data"}]]
)
def test_restore_store_cannot_implicitly_create_unbacked_volume(tmp_path, mounts):
    _, key = make_manifest(tmp_path)
    dep = fake_deployment()
    dep.config["services"]["neo4j"]["volumes"] = mounts
    with pytest.raises(OperationError, match="backed named volume|unarchived volume"):
        restore(dep, tmp_path, key, max_bytes=10**6)
    dep.run.assert_not_called()
    dep.compose.assert_not_called()
    dep.maintenance.assert_not_called()


class GraphRows:
    def __init__(self, rows):
        self.rows = rows

    async def single(self, **kwargs):
        return self.rows[0]

    async def data(self):
        return self.rows

    def __aiter__(self):
        async def iterate():
            for row in self.rows:
                yield row

        return iterate()


@pytest.mark.parametrize("changed", [False, True])
def test_network_checkpoint_counts_and_revision_bytes_readonly(backend_path, changed):
    from app.modules.network.operations import maintenance_checkpoint

    revision = {
        "device_id": "device1",
        "epoch_us": 100,
        "rank": 2,
        "event_id": "event1",
        "deleted": changed,
    }
    results = [GraphRows([{"count": count}]) for count in (4, 2, int(changed))]
    results += [
        GraphRows(GRAPH["node_labels"]),
        GraphRows(GRAPH["relationship_types"]),
        GraphRows([revision]),
    ]
    tx = AsyncMock()
    tx.__aenter__.return_value = tx
    tx.run.side_effect = results
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.begin_transaction.return_value = tx
    driver = Mock(session=Mock(return_value=session))
    result = asyncio.run(maintenance_checkpoint(driver))
    assert result["nodes"] == 4 and result["relationships"] == 2
    assert result["revision_tombstones"] == int(changed)
    assert (
        result["revisions_sha256"]
        == hashlib.sha256(canonical(revision) + b"\n").hexdigest()
    )
    driver.session.assert_called_once_with(default_access_mode="READ")
    assert all(
        call.args[0].strip().startswith("MATCH") for call in tx.run.call_args_list
    )
    assert all(not getattr(tx, method).called for method in ("execute_write",))


def test_network_checkpoint_group_cap_fails_closed(backend_path):
    from app.modules.network.operations import maintenance_checkpoint

    tx = AsyncMock()
    tx.__aenter__.return_value = tx
    tx.run.side_effect = [GraphRows([{"count": 0}])] * 3 + [
        GraphRows(GRAPH["node_labels"])
    ]
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.begin_transaction.return_value = tx
    driver = Mock(session=Mock(return_value=session))
    with pytest.raises(ValueError, match="group cap"):
        asyncio.run(maintenance_checkpoint(driver, max_groups=1))


def test_network_checkpoint_revision_cap_fails_closed(backend_path):
    from app.modules.network.operations import maintenance_checkpoint

    tx = AsyncMock()
    tx.__aenter__.return_value = tx
    tx.run.side_effect = (
        [GraphRows([{"count": 0}])] * 3
        + [GraphRows([])] * 2
        + [GraphRows([{"device_id": "a"}, {"device_id": "b"}])]
    )
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.begin_transaction.return_value = tx
    driver = Mock(session=Mock(return_value=session))
    with pytest.raises(ValueError, match="revision inventory cap"):
        asyncio.run(maintenance_checkpoint(driver, max_revisions=1))
