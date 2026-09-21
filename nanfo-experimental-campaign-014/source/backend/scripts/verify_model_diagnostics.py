"""Real migrated disposable PostgreSQL DB + authenticated ASGI HTTP + frozen AI.

Run from backend: PYTHONPATH=. poetry run python scripts/verify_model_diagnostics.py
Existing deployment credentials are consumed in memory by Settings, never printed.
Redis sessions/locks use a UUID-owned disposable Redis container, never shared Redis.
Docker is verifier-only. No lifespan workers, lab, live networks or auth overrides.
"""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import tempfile
import traceback
import uuid

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from app.core.config import get_settings
from app.core.dependencies import get_db, get_redis
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.main import app
from app.modules.autonomy.model_diagnostic_models import ModelDiagnostic
from app.modules.identity.models import UserRole
from app.modules.identity.repository import UserRepository
from app.modules.network.models import Network
from app.modules.organization.models import Organization, OrgMember, Workspace
from tests.model_diagnostic_support import provision_registry


@asynccontextmanager
async def disposable_redis():
    async def docker(*args):
        process = await asyncio.create_subprocess_exec("docker", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            async with asyncio.timeout(30):
                stdout, _ = await process.communicate()
            if process.returncode:
                raise RuntimeError("diagnostic_verifier_redis_container_failed")
            return stdout.decode().strip()
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()

    name = "nanfo-model-diagnostic-redis-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="model-redis-") as directory:
        config = Path(directory) / "redis.conf"
        password = secrets.token_hex(32)
        config.write_text(f'bind 0.0.0.0\nprotected-mode yes\nsave ""\nappendonly no\nrequirepass {password}\n')
        config.chmod(0o600)
        redis = None
        try:
            await docker("run", "-d", "--pull=never", "--name", name,
                "--label", "nanfo.model-diagnostic-verifier=" + name,
                "--cpus", "0.5", "--memory", "128m", "--pids-limit", "32",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
                "--user", str(os.geteuid()), "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
                "-p", "127.0.0.1::6379", "--mount", f"type=bind,source={config},target=/run/redis.conf,readonly",
                "redis:7-alpine", "redis-server", "/run/redis.conf")
            address = await docker("port", name, "6379/tcp")
            host, port = address.split(":")
            if host != "127.0.0.1" or not port.isdigit():
                raise RuntimeError("diagnostic_verifier_redis_binding_invalid")
            redis = Redis(host=host, port=int(port), password=password, decode_responses=True,
                          socket_connect_timeout=2, socket_timeout=2)
            async with asyncio.timeout(15):
                while True:
                    try:
                        if await redis.ping():
                            break
                    except RedisError:
                        pass
                    await asyncio.sleep(0.1)
            yield redis
        finally:
            if redis:
                await redis.aclose()
            await docker("rm", "-f", name)


async def verify():
    configure_logging("CRITICAL")
    logging.disable(logging.CRITICAL)
    settings = get_settings()
    backend = Path(__file__).resolve().parents[1]
    database = "model_diagnostic_verify_" + uuid.uuid4().hex
    admin = create_engine(settings.POSTGRES_SYNC_DSN, isolation_level="AUTOCOMMIT", echo=False)
    sync = engine = None
    created = False
    resources = AsyncExitStack()
    network_id, workspace_id, org_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    other_network = uuid.uuid4()
    original_env = {key: os.environ.get(key) for key in
                    ("NANFO_MODEL_REGISTRY", "NANFO_MODEL_REGISTRY_SHA256", "NANFO_MODEL_ROOT", "NANFO_MODEL_PYTHON")}
    original_overrides = app.dependency_overrides.copy()
    try:
        redis = await resources.enter_async_context(disposable_redis())
        with admin.connect() as db:
            db.execute(text(f'CREATE DATABASE "{database}"'))
        created = True
        sync = create_engine(admin.url.set(database=database), echo=False)
        config = Config()
        config.set_main_option("script_location", str(backend / "alembic"))
        scripts = ScriptDirectory.from_config(config)
        with sync.begin() as connection:
            with EnvironmentContext(config, scripts, fn=lambda rev, _: scripts._upgrade_revs("0016", rev)) as context:
                context.configure(connection=connection)
                context.run_migrations()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0016"
        engine = create_async_engine(admin.url.set(drivername="postgresql+asyncpg", database=database), echo=False)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        password = secrets.token_urlsafe(24)
        async with sessions() as db:
            users = UserRepository(db)
            actor = await users.create("diagnostic-verifier@example.com", hash_password(password))
            await users.assign_role(actor.user_id, "Admin")
            actor_id = actor.user_id
            db.add(Organization(org_id=org_id, name="Diagnostic fixture", slug=database))
            await db.flush()
            db.add_all([Workspace(workspace_id=workspace_id, org_id=org_id, name="Fixture"),
                        OrgMember(org_id=org_id, user_id=actor_id, org_role="Admin"),
                        Network(network_id=network_id, workspace_id=workspace_id, name="Registered fixture"),
                        Network(network_id=other_network, workspace_id=workspace_id, name="Unregistered fixture")])
            await db.commit()

        async def database_dependency():
            async with sessions() as db:
                yield db

        async def redis_dependency():
            yield redis

        app.dependency_overrides[get_db] = database_dependency
        app.dependency_overrides[get_redis] = redis_dependency
        with tempfile.TemporaryDirectory(prefix="model-registry-") as directory:
            env, registry = provision_registry(Path(directory), network_id)
            os.environ.update(env)
            model = registry["models"][0]
            ai = Path(env["NANFO_MODEL_ROOT"])
            source_before = {name: hashlib.sha256((ai / model["source_directory"] / name).read_bytes()).hexdigest()
                             for name in model["source_sha256"]}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://verification") as client:
                path = "/api/v1/autonomy/model"
                payload = {"network_id": str(network_id), "history_reference": "validation-06"}
                assert (await client.get(path, params={"network_id": str(network_id)})).status_code == 401
                login = await client.post("/api/v1/auth/login", json={"email": "diagnostic-verifier@example.com", "password": password})
                assert login.status_code == 200, "real login failed"
                headers = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
                before = await client.get(path, params={"network_id": str(network_id)}, headers=headers)
                assert before.status_code == 200 and before.json()["data"]["status"] == "operator_registered"
                assert before.json()["data"]["diagnostics"] == []
                events_before = await redis.xlen("nanfo:events:autonomy")
                first = await client.post(path + "/diagnose", json=payload, headers=headers)
                assert first.status_code == 201, f"diagnostic status {first.status_code}"
                second = await client.post(path + "/diagnose", json=payload, headers=headers)
                assert second.status_code == 201
                one, two = first.json()["data"], second.json()["data"]
                assert one["diagnostic_id"] != two["diagnostic_id"]
                result = one["result"]
                for key in ("action", "probabilities", "value", "input_sha256", "policy_sha256", "history_sha256"):
                    assert result[key] == two["result"][key]
                assert result["action"] == 0 and result["value"] == 3.2172513008117676
                assert result["probabilities"] == [0.9718289375305176, 0.028171034529805183]
                assert not result["live"] and not result["safety_authorized"]
                assert await redis.xlen("nanfo:events:autonomy") == events_before
                listing = await client.get(path, params={"network_id": str(network_id)}, headers=headers)
                assert len(listing.json()["data"]["diagnostics"]) == 2
                for extra in ({"checkpoint": "/tmp/evil"}, {"history_reference": "../../etc/passwd"}, {"vector": [0] * 16}):
                    assert (await client.post(path + "/diagnose", json=payload | extra, headers=headers)).status_code == 422
                assert (await client.post(path + "/diagnose", json=payload | {"history_reference": "unknown"}, headers=headers)).status_code == 404
                assert (await client.post(path + "/diagnose", json=payload | {"network_id": str(other_network)}, headers=headers)).status_code == 404
                hidden = await client.get(path, params={"network_id": str(other_network)}, headers=headers)
                assert hidden.json()["data"]["model"] is None and hidden.json()["data"]["diagnostics"] == []
                assert (await client.get(path, params={"network_id": str(uuid.uuid4())}, headers=headers)).status_code == 404
                assert (await client.get(path, params={"network_id": str(network_id), "history_limit": 101}, headers=headers)).status_code == 422
                lock = redis.lock("nanfo:autonomy:model-diagnostics:inference", timeout=40, thread_local=False)
                await lock.acquire()
                try:
                    assert (await client.post(path + "/diagnose", json=payload, headers=headers)).status_code == 429
                finally:
                    await lock.release()
                async with sessions() as db:
                    try:
                        await db.execute(update(ModelDiagnostic).values(actor_id="mutated"))
                    except Exception:
                        await db.rollback()
                    else:
                        raise AssertionError("immutable trigger did not reject update")
                    assert len(list(await db.scalars(select(ModelDiagnostic)))) == 2
                    await db.execute(text("UPDATE org_members SET org_role='Viewer' WHERE user_id=:actor"), {"actor": actor_id})
                    await db.commit()
                assert (await client.post(path + "/diagnose", json=payload, headers=headers)).status_code == 403
                async with sessions() as db:
                    await db.execute(text("UPDATE org_members SET org_role='Admin' WHERE user_id=:actor"), {"actor": actor_id})
                    await db.execute(UserRole.__table__.delete().where(UserRole.user_id == actor_id))
                    await db.commit()
                assert (await client.post(path + "/diagnose", json=payload, headers=headers)).status_code == 403
                assert (await client.get(path, params={"network_id": str(network_id)}, headers=headers)).status_code == 403
            assert source_before == {name: hashlib.sha256((ai / model["source_directory"] / name).read_bytes()).hexdigest()
                                     for name in model["source_sha256"]}
        return {"migration": "0016 after 0015", "authenticated_http": "passed", "immutable_records": 2,
                "replay": "exact fresh-process match", "scope_rbac_and_concurrency": "passed",
                "frozen_source_preserved": True, "redis": "real isolated UUID-owned Redis container",
                "inference": {key: result[key] for key in ("action", "probabilities", "value", "input_sha256", "policy_sha256",
                                                            "inference_seconds", "subprocess_seconds")},
                "live": False, "safety_authorized": False}
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if engine:
            await engine.dispose()
        if sync:
            sync.dispose()
        if created:
            with admin.connect() as db:
                db.execute(text(f'DROP DATABASE "{database}"'))
        admin.dispose()
        await resources.aclose()


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(verify()), allow_nan=False))
    except Exception as exc:
        # Driver errors may include connection parameters. Never print their text.
        frames = traceback.extract_tb(exc.__traceback__)
        print(json.dumps({"verification": "failed", "error_type": type(exc).__name__,
                          "verifier_lines": [frame.lineno for frame in frames if frame.filename == __file__]}))
        raise SystemExit(1) from None
