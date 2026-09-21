"""Opt-in non-actuating ADR-012 verifier using disposable infrastructure only.

From backend: PYTHONPATH=. poetry run python scripts/verify_autonomy.py --live
Never starts a lab, enables execution, or migrates the configured shared database.
"""

import argparse
import asyncio
import json
import logging
import os
import secrets
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.modules.identity.repository import UserRepository
from scripts.verify_execution import (
    VerificationError,
    check,
    external,
    port,
    private_json,
    stop,
    until,
)


async def verify(directory, artifact):
    settings = get_settings()
    configure_logging("CRITICAL")
    logging.disable(logging.CRITICAL)
    backend = Path(__file__).resolve().parents[1]
    suffix = uuid.uuid4().hex
    postgres_port, redis_port, neo_port, api_port = port(), port(), port(), port()
    env = {**os.environ, **{key: str(value) for key, value in settings.model_dump(exclude_computed_fields=True).items()}}
    env.update(APP_ENV="verification", LOG_LEVEL="CRITICAL", EXECUTION_MODE="emulation", EMULATION_CONTROL_ENABLED="false",
        POSTGRES_HOST="127.0.0.1", POSTGRES_PORT=str(postgres_port), POSTGRES_DB="autonomy_verify", POSTGRES_USER="verifier",
        POSTGRES_PASSWORD=secrets.token_hex(24), REDIS_HOST="127.0.0.1", REDIS_PORT=str(redis_port), REDIS_DB="0",
        REDIS_PASSWORD=secrets.token_hex(24), NEO4J_URI=f"bolt://127.0.0.1:{neo_port}", NEO4J_USER="neo4j",
        NEO4J_PASSWORD=secrets.token_hex(24), JWT_SECRET_KEY=secrets.token_hex(48), TELEMETRY_RUNTIME_ADAPTER_MODE="stub",
        EMULATION_SNAPSHOT_PATH="", EMULATION_BINDING_PATH="", EMULATION_COMMANDS_PATH="", EMULATION_RESULTS_PATH="",
        PYTHONPATH=str(backend))
    isolated = Settings(_env_file=None, **{key: env[key] for key in Settings.model_fields})
    containers, processes = [], []
    engine = None
    config = directory / "redis.conf"
    try:
        artifact["stage"] = "disposable_infrastructure"
        for kind, image, mapping, args, extra in [
            ("postgres", "postgres:16-alpine", f"{postgres_port}:5432", ["-e", "POSTGRES_USER", "-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_DB"], {}),
            ("neo4j", "neo4j:5.25-community", f"{neo_port}:7687", ["-e", "NEO4J_AUTH", "-e", "NEO4J_server_memory_heap_initial__size=256m",
                "-e", "NEO4J_server_memory_heap_max__size=256m", "-e", "NEO4J_server_memory_pagecache_size=128m"],
                {"NEO4J_AUTH": "neo4j/" + env["NEO4J_PASSWORD"]}),
        ]:
            name = "nanfo-autonomy-" + kind + "-" + suffix
            identity = (await external("docker", "run", "-d", "--name", name, "-p", "127.0.0.1:" + mapping,
                                      *args, image, env={**env, **extra})).strip()
            containers.append(identity)
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(f'bind 0.0.0.0\nprotected-mode yes\nsave ""\nappendonly no\nrequirepass {env["REDIS_PASSWORD"]}\n')
        containers.append((await external("docker", "run", "-d", "--name", "nanfo-autonomy-redis-" + suffix,
            "--user", str(os.geteuid()), "-p", f"127.0.0.1:{redis_port}:6379",
            "--mount", f"type=bind,source={config},target=/run/redis.conf,readonly", "redis:7-alpine",
            "redis-server", "/run/redis.conf")).strip())
        engine = create_async_engine(isolated.POSTGRES_DSN, echo=False)
        async def database_ready():
            try:
                async with engine.connect() as db:
                    return await db.scalar(text("SELECT 1")) == 1
            except Exception:  # noqa: BLE001
                return False
        await until(database_ready)
        artifact["stage"] = "migration_and_lock_tests"
        await external(sys.executable, "-m", "alembic", "-c", "alembic/alembic.ini", "upgrade", "0015", cwd=backend, env=env)
        output = await external(sys.executable, "-m", "pytest", "tests/integration/test_autonomy_postgres.py", "-q", "--no-cov",
            env={**env, "AUTONOMY_TEST_DSN": isolated.POSTGRES_SYNC_DSN}, cwd=backend)
        artifact["checks"]["postgres_tests"] = output.strip()
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            check(await db.scalar(text("SELECT version_num FROM alembic_version")) == "0015", "Migration mismatch")
            password = secrets.token_urlsafe(36)
            user = await UserRepository(db).create("autonomy-verifier@example.com", hash_password(password), "Autonomy verifier")
            await UserRepository(db).assign_role(user.user_id, "Admin")
            await db.commit()
        artifact["stage"] = "live_http"
        api = await asyncio.create_subprocess_exec(sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
            "--port", str(api_port), "--log-level", "critical", "--no-access-log", cwd=backend, env=env,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        processes.append(api)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{api_port}", timeout=15, trust_env=False) as client:
            async def ready():
                check(api.returncode is None, "API exited during startup")
                try:
                    return (await client.get("/api/openapi.json")).status_code == 200
                except httpx.TransportError:
                    return False
            await until(ready, timeout=120)
            async def request(method, path, *, expected=200, **kwargs):
                response = await client.request(method, path, **kwargs)
                check(response.status_code == expected, f"HTTP {method} {path}: {response.status_code}")
                value = response.json()
                check(value["success"] == (expected < 400), "Envelope mismatch")
                return value["data"] if expected < 400 else value["errors"]
            login = await request("POST", "/api/v1/auth/login", json={"email": "autonomy-verifier@example.com", "password": password})
            client.headers["Authorization"] = "Bearer " + login["access_token"]
            org = await request("POST", "/api/v1/organizations", expected=201, json={"name": "Autonomy verifier", "slug": "autonomy-verifier"})
            workspace = await request("POST", f'/api/v1/organizations/{org["org_id"]}/workspaces', expected=201, json={"name": "Verifier"})
            network = await request("POST", "/api/v1/networks", expected=201, json={"workspace_id": workspace["workspace_id"], "name": "Non-actuating verifier"})
            scope = {"network_id": network["network_id"]}
            configuration = await request("GET", "/api/v1/autonomy/configuration", params=scope)
            check(configuration["revision"] == 0 and configuration["effective_training"] is None, "Initial configuration mismatch")
            config_request = {**scope, "expected_revision": 0, "reason": "Disposable verifier requested settings",
                              "operational": {"decision_interval_seconds": 2}, "training": {"reward_weights": {"delay": -.2}}}
            configuration = await request("PUT", "/api/v1/autonomy/configuration", json=config_request)
            check(configuration["training_status"] == "retraining_required" and configuration["effective_training"] is None,
                  "Requested training was incorrectly promoted")
            await request("PUT", "/api/v1/autonomy/configuration", expected=409, json=config_request)
            overrides = await request("GET", "/api/v1/autonomy/overrides", params=scope)
            check(overrides["overrides"] == [], "Unexpected override")
            await request("POST", "/api/v1/autonomy/overrides", expected=404, json={**scope,
                "expected_revision": overrides["control_revision"], "reason": "Cannot adopt missing execution",
                "duration_seconds": 10, "return_mode": "monitor", "intent_id": str(uuid.uuid4()), "execution_id": str(uuid.uuid4())})
            artifact["checks"]["operator_configuration"] = configuration
            await request("PUT", "/api/v1/autonomy", json={**scope, "mode": "monitor", "expected_revision": configuration["control_revision"]})
            worker = await asyncio.create_subprocess_exec(sys.executable, "scripts/run_autonomy_worker.py", cwd=backend, env=env,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            processes.append(worker)
            async def status():
                return await request("GET", "/api/v1/autonomy", params=scope)
            observed = await until(status, lambda row: row["last_decision"] and row["last_decision"]["status"] == "observed", timeout=35)
            check(observed["last_observation"]["samples"] == [], "Unexpected fabricated telemetry")
            artifact["checks"]["monitor"] = observed
            await request("PUT", "/api/v1/autonomy", json={**scope, "mode": "recommend", "expected_revision": observed["revision"]})
            recommended = await until(status, lambda row: row["last_decision"] and row["last_decision"]["status"] == "blocked", timeout=35)
            check("qualified_checkpoint_unavailable" in recommended["last_decision"]["reasons"], "Missing recommendation blocker")
            artifact["checks"]["recommend"] = recommended
            artifact["checks"]["autonomous_rejected"] = await request("PUT", "/api/v1/autonomy", expected=409,
                json={**scope, "mode": "autonomous", "expected_revision": recommended["revision"], "checkpoint_sha256": "a" * 64,
                      "approval_expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()})
            check((await status())["mode"] == "recommend", "Rejected PUT changed mode")
            stopped = await request("POST", "/api/v1/autonomy/stop", json=scope)
            check(stopped["emergency_stopped"] and stopped["active_execution_id"] is None, "Stop not persisted")
            conflict = await request("PUT", "/api/v1/autonomy", expected=409,
                json={**scope, "mode": "monitor", "expected_revision": recommended["revision"]})
            check(conflict["code"] == "AUTONOMY_REVISION_CONFLICT", "Stale mode change not rejected")
            check((await status())["emergency_stopped"], "Stale PUT cleared newer stop")
            artifact["checks"]["stale_put_preserves_stop"] = True
            artifact["checks"]["stop"] = stopped
            await stop(worker)
            await stop(api)
            async with sessions() as db:
                check(await db.scalar(text("SELECT count(*) FROM intent_executions")) == 0, "Unexpected execution")
                check(await db.scalar(text("SELECT count(*) FROM autonomy_controls WHERE emergency_stopped")) == 1, "Latch not durable")
            artifact["checks"]["no_actuation"] = True
        artifact.update(passed=True, stage="complete")
    finally:
        failures = []
        for process in reversed(processes):
            try:
                await stop(process)
            except Exception:  # noqa: BLE001
                failures.append("process_cleanup")
        if engine:
            await engine.dispose()
        for identity in reversed(containers):
            try:
                await external("docker", "rm", "-f", "-v", identity)
            except Exception:  # noqa: BLE001
                failures.append("container_cleanup")
        config.unlink(missing_ok=True)
        artifact["cleanup"] = {"passed": not failures, "failures": failures}
        if failures:
            artifact["passed"] = False


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    if not parser.parse_args().live:
        parser.error("Explicit --live required")
    directory = Path(tempfile.mkdtemp(prefix="autonomy-verification-", dir="/tmp/opencode"))
    artifact = {"passed": False, "stage": "initializing", "checks": {}, "started_at": datetime.now(UTC).isoformat()}
    try:
        await verify(directory, artifact)
    except Exception as error:  # noqa: BLE001 - never expose credentials from infrastructure errors
        artifact["failure"] = str(error) if isinstance(error, VerificationError) else type(error).__name__
    artifact["finished_at"] = datetime.now(UTC).isoformat()
    private_json(directory / "result.json", artifact)
    print(json.dumps({"passed": artifact["passed"], "stage": artifact["stage"], "artifact": str(directory / "result.json")}))
    return 0 if artifact["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
