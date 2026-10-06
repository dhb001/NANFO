import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from app.modules.network.asset_settings import AssetSettings
from app.modules.network.asset_storage import AssetIntegrityError, AssetQuotaError, AssetStorageError, LocalAssetStore


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "objects"
    root.mkdir(mode=0o700)
    return LocalAssetStore(AssetSettings(root=root, max_total_bytes=100, max_objects=2))


def put(store, data=b"model"):
    digest = hashlib.sha256(data).hexdigest()
    store.put(data, digest, len(data))
    return digest


def test_durable_dedup_and_restart(store):
    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes = list(pool.map(lambda _: put(store), range(8)))
    assert len(set(hashes)) == 1
    assert len(list(store.settings.root.iterdir())) == 1
    assert LocalAssetStore(store.settings).read(hashes[0], 5) == b"model"
    assert (store.settings.root / hashes[0]).stat().st_mode & 0o777 == 0o400


@pytest.mark.parametrize("body", [b"tampr", b"long tampered body", b""])
def test_tamper_read_and_dedup_fail_closed(store, body):
    digest = put(store)
    path = store.settings.root / digest
    path.chmod(0o600)
    path.write_bytes(body)
    with pytest.raises(AssetIntegrityError):
        store.read(digest, 5)
    with pytest.raises(AssetIntegrityError):
        put(store)


def test_quotas_dedup_and_no_eviction(store):
    first = put(store)
    put(store, b"second")
    put(store)
    with pytest.raises(AssetQuotaError):
        put(store, b"third")
    assert store.read(first, 5) == b"model"
    small = LocalAssetStore(store.settings.model_copy(update={"max_total_bytes": 11}))
    with pytest.raises(AssetQuotaError):
        put(small, b"extra")


@pytest.mark.parametrize("digest", ["../escape", "/etc/passwd", "a" * 63, "A" * 64])
def test_untrusted_identity_never_reaches_filesystem(store, digest):
    with pytest.raises(AssetIntegrityError):
        store.read(digest, 5)
    with pytest.raises(AssetIntegrityError):
        store.put(b"model", digest, 5)


def test_symlink_root_parent_and_body_rejected(store, tmp_path):
    digest = hashlib.sha256(b"model").hexdigest()
    target = tmp_path / "outside"
    target.write_bytes(b"model")
    (store.settings.root / digest).symlink_to(target)
    with pytest.raises(AssetStorageError):
        store.read(digest, 5)
    with pytest.raises(AssetStorageError):
        put(store)
    link = tmp_path / "linked"
    link.symlink_to(store.settings.root, target_is_directory=True)
    with pytest.raises(AssetStorageError):
        LocalAssetStore(AssetSettings(root=link)).read(digest, 5)
    parent_link = tmp_path / "parent"
    parent_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(AssetStorageError):
        LocalAssetStore(AssetSettings(root=parent_link / "objects")).read(digest, 5)
    assert target.read_bytes() == b"model"


