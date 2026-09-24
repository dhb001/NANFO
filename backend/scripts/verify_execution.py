"""Opt-in real ADR-010 HTTP -> durable worker -> isolated lab verifier.

From backend: PYTHONPATH=..:. poetry run python scripts/verify_execution.py --live
Uses a disposable PostgreSQL database and dedicated Redis/Neo4j containers. Never
resets shared tables, users, streams, groups, graph data or existing lab containers.
Secrets travel only through private configuration/environment, never argv/output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import secrets
import signal
import socket
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx


class VerificationError(Exception):
    """Only fixed, credential-free messages cross the CLI error boundary."""


def check(condition, message):
    if not condition:
        raise VerificationError(message)


def private_json(path: Path, value: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def external(*args, env=None, stdin=None, timeout=120, cwd=None) -> str:
    process = await asyncio.create_subprocess_exec(*args, env=env, cwd=cwd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(process.communicate(stdin.encode() if stdin is not None else None), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    check(process.returncode == 0, "External operation failed; diagnostic output withheld")
    check(len(output) <= 8 * 1024 * 1024, "External result exceeded evidence bound")
    return output.decode()


def verify_no_flow_reinstall(before: dict, after: dict) -> None:
    """Counters may advance due to probes; resetting duration indicates reapply."""
    def flows(snapshot):
        result = {}
        for switch, state in snapshot["switches"].items():
            for line in state["flows"].splitlines():
                if "0x4e414e4600000001" not in line:
                    continue
                selector = line.split("priority=", 1)[1]
                result[switch, selector] = (float(re.search(r"duration=([0-9.]+)s", line)[1]),
                                            int(re.search(r"n_packets=(\d+)", line)[1]))
        return result

    old, new = flows(before), flows(after)
    check(bool(old) and old.keys() == new.keys(), "Recovery changed owned flow selectors")
    check(all(new[key][0] >= value[0] and new[key][1] >= value[1] for key, value in old.items()),
          "Recovery reset actual owned flow duration/counters")


async def until(action, predicate=bool, *, timeout=60, message="Readiness deadline exceeded"):
    deadline = time.monotonic() + timeout
    while True:
        result = await action()
        if predicate(result):
            return result
        if time.monotonic() >= deadline:
            raise VerificationError(message)
        await asyncio.sleep(.1)


async def stop(process, *, kill=False):
    if process is None or process.returncode is not None:
        return
    # SIGCONT first also releases a stopped worker during cleanup.
    process.send_signal(signal.SIGCONT)
    process.kill() if kill else process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 15)
    except TimeoutError:
        process.kill()
        await process.wait()


async def assert_lab_idle():
    # Include compose run/verify containers, not only the standard service name.
    active = await external("docker", "ps", "--filter", "ancestor=nanfo-emulation:campus-small-v1", "-q")
    compose = await external("docker", "ps", "--filter", "label=com.docker.compose.project=nanfo-emulation", "-q")
    check(not active.strip() and not compose.strip(), "Lab busy: another agent/operator owns an active lab; resume later")


def intent_payload(operation, *, dscp=None):
    paths = [["access1", "dist1", "core", "dist2", "access2"]] if operation == "reroute" else (
        [["access1", "dist1", "access2"], ["access1", "dist2", "access2"]] if operation == "multipath" else [])
    return {"action": "reroute_path" if operation in {"reroute", "multipath"} else "throttle_qos",
            "scope": {"source_host": "h1", "destination_host": "h3"}, "constraints": {
                "operation": operation, "paths": paths, "dscp": dscp,
                "rate_mbps": 5 if operation in {"shape", "police"} else None}}


# ADR-028 execution contract shared by the live verifiers and demo tooling:
#  * C3: a fresh Idempotency-Key per validate; execute/cancel reuse the intent's stored key;
#  * four-eyes: a user other than the requester approves (executes) a manual lab change,
#    echoing the validate/detail ``approval_binding`` (the exact approved lab identity);
#  * C18: high-impact actions first run a completed, passing simulation whose limits respect
#    the server policy floors and whose ``scenario_config.action_binding`` is the intent's
#    ``simulation_action_binding`` verbatim; its id is sent as ``simulation_id``.
POLICY_LIMITS = {"max_loss_pct": 1.0, "max_latency_ms": 1000.0, "min_throughput_mbps": 0.1}
TERMINAL_SIMULATION_STATES = frozenset({"completed", "cancelled", "failed"})


def policy_limits(settings=None) -> dict:
    """Scenario limits equal to the server policy floors (stricter is allowed, weaker is not)."""
    if settings is None:
        return dict(POLICY_LIMITS)
    return {"max_loss_pct": float(settings.SIMULATION_POLICY_MAX_LOSS_PCT),
            "max_latency_ms": float(settings.SIMULATION_POLICY_MAX_LATENCY_MS),
            # The scenario's own flow must still clear a positive throughput objective.
            "min_throughput_mbps": max(float(settings.SIMULATION_POLICY_MIN_THROUGHPUT_MBPS),
                                       POLICY_LIMITS["min_throughput_mbps"])}


def policy_scenario_config(action_binding: dict, *, limits: dict | None = None) -> dict:
    """Small under-capacity modeled scenario (0.5 of 1 Mbps: no loss, no queueing) bound to an intent."""
    return {
        "version": 1, "seed": 7, "tick_ms": 100, "duration_ticks": 10,
        "links": [{"link_id": "ab", "source": "a", "target": "b", "capacity_mbps": 1.0,
                   "buffer_bytes": 25000.0, "delay_ms": 0.0, "initial_queue_bytes": 0.0}],
        "flows": [{"flow_id": "f", "source": "a", "target": "b", "path": ["ab"], "demand_mbps": [0.5]}],
        "action_binding": dict(action_binding),
        "limits": dict(limits or POLICY_LIMITS),
    }


def validation_of(intent: dict) -> dict:
    """Validation state of a validate response (``validation``) or detail (``validation_result``)."""
    value = intent.get("validation") or intent.get("validation_result")
    return value if isinstance(value, dict) else {}


def requires_simulation(intent: dict) -> bool:
    """The server requires, and can bind, pre-execution simulation evidence for this intent."""
    return bool(validation_of(intent).get("simulation_required")) and bool(intent.get("simulation_action_binding"))


def execute_body(intent: dict, *, workspace_id: str, simulation_id: str | None = None, **extra) -> dict:
    """Approval request: stored idempotency key, echoed approval binding and bound evidence."""
    body = {"workspace_id": workspace_id, "intent_id": intent["intent_id"], "manual_approval": True}
    if intent.get("idempotency_key"):
        body["idempotency_key"] = intent["idempotency_key"]
    if intent.get("approval_binding"):
        body["approval_binding"] = dict(intent["approval_binding"])
    if simulation_id is not None:
        body["simulation_id"] = str(simulation_id)
    body.update(extra)
    return body


async def api_data(client, method: str, path: str, *, expected: int = 200, execution_mode: str | None = None,
                   **kwargs):
    """Canonical envelope: ``data`` for success statuses, ``errors`` for expected failures."""
    response = await client.request(method, path, **kwargs)
    check(response.status_code == expected, f"HTTP contract failed at {method} {path.split('?')[0]}")
    envelope = response.json()
    check(envelope.get("success") is (expected < 400), "Canonical envelope mismatch")
    if execution_mode is not None:
        check(envelope["meta"]["execution_mode"] == execution_mode, "Canonical execution mode missing")
    return envelope["data"] if expected < 400 else envelope["errors"]


async def run_bound_simulation(client, *, network_id: str, action_binding: dict, limits: dict | None = None,
                               timeout: float = 60, execution_mode: str | None = None) -> dict:
    """Start a policy-compliant modeled simulation bound to ``action_binding``; await a pass."""
    started = await api_data(client, "POST", "/api/v1/simulations/start", expected=202,
                             execution_mode=execution_mode, json={
                                 "network_id": network_id,
                                 "scenario_name": f"Pre-execution evidence {action_binding['intent_id']}",
                                 "scenario_config": policy_scenario_config(action_binding, limits=limits)})
    simulation_id = started["simulation_id"]
    done = await until(lambda: api_data(client, "GET", f"/api/v1/simulations/{simulation_id}",
                                        execution_mode=execution_mode),
                       lambda row: row["state"] in TERMINAL_SIMULATION_STATES, timeout=timeout,
                       message="Bound pre-execution simulation did not finish")
    check(done["state"] == "completed" and done["risk_gate"] == "passed",
          "Bound pre-execution simulation did not pass its limits")
    check((done.get("execution_policy") or {}).get("limits_respect_policy") is True,
          "Bound simulation limits are weaker than the server policy floors")
    return done


class ApprovalFlow:
    """Requester validates; a distinct approver runs bound evidence and executes (ADR-028)."""

    def __init__(self, *, requester, approver, workspace_id: str, network_id: str, limits: dict | None = None,
                 execution_mode: str | None = None, simulation_timeout: float = 60):
        self.requester, self.approver = requester, approver
        self.workspace_id, self.network_id = workspace_id, network_id
        self.limits, self.execution_mode, self.simulation_timeout = limits, execution_mode, simulation_timeout
        self.validated: dict[str, dict] = {}
        self._evidence: dict[str, asyncio.Future] = {}

    async def validate(self, intent: dict) -> dict:
        key = "verify-" + uuid.uuid4().hex  # C3: fresh per submission, <= 120 characters
        value = await api_data(self.requester, "POST", "/api/v1/intents/validate", execution_mode=self.execution_mode,
                               headers={"Idempotency-Key": key},
                               json={"workspace_id": self.workspace_id, "network_id": self.network_id, "intent": intent})
        check(value.get("idempotency_key") == key, "Validate did not store the submitted idempotency key")
        self.validated[value["intent_id"]] = value
        return value

    async def evidence(self, intent_id: str) -> str | None:
        """One bound simulation per intent, shared by concurrent identical approvals."""
        validated = self.validated[intent_id]
        if not requires_simulation(validated):
            return None
        future = self._evidence.get(intent_id)
        if future is None:
            future = self._evidence[intent_id] = asyncio.ensure_future(run_bound_simulation(
                self.approver, network_id=self.network_id, action_binding=validated["simulation_action_binding"],
                limits=self.limits, timeout=self.simulation_timeout, execution_mode=self.execution_mode))
        return (await asyncio.shield(future))["simulation_id"]

    def body(self, intent_id: str, *, simulation_id: str | None = None, **extra) -> dict:
        return execute_body(self.validated[intent_id], workspace_id=self.workspace_id,
                            simulation_id=simulation_id, **extra)

    async def execute(self, intent_id: str, *, actor=None, expected: int = 202, **extra):
        simulation_id = await self.evidence(intent_id)
        return await api_data(actor or self.approver, "POST", "/api/v1/intents/execute", expected=expected,
                              execution_mode=self.execution_mode,
                              json=self.body(intent_id, simulation_id=simulation_id, **extra))

    async def cancel(self, intent_id: str, *, actor=None, expected: int = 202):
        """Cancellation is a safety action: the stored key only, no approval or evidence."""
        validated = self.validated[intent_id]
        body = {"workspace_id": self.workspace_id, "intent_id": intent_id, "manual_approval": False, "cancel": True}
        if validated.get("idempotency_key"):
            body["idempotency_key"] = validated["idempotency_key"]
        return await api_data(actor or self.approver, "POST", "/api/v1/intents/execute", expected=expected,
                              execution_mode=self.execution_mode, json=body)


def verify_result(command: dict, result: dict, *, status="completed") -> dict:
    from app.modules.intent.lab import (
        LabCommand,
        LabResult,
        verified_completion,
        verified_no_mutation,
        verified_rollback,
    )

    cmd = LabCommand.model_validate_json(json.dumps(command))
    actual = LabResult.model_validate_json(json.dumps(result))
    check(actual.matches(cmd), "Lab result changed approved identity or command fence")
    check(actual.status == status, "Lab did not produce the expected terminal result")
    if status == "completed":
        check(verified_completion(actual.verification), "Completion lacks actual readback and probe evidence")
        probe = actual.verification["probe"]
        check(probe.get("source_host") == cmd.plan.source_host and probe.get("destination_host") == cmd.plan.destination_host,
              "Probe traffic selector differs from approved plan")
    else:
        check(verified_rollback(actual.rollback) or (actual.rollback is None and verified_no_mutation(actual.verification)),
              "Compensation or non-mutation lacks verified actual readback")
    return actual.model_dump(mode="json")


# Trusted verifier-only code, sent on stdin to docker exec, never through the
# mailbox and never derived from caller JSON. All mutations still use HTTP/worker.
_READBACK = r'''
import json, sys
from pathlib import Path
from emulation.actions import Actions
state = json.loads(Path('/results/.journal.json').read_text())
execution = sys.argv[1]
record = state['records'][execution]
absent = record['result']['status'] != 'completed' or record['command']['plan']['operation'] == 'restore'
if record['result']['verification'].get('no_mutation_verified'):
    active = state['records'].get(state['active'])
    actual = Actions(None).reconcile(active['prepared'] if active else None)
else:
    actual = (Actions(None).verify(record['prepared'], absent=absent) if 'prepared' in record
              else Actions(None).reconcile())
print(json.dumps({'phase': record['phase'], 'record_count': len(state['records']),
    'action_count': len(state['actions']), 'active': state['active'], 'blocked': state['blocked'],
    'dispatch_checked_at': record.get('dispatch_checked_at'),
    'command': record['command'], 'result': record['result'], 'actual': actual}))
'''

_TRAFFIC = r'''
import json, os, subprocess, sys, time
from pathlib import Path
def host(name):
    matches = []
    for path in Path('/proc').iterdir():
        if path.name.isdigit():
            try:
                argv = (path / 'cmdline').read_bytes().split(b'\0')
                if ('mininet:' + name).encode() in argv:
                    matches.append(int(path.name))
            except OSError:
                pass
    if len(matches) != 1:
        raise RuntimeError('Ambiguous Mininet host namespace')
    return ['nsenter', '-t', str(matches[0]), '-n', '--']
udp, dscp, parallel = bool(int(sys.argv[1])), int(sys.argv[2]), int(sys.argv[3])
server = subprocess.Popen(host('h3') + ['iperf3', '-s', '-1', '-J'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
client = None
try:
    time.sleep(.2)
    args = ['iperf3', '-c', '10.77.0.3', '-t', '4', '-J', '-P', str(parallel), '--tos', str(dscp << 2)]
    if udp:
        args += ['-u', '-b', '18M', '-l', '1200']
    client = subprocess.Popen(host('h1') + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, _ = client.communicate(timeout=15)
    received, _ = server.communicate(timeout=5)
    if client.returncode or server.returncode:
        raise RuntimeError('Real iperf workload failed')
    sent, received = json.loads(output), json.loads(received)
    if udp:
        intervals = [row['sum'] for row in received['intervals']]
        count = sum(row['bytes'] for row in intervals)
        seconds = sum(row['seconds'] for row in intervals)
        mbps = count * 8 / seconds / 1e6
    else:
        count = received['end']['sum_received']['bytes']
        mbps = received['end']['sum_received']['bits_per_second'] / 1e6
    print(json.dumps({'mbps': mbps, 'bytes': count, 'udp': udp, 'dscp': dscp, 'parallel': parallel}))
finally:
    for process in (client, server):
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
'''

_DEADLINE = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
execution = sys.argv[1]
limit = time.monotonic() + 8
pid = None
while time.monotonic() < limit:
    path = Path('/results/.journal.json')
    state = json.loads(path.read_text()) if path.exists() else {}
    record = state.get('records', {}).get(execution, {})
    if record.get('phase') == 'applying':
        flows = subprocess.check_output(['ovs-ofctl','-O','OpenFlow13','dump-flows','access1']).decode()
        if '0x4e414e4600000001' in flows:
            for process in Path('/proc').iterdir():
                if process.name.isdigit():
                    try:
                        args = (process / 'cmdline').read_bytes().split(b'\0')
                        if args and args[0].split(b'/')[-1].startswith(b'python') and b'emulation.runner' in args:
                            pid = int(process.name)
                    except OSError:
                        pass
            if pid:
                break
    time.sleep(.005)
if pid is None:
    raise RuntimeError('Actual partial mutation boundary not observed')
try:
    os.kill(pid, signal.SIGSTOP)
    time.sleep(12)
finally:
    os.kill(pid, signal.SIGCONT)
print(json.dumps({'actual_owned_flow_before_stop': True, 'deadline_elapsed': True}))
'''


async def verify(directory: Path, artifact: dict):
    from emulation.topology import manifest
    from sqlalchemy import create_engine, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.core.logging import configure_logging
    from app.core.schema_version import CURRENT_SCHEMA
    from app.core.security import hash_password
    from app.modules.identity.repository import UserRepository
    from app.modules.intent.lab import digest
    from scripts.bind_emulation import bind_emulation, save_binding

    settings = get_settings()
    configure_logging("CRITICAL")
    logging.disable(logging.CRITICAL)
    root = Path(__file__).resolve().parents[2]
    backend = root / "backend"
    suffix = uuid.uuid4().hex
    database = "execution_verify_" + suffix
    redis_name, neo_name, lab_name = ("nanfo-execution-" + kind + "-" + suffix for kind in ("redis", "neo", "lab"))
    redis_port, neo_port, api_port = port(), port(), port()
    env = os.environ.copy()
    # Explicit settings prevent an inherited .env or test process changing scope.
    env.update({key: str(value) for key, value in settings.model_dump(exclude_computed_fields=True).items()})
    env.update(APP_ENV="verification", LOG_LEVEL="CRITICAL", EXECUTION_MODE="emulation",
        EMULATION_CONTROL_ENABLED="true", POSTGRES_DB=database, REDIS_HOST="127.0.0.1",
        REDIS_PORT=str(redis_port), REDIS_DB="0", REDIS_PASSWORD=secrets.token_hex(32),
        NEO4J_URI=f"bolt://127.0.0.1:{neo_port}", NEO4J_USER="neo4j", NEO4J_PASSWORD=secrets.token_hex(24),
        JWT_SECRET_KEY=secrets.token_hex(48), TELEMETRY_RUNTIME_ADAPTER_MODE="stub",
        EMULATION_EXECUTION_LEASE_SECONDS="5", EMULATION_EXECUTION_POLL_SECONDS="0.1",
        EMULATION_EXECUTION_TIMEOUT_SECONDS="120", PYTHONPATH=f"{root}:{backend}")
    for name in ("commands", "results", "output", "binding"):
        (directory / name).mkdir(mode=0o755 if name != "binding" else 0o700)
    env.update(EMULATION_COMMANDS_PATH=str(directory / "commands"), EMULATION_RESULTS_PATH=str(directory / "results"),
        EMULATION_SNAPSHOT_PATH=str(directory / "output" / "snapshot.json"),
        EMULATION_BINDING_PATH=str(directory / "binding" / "binding.json"))
    admin = create_engine(settings.POSTGRES_SYNC_DSN, isolation_level="AUTOCOMMIT", echo=False)
    db_created = False
    containers = []
    api = worker = simulation_worker = None
    engine = redis = None
    try:
        artifact["stage"] = "preflight"
        await assert_lab_idle()
        from emulation.mailbox import COMMAND_FIELDS

        check("dispatch_expires_at" in COMMAND_FIELDS,
              "Lab receiver lacks dispatch_expires_at; coordinate receiver update and rebuild before live verification")
        await external("docker", "image", "inspect", "nanfo-emulation:campus-small-v1", "--format", "{{.Id}}")
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        db_created = True
        artifact["stage"] = "migrations"
        # The current API/worker code needs the current schema (ADR-028 reads 0014+ columns).
        await external(sys.executable, "-m", "alembic", "-c", str(backend / "alembic/alembic.ini"),
                       "upgrade", CURRENT_SCHEMA, env=env, cwd=backend)
        from app.core.config import Settings

        isolated = Settings(_env_file=None, **{key: env[key] for key in Settings.model_fields})
        engine = create_async_engine(isolated.POSTGRES_DSN, echo=False)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            check(await db.scalar(text("SELECT version_num FROM alembic_version")) == CURRENT_SCHEMA, "Migration version mismatch")
            user = await UserRepository(db).create("execution-verifier@example.com", hash_password(password := secrets.token_urlsafe(36)),
                                                   "Disposable execution verifier")
            await UserRepository(db).assign_role(user.user_id, "Admin")
            # ADR-028 four-eyes rule: a second, distinct operator approves manual lab changes.
            approver_user = await UserRepository(db).create(
                "execution-approver@example.com", hash_password(approver_password := secrets.token_urlsafe(36)),
                "Disposable execution approver")
            await UserRepository(db).assign_role(approver_user.user_id, "Operator")
            await db.commit()
        artifact["checks"]["migrations_0011_0012"] = True
        artifact["checks"]["schema"] = CURRENT_SCHEMA

        # Private config holds Redis authentication; neither password appears in
        # Docker argv. Dedicated instances isolate all hardcoded stream/group keys.
        redis_config = directory / "redis.conf"
        fd = os.open(redis_config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(f"bind 0.0.0.0\nprotected-mode yes\nsave \"\"\nappendonly no\nrequirepass {env['REDIS_PASSWORD']}\n")
        containers.append(redis_name)
        await external("docker", "run", "-d", "--name", redis_name, "--user", str(os.geteuid()),
            "-p", f"127.0.0.1:{redis_port}:6379", "--mount", f"type=bind,source={redis_config},target=/run/redis.conf,readonly",
            "redis:7-alpine", "redis-server", "/run/redis.conf")
        neo_env = {**env, "NEO4J_AUTH": "neo4j/" + env["NEO4J_PASSWORD"]}
        containers.append(neo_name)
        await external("docker", "run", "-d", "--name", neo_name, "-p", f"127.0.0.1:{neo_port}:7687",
            "-e", "NEO4J_AUTH", "-e", "NEO4J_server_memory_heap_initial__size=256m",
            "-e", "NEO4J_server_memory_heap_max__size=256m", "-e", "NEO4J_server_memory_pagecache_size=128m",
            "neo4j:5.25-community", env=neo_env)
        import redis.asyncio as aioredis
        from neo4j import AsyncGraphDatabase

        redis = aioredis.from_url(isolated.REDIS_URL, decode_responses=True)

        async def infrastructure_ready():
            try:
                await redis.ping()
                async with AsyncGraphDatabase.driver(isolated.NEO4J_URI, auth=(isolated.NEO4J_USER, isolated.NEO4J_PASSWORD)) as driver:
                    await driver.verify_connectivity()
                return True
            except Exception:  # noqa: BLE001 - readiness; no infrastructure exception text is emitted
                return False

        artifact["stage"] = "isolated_infrastructure"
        await until(infrastructure_ready, timeout=100, message="Dedicated Redis/Neo4j startup failed")
        api = await asyncio.create_subprocess_exec(sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(api_port), "--log-level", "critical", "--no-access-log",
            cwd=backend, env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)

        async def start_worker():
            return await asyncio.create_subprocess_exec(sys.executable, str(backend / "scripts/run_execution_worker.py"),
                cwd=backend, env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)

        async def start_simulation_worker():
            # Independent modeled-simulation worker: evaluates the C18 pre-execution evidence.
            return await asyncio.create_subprocess_exec(sys.executable, str(backend / "scripts/run_simulation_worker.py"),
                cwd=backend, env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{api_port}", timeout=30, trust_env=False) as client, \
                httpx.AsyncClient(base_url=f"http://127.0.0.1:{api_port}", timeout=30, trust_env=False) as approver:
            async def api_ready():
                check(api.returncode is None, "Isolated API process exited during startup")
                try:
                    return (await client.get("/api/openapi.json")).status_code == 200
                except httpx.TransportError:
                    return False

            await until(api_ready, timeout=60, message="Isolated HTTP API startup failed")
            binding = await bind_emulation(client, email="execution-verifier@example.com", password=password,
                manifest=manifest(), org_slug="execution-verifier", workspace_name="Execution verifier", network_name="campus-small-v1")
            save_binding(binding, Path(env["EMULATION_BINDING_PATH"]), Path(env["EMULATION_SNAPSHOT_PATH"]))
            login = await client.post("/api/v1/auth/login", json={"email": "execution-verifier@example.com", "password": password})
            check(login.status_code == 200, "Verifier login failed")
            client.headers["Authorization"] = "Bearer " + login.json()["data"]["access_token"]
            workspace = str(binding.workspace_id)
            orgs = await api_data(client, "GET", "/api/v1/organizations")
            org_id = next(org["org_id"] for org in orgs["items"] if org["slug"] == "execution-verifier")
            await api_data(client, "POST", f"/api/v1/organizations/{org_id}/members", expected=201,
                           json={"user_id": str(approver_user.user_id), "org_role": "Operator"})
            approver_login = await client.post("/api/v1/auth/login", json={
                "email": "execution-approver@example.com", "password": approver_password})
            check(approver_login.status_code == 200, "Approver login failed")
            approver.headers["Authorization"] = "Bearer " + approver_login.json()["data"]["access_token"]
            flow = ApprovalFlow(requester=client, approver=approver, workspace_id=workspace,
                                network_id=str(binding.network_id), limits=policy_limits(isolated),
                                execution_mode="emulation")
            lab_env = {"PATH": os.environ["PATH"], "EMULATION_CONTROL_ENABLED": "true",
                       "EMULATION_BINDING_DIGEST": digest(binding.model_dump(mode="json"))}
            artifact["stage"] = "lab_start"
            # Recheck after DB/API setup: a build/verification agent may have begun.
            await assert_lab_idle()
            containers.append(lab_name)
            await external("docker", "run", "-d", "--name", lab_name, "--privileged", "--network", "none",
                "--pids-limit", "256", "--memory", "768m", "--cpus", "2",
                "--tmpfs", "/run:exec,size=64m", "--tmpfs", "/tmp:exec,size=64m",
                "-e", "EMULATION_CONTROL_ENABLED", "-e", "EMULATION_BINDING_DIGEST",
                "--mount", f"type=bind,source={directory / 'output'},target=/output",
                "--mount", f"type=bind,source={directory / 'commands'},target=/commands,readonly",
                "--mount", f"type=bind,source={directory / 'results'},target=/results",
                "nanfo-emulation:campus-small-v1", env=lab_env)

            async def lab_ready():
                try:
                    response = await external("docker", "exec", lab_name, "python", "-m", "emulation.runner", "--request", "status", timeout=5)
                    return json.loads(response).get("passed") is True
                except VerificationError:
                    return False

            await until(lab_ready, timeout=100, message="Owned lab startup failed")
            worker = await start_worker()
            simulation_worker = await start_simulation_worker()

            async def request(path, body=None, *, expected=200):
                response = await client.get(path, params={"workspace_id": workspace}) if body is None else await client.post(path, json=body)
                check(response.status_code == expected, f"HTTP contract failed at {path.split('?')[0]}")
                envelope = response.json()
                check(envelope["success"] is True and envelope["meta"]["execution_mode"] == "emulation", "Canonical emulation envelope missing")
                return envelope["data"]

            async def validate(operation, dscp=None):
                await asyncio.sleep(3.2)  # Lab hold-down, not a bypass of the driver policy.
                value = await flow.validate(intent_payload(operation, dscp=dscp))
                check(value["status"] == "validated", "Fresh bound manual plan rejected")
                check(value.get("approval_binding") is not None, "Validated lab plan lacks its approval binding")
                return value["intent_id"]

            async def execute(intent_id, **extra):
                # Distinct approver, stored key, approval binding and (high-impact) bound evidence.
                return await flow.execute(intent_id, **extra)

            async def cancel(intent_id):
                return await flow.cancel(intent_id)

            async def detail(intent_id):
                return await request(f"/api/v1/intents/{intent_id}")

            async def terminal(intent_id, *, expected="completed", timeout=150):
                expected_phases = {expected} if isinstance(expected, str) else set(expected)
                value = await until(lambda: detail(intent_id), lambda row: row["execution_provenance"].get("phase") in expected_phases,
                    timeout=timeout, message="Durable lifecycle did not reach expected verified terminal phase")
                provenance = value["execution_provenance"]
                execution_id = provenance["execution_id"]
                expected = provenance["phase"]
                cmd = json.loads((directory / "commands" / f"{execution_id}.json").read_bytes())
                check(cmd.get("dispatch_expires_at") == provenance.get("dispatch_expires_at"),
                      "Wire dispatch authorization differs from persisted provenance")
                # Read-only operator inspection also verifies current switch state independently.
                evidence = json.loads(await external("docker", "exec", "-i", lab_name, "python", "-", execution_id, stdin=_READBACK))
                verify_result(cmd, evidence["result"], status=expected)
                if expected == "completed":
                    checked_at = evidence.get("dispatch_checked_at")
                    expiry = datetime.fromisoformat(cmd["dispatch_expires_at"].replace("Z", "+00:00")).timestamp()
                    check(isinstance(checked_at, (int, float)) and 0 < expiry - checked_at <= 5,
                          "Lab journal lacks bounded initial dispatch authorization evidence")
                check(not evidence["blocked"], "Lab journal blocks successors")
                check(value["confidence"]["score"] == 0, "Unjustified learned confidence")
                artifact["actions"].append({"intent_id": intent_id, "execution_id": execution_id,
                    "operation": cmd["plan"]["operation"], "plan_hash": cmd["plan_hash"], "command_fence": cmd["fence"],
                    "dispatch_expires_at": cmd["dispatch_expires_at"],
                    "dispatch_checked_at": evidence.get("dispatch_checked_at"),
                    "phase": expected, "result": evidence["result"]})
                return value, evidence

            async def action(operation, dscp=None):
                intent_id = await validate(operation, dscp)
                accepted = await execute(intent_id)
                check(accepted["status"] == "execution_started", "Acceptance must return durable execution_started")
                return intent_id, await terminal(intent_id)

            async def traffic(udp=False, dscp=0, parallel=1):
                return json.loads(await external("docker", "exec", "-i", lab_name, "python", "-",
                    str(int(udp)), str(dscp), str(parallel), stdin=_TRAFFIC, timeout=30))

            artifact["stage"] = "manual_reroute_and_duplicate"
            baseline = await traffic()
            check(baseline["mbps"] > 10, "Baseline workload below lab capacity")
            artifact["checks"]["baseline_tcp"] = baseline
            # Real rejected restore has no owned policy. It must reconcile actual
            # absence and release backend exclusion rather than remain uncertain.
            no_policy = await validate("restore")
            await execute(no_policy)
            await terminal(no_policy, expected="failed")
            artifact["checks"]["verified_no_mutation_releases_lab"] = True
            first = await validate("reroute")
            denied = await client.post("/api/v1/intents/execute", json={"workspace_id": workspace, "intent_id": first})
            check(denied.status_code == 409, "Missing manual approval was not rejected")
            # ADR-028: the requester cannot approve its own change; reroute needs bound evidence;
            # the approver must echo the current approval binding. None of these create a job.
            own = await flow.execute(first, actor=client, expected=409)
            check(own["code"] == "DISTINCT_APPROVER_REQUIRED", "Requester approved its own manual lab change")
            unsimulated = await api_data(approver, "POST", "/api/v1/intents/execute", expected=409, json=flow.body(first))
            check(unsimulated["code"] == "SIMULATION_REQUIRED", "High-impact change accepted without simulation")
            unbound = flow.body(first, simulation_id=await flow.evidence(first))
            unbound.pop("approval_binding", None)
            mismatch = await api_data(approver, "POST", "/api/v1/intents/execute", expected=409, json=unbound)
            check(mismatch["code"] == "APPROVAL_BINDING_MISMATCH", "Approval without the approved lab identity accepted")
            artifact["checks"]["four_eyes_simulation_and_binding_gates"] = {
                "distinct_approver_required": True, "simulation_required": True, "approval_binding_required": True}
            accepted = await asyncio.gather(*(execute(first) for _ in range(4)))
            ids = {row["execution_provenance"]["execution_id"] for row in accepted}
            check(len(ids) == 1, "Concurrent duplicate requests created multiple jobs")
            await terminal(first)
            artifact["checks"]["concurrent_duplicate"] = {"requests": 4, "executions": len(ids)}
            artifact["checks"]["reroute_tcp"] = await traffic()
            first_id = next(iter(ids))
            readback = json.loads(await external("docker", "exec", "-i", lab_name, "python", "-", first_id, stdin=_READBACK))
            for switch in ("access1", "dist1", "core", "dist2", "access2"):
                flows = readback["actual"]["switches"][switch]["flows"]
                owned = [line for line in flows.splitlines() if "0x4e414e4600000001" in line]
                check(len(owned) == 2 and all(int(re.search(r"n_packets=(\d+)", line)[1]) > 0 for line in owned),
                      "Reroute forward/return traffic did not exercise every approved switch")
            await cancel(first)
            await terminal(first, expected="cancelled")
            artifact["checks"]["late_cancel_compensation"] = True

            artifact["stage"] = "multipath_qos_restore"
            await action("multipath")
            artifact["checks"]["multipath_tcp"] = await traffic(parallel=12)
            for switch in ("access1", "access2"):
                stats = await external("docker", "exec", lab_name, "ovs-ofctl", "-O", "OpenFlow13", "dump-group-stats", switch)
                counts = re.findall(r"bucket\d+:packet_count=(\d+)", stats)
                check(len(counts) == 2 and all(int(value) > 0 for value in counts), "Both SELECT buckets were not exercised")
            await action("restore")
            for operation, dscp in (("shape", 10), ("police", 12)):
                await action(operation, dscp)
                classified, unclassified = await traffic(True, dscp), await traffic(True)
                check(3 <= classified["mbps"] <= 6.5 and unclassified["mbps"] >= 12, "QoS classifier/rate traffic effect invalid")
                artifact["checks"][operation] = {"classified": classified, "unclassified": unclassified}
                await action("restore", dscp)
                restored = await traffic(True, dscp)
                check(restored["mbps"] >= 12, "Owned policy restore failed to restore actual traffic")
                artifact["checks"][operation]["restored"] = restored

            artifact["stage"] = "worker_process_death_and_lost_result"
            restart_intent = await validate("reroute")
            restarted_job = await execute(restart_intent)
            execution_id = restarted_job["execution_provenance"]["execution_id"]
            path = directory / "commands" / f"{execution_id}.json"

            async def published():
                return path.exists()

            await until(published, timeout=20)
            # Actual process death after command publication, before lab acknowledgment.
            await stop(worker, kill=True)
            worker = None
            original = json.loads(path.read_bytes())

            async def result_exists():
                return (directory / "results" / path.name).exists()

            await until(result_exists, timeout=60)
            before = json.loads(await external("docker", "exec", "-i", lab_name, "python", "-", execution_id, stdin=_READBACK))
            await external("docker", "exec", lab_name, "python", "-c",
                "import sys; from pathlib import Path; Path('/results',sys.argv[1]+'.json').unlink()", execution_id)
            await until(result_exists, timeout=30, message="Lab journal did not recover missing result file")
            worker = await start_worker()
            _, after = await terminal(restart_intent)
            check(json.loads(path.read_bytes()) == original and before["command"] == after["command"], "Restart changed command identity")
            check(before["record_count"] == after["record_count"] and before["action_count"] == after["action_count"],
                  "Recovery created an extra lab mutation")
            verify_no_flow_reinstall(before["actual"], after["actual"])
            artifact["checks"]["worker_kill_lost_result"] = {"same_command": True, "same_journal_action_count": True}
            await action("restore")

            artifact["stage"] = "cancel_restored_preserves_successor"
            policy_a, _ = await action("reroute")
            restore_b, _ = await action("restore")
            policy_c, (c_detail, c_before) = await action("reroute")
            c_execution = c_detail["execution_provenance"]["execution_id"]
            await cancel(policy_a)
            _, cancelled_a = await terminal(policy_a, expected="cancelled")
            check(cancelled_a["result"]["verification"].get("already_restored") is True,
                  "Cancelling restored policy did not acknowledge actual no-mutation proof")
            check(cancelled_a["result"]["rollback"] is None and cancelled_a["active"] == c_execution,
                  "Cancelling restored policy changed the active successor")
            c_after = json.loads(await external("docker", "exec", "-i", lab_name, "python", "-", c_execution, stdin=_READBACK))
            verify_no_flow_reinstall(c_before["actual"], c_after["actual"])
            successor_traffic = await traffic()
            check(successor_traffic["mbps"] > 10, "Stale cancellation damaged successor traffic")
            restore_c, _ = await action("restore")
            artifact["checks"]["cancel_restored_preserves_successor"] = {
                "policy_a": policy_a, "restore_b": restore_b, "policy_c": policy_c, "restore_c": restore_c,
                "no_mutation_verified": True, "successor_unchanged": True, "successor_tcp": successor_traffic,
            }

            artifact["stage"] = "terminal_outbox_replay"
            async def outbox_delivered():
                async with sessions() as db:
                    return await db.scalar(text("SELECT count(*) FROM intent_outbox WHERE published_at IS NULL")) == 0

            await until(outbox_delivered, timeout=30)
            await stop(worker)
            worker = None
            async with sessions() as db:
                rows = (await db.execute(text("SELECT event_id, envelope FROM intent_outbox WHERE envelope->>'event_type'='intent.execution_completed'"))).all()
                check(bool(rows), "No terminal outbox envelope found")
                event_id, envelope = rows[0]
                await db.execute(text("UPDATE intent_outbox SET published_at=NULL, lease_owner=NULL, lease_until=NULL WHERE event_id=:id"), {"id": event_id})
                await db.commit()
            worker = await start_worker()
            await until(outbox_delivered, timeout=30)
            copies = [fields for _, fields in await redis.xrange("stream:intent") if fields["event_id"] == str(event_id)]
            check(len(copies) >= 2 and all(value == envelope for value in copies), "Outbox replay changed event identity/time/payload")

            async def audit_delivered():
                async with sessions() as db:
                    return await db.scalar(text("SELECT count(*) FROM audit_logs WHERE event_id=:id"), {"id": event_id})

            await until(audit_delivered, timeout=30)
            async def intent_delivery_finished():
                pending = await redis.xpending("stream:intent", "nanfo-consumers")
                groups = await redis.xinfo_groups("stream:intent")
                return pending["pending"] == 0 and all(group.get("lag") == 0 for group in groups)

            await until(intent_delivery_finished, timeout=30)
            check(await audit_delivered() == 1, "Terminal event replay duplicated durable audit")
            artifact["checks"]["terminal_outbox_replay"] = {"event_id": str(event_id), "copies": len(copies), "audit_rows": 1}

            # A real stopped API-configured worker plus blocked lab subprocess
            # exercises deadline compensation without editing approved commands.
            # Use a separate owned API process configured with the minimum deadline.
            artifact["stage"] = "deadline_compensation"
            await stop(worker)
            worker = None
            await stop(api)
            api = None
            env["EMULATION_EXECUTION_TIMEOUT_SECONDS"] = "10"
            api = await asyncio.create_subprocess_exec(sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                "--port", str(api_port), "--log-level", "critical", "--no-access-log", cwd=backend, env=env,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await until(api_ready, timeout=60)
            timeout_intent = await validate("reroute")
            accepted = await execute(timeout_intent)
            timeout_id = accepted["execution_provenance"]["execution_id"]
            fault = asyncio.create_task(external("docker", "exec", "-i", lab_name, "python", "-", timeout_id,
                                                  stdin=_DEADLINE, timeout=35))
            worker = await start_worker()
            artifact["checks"]["deadline_fault_boundary"] = json.loads(await fault)
            value, _ = await terminal(timeout_intent, expected={"cancelled", "failed"}, timeout=60)
            check(value["execution_provenance"]["rollback"]["verified"] is True, "Deadline did not verify compensation")
            artifact["checks"]["deadline_compensation"] = True
            await client.post("/api/v1/auth/logout")
            await approver.post("/api/v1/auth/logout")
        artifact["passed"] = True
        artifact["stage"] = "complete"
    finally:
        cleanup_errors = []
        for process in (worker, simulation_worker, api):
            try:
                await stop(process)
            except Exception:  # noqa: BLE001
                cleanup_errors.append("process_cleanup")
        if redis is not None:
            try:
                await redis.aclose()
            except Exception:  # noqa: BLE001 - still remove all other owned resources
                cleanup_errors.append("redis_client_cleanup")
        if engine is not None:
            try:
                await engine.dispose()
            except Exception:  # noqa: BLE001
                cleanup_errors.append("database_client_cleanup")
        for name in reversed(containers):
            try:
                await external("docker", "rm", "-f", "-v", name, timeout=45)
            except Exception:  # noqa: BLE001
                cleanup_errors.append("container_cleanup")
        if db_created:
            try:
                with admin.connect() as connection:
                    connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
            except Exception:  # noqa: BLE001
                cleanup_errors.append("database_cleanup")
        admin.dispose()
        # Secret-bearing Redis config is always removed. Raw mailbox/journal
        # evidence contains only this disposable lab's identities and readbacks.
        (directory / "redis.conf").unlink(missing_ok=True)
        artifact["cleanup"] = {"passed": not cleanup_errors, "failures": cleanup_errors}
        if cleanup_errors:
            artifact["passed"] = False


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Create disposable resources and actuate an isolated lab")
    args = parser.parse_args()
    if not args.live:
        parser.error("Explicit --live required; no resources created")
    directory = Path(tempfile.mkdtemp(prefix="execution-verification-", dir="/tmp/opencode"))
    artifact = {"version": 1, "passed": False, "stage": "initializing", "started_at": datetime.now(UTC).isoformat(),
                "checks": {}, "actions": [], "limitations": [
                    "Real bounded campus only; no production/simulation certification",
                    "Outbox replay resets only an owned publication acknowledgement to reproduce the XADD/ack crash window",
                    "Old-run interrupted-journal polling is covered by the separate lab-local gate, not this API verifier",
                ]}
    try:
        await verify(directory, artifact)
    except Exception as error:  # noqa: BLE001 - never serialize infrastructure exceptions/URLs/tokens
        artifact["failure"] = str(error) if isinstance(error, VerificationError) else type(error).__name__
    finally:
        artifact["finished_at"] = datetime.now(UTC).isoformat()
        private_json(directory / "result.json", artifact)
    print(json.dumps({"passed": artifact["passed"], "stage": artifact["stage"], "artifact": str(directory / "result.json")}))
    return 0 if artifact["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
