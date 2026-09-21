"""Opt-in real disposable PostgreSQL/Redis/API/worker report verification. No lab.

From backend, with its Poetry environment: python -m scripts.verify_reports --live
"""

import argparse
import asyncio
import csv
import hashlib
import io
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
from pypdf import PdfReader
from redis.asyncio import Redis
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.modules.identity.repository import UserRepository
from app.modules.alert.models import AlertRecord
from app.modules.intent.models import Intent
from app.modules.intent.lab import digest as plan_digest
from app.modules.organization.models import OrgMember
from app.modules.report.models import ReportRecord
from app.modules.telemetry.models import TelemetryRecord
from scripts.verify_execution import check, external, port, private_json, stop, until
from tests.simulation_support import record as simulation_record


async def verify(directory, evidence):
    configure_logging("CRITICAL")
    logging.disable(logging.CRITICAL)
    backend = Path(__file__).resolve().parents[1]
    ports = {key: port() for key in ("pg", "redis", "neo", "api")}
    suffix = uuid.uuid4().hex
    env = {
        **os.environ,
        **{
            key: str(value)
            for key, value in get_settings()
            .model_dump(exclude_computed_fields=True)
            .items()
        },
    }
    env.pop("VIRTUAL_ENV", None)
    env.pop("CONDA_PREFIX", None)
    storage = directory / "artifacts"
    storage.mkdir(mode=0o700)
    env.update(
        APP_ENV="verification",
        LOG_LEVEL="CRITICAL",
        EXECUTION_MODE="production",
        EMULATION_CONTROL_ENABLED="false",
        EMULATION_SNAPSHOT_PATH="",
        EMULATION_BINDING_PATH="",
        EMULATION_COMMANDS_PATH="",
        EMULATION_RESULTS_PATH="",
        TELEMETRY_RUNTIME_ADAPTER_MODE="stub",
        POSTGRES_HOST="127.0.0.1",
        POSTGRES_PORT=str(ports["pg"]),
        POSTGRES_DB="report_verify",
        POSTGRES_USER="verifier",
        POSTGRES_PASSWORD=secrets.token_hex(24),
        REDIS_HOST="127.0.0.1",
        REDIS_PORT=str(ports["redis"]),
        REDIS_DB="0",
        REDIS_PASSWORD=secrets.token_hex(24),
        NEO4J_URI=f"bolt://127.0.0.1:{ports['neo']}",
        NEO4J_USER="neo4j",
        NEO4J_PASSWORD=secrets.token_hex(24),
        JWT_SECRET_KEY=secrets.token_hex(48),
        PYTHONPATH=str(backend),
        REPORTS_STORAGE_PATH=str(storage),
    )
    settings = Settings(
        _env_file=None, **{key: env[key] for key in Settings.model_fields}
    )
    containers, processes = [], []
    engine = redis = None
    try:
        evidence["stage"] = "isolated_infrastructure"
        for kind, image, mapping, args, extra in (
            (
                "pg",
                "postgres:16-alpine",
                f"{ports['pg']}:5432",
                ["-e", "POSTGRES_USER", "-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_DB"],
                {},
            ),
            (
                "neo",
                "neo4j:5.25-community",
                f"{ports['neo']}:7687",
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
        ):
            containers.append(
                (
                    await external(
                        "docker",
                        "run",
                        "-d",
                        "--name",
                        f"nanfo-report-{kind}-{suffix}",
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
            )
        config = directory / "redis.conf"
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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
                    f"nanfo-report-redis-{suffix}",
                    "--cpus",
                    "0.5",
                    "--memory",
                    "128m",
                    "--user",
                    str(os.geteuid()),
                    "-p",
                    f"127.0.0.1:{ports['redis']}:6379",
                    "--mount",
                    f"type=bind,source={config},target=/run/redis.conf,readonly",
                    "redis:7-alpine",
                    "redis-server",
                    "/run/redis.conf",
                )
            ).strip()
        )
        engine = create_async_engine(settings.POSTGRES_DSN)
        redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)

        async def pg_ready():
            try:
                async with engine.connect() as db:
                    return await db.scalar(text("SELECT 1")) == 1
            except Exception:
                return False

        await until(pg_ready)
        await until(redis.ping)
        async with AsyncGraphDatabase.driver(
            settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        ) as graph:

            async def neo_ready():
                try:
                    await graph.verify_connectivity()
                    return True
                except Exception:
                    return False

            await until(neo_ready, timeout=120)
        evidence["stage"] = "migrations_and_transaction_tests"
        await external(
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "alembic/alembic.ini",
            "upgrade",
            "0017",
            cwd=backend,
            env=env,
        )
        evidence["postgres_tests"] = await external(
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/test_report_postgres.py",
            "-q",
            "--no-cov",
            cwd=backend,
            env={
                **env,
                "REPORT_TEST_DSN": settings.POSTGRES_SYNC_DSN,
                "REPORT_TEST_REDIS_URL": settings.REDIS_URL,
            },
        )
        # Current Alert public service requires its separately owned ADR019 migration.
        await external(
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "alembic/alembic.ini",
            "upgrade",
            "0018",
            cwd=backend,
            env=env,
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        password = secrets.token_urlsafe(36)
        async with sessions() as db:
            users = []
            for name in ("owner", "outsider"):
                user = await UserRepository(db).create(
                    f"report-{name}@example.com", hash_password(password), name
                )
                await UserRepository(db).assign_role(user.user_id, "Admin")
                users.append(user)
            await db.commit()
        api = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(ports["api"]),
            "--log-level",
            "critical",
            "--no-access-log",
            cwd=backend,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        processes.append(api)
        evidence["stage"] = "authenticated_api_and_frozen_source"
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{ports['api']}", timeout=30, trust_env=False
        ) as client:

            async def ready():
                check(api.returncode is None, "API exited")
                try:
                    return (await client.get("/api/openapi.json")).status_code == 200
                except httpx.TransportError:
                    return False

            await until(ready, timeout=120)

            async def request(method, path, expected=200, **kwargs):
                response = await client.request(method, path, **kwargs)
                check(
                    response.status_code == expected,
                    f"{method} {path}: {response.status_code}, expected {expected}",
                )
                body = response.json()
                check(body["success"] == (expected < 400), "Envelope mismatch")
                return body["data"] if expected < 400 else body["errors"]

            tenants = []
            for name in ("owner", "outsider"):
                login = await request(
                    "POST",
                    "/api/v1/auth/login",
                    json={"email": f"report-{name}@example.com", "password": password},
                )
                client.headers["Authorization"] = "Bearer " + login["access_token"]
                org = await request(
                    "POST",
                    "/api/v1/organizations",
                    201,
                    json={"name": name, "slug": "report-" + name},
                )
                ws = await request(
                    "POST",
                    f"/api/v1/organizations/{org['org_id']}/workspaces",
                    201,
                    json={"name": name},
                )
                network = await request(
                    "POST",
                    "/api/v1/networks",
                    201,
                    json={"workspace_id": ws["workspace_id"], "name": name},
                )
                tenants.append((login, org, ws, network))
            login, org, ws, network = tenants[0]
            client.headers["Authorization"] = "Bearer " + login["access_token"]
            now = datetime.now(UTC)
            sim_id, intent_id = uuid.uuid4(), uuid.uuid4()
            plan = {
                "operation": "shape",
                "source_host": "h1",
                "destination_host": "h3",
                "paths": [],
                "weights": [],
                "rate_mbps": 5.0,
                "dscp": None,
            }
            async with sessions() as db:
                for index, tenant in enumerate(tenants):
                    db.add(
                        TelemetryRecord(
                            event_id=uuid.uuid4(),
                            correlation_id=uuid.uuid4(),
                            device_id=uuid.uuid4(),
                            network_id=uuid.UUID(tenant[3]["network_id"]),
                            workspace_id=uuid.UUID(tenant[2]["workspace_id"]),
                            metric="report_fixture_rtt",
                            value=12.5 if index == 0 else 987654.25,
                            unit="ms",
                            observed_at=now,
                            source="disposable_fixture_not_measured",
                            tags={
                                "secret": "MUST_NOT_EXPORT",
                                "run_id": "report-fixture",
                            },
                        )
                    )
                    db.add(
                        AlertRecord(
                            alert_id=uuid.uuid4(),
                            alert_key=f"report-{index}",
                            source="fixture",
                            status="active",
                            severity="warning",
                            correlation_id=uuid.uuid4(),
                            payload={
                                "workspace_id": tenant[2]["workspace_id"],
                                "network_id": tenant[3]["network_id"],
                                "value": 12.5 if index == 0 else 987654.25,
                                "secret": "MUST_NOT_EXPORT",
                            },
                            created_at=now,
                            updated_at=now,
                        )
                    )
                db.add(
                    simulation_record(
                        complete=True,
                        simulation_id=sim_id,
                        workspace_id=uuid.UUID(ws["workspace_id"]),
                        network_id=uuid.UUID(network["network_id"]),
                        requested_by_user_id=str(users[0].user_id),
                    )
                )
                db.add(
                    Intent(
                        intent_id=intent_id,
                        workspace_id=uuid.UUID(ws["workspace_id"]),
                        network_id=uuid.UUID(network["network_id"]),
                        intent_kind="throttle_qos",
                        status="execution_started",
                        intent_payload={"secret": "MUST_NOT_EXPORT"},
                        validation_result={"validation_kind": "manual_lab_plan"},
                        execution_provenance={
                            "executor": "manual_lab_v1",
                            "phase": "accepted",
                            "execution_id": str(uuid.uuid4()),
                            "approved_plan": plan,
                            "plan_hash": plan_digest(plan),
                        },
                        explainability={},
                        requested_by_user_id=str(users[0].user_id),
                        requested_at=now,
                        correlation_id=uuid.uuid4(),
                    )
                )
                await db.commit()
            body = {
                "workspace_id": ws["workspace_id"],
                "network_id": network["network_id"],
                "report_type": "executive_summary",
                "format": "csv",
                "date_range": {
                    "start": (now - timedelta(hours=1)).isoformat(),
                    "end": (now + timedelta(minutes=1)).isoformat(),
                },
                "scope": {
                    "simulation_ids": [str(sim_id)],
                    "intent_ids": [str(intent_id)],
                },
                "filters": {"metric": "report_fixture_rtt"},
            }
            csv_job = await request(
                "POST",
                "/api/v1/reports/generate",
                202,
                json=body,
                headers={"Idempotency-Key": "csv-1"},
            )
            pdf_job = await request(
                "POST",
                "/api/v1/reports/generate",
                202,
                json={**body, "format": "pdf"},
                headers={"Idempotency-Key": "pdf-1"},
            )
            check(
                csv_job["status"] == pdf_job["status"] == "requested",
                "Consumer rendered inline",
            )
            check(
                csv_job["snapshot_summary"]["telemetry"]["row_count"] == 1,
                "Wrong frozen source scope",
            )
            check(
                all(
                    csv_job["snapshot_summary"][name]["row_count"] == 1
                    for name in ("alerts", "simulation", "intent")
                ),
                "Source section missing",
            )
            # Mutating the fixture after acceptance cannot alter frozen report values.
            async with sessions() as db:
                await db.execute(
                    update(TelemetryRecord)
                    .where(
                        TelemetryRecord.workspace_id == uuid.UUID(ws["workspace_id"])
                    )
                    .values(value=444444.5)
                )
                await db.commit()
            replay = await request(
                "POST",
                "/api/v1/reports/generate",
                202,
                json=body,
                headers={"Idempotency-Key": "csv-1"},
            )
            check(
                replay["report_id"] == csv_job["report_id"]
                and replay["idempotent_replay"],
                "Replay identity drift",
            )
            await request(
                "POST",
                "/api/v1/reports/generate",
                409,
                json={**body, "format": "pdf"},
                headers={"Idempotency-Key": "csv-1"},
            )
            # Expired leased job is recovered by a new process, not an inline fallback.
            async with sessions() as db:
                await db.execute(
                    update(ReportRecord)
                    .where(ReportRecord.report_id == uuid.UUID(csv_job["report_id"]))
                    .values(
                        status="running",
                        lease_token=uuid.uuid4(),
                        lease_expires_at=now - timedelta(seconds=1),
                        status_version=2,
                    )
                )
                await db.commit()
            worker = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "scripts.run_report_worker",
                cwd=backend,
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            processes.append(worker)
            evidence["stage"] = "worker_download_content"
            artifacts = []
            for job in (csv_job, pdf_job):
                path = f"/api/v1/reports/{job['report_id']}"

                async def terminal():
                    check(worker.returncode is None, "Worker exited")
                    return await request(
                        "GET", path, params={"workspace_id": ws["workspace_id"]}
                    )

                done = await until(
                    terminal, lambda value: value["status"] in {"generated", "failed"}
                )
                check(
                    done["status"] == "generated", "Report failed instead of rendering"
                )
                response = await client.get(
                    path + "/download", params={"workspace_id": ws["workspace_id"]}
                )
                check(response.status_code == 200, "Download failed")
                artifact = done["artifacts"][0]
                check(
                    len(response.content)
                    == artifact["size_bytes"]
                    == int(response.headers["Content-Length"]),
                    "Actual length mismatch",
                )
                check(
                    hashlib.sha256(response.content).hexdigest()
                    == artifact["checksum_sha256"],
                    "Actual SHA256 mismatch",
                )
                if job is csv_job:
                    rows = list(csv.reader(io.StringIO(response.text)))
                    content = " ".join(" ".join(row) for row in rows)
                    check(
                        any(row[3] == "12.5" for row in rows),
                        "CSV actual metric missing",
                    )
                else:
                    pdf = PdfReader(io.BytesIO(response.content))
                    content = " ".join(page.extract_text() for page in pdf.pages)
                    check("12.5" in content, "PDF actual metric missing")
                check(
                    all(
                        value not in content
                        for value in ("987654.25", "444444.5", "MUST_NOT_EXPORT")
                    ),
                    "Tenant/snapshot/secret leakage",
                )
                check(
                    all(
                        value in content
                        for value in (
                            "configured_model",
                            "throughput_mbps",
                            "plan_hash",
                            "rate_mbps",
                            "acknowledged_at",
                        )
                    ),
                    "Actual source fields missing",
                )
                artifacts.append(artifact)
            evidence["checks"] = [
                "CSV actual parsed cells",
                "PDF parsed text",
                "SHA256 and Content-Length",
                "four real owning-service source sections",
                "frozen source after mutation",
                "dual tenant source isolation",
                "expired lease process recovery",
            ]
            history = await request(
                "GET",
                "/api/v1/reports",
                params={"workspace_id": ws["workspace_id"], "page_size": 1},
            )
            empty = await request(
                "GET",
                "/api/v1/reports",
                params={"workspace_id": ws["workspace_id"], "page": 3, "page_size": 1},
            )
            check(
                history["total"] == empty["total"] == 2
                and len(history["items"]) == 1
                and not empty["items"],
                "Scoped pagination total wrong",
            )
            outsider = tenants[1]
            client.headers["Authorization"] = "Bearer " + outsider[0]["access_token"]
            await request(
                "GET",
                f"/api/v1/reports/{csv_job['report_id']}/download",
                403,
                params={"workspace_id": ws["workspace_id"]},
            )
            await request(
                "GET",
                f"/api/v1/reports/{csv_job['report_id']}/download",
                404,
                params={"workspace_id": outsider[2]["workspace_id"]},
            )
            own_history = await request(
                "GET",
                "/api/v1/reports",
                params={"workspace_id": outsider[2]["workspace_id"]},
            )
            check(own_history["total"] == 0, "History tenant leakage")
            client.headers["Authorization"] = "Bearer " + login["access_token"]
            target = storage / artifacts[0]["filename"]
            original = target.read_bytes()
            target.write_bytes(b"X" + original[1:])
            denial = await request(
                "GET",
                f"/api/v1/reports/{csv_job['report_id']}/download",
                409,
                params={"workspace_id": ws["workspace_id"]},
            )
            check(
                denial["code"] == "REPORT_ARTIFACT_INVALID",
                "Same-size tamper not denied",
            )
            target.write_bytes(original[:-1])
            await request(
                "GET",
                f"/api/v1/reports/{csv_job['report_id']}/download",
                409,
                params={"workspace_id": ws["workspace_id"]},
            )
            target.write_bytes(original)
            await stop(worker)
            pending = await request("POST", "/api/v1/reports/generate", 202, json=body)
            # Logout revokes credentials but not the durable actor's current role/membership.
            await request("POST", "/api/v1/auth/logout")
            await external(
                sys.executable,
                "-m",
                "scripts.run_report_worker",
                "--once",
                cwd=backend,
                env=env,
            )
            await request(
                "GET",
                f"/api/v1/reports/{pending['report_id']}/download",
                401,
                params={"workspace_id": ws["workspace_id"]},
            )
            login = await request(
                "POST",
                "/api/v1/auth/login",
                json={"email": "report-owner@example.com", "password": password},
            )
            client.headers["Authorization"] = "Bearer " + login["access_token"]
            after_logout = await request(
                "GET",
                f"/api/v1/reports/{pending['report_id']}",
                params={"workspace_id": ws["workspace_id"]},
            )
            check(
                after_logout["status"] == "generated",
                "Logout incorrectly cancelled durable report",
            )
            revoked_job = await request(
                "POST", "/api/v1/reports/generate", 202, json=body
            )
            # Revocation is independent of still-valid login/session credentials.
            async with sessions() as db:
                member = await db.scalar(
                    select(OrgMember).where(
                        OrgMember.org_id == uuid.UUID(org["org_id"]),
                        OrgMember.user_id == users[0].user_id,
                    )
                )
                await db.delete(member)
                await db.commit()
            await request(
                "GET",
                f"/api/v1/reports/{pdf_job['report_id']}/download",
                403,
                params={"workspace_id": ws["workspace_id"]},
            )
            await stop(worker)
            await external(
                sys.executable,
                "-m",
                "scripts.run_report_worker",
                "--once",
                cwd=backend,
                env=env,
            )
            async with sessions() as db:
                failed = await db.get(ReportRecord, uuid.UUID(revoked_job["report_id"]))
                check(
                    failed.status == "failed"
                    and failed.error_context["code"] == "REPORT_AUTHORITY_REVOKED"
                    and not failed.artifact_refs,
                    "Revoked queued generation was not denied",
                )
            evidence["checks"] += [
                "exact scoped history totals",
                "foreign tenant download denial",
                "same-size tamper denial",
                "length tamper denial",
                "current membership revocation denial",
                "worker restart no duplicate generation",
                "logout preserves authorized durable generation but rejects old download credentials",
                "queued actor revocation blocks generation",
            ]
            evidence["artifacts"] = artifacts
        evidence["stage"] = "passed"
    finally:
        for process in reversed(processes):
            await stop(process)
        if redis:
            await redis.aclose()
        if engine:
            await engine.dispose()
        for container in reversed(containers):
            await external("docker", "rm", "-f", "-v", container)
        evidence["cleanup"] = {
            "owned_containers_removed": len(containers),
            "owned_processes_stopped": len(processes),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    directory = Path(
        tempfile.mkdtemp(prefix="report-verification-", dir="/tmp/opencode")
    )
    evidence = {"stage": "starting", "kind": "disposable_fixture_not_lab"}
    try:
        asyncio.run(verify(directory, evidence))
    finally:
        private_json(directory / "result.json", evidence)
        print(directory / "result.json")


if __name__ == "__main__":
    main()
