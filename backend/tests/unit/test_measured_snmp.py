"""Offline protocol fixtures and owner-contract doubles; no physical acceptance."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from app.modules.telemetry.service import TelemetryIngestionService
from app.modules.telemetry.snmp import MeasuredSNMPAdapter, Observation, counter_rates
from app.modules.telemetry.snmp_config import SNMPBinding, SNMPCredentials, SNMPError, load_protected_json
from app.modules.telemetry.snmp_ownership import validate_owner_scope
from app.modules.telemetry.snmp_transport import MAX_OUTPUT_BYTES, NetSNMPTransport, parse_response, requested_oids

FIXTURES = Path(__file__).parents[1] / "fixtures" / "snmp"
FIRST = (FIXTURES / "if_mib_first.txt").read_bytes()
SECOND = (FIXTURES / "if_mib_second.txt").read_bytes()


@pytest.fixture
def binding():
    return SNMPBinding.model_validate_json(json.dumps({
        "version": 1, "org_id": "00000000-0000-4000-8000-000000000001",
        "workspace_id": "00000000-0000-4000-8000-000000000002",
        "network_id": "00000000-0000-4000-8000-000000000003",
        "device_id": "00000000-0000-4000-8000-000000000004",
        "actor_user_id": "00000000-0000-4000-8000-000000000005",
        "target": "192.0.2.10", "sys_name": "fixture-switch",
        "interfaces": [{"if_index": 2, "if_name": "eth2"}],
        "execution_mode": "production", "environment": "physical",
    }))


def credentials():
    return {"username": "fixture-user", "auth_passphrase": "fixture-auth-only",
            "priv_passphrase": "fixture-priv-only"}


def protected(path, data):
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return path


def parsed(binding, data=FIRST):
    return parse_response(data, binding, binding.interfaces[0])


def observation(binding, data=FIRST, clock=0):
    return Observation(parsed(binding, data), datetime(2026, 9, 19, tzinfo=UTC), clock, 0.01)


def make_adapter(binding):
    transport = SimpleNamespace(get=AsyncMock(side_effect=[parsed(binding), parsed(binding, SECOND)]))
    authorize = AsyncMock()
    clock = SimpleNamespace(value=0.0)
    adapter = MeasuredSNMPAdapter(binding=binding, transport=transport, authorize=authorize,
                                  monotonic=lambda: clock.value,
                                  utcnow=lambda: datetime.fromtimestamp(1790000000 + clock.value, UTC))
    return adapter, transport, authorize, clock


def test_fixture_rates_and_units(binding):
    first, second = observation(binding), observation(binding, SECOND, 10)
    quality, interval, rates = counter_rates(second, first, 120)
    assert (quality, interval, rates) == ("measured", 10, (500_000_000, 200_000_000))
    assert parsed(binding).speed_bps == 1_000_000_000


@pytest.mark.parametrize("old,new", [
    (b"Counter64: 1000000000", b"Counter64: -1"),
    (b"Counter64: 1000000000", b"Counter64: 18446744073709551616"),
    (b"Counter64: 1000000000", b"Counter64: NaN"),
    (b"Counter64: 1000000000", b"Counter32: 1000000000"),
    (b'"fixture-switch"', b'"wrong-switch"'),
    (b'"eth2"', b'"eth3"'),
    (b"INTEGER: 2", b"INTEGER: 3"),
    (b"Timeticks: (100000) 0:16:40.00", b"No Such Instance currently exists at this OID"),
    (b"Gauge32: 1000", b"Gauge32: true"),
])
def test_bad_protocol_values_rejected(binding, old, new):
    with pytest.raises(SNMPError, match="invalid_or_incomplete"):
        parsed(binding, FIRST.replace(old, new))


@pytest.mark.parametrize("data", [FIRST + FIRST, FIRST.split(b"\n", 1)[1], b"x" * (MAX_OUTPUT_BYTES + 1), b"\xff"])
def test_partial_duplicate_or_oversize_protocol_rejected(binding, data):
    with pytest.raises(SNMPError):
        parsed(binding, data)


def test_if_high_speed_units_and_zero_speed(binding):
    data = FIRST.replace(b"Gauge32: 1000000000", b"Gauge32: 4294967295").replace(b"Gauge32: 1000\n", b"Gauge32: 10000\n")
    assert parsed(binding, data).speed_bps == 10_000_000_000
    assert parsed(binding, FIRST.replace(b"Gauge32: 1000000000", b"Gauge32: 0")).speed_bps == 0


@pytest.mark.parametrize("changes,clock,reason", [
    ({"engine_boots": 8}, 10, "agent_restart"),
    ({"discontinuity": 100500}, 10, "counter_discontinuity"),
    ({"speed_bps": 0}, 10, "speed_unavailable"),
    ({"speed_bps": 100_000_000}, 10, "speed_changed"),
    ({"rx": 1}, 10, "counter_reset_or_capacity_exceeded"),
    ({"rx": 20_000_000_000}, 10, "counter_reset_or_capacity_exceeded"),
    ({"uptime": 500}, 10, "interval_unavailable"),
    ({}, 130, "interval_unavailable"),
    ({}, 0, "interval_unavailable"),
    ({"uptime": 102000}, 10, "agent_clock_discontinuity"),
])
def test_rate_unavailable_conditions(binding, changes, clock, reason):
    first, second = observation(binding), observation(binding, SECOND, clock)
    second = replace(second, counters=replace(second.counters, **changes))
    quality, _, rates = counter_rates(second, first, 120)
    assert (quality, rates) == (reason, None)


def test_counter64_and_uptime_single_wrap(binding):
    first, second = observation(binding), observation(binding, SECOND, 10)
    first = replace(first, counters=replace(first.counters, uptime=2**32 - 500, rx=2**64 - 100))
    second = replace(second, counters=replace(second.counters, uptime=500, rx=100))
    quality, interval, rates = counter_rates(second, first, 120)
    assert (quality, interval, rates[0]) == ("measured_wrap", 10, 160)


async def test_batch_baseline_ack_retry_and_provenance(binding):
    adapter, transport, authorize, clock = make_adapter(binding)
    first = await adapter.poll()
    assert len(first) == 3 and all(s["tags"]["rate_quality"] == "baseline" for s in first)
    replay = await adapter.poll()
    assert replay == first and replay is not first
    assert transport.get.await_count == 1
    replay[0]["value"] = -1
    with pytest.raises(SNMPError, match="acknowledgement"):
        await adapter.acknowledge_batch(replay)
    await adapter.acknowledge_batch(first)
    clock.value = 10
    second = await adapter.poll()
    values = {s["metric"]: (s["value"], s["unit"]) for s in second}
    assert values["port_rx_bps"] == (500_000_000, "bps")
    assert values["port_tx_bps"] == (200_000_000, "bps")
    assert values["throughput_mbps"] == (500, "Mbps")
    assert values["link_utilization_percent"] == (50, "%")
    assert all(s["tags"]["synthetic"] is False and s["source"] == "measured_snmp" for s in second)
    assert all(s["tags"]["port_no"] == "2" for s in second)
    assert authorize.await_count == 7


async def test_scope_denial_prevents_transport_and_publication(binding):
    adapter, transport, authorize, _ = make_adapter(binding)
    authorize.side_effect = SNMPError("collector_permission_denied")
    ingestion = SimpleNamespace(ingest=AsyncMock())
    with pytest.raises(SNMPError):
        await adapter.collect_and_publish(ingestion)
    transport.get.assert_not_awaited()
    ingestion.ingest.assert_not_awaited()


async def test_mid_poll_revocation_does_not_stage_batch(binding):
    adapter, _, authorize, _ = make_adapter(binding)
    authorize.side_effect = [None, None, SNMPError("revoked")]
    with pytest.raises(SNMPError, match="revoked"):
        await adapter.poll()
    assert adapter._pending is None


async def test_stale_pending_rejected_without_new_measurement(binding):
    adapter, transport, _, clock = make_adapter(binding)
    await adapter.poll()
    clock.value = 31
    with pytest.raises(SNMPError, match="expired"):
        await adapter.poll()
    assert transport.get.await_count == 1


async def test_partial_publication_replays_same_event_ids(binding):
    adapter, transport, _, _ = make_adapter(binding)
    ingestion = SimpleNamespace(ingest=AsyncMock(side_effect=["ok", RuntimeError("offline")]))
    with pytest.raises(RuntimeError):
        await adapter.collect_and_publish(ingestion)
    first_id = ingestion.ingest.call_args_list[0].kwargs["event_id"]
    ingestion.ingest.side_effect = None
    assert await adapter.collect_and_publish(ingestion) == 3
    assert ingestion.ingest.call_args_list[2].kwargs["event_id"] == first_id
    assert transport.get.await_count == 1
    assert adapter._pending is None


async def test_publication_rechecks_revocation_between_samples(binding):
    adapter, _, authorize, _ = make_adapter(binding)
    # write precheck, read precheck, per-GET check, postcheck, first write, revocation.
    authorize.side_effect = [None, None, None, None, None, SNMPError("revoked")]
    ingestion = SimpleNamespace(ingest=AsyncMock(return_value="ok"))
    with pytest.raises(SNMPError, match="revoked"):
        await adapter.collect_and_publish(ingestion)
    assert ingestion.ingest.await_count == 1
    assert adapter._pending is not None


async def test_multi_interface_failure_publishes_nothing(binding):
    data = binding.model_dump(mode="json")
    data["interfaces"].append({"if_index": 3, "if_name": "eth3"})
    binding = SNMPBinding.model_validate_json(json.dumps(data))
    adapter, transport, _, _ = make_adapter(binding)
    transport.get.side_effect = [parsed(binding), SNMPError("snmp_timeout")]
    ingestion = SimpleNamespace(ingest=AsyncMock())
    with pytest.raises(SNMPError, match="snmp_timeout"):
        await adapter.collect_and_publish(ingestion)
    ingestion.ingest.assert_not_awaited()
    assert adapter._pending is None


async def test_revocation_during_first_get_prevents_second_interface_read(binding):
    data = binding.model_dump(mode="json")
    data["interfaces"].append({"if_index": 3, "if_name": "eth3"})
    binding = SNMPBinding.model_validate_json(json.dumps(data))
    adapter, transport, authorize, _ = make_adapter(binding)
    revoked = False

    async def check_authority(*args):
        if revoked:
            raise SNMPError("collector_permission_denied")

    async def first_get(*args):
        nonlocal revoked
        revoked = True
        return parsed(binding)

    authorize.side_effect = check_authority
    transport.get.side_effect = first_get
    ingestion = SimpleNamespace(ingest=AsyncMock())
    with pytest.raises(SNMPError, match="permission_denied"):
        await adapter.collect_and_publish(ingestion)
    transport.get.assert_awaited_once_with(binding, binding.interfaces[0])
    ingestion.ingest.assert_not_awaited()
    assert adapter._pending is None
    assert adapter._previous == {}


async def test_real_ingestion_contract_with_fake_redis(binding):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        adapter, _, _, _ = make_adapter(binding)
        assert await adapter.collect_and_publish(TelemetryIngestionService(redis)) == 3
        events = await redis.xrange("stream:telemetry")
        assert len(events) == 3
        assert all(fields["event_type"] == "telemetry.metric.ingested" for _, fields in events)
        assert all(json.loads(fields["payload"])["source"] == "measured_snmp" for _, fields in events)
    finally:
        await redis.aclose()


def owner_doubles(binding):
    identity = SimpleNamespace(get_profile=AsyncMock(return_value=SimpleNamespace(
        permissions=["read:telemetry", "read:topology", "write:config"])))
    network = SimpleNamespace(assert_network_workspace_access=AsyncMock(), assert_device_workspace_access=AsyncMock(
        return_value=(binding.network_id, binding.workspace_id)))
    device = SimpleNamespace(device_id=binding.device_id, network_id=binding.network_id, status="active", ip_address=str(binding.target))
    devices = SimpleNamespace(list_devices=AsyncMock(return_value=SimpleNamespace(items=[device], total=1)))
    return identity, network, devices, device


async def test_owner_contract_enforces_org_membership_write_and_address(binding):
    identity, network, devices, _ = owner_doubles(binding)
    await validate_owner_scope(binding, publish=True, identity=identity, network=network, devices=devices)
    assert network.assert_network_workspace_access.call_args.kwargs == {
        "network_id": binding.network_id, "requested_workspace_id": binding.workspace_id,
        "actor_user_id": str(binding.actor_user_id), "claim_org_id": binding.org_id, "require_write": True,
    }


@pytest.mark.parametrize("case", ["permissions", "cross_network", "wrong_address", "inactive", "membership", "missing"])
async def test_owner_rejects_invalid_bindings(binding, case):
    identity, network, devices, device = owner_doubles(binding)
    if case == "permissions":
        identity.get_profile.return_value.permissions = ["read:telemetry", "read:topology"]
    elif case == "cross_network":
        network.assert_device_workspace_access.return_value = (binding.org_id, binding.workspace_id)
    elif case == "wrong_address":
        device.ip_address = "192.0.2.11"
    elif case == "inactive":
        device.status = "inactive"
    elif case == "membership":
        network.assert_network_workspace_access.side_effect = SNMPError("denied")
    else:
        devices.list_devices.return_value.items = []
    with pytest.raises(SNMPError):
        await validate_owner_scope(binding, publish=True, identity=identity, network=network, devices=devices)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o666, 0o400])
def test_secret_file_exact_permissions(tmp_path, mode):
    path = protected(tmp_path / "secret.json", credentials())
    path.chmod(mode)
    with pytest.raises(SNMPError):
        load_protected_json(path, SNMPCredentials)


def test_secret_symlink_injection_and_redaction(tmp_path):
    path = protected(tmp_path / "secret.json", credentials())
    secret = load_protected_json(path, SNMPCredentials)
    assert "fixture-auth-only" not in repr(secret)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(SNMPError):
        load_protected_json(link, SNMPCredentials)
    protected(path, {**credentials(), "auth_passphrase": "secret\ninclude /tmp/file"})
    with pytest.raises(SNMPError) as raised:
        load_protected_json(path, SNMPCredentials)
    assert "secret" not in str(raised.value)
    assert raised.value.__suppress_context__


def test_duplicate_json_keys_rejected(tmp_path):
    path = protected(tmp_path / "secret.json", credentials())
    path.write_text(json.dumps(credentials())[:-1] + ', "username": "another"}')
    with pytest.raises(SNMPError):
        load_protected_json(path, SNMPCredentials)


async def test_binding_change_revokes_owner_boundary_before_services(binding, tmp_path):
    from app.modules.telemetry.snmp_ownership import SNMPOwnerBoundary

    data = binding.model_dump(mode="json")
    data["port"] = 1161
    path = protected(tmp_path / "binding.json", data)
    boundary = SNMPOwnerBoundary(binding_path=path, session_factory=None, redis=None)
    with pytest.raises(SNMPError, match="binding_changed"):
        await boundary.authorize(binding, False)


@pytest.mark.parametrize("field,value", [
    ("target", "udp:192.0.2.1;id"), ("target", "example.com"),
    ("target", "224.0.0.1"), ("port", True), ("timeout_seconds", float("inf")),
    ("interfaces", [{"if_index": 0, "if_name": "eth2"}]),
    ("interfaces", [{"if_index": 2, "if_name": "eth2"}] * 2),
])
def test_invalid_operator_config(binding, tmp_path, field, value):
    data = binding.model_dump(mode="json")
    data[field] = value
    path = protected(tmp_path / "binding.json", data)
    with pytest.raises(SNMPError):
        load_protected_json(path, SNMPBinding)


async def test_transport_argv_environment_permissions_and_cleanup(binding, tmp_path, monkeypatch):
    path = protected(tmp_path / "secret.json", credentials())
    transport = NetSNMPTransport(credentials_path=path)
    monkeypatch.setattr(transport, "check_available", lambda: None)
    captured = {}

    async def execute(args, env, cwd, timeout):
        captured["directory"] = Path(cwd)
        config = Path(cwd) / "snmp.conf"
        assert stat.S_IMODE(config.stat().st_mode) == 0o600
        assert stat.S_IMODE(Path(cwd).stat().st_mode) == 0o700
        indexes = Path(env["SNMP_PERSISTENT_DIR"]) / "cert_indexes"
        assert indexes.parent == Path(cwd)
        assert indexes.is_dir() and not indexes.is_symlink()
        assert stat.S_IMODE(indexes.stat().st_mode) == 0o700
        assert not list(indexes.iterdir())
        assert "defAuthPassphrase fixture-auth-only" in config.read_text()
        for value in credentials().values():
            assert value not in str(args) and value not in str(env)
        assert "-A" not in args and "-X" not in args and "-u" not in args
        assert args[-10:] == list(requested_oids(binding.interfaces[0]))
        assert args[args.index("-r") + 1] == "0"
        assert "PATH" not in env and "SNMP_PERSISTENT_DIR" in env
        assert timeout == 3
        return FIRST

    monkeypatch.setattr(transport, "_execute", execute)
    result = await transport.get(binding, binding.interfaces[0])
    assert result.rx == 1_000_000_000
    assert not captured["directory"].exists()


async def test_transport_failure_cleans_credential_directory(binding, tmp_path, monkeypatch):
    path = protected(tmp_path / "secret.json", credentials())
    transport = NetSNMPTransport(credentials_path=path)
    monkeypatch.setattr(transport, "check_available", lambda: None)
    directories = []

    async def fail(args, env, cwd, timeout):
        directories.append(Path(cwd))
        assert (Path(cwd) / "cert_indexes").is_dir()
        raise SNMPError("snmp_timeout")

    monkeypatch.setattr(transport, "_execute", fail)
    with pytest.raises(SNMPError, match="snmp_timeout"):
        await transport.get(binding, binding.interfaces[0])
    assert directories and not directories[0].exists()


async def test_bounded_subprocess_success(tmp_path):
    result = await NetSNMPTransport._execute(
        [sys.executable, "-c", "print('response')"], {}, str(tmp_path), 2)
    assert result == b"response\n"


async def test_transport_preprovisions_certificate_index_before_child_initialization(binding, tmp_path, monkeypatch):
    """Reproduce Debian's create-and-log behavior without requiring its package."""
    path = protected(tmp_path / "secret.json", credentials())
    transport = NetSNMPTransport(credentials_path=path)
    monkeypatch.setattr(transport, "check_available", lambda: None)
    execute = NetSNMPTransport._execute
    directories = []

    async def initialize(args, env, cwd, timeout):
        directories.append(Path(cwd))
        program = (
            "import os, pathlib, sys\n"
            "indexes = pathlib.Path(os.environ['SNMP_PERSISTENT_DIR']) / 'cert_indexes'\n"
            "if not indexes.exists():\n"
            "    indexes.mkdir(mode=0o700)\n"
            "    sys.stderr.write('Created directory: ' + str(indexes) + '\\n')\n"
            f"sys.stdout.buffer.write({FIRST!r})\n"
        )
        return await execute([sys.executable, "-c", program], env, cwd, timeout)

    monkeypatch.setattr(transport, "_execute", initialize)
    assert await transport.get(binding, binding.interfaces[0]) == parsed(binding)
    assert directories and not directories[0].exists()


