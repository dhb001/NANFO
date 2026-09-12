"""Opt-in ADR018 physical overrides in owned disposable infrastructure only.

PYTHONPATH=.:.. poetry run python scripts/verify_operator_override.py --live
Docker is verifier-only. API/workers have read-only filesystems, no Docker socket,
and only the Intent worker can write the dedicated command mailbox.
"""

import argparse
import asyncio
import errno
import json
import logging
import os
import secrets
import signal
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.modules.identity.repository import UserRepository
from app.modules.intent.lab import digest
from scripts.bind_emulation import bind_emulation, save_binding
from scripts.verify_execution import (
    _READBACK,
    VerificationError,
    assert_lab_idle,
    check,
    external,
    intent_payload,
    port,
    private_json,
    stop,
    until,
    verify_no_flow_reinstall,
    verify_result,
)

OPERATOR_IMAGE = 'sha256:d91efe1717f29a277683b735418877d73243ae24ab80e4c2c3311f6f0343c05c'
CASES = (('expiry_restart', 60), ('stop_during_restoration', 10), ('expiry_during_capture', 15),
         ('stop_during_capture', 60), ('lab_restart_holding', 60), ('actor_revocation', 60))

_CAPTURE = r'''
import json, socket
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
    client.settimeout(60)
    client.connect('/run/nanfo/control.sock')
    client.sendall(b'paths\n')
    data = bytearray()
    while len(data) <= 65536:
        chunk = client.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
    print(json.dumps(json.loads(data)))
'''

_CAPTURE_CHILDREN = r'''
import json
from pathlib import Path
children = []
for path in Path('/proc').iterdir():
    if path.name.isdigit():
        try:
            args = (path / 'cmdline').read_bytes().split(b'\0')
            if args and (args[0].split(b'/')[-1] == b'tcpdump' or b'emulation.probe_paths' in args):
                children.append({'pid': int(path.name), 'kind': 'tcpdump' if args[0].split(b'/')[-1] == b'tcpdump' else 'probe_sender'})
        except OSError:
            pass
print(json.dumps(children))
'''

_PHYSICAL = r'''
import json, re, subprocess
from pathlib import Path
switches = {}
for name in ('access1', 'dist1', 'core', 'dist2', 'access2'):
    flows = subprocess.check_output(['ovs-ofctl', '-O', 'OpenFlow13', 'dump-flows', name]).decode()
    switches[name] = {'flows': flows, 'owned_flows': sum('cookie=0x4e414e46' in line for line in flows.splitlines())}
pids = []
for path in Path('/proc').iterdir():
    if path.name.isdigit():
        try:
            if b'mininet:h1' in (path / 'cmdline').read_bytes().split(b'\0'):
                pids.append(path.name)
        except OSError:
            pass
if len(pids) != 1:
    raise RuntimeError('Ambiguous host namespace')
probe = subprocess.run(['nsenter', '-t', pids[0], '-n', '--', 'ping', '-n', '-c', '3', '-W', '2', '10.77.0.3'],
                       capture_output=True, text=True, timeout=12)
match = re.search(r'(\d+) packets transmitted, (\d+) received', probe.stdout)
if probe.returncode or not match or match.groups() != ('3', '3'):
    raise RuntimeError('Independent physical ping failed')
path = Path('/results/.journal.json')
state = json.loads(path.read_text()) if path.exists() else {'active': None, 'blocked': False, 'records': {}, 'actions': []}
print(json.dumps({'switches': switches, 'owned_flow_count': sum(s['owned_flows'] for s in switches.values()),
                 'ping': {'sent': 3, 'received': 3, 'output': probe.stdout}, 'active': state['active'],
                 'blocked': state['blocked'], 'record_count': len(state['records']), 'action_count': len(state['actions'])}))
'''