def test_nonroot_private_permissions_and_hardlinks(store, tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(os, "geteuid", lambda: 0)
        with pytest.raises(AssetStorageError):
            put(store)
    store.settings.root.chmod(0o755)
    with pytest.raises(AssetStorageError):
        put(store)
    store.settings.root.chmod(0o700)
    digest = put(store)
    os.link(store.settings.root / digest, tmp_path / "hardlink")
    with pytest.raises(AssetStorageError):
        store.read(digest, 5)


def test_atomic_publication_failure_keeps_no_partial_object(store, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("injected link failure")
    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(AssetStorageError):
        put(store)
    assert list(store.settings.root.iterdir()) == []


def test_config_and_object_bounds(store):
    for root in ("relative", "/", "/private/../escape"):
        with pytest.raises(ValidationError):
            AssetSettings(root=root)
    with pytest.raises(AssetIntegrityError):
        store.put(b"model", hashlib.sha256(b"model").hexdigest(), 4)
    with pytest.raises(AssetIntegrityError):
        LocalAssetStore(store.settings.model_copy(update={"max_object_bytes": 4})).put(
            b"model", hashlib.sha256(b"model").hexdigest(), 5,
        )


def test_concurrent_quota_admission_is_serialized(store):
    def attempt(index):
        try:
            put(store, f"model-{index}".encode())
            return True
        except AssetQuotaError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(attempt, range(8)))
    assert sum(admitted) == 2
    assert len(list(store.settings.root.iterdir())) == 2


@pytest.mark.parametrize("recover_first", ["read", "unrelated-upload"])
def test_process_exit_after_link_recovers_on_new_store(store, recover_first):
    script = """
import os, sys, hashlib
from app.modules.network.asset_settings import AssetSettings
from app.modules.network.asset_storage import LocalAssetStore
store = LocalAssetStore(AssetSettings(root=sys.argv[1]))
os.unlink = lambda *args, **kwargs: os._exit(23)
store.put(b'model', hashlib.sha256(b'model').hexdigest(), 5)
"""
    result = subprocess.run([sys.executable, "-c", script, str(store.settings.root)], timeout=10)
    assert result.returncode == 23
    digest = hashlib.sha256(b"model").hexdigest()
    assert (store.settings.root / digest).stat().st_nlink == 2
    restarted = LocalAssetStore(store.settings)
    if recover_first == "read":
        assert restarted.read(digest, 5) == b"model"
    other = put(restarted, b"unrelated")
    assert restarted.read(other, 9) == b"unrelated"
    assert restarted.read(digest, 5) == b"model"
    assert (store.settings.root / digest).stat().st_nlink == 1
    assert sorted(p.name for p in store.settings.root.iterdir()) == sorted([digest, other])


@pytest.mark.parametrize("alias", ["external", "unknown-name", "extra-external", "wrong-digest", "symlink"])
def test_recovery_does_not_remove_unproven_aliases(store, tmp_path, alias):
    digest = put(store)
    published = store.settings.root / digest
    temporary = store.settings.root / (".upload-" + "a" * 32)
    if alias == "external":
        os.link(published, tmp_path / temporary.name)
    elif alias == "unknown-name":
        os.link(published, store.settings.root / "unrelated-file")
    elif alias == "extra-external":
        os.link(published, temporary)
        os.link(published, tmp_path / "external")
    elif alias == "wrong-digest":
        os.link(published, temporary)
        published.rename(store.settings.root / ("0" * 64))
    else:
        os.link(published, temporary)
        published.rename(tmp_path / "external")
        published.symlink_to(tmp_path / "external")
    before = {path.name: path.lstat() for path in store.settings.root.iterdir()}
    restarted = LocalAssetStore(store.settings)
    with pytest.raises(AssetStorageError):
        restarted.read(digest, 5)
    with pytest.raises(AssetStorageError):
        put(restarted, b"unrelated")
    assert {path.name: path.lstat().st_ino for path in store.settings.root.iterdir()} == {
        name: info.st_ino for name, info in before.items()
    }


def test_recovery_preserves_unpublished_upload_and_unrelated_regular_file(store):
    temporary = store.settings.root / (".upload-" + "b" * 32)
    temporary.write_bytes(b"unpublished")
    temporary.chmod(0o400)
    unrelated = store.settings.root / "operator-note"
    unrelated.write_bytes(b"keep")
    unrelated.chmod(0o600)
    restarted = LocalAssetStore(store.settings.model_copy(update={"max_objects": 4}))
    digest = put(restarted)
    assert restarted.read(digest, 5) == b"model"
    assert temporary.read_bytes() == b"unpublished" and unrelated.read_bytes() == b"keep"


def test_put_reports_new_publication_and_verified_put_skips_rehash(store, monkeypatch):
    from app.modules.network import asset_storage

    digest = hashlib.sha256(b"model").hexdigest()
    hashed = []
    original = asset_storage.verify_body
    monkeypatch.setattr(asset_storage, "verify_body", lambda *a, **k: hashed.append(1) or original(*a, **k))
    assert store.put(b"model", digest, 5, verified=True) is True
    assert hashed == []
    # Dedup still verifies the stored object before trusting it.
    assert store.put(b"model", digest, 5, verified=True) is False
    assert hashed == [1]
    with pytest.raises(AssetIntegrityError):
        store.put(b"model", digest, 4, verified=True)
    with pytest.raises(AssetIntegrityError):
        store.put(b"model", "not-a-digest", 5, verified=True)


def test_reads_take_a_shared_lock_and_recover_only_once_per_process(store, monkeypatch):
    import fcntl

    digest = put(store)
    recoveries, modes = [], []
    original_recover = LocalAssetStore._recover_publications
    original_flock = fcntl.flock
    monkeypatch.setattr(LocalAssetStore, "_recover_publications",
                        lambda self, root: recoveries.append(1) or original_recover(self, root))
    monkeypatch.setattr(fcntl, "flock", lambda fd, mode: modes.append(mode) or original_flock(fd, mode))
    for _ in range(3):
        assert LocalAssetStore(store.settings).read(digest, 5) == b"model"
    # Startup recovery already ran during the upload; reads never scan or serialize.
    assert recoveries == []
    assert fcntl.LOCK_EX not in modes and modes.count(fcntl.LOCK_SH) == 3


def test_parallel_reads_are_not_serialized(store):
    digest = put(store)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert set(pool.map(lambda _: store.read(digest, 5), range(32))) == {b"model"}


def test_stale_single_link_uploads_are_collected_fresh_ones_kept(store):
    stale = store.settings.root / (".upload-" + "c" * 32)
    fresh = store.settings.root / (".upload-" + "d" * 32)
    for path in (stale, fresh):
        path.write_bytes(b"partial")
        path.chmod(0o600)
    old = stale.stat().st_mtime - store.settings.stale_upload_seconds - 5
    os.utime(stale, (old, old))
    assert store.remove_stale_uploads() == 1
    assert not stale.exists() and fresh.read_bytes() == b"partial"
    # Uploads also collect abandoned temporaries before admission.
    os.utime(fresh, (old, old))
    put(store)
    assert not fresh.exists()


def test_remove_unreferenced_only_removes_private_single_link_objects(store, tmp_path):
    digest = put(store)
    other = put(store, b"second")
    assert store.list_objects() == sorted([digest, other])
    assert store.remove_unreferenced(digest) is True
    assert store.remove_unreferenced(digest) is False
    os.link(store.settings.root / other, tmp_path / "alias")
    with pytest.raises(AssetStorageError):
        store.remove_unreferenced(other)
    assert (store.settings.root / other).exists()
    for bad in ("../escape", "A" * 64, ".upload-" + "a" * 32):
        with pytest.raises(AssetIntegrityError):
            store.remove_unreferenced(bad)


def test_list_objects_excludes_temporaries(store):
    digest = put(store)
    temporary = store.settings.root / (".upload-" + "e" * 32)
    temporary.write_bytes(b"x")
    temporary.chmod(0o600)
    assert store.list_objects() == [digest]


async def test_collector_rechecks_each_candidate_under_its_digest_lock(store, monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from app.modules.network import asset_gc

    store = LocalAssetStore(store.settings.model_copy(update={"max_objects": 10}))
    referenced, orphan, raced = put(store, b"referenced"), put(store, b"orphan"), put(store, b"raced")
    events = []

    class Repository:
        def __init__(self, db):
            self.db = db

        async def referenced_digests(self, digests):
            return {referenced}

        async def lock_digest(self, digest):
            events.append(("lock", digest))

        async def digest_referenced(self, digest):
            # A concurrent upload committed a row for `raced` before the lock was granted.
            return digest == raced

    db = AsyncMock()

    @asynccontextmanager
    async def sessions():
        yield db

    monkeypatch.setattr(asset_gc, "CampusModelAssetRepository", Repository)
    dry = await asset_gc.collect_garbage(sessions, store, dry_run=True)
    assert dry["unreferenced"] == 2 and dry["removed"] == 0 and events == []
    report = await asset_gc.collect_garbage(sessions, store)
    assert report["removed"] == 1 and report["retained"] == 2
    assert set(store.list_objects()) == {referenced, raced}
    assert sorted(digest for _, digest in events) == sorted([orphan, raced])
    assert db.commit.await_count == 2