@pytest.mark.parametrize("code,reason", [
    ("import time; time.sleep(10)", "snmp_timeout"),
    ("import sys; sys.stdout.write('x'*20000)", "snmp_output_limit"),
    ("import sys\nwhile True: sys.stdout.write('x'*65536)", "snmp_output_limit"),
    ("import sys\nwhile True: sys.stderr.write('x'*65536)", "snmp_output_limit"),
    ("import sys; sys.stderr.write('fixture-auth-only'); sys.exit(1)", "snmp_request_failed"),
    ("import sys; sys.stdout.write('response'); sys.stderr.write('fixture-auth-only'); sys.exit(0)", "snmp_request_failed"),
    ("import sys; sys.stdout.write('response'); sys.stderr.write('Created directory: /tmp/private/cert_indexes\\n')", "snmp_request_failed"),
])
async def test_bounded_subprocess_failures_do_not_leak_credentials(tmp_path, code, reason):
    with pytest.raises(SNMPError, match=reason) as raised:
        async with asyncio.timeout(3):
            await NetSNMPTransport._execute([sys.executable, "-c", code], {}, str(tmp_path), 0.2)
    assert "fixture-auth-only" not in str(raised.value)


async def test_subprocess_cancellation_reaps_child(tmp_path, monkeypatch):
    original = asyncio.create_subprocess_exec
    created = []

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        created.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(NetSNMPTransport._execute(
        [sys.executable, "-c", "import time; time.sleep(10)"], {}, str(tmp_path), 20))
    while not created:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert created[0].returncode is not None


