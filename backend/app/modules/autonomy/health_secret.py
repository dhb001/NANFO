"""Descriptor-bound confidential key read, separate from public evidence policy."""

import hashlib
import os
from pathlib import Path, PurePosixPath
import stat


def read_health_secret(root, reference):
    root = Path(root)
    relative = PurePosixPath(reference.path)
    if (not root.is_absolute() or ".." in root.parts or not reference.path
            or relative.is_absolute() or str(relative) != reference.path
            or any(p in {"", ".", ".."} for p in reference.path.split("/"))):
        raise ValueError("health_secret_path_invalid")
    descriptors = []
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        for component in (*root.parts[1:], *relative.parts[:-1]):
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
            info = os.fstat(fd)
            sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if info.st_uid not in {0, os.geteuid()} or (info.st_mode & 0o022 and not sticky_root):
                raise ValueError("health_secret_ancestor_unprotected")
        fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        descriptors.append(fd)
        before = os.fstat(fd)
        def private(info):
            return (stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_uid in {0, os.geteuid()} and info.st_nlink == 1
                    and 32 <= info.st_size <= 4096)
        if not private(before) or before.st_size != reference.size_bytes:
            raise ValueError("health_secret_requires_private_0600")
        with os.fdopen(os.dup(fd), "rb") as stream:
            content = stream.read(4097)
        after = os.fstat(fd)
        if (not private(after) or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or len(content) != before.st_size or hashlib.sha256(content).hexdigest() != reference.sha256):
            raise ValueError("health_secret_changed_or_hash_mismatch")
        # Recheck permissions on the opened ancestry, not a later pathname target.
        for directory in descriptors[:-1]:
            info = os.fstat(directory)
            if info.st_uid not in {0, os.geteuid()} or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)):
                raise ValueError("health_secret_ancestor_unprotected")
        return content
    except OSError as exc:
        raise ValueError("health_secret_unreadable_or_symlink") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
