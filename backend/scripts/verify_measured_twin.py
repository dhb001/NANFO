"""ADR021 isolated local acceptance; never connects to operator-supplied stores.

Run from backend: poetry run python -m scripts.verify_measured_twin --live
Requires installed initdb/postgres and optionally --redis-server /absolute/binary.
Alternatively --redis-image-id sha256:<exact-local-id> authorizes one owned Docker
Redis container/volume, with --pull=never and only a high loopback host port.
Missing Redis is reported as blocked, after real PostgreSQL acceptance. Evidence
contains only named outcomes, counts and hashes; private data/credentials are removed.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ACCEPTANCE_SCHEMA = "0027"
CASES = (
    "migration_0027", "postgres_inventory_pending", "postgres_spatial_audit",
    "postgres_spatial_conflict_tenant", "postgres_audit_handler_replay",
    "authenticated_http_inventory", "http_spatial_reload_conflict_tenant",
    "redis_outage_retry", "post_xadd_interruption_stable_replay",
    "real_audit_consumer_dedup", "redis_persistence_restart", "logout_denial",
    "http_spatial_history_restore", "http_asset_cas_download_tenant",
    "http_geometry_roundtrip_history_denial",
)
SNMP_CASES = (
    "snmp_owner_guarded_real_collection", "snmp_real_bus_persistence",
    "snmp_authorized_history_tenant_denial", "snmp_websocket_manager_delivery",
    "snmp_revocation_before_read",
    "snmp_keyset_cursor_scope_denial",
    "snmp_report_pin_before_reference", "snmp_archive_tombstone_restore",
)


class AcceptanceFailure(RuntimeError):
    """Fixed-code failure; never retains arbitrary exception/response text."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AcceptanceFailure(code)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_hashes() -> dict[str, str]:
    paths = [*BACKEND.joinpath("app").rglob("*.py"), *BACKEND.joinpath("alembic").rglob("*.py"),
             BACKEND / "scripts/run_network_outbox_worker.py", Path(__file__), BACKEND / "poetry.lock"]
    return {str(path.relative_to(BACKEND)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def private_file(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as handle:
        os.chmod(path, 0o600)
        handle.write(content)


def high_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    require(port >= 1024, "high_port_required")
    return port


def port_free(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


def command(argv: list[str], env: dict[str, str], *, timeout: float = 60) -> int:
    # Child errors can include DSNs or SQL parameters. Discard rather than redact.
    process = subprocess.Popen(argv, cwd=BACKEND, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return process.wait(timeout=timeout)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


@contextmanager
def environment(values: dict[str, str]):
    before = dict(os.environ)
    os.environ.clear()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(before)


class LocalLab:
    """Own exact child handles and one newly allocated private resource tree."""

    def __init__(self, root: Path, redis_binary: str | None, redis_image_id: str | None = None):
        self.root = root
        self.asset_root = root / "network-assets"
        self.asset_root.mkdir(mode=0o700)
        (root / "reports").mkdir(mode=0o700)
        self.redis_binary = redis_binary
        self.pg = None
        self.redis = None
        self.snmp = None
        self.measured_snmp = False
        self.docker_redis = DockerRedis(self, redis_image_id) if redis_image_id else None
        self.pids: list[int] = []
        self.pg_port = high_port()
        self.redis_port = high_port()
        while self.redis_port == self.pg_port:
            self.redis_port = high_port()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("PG", "POSTGRES_", "REDIS_", "NEO4J_", "JWT_", "TELEMETRY_"))}
        self.env.update({
            "APP_ENV": "test", "EXECUTION_MODE": "emulation", "LOG_LEVEL": "CRITICAL",
            "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": str(self.pg_port),
            "POSTGRES_USER": "lab_owner", "POSTGRES_PASSWORD": secrets.token_hex(24),
            "POSTGRES_DB": "postgres", "REDIS_HOST": "127.0.0.1",
            "REDIS_PORT": str(self.redis_port), "REDIS_PASSWORD": secrets.token_hex(24), "REDIS_DB": "0",
            "JWT_SECRET_KEY": secrets.token_hex(32), "JWT_ALGORITHM": "HS256",
            # Never initialize Neo4j; this closed local destination cannot select shared7687.
            "NEO4J_URI": "bolt://127.0.0.1:1", "NEO4J_USER": "unavailable",
            "NEO4J_PASSWORD": secrets.token_hex(24), "TELEMETRY_RUNTIME_ADAPTER_MODE": "stub",
            "WORKER_HEARTBEAT_PATH": str(root / "worker"),
            "WORKER_ITERATION_TIMEOUT_SECONDS": "10", "PYTHONUNBUFFERED": "1",
            "NETWORK_ASSET_ROOT": str(self.asset_root),
            "REPORTS_STORAGE_PATH": str(root / "reports"),
        })

    def spawn(self, argv: list[str]):
        child = subprocess.Popen(argv, cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.pids.append(child.pid)
        return child

    @staticmethod
    def stop(child) -> bool:
        if child is None or child.poll() is not None:
            return True
        child.terminate()
        try:
            child.wait(timeout=15)
            return True
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)
            return False

    def start_postgres(self):
        password_file = self.root / "pg-password"
        private_file(password_file, self.env["POSTGRES_PASSWORD"] + "\n")
        require(command(["initdb", "-D", str(self.root / "pg"), "-U", "lab_owner",
                         "--auth=scram-sha-256", "--no-locale", "--encoding=UTF8",
                         "--pwfile", str(password_file)], self.env) == 0, "initdb_failed")
        self.pg = self.spawn(["postgres", "-D", str(self.root / "pg"), "-h", "127.0.0.1",
                              "-p", str(self.pg_port), "-k", str(self.root),
                              "-c", "unix_socket_permissions=0700"])
        self.wait_port(self.pg, self.pg_port)

    @staticmethod
    def wait_port(child, port):
        for _ in range(100):
            require(child.poll() is None, "service_exited_during_startup")
            if not port_free(port):
                return
            time.sleep(0.05)
        raise AcceptanceFailure("service_startup_timeout")

    def start_redis(self):
        if self.docker_redis:
            self.docker_redis.start()
            return
        require(self.redis_binary is not None, "redis_binary_missing")
        config = self.root / "redis.conf"
        if not config.exists():
            private_file(config, "\n".join([
                "bind 127.0.0.1", f"port {self.redis_port}", "protected-mode yes", "daemonize no",
                f"dir {self.root}", f"requirepass {self.env['REDIS_PASSWORD']}",
                'save ""', "appendonly yes", "appendfsync always", 'logfile ""',
            ]) + "\n")
        self.redis = self.spawn([self.redis_binary, str(config)])
        self.wait_port(self.redis, self.redis_port)

    def stop_redis(self) -> bool:
        if self.docker_redis:
            return self.docker_redis.stop()
        return self.stop(self.redis)

    def cleanup(self) -> dict:
        snmp_clean = self.snmp.cleanup() if self.snmp else {}
        docker_clean = {}
        if self.docker_redis:
            try:
                docker_clean = self.docker_redis.cleanup()
            except Exception:  # noqa: BLE001 - still stop the owned PostgreSQL process
                docker_clean = {"owned_container_removed": False, "owned_volume_removed": False}
            redis_clean = all(docker_clean.values())
        else:
            redis_clean = self.stop(self.redis)
        pg_clean = self.stop(self.pg)
        stopped = all(child is None or child.poll() is not None for child in (self.pg, self.redis))
        if stopped:
            shutil.rmtree(self.root)
        return {"children_reaped": stopped, "graceful": redis_clean and pg_clean,
                "private_tree_removed": not self.root.exists(),
                "postgres_port_closed": port_free(self.pg_port),
                "redis_port_closed": port_free(self.redis_port), "owned_pids": self.pids, **docker_clean, **snmp_clean}


def owned_udp_addresses(pid: int) -> list[dict]:
    inodes = set()
    for fd in Path(f"/proc/{pid}/fd").iterdir():
        try:
            link = os.readlink(fd)
            if link.startswith("socket:["):
                inodes.add(link[8:-1])
        except FileNotFoundError:
            pass
    addresses = []
    for name in ("udp", "udp6"):
        for line in Path(f"/proc/{pid}/net/{name}").read_text().splitlines()[1:]:
            fields = line.split()
            if fields[9] in inodes:
                addresses.append({"family": name, "local": fields[1]})
    return addresses


class LocalSNMP:
    """One foreground read-only SNMPv3 agent; all config/state belongs to the lab."""

    def __init__(self, lab):
        self.lab = lab
        self.root = lab.root / "snmp"
        self.root.mkdir(mode=0o700)
        for name in ("home", "config", "state"):
            (self.root / name).mkdir(mode=0o700)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.process = None
        self.credentials_path = self.root / "credentials.json"
        self.binding_path = self.root / "binding.json"
        self.sys_name = "nanfo-pipeline-" + uuid.uuid4().hex[:12]
        self.credentials = {"username": "lab" + secrets.token_hex(6),
                            "auth_passphrase": secrets.token_hex(24), "priv_passphrase": secrets.token_hex(24)}

    async def start(self):
        require(shutil.which("snmpd") is not None and shutil.which("snmpget") is not None, "snmp_binaries_missing")
        private_file(self.credentials_path, json.dumps(self.credentials))
        config = self.root / "config/snmpd.conf"
        private_file(config, "\n".join([
            f"agentaddress udp:127.0.0.1:{self.port}", f"sysName {self.sys_name}",
            f"createUser {self.credentials['username']} SHA-256 {self.credentials['auth_passphrase']} AES {self.credentials['priv_passphrase']}",
            "view measured included .1.3.6.1.2.1.1", "view measured included .1.3.6.1.2.1.2",
            "view measured included .1.3.6.1.2.1.31", "view measured included .1.3.6.1.6.3.10.2.1.2",
            f"rouser {self.credentials['username']} priv -V measured",
        ]) + "\n")
        env = {"HOME": str(self.root / "home"), "SNMPCONFPATH": str(self.root / "config"),
               "SNMP_PERSISTENT_DIR": str(self.root / "state"), "MIBS": "", "LC_ALL": "C"}
        self.process = subprocess.Popen([
            shutil.which("snmpd"), "-f", "-C", "-c", str(config), "-p", str(self.root / "snmpd.pid"), "-Ln",
        ], env=env, cwd=self.root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, umask=0o077)
        self.lab.pids.append(self.process.pid)
        expected = [{"family": "udp", "local": f"0100007F:{self.port:04X}"}]
        for _ in range(60):
            require(self.process.poll() is None, "snmp_agent_exited")
            addresses = owned_udp_addresses(self.process.pid)
            if addresses:
                require(addresses == expected, "snmp_listener_not_exclusively_loopback")
                break
            await asyncio.sleep(0.1)
        else:
            raise AcceptanceFailure("snmp_listener_timeout")
        proc = Path(f"/proc/{self.process.pid}")
        process_bytes = (proc / "cmdline").read_bytes() + (proc / "environ").read_bytes()
        require(not any(secret.encode() in process_bytes for secret in self.credentials.values()), "snmp_secret_in_process")

    def cleanup(self):
        graceful = LocalLab.stop(self.process)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            try:
                probe.bind(("127.0.0.1", self.port))
                released = True
            except OSError:
                released = False
        return {"snmp_reaped": self.process is None or self.process.poll() is not None,
                "snmp_graceful_stop": graceful, "snmp_udp_released": released}


class CollectingWebSocket:
    """Transport-only substitute; actual manager and per-delivery auth remain real."""

    def __init__(self):
        self.frames = []
        self.close_codes = []

    async def send_text(self, text):
        self.frames.append(json.loads(text))

    async def close(self, code):
        self.close_codes.append(code)


class DockerRedis:
    """An exact local image and newly created resources, never an external URL.

    Copy the0600 config into the stopped container; no host mounts, credentials in
    argv/environment, Docker socket mount, log driver, pulls or service discovery.
    A newly labelled volume retains AOF across exact-container stop/start.
    """

    LABEL = "org.nanfo.adr021.acceptance"

    def __init__(self, lab: LocalLab, image_id: str):
        require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)), "exact_redis_image_id_required")
        self.lab = lab
        self.image_id = image_id
        self.owner = uuid.uuid4().hex
        self.name = "nanfo-adr021-redis-" + self.owner
        self.volume = self.name + "-data"
        self.container_id = None
        self.volume_created = False
        self.env = {key: value for key, value in os.environ.items()
                    if key in {"PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "XDG_RUNTIME_DIR"}}

    def docker(self, *args: str, check=True) -> subprocess.CompletedProcess:
        completed = subprocess.run(["docker", *args], env=self.env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=40)
        require(not check or completed.returncode == 0, "owned_redis_docker_" + args[0] + "_failed")
        return completed

    def inspect(self) -> dict:
        require(self.container_id is not None, "owned_redis_container_missing")
        record = json.loads(self.docker("container", "inspect", self.container_id).stdout)[0]
        require(record["Id"] == self.container_id and record["Config"]["Labels"].get(self.LABEL) == self.owner,
                "owned_redis_container_identity_mismatch")
        require(record["Image"] == self.image_id, "owned_redis_image_mismatch")
        return record

    def start(self):
        if self.container_id is None:
            image = json.loads(self.docker("image", "inspect", self.image_id).stdout)[0]
            require(image["Id"] == self.image_id and image["Os"] == "linux", "redis_local_image_mismatch")
            self.docker("volume", "create", "--label", f"{self.LABEL}={self.owner}", self.volume)
            self.volume_created = True
            # cidfile allows exact cleanup even if create returns after an interruption.
            cidfile = self.lab.root / "redis.cid"
            created = self.docker(
                "create", "--pull=never", "--name", self.name, "--label", f"{self.LABEL}={self.owner}",
                "--cidfile", str(cidfile), "--publish", f"127.0.0.1:{self.lab.redis_port}:6379",
                "--mount", f"type=volume,source={self.volume},target=/data", "--network", "bridge",
                "--log-driver", "none", "--restart", "no", "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE",
                "--security-opt", "no-new-privileges", "--user", "0:0", "--read-only",
                "--pids-limit", "32", "--memory", "128m", "--cpus", "0.5",
                "--entrypoint", "redis-server", self.image_id, "/data/redis-acceptance.conf",
            )
            self.container_id = created.stdout.strip()
            require(bool(re.fullmatch(r"[0-9a-f]{64}", self.container_id)), "redis_container_id_invalid")
            record = self.inspect()
            require(len(record["Mounts"]) == 1 and record["Mounts"][0].get("Name") == self.volume,
                    "unexpected_container_mount")
            require(record["HostConfig"]["PortBindings"] == {
                "6379/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(self.lab.redis_port)}]},
                "unexpected_container_port_binding")
            config = self.lab.root / "redis-container.conf"
            private_file(config, "\n".join([
                "bind 0.0.0.0", "port 6379", "protected-mode yes", "daemonize no", "dir /data",
                f"requirepass {self.lab.env['REDIS_PASSWORD']}", 'save ""', "appendonly yes",
                "appendfsync always", 'logfile ""',
            ]) + "\n")
            self.docker("cp", str(config), self.container_id + ":/data/redis-acceptance.conf")
        self.inspect()
        self.docker("start", self.container_id)
        for _ in range(100):
            state = self.inspect()["State"]
            require(state["Running"], "owned_redis_exited_during_startup_" + str(state["ExitCode"]))
            # Host port publication precedes Redis readiness. Authenticate before
            # admitting application traffic; never treat docker-proxy as readiness.
            from redis import Redis
            from redis.exceptions import RedisError

            try:
                with Redis(host="127.0.0.1", port=self.lab.redis_port,
                           password=self.lab.env["REDIS_PASSWORD"], socket_timeout=0.2) as probe:
                    if probe.ping():
                        return
            except RedisError:
                pass
            time.sleep(0.05)
        raise AcceptanceFailure("owned_redis_startup_timeout")

    def stop(self) -> bool:
        self.inspect()
        self.docker("stop", "--time", "10", self.container_id)
        state = self.inspect()["State"]
        return not state["Running"] and state["ExitCode"] == 0 and port_free(self.lab.redis_port)

    def cleanup(self) -> dict:
        cidfile = self.lab.root / "redis.cid"
        if self.container_id is None and cidfile.exists():
            candidate = cidfile.read_text().strip()
            require(bool(re.fullmatch(r"[0-9a-f]{64}", candidate)), "cleanup_container_id_invalid")
            self.container_id = candidate
        graceful = True
        if self.container_id:
            graceful = self.stop()
            self.docker("rm", self.container_id)
            require(self.docker("container", "inspect", self.container_id, check=False).returncode != 0,
                    "owned_container_remains")
        if self.volume_created:
            volume = json.loads(self.docker("volume", "inspect", self.volume).stdout)[0]
            require(volume["Labels"].get(self.LABEL) == self.owner, "owned_volume_identity_mismatch")
            self.docker("volume", "rm", self.volume)
            require(self.docker("volume", "inspect", self.volume, check=False).returncode != 0,
                    "owned_volume_remains")
        return {"owned_container_removed": True, "owned_volume_removed": True, "redis_graceful_stop": graceful}

    def evidence(self) -> dict:
        return {"image_id": self.image_id, "container_id": self.container_id, "container_name": self.name,
                "volume_name": self.volume, "owner_label": self.owner, "pull_policy": "never",
                "host_binding": f"127.0.0.1:{self.lab.redis_port}", "config_mode": "0600",
                "log_driver": "none", "application_docker_socket": False}


def spatial_payload(device_id: str, revision: int = 0) -> dict:
    return {"expected_revision": revision, "scene": {
        "version": 1, "coordinate_system": {"units": "m", "up_axis": "y"},
        "objects": [{"object_id": "acceptance-device", "parent_id": None, "object_type": "device",
                     "name": "Local lab fixture", "device_id": device_id,
                     "position": {"x": 1.5, "y": 2, "z": 0}, "rotation": {"x": 0, "y": 0, "z": 0},
                     "provenance": {"source": "acceptance-fixture", "accuracy_m": None}}],
    }}


async def postgres_cases(sessions, result, *, inventory_only=False):
    """Owner repositories bootstrap fixtures; real services commit all subject mutations."""
    from fastapi import HTTPException
    from sqlalchemy import func, select, text

    from app.core.runtime_health import SCHEMA_HEAD, WORKER_LOOPS
    from app.core.security import hash_password
    from app.events.consumers.audit_consumer import handle_audit_event
    from app.modules.identity.models import AuditLog
    from app.modules.identity.repository import UserRepository
    from app.modules.network.outbox_models import NetworkOutbox
    from app.modules.network.schemas import CreateDeviceRequest, CreateNetworkRequest
    from app.modules.network.service import DeviceService, NetworkService
    from app.modules.network.spatial_schemas import ReplaceSpatialSceneRequest
    from app.modules.network.spatial_service import SpatialSceneService
    from app.modules.organization.repository import OrganizationRepository, OrgMemberRepository, WorkspaceRepository

    async with sessions() as db:
        require(await db.scalar(text("SELECT version_num FROM alembic_version")) == ACCEPTANCE_SCHEMA,
                "installed_schema_mismatch")
        result["runtime_schema_head"] = SCHEMA_HEAD
        if SCHEMA_HEAD != ACCEPTANCE_SCHEMA:
            result["blockers"].append("parent_runtime_schema_head_mismatch")
        require(WORKER_LOOPS.get("network") == ("outbox",), "outbox_health_registration_missing")
        result["postgres_version"] = await db.scalar(text("SHOW server_version"))
        result["cases"]["migration_0027"] = "passed"
        credentials = []
        for index in range(2):
            password = secrets.token_hex(20)
            email = f"acceptance-{index}@example.com"
            repo = UserRepository(db)
            user = await repo.create(email, hash_password(password), "Private acceptance actor")
            await repo.assign_role(user.user_id, "Admin")
            org = await OrganizationRepository(db).create(name="Private lab", slug=f"acceptance-{index}")
            await OrgMemberRepository(db).add_member(org.org_id, user.user_id, "Admin")
            workspace = await WorkspaceRepository(db).create(org_id=org.org_id, name="Private lab", description=None)
            credentials.append((email, password, str(user.user_id), str(workspace.workspace_id)))
        await db.commit()

    actor, workspace = credentials[0][2:]
    async with sessions() as db:
        network = await NetworkService(db, None).create_network(
            req=CreateNetworkRequest(workspace_id=workspace, name="PostgreSQL acceptance"),
            actor_id=actor, correlation_id=str(uuid.uuid4()),
        )
    async with sessions() as db:
        device = await DeviceService(db, None).add_device(
            network_id=network.network_id, req=CreateDeviceRequest(hostname="lab-device", device_type="ap"),
            actor_id=actor, correlation_id=str(uuid.uuid4()),
        )
    async with sessions() as db:
        rows = list((await db.scalars(select(NetworkOutbox).order_by(NetworkOutbox.sequence))).all())
        require(len(rows) == 2 and all(row.published_at is None and row.attempts == 0 for row in rows),
                "inventory_not_durably_pending")
        envelopes = [dict(row.envelope) for row in rows]
        result["postgres_pending_envelopes_sha256"] = digest(envelopes)
        result["cases"]["postgres_inventory_pending"] = "passed"
        if inventory_only:
            return credentials
        req = ReplaceSpatialSceneRequest.model_validate(spatial_payload(str(device.device_id)))
        scene = await SpatialSceneService(db, None).replace_scene(
            network_id=network.network_id, actor_user_id=actor, req=req, correlation_id=str(uuid.uuid4()),
        )
    async with sessions() as db:
        reloaded = await SpatialSceneService(db, None).get_scene(network_id=network.network_id, actor_user_id=actor)
        require(reloaded == scene and scene.revision == 1, "postgres_scene_reload_failed")
        count = await db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.event_type == "network.spatial_scene.replaced", AuditLog.resource_id == network.network_id))
        require(count == 1, "postgres_scene_audit_missing")
        result["cases"]["postgres_spatial_audit"] = "passed"
    for denied_actor, expected in ((actor, 409), (credentials[1][2], 403)):
        async with sessions() as db:
            try:
                await SpatialSceneService(db, None).replace_scene(
                    network_id=network.network_id, actor_user_id=denied_actor, req=req,
                    correlation_id=str(uuid.uuid4()),
                )
            except HTTPException as exc:
                require(exc.status_code == expected, "postgres_spatial_denial_wrong_status")
            else:
                raise AcceptanceFailure("postgres_spatial_denial_missing")
    async with sessions() as db:
        try:
            await SpatialSceneService(db, None).get_scene(
                network_id=network.network_id, actor_user_id=credentials[1][2],
            )
        except HTTPException as exc:
            require(exc.status_code == 403, "postgres_spatial_read_denial_wrong_status")
        else:
            raise AcceptanceFailure("postgres_spatial_read_denial_missing")
    async with sessions() as db:
        require(await SpatialSceneService(db, None).get_scene(
            network_id=network.network_id, actor_user_id=actor) == scene, "postgres_denial_mutated_scene")
        count = await db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.event_type == "network.spatial_scene.replaced", AuditLog.resource_id == network.network_id))
        require(count == 1, "postgres_denial_created_audit")
    result["cases"]["postgres_spatial_conflict_tenant"] = "passed"
    # Direct handler invocation is independent of Redis. Report it separately
    # from the bus/worker acceptance; these event rows remain unpublished.
    for _ in range(2):
        for envelope in envelopes:
            await handle_audit_event({**envelope, "payload": json.loads(envelope["payload"])})
    async with sessions() as db:
        count = await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.event_id.is_not(None)))
        require(count == 2, "postgres_audit_replay_duplicated")
    result["cases"]["postgres_audit_handler_replay"] = "passed"
    return credentials