async def test_cli_dry_run_has_no_transport_or_owner_io(binding, tmp_path, monkeypatch, capsys):
    from scripts.collect_measured_telemetry import parser, run

    binding_path = protected(tmp_path / "binding.json", binding.model_dump(mode="json"))
    secrets_path = protected(tmp_path / "secrets.json", credentials())
    get = AsyncMock(side_effect=AssertionError("must remain offline"))
    monkeypatch.setattr(NetSNMPTransport, "get", get)
    monkeypatch.setattr(NetSNMPTransport, "check_available", lambda _: None)
    args = parser().parse_args(["--binding", str(binding_path), "--credentials", str(secrets_path), "--dry-run"])
    await run(args)
    output = capsys.readouterr().out
    assert json.loads(output)["scope_checked"] is False
    assert "fixture-auth-only" not in output
    get.assert_not_awaited()


# ------------------------------------------------ ADR-028 per-batch owner authorization


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


def boundary_with_doubles(binding, tmp_path, monkeypatch, *, active=True, ttl=10.0):
    from contextlib import asynccontextmanager

    from app.modules.telemetry import snmp_ownership

    path = protected(tmp_path / "binding.json", binding.model_dump(mode="json"))
    full = AsyncMock()
    monkeypatch.setattr(snmp_ownership, "validate_owner_scope", full)
    exists = AsyncMock(return_value=active)
    monkeypatch.setattr(snmp_ownership.IdentityDirectoryService, "user_exists", exists)
    sessions = []

    @asynccontextmanager
    async def session():
        sessions.append(True)
        yield object()

    clock = FakeClock()
    boundary = snmp_ownership.SNMPOwnerBoundary(binding_path=path, session_factory=session, redis=None,
                                                authority_ttl_seconds=ttl, clock=clock)
    return boundary, full, exists, clock, path