_READ_ONLY_PROOF = r'''
import errno, json, os, sys
from pathlib import Path
directory = Path(sys.argv[1])
journal = directory / '.journal.json'
assert journal.read_bytes()
denied = []
for path, flags in ((journal, os.O_WRONLY), (directory / '.backend-write-probe', os.O_WRONLY | os.O_CREAT | os.O_EXCL)):
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as error:
        assert error.errno in (errno.EROFS, errno.EACCES, errno.EPERM)
        denied.append(error.errno)
    else:
        os.close(fd)
        raise RuntimeError('Producer journal is writable')
assert not Path('/run/docker.sock').exists()
print(json.dumps({'journal_readable': True, 'journal_write_denied': True, 'directory_write_denied': True,
                  'docker_socket_absent': True, 'denial_errno': denied}))
'''


def sandbox(directory, *, commands=False):
    args = ['bwrap', '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
            '--tmpfs', '/tmp', '--tmpfs', '/run', '--unshare-user', '--unshare-pid', '--die-with-parent',
            '--ro-bind', str(directory), str(directory)]
    if commands:
        args += ['--bind', str(directory / 'commands'), str(directory / 'commands')]
    return args


async def verify(directory, artifact):
    from emulation.topology import manifest

    configure_logging('CRITICAL')
    logging.disable(logging.CRITICAL)
    root = Path(__file__).resolve().parents[2]
    backend = root / 'backend'
    suffix = uuid.uuid4().hex
    ports = {kind: port() for kind in ('postgres', 'redis', 'neo4j', 'api')}
    env = {**os.environ, **{key: str(value) for key, value in get_settings().model_dump(exclude_computed_fields=True).items()}}
    env.update(APP_ENV='verification', LOG_LEVEL='CRITICAL', EXECUTION_MODE='emulation', EMULATION_CONTROL_ENABLED='true',
        POSTGRES_HOST='127.0.0.1', POSTGRES_PORT=str(ports['postgres']), POSTGRES_DB='override_verify', POSTGRES_USER='verifier',
        POSTGRES_PASSWORD=secrets.token_hex(24), REDIS_HOST='127.0.0.1', REDIS_PORT=str(ports['redis']), REDIS_DB='0',
        REDIS_PASSWORD=secrets.token_hex(24), NEO4J_URI=f"bolt://127.0.0.1:{ports['neo4j']}", NEO4J_USER='neo4j',
        NEO4J_PASSWORD=secrets.token_hex(24), JWT_SECRET_KEY=secrets.token_hex(48), TELEMETRY_RUNTIME_ADAPTER_MODE='stub',
        EMULATION_EXECUTION_LEASE_SECONDS='5', EMULATION_EXECUTION_POLL_SECONDS='0.1', EMULATION_EXECUTION_TIMEOUT_SECONDS='120',
        EMULATION_COMMANDS_PATH=str(directory / 'commands'), EMULATION_RESULTS_PATH=str(directory / 'results'),
        EMULATION_SNAPSHOT_PATH=str(directory / 'output' / 'snapshot.json'), EMULATION_BINDING_PATH=str(directory / 'binding' / 'binding.json'),
        PYTHONPATH=f'{backend}:{root}', PYTHONDONTWRITEBYTECODE='1')
    for name in ('commands', 'results', 'output', 'binding'):
        (directory / name).mkdir(mode=0o700 if name == 'binding' else 0o755)
    isolated = Settings(_env_file=None, **{key: env[key] for key in Settings.model_fields})
    containers, processes, capture_tasks = [], [], []
    engine = None
    config = directory / 'redis.conf'
    lab_name = 'nanfo-override-lab-' + suffix
    try:
        artifact['stage'] = 'preflight'
        await assert_lab_idle()
        artifact['image'] = (await external('docker', 'image', 'inspect', OPERATOR_IMAGE, '--format', '{{.Id}}')).strip()
        check(artifact['image'] == OPERATOR_IMAGE, 'Operator image identity mismatch')
        check(not (await external('docker', 'ps', '--filter', f'ancestor={OPERATOR_IMAGE}', '-q')).strip(), 'Operator lab slot busy')
        artifact['backend_python'] = sys.executable
        await external(*sandbox(directory), '/usr/bin/true')
        artifact['stage'] = 'isolated_infrastructure'
        for kind, image, target, args, extra in [
            ('postgres', 'postgres:16-alpine', 5432, ['-e', 'POSTGRES_USER', '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_DB'], {}),
            ('neo4j', 'neo4j:5.25-community', 7687, ['-e', 'NEO4J_AUTH', '-e', 'NEO4J_server_memory_heap_initial__size=256m',
             '-e', 'NEO4J_server_memory_heap_max__size=256m', '-e', 'NEO4J_server_memory_pagecache_size=128m'],
             {'NEO4J_AUTH': 'neo4j/' + env['NEO4J_PASSWORD']}),
        ]:
            identity = (await external('docker', 'run', '-d', '--name', f'nanfo-override-{kind}-{suffix}',
                '-p', f'127.0.0.1:{ports[kind]}:{target}', *args, image, env={**env, **extra})).strip()
            containers.append(identity)
        fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(f'bind 0.0.0.0\nprotected-mode yes\nsave ""\nappendonly no\nrequirepass {env["REDIS_PASSWORD"]}\n')
        containers.append((await external('docker', 'run', '-d', '--name', 'nanfo-override-redis-' + suffix,
            '--user', str(os.geteuid()), '-p', f"127.0.0.1:{ports['redis']}:6379", '--mount',
            f'type=bind,source={config},target=/run/redis.conf,readonly', 'redis:7-alpine', 'redis-server', '/run/redis.conf')).strip())
        engine = create_async_engine(isolated.POSTGRES_DSN)
        async def database_ready():
            try:
                async with engine.connect() as db:
                    return await db.scalar(text('SELECT 1')) == 1
            except Exception:
                return False
        await until(database_ready)
        await external(sys.executable, '-m', 'alembic', '-c', 'alembic/alembic.ini', 'upgrade', '0016', env=env, cwd=backend)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        users = {}
        async with sessions() as db:
            check(await db.scalar(text('SELECT version_num FROM alembic_version')) == '0016', 'Migration0016 missing')
            for name in ('operator', 'supervisor'):
                password = secrets.token_urlsafe(32)
                user = await UserRepository(db).create(f'{name}@override.example', hash_password(password), name)
                await UserRepository(db).assign_role(user.user_id, 'Admin')
                users[name] = (str(user.user_id), password)
            await db.commit()
        artifact['checks']['migration'] = '0016'
        import redis.asyncio as aioredis
        from neo4j import AsyncGraphDatabase

        async def infrastructure_ready():
            try:
                async with aioredis.from_url(isolated.REDIS_URL) as redis:
                    await redis.ping()
                async with AsyncGraphDatabase.driver(isolated.NEO4J_URI, auth=(isolated.NEO4J_USER, isolated.NEO4J_PASSWORD)) as driver:
                    await driver.verify_connectivity()
                return True
            except Exception:
                return False
        await until(infrastructure_ready, timeout=120)

        async def spawn(script=None):
            args = ([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(ports['api']),
                     '--log-level', 'critical', '--no-access-log'] if script is None else [sys.executable, f'scripts/{script}.py'])
            process = await asyncio.create_subprocess_exec(*sandbox(directory, commands=script == 'run_execution_worker'), *args,
                env=env, cwd=backend, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            processes.append(process)
            return process

        api = await spawn()
        base = f"http://127.0.0.1:{ports['api']}"
        async with httpx.AsyncClient(base_url=base, timeout=20, trust_env=False) as client, \
                httpx.AsyncClient(base_url=base, timeout=20, trust_env=False) as supervisor:
            async def request(method, path, *, actor=client, expected=200, **kwargs):
                response = await actor.request(method, path, **kwargs)
                check(response.status_code == expected, f'HTTP {method} {path}: {response.status_code}')
                if expected == 204:
                    return None
                value = response.json()
                check(value['success'] == (expected < 400), 'Canonical envelope mismatch')
                return value['data'] if expected < 400 else value['errors']
            async def api_ready():
                check(api.returncode is None, 'Sandbox API exited')
                try:
                    return (await client.get('/api/openapi.json')).status_code == 200
                except httpx.TransportError:
                    return False
            await until(api_ready, timeout=120)
            binding = await bind_emulation(client, email='operator@override.example', password=users['operator'][1],
                manifest=manifest(), org_slug='override-verifier', workspace_name='Override verifier', network_name='campus-small-v1')
            save_binding(binding, Path(env['EMULATION_BINDING_PATH']), Path(env['EMULATION_SNAPSHOT_PATH']))
            for name, actor in (('operator', client), ('supervisor', supervisor)):
                login = await request('POST', '/api/v1/auth/login', actor=actor,
                    json={'email': f'{name}@override.example', 'password': users[name][1]})
                actor.headers['Authorization'] = 'Bearer ' + login['access_token']
            orgs = await request('GET', '/api/v1/organizations')
            org_id = orgs['items'][0]['org_id']
            await request('POST', f'/api/v1/organizations/{org_id}/members', expected=201,
                json={'user_id': users['supervisor'][0], 'org_role': 'Admin'})
            await assert_lab_idle()
            lab_env = {**os.environ, 'EMULATION_CONTROL_ENABLED': 'true', 'EMULATION_BINDING_DIGEST': digest(binding.model_dump(mode='json'))}
            containers.append((await external('docker', 'run', '-d', '--name', lab_name, '--privileged', '--network', 'none',
                '--pids-limit', '256', '--memory', '768m', '--cpus', '2', '--tmpfs', '/run:exec,size=64m', '--tmpfs', '/tmp:exec,size=64m',
                '-e', 'EMULATION_CONTROL_ENABLED', '-e', 'EMULATION_BINDING_DIGEST',
                '--mount', f"type=bind,source={directory / 'output'},target=/output",
                '--mount', f"type=bind,source={directory / 'commands'},target=/commands,readonly",
                '--mount', f"type=bind,source={directory / 'results'},target=/results", artifact['image'], env=lab_env)).strip())
            async def lab_ready():
                try:
                    return json.loads(await external('docker', 'exec', lab_name, 'python', '-m', 'emulation.runner', '--request', 'status', timeout=5))['passed']
                except VerificationError:
                    return False
            await until(lab_ready, timeout=100)
            async def capture():
                check(len(list((directory / 'output').glob('probe-capture-*'))) < 8, 'Owned capture limit reached')
                return json.loads(await external('docker', 'exec', '-i', lab_name, 'python', '-', stdin=_CAPTURE, timeout=70))
            async def capture_children():
                return json.loads(await external('docker', 'exec', '-i', lab_name, 'python', '-', stdin=_CAPTURE_CHILDREN, timeout=5))
            baseline_capture = await capture()
            check(baseline_capture.get('passed') is True, 'Baseline capture failed')
            artifact['checks']['baseline_capture'] = baseline_capture
            intent_worker = await spawn('run_execution_worker')
            autonomy_worker = await spawn('run_autonomy_worker')
            scope = {'network_id': str(binding.network_id)}
            workspace = str(binding.workspace_id)
            async def control():
                return await request('GET', '/api/v1/autonomy', actor=supervisor, params=scope)
            async def physical():
                value = json.loads(await external('docker', 'exec', '-i', lab_name, 'python', '-', stdin=_PHYSICAL, timeout=20))
                value['observed_at'] = datetime.now(UTC).isoformat()
                return value
            baseline = await physical()
            check(baseline['owned_flow_count'] == 0 and baseline['active'] is None, 'Nonempty baseline')
            artifact['checks']['baseline'] = baseline
            config_request = {**scope, 'expected_revision': 0, 'reason': 'Physical verifier operational interval',
                              'operational': {'decision_interval_seconds': 3}, 'training': {}}
            configured = await request('PUT', '/api/v1/autonomy/configuration', json=config_request)
            await request('PUT', '/api/v1/autonomy/configuration', json=config_request, expected=409)
            check(configured['training_status'] == 'not_requested' and configured['effective_training'] is None, 'Training settings changed')
            await request('PUT', '/api/v1/autonomy', json={**scope, 'expected_revision': configured['control_revision'], 'mode': 'monitor'})
            async def cycles():
                return [row for row in (await control())['decisions'] if row['status'] == 'observed']
            observed = await until(cycles, lambda rows: len(rows) >= 3, timeout=30)
            stamps = sorted(datetime.fromisoformat(row['created_at']).timestamp() for row in observed)
            gaps = [b - a for a, b in zip(stamps, stamps[1:])]
            check(all(2.5 <= gap <= 6 for gap in gaps), 'Actual worker did not apply configured interval')
            artifact['checks']['configuration'] = {'revision': configured['revision'], 'training_status': configured['training_status'],
                                                  'interval_seconds': 3, 'observed_cycle_gaps_seconds': gaps}

            for case, duration in CASES:
                artifact['stage'] = case
                await asyncio.sleep(3.2)
                validated = await request('POST', '/api/v1/intents/validate', json={**scope, 'workspace_id': workspace, 'intent': intent_payload('reroute')})
                check(validated['status'] == 'validated', 'Real manual reroute validation failed')
                intent_id = validated['intent_id']
                execute_body = {'workspace_id': workspace, 'intent_id': intent_id, 'manual_approval': True, 'idempotency_key': intent_id}
                accepted = await request('POST', '/api/v1/intents/execute', expected=202, json=execute_body)
                execution_id = accepted['execution_provenance']['execution_id']
                async def detail():
                    return await request('GET', f'/api/v1/intents/{intent_id}', actor=supervisor, params={'workspace_id': workspace})
                await until(detail, lambda row: row['execution_provenance'].get('phase') == 'completed', timeout=60)
                original = json.loads((directory / 'commands' / f'{execution_id}.json').read_bytes())
                current = await control()
                enrollment_body = {**scope, 'intent_id': intent_id, 'execution_id': execution_id, 'expected_revision': current['revision'],
                    'reason': 'Physical ' + case, 'duration_seconds': duration, 'return_mode': 'monitor'}
                enrolled = await request('POST', '/api/v1/autonomy/overrides', expected=201, json=enrollment_body)
                await request('POST', '/api/v1/autonomy/overrides', expected=409, json=enrollment_body)
                override_id = enrolled['override_id']
                async def override():
                    rows = await request('GET', '/api/v1/autonomy/overrides', actor=supervisor, params=scope)
                    return next(row for row in rows['overrides'] if row['override_id'] == override_id)
                before = await physical()
                check(before['owned_flow_count'] == 10 and before['active'] == execution_id, 'Reroute not physically active')
                proof = json.loads(await external(*sandbox(directory), sys.executable, '-c', _READ_ONLY_PROOF, str(directory / 'results'), env=env, cwd=backend))
                check(all(value in (errno.EROFS, errno.EACCES, errno.EPERM) for value in proof['denial_errno']), 'Read-only proof failed')
                evidence = {'enrolled': enrolled, 'before': before, 'filesystem': proof, 'duration_seconds': duration}
                artifact['cases'][case] = evidence
                capture_task = None
                if case == 'expiry_restart':
                    await asyncio.sleep(3)
                    evidence['worker_killed_at'] = datetime.now(UTC).isoformat()
                    await stop(autonomy_worker, kill=True)
                    await asyncio.sleep(5)
                    check((await override())['status'] == 'holding', 'Hold did not survive worker death')
                    held = await physical()
                    verify_no_flow_reinstall(before, held)
                    autonomy_worker = await spawn('run_autonomy_worker')
                    evidence['worker_restarted_at'] = datetime.now(UTC).isoformat()
                    await asyncio.sleep(3)
                    verify_no_flow_reinstall(held, await physical())
                elif case == 'actor_revocation':
                    await stop(autonomy_worker, kill=True)
                    await request('DELETE', f"/api/v1/organizations/{org_id}/members/{users['operator'][0]}", actor=supervisor, expected=204)
                    evidence['revoked_at'] = datetime.now(UTC).isoformat()
                    await request('POST', '/api/v1/intents/execute', json=execute_body, expected=403)
                    await request('GET', '/api/v1/autonomy/overrides', params=scope, expected=403)
                    autonomy_worker = await spawn('run_autonomy_worker')
                elif case in ('expiry_during_capture', 'stop_during_capture'):
                    previous_capture = (directory / 'output' / 'probe-paths.json').read_bytes()
                    if case == 'expiry_during_capture':
                        remaining = (datetime.fromisoformat(enrolled['expires_at']) - datetime.now(UTC)).total_seconds()
                        await asyncio.sleep(max(0, remaining - 1))
                    else:
                        # Freeze only our recovery worker after the completed Intent
                        # lease elapses. Resume after STOP commits, so a stale sample
                        # of next_check_at cannot let an authority check win the race.
                        await asyncio.sleep(6)
                        autonomy_worker.send_signal(signal.SIGSTOP)
                        async with sessions() as db:
                            next_check = await db.scalar(text('SELECT next_check_at FROM autonomy_overrides WHERE override_id=:id'),
                                {'id': uuid.UUID(override_id)})
                        evidence['scheduled_authority_check_at'] = next_check.isoformat()
                        await asyncio.sleep(max(0, (next_check - datetime.now(UTC)).total_seconds()))
                    evidence['capture_requested_at'] = datetime.now(UTC).isoformat()
                    capture_task = asyncio.create_task(capture())
                    capture_tasks.append(capture_task)
                    children = await until(capture_children, timeout=5, message='No actual capture children observed')
                    evidence['capture_children_at_trigger'] = children
                    evidence['capture_children_observed_at'] = datetime.now(UTC).isoformat()
                    check(not capture_task.done(), 'Capture ended before trigger')
                    if case == 'expiry_during_capture':
                        check(datetime.now(UTC) < datetime.fromisoformat(enrolled['expires_at']), 'Capture started after expiry')
                    else:
                        evidence['stop_requested_at'] = datetime.now(UTC).isoformat()
                        stopped = await request('POST', '/api/v1/autonomy/stop', actor=supervisor, json=scope)
                        check(stopped['emergency_stopped'], 'Capture STOP not latched')
                        evidence['stop_committed_at'] = datetime.now(UTC).isoformat()
                        autonomy_worker.send_signal(signal.SIGCONT)
                    response = await capture_task
                    evidence['capture_finished_at'] = datetime.now(UTC).isoformat()
                    evidence['capture_response'] = response
                    check(response.get('passed') is False and response.get('status') == 'partial', 'Control did not interrupt capture')
                    check((directory / 'output' / 'probe-paths.json').read_bytes() == previous_capture, 'Interrupted capture replaced evidence')
                    check(not await capture_children(), 'Capture children leaked')
                    evidence['prior_capture_unchanged'] = True
                elif case == 'lab_restart_holding':
                    retained_result = (directory / 'results' / f'{execution_id}.json').read_bytes()
                    evidence['lab_restart_started_at'] = datetime.now(UTC).isoformat()
                    await external('docker', 'restart', '--time', '10', lab_name, timeout=60)
                    await until(lab_ready, timeout=100)
                    latest_run = json.loads(await external('docker', 'exec', lab_name, 'python', '-m', 'emulation.runner', '--request', 'status'))['run_id']
                    check(latest_run != original['run_id'], 'Lab restart did not create a new run')
                    check((directory / 'results' / f'{execution_id}.json').read_bytes() == retained_result, 'Original completion receipt not retained')
                    check((await detail())['execution_provenance']['phase'] == 'completed', 'Historical backend completion changed before expiry')
                    check((await override())['status'] == 'holding', 'Override did not remain holding after lab restart')
                    restarted = await physical()
                    check(restarted['owned_flow_count'] == 0 and restarted['active'] is None, 'New run recovery not physically clean')
                    evidence.update(current_run_id=latest_run, old_completed_result_retained=True,
                                    lab_restart_ready_at=datetime.now(UTC).isoformat(), after_lab_restart=restarted)
                else:
                    intent_worker.send_signal(signal.SIGSTOP)
                    pending = await until(override, lambda row: row['status'] == 'restoring', timeout=30)
                    check(pending['restored_at'] is None, 'Restoration incorrectly completed without Intent worker')
                    evidence['stop_requested_at'] = datetime.now(UTC).isoformat()
                    stopped = await request('POST', '/api/v1/autonomy/stop', actor=supervisor, json=scope)
                    check(stopped['emergency_stopped'], 'STOP not latched')
                    intent_worker.send_signal(signal.SIGCONT)
                terminal = await until(override, lambda row: row['status'] in ('returned', 'return_blocked'), timeout=100)
                after = await physical()
                journal = json.loads(await external('docker', 'exec', '-i', lab_name, 'python', '-', execution_id, stdin=_READBACK))
                verify_result(original, journal['result'], status='cancelled')
                latest_receipt = json.loads((directory / 'results' / f'{execution_id}.json').read_bytes())
                check(latest_receipt == journal['result'], 'Latest mailbox receipt differs from journal')
                check(datetime.fromisoformat(latest_receipt['completed_at']) >= datetime.fromisoformat(enrolled['configuration_verified_at']),
                      'Cancellation recycled historical proof')
                if case == 'lab_restart_holding':
                    proof = latest_receipt['verification']
                    check(proof.get('recovered_obsolete') is True and proof.get('no_mutation_verified') is True
                          and proof.get('current_run_id') == evidence['current_run_id'], 'Missing fresh current-run obsolete proof')
                    check(datetime.fromisoformat(latest_receipt['completed_at']) >= datetime.fromisoformat(enrolled['expires_at']),
                          'Obsolete cancellation receipt predates expiry')
                check(after['owned_flow_count'] == 0 and after['active'] is None and not after['blocked'], 'Physical restoration incomplete')
                wire = json.loads((directory / 'commands' / f'{execution_id}.json').read_bytes())
                check(wire == {**original, 'operation': 'cancel'}, 'Recovery altered exact enrolled command')
                check(after['record_count'] == before['record_count'] and after['action_count'] <= before['action_count'], 'Recovery replayed execution')
                check(terminal['verification']['safe_to_release'] and terminal['restored_at'], 'Backend did not verify physical restoration')
                restored = datetime.fromisoformat(terminal['restored_at'])
                evidence.update(terminal=terminal, after=after, lab_result=journal['result'],
                    enrollment_to_verified_seconds=(restored - datetime.fromisoformat(enrolled['created_at'])).total_seconds(),
                    trigger_to_verified_seconds=(restored - datetime.fromisoformat(evidence.get('revoked_at', evidence.get('stop_requested_at', enrolled['expires_at'])))).total_seconds(),
                    exact_cancel_only=True, no_execute_replay=True)
                if case in ('expiry_restart', 'expiry_during_capture', 'lab_restart_holding'):
                    check(restored >= datetime.fromisoformat(enrolled['expires_at']), 'Early expiry restoration')
                    check(terminal['status'] == 'returned', 'Monitor return failed')
                elif case == 'actor_revocation':
                    check(terminal['status'] == 'return_blocked' and 'return_actor_unauthorized' in terminal['reasons'], 'Revoked actor returned')
                    async with sessions() as db:
                        row = (await db.execute(text('SELECT actor_id, cancelled_by_user_id, cancel_requested FROM intent_executions WHERE execution_id=:id'),
                            {'id': uuid.UUID(execution_id)})).one()
                    check(row.actor_id == users['operator'][0] and row.cancelled_by_user_id is None and row.cancel_requested, 'Compensation impersonated actor')
                    evidence['no_impersonation'] = True
                else:
                    check(terminal['status'] == 'return_blocked' and 'emergency_stop_latched' in terminal['reasons'], 'STOP lost to return')
                    current = await control()
                    returned = await request('POST', f'/api/v1/autonomy/overrides/{override_id}/return', actor=supervisor,
                        json={'expected_revision': current['revision'], 'reason': 'Verify explicit return cannot clear STOP'})
                    check(returned['status'] == 'return_blocked' and (await control())['emergency_stopped'], 'Explicit return cleared STOP')
                    evidence['explicit_return'] = returned
                    # A separate explicit ordinary mode PUT, not override return,
                    # clears the resolved STOP for the subsequent revocation case.
                    current = await control()
                    await request('PUT', '/api/v1/autonomy', actor=supervisor,
                        json={**scope, 'expected_revision': current['revision'], 'mode': 'monitor'})
                check((await control())['mode'] == 'monitor', 'Unexpected autonomous activation')
            final_capture = await capture()
            check(final_capture.get('passed') is True, 'Final restored capture failed')
            artifact['checks']['final_capture'] = final_capture
            artifact['checks']['capture_directories'] = sorted(path.name for path in (directory / 'output').glob('probe-capture-*'))
            check(len(artifact['checks']['capture_directories']) <= 8, 'Capture retention exceeded')
            async with sessions() as db:
                check(await db.scalar(text('SELECT count(*) FROM intent_executions')) == len(CASES), 'Unexpected execution jobs')
                check(await db.scalar(text("SELECT count(*) FROM intent_executions WHERE blocks_lab OR phase != 'cancelled'")) == 0, 'Unresolved Intent execution')
                check(await db.scalar(text("SELECT count(*) FROM autonomy_overrides WHERE status IN ('holding','restoring')")) == 0, 'Unresolved override')
                check(await db.scalar(text('SELECT count(*) FROM autonomy_model_diagnostics')) == 0, 'Unexpected model inference')
            artifact['checks']['final'] = {'executions': len(CASES), 'cancelled': len(CASES), 'owned_flows': 0, 'active': None, 'model_inferences': 0}
        artifact.update(passed=True, stage='complete')
    finally:
        failures = []
        for task in capture_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*capture_tasks, return_exceptions=True)
        for process in reversed(processes):
            try:
                await stop(process)
            except Exception:
                failures.append('process_cleanup')
        if engine:
            await engine.dispose()
        for identity in reversed(containers):
            try:
                await external('docker', 'rm', '-f', '-v', identity, timeout=45)
            except Exception:
                failures.append('container_cleanup')
        config.unlink(missing_ok=True)
        artifact['cleanup'] = {'passed': not failures, 'failures': failures, 'owned_containers_removed': len(containers),
                               'owned_processes_stopped': len(processes), 'shared_services_touched': False}
        if failures:
            artifact['passed'] = False


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    if not parser.parse_args().live:
        parser.error('Explicit --live required; no resources created')
    directory = Path(tempfile.mkdtemp(prefix='operator-override-verification-', dir='/tmp/opencode'))
    artifact = {'version': 1, 'passed': False, 'stage': 'initializing', 'started_at': datetime.now(UTC).isoformat(),
                'checks': {}, 'cases': {}, 'limitations': ['Isolated Mininet/OVS campus, not production autonomy certification',
                'No AI training, model diagnostics, frontend or shared-service changes']}
    started = time.monotonic()
    try:
        await verify(directory, artifact)
    except Exception as error:
        artifact['failure'] = str(error) if isinstance(error, VerificationError) else type(error).__name__
    artifact.update(finished_at=datetime.now(UTC).isoformat(), elapsed_seconds=time.monotonic() - started)
    private_json(directory / 'result.json', artifact)
    print(json.dumps({'passed': artifact['passed'], 'stage': artifact['stage'], 'artifact': str(directory / 'result.json')}))
    return 0 if artifact['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
