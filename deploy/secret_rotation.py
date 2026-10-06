"""In-container credential rotation helper; invoked only by ``manage.py rotate``.

    secret_rotation.py apply {postgres_app,postgres_owner,neo4j,redis}
    secret_rotation.py finalize redis

Reads exactly one JSON object ``{"password": "..."}`` from stdin (never argv/env) and
authenticates with the init volume's copies of the current/admin credentials. Every
action is idempotent so an interrupted rotation can be resumed. PostgreSQL receives a
client-computed SCRAM-SHA-256 verifier (never plaintext SQL); Redis receives SHA-256
ACL hashes; Neo4j changes the connecting user's own password. Output never contains
credentials.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path

try:
    from deploy.entrypoint import read_secret
except ModuleNotFoundError:  # Executed by path inside the image.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from deploy.entrypoint import read_secret

SECRET_ROOT = Path("/run/secrets")
ROLES = {"postgres_app": "nanfo_runtime", "postgres_owner": "nanfo_owner"}
REDIS_APP_USER = "nanfo"
REDIS_ADMIN_USER = "nanfo-admin"
# Store entrypoints (redis/neo4j) accept only this generated alphabet and length.
PASSWORD = re.compile(r"[A-Za-z0-9_-]{32,128}")


def read_password(stream):
    value = json.loads(stream.read(4096))
    if not isinstance(value, dict) or set(value) != {"password"} or not isinstance(value["password"], str):
        raise ValueError("Expected one password object")
    if not PASSWORD.fullmatch(value["password"]):
        raise ValueError("Generated password alphabet/length required")
    return value["password"]


def scram_verifier(connection, role, password):
    """libpq computes the SCRAM verifier client-side; the server never sees plaintext."""
    from psycopg2.extensions import encrypt_password

    verifier = encrypt_password(password, role, connection, "scram-sha-256")
    if not isinstance(verifier, str) or not verifier.startswith("SCRAM-SHA-256$") or password in verifier:
        raise ValueError("SCRAM verifier unavailable")
    return verifier


def rotate_postgres(kind, password, *, connect=None, secret_root=SECRET_ROOT):
    import psycopg2
    from psycopg2 import sql

    connect = connect or psycopg2.connect
    role = ROLES[kind]
    host, database = os.environ.get("POSTGRES_HOST", "postgres"), os.environ.get("POSTGRES_DB", "nanfo")
    admin = connect(host=host, dbname=database, user="postgres",
                    password=read_secret(secret_root / "postgres_admin_password"), connect_timeout=10)
    try:
        admin.autocommit = True
        verifier = scram_verifier(admin, role, password)
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(verifier)))
    finally:
        admin.close()
    # Prove the new credential before the caller publishes it.
    connect(host=host, dbname=database, user=role, password=password, connect_timeout=10).close()
    return "applied"


async def rotate_redis(action, password, *, client=None, secret_root=SECRET_ROOT):
    from redis.asyncio import Redis

    client = client or Redis
    options = {"host": os.environ.get("REDIS_HOST", "redis"), "port": int(os.environ.get("REDIS_PORT", "6379")),
               "socket_connect_timeout": 3, "socket_timeout": 5}
    digest = hashlib.sha256(password.encode()).hexdigest()
    # apply: add the new hash beside the old one; finalize: keep only the new hash.
    rules = ["#" + digest] if action == "apply" else ["resetpass", "#" + digest]
    admin = client(username=REDIS_ADMIN_USER, password=read_secret(secret_root / "redis_admin_password"), **options)
    try:
        await admin.execute_command("ACL", "SETUSER", REDIS_APP_USER, *rules)
    finally:
        await admin.aclose()
    probe = client(username=REDIS_APP_USER, password=password, **options)
    try:
        if not await probe.ping():
            raise ValueError("Rotated Redis credential rejected")
    finally:
        await probe.aclose()
    return "applied" if action == "apply" else "finalized"


async def rotate_neo4j(password, *, driver_factory=None, secret_root=SECRET_ROOT):
    from neo4j import AsyncGraphDatabase
    from neo4j.exceptions import AuthError

    factory = driver_factory or AsyncGraphDatabase.driver
    uri, user = os.environ.get("NEO4J_URI", "bolt://neo4j:7687"), os.environ.get("NEO4J_USER", "neo4j")
    old = read_secret(secret_root / "neo4j_password")
    for candidate in dict.fromkeys((password, old)):
        driver = factory(uri, auth=(user, candidate))
        try:
            await driver.verify_connectivity()
        except AuthError:
            continue
        else:
            if candidate == password:
                return "already_applied"
            async with driver.session(database="system") as session:
                result = await session.run("ALTER CURRENT USER SET PASSWORD FROM $old TO $new",
                                           old=old, new=password)
                await result.consume()
        finally:
            await driver.close()
        probe = factory(uri, auth=(user, password))
        try:
            await probe.verify_connectivity()
        finally:
            await probe.close()
        return "applied"
    raise ValueError("Neither the current nor the new Neo4j credential authenticates")


def execute(action, kind, password):
    if action == "finalize":
        if kind != "redis":
            raise ValueError("Only Redis rotation has a finalize step")
        return asyncio.run(rotate_redis("finalize", password))
    if kind in ROLES:
        return rotate_postgres(kind, password)
    if kind == "redis":
        return asyncio.run(rotate_redis("apply", password))
    if kind == "neo4j":
        return asyncio.run(rotate_neo4j(password))
    raise ValueError("Unknown rotation")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["apply", "finalize"])
    parser.add_argument("secret", choices=[*ROLES, "neo4j", "redis"])
    args = parser.parse_args(argv)
    try:
        status = execute(args.action, args.secret, read_password(sys.stdin))
    except Exception as exc:  # noqa: BLE001 - driver errors may embed credentials
        print(json.dumps({"status": "refused", "secret": args.secret, "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({"status": status, "secret": args.secret}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
