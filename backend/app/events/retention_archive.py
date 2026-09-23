"""ADR027 private, atomic, content-addressed stream bundles (manifest + bytes).

Descriptor-walk protection follows the existing telemetry archive contract, without
coupling domain stream retention to a module's data or persistence implementation.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

MAX_BUNDLE_BYTES = 2 * 1024 * 1024


class StreamArchive:
    def __init__(self, root: Path):
        self.root = Path(root)
        if not self.root.is_absolute() or '..' in self.root.parts:
            raise ValueError('absolute private archive root required')
        with self._walk() as descriptors:
            self.identities = tuple(self._identity(fd) for fd in descriptors)
        self.verify_binding()

    @staticmethod
    def _identity(fd):
        info = os.fstat(fd)
        return info.st_dev, info.st_ino

    @contextmanager
    def _walk(self):
        descriptors = []
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            descriptors.append(os.open('/', flags))
            for component in self.root.parts[1:]:
                descriptors.append(os.open(component, flags, dir_fd=descriptors[-1]))
            for index, fd in enumerate(descriptors):
                info = os.fstat(fd)
                mode = stat.S_IMODE(info.st_mode)
                if index == len(descriptors) - 1:
                    if info.st_uid != os.geteuid() or mode != 0o700:
                        raise ValueError('archive root requires owner mode0700')
                elif info.st_uid not in {0, os.geteuid()} or (mode & 0o022 and not mode & stat.S_ISVTX):
                    raise ValueError('unprotected archive ancestor')
            if hasattr(self, 'identities') and tuple(map(self._identity, descriptors)) != self.identities:
                raise ValueError('archive path identity changed')
            yield descriptors
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    def verify_binding(self):
        with self._walk():
            pass

    @contextmanager
    def exclusive(self):
        """Serialize admission/writes across operators sharing this archive root."""
        with self._walk() as descriptors:
            fd = descriptors[-1]
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
                self.verify_binding()
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)

    def free_bytes(self):
        with self._walk() as descriptors:
            info = os.fstatvfs(descriptors[-1])
            return info.f_bavail * info.f_frsize

    def write(self, data: bytes, *, min_free_bytes: int):
        if not 0 < len(data) <= MAX_BUNDLE_BYTES:
            raise ValueError('archive bundle size outside bound')
        digest = hashlib.sha256(data).hexdigest()
        temporary = '.pending-' + uuid.uuid4().hex
        with self._walk() as descriptors:
            directory = descriptors[-1]
            info = os.fstatvfs(directory)
            # Reserve allocation rounding and directory metadata as well as payload.
            required = ((len(data) + info.f_frsize - 1) // info.f_frsize + 4) * info.f_frsize
            if info.f_bavail * info.f_frsize - required < min_free_bytes:
                raise ValueError('archive_disk_admission')
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
                with os.fdopen(fd, 'wb') as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    os.link(temporary, digest, src_dir_fd=directory, dst_dir_fd=directory,
                            follow_symlinks=False)
                except FileExistsError:
                    pass
                os.unlink(temporary, dir_fd=directory)
                os.fsync(directory)
                if self._read(directory, digest) != data:
                    raise ValueError('archive readback mismatch')
                self.verify_binding()
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
        return digest

    @staticmethod
    def _read(directory, digest):
        fd = os.open(digest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) not in {0o400, 0o600}
                    or info.st_uid != os.geteuid() or info.st_nlink != 1
                    or not 0 < info.st_size <= MAX_BUNDLE_BYTES):
                raise ValueError('archive file protection or size invalid')
            data = source.read(MAX_BUNDLE_BYTES + 1)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('archive checksum mismatch')
        return data

    def read(self, digest: str):
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('invalid archive digest')
        with self._walk() as descriptors:
            data = self._read(descriptors[-1], digest)
            self.verify_binding()
            return data
