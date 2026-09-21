"""Protected POSIX content-addressed storage. No deletion/GC operation exists.

Only digest-derived single-component names are used under an opened private root.
Directory descriptors and O_NOFOLLOW prevent traversal and symlink races. flock
serializes admission/publication across processes; files are durable before SQL
may reference them. A failed SQL transaction deliberately retains published bytes.
"""

from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import os
import re
import stat
import uuid
from contextlib import contextmanager

from app.modules.network.asset_settings import AssetSettings


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


def verify_body(data: bytes, digest: str, size: int, limit: int = 8 * 1024 * 1024) -> bytes:
    if (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(size) is not int or not 0 < size <= limit
            or len(data) != size or hashlib.sha256(data).hexdigest() != digest):
        raise AssetIntegrityError()
    return data


def decode_inline(encoded: str, digest: str, size: int) -> bytes:
    if not isinstance(encoded, str) or len(encoded) > 12_000_000:
        raise AssetIntegrityError()
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise AssetIntegrityError() from exc
    return verify_body(data, digest, size)


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

    @staticmethod
    def _private_file(info):
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
            raise AssetStorageError()

    def _recover_publications(self, root: int) -> None:
        """Under the publication lock, remove only verified interrupted temp links.

        Exactly two links must be accounted for by an owned upload name and its
        verified digest in this directory. Unknown/external aliases are never
        removed or exempted from the normal single-link validation.
        """
        with os.scandir(root) as entries:
            for entry in entries:
                if re.fullmatch(r"\.upload-[0-9a-f]{32}", entry.name) is None:
                    continue
                info = entry.stat(follow_symlinks=False)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                        or stat.S_IMODE(info.st_mode) != 0o400 or info.st_nlink != 2
                        or not 0 < info.st_size <= 8 * 1024 * 1024):
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

    def _read(self, root: int, digest: str, size: int) -> bytes:
        # Validate identity before passing a name to openat, including on corrupt DB rows.
        if re.fullmatch(r"[0-9a-f]{64}", digest or "") is None or not 0 < size <= 8 * 1024 * 1024:
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
        with self._root() as root:
            fcntl.flock(root, fcntl.LOCK_EX)
            try:
                self._recover_publications(root)
                # Return a verified snapshot, never a later-opened FileResponse.
                return self._read(root, digest, size)
            finally:
                fcntl.flock(root, fcntl.LOCK_UN)

    def put(self, data: bytes, digest: str, size: int) -> None:
        verify_body(data, digest, size, self.settings.max_object_bytes)
        with self._root() as root:
            fcntl.flock(root, fcntl.LOCK_EX)
            try:
                self._recover_publications(root)
                try:
                    self._read(root, digest, size)
                except FileNotFoundError:
                    pass
                else:
                    os.fsync(root)
                    return
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
                self._read(root, digest, size)
            finally:
                fcntl.flock(root, fcntl.LOCK_UN)