async def test_owner_boundary_full_check_once_per_batch_then_cheap_revocation(binding, tmp_path, monkeypatch):
    """Regression: every sample re-ran permissions, membership and up to 32x200 device pages."""
    boundary, full, exists, _, _ = boundary_with_doubles(binding, tmp_path, monkeypatch)
    await boundary.authorize(binding, True)
    for _ in range(3):
        await boundary.authorize(binding, False)  # per interface GET
    for _ in range(112):
        await boundary.authorize(binding, True)  # per published sample
    assert full.await_count == 1 and boundary.full_checks == 1
    assert exists.await_count == 115
    assert all(call.args[-1] == binding.actor_user_id for call in exists.await_args_list)
    boundary.invalidate()  # next batch
    await boundary.authorize(binding, True)
    assert full.await_count == 2


async def test_owner_boundary_read_cache_never_grants_write(binding, tmp_path, monkeypatch):
    boundary, full, _, _, _ = boundary_with_doubles(binding, tmp_path, monkeypatch)
    await boundary.authorize(binding, False)
    await boundary.authorize(binding, True)
    assert [call.kwargs["publish"] for call in full.await_args_list] == [False, True]


async def test_owner_boundary_ttl_expiry_and_binding_revision(binding, tmp_path, monkeypatch):
    boundary, full, _, clock, path = boundary_with_doubles(binding, tmp_path, monkeypatch, ttl=10.0)
    await boundary.authorize(binding, True)
    clock.value += 9.9
    await boundary.authorize(binding, True)
    assert full.await_count == 1
    clock.value += 0.2
    await boundary.authorize(binding, True)
    assert full.await_count == 2
    changed = binding.model_dump(mode="json")
    changed["port"] = 1161
    protected(path, changed)
    with pytest.raises(SNMPError, match="binding_changed"):
        await boundary.authorize(binding, True)  # version check on every call
    protected(path, binding.model_dump(mode="json"))
    await boundary.authorize(binding, True)
    assert full.await_count == 3  # the revision change dropped the cached authority


