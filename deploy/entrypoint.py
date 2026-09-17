"""Read only the mounted deployment secret allowlist; never accept fallback values."""

import os
from pathlib import Path
import stat
import sys

SECRETS = {
    "POSTGRES_PASSWORD": "postgres_runtime_password",
    "REDIS_PASSWORD": "redis_password",
    "NEO4J_PASSWORD": "neo4j_password",
    "JWT_SECRET_KEY": "jwt_secret",
}


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


def main():
    try:
        if os.geteuid() != 10001 or len(sys.argv) < 2:
            raise ValueError("Deployment requires UID 10001 and an explicit command")
        for key, name in SECRETS.items():
            os.environ[key] = read_secret(Path("/run/secrets") / name)
            os.environ.pop(key + "_FILE", None)
        os.umask(0o077)
        os.execvp(sys.argv[1], sys.argv[1:])
    except (OSError, ValueError):
        sys.exit("Deployment entrypoint refused invalid credentials, user or command")


if __name__ == "__main__":
    main()