async def http_cases(lab, sessions, redis, credentials, result):
    import httpx
    from sqlalchemy import func, select

    from app.core.dependencies import get_db, get_redis
    from app.main import app
    from app.modules.identity.models import AuditLog
    from app.modules.network.outbox_models import NetworkOutbox

    require(not app.dependency_overrides, "unexpected_existing_dependency_override")

    async def database():
        async with sessions() as db:
            yield db

    async def redis_dependency():
        yield redis

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_redis] = redis_dependency
    try:
        # ASGITransport intentionally does not start lifespan/Neo4j; startup wiring
        # has its own explicitly substituted unit smoke in test_verify_measured_twin.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lab") as client:
            async def request(method, path, status=200, headers=None, **kwargs):
                response = await client.request(method, path, headers=headers, **kwargs)
                body = response.json()
                require(response.status_code == status, f"http_{method.lower()}_{status}_expected")
                require(set(body) == {"success", "data", "meta", "errors"}, "invalid_http_envelope")
                require(body["success"] is (status < 400), "invalid_http_success")
                return body

            headers = []
            await request("POST", "/api/v1/auth/login", 401,
                          json={"email": credentials[0][0], "password": secrets.token_hex(20)})
            for email, password, _, _ in credentials:
                body = await request("POST", "/api/v1/auth/login", json={"email": email, "password": password})
                headers.append({"Authorization": "Bearer " + body["data"]["access_token"]})
            owner, foreign = headers
            network = (await request("POST", "/api/v1/networks", 201, owner,
                                     json={"workspace_id": credentials[0][3], "name": "HTTP acceptance"}))["data"]
            network_id = network["network_id"]
            base = f"/api/v1/networks/{network_id}"
            device = (await request("POST", base + "/devices", 201, owner,
                                    json={"hostname": "http-lab", "device_type": "ap",
                                          "ip_address": "192.0.2.21"}))["data"]
            await request("PATCH", base + "/devices/" + device["device_id"], headers=owner,
                          json={"spatial_ref_id": "acceptance-slot"})
            async with sessions() as db:
                rows = list((await db.scalars(select(NetworkOutbox).where(
                    NetworkOutbox.network_id == uuid.UUID(network_id)).order_by(NetworkOutbox.sequence))).all())
                require(len(rows) == 3 and all(row.published_at is None and row.attempts == 0 for row in rows),
                        "http_inventory_pending_failed")
            require(await redis.xlen("stream:network") == 0, "inventory_published_inline")
            result["cases"]["authenticated_http_inventory"] = "passed"
            path = base + "/spatial-scene"
            payload = spatial_payload(device["device_id"])
            await request("GET", path, 401)
            require((await request("GET", path, headers=owner))["data"]["revision"] == 0, "initial_revision")
            saved = (await request("PUT", path, headers=owner, json=payload))["data"]
            require(saved["revision"] == 1, "saved_revision")
            require((await request("GET", path, headers=owner))["data"] == saved, "http_reload")
            conflict = await request("PUT", path, 409, owner, json=payload)
            require(conflict["errors"]["code"] == "SPATIAL_REVISION_CONFLICT", "conflict_code")
            await request("GET", path, 403, foreign)
            await request("PUT", path, 403, foreign, json=spatial_payload(device["device_id"], 1))
            require((await request("GET", path, headers=owner))["data"] == saved, "denial_mutated_scene")
            async with sessions() as db:
                count = await db.scalar(select(func.count()).select_from(AuditLog).where(
                    AuditLog.resource_id == uuid.UUID(network_id),
                    AuditLog.event_type == "network.spatial_scene.replaced"))
                require(count == 1, "http_spatial_audit_count")
            result["http_scene_sha256"] = digest(saved)
            result["cases"]["http_spatial_reload_conflict_tenant"] = "passed"
            await spatial_history_cases(request, path, saved, owner, foreign, result)
            await geometry_cases(request, path, device["device_id"], owner, foreign, result)
            await asset_cases(lab, client, request, base, owner, foreign, result)
            await publication_cases(lab, sessions, redis, result)
            await request("POST", "/api/v1/auth/logout", headers=owner)
            await request("GET", path, 401, owner)
            result["cases"]["logout_denial"] = "passed"
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_redis, None)


