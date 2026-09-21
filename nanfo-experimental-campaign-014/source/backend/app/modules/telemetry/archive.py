"""Private durable content-addressed archive. Never accepts caller-chosen paths."""

import hashlib
import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

MAX_RECORD_BYTES = 2 * 1024 * 1024


def canonical_record(record):
    fields = ("record_id", "event_id", "correlation_id", "device_id", "network_id", "workspace_id",
              "metric", "value", "unit", "observed_at", "source", "tags", "created_at")
    value = {field: getattr(record, field) for field in fields}
    for key, item in value.items():
        if isinstance(item, uuid.UUID):
            value[key] = str(item)
        elif isinstance(item, datetime):
            value[key] = item.isoformat()
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(data) > MAX_RECORD_BYTES:
        raise ValueError("archive record exceeds bound")
    return data


class TelemetryArchiveStore:
    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_absolute() or self.root.anchor != "/" or ".." in self.root.parts:
            raise ValueError("absolute private archive directory required")
        with self._walk() as descriptors:
            self._identities = tuple(self._identity(fd) for fd in descriptors)
            self._validate_binding(descriptors)

    @staticmethod
    def _identity(fd):
        info = os.fstat(fd)
        return info.st_dev, info.st_ino

    @staticmethod
    def _check_directory(fd, *, archive):
        info = os.fstat(fd)
        mode = stat.S_IMODE(info.st_mode)
        if archive:
            if info.st_uid != os.geteuid() or mode != 0o700:
                raise ValueError("archive directory must be private mode0700 and owned by current user")
        elif (info.st_uid not in {0, os.geteuid()} or mode & 0o022 and not mode & stat.S_ISVTX):
            # Trusted sticky shared parents such as /tmp are safe for entries owned
            # by us/root. Other group/world-writable ancestors admit replacement.
            raise ValueError("archive ancestor ownership or permissions invalid")

    @contextmanager
    def _walk(self, expected=None):
        """Never pass a multi-component path to open; retain all walked handles."""
        descriptors = []
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            descriptors.append(os.open("/", flags))
            for index, component in enumerate((None, *self.root.parts[1:])):
                if component is not None:
                    descriptors.append(os.open(component, flags, dir_fd=descriptors[-1]))
                fd = descriptors[-1]
                self._check_directory(fd, archive=index == len(self.root.parts) - 1)
                if expected is not None and self._identity(fd) != expected[index]:
                    raise ValueError("archive directory identity changed")
            yield descriptors
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    def _validate_binding(self, descriptors):
        for index, fd in enumerate(descriptors):
            self._check_directory(fd, archive=index == len(descriptors) - 1)
        # Rewalk from /: an opened directory may have been renamed while I/O kept
        # safely using its handle. Such bytes must not authorize a SQL deletion.
        with self._walk(self._identities):
            pass

    @contextmanager
    def _directory(self):
        with self._walk(self._identities) as descriptors:
            yield descriptors[-1]
            self._validate_binding(descriptors)

    def write(self, data):
        if not 0 < len(data) <= MAX_RECORD_BYTES:
            raise ValueError("archive size outside bound")
        digest = hashlib.sha256(data).hexdigest()
        temporary = ".pending-" + uuid.uuid4().hex
        with self._directory() as directory:
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
                with os.fdopen(fd, "wb") as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    os.link(temporary, digest, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                except FileExistsError:
                    pass
                os.unlink(temporary, dir_fd=directory)
                os.fsync(directory)
                if self._read(directory, digest, len(data)) != data:
                    raise ValueError("archive readback mismatch")
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
        return digest

    def read(self, digest, size):
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not 0 < size <= MAX_RECORD_BYTES:
            raise ValueError("invalid archive receipt")
        with self._directory() as directory:
            return self._read(directory, digest, size)

    @staticmethod
    def _read(directory, digest, size):
        fd = os.open(digest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) not in {0o400, 0o600}
                    or info.st_uid != os.geteuid() or info.st_size != size):
                raise ValueError("archive file protection or size invalid")
            data = source.read(MAX_RECORD_BYTES + 1)
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("archive checksum mismatch")
        return data
