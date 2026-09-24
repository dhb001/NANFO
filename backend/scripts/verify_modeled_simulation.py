"""Disposable migrated DB + authenticated HTTP + independent model worker, never a lab.

Run from backend: PYTHONPATH=. poetry run python scripts/verify_modeled_simulation.py --live
"""

import argparse
import asyncio
import copy
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
from neo4j import AsyncGraphDatabase
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.schema_version import CURRENT_SCHEMA
from app.core.security import hash_password
from app.modules.identity.repository import UserRepository
from app.modules.simulation.models import Simulation
from app.modules.simulation.service import SimulationStartService
from scripts.verify_execution import (
    VerificationError,
    check,
    external,
    policy_limits,
    port,
    private_json,
    run_bound_simulation,
    stop,
    until,
)
from tests.simulation_support import completed, scenario


async def verify(directory, artifact):
    configure_logging("CRITICAL")
    logging.disable(logging.CRITICAL)
    backend = Path(__file__).resolve().parents[1]
    suffix = uuid.uuid4().hex
    pg_port, redis_port, neo_port, api_port = port(), port(), port(), port()
    settings = get_settings()
    env = {
        **os.environ,
        **{
            key: str(value)
            for key, value in settings.model_dump(exclude_computed_fields=True).items()
        },
    }
    env.update(
        APP_ENV="verification",
        LOG_LEVEL="CRITICAL",
        EXECUTION_MODE="production",
        EMULATION_CONTROL_ENABLED="false",
        POSTGRES_HOST="127.0.0.1",
        POSTGRES_PORT=str(pg_port),
        POSTGRES_DB="simulation_verify",
        POSTGRES_USER="verifier",
        POSTGRES_PASSWORD=secrets.token_hex(24),
        REDIS_HOST="127.0.0.1",
        REDIS_PORT=str(redis_port),
        REDIS_DB="0",
        REDIS_PASSWORD=secrets.token_hex(24),
        NEO4J_URI=f"bolt://127.0.0.1:{neo_port}",
        NEO4J_USER="neo4j",
        NEO4J_PASSWORD=secrets.token_hex(24),
        JWT_SECRET_KEY=secrets.token_hex(48),
        TELEMETRY_RUNTIME_ADAPTER_MODE="stub",
        EMULATION_SNAPSHOT_PATH="",
        EMULATION_BINDING_PATH="",
        EMULATION_COMMANDS_PATH="",
        EMULATION_RESULTS_PATH="",
        PYTHONPATH=str(backend),
    )
    isolated = Settings(
        _env_file=None, **{key: env[key] for key in Settings.model_fields}
    )
    containers, processes = [], []
    engine = redis = None
    config_path = directory / "redis.conf"
    try:
        artifact["stage"] = "disposable_infrastructure"
        for kind, image, mapping, args, extra in [
            (
                "postgres",
                "postgres:16-alpine",
                f"{pg_port}:5432",
                ["-e", "POSTGRES_USER", "-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_DB"],
                {},
            ),
            (
                "neo4j",
                "neo4j:5.25-community",
                f"{neo_port}:7687",
                [
                    "-e",
                    "NEO4J_AUTH",
                    "-e",
                    "NEO4J_server_memory_heap_initial__size=256m",
                    "-e",
                    "NEO4J_server_memory_heap_max__size=256m",
                    "-e",
                    "NEO4J_server_memory_pagecache_size=128m",
                ],
                {"NEO4J_AUTH": "neo4j/" + env["NEO4J_PASSWORD"]},
            ),
        ]:
            identity = (
                await external(
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    f"nanfo-simulation-{kind}-{suffix}",
                    "--cpus",
                    "1",
                    "--memory",
                    "1g",
                    "-p",
                    "127.0.0.1:" + mapping,
                    *args,
                    image,
                    env={**env, **extra},
                )
            ).strip()
            containers.append(identity)
        fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(
                f'bind 0.0.0.0\nprotected-mode yes\nsave ""\nappendonly no\nrequirepass {env["REDIS_PASSWORD"]}\n'
            )
        containers.append(
            (
                await external(
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    "nanfo-simulation-redis-" + suffix,
                    "--cpus",
                    "0.5",
                    "--memory",
                    "128m",
                    "--user",
                    str(os.geteuid()),
                    "-p",
                    f"127.0.0.1:{redis_port}:6379",
                    "--mount",
                    f"type=bind,source={config_path},target=/run/redis.conf,readonly",
                    "redis:7-alpine",
                    "redis-server",
                    "/run/redis.conf",
                )
            ).strip()
        )
        engine = create_async_engine(isolated.POSTGRES_DSN, echo=False)
        redis = Redis.from_url(isolated.REDIS_URL, decode_responses=True)

        async def database_ready():
            try:
                async with engine.connect() as db:
                    return await db.scalar(text("SELECT 1")) == 1
            except Exception:  # noqa: BLE001
                return False

        await until(database_ready)
        async with AsyncGraphDatabase.driver(
            isolated.NEO4J_URI, auth=(isolated.NEO4J_USER, isolated.NEO4J_PASSWORD)
        ) as driver:

            async def graph_ready():
                try:
                    await driver.verify_connectivity()
                    return True
                except Exception:  # noqa: BLE001
                    return False

            await until(graph_ready, timeout=120)
        await until(redis.ping)
        artifact["stage"] = "migration_and_races"
        await external(
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "alembic/alembic.ini",
            "upgrade",
            CURRENT_SCHEMA,
            cwd=backend,
            env=env,
        )
        artifact["checks"]["postgres"] = await external(
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/test_simulation_postgres.py",
            "-q",
            "--no-cov",
            cwd=backend,
            env={**env, "SIMULATION_TEST_DSN": isolated.POSTGRES_SYNC_DSN},
        )
        artifact["checks"]["intent_postgres"] = await external(
            sys.executable, "-m", "pytest", "tests/integration/test_intent_execution_postgres.py", "-q", "--no-cov",
            cwd=backend, env={**env, "INTENT_TEST_DSN": isolated.POSTGRES_SYNC_DSN,
                              "INTENT_TEST_REDIS_URL": isolated.REDIS_URL},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        password = secrets.token_urlsafe(36)
        async with sessions() as db:
            check(
                await db.scalar(text("SELECT version_num FROM alembic_version"))
                == CURRENT_SCHEMA,
                "Migration mismatch",
            )
            user = await UserRepository(db).create(
                "simulation-verifier@example.com",
                hash_password(password),
                "Simulation verifier",
            )
            await UserRepository(db).assign_role(user.user_id, "Admin")
            outsider = await UserRepository(db).create(
                "simulation-outsider@example.com", hash_password(password), "Outsider"
            )
            await UserRepository(db).assign_role(outsider.user_id, "Admin")
            await db.commit()
        artifact["stage"] = "authenticated_http_worker"
        api = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
            "--log-level",
            "critical",
            "--no-access-log",
            cwd=backend,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        processes.append(api)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{api_port}", timeout=20, trust_env=False
        ) as client:

            async def ready():
                check(api.returncode is None, "API exited")
                try:
                    return (await client.get("/api/openapi.json")).status_code == 200
                except httpx.TransportError:
                    return False

            await until(ready, timeout=120)

            async def request(method, path, *, expected=200, **kwargs):
                response = await client.request(method, path, **kwargs)
                check(
                    response.status_code == expected,
                    f"HTTP {method} {path}: {response.status_code}, expected {expected}",
                )
                value = response.json()
                check(value["success"] == (expected < 400), "Envelope mismatch")
                return value["data"] if expected < 400 else value["errors"]

            login = await request(
                "POST",
                "/api/v1/auth/login",
                json={"email": "simulation-verifier@example.com", "password": password},
            )
            token = login["access_token"]
            client.headers["Authorization"] = "Bearer " + token
            org = await request(
                "POST",
                "/api/v1/organizations",
                expected=201,
                json={"name": "Simulation verifier", "slug": "simulation-verifier"},
            )
            workspace = await request(
                "POST",
                f"/api/v1/organizations/{org['org_id']}/workspaces",
                expected=201,
                json={"name": "Verifier"},
            )
            network = await request(
                "POST",
                "/api/v1/networks",
                expected=201,
                json={
                    "workspace_id": workspace["workspace_id"],
                    "name": "Configured, not observed",
                },
            )
            binding = {
                "intent_id": str(uuid.uuid4()),
                "plan_sha256": "a" * 64,
                "network_state_sha256": "b" * 64,
            }
            config = scenario(action_binding=binding)
            body = {
                "network_id": network["network_id"],
                "scenario_name": "Finite buffer",
                "scenario_config": config.model_dump(mode="json"),
            }
            started = await request(
                "POST", "/api/v1/simulations/start", expected=202, json=body
            )
            sim_id = started["simulation_id"]
            check(started["state"] == "queued", "Configured start not queued")
            check(started["validation"]["source"] == "operator_configured_model"
                  and started["validation"]["physical_safety_authorized"] is False,
                  "Start response lost configured model provenance")
            await request(
                "POST", "/api/v1/simulations/pause", json={"simulation_id": sim_id}
            )
            worker = await asyncio.create_subprocess_exec(
                sys.executable,
                "scripts/run_simulation_worker.py",
                "--batch-ticks",
                "1",
                cwd=backend,
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            processes.append(worker)
            await asyncio.sleep(1)
            paused = await request("GET", f"/api/v1/simulations/{sim_id}")
            check(
                paused["state"] == "paused" and paused["progress"]["tick"] == 0,
                "Worker advanced paused simulation",
            )
            await request(
                "POST",
                "/api/v1/simulations/start",
                expected=202,
                json={**body, "simulation_id": sim_id},
            )

            async def detail():
                check(worker.returncode is None, "Worker exited")
                return await request("GET", f"/api/v1/simulations/{sim_id}")

            done = await until(detail, lambda r: r["state"] == "completed")
            check(
                done["run_output"] == completed(config)[1], "Numerical replay mismatch"
            )
            check(
                done["risk_gate"] == "passed" and done["run_output"]["loss_pct"] == 45,
                "Analytic result mismatch",
            )
            # Its own 100% loss limit passes the model, but is weaker than the server
            # policy floors: this run is never execution evidence (ADR-028 C18).
            check(
                (done.get("execution_policy") or {}).get("limits_respect_policy") is False,
                "Weak scenario limits reported as policy compliant",
            )
            artifact["checks"]["modeled_output"] = done
            branch = await request(
                "POST",
                "/api/v1/simulations/branch",
                expected=201,
                json={"parent_simulation_id": sim_id, "scenario_name": "Replay"},
            )
            branch_id = branch["simulation_id"]
            check(branch["validation"]["source"] == "operator_configured_model"
                  and branch["validation"]["physical_safety_authorized"] is False,
                  "Branch response lost configured model provenance")
            copied = await request("GET", f"/api/v1/simulations/{branch_id}")
            check(
                copied["checkpoint_sha256"] == done["checkpoint_sha256"],
                "Branch did not copy checkpoint",
            )
            await request(
                "POST",
                "/api/v1/simulations/start",
                expected=202,
                json={
                    "network_id": network["network_id"],
                    "scenario_name": "Replay",
                    "simulation_id": branch_id,
                },
            )

            async def branch_detail():
                return await request("GET", f"/api/v1/simulations/{branch_id}")

            await until(branch_detail, lambda r: r["state"] == "completed")
            comparison = await request(
                "GET", f"/api/v1/simulations/{branch_id}/compare/{sim_id}"
            )
            check(
                comparison["compatible"]
                and all(v == 0 for v in comparison["deltas"].values()),
                "Replay comparison mismatch",
            )
            strict = copy.deepcopy(body["scenario_config"])
            strict["limits"]["max_loss_pct"] = 1.0
            failed = await request(
                "POST",
                "/api/v1/simulations/branch",
                expected=201,
                json={
                    "parent_simulation_id": sim_id,
                    "scenario_name": "Strict objective",
                    "scenario_config": strict,
                },
            )
            failed_id = failed["simulation_id"]
            reset = await request("GET", f"/api/v1/simulations/{failed_id}")
            check(
                reset["progress"]["tick"] == 0
                and reset["input_sha256"] != done["input_sha256"],
                "Override did not reset",
            )
            await request(
                "POST",
                "/api/v1/simulations/start",
                expected=202,
                json={
                    "network_id": network["network_id"],
                    "scenario_name": "Strict objective",
                    "simulation_id": failed_id,
                },
            )

            async def failed_detail():
                return await request("GET", f"/api/v1/simulations/{failed_id}")

            rejected = await until(failed_detail, lambda r: r["state"] == "completed")
            check(rejected["risk_gate"] == "blocked", "Failed objective passed")
            artifact["checks"]["failed_objective_completed"] = True
            artifact["checks"]["replay_comparison"] = comparison["deltas"]
            outsider_login = await request(
                "POST",
                "/api/v1/auth/login",
                json={"email": "simulation-outsider@example.com", "password": password},
            )
            client.headers["Authorization"] = "Bearer " + outsider_login["access_token"]
            await request("GET", f"/api/v1/simulations/{sim_id}", expected=403)
            await request(
                "POST",
                "/api/v1/simulations/branch",
                expected=403,
                json={"parent_simulation_id": sim_id, "scenario_name": "Forbidden"},
            )
            client.headers["Authorization"] = "Bearer " + token
            # Execution evidence: a passing run whose limits respect the policy floors and
            # whose scenario_config.action_binding is the intent binding verbatim (C18).
            compliant = await run_bound_simulation(
                client, network_id=network["network_id"], action_binding=binding,
                limits=policy_limits(isolated), timeout=60,
            )
            evidence_id = compliant["simulation_id"]
            artifact["checks"]["policy_compliant_evidence"] = {
                "simulation_id": evidence_id, "execution_policy": compliant["execution_policy"],
            }
            args = {
                "simulation_id": uuid.UUID(evidence_id),
                "workspace_id": uuid.UUID(workspace["workspace_id"]),
                "network_id": uuid.UUID(network["network_id"]),
                "intent_id": uuid.UUID(binding["intent_id"]),
                "actor_id": str(user.user_id),
                "plan_sha256": binding["plan_sha256"],
                "network_state_sha256": binding["network_state_sha256"],
            }
            async with sessions() as db:
                evidence = await SimulationStartService(
                    db=db, redis=redis
                ).validate_execution_reference(**args)
                check(
                    not evidence["physical_safety_authorized"],
                    "Model granted physical safety",
                )
            from fastapi import HTTPException

            async with sessions() as db:
                try:
                    await SimulationStartService(
                        db=db, redis=redis
                    ).validate_execution_reference(**{**args, "simulation_id": uuid.UUID(sim_id)})
                except HTTPException as error:
                    check(
                        error.status_code == 409 and isinstance(error.detail, dict)
                        and error.detail.get("code") == "SIMULATION_POLICY_VIOLATION",
                        "Weak-limit evidence wrong rejection",
                    )
                else:
                    raise VerificationError("Weak-limit simulation accepted as execution evidence")
            for changes in (
                {"plan_sha256": "c" * 64},
                {"network_state_sha256": "d" * 64},
            ):
                async with sessions() as db:
                    try:
                        await SimulationStartService(
                            db=db, redis=redis
                        ).validate_execution_reference(**{**args, **changes})
                    except HTTPException as error:
                        check(error.status_code == 409, "Binding mismatch wrong status")
                    else:
                        raise VerificationError("Changed action/current state accepted")
            async with sessions() as db:
                row = await db.get(Simulation, uuid.UUID(evidence_id))
                row.evidence_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await db.commit()
            async with sessions() as db:
                try:
                    await SimulationStartService(
                        db=db, redis=redis
                    ).validate_execution_reference(**args)
                except HTTPException as error:
                    check(error.status_code == 409, "Stale evidence wrong status")
                else:
                    raise VerificationError("Stale evidence accepted")
            # Even compliant model evidence never authorizes production execution.
            rejected_execution = await request(
                "POST",
                "/api/v1/intents/execute",
                expected=409,
                json={
                    "workspace_id": workspace["workspace_id"],
                    "intent_id": binding["intent_id"],
                    "simulation_id": evidence_id,
                    "manual_approval": True,
                },
            )
            check(
                rejected_execution["code"] == "SIMULATION_EVIDENCE_REJECTED",
                "Production execution rejection code mismatch",
            )
            artifact["checks"]["action_binding_stale_and_production_rejection"] = True
            async with sessions() as db:
                check(
                    await db.scalar(text("SELECT count(*) FROM intent_executions"))
                    == 0,
                    "Unexpected actuation job",
                )
            artifact["checks"]["cross_tenant_denial_no_actuation"] = True
            events = await redis.xrange("stream:simulation")
            check(
                any(e[1]["event_type"] == "simulation.completed" for e in events),
                "No terminal outbox delivery",
            )
        artifact.update(passed=True, stage="complete")
    finally:
        failures = []
        for process in reversed(processes):
            try:
                await stop(process)
            except Exception:  # noqa: BLE001
                failures.append("process_cleanup")
        if redis:
            await redis.aclose()
        if engine:
            await engine.dispose()
        for identity in reversed(containers):
            try:
                await external("docker", "rm", "-f", "-v", identity)
            except Exception:  # noqa: BLE001
                failures.append("container_cleanup")
        config_path.unlink(missing_ok=True)
        artifact["cleanup"] = {"passed": not failures, "failures": failures}
        if failures:
            artifact["passed"] = False


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    if not parser.parse_args().live:
        parser.error("Explicit --live required")
    directory = Path(
        tempfile.mkdtemp(prefix="simulation-verification-", dir="/tmp/opencode")
    )
    artifact = {
        "passed": False,
        "stage": "initializing",
        "checks": {},
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        await verify(directory, artifact)
    except Exception as error:  # noqa: BLE001 - no credentials in failure output
        artifact["failure"] = (
            str(error) if isinstance(error, VerificationError) else type(error).__name__
        )
    artifact["finished_at"] = datetime.now(UTC).isoformat()
    private_json(directory / "result.json", artifact)
    print(
        json.dumps(
            {
                "passed": artifact["passed"],
                "stage": artifact["stage"],
                "artifact": str(directory / "result.json"),
            }
        )
    )
    return 0 if artifact["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