async def spatial_history_cases(request, path, saved, owner, foreign, result):
    history_path = path + "/history"
    first = (await request("GET", history_path, headers=owner))["data"]
    require(first["total"] == 1 and first["items"][0]["revision"] == 1, "spatial_history_first_revision")
    original = (await request("GET", history_path + "/1", headers=owner))["data"]
    require(original == saved, "spatial_history_body_mismatch")
    await request("GET", history_path, 403, foreign)
    await request("GET", history_path + "/1", 403, foreign)
    changed = json.loads(json.dumps(original))
    changed.pop("revision")
    changed["objects"][0]["position"]["x"] = 9.0
    second = (await request("PUT", path, headers=owner,
                           json={"expected_revision": 1, "scene": changed}))["data"]
    require(second["revision"] == 2, "spatial_history_second_revision")
    restored = (await request("PUT", path, headers=owner, json={
        "expected_revision": 2, "scene": {key: value for key, value in original.items() if key != "revision"},
    }))["data"]
    require(restored == {**original, "revision": 3}, "spatial_restore_not_new_revision")
    require((await request("GET", path, headers=owner))["data"] == restored, "spatial_restore_reload")
    require((await request("GET", history_path + "/1", headers=owner))["data"] == original,
            "spatial_restore_mutated_history")
    require((await request("GET", history_path + "/2", headers=owner))["data"] == second,
            "spatial_restore_mutated_intermediate")
    history = (await request("GET", history_path, headers=owner))["data"]
    require(history["total"] == 3 and [item["revision"] for item in history["items"]] == [3, 2, 1],
            "spatial_history_revision_order")
    result["spatial_history"] = {"revisions": [3, 2, 1], "restored_revision": 3,
                                  "original_sha256": digest(original), "restored_sha256": digest(restored)}
    result["cases"]["http_spatial_history_restore"] = "passed"


