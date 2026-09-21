"""Explicit opt-in real local SNMPv3 + private PostgreSQL/Redis acceptance.

Uses separate snmpd processes with private state and loopback ephemeral ports.
No shared daemon, discovery, image build or fabricated counter observations.
"""

import asyncio
import json
import os
import secrets
import socket
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from redis.asyncio import Redis
from sqlalchemy import select, update

from app.modules.identity.models import Role, User, UserRole
from app.modules.network.models import Device, Network
from app.modules.organization.models import Organization, OrgMember, Workspace
from app.modules.telemetry.fleet import FleetWorker
from app.modules.telemetry.fleet_config import FleetSettings
from app.modules.telemetry.fleet_models import FleetBatch
from app.modules.telemetry.service import TelemetryIngestionService
from tests.integration.test_fleet_postgres import database as fleet_database_fixture
from tests.integration.test_fleet_postgres import expire
from tests.unit.test_fleet import protected

database = fleet_database_fixture
pytestmark = pytest.mark.skipif(
    not (os.environ.get("FLEET_TEST_DSN") and os.environ.get("FLEET_TEST_REDIS_URL")
         and os.environ.get("FLEET_LOCAL_SNMP") == "1"),
    reason="explicit private fleet PG/Redis and local SNMP acceptance required",
)


@asynccontextmanager
async def local_agent(directory, number):
    directory.mkdir(mode=0o700)
    for name in ("home", "state", "config"):
        (directory / name).mkdir(mode=0o700)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    credential = {"username": "fleet" + secrets.token_hex(6), "auth_passphrase": secrets.token_hex(24),
                  "priv_passphrase": secrets.token_hex(24)}
    credentials = protected(directory / "credentials.json", credential)
    config = directory / "config/snmpd.conf"
    config.write_text(
        f"agentaddress udp:127.0.0.1:{port}\nsysName fleet-local-{number}\n"
        f"createUser {credential['username']} SHA-256 {credential['auth_passphrase']} AES {credential['priv_passphrase']}\n"
        "view measured included .1.3.6.1.2.1.1\nview measured included .1.3.6.1.2.1.2\n"
        "view measured included .1.3.6.1.2.1.31\nview measured included .1.3.6.1.6.3.10.2.1.2\n"
        f"rouser {credential['username']} priv -V measured\n"
    )
    config.chmod(0o600)
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/snmpd", "-f", "-C", "-c", str(config), "-p", str(directory / "snmpd.pid"), "-Ln",
        env={"HOME": str(directory / "home"), "SNMPCONFPATH": str(directory / "config"),
             "SNMP_PERSISTENT_DIR": str(directory / "state"), "MIBS": "", "LC_ALL": "C"},
        cwd=directory, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            assert process.returncode is None, "private snmpd exited"
            inodes = set()
            for descriptor in Path(f"/proc/{process.pid}/fd").iterdir():
                try:
                    target = descriptor.readlink().as_posix()
                    if target.startswith("socket:["):
                        inodes.add(target[8:-1])
                except FileNotFoundError:
                    pass
            listeners = []
            for protocol in ("udp", "udp6"):
                for line in Path(f"/proc/{process.pid}/net/{protocol}").read_text().splitlines()[1:]:
                    fields = line.split()
                    if fields[9] in inodes:
                        listeners.append((protocol, fields[1]))
            if listeners:
                assert listeners == [("udp", f"0100007F:{port:04X}")]
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("private snmpd listener timeout")
        yield port, credentials
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()
                await process.wait()
        assert process.returncode is not None
        # Remove credential material and private agent state after the gate.
        import shutil
        shutil.rmtree(directory)


