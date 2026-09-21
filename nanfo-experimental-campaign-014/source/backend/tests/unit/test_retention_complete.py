import hashlib
import os
import uuid

import pytest

from app.modules.telemetry.archive import TelemetryArchiveStore
from app.modules.telemetry.references import evidence_item, reference_ids


def test_archive_protected_durable_replay_and_tamper(tmp_path):
    os.chmod(tmp_path, 0o700)
    store = TelemetryArchiveStore(tmp_path)
    data = b'{"canonical":"bytes"}'
    digest = store.write(data)
    assert digest == hashlib.sha256(data).hexdigest()
    assert store.write(data) == digest
    assert store.read(digest, len(data)) == data
    assert (tmp_path / digest).stat().st_mode & 0o077 == 0
    (tmp_path / digest).write_bytes(b"x" * len(data))
    with pytest.raises(ValueError, match="checksum"):
        store.read(digest, len(data))
    with pytest.raises(ValueError, match="checksum"):
        store.write(data)


def test_archive_rejects_symlinks_and_public_files(tmp_path):
    os.chmod(tmp_path, 0o700)
    store = TelemetryArchiveStore(tmp_path)
    digest = store.write(b"private")
    os.chmod(tmp_path / digest, 0o644)
    with pytest.raises(ValueError, match="protection"):
        store.read(digest, 7)
    os.chmod(tmp_path, 0o755)
    with pytest.raises(ValueError, match="private"):
        TelemetryArchiveStore(tmp_path)


def test_reference_version_identity_does_not_retarget_mutable_evidence():
    network, record = uuid.uuid4(), uuid.uuid4()
    first = evidence_item(identity="decision:1", network_id=network,
                          fields={"evidence": {"record_id": str(record), "value": 1}})
    replay = evidence_item(identity="decision:1", network_id=network,
                           fields={"evidence": {"value": 1, "record_id": str(record)}})
    changed = evidence_item(identity="decision:1", network_id=network,
                            fields={"evidence": {"record_id": str(record), "value": 2}})
    assert first == replay
    assert first.references[0].reference_id != changed.references[0].reference_id
    assert reference_ids([f"telemetry_record:{record}", {"telemetry_record_ids": [str(record)]}]) == [record]
    with pytest.raises(ValueError):
        reference_ids({"record_id": "lost-legacy-identity"})


@pytest.mark.parametrize("target", ["ancestor", "root"])
@pytest.mark.parametrize("replacement", ["symlink", "directory"])
@pytest.mark.parametrize("timing", ["before", "publication", "readback"])
def test_archive_rejects_directory_substitution(tmp_path, monkeypatch, target, replacement, timing):
    parent = tmp_path / "parent"
    root = parent / "archive"
    parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    store = TelemetryArchiveStore(root)
    data = b"pinned-directory"
    digest = hashlib.sha256(data).hexdigest()
    moved = tmp_path / "original"

    def replace():
        path = parent if target == "ancestor" else root
        path.rename(moved)
        alternate = tmp_path / "alternate"
        alternate.mkdir(mode=0o700)
        if replacement == "symlink":
            path.symlink_to(alternate, target_is_directory=True)
        else:
            path.mkdir(mode=0o700)
        redirected = path / "archive" if target == "ancestor" else path
        if target == "ancestor":
            redirected.mkdir(mode=0o700)
        # Even matching bytes in the substituted directory cannot validate identity.
        (redirected / digest).write_bytes(data)
        os.chmod(redirected / digest, 0o600)

    if timing == "before":
        replace()
    elif timing == "publication":
        original = os.link

        def link(*args, **kwargs):
            replace()
            return original(*args, **kwargs)

        monkeypatch.setattr(os, "link", link)
    else:
        original = store._read

        def read(*args):
            result = original(*args)
            replace()
            return result

        monkeypatch.setattr(store, "_read", read)
    with pytest.raises((OSError, ValueError)):
        store.write(data)
    original_root = moved / "archive" if target == "ancestor" else moved
    assert (original_root / digest).exists() is (timing != "before")


@pytest.mark.parametrize("target", ["ancestor", "root"])
@pytest.mark.parametrize("timing", ["before", "during"])
def test_archive_read_rejects_replacement_and_restart_preserves_bytes(tmp_path, monkeypatch, target, timing):
    parent = tmp_path / "parent"
    root = parent / "archive"
    parent.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    data = b"survives-legitimate-restart"
    digest = TelemetryArchiveStore(root).write(data)
    store = TelemetryArchiveStore(root)
    assert store.read(digest, len(data)) == data

    def replace():
        path = parent if target == "ancestor" else root
        path.rename(tmp_path / "old")
        path.mkdir(mode=0o700)
        redirected = path / "archive" if target == "ancestor" else path
        if target == "ancestor":
            redirected.mkdir(mode=0o700)
        (redirected / digest).write_bytes(data)
        os.chmod(redirected / digest, 0o600)

    if timing == "before":
        replace()
    else:
        original = store._read

        def read(*args):
            result = original(*args)
            replace()
            return result

        monkeypatch.setattr(store, "_read", read)
    with pytest.raises(ValueError, match="identity"):
        store.read(digest, len(data))


@pytest.mark.parametrize("mode", [0o777, 0o770, 0o720])
def test_archive_rechecks_ancestor_permissions(tmp_path, mode):
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    root = parent / "archive"
    root.mkdir(mode=0o700)
    store = TelemetryArchiveStore(root)
    os.chmod(parent, mode)
    with pytest.raises(ValueError, match="ancestor"):
        store.write(b"refused")
    with pytest.raises(ValueError, match="ancestor"):
        TelemetryArchiveStore(root)


def test_archive_rechecks_permissions_after_readback(tmp_path, monkeypatch):
    os.chmod(tmp_path, 0o700)
    store = TelemetryArchiveStore(tmp_path)
    original = store._read

    def read(*args):
        result = original(*args)
        os.chmod(tmp_path, 0o750)
        return result

    monkeypatch.setattr(store, "_read", read)
    with pytest.raises(ValueError, match="private"):
        store.write(b"refused")