async def asset_cases(lab, client, request, base, owner, foreign, result):
    require(os.geteuid() != 0, "asset_acceptance_requires_nonroot")
    content = b'{"asset":{"version":"2.0","generator":"acceptance"},"scene":0,"scenes":[{"nodes":[]}]}\n'
    checksum = hashlib.sha256(content).hexdigest()
    registration = {"version": 1, "translation": {"x": 1.0, "y": 2.0, "z": 3.0},
                    "rotation": {"x": 0.0, "y": 0.0, "z": 0.0}, "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
                    "target_units": "m", "target_up_axis": "y", "source": "acceptance-fixture"}
    path = base + "/campus/model-assets"
    uploaded = (await request("POST", path, headers=owner, json={
        "model_file_name": "acceptance.gltf", "model_mime_type": "model/gltf+json",
        "model_data_base64": base64.b64encode(content).decode(), "model_sha256": checksum,
        "model_size_bytes": len(content), "registration": registration,
    }))["data"]["items"][0]
    require(uploaded["storage_backend"] == "local_cas" and uploaded["registration"] == registration,
            "asset_cas_registration_missing")
    listed = (await request("GET", path, headers=owner))["data"]["items"][0]
    require(listed == uploaded and base64.b64decode(listed["model_data_base64"]) == content, "asset_reload_mismatch")
    response = await client.get(uploaded["download_path"], headers=owner)
    require(response.status_code == 200 and response.content == content, "asset_binary_download_mismatch")
    require(response.headers["cache-control"] == "private, no-store", "asset_download_cache_policy")
    await request("GET", uploaded["download_path"], 403, foreign)
    await request("GET", path, 403, foreign)
    result["assets"] = {"sha256": checksum, "size_bytes": len(content), "storage_backend": "local_cas",
                        "nonroot_uid": os.geteuid(), "private_root_mode": oct(lab.asset_root.stat().st_mode & 0o777)}
    result["cases"]["http_asset_cas_download_tenant"] = "passed"


def geometry_payload(device_id, revision=3):
    payload = spatial_payload(device_id, revision)
    device = payload["scene"]["objects"][0]
    device["parent_id"] = "room"

    def shape(identity, kind, parent, geometry):
        return {**device, "object_id": identity, "name": identity, "object_type": kind,
                "parent_id": parent, "device_id": None, "geometry": geometry,
                "position": {"x": 0.0, "y": 0.0, "z": 0.0}}

    payload["scene"]["objects"] = [
        shape("building", "building", None, {"kind": "box", "width": 20.0, "depth": 12.0, "height": 6.0}),
        shape("floor", "floor", "building", {"kind": "slab", "width": 20.0, "depth": 12.0, "thickness": 0.2}),
        shape("room", "room", "floor", {"kind": "box", "width": 8.0, "depth": 6.0, "height": 3.0}),
        shape("wall", "wall", "room", {"kind": "wall", "length": 6.0, "height": 3.0, "thickness": 0.15,
            "material": {"name": "acceptance-partition", "attenuation_db": None, "source": "acceptance-fixture"}}),
        device,
    ]
    return payload


