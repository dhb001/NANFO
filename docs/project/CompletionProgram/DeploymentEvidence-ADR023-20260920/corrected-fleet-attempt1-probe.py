"""Private image acceptance, real worker CLI and DB/Redis, no pytest substitutes."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import tempfile
import uuid

from redis.asyncio import Redis
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import get_settings
from app.modules.identity.models import Role, User, UserRole
from app.modules.network.models import Device, Network
from app.modules.organization.models import Organization, OrgMember, Workspace
from app.modules.telemetry.models import TelemetryRecord
from app.modules.telemetry.service import TelemetryPersistenceService
from app.modules.telemetry.fleet_models import FleetBatch


def protected(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return str(path)


async def command(*args, env=None, expected=0):
    process = await asyncio.create_subprocess_exec(*args, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(process.communicate(), 90)
    if process.returncode != expected:
        # Only credential-free CLI status JSON, never driver stderr.
        print(json.dumps({'unexpected_cli_code': process.returncode, 'expected': expected}), flush=True)
        raise AssertionError('CLI exit mismatch')
    return out


async def main():
    os.umask(0o077)
    await command('alembic', 'upgrade', '0027')
    settings = get_settings()
    engine = create_async_engine(settings.POSTGRES_DSN)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    actor, org, workspace, network = (uuid.uuid4() for _ in range(4))
    devices = [uuid.uuid4() for _ in range(3)]
    proofs = []
    children = []
    worker = None
    try:
        async with sessions() as db:
            role = await db.scalar(select(Role).where(Role.name == 'Admin'))
            assert role is not None
            db.add(User(user_id=actor, email=f'{actor}@example.test', hashed_password='unusable-fixture'))
            db.add(Organization(org_id=org, name='Isolated Fleet', slug=org.hex))
            await db.flush()
            db.add(UserRole(user_id=actor, role_id=role.role_id))
            db.add(Workspace(workspace_id=workspace, org_id=org, name='Isolated Fleet'))
            db.add(OrgMember(org_id=org, user_id=actor, org_role='Operator'))
            db.add(Network(network_id=network, workspace_id=workspace, name='Isolated Fleet'))
            await db.flush()
            db.add_all([Device(device_id=device, network_id=network, hostname=f'fleet-{index}',
                               ip_address='127.0.0.1', device_type='switch') for index, device in enumerate(devices)])
            await db.commit()
        with tempfile.TemporaryDirectory(prefix='fleet-acceptance-') as temporary:
            root = Path(temporary)
            credentials = []
            for number in (1, 2):
                directory = root / f'agent{number}'
                directory.mkdir(mode=0o700)
                for name in ('home', 'state', 'config'):
                    (directory / name).mkdir(mode=0o700)
                secret = {'username': 'fleet' + secrets.token_hex(6), 'auth_passphrase': secrets.token_hex(24),
                          'priv_passphrase': secrets.token_hex(24)}
                credentials.append(protected(directory / 'credentials.json', secret))
                config = directory / 'config/snmpd.conf'
                config.write_text(f'agentaddress udp:127.0.0.1:{1160+number}\nsysName fleet-local-{number}\n'
                    f"createUser {secret['username']} SHA-256 {secret['auth_passphrase']} AES {secret['priv_passphrase']}\n"
                    'view measured included .1.3.6.1.2.1.1\nview measured included .1.3.6.1.2.1.2\n'
                    'view measured included .1.3.6.1.2.1.31\nview measured included .1.3.6.1.6.3.10.2.1.2\n'
                    f"rouser {secret['username']} priv -V measured\n")
                config.chmod(0o600)
                children.append(subprocess.Popen(['/usr/sbin/snmpd', '-f', '-C', '-c', str(config), '-p', str(directory / 'agent.pid'), '-Ln'],
                    env={'HOME': str(directory/'home'), 'SNMPCONFPATH': str(directory/'config'),
                         'SNMP_PERSISTENT_DIR': str(directory/'state'), 'MIBS': '', 'LC_ALL': 'C'},
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            await asyncio.sleep(1)
            assert all(child.poll() is None for child in children)
            targets = []
            for index, device in enumerate(devices):
                number = min(index + 1, 2)
                binding = protected(root / f'binding{index}.json', {
                    'version': 1, 'org_id': str(org), 'workspace_id': str(workspace), 'network_id': str(network),
                    'actor_user_id': str(actor), 'device_id': str(device), 'target': '127.0.0.1', 'port': 1160 + number,
                    'sys_name': f'fleet-local-{index+1}', 'interfaces': [{'if_index': 1, 'if_name': 'lo'}],
                    'execution_mode': 'emulation', 'environment': 'emulation', 'max_pending_seconds': 60.0})
                targets.append({'device_id': str(device), 'binding_path': binding, 'credentials_path': credentials[number-1],
                                'interval_seconds': 1.0, 'poll_timeout_seconds': 20.0})
            manifest = protected(root / 'manifest.json', {'version': 1, 'targets': targets})
            env = {**os.environ, 'NANFO_FLEET_MANIFEST_PATH': manifest, 'NANFO_FLEET_CONCURRENCY': '2',
                   'NANFO_FLEET_LEASE_SECONDS': '6', 'NANFO_FLEET_DB_TIMEOUT_SECONDS': '1', 'NANFO_FLEET_SCAN_SECONDS': '.5'}
            for _ in range(2):
                health = json.loads(await command('python', '-m', 'scripts.run_fleet_collector', '--once', env=env, expected=2))
                outcomes = {row['device_id']: row['outcome'] for row in health['devices']}
                assert outcomes[str(devices[0])] == outcomes[str(devices[1])] == 'published'
                assert outcomes[str(devices[2])] == 'collection_deferred'
                await asyncio.sleep(2.2)
            proofs.append('actual_cli_two_targets_bad_third_isolated')
            entries = await redis.xrange('stream:telemetry')
            assert entries
            payloads = [json.loads(event['payload']) for _, event in entries]
            assert {row['device_id'] for row in payloads} == {str(v) for v in devices[:2]}
            assert all(row['source'] == 'measured_snmp' and row['tags']['synthetic'] is False for row in payloads)
            async with sessions() as db:
                count = 0
                for _, event in entries:
                    event = {**event, 'payload': json.loads(event['payload'])}
                    count += bool(await TelemetryPersistenceService(db).persist_event(event))
                    assert not await TelemetryPersistenceService(db).persist_event(event)
                await db.commit()
                assert await db.scalar(select(func.count()).select_from(TelemetryRecord)) == count
                pending = await db.scalar(select(func.count()).select_from(FleetBatch).where(FleetBatch.status == 'pending'))
                assert pending == 0
            proofs.append('real_redis_publication_owner_persistence_dedup')
            probe = json.loads(await command('python', '/opt/nanfo/deploy/check_fleet_health.py', env=env, expected=1))
            assert probe['ready'] is False and probe['checks']['fleet_heartbeat'] == 'unavailable'
            proofs.append('bad_target_health_unavailable')
            # Operator replacement between worker processes, never mutate a live manifest.
            protected(root / 'manifest.json', {'version': 1, 'targets': targets[:2]})
            worker = await asyncio.create_subprocess_exec('python', '-m', 'scripts.run_fleet_collector', env=env,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.sleep(6)
            assert worker.returncode is None
            health = json.loads(await command('python', '/opt/nanfo/deploy/check_fleet_health.py', env=env))
            assert health['ready'] is True
            proofs.append('daemon_cli_healthy_current_two_target_manifest')
            os.kill(worker.pid, signal.SIGSTOP)
            await asyncio.sleep(12)
            health = json.loads(await command('python', '/opt/nanfo/deploy/check_fleet_health.py', env=env, expected=1))
            assert health['checks']['fleet_heartbeat'] == 'unavailable'
            os.kill(worker.pid, signal.SIGCONT)
            worker.kill()
            await worker.wait()
            worker = None
            await asyncio.sleep(7)
            await command('python', '-m', 'scripts.run_fleet_collector', '--once', env=env)
            proofs.append('stale_heartbeat_sigkill_restart')
            async with sessions() as db:
                await db.execute(update(User).where(User.user_id == actor).values(is_active=False))
                await db.commit()
            await asyncio.sleep(2)
            before = await redis.xlen('stream:telemetry')
            health = json.loads(await command('python', '-m', 'scripts.run_fleet_collector', '--once', env=env, expected=2))
            assert all(row['outcome'] == 'collection_deferred' for row in health['devices'])
            assert await redis.xlen('stream:telemetry') == before
            proofs.append('actor_revocation_prevents_publication')
            print(json.dumps({'status': 'passed', 'passed': len(proofs), 'failed': 0, 'blocked': 0,
                              'proofs': proofs, 'persisted_records': count, 'schema': '0027',
                              'provenance': 'actual_private_snmpd_loopback_not_physical',
                              'scope': 'packaged_worker_CLI_and_owner_persistence; no_API_consumer_or_ambiguous_ack_claim'}))
    finally:
        if worker is not None and worker.returncode is None:
            os.kill(worker.pid, signal.SIGCONT)
            worker.kill()
            await worker.wait()
        for child in children:
            child.terminate()
            try:
                child.wait(5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(5)
        await redis.aclose()
        await engine.dispose()

asyncio.run(main())
