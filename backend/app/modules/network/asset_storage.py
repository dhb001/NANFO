"""Protected POSIX content-addressed storage with database-driven garbage collection.

Only digest-derived single-component names are used under an opened private root.
Directory descriptors and O_NOFOLLOW prevent traversal and symlink races. An
exclusive ``flock`` serializes admission, publication, recovery and removal across
processes; reads take a *shared* ``flock`` and never scan the directory. Crash
recovery runs once per process per root ("startup") and on every upload. Files are
durable before SQL may reference them.

Removal exists only for two cases: a blob that the caller has proven — while holding
that digest's database advisory lock — is referenced by *no* asset row, and
single-link ``.upload-*`` temporaries older than ``stale_upload_seconds``. The global
directory scan remains a safety cap; tenant quotas are enforced from database
accounting of active assets by the service layer.
"""

from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import os
import re
import stat
import threading
import time
import uuid
from contextlib import contextmanager

from app.modules.network.asset_settings import AssetSettings

_DIGEST = re.compile(r"[0-9a-f]{64}")
_UPLOAD = re.compile(r"\.upload-[0-9a-f]{32}")
_MAX_OBJECT = 8 * 1024 * 1024

# Roots (st_dev, st_ino) already recovered by this process; guarded for worker threads.
_RECOVERED: set[tuple[int, int]] = set()
_RECOVERED_GUARD = threading.Lock()


class AssetStorageError(Exception):
    code = "CAMPUS_MODEL_ASSET_STORAGE_UNAVAILABLE"
    message = "Campus model asset storage is unavailable."
    status_code = 503


class AssetIntegrityError(AssetStorageError):
    code = "CAMPUS_MODEL_ASSET_INTEGRITY_FAILED"
    message = "Campus model asset integrity verification failed."


class AssetQuotaError(AssetStorageError):
    code = "CAMPUS_MODEL_ASSET_QUOTA_EXCEEDED"
    message = "Campus model asset storage quota exceeded."
    status_code = 507


def _valid_identity(digest: str, size: int, limit: int = _MAX_OBJECT) -> bool:
    return (isinstance(digest, str) and _DIGEST.fullmatch(digest) is not None
            and type(size) is int and 0 < size <= limit)


def verify_body(data: bytes, digest: str, size: int, limit: int = _MAX_OBJECT) -> bytes:
    if (not _valid_identity(digest, size, limit) or len(data) != size
            or hashlib.sha256(data).hexdigest() != digest):
        raise AssetIntegrityError()
    return data


def decode_inline(encoded: str, digest: str, size: int) -> bytes:
    """Decode and hash once. CPU-bound: call from a worker thread."""
    if not isinstance(encoded, str) or len(encoded) > 12_000_000:
        raise AssetIntegrityError()
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AssetIntegrityError() from exc
    return verify_body(data, digest, size)


def _root_key(root: int) -> tuple[int, int]:
    info = os.fstat(root)
    return info.st_dev, info.st_ino