async def geometry_cases(request, path, device_id, owner, foreign, result):
    legacy = (await request("GET", path, headers=owner))["data"]
    require(all("geometry" not in obj for obj in legacy["objects"]), "legacy_geometry_omission_lost")
    payload = geometry_payload(device_id, legacy["revision"])
    saved = (await request("PUT", path, headers=owner, json=payload))["data"]
    require(saved == {**payload["scene"], "revision": 4}, "geometry_save_changed_body")
    require((await request("GET", path, headers=owner))["data"] == saved, "geometry_reload_mismatch")
    require((await request("GET", path + "/history/4", headers=owner))["data"] == saved, "geometry_history_mismatch")
    await request("GET", path + "/history/4", 403, foreign)
    await request("PUT", path, 403, foreign, json={**payload, "expected_revision": 4})
    await request("PUT", path, 409, owner, json=payload)
    for invalid_kind in ("dimension", "parent", "material"):
        invalid = geometry_payload(device_id, 4)
        objects = invalid["scene"]["objects"]
        if invalid_kind == "dimension":
            objects[0]["geometry"]["width"] = 0
        elif invalid_kind == "parent":
            objects[3]["parent_id"] = "building"
        else:
            objects[3]["geometry"]["material"]["attenuation_db"] = 101
        await request("PUT", path, 422, owner, json=invalid)
    require((await request("GET", path, headers=owner))["data"] == saved, "geometry_denial_mutated_scene")
    require((await request("GET", path + "/history", headers=owner))["data"]["total"] == 4,
            "geometry_denial_created_history")
    restored = (await request("PUT", path, headers=owner, json={"expected_revision": 4,
        "scene": {key: value for key, value in legacy.items() if key != "revision"}}))["data"]
    require(restored == {**legacy, "revision": 5}, "geometry_legacy_restore_changed_body")
    require((await request("GET", path + "/history/4", headers=owner))["data"] == saved,
            "geometry_restore_mutated_history")
    result["geometry"] = {"object_count": 5, "kinds": ["box", "slab", "box", "wall"],
                          "saved_revision": 4, "restored_revision": 5, "scene_sha256": digest(saved),
                          "invalid_statuses": [422, 422, 422], "unknown_attenuation_preserved": True}
    result["cases"]["http_geometry_roundtrip_history_denial"] = "passed"


async def publication_cases(lab, sessions, redis, result):
    from sqlalchemy import func, select

    from app.events.bus import ensure_consumer_groups, run_consumer_loop
    from app.modules.identity.models import AuditLog
    from app.modules.network.outbox import NetworkOutboxPublisher
    from app.modules.network.outbox_models import NetworkOutbox

    worker = [sys.executable, "-m", "scripts.run_network_outbox_worker", "--once", "--batch-size", "32",
              "--lease-seconds", "2", "--publish-timeout", "0.5", "--retry-base-seconds", "0.1"]
    require(lab.stop_redis(), "redis_outage_stop_failed")
    require(await asyncio.to_thread(command, worker, lab.env) != 0, "worker_did_not_fail_during_outage")
    async with sessions() as db:
        rows = list((await db.scalars(select(NetworkOutbox).order_by(NetworkOutbox.sequence))).all())
        require(len(rows) == 5 and all(row.published_at is None for row in rows), "outage_lost_pending")
        require(rows[0].attempts == 1 and rows[0].last_error == "ConnectionError", "outage_retry_not_recorded")
        original = [row.envelope for row in rows]
    lab.start_redis()
    require(await redis.ping(), "redis_restart_ping")
    await asyncio.sleep(0.15)

    class InterruptedRedis:
        async def xadd(self, stream, fields):
            await redis.xadd(stream, fields)
            # Deterministic fault at the real XADD -> database acknowledgement gap.
            raise asyncio.CancelledError

    try:
        await NetworkOutboxPublisher(sessions=sessions, redis=InterruptedRedis(), lease_seconds=1,
                                     publish_timeout=0.5).publish_one()
    except asyncio.CancelledError:
        pass
    else:
        raise AcceptanceFailure("interruption_not_reached")
    require(await redis.xlen("stream:network") == 1, "interrupted_xadd_missing")
    async with sessions() as db:
        first = await db.get(NetworkOutbox, uuid.UUID(original[0]["event_id"]))
        require(first.published_at is None and first.lease_token is not None, "interruption_not_pending")
    await asyncio.sleep(1.1)
    require(await asyncio.to_thread(command, worker, lab.env) == 0, "worker_recovery_failed")
    entries = await redis.xrange("stream:network")
    fields = [item[1] for item in entries]
    require(len(fields) == 6 and fields[0] == fields[1] == original[0] and fields[2:] == original[1:],
            "replay_envelope_not_stable")
    async with sessions() as db:
        require(await db.scalar(select(func.count()).select_from(NetworkOutbox).where(
            NetworkOutbox.published_at.is_(None))) == 0, "outbox_not_drained")
    require(Path(lab.env["WORKER_HEARTBEAT_PATH"] + ".outbox").is_file(), "worker_heartbeat_missing")
    result["cases"]["redis_outage_retry"] = "passed"
    result["cases"]["post_xadd_interruption_stable_replay"] = "passed"
    result["stream_envelopes_sha256"] = digest(fields)
    result["stream_entries"] = len(fields)
    result["distinct_events"] = len({field["event_id"] for field in fields})

    # Uses the actual audit handler, its real configured session factory and real
    # Redis consumer loop. No Neo4j binary is available in this local-service lane.
    from app.events.consumers.audit_consumer import AUDIT_HANDLERS, handle_audit_event

    topology_received = []
    result["topology"] = "substituted_no_private_neo4j"

    async def topology_substitute(event):
        topology_received.append(event["event_id"])

    handlers = {key: [AUDIT_HANDLERS[key], topology_substitute] for key in {f["event_type"] for f in fields}}
    await ensure_consumer_groups(redis)
    task = asyncio.create_task(run_consumer_loop(redis, "stream:network", "nanfo-consumers", "acceptance",
                                                handlers, reclaim_idle_ms=100, batch_size=10))
    try:
        async with asyncio.timeout(10):
            while True:
                async with sessions() as db:
                    count = await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.event_id.is_not(None)))
                pending = await redis.xpending("stream:network", "nanfo-consumers")
                if count == 5 and len(topology_received) == 5 and pending["pending"] == 0:
                    break
                await asyncio.sleep(0.05)
        require(await redis.xlen("stream:dead_letter") == 0, "consumer_dead_letter")
        # Bypass only the bus completion cache to verify Identity's durable replay guard.
        for envelope in fields:
            await handle_audit_event({**envelope, "payload": json.loads(envelope["payload"])})
        async with sessions() as db:
            count = await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.event_id.is_not(None)))
            require(count == 5, "audit_durable_dedup_failed")
        result["audit_event_rows"] = count
        result["topology_substitute_calls"] = len(topology_received)
        result["cases"]["real_audit_consumer_dedup"] = "passed"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    require(lab.stop_redis(), "redis_persistence_stop_failed")
    lab.start_redis()
    require(await redis.xrange("stream:network") == entries, "redis_persistence_entries_changed")
    require((await redis.xpending("stream:network", "nanfo-consumers"))["pending"] == 0,
            "redis_persistence_ack_changed")
    result["cases"]["redis_persistence_restart"] = "passed"


async def exercise(lab, result):
    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.db.postgres import AsyncSessionLocal, get_engine

    get_settings.cache_clear()
    configure_logging("CRITICAL")
    redis = None
    try:
        credentials = await postgres_cases(AsyncSessionLocal, result, inventory_only=lab.measured_snmp)
        if lab.redis_binary is None and lab.docker_redis is None:
            result["blockers"].append("installed_private_redis_server_missing")
            return
        lab.start_redis()
        from redis.asyncio import Redis

        redis = Redis.from_url(get_settings().REDIS_URL, decode_responses=True, socket_timeout=3)
        require(await redis.ping(), "redis_ping_failed")
        result["redis_version"] = (await redis.info("server"))["redis_version"]
        if lab.measured_snmp:
            await measured_pipeline(lab, AsyncSessionLocal, redis, credentials, result)
        else:
            await http_cases(lab, AsyncSessionLocal, redis, credentials, result)
    finally:
        if redis is not None:
            await redis.aclose()
        await get_engine().dispose()


def verify_measured_payloads(payloads: list[dict]) -> dict:
    """Reconstruct observed interval rates independently from exact integer tags."""
    require(bool(payloads), "snmp_no_payloads")
    for payload in payloads:
        tags = payload["tags"]
        require(payload["source"] == "measured_snmp" and tags["synthetic"] is False
                and tags["protocol"] == "SNMPv3" and tags["security_level"] == "authPriv", "snmp_provenance_invalid")
        if payload["metric"] in {"port_rx_bps", "port_tx_bps"}:
            direction = tags["direction"]
            delta = int(tags[f"{direction}_counter_end_decimal"]) - int(tags[f"{direction}_counter_start_decimal"])
            expected = delta * 8 / tags["interval_seconds"]
            require(math.isclose(payload["value"], expected, rel_tol=1e-12), "snmp_rate_reconstruction_failed")
    raw = sorted((p for p in payloads if p["metric"] == "port_rx_bytes"), key=lambda p: p["observed_at"])
    require(len(raw) == 3, "snmp_observation_count")
    counters = [int(p["tags"]["counter_decimal"]) for p in raw]
    require(counters[0] < counters[1] < counters[2], "snmp_counters_did_not_increase")
    return {"raw_rx_counters": counters, "rx_counter_growth": counters[-1] - counters[0],
            "rate_qualities": [p["tags"]["rate_quality"] for p in raw],
            "observed_at": [p["observed_at"] for p in raw],
            "rate_samples": [{"metric": p["metric"], "value": p["value"],
                              "interval_seconds": p["tags"]["interval_seconds"]}
                             for p in payloads if p["metric"] in {"port_rx_bps", "port_tx_bps"}]}


