#!/usr/bin/env bash
set -euo pipefail

# Starts NANFO local development dependencies (Postgres, Neo4j, Redis)
# using backend/docker-compose.yml.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"

# Never trace credential provisioning, even when invoked with bash -x.
set +x
umask 077

if ! command -v python3 >/dev/null 2>&1; then
  echo "[error] python3 is required to provision private local credentials."
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[error] docker not found. Install dependencies first: ./scripts/install-deps-arch.sh"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "[error] Docker daemon is not available. Start it manually and retry."
  exit 1
fi

cd "${BACKEND_DIR}"

# Require bounded health-wait support before creating any containers.
COMPOSE_HELP="$(docker compose up --help)"
if [[ "$COMPOSE_HELP" != *"--wait-timeout"* ]]; then
  echo "[error] Docker Compose with up --wait --wait-timeout support is required. Upgrade Compose."
  exit 1
fi
WAIT_SECONDS="${NANFO_DEV_WAIT_SECONDS:-180}"
if [[ ! "$WAIT_SECONDS" =~ ^[1-9][0-9]{0,3}$ ]] || (( WAIT_SECONDS > 3600 )); then
  echo "[error] NANFO_DEV_WAIT_SECONDS must be an integer from 1 to 3600."
  exit 1
fi

python3 - <<'PY'
import errno
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile

names = ("POSTGRES_PASSWORD", "NEO4J_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET_KEY")


def jwt_key():
    # Backend Settings require >= 32 bytes and >= 10 distinct characters outside APP_ENV=test.
    while True:
        value = secrets.token_hex(32)
        if len(set(value)) >= 10:
            return value


def restrict_existing_env():
    """Owner-only permissions for backend/.env; never follow or modify through a symlink."""
    try:
        fd = os.open(".env", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            sys.exit("[error] backend/.env must be a regular file, not a symlink; it was left untouched.")
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            sys.exit("[error] backend/.env must be a regular file; it was left untouched.")
        if info.st_uid != os.geteuid():
            sys.exit("[error] backend/.env must be owned by the current user; it was left untouched.")
        if stat.S_IMODE(info.st_mode) & 0o077:
            os.fchmod(fd, 0o600)
            print("[info] Restricted existing backend/.env to mode 0600 (owner read/write only).")
    finally:
        os.close(fd)


try:
    if not os.path.lexists(".env"):
        sample = Path(".env.example").read_text()
        lines = []
        for line in sample.splitlines():
            key = line.partition("=")[0]
            if key == "JWT_SECRET_KEY":
                lines.append(f"{key}={jwt_key()}")
            elif key in names:
                lines.append(f"{key}={secrets.token_hex(32)}")
            elif key == "APP_ENV":
                # Settings default to production (fail closed); local stores are explicitly dev.
                lines.append("APP_ENV=development")
            else:
                lines.append(line)
        if "APP_ENV=development" not in lines:
            lines.insert(0, "APP_ENV=development")
        # Publish complete bytes atomically. A concurrent/existing env wins;
        # even dangling symlinks are never replaced or followed for writing.
        fd, temporary = tempfile.mkstemp(prefix=".env-", dir=".")
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write("\n".join(lines) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, ".env")
                print("[info] Generated private backend/.env credentials (mode 0600).")
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    restrict_existing_env()

    # Validate the effective Compose config, including shell overrides, without
    # sourcing executable env content or emitting rendered credentials/errors.
    result = subprocess.run(
        ["docker", "compose", "--env-file", ".env", "-f", "docker-compose.yml",
         "config", "--format", "json"], capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        sys.exit("[error] Invalid Compose configuration. Fill all four secrets in backend/.env.")
    config = json.loads(result.stdout)
    services = config["services"]
    values = {
        "POSTGRES_PASSWORD": services["postgres"]["environment"]["POSTGRES_PASSWORD"],
        "NEO4J_PASSWORD": services["neo4j"]["environment"]["NEO4J_AUTH"].partition("/")[2],
        "REDIS_PASSWORD": services["redis"]["environment"]["REDIS_PASSWORD"],
        "JWT_SECRET_KEY": config["x-required-credentials"]["JWT_SECRET_KEY"],
    }
    for key, value in values.items():
        minimum = 32 if key == "JWT_SECRET_KEY" else 16
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if (len(value.encode()) < minimum or not value.strip()
                or "change_me" in normalized or "changeme" in normalized
                or normalized in {"nanfo_dev_secret", "nanfo_test", "test_secret_key_32_chars_minimum!"}
                or (key == "JWT_SECRET_KEY" and len(set(value)) < 10)
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            sys.exit(f"[error] {key} requires a non-placeholder secret of at least {minimum} characters; existing env preserved.")
    # The dev Redis ACL config is rendered from these values (see docker-compose.yml).
    if re.search(r"[\s\"'\\]", values["REDIS_PASSWORD"]):
        sys.exit("[error] REDIS_PASSWORD must not contain whitespace, quotes or backslashes; existing env preserved.")
    username = services["redis"]["environment"]["REDIS_USERNAME"]
    if username == "default" or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", username):
        sys.exit("[error] REDIS_USERNAME must be a plain ACL user name other than 'default'; existing env preserved.")
except (OSError, ValueError, KeyError, IndexError, TypeError, subprocess.TimeoutExpired):
    sys.exit("[error] Local credential provisioning/configuration failed; inspect backend/.env privately.")
PY

echo "[step] Starting infrastructure and waiting up to ${WAIT_SECONDS}s for healthy stores..."
if ! docker compose --env-file .env -f docker-compose.yml up -d --wait --wait-timeout "$WAIT_SECONDS"; then
  echo "[error] Infrastructure did not become healthy within the bounded startup wait."
  exit 1
fi

echo

echo "[done] NANFO development stores are healthy. API and workers are separate processes."
echo "[info] PostgreSQL: localhost:5432"
echo "[info] Neo4j HTTP: http://localhost:7474  | Bolt: localhost:7687"
echo "[info] Redis: localhost:6379"
echo

echo "[next] Optional backend app run:"
echo "       cd backend && poetry install && poetry run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
