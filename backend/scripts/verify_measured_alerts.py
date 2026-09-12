"""Opt-in sustained alerts from actual isolated network counters, never fixtures.

Prepare: python -m scripts.verify_measured_alerts --plan
After parent releases lab slot: python -m scripts.verify_measured_alerts --live --slot-released
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import fcntl
import hashlib
import json
import logging
import os
import re
import secrets
import signal
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from scripts.verify_execution import VerificationError, assert_lab_idle, check, external, port, private_json, stop, until

IMAGE = "sha256:d91efe1717f29a277683b735418877d73243ae24ab80e4c2c3311f6f0343c05c"
LOCK = Path("/tmp/opencode/nanfo-step14-lab.lock")
DPID, PORT = "0000000000000004", 1
METRIC = "link_utilization_percent"
POLL_SECONDS = 2
WORKLOAD_SECONDS = 30
RECOVERY_SECONDS = 18

# Fixed verifier-only namespace workload. No caller-controlled command or host.
# iperf remains foreground, and finally reaps both processes inside the owned lab.
TRAFFIC = r'''
import json, subprocess, time
from pathlib import Path
def host(name):
    matches = []
    for path in Path('/proc').iterdir():
        if path.name.isdigit():
            try:
                if ('mininet:' + name).encode() in (path / 'cmdline').read_bytes().split(b'\0'):
                    matches.append(path.name)
            except OSError:
                pass
    if len(matches) != 1:
        raise RuntimeError('Ambiguous host namespace')
    return ['nsenter', '-t', matches[0], '-n', '--']
server = subprocess.Popen(host('h3') + ['iperf3', '-s', '-1', '-J', '-p', '5219'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
client = None
try:
    time.sleep(.3)
    client = subprocess.Popen(host('h1') + ['iperf3', '-c', '10.77.0.3', '-p', '5219', '-u', '-b', '22M', '-l', '1200', '-t', '30', '-J'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sent, _ = client.communicate(timeout=40)
    received, _ = server.communicate(timeout=5)
    if client.returncode or server.returncode:
        raise RuntimeError('iperf failed')
    print(json.dumps({'client': json.loads(sent), 'server': json.loads(received)}))
finally:
    for process in (client, server):
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
'''


def plan(image=IMAGE):
    return {"status": "prepared_not_run", "live_capture": False, "image": image,
        "migration": "0019", "lab_lock": str(LOCK), "requires_parent_slot_release": True,
        "scope": {"dpid": DPID, "port_no": PORT, "capacity_mbps": 20, "metric": METRIC},
        "workload": {"source": "h1", "destination": "h3", "udp_offered_mbps": 22,
                     "seconds": WORKLOAD_SECONDS, "recovery_seconds": RECOVERY_SECONDS},
        "detector": {"breach": 85, "recover": 70, "min_samples": 3, "duration_seconds": 10,
                     "max_gap_seconds": 10, "max_age_seconds": 30, "poll_seconds": POLL_SECONDS},
        "runtime": "backend Python; sandboxed API, collector and alert outbox; no Docker socket"}


def sandbox(directory, *, evidence=False):
    args = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/tmp", "--tmpfs", "/run", "--unshare-user", "--unshare-pid", "--die-with-parent",
            "--ro-bind", str(directory), str(directory)]
    if evidence:
        args += ["--bind", str(directory / "collector"), str(directory / "collector")]
    return args


def validate_lifecycle(history, samples, *, network_id, workspace_id, device_id, correlation_id):
    """Independent evidence check: original sample IDs, same series, actual time windows."""
    items = history["items"]
    check(history["total"] == len(items) == 2, "Expected exactly generation and recovery history")
    by_type = {row["event_type"]: row for row in items}
    check(set(by_type) == {"alert.generated", "alert.resolved"}, "Unexpected lifecycle transition")
    generated, recovered = by_type["alert.generated"], by_type["alert.resolved"]
    check(generated["alert_id"] == recovered["alert_id"] == history["alert_id"], "Incident identity changed")
    check(generated["event_id"] != recovered["event_id"], "Lifecycle event IDs collided")
    samples = sorted(samples, key=lambda row: row["observed_at"])
    check(len({row["event_id"] for row in samples}) == len(samples), "Duplicate persisted observations")
    evidence = {}
    for row, phase in [(generated, "breach"), (recovered, "recovery")]:
        payload = row["payload"]
        check(row["correlation_id"] == correlation_id, "Actual collector correlation lost")
        check(all(payload[key] == value for key, value in {
            "network_id": network_id, "workspace_id": workspace_id, "device_id": device_id,
            "port_no": PORT, "metric": METRIC, "unit": "%"}.items()), "Lifecycle scope changed")
        check(payload["synthetic"] is False and payload["quality"] == "measured", "Nonmeasured lifecycle")
        check(payload["rule"] == {"version": "operator-v1", "breach": 85.0, "recover": 70.0,
            "min_samples": 3, "duration_seconds": 10.0, "max_gap_seconds": 10.0, "max_age_seconds": 30.0},
            "Detector acceptance thresholds changed")
        start, end = (datetime.fromisoformat(payload[key]) for key in ("window_started_at", "observed_at"))
        window = [sample for sample in samples if start <= datetime.fromisoformat(sample["observed_at"]) <= end]
        check(len(window) >= 3 and (end - start).total_seconds() >= 10, "Unsustained measurement window")
        times = [datetime.fromisoformat(sample["observed_at"]) for sample in window]
        check(all(0 < (b - a).total_seconds() <= 10 for a, b in zip(times, times[1:])), "Observation gap/order invalid")
        check(window[-1]["event_id"] == payload["observation_event_id"], "Transition lacks original observation")
        check(window[-1]["value"] == payload["value"], "Transition changed measurement value")
        for sample in window:
            tags = sample["tags"]
            check(sample["device_id"] == device_id and tags["port_no"] == PORT and tags["dpid"] == DPID
                  and tags["run_id"] == payload["run_id"] and tags["synthetic"] is False
                  and tags["measurement_method"] == "openflow_port_counter_delta"
                  and tags["capacity_mbps"] == 20 and sample["unit"] == "%", "Mixed series or fabricated provenance")
            check(sample["value"] >= 85 if phase == "breach" else sample["value"] < 70, "Threshold not sustained")
        evidence[phase] = {"samples": len(window), "seconds": (end - start).total_seconds(),
                           "event_ids": [sample["event_id"] for sample in window]}
    check(generated["payload"]["run_id"] == recovered["payload"]["run_id"], "Recovery changed run")
    check(recovered["payload"].get("resolution_reason") == "measured_recovery", "Manual or fabricated resolution")
    return evidence


async def collector(directory: Path):
    """Private bounded child; real adapter/ingestion only, no Docker or clock injection."""
    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.db.neo4j import close_neo4j, init_neo4j
    from app.db.postgres import get_engine
    from app.db.redis import close_redis, get_redis_client, init_redis
    from app.main import _build_emulation_adapter
    from app.modules.telemetry.emulation import EmulationSnapshot, SnapshotReader, read_bounded_file, validate_json
    from app.modules.telemetry.service import TelemetryCollectorRunner, TelemetryIngestionService
    from app.modules.network.emulation import load_binding
    from scripts.verify_emulation import verify_measurements

    configure_logging("CRITICAL")
    check(not Path("/run/docker.sock").exists() and not Path("/var/run/docker.sock").exists(), "Collector Docker socket exposed")
    settings = get_settings()
    evidence = directory / "collector"
    try:
        fd = os.open(settings.EMULATION_SNAPSHOT_PATH, os.O_WRONLY | os.O_NOFOLLOW)
    except OSError as error:
        check(error.errno in (errno.EROFS, errno.EACCES, errno.EPERM), "Source write denial unverified")
    else:
        os.close(fd)
        raise VerificationError("Collector can write producer snapshot")
    private_json(evidence / "runtime-proof.json", {"docker_socket_absent": True, "source_write_denied": True,
        "clock": "wall_utc", "backend_python": sys.executable, "uid": os.getuid()})
    binding = await load_binding(Path(settings.EMULATION_BINDING_PATH), snapshot_path=Path(settings.EMULATION_SNAPSHOT_PATH))
    correlation = str(uuid.UUID(os.environ["ALERT_VERIFY_CORRELATION"]))
    await init_redis()
    await init_neo4j()
    try:
        adapter = await _build_emulation_adapter(settings, get_redis_client())

        class RecordingReader(SnapshotReader):
            async def read(self, *, now=None):
                raw = await asyncio.to_thread(read_bounded_file, self.path, self.max_bytes)
                snapshot = validate_json(EmulationSnapshot, raw)
                self.assert_snapshot_fresh(snapshot)
                digest = hashlib.sha256(raw).hexdigest()
                path = evidence / f"snapshot-{digest}.json"
                if not path.exists():
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                self.raw_reference = {"file": path.name, "sha256": digest, "bytes": len(raw)}
                return snapshot

        adapter.reader = RecordingReader(Path(settings.EMULATION_SNAPSHOT_PATH), max_age_seconds=30)
        runner = TelemetryCollectorRunner(TelemetryIngestionService(get_redis_client()))
        previous = None
        batches = []
        deadline, next_poll = time.monotonic() + 90, time.monotonic()
        while time.monotonic() < deadline:
            if (directory / "stop-collector.json").exists():
                break
            samples = await adapter.poll()
            snapshot = adapter._pending or adapter._previous
            verify_measurements(snapshot, previous, binding, samples)
            selected = [sample for sample in samples if sample["metric"] == METRIC
                        and sample["tags"].get("dpid") == DPID and sample["tags"].get("port_no") == PORT]
            for sample in selected:
                await runner.ingest_once(sample, correlation, event_id=sample["event_id"])
            batch = {"observed_wall_time": datetime.now(UTC).isoformat(), "source": adapter.reader.raw_reference,
                     "samples": selected, "correlation_id": correlation}
            private_json(evidence / f"batch-{len(batches):03d}.json", batch)
            batches.append(batch)
            await adapter.acknowledge_batch(samples)
            previous = snapshot
            next_poll += POLL_SECONDS
            await asyncio.sleep(max(0, next_poll - time.monotonic()))
    finally:
        await close_redis()
        await close_neo4j()
        await get_engine().dispose()


async def verify(directory: Path, artifact: dict, *, image=IMAGE, preserve_stopped=None):
    import httpx
    from neo4j import AsyncGraphDatabase
    from redis.asyncio import Redis
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.core.config import Settings
    from app.core.security import hash_password
    from app.modules.identity.repository import UserRepository
    from app.modules.alert.models import AlertHistory, AlertOutbox
    from app.modules.identity.models import AuditLog
    from emulation.topology import manifest
    from scripts.bind_emulation import bind_emulation, save_binding

    root = Path(__file__).resolve().parents[2]
    backend = root / "backend"
    suffix, correlation = uuid.uuid4().hex, str(uuid.uuid4())
    ports = {kind: port() for kind in ("postgres", "redis", "neo4j", "api")}
    for name in ("binding", "output", "collector", "artifacts"):
        (directory / name).mkdir(mode=0o700 if name != "output" else 0o755)
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG") if key in os.environ}
    env.update(APP_ENV="verification", LOG_LEVEL="CRITICAL", EXECUTION_MODE="emulation",
        POSTGRES_HOST="127.0.0.1", POSTGRES_PORT=str(ports["postgres"]), POSTGRES_USER="verifier",
        POSTGRES_DB="measured_alert_verify", POSTGRES_PASSWORD=secrets.token_hex(24),
        REDIS_HOST="127.0.0.1", REDIS_PORT=str(ports["redis"]), REDIS_PASSWORD=secrets.token_hex(24), REDIS_DB="0",
        NEO4J_URI=f"bolt://127.0.0.1:{ports['neo4j']}", NEO4J_USER="neo4j", NEO4J_PASSWORD=secrets.token_hex(24),
        JWT_SECRET_KEY=secrets.token_hex(48), TELEMETRY_RUNTIME_ADAPTER_MODE="stub", EMULATION_CONTROL_ENABLED="false",
        EMULATION_BINDING_PATH=str(directory / "binding/binding.json"),
        EMULATION_SNAPSHOT_PATH=str(directory / "output/snapshot.json"), REPORTS_STORAGE_PATH=str(directory / "artifacts"),
        PYTHONPATH=f"{backend}:{root}", PYTHONDONTWRITEBYTECODE="1", ALERT_VERIFY_CORRELATION=correlation)
    settings = Settings(_env_file=None, **{key: value for key, value in env.items() if key in Settings.model_fields})
    env.update({key: str(getattr(settings, key)) for key in Settings.model_fields})
    processes, containers = [], []
    engine = None
    traffic = None
    config = directory / "redis.conf"
    label = f"nanfo.measured-alert-verifier={suffix}"
    preserved = None
    async def preserved_state():
        return json.loads(await external("docker", "inspect", preserve_stopped, "--format",
            '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},"state":{{json .State}}}'))
    try:
        artifact["stage"] = "preflight"
        check(os.geteuid() != 0, "Run verifier as an unprivileged operator with Docker access, not root")
        await assert_lab_idle()
        if preserve_stopped:
            preserved = await preserved_state()
            check(preserved["id"] == preserve_stopped and preserved["state"]["Status"] == "exited"
                  and not preserved["state"]["Running"], "Approved preserved container is not stopped")
            artifact["preserved_stopped_container"] = preserved
        check(not (await external("docker", "ps", "--filter", f"ancestor={image}", "-q")).strip(), "Pinned lab image busy")
        check((await external("docker", "image", "inspect", image, "--format", "{{.Id}}")).strip() == image, "Image identity mismatch")
        await external(*sandbox(directory), sys.executable, "-c",
            "from pathlib import Path; assert not Path('/run/docker.sock').exists(); assert not Path('/var/run/docker.sock').exists()")
        # Import checks run with this backend interpreter before any service is started.
        await external(sys.executable, "-c", "import asyncpg, redis, neo4j, reportlab, pypdf, uvicorn", env=env, cwd=backend)
        artifact.update(backend_python=sys.executable, image=image, correlation_id=correlation)

        async def create(kind, args, *, extra=None):
            name = f"nanfo-alert-verify-{kind}-{suffix}"
            containers.append(name)
            private_json(directory / f"owned-{kind}.json", {"name": name, "label": label})
            await external("docker", "run", "-d", "--name", name, "--label", label, *args, env={**env, **(extra or {})})
            return name

        artifact["stage"] = "isolated_infrastructure"
        await create("postgres", ["-p", f"127.0.0.1:{ports['postgres']}:5432", "-e", "POSTGRES_USER", "-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_DB", "postgres:16-alpine"])
        await create("neo4j", ["-p", f"127.0.0.1:{ports['neo4j']}:7687", "-e", "NEO4J_AUTH",
            "-e", "NEO4J_server_memory_heap_initial__size=256m", "-e", "NEO4J_server_memory_heap_max__size=256m",
            "-e", "NEO4J_server_memory_pagecache_size=128m", "neo4j:5.25-community"], extra={"NEO4J_AUTH": "neo4j/" + env["NEO4J_PASSWORD"]})
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(f'bind 0.0.0.0\nprotected-mode yes\nsave ""\nappendonly no\nrequirepass {env["REDIS_PASSWORD"]}\n')
        await create("redis", ["--user", str(os.geteuid()), "-p", f"127.0.0.1:{ports['redis']}:6379", "--mount",
            f"type=bind,source={config},target=/run/redis.conf,readonly", "redis:7-alpine", "redis-server", "/run/redis.conf"])
        engine = create_async_engine(settings.POSTGRES_DSN)
        async def ready():
            try:
                async with engine.connect() as db:
                    await db.scalar(text("SELECT 1"))
                async with Redis.from_url(settings.REDIS_URL) as redis:
                    await redis.ping()
                async with AsyncGraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)) as driver:
                    await driver.verify_connectivity()
                return True
            except Exception:
                return False
        await until(ready, timeout=120)
        artifact["stage"] = "migration0019"
        await external(sys.executable, "-m", "alembic", "-c", "alembic/alembic.ini", "upgrade", "0019", env=env, cwd=backend)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        users = {}
        async with sessions() as db:
            check(await db.scalar(text("SELECT version_num FROM alembic_version")) == "0019", "Migration0019 missing")
            for name in ("operator", "outsider"):
                password = secrets.token_urlsafe(32)
                user = await UserRepository(db).create(f"{name}@alerts.example.invalid", hash_password(password), name)
                await UserRepository(db).assign_role(user.user_id, "Admin")
                users[name] = password
            await db.commit()

        async def spawn(args, *, evidence=False):
            process = await asyncio.create_subprocess_exec(*sandbox(directory, evidence=evidence), sys.executable, *args,
                env=env, cwd=backend, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            processes.append(process)
            return process
        api = await spawn(["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(ports["api"]), "--log-level", "critical", "--no-access-log"])
        base = f"http://127.0.0.1:{ports['api']}"
        async with httpx.AsyncClient(base_url=base, timeout=20, trust_env=False) as client, httpx.AsyncClient(base_url=base, timeout=20, trust_env=False) as outsider:
            async def request(method, path, *, actor=client, expected=200, **kwargs):
                response = await actor.request(method, path, **kwargs)
                check(response.status_code == expected, "Unexpected HTTP status in alert verification")
                body = response.json()
                check(body["success"] == (expected < 400), "Invalid API envelope")
                return body.get("data")
            async def api_ready():
                check(api.returncode is None, "Sandbox API exited")
                try:
                    return (await client.get("/api/openapi.json")).status_code == 200
                except httpx.TransportError:
                    return False
            await until(api_ready, timeout=120)
            artifact["stage"] = "authenticated_binding"
            binding = await bind_emulation(client, email="operator@alerts.example.invalid", password=users["operator"],
                manifest=manifest(), org_slug="measured-alert-owner", workspace_name="Measured alerts", network_name="campus-small-v1")
            save_binding(binding, Path(env["EMULATION_BINDING_PATH"]), Path(env["EMULATION_SNAPSHOT_PATH"]))
            for name, actor in (("operator", client), ("outsider", outsider)):
                tokens = await request("POST", "/api/v1/auth/login", actor=actor, json={"email": f"{name}@alerts.example.invalid", "password": users[name]})
                actor.headers["Authorization"] = "Bearer " + tokens["access_token"]
            org = await request("POST", "/api/v1/organizations", actor=outsider, expected=201, json={"name": "Foreign tenant", "slug": "foreign-alert-tenant"})
            await request("POST", f"/api/v1/organizations/{org['org_id']}/workspaces", actor=outsider, expected=201, json={"name": "Foreign workspace"})
            artifact["scope"] = {"network_id": str(binding.network_id), "workspace_id": str(binding.workspace_id),
                "device_id": str(binding.switches[DPID]), "port_no": PORT, "actor_user_id": str(binding.actor_user_id)}
            await assert_lab_idle()
            lab = await create("lab", ["--privileged", "--network", "none", "--pids-limit", "256", "--memory", "768m", "--cpus", "2",
                "--tmpfs", "/run:exec,size=64m", "--tmpfs", "/tmp:exec,size=64m", "-e", "EMULATION_CONTROL_ENABLED=false",
                "--mount", f"type=bind,source={directory / 'output'},target=/output", image])
            async def lab_ready():
                try:
                    return json.loads(await external("docker", "exec", lab, "python", "-m", "emulation.runner", "--request", "status", timeout=5))["passed"]
                except VerificationError:
                    return False
            await until(lab_ready, timeout=100)
            outbox = await spawn(["-m", "scripts.run_alert_worker"])
            reader = await spawn(["-m", "scripts.verify_measured_alerts", "--collector-directory", str(directory)], evidence=True)
            async def samples():
                check(all(process.returncode is None for process in (api, reader, outbox)), "Sandbox runtime exited")
                data = await request("GET", f"/api/v1/telemetry/device/{binding.switches[DPID]}", params={"metric": METRIC, "page_size": 200})
                check(data["total"] <= 200, "Telemetry evidence exceeds bound")
                return data["items"]
            artifact["stage"] = "baseline_actual_counters"
            await until(samples, lambda rows: len(rows) >= 2, timeout=20)
            artifact["stage"] = "foreground_iperf30"
            artifact["workload_started_at"] = datetime.now(UTC).isoformat()
            traffic = asyncio.create_task(external("docker", "exec", "-i", lab, "python", "-", stdin=TRAFFIC, timeout=48))
            raw = await traffic
            workload = json.loads(raw)
            check("error" not in workload["client"] and "error" not in workload["server"], "iperf error document")
            check(sum(row["sum"]["bytes"] for row in workload["server"]["intervals"]) > 0, "No actual delivered traffic")
            private_json(directory / "iperf.json", workload)
            artifact["workload_stopped_at"] = datetime.now(UTC).isoformat()
            artifact["stage"] = "actual_recovery"
            await asyncio.sleep(RECOVERY_SECONDS)
            private_json(directory / "stop-collector.json", {"requested_at": datetime.now(UTC).isoformat()})
            await asyncio.wait_for(reader.wait(), 10)
            check(reader.returncode == 0, "Collector did not finish its last source batch")
            async with Redis.from_url(settings.REDIS_URL, decode_responses=True) as redis:
                async def initial_drained():
                    groups = await redis.xinfo_groups("stream:telemetry")
                    return bool(groups) and all(row.get("lag") == 0 and row["pending"] == 0 for row in groups)
                await until(initial_drained, timeout=30)
            measured = (await request("GET", f"/api/v1/telemetry/device/{binding.switches[DPID]}",
                                      params={"metric": METRIC, "page_size": 200}))["items"]
            expected = {}
            for path in sorted((directory / "collector").glob("batch-*.json")):
                batch = json.loads(path.read_bytes())
                for sample in batch["samples"]:
                    check(sample["event_id"] not in expected, "Collector duplicated a source observation")
                    expected[sample["event_id"]] = sample
            check(len(measured) == len(expected) > 3, "Source-to-persistence sample count mismatch")
            for row in measured:
                check(row["event_id"] in expected, "Persisted sample not in actual source batch")
                sample = expected[row["event_id"]]
                check(all(row[key] == sample[key] for key in ("device_id", "network_id", "workspace_id", "metric", "unit", "source", "value", "tags")),
                      "Persisted sample differs from independently verified actual source")
                check(datetime.fromisoformat(row["observed_at"]) == datetime.fromisoformat(sample["observed_at"]), "Persisted observation time changed")
            alerts = await request("GET", "/api/v1/alerts", params={"correlation_id": correlation, "limit": 500})
            check(alerts["total"] == len(alerts["items"]) == 1, "Expected one sustained same-port incident")
            incident = alerts["items"][0]
            check(incident["status"] == "resolved", "Actual recovery did not resolve incident")
            history = await request("GET", f"/api/v1/alerts/{incident['alert_id']}/history")
            artifact["windows"] = validate_lifecycle(history, measured, **{key: artifact["scope"][key] for key in ("network_id", "workspace_id", "device_id")}, correlation_id=correlation)
            generated = next(row for row in history["items"] if row["event_type"] == "alert.generated")
            recovered = next(row for row in history["items"] if row["event_type"] == "alert.resolved")
            stopped_at = datetime.fromisoformat(artifact["workload_stopped_at"])
            check(datetime.fromisoformat(generated["payload"]["observed_at"]) < stopped_at
                  < datetime.fromisoformat(recovered["payload"]["observed_at"]), "Incident did not span actual workload stop")
            private_json(directory / "telemetry.json", {"items": measured})
            private_json(directory / "history.json", history)
            private_json(directory / "alerts.json", alerts)
            # Replay original source IDs in reverse chronological order, with no
            # changed values/timestamps/UUIDs. These are real retained observations.
            async with Redis.from_url(settings.REDIS_URL, decode_responses=True) as redis:
                source_events = await redis.xrange("stream:telemetry")
                check(len(source_events) == len(measured), "Unpersisted collector observations")
                for _, fields in reversed(source_events):
                    await redis.xadd("stream:telemetry", fields)
                    await redis.xadd("stream:telemetry", fields)
                async def drained():
                    groups = await redis.xinfo_groups("stream:telemetry")
                    return bool(groups) and all(row.get("lag") == 0 and row["pending"] == 0 for row in groups)
                await until(drained, timeout=30)
            replay = await request("GET", f"/api/v1/alerts/{incident['alert_id']}/history")
            check(replay == history, "Duplicate/out-of-order replay changed history")
            after = await request("GET", "/api/v1/alerts", params={"correlation_id": correlation})
            check(after["total"] == 1, "Replay created another incident")
            after_samples = await request("GET", f"/api/v1/telemetry/device/{binding.switches[DPID]}", params={"metric": METRIC, "page_size": 200})
            check(after_samples["total"] == len(measured), "Replay duplicated persisted observations")
            foreign = await request("GET", "/api/v1/alerts", actor=outsider)
            check(foreign["total"] == 0, "Foreign tenant list leaked incident")
            for path in (f"/api/v1/alerts/{incident['alert_id']}", f"/api/v1/alerts/{incident['alert_id']}/history"):
                await request("GET", path, actor=outsider, expected=403)
            for action in ("ack", "resolve"):
                await request("POST", f"/api/v1/alerts/{incident['alert_id']}/{action}", actor=outsider, expected=403)
            async def delivered():
                async with sessions() as db:
                    pending = list((await db.scalars(select(AlertOutbox).where(AlertOutbox.published_at.is_(None)))).all())
                    audits = list((await db.scalars(select(AuditLog).where(AuditLog.resource_id == uuid.UUID(incident["alert_id"])))).all())
                    return not pending and len(audits) == 2
            await until(delivered, timeout=30)
            async with sessions() as db:
                records = list((await db.scalars(select(AlertHistory))).all())
                audits = list((await db.scalars(select(AuditLog).where(AuditLog.resource_id == uuid.UUID(incident["alert_id"])))).all())
                check({row.event_id for row in records} == {row.event_id for row in audits}, "Outbox audit IDs differ from history")
            artifact.update(passed=True, status="passed", stage="complete", incident_id=incident["alert_id"],
                measured_samples=len(measured), history_events=2, audit_events=2,
                checks={"real_source_counter_calculation": True, "sustained_breach_and_recovery": True,
                        "exact_source_persistence_match": True,
                        "same_incident_scope_run": True, "reverse_duplicate_replay_unchanged": True,
                        "two_tenant_denial": True, "outbox_audit_event_ids": True})
            private_json(directory / "checks.json", {"checks": artifact["checks"],
                "history_event_ids": [row["event_id"] for row in history["items"]],
                "audit_event_ids": sorted(str(row.event_id) for row in audits),
                "replayed_original_events": len(source_events) * 2})
    finally:
        errors = []
        if traffic is not None and not traffic.done():
            traffic.cancel()
            await asyncio.gather(traffic, return_exceptions=True)
        for process in reversed(processes):
            try:
                await stop(process)
            except Exception:
                errors.append("process_cleanup")
        if engine is not None:
            await engine.dispose()
        for name in reversed(containers):
            try:
                ids = (await external("docker", "ps", "-aq", "--filter", f"name=^/{name}$", "--filter", f"label={label}", timeout=10)).split()
                for identity in ids:
                    await external("docker", "rm", "-f", "-v", identity, timeout=30)
            except Exception:
                errors.append("container_cleanup")
        config.unlink(missing_ok=True)
        if preserved is not None:
            try:
                check(await preserved_state() == preserved, "Preserved stopped container changed")
                artifact["preserved_stopped_unchanged"] = True
            except Exception:
                errors.append("preserved_container_changed")
        artifact["cleanup"] = {"passed": not errors, "errors": errors}
        if errors:
            artifact.update(passed=False, status="blocked")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan", action="store_true", help="No Docker, lab, lock or filesystem side effects")
    modes.add_argument("--live", action="store_true")
    modes.add_argument("--collector-directory", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--slot-released", action="store_true", help="Parent explicitly released the campaign lab slot")
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--preserve-stopped-container", help="Parent-approved exact 64-character container ID; inspect only")
    parser.add_argument("--output-parent", type=Path, default=Path("/tmp/opencode"))
    parser.add_argument("--timeout-seconds", type=int, default=480)
    args = parser.parse_args(argv)
    if args.preserve_stopped_container and not re.fullmatch(r"[0-9a-f]{64}", args.preserve_stopped_container):
        parser.error("Preservation approval must identify an exact full container ID")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.image):
        parser.error("An immutable sha256 image ID is required")
    if not 240 <= args.timeout_seconds <= 900:
        parser.error("timeout must be 240..900 seconds")
    if args.plan:
        print(json.dumps(plan(args.image)))
        return 0
    if args.collector_directory:
        if "ALERT_VERIFY_CORRELATION" not in os.environ:
            parser.error("Private collector requires verifier environment")
        logging.disable(logging.CRITICAL)
        asyncio.run(collector(args.collector_directory))
        return 0
    if not args.slot_released:
        parser.error("--live requires --slot-released from parent; no resources created")
    check(args.output_parent.is_dir() and not args.output_parent.is_symlink(), "Output parent must already be a real directory")
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "blocked", "reason": "parent_campaign_lab_slot_busy", "live_capture": False}))
            return 2
        directory = Path(tempfile.mkdtemp(prefix="measured-alerts-", dir=args.output_parent))
        artifact = {**plan(args.image), "status": "blocked", "passed": False, "evidence_kind": "measured",
                    "live_capture": False, "started_at": datetime.now(UTC).isoformat()}
        private_json(directory / "plan.json", plan(args.image))
        async def run():
            task = asyncio.current_task()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, task.cancel)
            try:
                async with asyncio.timeout(args.timeout_seconds):
                    await verify(directory, artifact, image=args.image, preserve_stopped=args.preserve_stopped_container)
                artifact["live_capture"] = artifact["passed"]
            except BaseException as error:
                artifact.update(passed=False, status="blocked", error_type=type(error).__name__)
                if isinstance(error, VerificationError):
                    artifact["blocker"] = str(error)
        logging.disable(logging.CRITICAL)
        asyncio.run(run())
        artifact["finished_at"] = datetime.now(UTC).isoformat()
        private_json(directory / "result.json", artifact)
        print(json.dumps({"status": artifact["status"], "artifact": str(directory / "result.json")}))
        return 0 if artifact["passed"] else 2
    finally:
        os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