async def measured_pipeline(lab, sessions, redis, credentials, result):
    from dataclasses import asdict
    from unittest.mock import patch

    import httpx
    from sqlalchemy import func, select, update

    from app.core.config import get_settings
    from app.core.dependencies import get_db, get_redis
    from app.db.redis import close_redis, init_redis
    from app.events.bus import completion_key, ensure_consumer_groups, run_consumer_loop
    from app.events.consumers.telemetry_consumer import TELEMETRY_HANDLERS, handle_telemetry_event
    from app.main import app
    from app.modules.identity.models import User
    from app.modules.organization.service import WorkspaceService
    from app.modules.telemetry.models import TelemetryRecord
    from app.modules.telemetry.service import TelemetryIngestionService
    from app.modules.telemetry.snmp_composition import build_measured_snmp_poll_action
    from app.modules.telemetry.snmp_config import SNMPError
    from app.modules.telemetry.snmp_transport import NetSNMPTransport
    from app.websocket.auth import authenticate
    from app.websocket.manager import telemetry_ws_manager

    # Initialize the real owning Redis client used by consumer counters and WS auth.
    # Settings refer exclusively to this lab's loopback endpoint.
    await init_redis()
    lab.snmp = LocalSNMP(lab)
    task = None
    sockets = [CollectingWebSocket(), CollectingWebSocket()]
    network_id = None
    require(not app.dependency_overrides, "unexpected_existing_dependency_override")

    async def database():
        async with sessions() as db:
            yield db

    async def redis_dependency():
        yield redis

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_redis] = redis_dependency
    try:
        await lab.snmp.start()
        result["snmp"] = {"pid": lab.snmp.process.pid, "udp_port": lab.snmp.port,
                          "sys_name": lab.snmp.sys_name, "interface": "lo", "if_index": socket.if_nametoindex("lo"),
                          "listeners": owned_udp_addresses(lab.snmp.process.pid), "observations": [],
                          "websocket_transport": "collecting_substitute_not_network_socket",
                          "auth": "SHA-256", "privacy": "AES", "schema_pin": ACCEPTANCE_SCHEMA}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lab") as client:
            async def request(method, path, status=200, headers=None, **kwargs):
                response = await client.request(method, path, headers=headers, **kwargs)
                require(response.status_code == status, f"snmp_http_{method.lower()}_{status}_expected")
                body = response.json()
                require(body["success"] is (status < 400), "snmp_http_envelope_invalid")
                return body["data"]

            headers, tokens = [], []
            for email, password, _, _ in credentials:
                pair = await request("POST", "/api/v1/auth/login", json={"email": email, "password": password})
                tokens.append(pair["access_token"])
                headers.append({"Authorization": "Bearer " + pair["access_token"]})
            owner, foreign = headers
            network = await request("POST", "/api/v1/networks", 201, owner,
                                    json={"workspace_id": credentials[0][3], "name": "Real local SNMP"})
            network_id = network["network_id"]
            device = await request("POST", f"/api/v1/networks/{network_id}/devices", 201, owner,
                                   json={"hostname": lab.snmp.sys_name, "ip_address": "127.0.0.1", "device_type": "switch"})
            async with sessions() as db:
                workspace = await WorkspaceService(db, redis).get_active_workspace(
                    uuid.UUID(credentials[0][3]), user_id=credentials[0][2])
                org_id = str(workspace.org_id)
            binding = {"version": 1, "org_id": org_id, "workspace_id": credentials[0][3],
                       "network_id": network_id, "device_id": device["device_id"], "actor_user_id": credentials[0][2],
                       "target": "127.0.0.1", "port": lab.snmp.port, "sys_name": lab.snmp.sys_name,
                       "interfaces": [{"if_index": socket.if_nametoindex("lo"), "if_name": "lo"}],
                       "execution_mode": "emulation", "environment": "emulation"}
            private_file(lab.snmp.binding_path, json.dumps(binding))
            settings = get_settings().model_copy(update={
                "TELEMETRY_RUNTIME_ADAPTER_MODE": "measured_snmp",
                "TELEMETRY_MEASURED_SNMP_BINDING_PATH": lab.snmp.binding_path,
                "TELEMETRY_MEASURED_SNMP_CREDENTIALS_PATH": lab.snmp.credentials_path,
                "TELEMETRY_MEASURED_SNMP_POLL_INTERVAL_SECONDS": 6.0,
            })
            ingestion = TelemetryIngestionService(redis=redis)
            action = await build_measured_snmp_poll_action(
                settings=settings, session_factory=sessions, redis=redis, ingestion_service=ingestion)
            await reconcile_measured_workspace(sessions, uuid.UUID(credentials[0][3]), result)
            for token, ws in zip(tokens, sockets, strict=True):
                claims = await authenticate(token, "telemetry")
                # Force both into the target subscription to test real dequeue
                # authorization: the foreign token must be closed, not delivered.
                await telemetry_ws_manager.subscribe(network_id, ws, token_exp=claims["exp"],
                    token_jti=claims["jti"], workspace_id=credentials[0][3], token=token)
            await ensure_consumer_groups(redis)
            task = asyncio.create_task(run_consumer_loop(redis, "stream:telemetry", "nanfo-consumers",
                "measured-acceptance", TELEMETRY_HANDLERS, reclaim_idle_ms=100, batch_size=10))
            real_get = NetSNMPTransport.get
            calls = []

            async def observed_get(transport, binding, interface):
                calls.append(time.monotonic())
                counters = await real_get(transport, binding, interface)
                result["snmp"]["observations"].append({"utc": datetime.now(UTC).isoformat(), **asdict(counters)})
                return counters

            # Observation-only wrapper calls the unmodified real subprocess/parser;
            # no fabricated measurements, callback authorization or transport results.
            with patch.object(NetSNMPTransport, "get", observed_get):
                for index in range(3):
                    await action()
                    if index < 2:
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, socket.socket(
                            socket.AF_INET, socket.SOCK_DGRAM
                        ) as sender:
                            receiver.bind(("127.0.0.1", 0))
                            receiver.settimeout(1)
                            for _ in range(64):
                                sender.sendto(b"n" * 1024, receiver.getsockname())
                                receiver.recvfrom(2048)
                        await asyncio.sleep(6)
                entries = await redis.xrange("stream:telemetry")
                fields = [field for _, field in entries]
                payloads = [json.loads(field["payload"]) for field in fields]
                result["snmp"].update(verify_measured_payloads(payloads))
                require(len(calls) == 3, "snmp_real_get_count")
                result["cases"]["snmp_owner_guarded_real_collection"] = "passed"
                expected = len(fields)

                async def count_rows():
                    async with sessions() as db:
                        return await db.scalar(select(func.count()).select_from(TelemetryRecord).where(
                            TelemetryRecord.device_id == uuid.UUID(device["device_id"])))

                async with asyncio.timeout(15):
                    while await count_rows() != expected or len(sockets[0].frames) != expected:
                        await asyncio.sleep(0.05)
                require((await redis.xpending("stream:telemetry", "nanfo-consumers"))["pending"] == 0,
                        "snmp_consumer_pending")
                require(await redis.xlen("stream:dead_letter") == 0, "snmp_consumer_dead_letter")
                require(all(frame["event"] == "telemetry.metric.ingested" for frame in sockets[0].frames),
                        "snmp_websocket_owner_delivery_failed")
                require(sockets[1].close_codes == [1008] and all(frame["event"] == "error" for frame in sockets[1].frames),
                        "snmp_websocket_tenant_leak")
                delivered = {frame["data"]["metric"]["event_id"] for frame in sockets[0].frames}
                require(delivered == {field["event_id"] for field in fields}, "snmp_websocket_event_ids_mismatch")
                result["cases"]["snmp_websocket_manager_delivery"] = "passed"
                history_url = f"/api/v1/telemetry/history?network_id={network_id}&page_size=200"
                history = await request("GET", history_url, headers=owner)
                require(history["total"] == expected and {row["event_id"] for row in history["items"]} == delivered,
                        "snmp_history_event_ids_mismatch")
                by_id = {field["event_id"]: json.loads(field["payload"]) for field in fields}
                for row in history["items"]:
                    payload = by_id[row["event_id"]]
                    require(all(row[key] == payload[key] for key in (
                        "device_id", "network_id", "workspace_id", "metric", "value", "unit", "source", "tags")),
                        "snmp_persisted_payload_mismatch")
                await request("GET", history_url, 403, foreign)
                device_url = f"/api/v1/telemetry/device/{device['device_id']}?page_size=200"
                require((await request("GET", device_url, headers=owner))["total"] == expected, "snmp_device_history_count")
                await request("GET", device_url, 403, foreign)
                result["cases"]["snmp_authorized_history_tenant_denial"] = "passed"
                await cursor_cases(request, network_id, owner, foreign, credentials, delivered, result)
                # Clear one completion marker and replay the real stream entry:
                # exercise persistence idempotency even past the bus cache.
                replay = fields[0]
                await redis.delete(completion_key("stream:telemetry", "nanfo-consumers", replay["event_id"], handle_telemetry_event))
                await redis.xadd("stream:telemetry", replay)
                async with asyncio.timeout(10):
                    while len(sockets[0].frames) != expected + 1:
                        await asyncio.sleep(0.05)
                require(await count_rows() == expected, "snmp_duplicate_persisted")
                result["cases"]["snmp_real_bus_persistence"] = "passed"
                await retention_cases(lab, sessions, request, owner, foreign, credentials, network_id,
                                      history, fields, result)
                # Revoke the actual Identity row in the owned database; neither
                # the collector's authority check nor transport is replaced.
                async with sessions() as db:
                    await db.execute(update(User).where(User.user_id == uuid.UUID(credentials[0][2])).values(is_active=False))
                    await db.commit()
                before = len(calls)
                stream_before = await redis.xlen("stream:telemetry")
                try:
                    await action()
                except SNMPError:
                    pass
                else:
                    raise AcceptanceFailure("snmp_revoked_actor_allowed")
                require(len(calls) == before and await redis.xlen("stream:telemetry") == stream_before,
                        "snmp_revoked_actor_read_or_published")
                await request("GET", history_url, 401, owner)
                # Already measured event replay must also trigger per-delivery
                # revocation and close the existing owner subscription.
                await redis.delete(completion_key("stream:telemetry", "nanfo-consumers", replay["event_id"], handle_telemetry_event))
                await redis.xadd("stream:telemetry", replay)
                async with asyncio.timeout(10):
                    while not sockets[0].close_codes:
                        await asyncio.sleep(0.05)
                require(sockets[0].close_codes == [1008] and sockets[0].frames[-1]["event"] == "error",
                        "snmp_websocket_revocation_failed")
                require(await count_rows() == expected, "snmp_revocation_changed_persistence")
                result["cases"]["snmp_revocation_before_read"] = "passed"
                result["snmp"].update({"published_unique_events": expected, "persisted_rows": expected,
                    "stream_entries_with_replays": await redis.xlen("stream:telemetry"),
                    "real_get_calls": len(calls), "get_calls_after_revocation": len(calls) - before,
                    "owner_metric_frames": expected + 1, "foreign_metric_frames": 0,
                    "history_sha256": digest(history), "envelopes_sha256": digest(fields),
                    "binding_sha256": payloads[0]["tags"]["binding_sha256"]})
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if network_id:
            for ws in sockets:
                await telemetry_ws_manager.unsubscribe(network_id, ws)
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_redis, None)
        await close_redis()


