"""Load only the role's staged secret allowlist; never accept fallback values.

``NANFO_SERVICE_ROLE`` (required, with an explicit ``APP_ENV``) selects the allowlist:
``api`` reads the API volume (JWT signing key plus optional verify-only previous keys,
C19); ``worker`` reads the worker volume and refuses to start if any JWT key file is
mounted (C24). Secret files must be regular, single-link, owner-only (0400) and
bounded. Values supplied through the image/compose environment never pre-empt them.
Key files consumed by path (C15 lab command key, C21 receiver-health keys) are
validated before the command starts so misprovisioning fails closed at start-up.
"""

import os
import re
import stat
import sys
import time
from pathlib import Path
from urllib.parse import quote

SECRET_ROOT = Path("/run/secrets")
_COMMON = {
    "POSTGRES_PASSWORD": "postgres_runtime_password",
    "REDIS_PASSWORD": "redis_password",
    "NEO4J_PASSWORD": "neo4j_password",
}
ROLE_SECRETS = {
    "api": {**_COMMON, "JWT_SECRET_KEY": "jwt_secret"},
    "worker": dict(_COMMON),
}
# Union of every value exported into an application environment (API superset).
SECRETS = ROLE_SECRETS["api"]
JWT_PREVIOUS_FILE = "jwt_previous_secrets"
JWT_FILES = frozenset({"jwt_secret", JWT_PREVIOUS_FILE})
KEY_FILE_ENVIRONMENT = (
    "NANFO_LAB_COMMAND_KEY_FILE",
    "NANFO_RECEIVER_HEALTH_PUBLIC_KEY_FILE",
    "NANFO_RECEIVER_HEALTH_PRIVATE_KEY_FILE",
)
UMASKS = {"077": 0o077, "027": 0o027}
_DERIVED = ("JWT_PREVIOUS_SECRET_KEYS", "TELEMETRY_RETENTION_DSN")
_PREVIOUS_KEY = re.compile(r"[A-Za-z0-9_-]{32,512}")
_HOST = re.compile(r"[A-Za-z0-9.-]{1,253}")


def read_secret(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid not in (0, os.geteuid())
            or info.st_mode & 0o377
            or not 16 <= info.st_size <= 4096
        ):
            raise ValueError("Secret must be a protected owner-readable regular file")
        value = stream.read(4097).decode("utf-8").rstrip("\n")
        if not value or any(char in value for char in "\r\n\x00"):
            raise ValueError("Invalid secret content")
        return value


def check_key_file(path):
    """C15/C21 consumers read these by path; enforce owner-only single-link files."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Key file path must be absolute")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
    finally:
        os.close(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o177
        or not 32 <= info.st_size <= 16384
    ):
        raise ValueError("Key file must be an owner-only 0400/0600 regular file of at least 32 bytes")


def previous_keys(raw, now):
    """``<not_after_epoch>:<key>[,...]``; entries past their overlap window are dropped."""
    keys = []
    for entry in raw.split(","):
        not_after, separator, key = entry.partition(":")
        if not separator or not not_after.isdigit() or not _PREVIOUS_KEY.fullmatch(key):
            raise ValueError("Invalid previous signing-key record")
        if int(not_after) > now:
            keys.append(key)
    return keys


def telemetry_dsn(environ):
    host = environ["POSTGRES_HOST"]
    port = int(environ.get("POSTGRES_PORT", "5432"))
    if not _HOST.fullmatch(host) or not 1 <= port <= 65535:
        raise ValueError("Invalid database endpoint")
    return (
        f"postgresql+asyncpg://{quote(environ['POSTGRES_USER'], safe='')}:"
        f"{quote(environ['POSTGRES_PASSWORD'], safe='')}@{host}:{port}/"
        f"{quote(environ['POSTGRES_DB'], safe='')}"
    )


def prepare(environ, *, secret_root=SECRET_ROOT, now=None):
    """Mutate ``environ`` into the command environment; returns the umask to apply."""
    role = environ.get("NANFO_SERVICE_ROLE")
    if role not in ROLE_SECRETS or not environ.get("APP_ENV", "").strip():
        raise ValueError("Explicit NANFO_SERVICE_ROLE (api|worker) and APP_ENV are required")
    for key in (*SECRETS, *_DERIVED):
        environ.pop(key, None)
        environ.pop(key + "_FILE", None)
    if role == "worker" and any(os.path.lexists(secret_root / name) for name in JWT_FILES):
        raise ValueError("Worker role must not receive JWT signing keys")
    for key, name in ROLE_SECRETS[role].items():
        environ[key] = read_secret(secret_root / name)
    if role == "api" and os.path.lexists(secret_root / JWT_PREVIOUS_FILE):
        keys = previous_keys(read_secret(secret_root / JWT_PREVIOUS_FILE), time.time() if now is None else now)
        if keys:
            environ["JWT_PREVIOUS_SECRET_KEYS"] = ",".join(keys)
    flag = environ.pop("NANFO_TELEMETRY_RETENTION_DSN_FROM_SECRETS", "false")
    if flag not in ("true", "false"):
        raise ValueError("Invalid derived DSN flag")
    if flag == "true":
        environ["TELEMETRY_RETENTION_DSN"] = telemetry_dsn(environ)
    for name in KEY_FILE_ENVIRONMENT:
        if environ.get(name):
            check_key_file(environ[name])
    return UMASKS[environ.get("NANFO_UMASK", "077")]


def main():
    try:
        if os.geteuid() != 10001 or len(sys.argv) < 2:
            raise ValueError("Deployment requires UID 10001 and an explicit command")
        os.umask(prepare(os.environ))
        os.execvp(sys.argv[1], sys.argv[1:])
    except (OSError, ValueError, KeyError):
        sys.exit("Deployment entrypoint refused invalid credentials, role, user or command")


if __name__ == "__main__":
    main()