async def test_real_two_agents_bad_target_restart_and_owner_revocation(database, tmp_path):
    redis = Redis.from_url(os.environ["FLEET_TEST_REDIS_URL"], decode_responses=True)
    actor, org, workspace, network = (uuid.uuid4() for _ in range(4))
    device_ids = [uuid.uuid4() for _ in range(3)]
    async with database.sessions() as db:
        role = await db.scalar(select(Role).where(Role.name == "Admin"))
        assert role is not None
        db.add(User(user_id=actor, email=f"{actor}@example.test", hashed_password="unusable-local-fixture"))
        db.add(Organization(org_id=org, name="Private Fleet", slug=org.hex))
        await db.flush()
        db.add(UserRole(user_id=actor, role_id=role.role_id))
        db.add(Workspace(workspace_id=workspace, org_id=org, name="Private Fleet"))
        db.add(OrgMember(org_id=org, user_id=actor, org_role="Operator"))
        db.add(Network(network_id=network, workspace_id=workspace, name="Private Fleet"))
        await db.flush()
        db.add_all([Device(device_id=device, network_id=network, hostname=f"fleet-{index}",
                           ip_address="127.0.0.1", device_type="switch") for index, device in enumerate(device_ids)])
        await db.commit()
    try:
        async with local_agent(tmp_path / "agent1", 1) as first, local_agent(tmp_path / "agent2", 2) as second:
            targets = []
            # Third binding points at agent2 but has the wrong pinned sysName:
            # real malformed identity failure rather than invented observations.
            for index, ((port, credentials), device) in enumerate(zip((first, second, second), device_ids, strict=True), 1):
                binding = protected(tmp_path / f"binding{index}.json", {
                    "version": 1, "org_id": str(org), "workspace_id": str(workspace), "network_id": str(network),
                    "actor_user_id": str(actor), "device_id": str(device), "target": "127.0.0.1", "port": port,
                    "sys_name": f"fleet-local-{index}", "interfaces": [{"if_index": socket.if_nametoindex("lo"), "if_name": "lo"}],
                    "execution_mode": "emulation", "environment": "emulation", "max_pending_seconds": 60.0,
                })
                targets.append({"device_id": str(device), "binding_path": str(binding), "credentials_path": str(credentials),
                                "interval_seconds": 1.0, "poll_timeout_seconds": 20.0})
            manifest = protected(tmp_path / "manifest.json", {"version": 1, "targets": targets})
            settings = FleetSettings(manifest_path=manifest, concurrency=2, lease_seconds=3, db_timeout_seconds=0.5)

            def new_worker(ingestion=None):
                return FleetWorker(settings=settings, execution_mode="emulation", repository=database.repository,
                                   locks=database.locks, sessions=database.sessions, redis=redis,
                                   ingestion=ingestion or TelemetryIngestionService(redis))

            instance = new_worker()
            assert await instance.run_once() == ["published", "published", "collection_deferred"]
            for device in device_ids:
                await expire(database, device)
            # Actual subsequent readings; loopback has no guaranteed line speed,
            # so absence of a derived utilization is a valid measured outcome.
            await asyncio.sleep(1.1)
            assert await instance.run_once() == ["published", "published", "collection_deferred"]
            for device in device_ids:
                await expire(database, device)
            ingestion = TelemetryIngestionService(redis)

            class LostAck:
                async def ingest(self, **kwargs):
                    await ingestion.ingest(**kwargs)
                    raise ConnectionError("simulated crash after real Redis success")

            interrupted = new_worker(LostAck())
            assert await interrupted.collect_target(interrupted.manifest.targets[0]) == "collection_deferred"
            async with database.sessions() as db:
                pending = await db.scalar(select(FleetBatch).where(FleetBatch.device_id == device_ids[0], FleetBatch.status == "pending"))
                event_id = pending.samples[0]["event_id"]
            await expire(database, device_ids[0])
            restarted = new_worker()
            assert await restarted.collect_target(restarted.manifest.targets[0]) == "published"
            entries = await redis.xrange("stream:telemetry")
            replay = [entry for _, entry in entries if entry["event_id"] == event_id]
            assert len(replay) == 2 and replay[0]["payload"] == replay[1]["payload"]
            payloads = [json.loads(entry["payload"]) for _, entry in entries
                        if json.loads(entry["payload"])["device_id"] in {str(value) for value in device_ids}]
            assert {value["device_id"] for value in payloads} == {str(value) for value in device_ids[:2]}
            assert all(value["tags"]["synthetic"] is False and value["source"] == "measured_snmp" for value in payloads)
            # Fresh real owner service checks must observe a revoked actor.
            async with database.sessions() as db:
                await db.execute(update(User).where(User.user_id == actor).values(is_active=False))
                await db.commit()
            await expire(database, device_ids[0])
            before = await redis.xlen("stream:telemetry")
            assert await restarted.collect_target(restarted.manifest.targets[0]) == "collection_deferred"
            assert await redis.xlen("stream:telemetry") == before
            health = await restarted.health()
            assert health["status"] == "degraded" and len(health["devices"]) == 3
            await redis.delete(f"nanfo:fleet:health:v1:{restarted.owner_id}")
    finally:
        await redis.aclose()