async def reconcile_measured_workspace(sessions, workspace_id, result):
    from app.modules.telemetry.reconciliation import TelemetryReconciliationService, owner_contracts

    summaries = []
    for owner in owner_contracts():
        for _ in range(30):
            async with sessions() as db:
                progress = await TelemetryReconciliationService(db).step(workspace_id=workspace_id, owner=owner, limit=10)
                await db.commit()
            if progress["complete"]:
                require(progress["unknown"] == 0, "fresh_workspace_reconciliation_unknown")
                summaries.append({"owner": owner, "scanned": progress["scanned"], "unknown": progress["unknown"]})
                break
        else:
            raise AcceptanceFailure("owner_reconciliation_not_bounded")
    result["retention"] = {"reconciliation_before_measurement": summaries}


async def retention_cases(lab, sessions, request, owner, foreign, credentials, network_id, history, fields, result):
    from sqlalchemy import select

    from app.modules.organization.service import WorkspaceService
    from app.modules.telemetry.archive import TelemetryArchiveStore
    from app.modules.telemetry.archive_models import TelemetryArchiveReceipt, TelemetryEventTombstone
    from app.modules.telemetry.models import TelemetryRecord
    from app.modules.telemetry.pin_models import TelemetryEvidencePin
    from app.modules.telemetry.retention import ArchivalAssessmentRequest, TelemetryRetentionService
    from app.modules.telemetry.service import TelemetryPersistenceService

    workspace_id = uuid.UUID(credentials[0][3])
    start = min(datetime.fromisoformat(row["observed_at"]) for row in history["items"]) - timedelta(seconds=1)
    end = datetime.now(UTC) + timedelta(seconds=1)
    report_body = {"workspace_id": str(workspace_id), "network_id": network_id, "report_type": "telemetry",
                   "format": "csv", "date_range": {"start": start.isoformat(), "end": end.isoformat()},
                   "filters": {"metric": "port_rx_bytes", "max_rows": 100}}
    await request("POST", "/api/v1/reports/generate", 403, foreign, json=report_body)
    report = await request("POST", "/api/v1/reports/generate", 202, owner, json=report_body)
    report_url = f"/api/v1/reports/{report['report_id']}?workspace_id={workspace_id}"
    await request("GET", report_url, headers=owner)
    await request("GET", report_url, 403, foreign)
    expected_pins = {uuid.UUID(row["record_id"]) for row in history["items"] if row["metric"] == "port_rx_bytes"}
    async with sessions() as db:
        pins = list((await db.scalars(select(TelemetryEvidencePin).where(
            TelemetryEvidencePin.workspace_id == workspace_id, TelemetryEvidencePin.owner == "report"))).all())
        require({pin.record_id for pin in pins} == expected_pins and len(pins) == 3, "report_did_not_pin_actual_measurements")
    result["cases"]["snmp_report_pin_before_reference"] = "passed"
    archive_root = lab.root / "telemetry-archive"
    archive_root.mkdir(mode=0o700)
    store = TelemetryArchiveStore(archive_root)
    assessment_request = ArchivalAssessmentRequest(workspace_id=workspace_id, start_time=start, end_time=end, batch_size=100)
    async with sessions() as db:
        # Trusted operator acceptance uses actual current authority before calling
        # internal retention contracts; no public retention endpoint is invented.
        await WorkspaceService(db, None).get_active_workspace(workspace_id, user_id=credentials[0][2], require_write=True)
        assessed = await TelemetryRetentionService(db).assess(assessment_request)
        require(set(assessed.pinned) == expected_pins and not assessed.missing_owners and not assessed.coverage_unknown,
                "retention_actual_coverage_or_pins_mismatch")
        applied = await TelemetryRetentionService(db).apply(assessment_request, store=store)
        require(applied.deleted == len(history["items"]) - 3, "retention_delete_count")
        await db.commit()
    history_path = f"/api/v1/telemetry/history?network_id={network_id}&page_size=200"
    retained = await request("GET", history_path, headers=owner)
    require({uuid.UUID(row["record_id"]) for row in retained["items"]} == expected_pins, "retention_removed_pinned_record")
    await request("GET", history_path, 403, foreign)
    by_event = {field["event_id"]: {**field, "payload": json.loads(field["payload"])} for field in fields}
    async with sessions() as db:
        receipts = list((await db.scalars(select(TelemetryArchiveReceipt).where(
            TelemetryArchiveReceipt.workspace_id == workspace_id))).all())
        receipt_ids = [row.record_id for row in receipts]
        require(len(receipts) == applied.deleted, "archive_receipt_count")
        for receipt in receipts:
            require(await db.get(TelemetryEventTombstone, receipt.event_id) is not None, "archive_tombstone_missing")
            require(await db.get(TelemetryRecord, receipt.record_id) is None, "archived_row_still_active")
            event = by_event[str(receipt.event_id)]
            require(await TelemetryPersistenceService(db).persist_event(event) is False, "archived_event_recreated")
            foreign_event = {**event, "payload": {**event["payload"], "workspace_id": credentials[1][3]}}
            require(await TelemetryPersistenceService(db).persist_event(foreign_event) is False, "global_tombstone_tenant_replay")
        await db.commit()
    async with sessions() as db:
        try:
            await TelemetryRetentionService(db).restore(workspace_id=uuid.UUID(credentials[1][3]),
                record_id=receipt_ids[0], store=store)
        except ValueError:
            pass
        else:
            raise AcceptanceFailure("foreign_archive_restore_allowed")
    async with sessions() as db:
        await WorkspaceService(db, None).get_active_workspace(workspace_id, user_id=credentials[0][2], require_write=True)
        for record_id in receipt_ids:
            require(await TelemetryRetentionService(db).restore(workspace_id=workspace_id, record_id=record_id, store=store),
                    "archive_restore_failed")
        await db.commit()
    restored = await request("GET", history_path, headers=owner)
    require(sorted(restored["items"], key=lambda r: r["record_id"]) == sorted(history["items"], key=lambda r: r["record_id"]),
            "archive_restore_not_exact")
    result["retention"].update({"report_id": report["report_id"], "pinned_records": len(expected_pins),
        "archived_restored_records": len(receipt_ids), "tombstone_replay_denials": len(receipt_ids) * 2,
        "restored_history_sha256": digest(restored), "archive_receipts_sha256": digest([
            {"record_id": str(row.record_id), "sha256": row.sha256, "size_bytes": row.size_bytes} for row in receipts])})
    result["cases"]["snmp_archive_tombstone_restore"] = "passed"