class LocalAssetStore:
    def __init__(self, settings: AssetSettings | None = None):
        self.settings = settings or AssetSettings()

    @contextmanager
    def _root(self):
        descriptor = None
        try:
            if os.geteuid() == 0:
                raise AssetStorageError()
            descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
            for component in self.settings.root.parts[1:]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            info = os.fstat(descriptor)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise AssetStorageError()
            yield descriptor
        except OSError as exc:
            raise AssetStorageError() from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @contextmanager
    def _locked(self, mode: int):
        with self._root() as root:
            fcntl.flock(root, mode)
            try:
                yield root
            finally:
                fcntl.flock(root, fcntl.LOCK_UN)

    @staticmethod
    def _private_file(info):
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
            raise AssetStorageError()

    def _recover_publications(self, root: int) -> None:
        """Under the exclusive lock, remove only provably abandoned temporaries.

        * Interrupted publications: exactly two links, accounted for by an owned
          upload name and its verified digest name in this directory.
        * Stale single-link uploads older than ``stale_upload_seconds`` (a writer
          holds the exclusive lock for its whole write, so none is in progress).

        Unknown/external aliases are never removed or exempted from validation.
        """
        stale_before = time.time() - self.settings.stale_upload_seconds
        with os.scandir(root) as entries:
            for entry in entries:
                if _UPLOAD.fullmatch(entry.name) is None:
                    continue
                info = entry.stat(follow_symlinks=False)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or stat.S_IMODE(info.st_mode) & 0o077):
                    continue
                if info.st_nlink == 1:
                    if info.st_mtime < stale_before:
                        current = os.stat(entry.name, dir_fd=root, follow_symlinks=False)
                        if (current.st_ino, current.st_dev, current.st_nlink) == (info.st_ino, info.st_dev, 1):
                            os.unlink(entry.name, dir_fd=root)
                            os.fsync(root)
                    continue
                if (stat.S_IMODE(info.st_mode) != 0o400 or info.st_nlink != 2
                        or not 0 < info.st_size <= _MAX_OBJECT):
                    continue
                fd = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
                with os.fdopen(fd, "rb") as body:
                    if os.fstat(body.fileno()) != info:
                        raise AssetStorageError()
                    data = body.read(info.st_size + 1)
                    digest = hashlib.sha256(data).hexdigest()
                    verify_body(data, digest, info.st_size)
                    try:
                        published = os.stat(digest, dir_fd=root, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    # Recheck the names and descriptor before unlinking; never follow
                    # a symlink or infer ownership from a filename alone.
                    current = os.fstat(body.fileno())
                    temporary = os.stat(entry.name, dir_fd=root, follow_symlinks=False)
                    if (published != current or temporary != current
                            or current.st_nlink != 2 or stat.S_IMODE(current.st_mode) != 0o400):
                        continue
                    os.unlink(entry.name, dir_fd=root)
                    os.fsync(root)
                    self._private_file(os.fstat(body.fileno()))

    def _mark_recovered(self, root: int) -> None:
        with _RECOVERED_GUARD:
            _RECOVERED.add(_root_key(root))

    def _ensure_recovered(self, root: int) -> None:
        """Startup recovery: the first use of a root in this process recovers it."""
        key = _root_key(root)
        with _RECOVERED_GUARD:
            if key in _RECOVERED:
                return
        fcntl.flock(root, fcntl.LOCK_EX)
        try:
            self._recover_publications(root)
        finally:
            fcntl.flock(root, fcntl.LOCK_UN)
        with _RECOVERED_GUARD:
            _RECOVERED.add(key)

    def recover(self) -> None:
        """Explicit startup hook: recover interrupted publications now."""
        with self._locked(fcntl.LOCK_EX) as root:
            self._recover_publications(root)
            self._mark_recovered(root)

    def _read(self, root: int, digest: str, size: int) -> bytes:
        # Validate identity before passing a name to openat, including on corrupt DB rows.
        if not _valid_identity(digest or "", size):
            raise AssetIntegrityError()
        fd = os.open(digest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        with os.fdopen(fd, "rb") as body:
            info = os.fstat(body.fileno())
            self._private_file(info)
            if info.st_size != size:
                raise AssetIntegrityError()
            data = body.read(size + 1)
        return verify_body(data, digest, size)

    def read(self, digest: str, size: int) -> bytes:
        """Return a verified snapshot under a shared lock (never a later-opened file)."""
        if not _valid_identity(digest or "", size):
            raise AssetIntegrityError()
        with self._root() as root:
            self._ensure_recovered(root)
            fcntl.flock(root, fcntl.LOCK_SH)
            try:
                return self._read(root, digest, size)
            finally:
                fcntl.flock(root, fcntl.LOCK_UN)

    def put(self, data: bytes, digest: str, size: int, *, verified: bool = False) -> bool:
        """Durably publish ``data``; return True only when this call created the object.

        ``verified=True`` means the caller already decoded and hashed ``data`` once
        (``decode_inline``); only bounds are re-checked, not the digest.
        """
        if verified:
            if not _valid_identity(digest, size, self.settings.max_object_bytes) or len(data) != size:
                raise AssetIntegrityError()
        else:
            verify_body(data, digest, size, self.settings.max_object_bytes)
        with self._locked(fcntl.LOCK_EX) as root:
            self._recover_publications(root)
            self._mark_recovered(root)
            try:
                self._read(root, digest, size)
            except FileNotFoundError:
                pass
            else:
                os.fsync(root)
                return False
            # Global safety cap across all tenants (per-network quotas are DB-accounted).
            total = count = 0
            with os.scandir(root) as entries:
                for entry in entries:
                    info = entry.stat(follow_symlinks=False)
                    self._private_file(info)
                    total += info.st_size
                    count += 1
                    if count >= self.settings.max_objects or total + size > self.settings.max_total_bytes:
                        raise AssetQuotaError()
            if total + size > self.settings.max_total_bytes:
                raise AssetQuotaError()
            temporary = ".upload-" + uuid.uuid4().hex
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
            try:
                with os.fdopen(fd, "wb") as body:
                    body.write(data)
                    body.flush()
                    os.fchmod(body.fileno(), 0o400)
                    os.fsync(body.fileno())
                # Hard-link publication is atomic and cannot replace an existing identity.
                os.link(temporary, digest, src_dir_fd=root, dst_dir_fd=root, follow_symlinks=False)
            finally:
                os.unlink(temporary, dir_fd=root)
                os.fsync(root)
            published = os.stat(digest, dir_fd=root, follow_symlinks=False)
            self._private_file(published)
            if published.st_size != size:
                raise AssetIntegrityError()
            return True

    def list_objects(self) -> list[str]:
        """Published digest names (shared lock; never includes temporaries)."""
        with self._locked(fcntl.LOCK_SH) as root:
            with os.scandir(root) as entries:
                return sorted(entry.name for entry in entries if _DIGEST.fullmatch(entry.name))

    def remove_unreferenced(self, digest: str) -> bool:
        """Remove one published object the caller proved no asset row references.

        The caller must hold the digest's database advisory lock across its
        reference check and this call. Only a private, single-link regular file
        under the exact digest name is ever removed.
        """
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise AssetIntegrityError()
        with self._locked(fcntl.LOCK_EX) as root:
            try:
                info = os.stat(digest, dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                return False
            self._private_file(info)
            os.unlink(digest, dir_fd=root)
            os.fsync(root)
            return True

    def remove_stale_uploads(self) -> int:
        """Run recovery now; return how many ``.upload-*`` temporaries were removed."""
        with self._locked(fcntl.LOCK_EX) as root:
            with os.scandir(root) as entries:
                before = sum(1 for entry in entries if _UPLOAD.fullmatch(entry.name))
            self._recover_publications(root)
            self._mark_recovered(root)
            with os.scandir(root) as entries:
                after = sum(1 for entry in entries if _UPLOAD.fullmatch(entry.name))
            return before - after
