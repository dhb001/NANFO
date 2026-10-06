"""Fresh-only volume permissions and per-role secret staging (ADR-028 C15/C21/C24).

    volume_init.py                 initialize empty volumes; refuses any nonempty volume
    volume_init.py restage NAME    atomically replace (or remove) one staged secret copy

Runs as root with CHOWN/FOWNER/DAC_OVERRIDE and no network. No recursive chown:
evidence is never rewritten. Local Compose file secrets cannot remap owners, so each
role receives its own copies: the API volume (JWT key), the worker volume (no JWT key),
the execution-worker and lab copies of the mailbox HMAC key, and the init volume.
"""

import os
import secrets
import stat
import sys
from pathlib import Path

from deploy.entrypoint import JWT_PREVIOUS_FILE, ROLE_SECRETS

SOURCE = Path("/source-secrets")
VOLUMES = Path("/volumes")
APP = 10001
LAB_KEY = "lab_command_key"
RECEIVER_PUBLIC = "receiver_health_public_key.pem"
INIT_SECRETS = frozenset({
    "postgres_admin_password",
    "postgres_owner_password",
    "postgres_runtime_password",
    "redis_password",
    "redis_admin_password",
    "neo4j_password",
    "jwt_secret",
    "bootstrap_password",
})
# The C21 receiver signing key is not a source secret: manage.py keeps it in the
# separate ${NANFO_STATE_DIR}/receiver directory, which no container mounts, for
# installation at the receiver only. Verifiers receive the public key.
SOURCE_SECRETS = INIT_SECRETS | {LAB_KEY, RECEIVER_PUBLIC}
OPTIONAL_SOURCES = frozenset({JWT_PREVIOUS_FILE})
# logical volume -> (uid, gid, mode). The C23 lab is root without DAC_OVERRIDE: it
# owns its output/result directories and reads commands through group 10001.
LAYOUT = {
    "reports": (APP, APP, 0o700),
    "network_assets": (APP, APP, 0o700),
    "telemetry_archive": (APP, APP, 0o700),
    "stream_archive": (APP, APP, 0o700),
    "lab_output": (0, APP, 0o750),
    "lab_commands": (APP, APP, 0o750),
    "lab_results": (0, APP, 0o750),
    "runtime_secrets_api": (APP, APP, 0o700),
    "runtime_secrets_worker": (APP, APP, 0o700),
    "execution_secrets": (APP, APP, 0o700),
    "lab_secrets": (0, 0, 0o700),
    "init_secrets": (APP, APP, 0o700),
}
# secret volume -> (file owner uid/gid, staged names)
STAGING = {
    "init_secrets": (APP, INIT_SECRETS),
    "runtime_secrets_api": (APP, frozenset(ROLE_SECRETS["api"].values()) | {JWT_PREVIOUS_FILE, RECEIVER_PUBLIC}),
    "runtime_secrets_worker": (APP, frozenset(ROLE_SECRETS["worker"].values()) | {RECEIVER_PUBLIC}),
    "execution_secrets": (APP, frozenset({LAB_KEY})),
    "lab_secrets": (0, frozenset({LAB_KEY})),
}
STAGED = frozenset().union(*(names for _, names in STAGING.values()))


def source_bytes(source, name):
    path = source / name
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or not 0 < info.st_size <= 16384:
        raise ValueError("Invalid source secret permissions")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        return stream.read(16385)


def write_private(directory, name, data, uid, *, fchown=os.fchown, replace=False):
    """Owner-only 0400 copy; replacement is atomic (temporary + rename + fsync)."""
    target = name
    if replace:
        name = f".{name}.restage-{secrets.token_hex(8)}"
    fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            fchown(stream.fileno(), uid, uid)
            os.fchmod(stream.fileno(), 0o400)
            os.fsync(stream.fileno())
        if replace:
            os.replace(directory / name, directory / target)
    except BaseException:
        if replace:
            (directory / name).unlink(missing_ok=True)
        raise
    sync_directory(directory)


def sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def initialize(*, source=SOURCE, volumes=VOLUMES, chown=os.chown, fchown=os.fchown):
    for name, (uid, gid, mode) in LAYOUT.items():
        path = volumes / name
        if any(path.iterdir()):
            raise ValueError("Refusing to initialize a nonempty volume")
        chown(path, uid, gid)
        os.chmod(path, mode)
    if {path.name for path in source.iterdir()} != SOURCE_SECRETS:
        raise ValueError("Source secrets must match the deployment allowlist")
    for volume, (uid, names) in STAGING.items():
        for name in sorted(names - OPTIONAL_SOURCES):
            write_private(volumes / volume, name, source_bytes(source, name), uid, fchown=fchown)


def restage(name, *, source=SOURCE, volumes=VOLUMES, fchown=os.fchown):
    """Replace one staged secret in every volume that holds it (rotation, C19)."""
    if name not in STAGED:
        raise ValueError("Unknown staged secret")
    present = (source / name).exists() or (source / name).is_symlink()
    if not present and name not in OPTIONAL_SOURCES:
        raise ValueError("Required source secret missing")
    data = source_bytes(source, name) if present else None
    for volume, (uid, names) in sorted(STAGING.items()):
        if name not in names:
            continue
        directory = volumes / volume
        info = directory.lstat()
        owner, group, mode = LAYOUT[volume]
        if not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (owner, group, mode):
            raise ValueError("Staged volume layout differs; refusing restage")
        if data is None:
            (directory / name).unlink(missing_ok=True)
            sync_directory(directory)
        else:
            write_private(directory, name, data, uid, fchown=fchown, replace=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        initialize()
    elif len(argv) == 2 and argv[0] == "restage":
        restage(argv[1])
    else:
        raise SystemExit("usage: volume_init.py [restage NAME]")


if __name__ == "__main__":
    main()