async def cursor_cases(request, network_id, owner, foreign, credentials, expected_ids, result):
    path = "/api/v1/telemetry/history"
    params = {"network_id": network_id, "pagination": "cursor", "page_size": 4}
    first = await request("GET", path, headers=owner, params=params)
    require(first["next_cursor"] is not None, "cursor_continuation_missing")
    cursor = first["next_cursor"]
    await request("GET", path, 403, foreign, params={**params, "cursor": cursor})
    # Foreign actor's own authorized workspace still cannot reuse this cursor.
    await request("GET", path, 400, foreign, params={
        "workspace_id": credentials[1][3], "pagination": "cursor", "page_size": 4, "cursor": cursor,
    })
    await request("GET", path, 400, owner, params={**params, "cursor": cursor, "metric": "port_rx_bytes"})
    altered = ("A" if cursor[0] != "A" else "B") + cursor[1:]
    await request("GET", path, 400, owner, params={**params, "cursor": altered})
    rows = list(first["items"])
    upper = (first["upper_observed_at"], first["upper_record_id"])
    pages = 1
    while cursor is not None:
        require(pages < 50, "cursor_traversal_unbounded")
        page = await request("GET", path, headers=owner, params={**params, "cursor": cursor})
        require((page["upper_observed_at"], page["upper_record_id"]) == upper, "cursor_upper_changed")
        rows.extend(page["items"])
        cursor = page["next_cursor"]
        pages += 1
    ids = [row["event_id"] for row in rows]
    require(len(ids) == len(set(ids)) and set(ids) == expected_ids, "cursor_missing_or_duplicate_records")
    order = [(row["observed_at"], row["record_id"]) for row in rows]
    require(order == sorted(order, reverse=True), "cursor_keyset_order")
    result["snmp"]["keyset"] = {"pages": pages, "records": len(rows), "page_size": 4,
                                  "records_sha256": digest(rows), "cross_tenant_denials": [403, 400],
                                  "filter_tamper_denials": [400, 400]}
    result["cases"]["snmp_keyset_cursor_scope_denial"] = "passed"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize creation of private local service processes")
    parser.add_argument("--measured-snmp", action="store_true", help="Run the measured pipeline lane on schema0027 instead of spatial/outbox lane")
    redis_options = parser.add_mutually_exclusive_group()
    redis_options.add_argument("--redis-server", type=Path, help="Installed executable; never a running service address")
    redis_options.add_argument("--redis-image-id", help="Authorize a NEW private container from this exact local sha256 ID")
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live is required")
    if args.redis_image_id and not re.fullmatch(r"sha256:[0-9a-f]{64}", args.redis_image_id):
        parser.error("--redis-image-id must be an exact sha256 image ID, not a tag")
    redis_binary = str(args.redis_server.resolve()) if args.redis_server else shutil.which("redis-server")
    if redis_binary and not os.access(redis_binary, os.X_OK):
        parser.error("Redis executable is unavailable")
    evidence = Path(tempfile.mkdtemp(prefix="measured-twin-acceptance-", dir="/tmp/opencode"))
    root = Path(tempfile.mkdtemp(prefix="private-", dir=evidence))
    result = {"version": 1, "started_at": datetime.now(UTC).isoformat(),
              "scope": "private_local_postgres_redis_http_asgi", "cases": dict.fromkeys(CASES, "blocked"),
              "blockers": [], "topology": "unavailable_not_exercised",
              "full_compose": False, "physical_acceptance": False, "source_before": source_hashes()}
    if args.measured_snmp:
        result["cases"] = dict.fromkeys(("migration_0027", "postgres_inventory_pending", *SNMP_CASES), "blocked")
        result["scope"] = "private_measured_snmp_owner_redis_postgres_http_ws_manager"
    lab = LocalLab(root, redis_binary, args.redis_image_id)
    lab.measured_snmp = args.measured_snmp
    result["ports"] = {"postgres": lab.pg_port, "redis": lab.redis_port}
    try:
        require(shutil.which("initdb") is not None and shutil.which("postgres") is not None, "postgres_binary_missing")
        lab.start_postgres()
        # This repository has no alembic.ini. Exercise the actual env.py with an
        # explicit script location, as the deployment initializer does.
        migration = migration_command()
        require(command([sys.executable, "-c", migration], lab.env) == 0, "migration_failed")
        with environment(lab.env):
            asyncio.run(exercise(lab, result))
    except Exception as exc:  # noqa: BLE001 - never serialize DSNs/passwords from third-party exceptions
        result["failure"] = str(exc) if isinstance(exc, AcceptanceFailure) else type(exc).__name__
    finally:
        result["cleanup"] = lab.cleanup()
        if lab.docker_redis:
            result["owned_docker_redis"] = lab.docker_redis.evidence()
        result["source_after"] = source_hashes()
        result["source_unchanged"] = result["source_before"] == result["source_after"]
        result["source_drift_paths"] = sorted(
            path for path in result["source_before"].keys() | result["source_after"].keys()
            if result["source_before"].get(path) != result["source_after"].get(path)
        )
        if result["source_drift_paths"]:
            result["blockers"].append("source_changed_during_acceptance")
        result["finished_at"] = datetime.now(UTC).isoformat()
        passed = all(value == "passed" for value in result["cases"].values())
        cleaned = all(value is True for key, value in result["cleanup"].items() if key != "owned_pids")
        result["status"] = "passed" if (passed and cleaned and result["source_unchanged"]
                                         and "failure" not in result and not result["blockers"]) else "partial"
        payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
        private_file(evidence / "result.json", payload)
        summary_hash = hashlib.sha256(payload.encode()).hexdigest()
        private_file(evidence / "result.sha256", summary_hash + "\n")
        print(json.dumps({"status": result["status"], "evidence": str(evidence / "result.json"),
                          "sha256": summary_hash, "cases": result["cases"],
                          "failure": result.get("failure"), "blockers": result["blockers"],
                          "cleanup": result["cleanup"]}, indent=2))
    return 0 if result["status"] == "passed" else 2


def migration_command() -> str:
    """Use the actual complete chain; refuse ambiguous/newer heads instead of truncating it."""
    return (
        "from alembic.config import Config; from alembic import command; "
        "from alembic.script import ScriptDirectory; "
        "c = Config(); c.set_main_option('script_location', 'alembic'); "
        f"assert ScriptDirectory.from_config(c).get_heads() == [{ACCEPTANCE_SCHEMA!r}]; "
        f"command.upgrade(c, {ACCEPTANCE_SCHEMA!r})"
    )


if __name__ == "__main__":
    raise SystemExit(main())
