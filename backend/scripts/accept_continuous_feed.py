"""Explicit ADR024 serialized live acceptance; private DB/Redis and owned labs only."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import traceback
import uuid
from datetime import UTC, datetime, timedelta

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = Path("/tmp/opencode/nanfo-adr024-evaluation-002")
IMAGE = "sha256:954462c0f00d5bbaa72ea144f6064936b399c430e6ab94bffcf1c00d134ea0d7"
AI = ROOT / "ai-engine/.venv/bin/python"


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False, default=str)
        stream.flush()
        os.fsync(stream.fileno())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def docker(*args, timeout=90):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=timeout).stdout.strip()


async def until(predicate, timeout=90):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.1)


def preregister(output):
    sys.path.insert(0, str(ROOT / "scripts"))
    import adr024_campaign
    audit = adr024_campaign.audit_seeds()
    reserved = set(audit["reserved_seeds"]) | set(range(3003, 3015))
    for path in Path("/tmp/opencode").glob("nanfo-live-acceptance-*/plan.json"):
        reserved.update(item["seed"] for item in json.loads(path.read_bytes()).get("episodes", []))
    seeds = [seed for seed in range(1000, 2000) if seed not in reserved][:2]
    assert len(seeds) == 2
    save(output / "seed-audit.json", audit | {"reserved_including_operational": sorted(reserved)})
    template = json.loads((CAMPAIGN / "live-registry.template.json").read_bytes())
    files = [Path(__file__), ROOT / "scripts/live_feed_evaluate.py", ROOT / "emulation/passive_observer.py",
             *sorted((ROOT / "backend/app/modules/autonomy").glob("*.py")),
             ROOT / "backend/scripts/frozen_live_inference.py", ROOT / "backend/scripts/verify_fresh_live_provider.py"]
    save(output / "source-manifest.json", {str(p.relative_to(ROOT)): digest(p) for p in files})
    save(output / "plan.json", dict(version="adr024-live-service-acceptance/v1", declared_at=datetime.now(UTC),
        image_id=IMAGE, checkpoint=str(CAMPAIGN / "checkpoint.ptz"), checkpoint_sha256=template["checkpoint"]["sha256"],
        source_directory=str(CAMPAIGN / "source"), client_source_sha256=template["source_sha256"],
        source_manifest_sha256=digest(output / "source-manifest.json"),
        seed_audit_sha256=digest(output / "seed-audit.json"), episodes=[dict(seed=s, scenario=p, expected_route=a)
            for s, p, a in zip(seeds, ("path0", "path1"), ("route1", "route0"), strict=True)],
        fixed_acquisition_action=0, measurement_frames_per_episode=3, window_seconds=2., episode_steps=4,
        training=False, recommendation_dispatch=False, budget_seconds=900, max_observation_age_seconds=30,
        cases=["real-login-scope-permission", "monitor", "recommend-both-directions", "fresh-helper",
               "stopfeed-stale", "disconnect", "expired-admission", "owned-cleanup"]))


async def acceptance(output):
    import httpx
    from redis.asyncio import Redis
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from alembic.config import Config
    from alembic.runtime.environment import EnvironmentContext
    from alembic.script import ScriptDirectory
    from app.core.dependencies import get_db, get_redis
    from app.core.security import hash_password
    from app.main import app
    from app.modules.identity.repository import UserRepository
    from app.modules.organization.models import Organization, OrgMember, Workspace
    from app.modules.network.models import Network
    from app.modules.autonomy.models import AutonomyDecision
    from app.modules.autonomy.providers import installed_providers
    from app.modules.autonomy.registry import LiveRegistry
    from app.modules.autonomy.worker import AutonomyWorker
    from app.modules.autonomy.model_provider import _QUALIFICATION_TASKS
    from emulation.passive_observer import Admission, process_identity
    from scripts.verify_fresh_live_provider import verify_fresh

    logging.disable(logging.CRITICAL)
    plan = json.loads((output / "plan.json").read_bytes())
    prefix = "nanfo-live-acceptance-" + uuid.uuid4().hex
    names, lab_ids, children = [], [], []
    engine = redis = None
    result = {"status": "running", "cases": [], "output": str(output), "recommendation_dispatch": False}
    cleanup = []
    original_overrides = app.dependency_overrides.copy()
    try:
        password = secrets.token_hex(24)
        pg = prefix + "-pg"
        docker("run", "-d", "--pull=never", "--name", pg, "--cpus", "1", "--memory", "256m",
               "--tmpfs", "/var/lib/postgresql/data", "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=" + password,
               "postgres:16-alpine")
        names.append(pg)
        rd = prefix + "-redis"
        docker("run", "-d", "--pull=never", "--name", rd, "--cpus", ".5", "--memory", "128m",
               "-p", "127.0.0.1::6379", "redis:7-alpine", "redis-server", "--save", "", "--appendonly", "no", "--requirepass", password)
        names.append(rd)
        pgport = docker("port", pg, "5432/tcp").rsplit(":", 1)[1]
        rdport = int(docker("port", rd, "6379/tcp").rsplit(":", 1)[1])
        for _ in range(100):
            if subprocess.run(["docker", "exec", pg, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"], capture_output=True).returncode == 0:
                break
            await asyncio.sleep(.2)
        dsn = f"postgresql+psycopg2://postgres:{password}@127.0.0.1:{pgport}/postgres"
        sync = create_engine(dsn)
        config = Config()
        config.set_main_option("script_location", str(ROOT / "backend/alembic"))
        migrations = ScriptDirectory.from_config(config)
        with sync.begin() as connection:
            with EnvironmentContext(config, migrations, fn=lambda rev, _: migrations._upgrade_revs("head", rev)) as context:
                context.configure(connection=connection)
                context.run_migrations()
            result["schema"] = connection.scalar(text("SELECT version_num FROM alembic_version"))
        sync.dispose()
        engine = create_async_engine(dsn.replace("+psycopg2", "+asyncpg"))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        redis = Redis(host="127.0.0.1", port=rdport, password=password, decode_responses=True)
        network, workspace, org = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        account_password = secrets.token_urlsafe(24)
        async with sessions() as db:
            users = UserRepository(db)
            actor = await users.create("live-acceptance@example.com", hash_password(account_password))
            await users.assign_role(actor.user_id, "Admin")
            actor_id = actor.user_id
            db.add(Organization(org_id=org, name="Owned live acceptance", slug=prefix))
            await db.flush()
            db.add_all([Workspace(workspace_id=workspace, org_id=org, name="Private measured workspace"),
                OrgMember(org_id=org, user_id=actor_id, org_role="Admin"),
                Network(network_id=network, workspace_id=workspace, name="Actual owned FRR lab")])
            await db.commit()
        async def database_dependency():
            async with sessions() as db:
                yield db
        async def redis_dependency():
            yield redis
        app.dependency_overrides[get_db] = database_dependency
        app.dependency_overrides[get_redis] = redis_dependency
        observations = output / "observations"
        observations.mkdir(mode=0o700)
        template = json.loads((CAMPAIGN / "live-registry.template.json").read_bytes())
        template.update(installed_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            expires_at=(datetime.now(UTC) + timedelta(minutes=20)).isoformat(),
            scopes=[dict(network_id=str(network), workspace_id=str(workspace), snapshot_path="snapshot.json")])
        save(output / "registry.json", template)
        os.environ.update(NANFO_LIVE_MODEL_REGISTRY=str(output / "registry.json"),
            NANFO_LIVE_MODEL_REGISTRY_SHA256=digest(output / "registry.json"), NANFO_MODEL_ROOT=str(CAMPAIGN),
            NANFO_MODEL_PYTHON=str(AI), NANFO_LIVE_OBSERVATION_ROOT=str(observations), NANFO_PASSIVE_PROC_SUDO="1")
        providers = installed_providers(sessions, redis)
        checkpoint = template["checkpoint"]["sha256"]
        await providers.model.qualify(checkpoint)
        await asyncio.gather(*list(_QUALIFICATION_TASKS))
        qualification = await providers.model.qualify(checkpoint)
        assert qualification.qualified, qualification.reasons
        save(output / "qualification.json", qualification.model_dump(mode="json"))
        assert providers.safety.status.status != "ready" and providers.executor.status.status != "ready"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://private-acceptance") as client:
            login = await client.post("/api/v1/auth/login", json={"email": "live-acceptance@example.com", "password": account_password})
            assert login.status_code == 200
            headers = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
            assert (await client.get("/api/v1/autonomy", params={"network_id": str(network)})).status_code == 401
            assert (await client.get("/api/v1/autonomy", params={"network_id": str(uuid.uuid4())}, headers=headers)).status_code == 404
            result["cases"].append("real_login_and_scope_pass")
            revision = 0
            async def mode(value):
                nonlocal revision
                response = await client.put("/api/v1/autonomy", headers=headers, json={"network_id": str(network),
                    "expected_revision": revision, "mode": value, "checkpoint_sha256": checkpoint})
                assert response.status_code == 200, (response.status_code, response.text)
                revision = response.json()["data"]["revision"]
            async def cycle(expected, label, route=None):
                worker = AutonomyWorker(sessions=sessions, redis=redis)
                async with asyncio.timeout(35):
                    while not await worker.run_one():
                        await asyncio.sleep(.2)
                async with sessions() as db:
                    row = await db.scalar(select(AutonomyDecision).order_by(AutonomyDecision.created_at.desc()).limit(1))
                    from app.modules.autonomy.schemas import DecisionResponse
                    value = DecisionResponse.model_validate(row).model_dump(mode="json")
                save(output / (label + "-decision.json"), value)
                assert value["status"] == expected, value["reasons"]
                if route:
                    assert value["proposal"]["action_id"] == route
                assert value["execution_id"] is None and value["authorization"] is None and value["safety"] is None
                result["cases"].append(label)
                return value
            for item in plan["episodes"]:
                scenario = item["scenario"]
                directory = output / scenario
                directory.mkdir(mode=0o700)
                name = "nanfo-training-" + uuid.uuid4().hex
                cid = docker("create", "--pull=never", "--name", name, "--label", "nanfo.live-acceptance=" + prefix,
                    "--network", "none", "--privileged", "--cpus", "2", "--memory", "768m", "--memory-swap", "768m",
                    "--pids-limit", "256", "--tmpfs", "/run:exec,size=64m", "--tmpfs", "/tmp:exec,size=64m",
                    "--env", "EMULATION_CONTROL_ENABLED=false", "--env", "NANFO_LAB_IMAGE_ID=" + IMAGE,
                    IMAGE, "--experiment", "--mode", "matched", "--output", "/output")
                lab_ids.append(cid)
                docker("start", cid)
                for _ in range(160):
                    check = subprocess.run(["docker", "exec", cid, "python", "-c",
                        "from pathlib import Path; raise SystemExit(not Path('/run/nanfo/experiment.sock').is_socket())"], capture_output=True)
                    if check.returncode == 0:
                        break
                    await asyncio.sleep(.5)
                else:
                    raise RuntimeError("lab_start_failed")
                info = json.loads(docker("inspect", cid))[0]
                assert info["Image"] == IMAGE and not info["Mounts"] and info["HostConfig"]["NetworkMode"] == "none"
                save(directory / "lab-identity.json", {"id": cid, "name": name, "image": IMAGE, "pid": info["State"]["Pid"]})
                producer_log = (directory / "producer.log").open("wb")
                producer = subprocess.Popen([str(AI), "-B", str(ROOT / "scripts/live_feed_evaluate.py"), "--plan", str(output / "plan.json"),
                    "--output", str(directory / "feed"), "--scenario", scenario, "--container", name], stdout=producer_log, stderr=subprocess.STDOUT)
                children.append(producer)
                feed = directory / "feed"
                await until(lambda: (feed / "header-ready.json").exists())
                processes = docker("top", cid, "-eo", "pid,args").splitlines()[1:]
                pid = next(int(line.split()[0]) for line in processes if "python -m emulation.runner" in line
                           and "tini" not in line)
                ticks, namespace = process_identity(pid)
                admission = Admission(version="nanfo.passive-feed-admission/v1", network_id=network, workspace_id=workspace,
                    registry_sha256=digest(output / "registry.json"), feed_path=str(feed / "evidence.jsonl"),
                    session_sha256=json.loads((feed / "header-ready.json").read_bytes())["session_sha256"],
                    server_pid=pid, server_start_ticks=ticks, boot_id=uuid.UUID(Path("/proc/sys/kernel/random/boot_id").read_text().strip()),
                    time_namespace=namespace, expires_at=datetime.now(UTC) + timedelta(seconds=210),
                    max_clock_drift_seconds=.25, max_delivery_seconds=10,
                    authorization="observe-existing-measured-feed-only")
                save(directory / "admission.json", admission.model_dump(mode="json"))
                bridge_log = (directory / "bridge.log").open("wb")
                env = dict(os.environ, PYTHONPATH=str(ROOT / "backend") + ":" + str(ROOT))
                bridge = subprocess.Popen([sys.executable, "-B", "-m", "emulation.passive_observer", "--admission", str(directory / "admission.json"),
                    "--sha256", digest(directory / "admission.json"), "--duration-seconds", "200"], env=env, cwd=ROOT,
                    stdout=bridge_log, stderr=subprocess.STDOUT)
                children.append(bridge)
                attached = observations / "snapshot.json.attached.json"
                await until(lambda: attached.exists() and json.loads(attached.read_bytes())["admission_sha256"] == digest(directory / "admission.json"))
                save(directory / "attached.json", json.loads(attached.read_bytes()))
                await mode("monitor")
                (feed / "release-reset").touch()
                async def fresh(index):
                    def ready():
                        try:
                            body = json.loads((observations / "snapshot.json").read_bytes())
                            return body["history"]["frames"][0]["response"]["data"]["step_index"] == index and body["history"]["frames"][0]["response"]["data"]["scenario"] == scenario
                        except (KeyError, FileNotFoundError):
                            return False
                    await until(ready)
                    save(directory / f"snapshot-{index}.json", json.loads((observations / "snapshot.json").read_bytes()))
                await fresh(0)
                await cycle("observed", scenario + "-monitor")
                await mode("recommend")
                helper = asyncio.create_task(verify_fresh(LiveRegistry.from_environment(), redis, network, workspace, timeout_seconds=90))
                await asyncio.sleep(.2)
                (feed / "release-step-1").touch()
                await fresh(1)
                helper_result = await helper
                assert helper_result["status"] == "fresh_provider_inference_verified", helper_result
                save(directory / "fresh-helper.json", helper_result)
                await cycle("recommended", scenario + "-recommend-1", item["expected_route"])
                (feed / "release-step-2").touch()
                await fresh(2)
                await cycle("recommended", scenario + "-recommend-2", item["expected_route"])
                # Actual pause: original observed_at stays untouched until it ages out.
                snapshot = json.loads((observations / "snapshot.json").read_bytes())
                observed = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
                await asyncio.sleep(max(0, 31 - (datetime.now(UTC) - observed).total_seconds()))
                stale = await providers.observer.observe(network, workspace)
                assert not stale.fresh and "live_observation_stale_or_future" in stale.reasons
                save(directory / "stale.json", stale.model_dump(mode="json"))
                await cycle("blocked", scenario + "-stale-blocked")
                (feed / "release-close").touch()
                await until(lambda: producer.poll() is not None and bridge.poll() is not None, timeout=30)
                assert producer.returncode == 0
                disconnected = await providers.observer.observe(network, workspace)
                assert not disconnected.compatible
                save(directory / "disconnected.json", disconnected.model_dump(mode="json"))
                # New expired admission uses actual past time; no measurement alteration.
                expired = admission.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
                save(directory / "expired-admission.json", expired.model_dump(mode="json"))
                from emulation.passive_observer import observe_feed
                try:
                    await observe_feed(directory / "expired-admission.json", digest(directory / "expired-admission.json"), duration_seconds=1)
                except ValueError as exc:
                    assert str(exc) == "passive_admission_expired"
                    result["cases"].append(scenario + "-expired-denied")
                else:
                    raise AssertionError("expired_admission_accepted")
                producer_log.close()
                bridge_log.close()
                docker("stop", "--time", "20", cid)
                docker("cp", cid + ":/output", str(directory / "lab-output"))
                docker("rm", cid)
                assert not docker("ps", "-a", "--filter", "id=" + cid, "--format", "{{.ID}}")
                cleanup.append({"container_id": cid, "removed": True, "scenario": scenario})
                lab_ids.remove(cid)
            # Actual current organization permission revocation, no auth monkeypatch.
            async with sessions() as db:
                await db.execute(text("UPDATE org_members SET org_role='Viewer' WHERE user_id=:actor"), {"actor": actor_id})
                await db.commit()
            denied = await client.put("/api/v1/autonomy", headers=headers, json={"network_id": str(network),
                "expected_revision": revision, "mode": "recommend", "checkpoint_sha256": checkpoint})
            assert denied.status_code == 403
            result["cases"].append("actual_membership_revocation_denied")
        async with sessions() as db:
            from app.modules.autonomy.schemas import DecisionResponse
            rows = list((await db.scalars(select(AutonomyDecision).order_by(AutonomyDecision.created_at))).all())
            save(output / "durable-decisions.json", [DecisionResponse.model_validate(row).model_dump(mode="json") for row in rows])
        result.update(status="passed", actor_id=str(actor_id), network_id=str(network), workspace_id=str(workspace),
                      training=False, safety_authorized=False, recommendations_applied=False)
    except Exception as exc:
        result.update(status="failed", error_type=type(exc).__name__, reason=str(exc)[:1000],
                      locations=[{"file": Path(f.filename).name, "line": f.lineno} for f in traceback.extract_tb(exc.__traceback__)])
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                try:
                    await asyncio.to_thread(child.wait, 15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        for cid in lab_ids:
            try:
                docker("stop", "--time", "20", cid)
                docker("cp", cid + ":/output", str(output / ("failed-lab-" + cid[:12])))
                docker("rm", cid)
                cleanup.append({"container_id": cid, "removed": True})
            except Exception:
                cleanup.append({"container_id": cid, "removed": False})
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        if redis:
            await redis.aclose()
        if engine:
            await engine.dispose()
        for name in reversed(names):
            docker("rm", "-f", name)
            cleanup.append({"name": name, "removed": not docker("ps", "-a", "--filter", "name=" + name, "--format", "{{.Names}}")})
        save(output / "cleanup.json", cleanup)
        save(output / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-serialized-lab", action="store_true", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    output = Path(tempfile.mkdtemp(prefix="nanfo-live-acceptance-", dir="/tmp/opencode"))
    preregister(output)
    print(json.dumps({"preregistered": str(output), "plan_sha256": digest(output / "plan.json")}), flush=True)
    result = asyncio.run(acceptance(output))
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if result["status"] == "passed" else 1)