async def test_owner_boundary_deactivated_actor_is_observed_on_next_call(binding, tmp_path, monkeypatch):
    boundary, full, exists, _, _ = boundary_with_doubles(binding, tmp_path, monkeypatch)
    await boundary.authorize(binding, True)
    exists.return_value = False
    with pytest.raises(SNMPError, match="collector_actor_revoked"):
        await boundary.authorize(binding, True)
    exists.return_value = True
    await boundary.authorize(binding, True)
    assert full.await_count == 2  # revocation invalidated the batch authority


async def test_owner_boundary_unavailable_is_logged_with_code_and_counted(binding, tmp_path, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.modules.telemetry import snmp_ownership
    from app.modules.telemetry.diagnostics import FailureCounter

    boundary, full, _, _, _ = boundary_with_doubles(binding, tmp_path, monkeypatch)
    boundary._failures = FailureCounter()
    logged = []
    monkeypatch.setattr(snmp_ownership.logger, "warning", lambda event, **fields: logged.append((event, fields)))
    full.side_effect = OperationalError("SELECT 1", {}, Exception("postgresql://nanfo:hunter2@db"))
    with pytest.raises(SNMPError, match="owner_authorization_failed_or_unavailable") as raised:
        await boundary.authorize(binding, True)
    assert raised.value.__suppress_context__
    assert logged == [("telemetry_owner_authorization_failed", {
        "error_code": "owner_authorization_unavailable", "error_type": "OperationalError",
        "device_id": str(binding.device_id), "publish": True, "cached": False})]
    from fastapi import HTTPException

    full.side_effect = HTTPException(403, "Insufficient permissions.")
    with pytest.raises(SNMPError):
        await boundary.authorize(binding, True)
    assert boundary._failures.snapshot() == {"owner_authorization_denied": 1, "owner_authorization_unavailable": 1}
    assert "hunter2" not in repr(logged)


# ------------------------------------------------ ADR-028 SNMPv3 credential file lifecycle


@pytest.fixture
def runtime_base(tmp_path, monkeypatch):
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    monkeypatch.setenv("NANFO_SNMP_RUNTIME_DIR", str(base))
    return base


async def test_secret_file_is_private_memory_scoped_and_unlinked_after_command(
        binding, tmp_path, monkeypatch, runtime_base):
    from app.modules.telemetry import snmp_transport

    transport = NetSNMPTransport(credentials_path=protected(tmp_path / "secret.json", credentials()))
    monkeypatch.setattr(transport, "check_available", lambda: None)
    seen = {}

    async def execute(args, env, cwd, timeout):
        directory = Path(cwd)
        config = directory / "snmp.conf"
        seen["directory"], seen["config"] = directory, config
        assert directory.parent == runtime_base  # never the shared default temp dir
        assert stat.S_IMODE(runtime_base.stat().st_mode) == 0o700
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(config.lstat().st_mode) == 0o600 and not config.is_symlink()
        assert config.stat().st_uid == os.geteuid()
        return FIRST

    removed = []
    real_rmtree = snmp_transport.shutil.rmtree

    def rmtree(path, **kwargs):
        # The secret must already be gone when directory cleanup starts.
        removed.append((Path(path), (Path(path) / "snmp.conf").exists()))
        real_rmtree(path, **kwargs)

    monkeypatch.setattr(transport, "_execute", execute)
    monkeypatch.setattr(snmp_transport.shutil, "rmtree", rmtree)
    assert (await transport.get(binding, binding.interfaces[0])).rx == 1_000_000_000
    assert removed == [(seen["directory"], False)]
    assert not seen["directory"].exists() and list(runtime_base.iterdir()) == []


@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_secret_file_removed_when_command_fails_or_is_cancelled(
        binding, tmp_path, monkeypatch, runtime_base, failure):
    transport = NetSNMPTransport(credentials_path=protected(tmp_path / "secret.json", credentials()))
    monkeypatch.setattr(transport, "check_available", lambda: None)
    started = asyncio.Event()

    async def execute(args, env, cwd, timeout):
        started.set()
        if failure == "error":
            raise SNMPError("snmp_request_failed")
        await asyncio.Event().wait()

    monkeypatch.setattr(transport, "_execute", execute)
    task = asyncio.create_task(transport.get(binding, binding.interfaces[0]))
    await started.wait()
    if failure == "cancel":
        task.cancel()
    with pytest.raises((SNMPError, asyncio.CancelledError)):
        await task
    assert list(runtime_base.iterdir()) == []


@pytest.mark.parametrize("problem", ["shared", "symlink", "missing", "relative"])
def test_runtime_base_must_be_private(tmp_path, monkeypatch, problem):
    from app.modules.telemetry.snmp_transport import private_runtime_base

    base = tmp_path / "runtime"
    if problem == "shared":
        base.mkdir(mode=0o700)
        base.chmod(0o755)
    elif problem == "symlink":
        real = tmp_path / "real"
        real.mkdir(mode=0o700)
        base.symlink_to(real, target_is_directory=True)
    elif problem == "relative":
        base = Path("relative-runtime")
    monkeypatch.setenv("NANFO_SNMP_RUNTIME_DIR", str(base))
    with pytest.raises(SNMPError, match="snmp_runtime_dir_unsafe"):
        private_runtime_base()


def test_runtime_base_prefers_memory_backed_dirs_and_fails_closed(tmp_path, monkeypatch):
    from app.modules.telemetry import snmp_transport

    monkeypatch.delenv("NANFO_SNMP_RUNTIME_DIR", raising=False)
    xdg = tmp_path / "xdg"
    xdg.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg))
    assert snmp_transport.private_runtime_base() == xdg
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    monkeypatch.setattr(snmp_transport, "_SHARED_MEMORY_DIR", tmp_path / "no-shm")
    with pytest.raises(SNMPError, match="snmp_runtime_dir_unavailable"):
        snmp_transport.private_runtime_base()  # never falls back to the default temp dir


def test_protected_revision_is_exact_even_when_timestamps_do_not_change(binding, tmp_path):
    from app.modules.telemetry.snmp_config import ProtectedRevision

    path = protected(tmp_path / "binding.json", binding.model_dump(mode="json"))
    revision = ProtectedRevision(path, SNMPBinding)
    assert revision.matches(binding) and revision.matches(binding)
    before = path.stat()
    changed = binding.model_dump(mode="json")
    changed["sys_name"] = changed["sys_name"][:-1] + ("x" if changed["sys_name"][-1] != "x" else "y")
    path.write_text(json.dumps(changed))  # same size, different identity
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))  # coarse clock: same mtime
    assert path.stat().st_size == before.st_size
    assert not revision.matches(binding)
    path.chmod(0o644)
    with pytest.raises(SNMPError):
        revision.matches(binding)  # security checks run on every call, not only on change
