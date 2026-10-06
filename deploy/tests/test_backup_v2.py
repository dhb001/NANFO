"""ADR-028 backup format 2: segmented AES-GCM, HKDF key separation, streaming restore.

Offline only: fake deployments, real cryptography/tar/subprocess pipes, no Docker.
"""

import copy
import hashlib
import hmac
import io
import json
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deploy import backup_restore
from deploy.backup_restore import (
    FORMAT,
    HEADER_V2,
    TAG,
    Deployment,
    OperationError,
    SegmentReader,
    backup,
    backup_keys,
    canonical,
    check_key_location,
    encrypt_segments,
    encrypt_stream,
    file_hash,
    filesystem_type,
    load_manifest,
    require_local_workspace,
    restore,
    validate_tar_stream,
    verify_archives,
    write_json,
)

KEY = bytes(range(32))
AAD = canonical({"project": "nanfo-deploy-source", "volume": "db", "file": "volume-0000.tar.gcm"})
GRAPH = {"nodes": 1, "relationships": 0, "revisions": 0, "revision_tombstones": 0,
         "node_labels": [], "relationship_types": [], "revisions_sha256": "a" * 64}


def sealed(data, *, segment=64, key=KEY, aad=AAD):
    output = io.BytesIO()
    assert encrypt_segments(io.BytesIO(data), output, key, aad, max_bytes=10**7, segment_size=segment) == len(data)
    return output.getvalue()


def opened(blob, *, key=KEY, aad=AAD, max_bytes=10**7):
    reader = SegmentReader(io.BytesIO(blob), key, aad, max_bytes=max_bytes)
    data = reader.read()
    reader.drain()
    return data


def segments(blob, segment=64):
    body = blob[HEADER_V2:]
    size = segment + TAG
    return blob[:HEADER_V2], [body[i:i + size] for i in range(0, len(body), size)]


@pytest.mark.parametrize("length", [0, 1, 63, 64, 65, 128, 64 * 7 + 5])
def test_segmented_roundtrip_including_empty_and_exact_boundaries(length):
    data = os.urandom(length)
    blob = sealed(data)
    assert blob.startswith(b"NANFO-GCM-2\0")
    assert opened(blob) == data
    _, parts = segments(blob)
    # Lookahead flags the last full segment final: no empty trailer segment is needed.
    assert len(parts) == max(1, -(-length // 64))
    assert data[:16] not in blob[HEADER_V2:] or length < 16


def test_nonces_and_segment_keys_are_fresh_per_archive():
    first, second = sealed(b"x" * 200), sealed(b"x" * 200)
    assert first[:HEADER_V2] != second[:HEADER_V2] and first[HEADER_V2:] != second[HEADER_V2:]


@pytest.mark.parametrize("tamper", ["segment_bit", "tag_bit", "header_salt", "header_prefix", "segment_size"])
def test_any_ciphertext_or_header_change_fails_authentication(tamper):
    blob = bytearray(sealed(b"payload" * 40))
    offset = {"segment_bit": HEADER_V2 + 70, "tag_bit": HEADER_V2 + 64 + 3, "header_salt": 17,
              "header_prefix": HEADER_V2 - 1}.get(tamper)
    if tamper == "segment_size":
        blob[12:16] = (32).to_bytes(4, "big")
    else:
        blob[offset] ^= 1
    with pytest.raises(OperationError, match="authentication failed|Truncated|segment"):
        opened(bytes(blob))


def test_truncation_reordering_and_appending_fail():
    header, parts = segments(sealed(b"0123456789" * 30))
    assert len(parts) >= 4
    for broken in (
        header + b"".join(parts[:-1]),                         # drop final segment (boundary)
        header + b"".join(parts)[:-5],                         # cut inside the final segment
        header + parts[1] + parts[0] + b"".join(parts[2:]),    # reorder
        header + b"".join(parts) + parts[-1],                  # append a replayed segment
        header + b"".join(parts[:2]) + parts[-1],              # splice the final segment early
        header,                                                # header only
    ):
        with pytest.raises(OperationError):
            opened(broken)


def test_identity_key_and_cap_are_enforced():
    blob = sealed(b"secret" * 50)
    with pytest.raises(OperationError, match="authentication failed"):
        opened(blob, aad=AAD + b"x")
    with pytest.raises(OperationError, match="authentication failed"):
        opened(blob, key=bytes(32))
    with pytest.raises(OperationError, match="cap"):
        opened(blob, max_bytes=100)
    with pytest.raises(OperationError, match="cap"):
        encrypt_segments(io.BytesIO(b"x" * 100), io.BytesIO(), KEY, AAD, max_bytes=99, segment_size=64)


def test_plaintext_is_released_only_per_authenticated_segment():
    header, parts = segments(sealed(b"A" * 64 + b"B" * 64 + b"C" * 10))
    tampered = bytearray(parts[1])
    tampered[0] ^= 1
    reader = SegmentReader(io.BytesIO(header + parts[0] + bytes(tampered) + parts[2]), KEY, AAD, max_bytes=10**6)
    assert reader.read(64) == b"A" * 64
    with pytest.raises(OperationError, match="authentication failed"):
        reader.read(64)


def test_hkdf_separates_encryption_mac_and_fingerprint_keys_and_v1_is_legacy():
    keys = backup_keys(KEY, FORMAT)
    assert len({keys.encryption, keys.mac, keys.fingerprint, KEY}) == 4
    assert backup_keys(KEY, FORMAT) == keys
    assert backup_keys(KEY, 1) == (KEY, KEY, KEY)
    with pytest.raises(OperationError):
        backup_keys(KEY, 3)


def tar_bytes(*members):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as output:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600
            output.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def test_streaming_tar_validation_rejects_unsafe_entries_and_authenticates_trailer():
    good = sealed(tar_bytes(("a", b"1"), ("dir/b", b"22")), segment=512)
    assert validate_tar_stream(SegmentReader(io.BytesIO(good), KEY, AAD, max_bytes=10**6), max_bytes=10**6)["entries"] == 2
    bad = sealed(tar_bytes(("../escape", b"x")), segment=512)
    with pytest.raises(OperationError, match="Unsafe archive path"):
        validate_tar_stream(SegmentReader(io.BytesIO(bad), KEY, AAD, max_bytes=10**6), max_bytes=10**6)
    header, parts = segments(good, 512)
    with pytest.raises(OperationError):  # tar parses, but the dropped final segment is detected
        validate_tar_stream(SegmentReader(io.BytesIO(header + b"".join(parts[:-1])), KEY, AAD, max_bytes=10**6),
                            max_bytes=10**6)


def manifest_dir(tmp_path, payload, *, fmt=FORMAT, key=KEY, project="nanfo-deploy-source", schema="0019"):
    tmp_path.chmod(0o700)
    item = {"logical": "postgresdata", "file": "volume-0000.tar.gcm", "kind": "volume", "bytes": len(payload)}
    aad = canonical({"project": project, "volume": item["logical"], "file": item["file"]})
    keys = backup_keys(key, fmt)
    blob = io.BytesIO()
    if fmt == FORMAT:
        encrypt_segments(io.BytesIO(payload), blob, keys.encryption, aad, max_bytes=10**7, segment_size=128)
    else:
        encrypt_stream(io.BytesIO(payload), blob, key, aad, max_bytes=10**7)
    path = tmp_path / item["file"]
    path.write_bytes(blob.getvalue())
    path.chmod(0o600)
    item["sha256"] = file_hash(path)
    manifest = {"format": fmt, "complete": True, "project": project, "images": {"api": {"id": "sha256:" + "a" * 64}},
                "external_fingerprints": {}, "volumes": [item],
                "checkpoint": {"safe": True, "schema": schema, "neo4j_graph": copy.deepcopy(GRAPH)}}
    write_json(tmp_path / "manifest.json", manifest)
    signature = tmp_path / "manifest.hmac"
    signature.write_text(hmac.new(keys.mac, canonical(manifest), hashlib.sha256).hexdigest())
    signature.chmod(0o600)
    return manifest


def test_manifest_mac_uses_the_derived_key_and_binds_the_format(tmp_path):
    manifest = manifest_dir(tmp_path, tar_bytes(("file", b"data")))
    assert load_manifest(tmp_path, KEY) == manifest
    raw = json.loads((tmp_path / "manifest.json").read_text())
    raw["format"] = 1  # downgrade attempt with the unchanged signature
    (tmp_path / "manifest.json").write_bytes(canonical(raw))
    with pytest.raises(OperationError, match="authentication"):
        load_manifest(tmp_path, KEY)


@pytest.mark.parametrize("fmt", [1, FORMAT])
def test_offline_verify_supports_v1_and_v2(tmp_path, fmt):
    manifest_dir(tmp_path, tar_bytes(("file", b"data")), fmt=fmt)
    assert verify_archives(tmp_path, KEY, max_bytes=10**6) == {"status": "authenticated", "format": fmt, "volumes": 1}


def target_deployment():
    dep = Mock(spec=Deployment)
    dep.project = "nanfo-deploy-target"
    dep.config = {"volumes": {"postgresdata": {}}, "services": {
        name: {"volumes": [{"type": "volume", "source": "postgresdata", "target": "/data"}]}
        for name in ("postgres", "redis", "neo4j", "api")}}
    dep.containers.return_value = dep.volumes.return_value = []
    dep.images.return_value = {"api": {"id": "sha256:" + "a" * 64}}
    dep.external_fingerprints.return_value = {}
    dep.binds.return_value = {}
    dep.run.return_value = b""
    dep.volume_name.return_value = "nanfo-deploy-target_postgresdata"
    dep.helper_args.return_value = ["helper"]
    dep.maintenance.return_value = {"safe": True, "schema": "0019", "neo4j_graph": copy.deepcopy(GRAPH)}
    return dep


def test_v2_restore_validates_every_archive_then_streams_into_extraction(tmp_path):
    payload = tar_bytes(("data", b"restored-bytes"))
    manifest_dir(tmp_path, payload)
    dep = target_deployment()
    received = []

    def stream_into(args, reader):
        with tarfile.open(fileobj=reader, mode="r|") as archive:
            for member in archive:
                received.append(archive.extractfile(member).read())
        reader.drain()
        return 0

    dep.stream_into.side_effect = stream_into
    result = restore(dep, tmp_path, KEY, max_bytes=10**6)
    assert result["status"] == "restored_verified" and received == [b"restored-bytes"]
    assert not list(tmp_path.glob(".restore-*"))  # nothing staged beside the backup
    dep.external_fingerprints.assert_called_once_with(backup_keys(KEY, FORMAT).fingerprint)


def test_v2_restore_refuses_tampered_final_segment_before_creating_anything(tmp_path):
    manifest = manifest_dir(tmp_path, tar_bytes(("data", b"x" * 1000)))
    path = tmp_path / "volume-0000.tar.gcm"
    blob = bytearray(path.read_bytes())
    blob[-1] ^= 1
    path.chmod(0o600)
    path.write_bytes(bytes(blob))
    # Keep the outer checksum consistent to prove per-segment authentication alone refuses.
    manifest["volumes"][0]["sha256"] = file_hash(path)
    (tmp_path / "manifest.json").chmod(0o600)
    (tmp_path / "manifest.json").unlink()
    write_json(tmp_path / "manifest.json", manifest)
    (tmp_path / "manifest.hmac").write_text(
        hmac.new(backup_keys(KEY, FORMAT).mac, canonical(manifest), hashlib.sha256).hexdigest())
    dep = target_deployment()
    with pytest.raises(OperationError, match="authentication failed"):
        restore(dep, tmp_path, KEY, max_bytes=10**6)
    dep.stream_into.assert_not_called()
    assert all("create" not in call.args for call in dep.run.call_args_list)
    dep.compose.assert_not_called()


def test_v1_backup_remains_restorable_with_checked_local_staging(tmp_path):
    backups, work = tmp_path / "backup", tmp_path / "work"
    backups.mkdir()
    work.mkdir(mode=0o700)
    manifest_dir(backups, tar_bytes(("data", b"legacy")), fmt=1)
    dep = target_deployment()
    restored = []

    def run(*args, **kwargs):
        if "stdin" in kwargs:
            with tarfile.open(fileobj=kwargs["stdin"], mode="r:") as archive:
                restored.append(archive.extractfile("data").read())
        return b""

    dep.run.side_effect = run
    assert restore(dep, backups, KEY, max_bytes=10**6, work_dir=work)["status"] == "restored_verified"
    assert restored == [b"legacy"]
    dep.external_fingerprints.assert_called_once_with(KEY)


def test_v1_staging_refuses_network_filesystems_and_missing_space(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(backup_restore, "filesystem_type", lambda path: "nfs4")
    with pytest.raises(OperationError, match="local storage"):
        require_local_workspace(tmp_path, 1)
    monkeypatch.setattr(backup_restore, "filesystem_type", lambda path: "ext4")
    monkeypatch.setattr(backup_restore.shutil, "disk_usage", lambda path: SimpleNamespace(free=10))
    with pytest.raises(OperationError, match="free space"):
        require_local_workspace(tmp_path, 1)


def test_filesystem_type_uses_the_longest_mount_point(tmp_path):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "22 1 0:21 / / rw,relatime - ext4 /dev/root rw\n"
        f"23 22 0:22 / {tmp_path} rw - nfs4 server:/export rw\n"
    )
    assert filesystem_type(tmp_path / "child", mountinfo=mountinfo) == "nfs4"
    assert filesystem_type("/", mountinfo=mountinfo) == "ext4"
    assert filesystem_type("/", mountinfo=tmp_path / "missing") is None


def test_key_must_not_live_in_or_beside_the_backup_tree(tmp_path):
    backups = tmp_path / "backups" / "b1"
    backups.mkdir(parents=True)
    for key in (backups / "k", tmp_path / "backups" / "keys" / "k", tmp_path / "backups" / "k", tmp_path / "k"):
        with pytest.raises(OperationError, match="outside the backup directory tree"):
            check_key_location(key, backups)
    elsewhere = tmp_path.parent / (tmp_path.name + "-keys")
    elsewhere.mkdir(exist_ok=True)
    (elsewhere / "k").write_bytes(b"x" * 32)
    warnings = []
    assert check_key_location(elsewhere / "k", backups, warn=warnings.append) is True
    assert "encryption_key_same_filesystem" in warnings[0]


def fake_source():
    dep = Mock(spec=Deployment)
    dep.project = "nanfo-deploy-source"
    dep.config = {"volumes": {"postgresdata": {}}, "services": {
        name: {"volumes": [{"type": "volume", "source": "postgresdata", "target": "/data"}]}
        for name in ("postgres", "redis", "neo4j", "api", "report-worker")}}
    dep.images.return_value = {name: {"id": "sha256:" + "a" * 64, "os": "linux", "architecture": "amd64"}
                               for name in dep.config["services"]}
    dep.containers.return_value = [{"Image": "sha256:" + "a" * 64,
                                    "Config": {"Labels": {"com.docker.compose.service": "api"}}}]
    dep.inventory.return_value = ({"postgresdata": "nanfo-deploy-source_postgresdata"}, {})
    dep.binds.return_value = {}
    dep.mount_contract.return_value = {}
    dep.volume_usage.return_value = {"bytes": 4096, "entries": 2}
    dep.maintenance.return_value = {"safe": True, "schema": "0019", "neo4j_graph": copy.deepcopy(GRAPH)}
    return dep


@pytest.mark.parametrize("problem", ["cap", "space"])
def test_capacity_is_checked_before_anything_is_stopped(tmp_path, monkeypatch, problem):
    tmp_path.chmod(0o700)
    dep = fake_source()
    if problem == "cap":
        dep.volume_usage.return_value = {"bytes": 10**7, "entries": 1}
    else:
        monkeypatch.setattr(backup_restore.shutil, "disk_usage", lambda path: SimpleNamespace(free=1024))
    with pytest.raises(OperationError, match="nothing was stopped"):
        backup(dep, tmp_path, KEY, max_bytes=10**6)
    dep.compose.assert_not_called()
    dep.maintenance.assert_not_called()
    assert not list(tmp_path.iterdir())
    assert dep.stage == "backup_capacity" and "backup_capacity" in backup_restore.STAGES


def test_backup_writes_format_2_segmented_archives_and_derived_mac(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    dep = fake_source()
    payload = tar_bytes(("data", os.urandom(3000)))
    process = SimpleNamespace(stdout=io.BytesIO(payload), wait=Mock(return_value=0), poll=Mock(return_value=0))
    monkeypatch.setattr("deploy.backup_restore.subprocess.Popen", Mock(return_value=process))
    result = backup(dep, tmp_path, KEY, max_bytes=10**6, segment_size=1024)
    assert result["status"] == "backed_up" and result["format"] == FORMAT
    manifest = load_manifest(tmp_path, KEY)
    assert manifest["format"] == FORMAT and manifest["encryption"]["segment_bytes"] == 1024
    assert manifest["capacity"]["estimated_bytes"] == 4096
    blob = (tmp_path / "volume-0000.tar.gcm").read_bytes()
    assert blob.startswith(b"NANFO-GCM-2\0") and len(blob) > len(payload) + 3 * TAG
    dep.inventory.assert_called_with(backup_keys(KEY, FORMAT).fingerprint)
    assert verify_archives(tmp_path, KEY, max_bytes=10**6)["status"] == "authenticated"


def test_stream_into_pipes_plaintext_and_keeps_authenticating_after_early_exit(tmp_path):
    dep = object.__new__(Deployment)
    out = tmp_path / "out"
    blob = sealed(b"z" * 500)
    assert dep.stream_into(["sh", "-c", f"cat > {out}"], SegmentReader(io.BytesIO(blob), KEY, AAD, max_bytes=10**6)) == 0
    assert out.read_bytes() == b"z" * 500
    header, parts = segments(blob)
    broken = header + b"".join(parts[:-1])
    with pytest.raises(OperationError):
        dep.stream_into(["sh", "-c", "head -c 1 >/dev/null"], SegmentReader(io.BytesIO(broken), KEY, AAD, max_bytes=10**6))
    with pytest.raises(OperationError, match="Docker operation failed"):
        dep.stream_into(["sh", "-c", "cat >/dev/null; exit 3"], SegmentReader(io.BytesIO(blob), KEY, AAD, max_bytes=10**6))


def test_volume_usage_probe_is_read_only_offline_and_bounded():
    dep = object.__new__(Deployment)
    dep.project = "nanfo-deploy-test"
    dep.run = Mock(return_value=b'{"bytes": 2048, "entries": 3}')
    assert dep.volume_usage("sha256:" + "b" * 64, "nanfo-deploy-test_reports") == {"bytes": 2048, "entries": 3}
    args = dep.run.call_args.args
    assert "none" in args and "--read-only" in args and "type=volume,src=nanfo-deploy-test_reports,dst=/volume,readonly" in args
    assert args[args.index("--entrypoint") + 1] == "python" and "tar" not in args
    dep.run.return_value = b'{"bytes": -1}'
    with pytest.raises(OperationError):
        dep.volume_usage("sha256:" + "b" * 64, "nanfo-deploy-test_reports")


def test_usage_probe_script_estimates_at_least_the_tar_stream(tmp_path):
    root = tmp_path / "volume"
    (root / "nested").mkdir(parents=True)
    (root / "a").write_bytes(b"x" * 700)
    (root / "nested" / ("long" * 40)).write_bytes(b"y" * 10)
    script = backup_restore.USAGE_PROBE.replace("'/volume'", repr(str(root)))
    namespace = {}
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(compile(script, "probe", "exec"), namespace)  # noqa: S102 - fixed module constant
    estimate = json.loads(buffer.getvalue())["bytes"]
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.GNU_FORMAT) as archive:
        archive.add(root, arcname=".")
    assert estimate >= len(stream.getvalue())


def test_cli_refuses_key_beside_backups_before_reading_it(tmp_path, capsys):
    backups = tmp_path / "b"
    backups.mkdir(mode=0o700)
    key = tmp_path / "key"
    key.write_bytes(b"x" * 32)
    key.chmod(0o600)
    code = backup_restore.main(["verify", "--project", "nanfo-deploy-x", "--compose-file", "c", "--env-file", "e",
                                "--directory", str(backups), "--encryption-key-file", str(key)])
    assert code == 1
    assert "outside the backup directory tree" in capsys.readouterr().err
    assert Path(key).read_bytes() == b"x" * 32
