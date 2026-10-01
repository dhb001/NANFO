"""ADR-009 boundary, discovery, and measurement regressions (no live lab claims)."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.network.emulation import (
    EmulationBinding,
    EmulationDiscoveryService,
    load_binding,
)
from app.modules.network.topology import TopologyQueryService
from app.modules.telemetry.emulation import (
    EmulationSnapshot,
    EmulationTelemetryAdapter,
    SnapshotReader,
    read_bounded_file,
    validate_json,
)
from app.modules.telemetry.service import build_production_runtime_adapter

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)
DPID = "0000000000000001"
PEER = "0000000000000002"


def snapshot_data(sequence=0):
    observed = (NOW + timedelta(seconds=sequence * 5)).isoformat()
    port = {"port_no": 1, "rx_bytes": 100 + sequence * 625000,
            "tx_bytes": 200 + sequence * 1250000, "rx_packets": 10,
            "tx_packets": 20, "rx_dropped": 0, "tx_dropped": 0,
            "duration_sec": 10.0 + sequence * 5}
    return {"version": 1, "topology_id": "campus-small-v1",
            "run_id": "11111111-1111-4111-8111-111111111111", "sequence": sequence,
            "observed_at": observed,
            "switches": [{"dpid": DPID, "name": "core", "observed_at": observed,
                          "ports": [port], "flows": [{"table_id": 0, "priority": 1,
                              "cookie": 0, "packet_count": 2, "byte_count": 100,
                              "duration_sec": 10.0}]}],
            "links": [{"src_dpid": DPID, "src_port": 1, "dst_dpid": PEER, "dst_port": 1}],
            "hosts": [{"name": "h1", "mac": "02:00:00:00:00:01", "ipv4": "10.77.0.1",
                       "dpid": DPID, "port_no": 2}],
            "queues": [{"dpid": DPID, "port_no": 1, "observed_at": observed,
                        "backlog_bytes": 123, "backlog_packets": 2}],
            "probes": [{"src_host": "h1", "dst_host": "h2", "observed_at": observed,
                        "sent": 4, "received": 3, "rtt_avg_ms": 2.5, "interval_seconds": 1.0}]}


def binding_data():
    return {"version": 1, "topology_id": "campus-small-v1",
            "network_id": str(uuid.UUID(int=1)), "workspace_id": str(uuid.UUID(int=2)),
            "actor_user_id": str(uuid.UUID(int=3)),
            "switches": {DPID: str(uuid.UUID(int=4)), PEER: str(uuid.UUID(int=5))},
            "hosts": {"h1": str(uuid.UUID(int=6)), "h2": str(uuid.UUID(int=7))},
            "port_capacities_mbps": {f"{DPID}:1": 20.0, f"{DPID}:2": 100.0, f"{PEER}:1": 20.0}}


def parse(data):
    return validate_json(EmulationSnapshot, json.dumps(data).encode())


def adapter():
    reader = SnapshotReader(Path("unused"))
    reader.read = AsyncMock()
    reader.assert_snapshot_fresh = MagicMock()
    return EmulationTelemetryAdapter(reader=reader, prepare_snapshot=AsyncMock(return_value=binding_data()))


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(network_id=str(uuid.uuid4())),
    lambda d: d.update(version=True),
    lambda d: d.update(sequence=True),
    lambda d: d.update(observed_at="2026-09-08T12:00:00"),
    lambda d: d.update(observed_at="2026-09-08T12:00:00+01:00"),
    lambda d: d["switches"][0].update(dpid="A" * 16),
    lambda d: d["switches"][0]["ports"][0].update(rx_bytes=-1),
    lambda d: d["switches"][0]["ports"][0].update(rx_bytes="12"),
    lambda d: d["switches"][0]["ports"][0].update(duration_sec=float("nan")),
    lambda d: d["switches"][0]["ports"].append(d["switches"][0]["ports"][0]),
    lambda d: d["probes"][0].update(received=5),
    lambda d: d["probes"][0].update(received=0),
    lambda d: d["hosts"][0].update(ipv4="::1"),
    lambda d: d.update(switches=d["switches"] * 65),
])
def test_strict_snapshot_rejects_invalid(mutation):
    data = snapshot_data()
    mutation(data)
    with pytest.raises(ValueError):
        parse(data)


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError):
        validate_json(EmulationSnapshot, b'{"version":1,"version":1}')


async def test_reader_rejects_stale_switch_independent_of_snapshot(tmp_path):
    path = tmp_path / "snapshot.json"
    data = snapshot_data()
    data["switches"][0]["observed_at"] = (NOW - timedelta(seconds=31)).isoformat()
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="stale"):
        await SnapshotReader(path).read(now=NOW)


@pytest.mark.parametrize("field", ["switches", "queues", "probes", None])
@pytest.mark.parametrize("seconds", [-31, 3])
async def test_reader_freshness(tmp_path, field, seconds):
    data = snapshot_data()
    target = data[field][0] if field else data
    target["observed_at"] = (NOW + timedelta(seconds=seconds)).isoformat()
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        await SnapshotReader(path).read(now=NOW)


async def test_reader_regular_bounded_no_symlinks(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot_data()))
    assert (await SnapshotReader(path).read(now=NOW)).sequence == 0
    with pytest.raises(ValueError):
        await SnapshotReader(path, max_bytes=10).read(now=NOW)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(path)
    with pytest.raises(ValueError):
        await SnapshotReader(symlink).read(now=NOW)
    directory_link = tmp_path / "dirlink"
    directory_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        await SnapshotReader(directory_link / path.name).read(now=NOW)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(ValueError):
        read_bounded_file(fifo, 10)
    with pytest.raises(ValueError):
        read_bounded_file(tmp_path, 10)


def test_first_sample_raw_counters_backlog_probe_semantics():
    samples = adapter().derive(parse(snapshot_data()), binding_data())
    metrics = {s["metric"]: s for s in samples}
    assert "throughput_mbps" not in metrics
    assert "link_utilization_percent" not in metrics
    assert metrics["port_rx_bytes"]["tags"]["rate_quality"] == "unavailable"
    assert metrics["flow_byte_count"]["value"] == 100
    assert metrics["queue_backlog_bytes"]["value"] == 123
    assert metrics["queue_backlog_packets"]["value"] == 2
    assert metrics["packet_loss_percent"]["value"] == 25
    assert metrics["packet_loss_percent"]["tags"]["loss_semantics"] == "probe"
    assert metrics["latency_ms"]["tags"]["latency_semantics"] == "RTT"
    assert all(s["tags"]["synthetic"] is False for s in samples)
    assert len({s["event_id"] for s in samples}) == len(samples)


def test_port_rate_and_full_duplex_utilization():
    samples = adapter().derive(parse(snapshot_data(1)), binding_data(), parse(snapshot_data()))
    metrics = {s["metric"]: s for s in samples}
    assert metrics["throughput_mbps"]["value"] == 2
    assert metrics["link_utilization_percent"]["value"] == 10
    assert metrics["link_utilization_percent"]["tags"]["capacity_mbps"] == 20
    assert metrics["throughput_mbps"]["tags"]["port_no"] == 1


@pytest.mark.parametrize("mutation", [
    lambda d: d["switches"][0]["ports"][0].update(rx_bytes=0),
    lambda d: d["switches"][0]["ports"][0].update(duration_sec=0.0),
    lambda d: d["switches"][0].update(observed_at=NOW.isoformat()),
    lambda d: d["switches"][0].update(observed_at=(NOW + timedelta(seconds=31)).isoformat()),
    lambda d: d.update(run_id=str(uuid.uuid4())),
])
def test_reset_restart_nonpositive_or_long_interval_has_no_rate(mutation):
    data = snapshot_data(1)
    mutation(data)
    samples = adapter().derive(parse(data), binding_data(), parse(snapshot_data()))
    assert not any(s["metric"] == "throughput_mbps" for s in samples)


async def test_retry_ids_and_current_authorization_every_poll():
    collector = adapter()
    collector.reader.read.return_value = parse(snapshot_data())
    first = await collector.poll()
    assert await collector.poll() == first
    assert collector.prepare_snapshot.await_count == 2
    collector.prepare_snapshot.side_effect = HTTPException(403)
    with pytest.raises(HTTPException):
        await collector.poll()


async def test_sequence_regression_mutation_and_retired_run():
    collector = adapter()
    collector.reader.read.return_value = parse(snapshot_data(1))
    await collector.acknowledge_batch(await collector.poll())
    collector.reader.read.return_value = parse(snapshot_data())
    with pytest.raises(ValueError, match="regressed"):
        await collector.poll()
    mutated = snapshot_data(1)
    mutated["queues"] = []
    collector.reader.read.return_value = parse(mutated)
    with pytest.raises(ValueError, match="reused"):
        await collector.poll()
    new_run = snapshot_data(2)
    new_run.update(run_id=str(uuid.uuid4()), sequence=0)
    collector.reader.read.return_value = parse(new_run)
    batch = await collector.poll()
    assert not any(s["metric"] == "throughput_mbps" for s in batch)
    await collector.acknowledge_batch(batch)
    collector.reader.read.return_value = parse(snapshot_data(3))
    with pytest.raises(ValueError, match="retired"):
        await collector.poll()


async def test_binding_file_trust(tmp_path):
    output = tmp_path / "producer"
    output.mkdir()
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(binding_data()))
    path.chmod(0o600)
    assert (await load_binding(path, snapshot_path=output / "snapshot.json")).version == 1
    path.chmod(0o666)
    with pytest.raises(ValueError):
        await load_binding(path, snapshot_path=output / "snapshot.json")
    with pytest.raises(ValueError):
        await load_binding(output / "binding.json", snapshot_path=output / "snapshot.json")


def discovery():
    binding = EmulationBinding.model_validate_json(json.dumps(binding_data()))
    devices = {}
    for key, device_id in {**binding.switches, **binding.hosts}.items():
        devices[device_id] = SimpleNamespace(network_id=binding.network_id, status="active",
            deleted_at=None, hostname={DPID: "core", PEER: "dist1"}.get(key, key),
            ip_address="10.77.0.1" if key == "h1" else None)
    identity = SimpleNamespace(get_profile=AsyncMock(return_value=SimpleNamespace(
        permissions=["write:config", "read:topology"])))
    topology = SimpleNamespace(replace_observed_device_edges=AsyncMock())
    service = EmulationDiscoveryService(identity=identity,
        network=SimpleNamespace(assert_network_workspace_access=AsyncMock()),
        devices=SimpleNamespace(get_by_id=AsyncMock(side_effect=lambda key: devices.get(key))),
        topology=topology, expected_topology={"topology_id": binding.topology_id,
            "switches": [{"dpid": DPID, "name": "core"}, {"dpid": PEER, "name": "dist1"}],
            "hosts": [snapshot_data()["hosts"][0], {"name": "h2"}],
            "links": [{"a": ["core", 1], "b": ["dist1", 1]}],
            "port_capacities_mbps": binding.port_capacities_mbps})
    return service, binding, devices


async def test_discovery_projects_host_and_observed_links_only():
    service, binding, _ = discovery()
    await service.apply_snapshot(binding, parse(snapshot_data()))
    kwargs = service.topology.replace_observed_device_edges.await_args.kwargs
    assert kwargs["owner_id"] == binding.owner_id
    assert len(kwargs["edges"]) == 2
    assert {e.metadata["measurement_method"] for e in kwargs["edges"]} == {"lldp_discovery", "host_attachment"}
    service.network.assert_network_workspace_access.assert_awaited_once_with(
        network_id=binding.network_id, requested_workspace_id=binding.workspace_id,
        actor_user_id=str(binding.actor_user_id), require_write=True)


@pytest.mark.parametrize("failure", ["capability", "membership", "inactive", "deleted", "tenant", "missing"])
async def test_discovery_revalidates_before_any_write(failure):
    service, binding, devices = discovery()
    await service.apply_snapshot(binding, parse(snapshot_data()))
    service.topology.replace_observed_device_edges.reset_mock()
    device = devices[binding.switches[DPID]]
    if failure == "capability":
        service.identity.get_profile.return_value.permissions = ["read:topology"]
    elif failure == "membership":
        service.network.assert_network_workspace_access.side_effect = HTTPException(403)
    elif failure == "inactive":
        device.status = "inactive"
    elif failure == "deleted":
        device.deleted_at = NOW
    elif failure == "tenant":
        device.network_id = uuid.uuid4()
    else:
        devices.clear()
    with pytest.raises((HTTPException, ValueError)):
        await service.apply_snapshot(binding, parse(snapshot_data(1)))
    service.topology.replace_observed_device_edges.assert_not_awaited()


@pytest.mark.parametrize("mutation", [
    lambda d: d["switches"][0].update(name="other"),
    lambda d: d["hosts"][0].update(mac="02:00:00:00:00:ff"),
    lambda d: d["hosts"][0].update(port_no=1),
    lambda d: d["links"][0].update(src_port=2),
    lambda d: d["queues"][0].update(port_no=99),
    lambda d: d["probes"][0].update(dst_host="unknown"),
])
async def test_discovery_rejects_unexpected_identities(mutation):
    service, binding, _ = discovery()
    data = snapshot_data()
    mutation(data)
    with pytest.raises(ValueError):
        await service.apply_snapshot(binding, parse(data))
    service.topology.replace_observed_device_edges.assert_not_awaited()


def owner_read_discovery(order):
    """Discovery composed like ``build_emulation_discovery``: no repository argument."""
    service, binding, devices = discovery()
    network = SimpleNamespace(assert_network_workspace_access=AsyncMock())

    async def owner_read(**kwargs):
        order.append("read")
        return {device_id: devices[device_id] for device_id in kwargs["device_ids"] if device_id in devices}

    network.get_devices_for_owner = AsyncMock(side_effect=owner_read)

    async def release():
        order.append("release")

    async def write(**kwargs):
        order.append("graph")

    service.topology.replace_observed_device_edges.side_effect = write
    return EmulationDiscoveryService(identity=service.identity, network=network, topology=service.topology,
                                     expected_topology=service.expected_topology, release=release), binding, devices


async def test_discovery_reads_devices_through_the_network_service_and_releases_before_graph_io():
    order = []
    service, binding, _ = owner_read_discovery(order)
    await service.apply_snapshot(binding, parse(snapshot_data()))
    assert order == ["read", "release", "graph"]
    kwargs = service.network.get_devices_for_owner.await_args.kwargs
    assert kwargs["network_id"] == binding.network_id and kwargs["requested_workspace_id"] == binding.workspace_id
    assert set(kwargs["device_ids"]) == {*binding.switches.values(), *binding.hosts.values()}
    assert service.devices is None


@pytest.mark.parametrize("failure", ["missing", "inactive", "tenant"])
async def test_owner_read_validation_failures_never_release_or_write(failure):
    order = []
    service, binding, devices = owner_read_discovery(order)
    device_id = binding.switches[DPID]
    if failure == "missing":
        devices.pop(device_id)
    elif failure == "inactive":
        devices[device_id].status = "inactive"
    else:
        devices[device_id].network_id = uuid.uuid4()
    with pytest.raises(ValueError):
        await service.apply_snapshot(binding, parse(snapshot_data()))
    assert order == ["read"]


def test_build_emulation_discovery_composes_public_services_per_session():
    from app.modules.identity.service import AuthService
    from app.modules.network.emulation import build_emulation_discovery
    from app.modules.network.service import NetworkService

    db = AsyncMock()
    first = build_emulation_discovery(db, None, expected_topology={"topology_id": "t"})
    second = build_emulation_discovery(AsyncMock(), None, expected_topology={"topology_id": "t"})
    assert isinstance(first.identity, AuthService) and isinstance(first.network, NetworkService)
    assert first.devices is None and first.topology is None and first.release == db.rollback
    assert first.network is not second.network


@pytest.mark.parametrize("mode", ["demo", "production", "emulation"])
def test_factory_emulation_mode_only(mode):
    with patch("app.modules.telemetry.runtime.adapters.get_settings", return_value=SimpleNamespace(EXECUTION_MODE=mode)):
        kwargs = {"mode": "emulation", "seeded_sample_key": "", "seeded_metric": "", "seeded_value": 0,
                  "seeded_unit": "", "seeded_source": "", "emulation_adapter": adapter()}
        if mode == "emulation":
            assert build_production_runtime_adapter(**kwargs) is kwargs["emulation_adapter"]
        else:
            with pytest.raises(ValueError):
                build_production_runtime_adapter(**kwargs)


async def test_observed_replace_is_atomic_and_owner_scoped():
    service, binding, _ = discovery()
    await service.apply_snapshot(binding, parse(snapshot_data()))
    kwargs = service.topology.replace_observed_device_edges.await_args.kwargs
    result = AsyncMock()
    result.single.side_effect = [{"matched": 2}, {"written": 2}]
    tx = SimpleNamespace(run=AsyncMock(return_value=result))
    session = AsyncMock()

    async def execute_write(callback):
        return await callback(tx)

    session.execute_write.side_effect = execute_write
    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    assert await TopologyQueryService(driver).replace_observed_device_edges(**kwargs) == 2
    # ADR-028: endpoint revision locks (sorted, de-duplicated) precede every read/write.
    lock = tx.run.await_args_list[0]
    assert "MERGE (r:DeviceEventRevision {device_id: device_id})" in lock.args[0]
    endpoints = {edge.source_id for edge in kwargs["edges"]} | {edge.target_id for edge in kwargs["edges"]}
    assert lock.kwargs["device_ids"] == sorted(endpoints)
    delete = tx.run.await_args_list[2]
    assert "r.observation_owner = $owner_id AND r.synthetic = false" in delete.args[0]
    assert "r.execution_mode = 'emulation'" in delete.args[0]
    assert delete.kwargs["owner_id"] == binding.owner_id
    assert "edge_key: edge.key" in tx.run.await_args_list[3].args[0]


async def test_graph_cross_page_and_parallel_ports_are_preserved():
    ids = [str(uuid.UUID(int=i)) for i in (1, 2)]
    node_result, edge_result = AsyncMock(), AsyncMock()
    node_result.data.return_value = [{"device_id": i, "hostname": "switch", "device_type": "switch",
                                      "status": "active"} for i in ids]
    edge_result.data.return_value = [
        {"source_id": ids[0], "target_id": ids[1],
         "edge_properties": {"edge_key": str(port), "source_port": port, "target_port": port}}
        for port in (1, 2)]
    session = AsyncMock()
    session.run.side_effect = [node_result, edge_result]

    async def execute_read(work):
        return await work(session)

    session.execute_read.side_effect = execute_read
    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock()
    graph, cursor = await TopologyQueryService(driver).get_graph(uuid.uuid4(), uuid.uuid4(), limit=1)
    assert len(graph.nodes) == 1 and len(graph.edges) == 2 and cursor == ids[0]
    query = session.run.await_args_list[1].args[0]
    assert "WHERE s.device_id IN $device_ids" in query
    assert "AND t.device_id IN $device_ids" not in query


async def test_missing_projection_aborts_before_cleanup():
    service, binding, _ = discovery()
    await service.apply_snapshot(binding, parse(snapshot_data()))
    kwargs = service.topology.replace_observed_device_edges.await_args.kwargs
    result = AsyncMock()
    result.single.return_value = {"matched": 1}
    tx = SimpleNamespace(run=AsyncMock(return_value=result))

    async def execute_write(callback):
        return await callback(tx)

    session = AsyncMock()
    session.execute_write.side_effect = execute_write
    driver = MagicMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    with pytest.raises(ValueError, match="projection incomplete"):
        await TopologyQueryService(driver).replace_observed_device_edges(**kwargs)
    # Only the endpoint lock and the activity check ran: no cleanup, no merge.
    assert tx.run.await_count == 2
    assert "DeviceEventRevision" in tx.run.await_args_list[0].args[0]
    assert "AS matched" in tx.run.await_args_list[1].args[0]


async def test_parallel_discovery_pairs_and_empty_cleanup():
    service, binding, _ = discovery()
    binding.port_capacities_mbps[f"{PEER}:2"] = 100.0
    service.expected_topology["links"].append({"a": ["core", 2], "b": ["dist1", 2]})
    data = snapshot_data()
    data["hosts"] = []
    data["links"].append({"src_dpid": DPID, "src_port": 2, "dst_dpid": PEER, "dst_port": 2})
    data["links"].append({"src_dpid": PEER, "src_port": 1, "dst_dpid": DPID, "dst_port": 1})
    await service.apply_snapshot(binding, parse(data))
    edges = service.topology.replace_observed_device_edges.await_args.kwargs["edges"]
    assert len(edges) == 2 and len({e.metadata["edge_key"] for e in edges}) == 2
    data["links"] = []
    await service.apply_snapshot(binding, parse(data))
    assert service.topology.replace_observed_device_edges.await_args.kwargs["edges"] == []


async def test_runtime_composition_checks_trusted_manifest_and_fresh_session(tmp_path, monkeypatch):
    from app.main import _build_emulation_adapter

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3]))
    from emulation.topology import manifest

    topology = manifest()
    data = binding_data()
    data["switches"] = {s["dpid"]: str(uuid.uuid4()) for s in topology["switches"]}
    data["hosts"] = {h["name"]: str(uuid.uuid4()) for h in topology["hosts"]}
    data["port_capacities_mbps"] = topology["port_capacities_mbps"]
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps(data))
    settings = SimpleNamespace(EXECUTION_MODE="emulation", EMULATION_BINDING_PATH=str(binding_path),
        EMULATION_SNAPSHOT_PATH=str(tmp_path / "producer" / "snapshot.json"),
        EMULATION_SNAPSHOT_MAX_BYTES=4194304, EMULATION_SNAPSHOT_MAX_AGE_SECONDS=30,
        EMULATION_SNAPSHOT_FUTURE_SKEW_SECONDS=2)
    collector = await _build_emulation_adapter(settings, AsyncMock())
    db = AsyncMock()
    sessions = MagicMock()
    sessions.return_value.__aenter__ = AsyncMock(return_value=db)
    sessions.return_value.__aexit__ = AsyncMock()
    services = []

    async def apply(self, bound, snapshot):
        services.append(self)
        return data

    with (
        patch("app.main.AsyncSessionLocal", sessions),
        patch("app.main.get_neo4j_driver", return_value=MagicMock()),
        patch("app.modules.network.emulation.EmulationDiscoveryService.apply_snapshot", apply),
    ):
        await collector.prepare_snapshot(parse(snapshot_data()))
        await collector.prepare_snapshot(parse(snapshot_data()))
    assert sessions.call_count == 2 and len(services) == 2
    # ADR-028: Network's public composition per poll — owner device reads (no repository),
    # a graph writer, and the session released before any graph write.
    from app.modules.network.service import NetworkService

    first, second = services
    assert first is not second and first.network is not second.network
    assert all(service.devices is None and isinstance(service.network, NetworkService)
               and service.topology is not None and service.release is db.rollback for service in services)


def test_flow_entries_with_same_table_priority_cookie_keep_independent_raw_counters():
    data = snapshot_data()
    data["switches"][0]["flows"].append({**data["switches"][0]["flows"][0], "byte_count": 200})
    samples = adapter().derive(parse(data), binding_data())
    flows = [s for s in samples if s["metric"] == "flow_byte_count"]
    assert len({s["event_id"] for s in flows}) == 2
    assert {s["value"] for s in flows} == {100, 200}


async def test_cached_observations_dedup_across_sequences_and_conflicts():
    collector = adapter()
    data = snapshot_data()
    collector.reader.read.return_value = parse(data)
    first = await collector.poll()
    await collector.acknowledge_batch(first)
    data.update(sequence=1, observed_at=(NOW + timedelta(seconds=5)).isoformat())
    collector.reader.read.return_value = parse(data)
    assert await collector.poll() == []
    await collector.acknowledge_batch(collector._samples)
    data.update(sequence=2, observed_at=(NOW + timedelta(seconds=10)).isoformat())
    data["probes"][0]["received"] = 2
    collector.reader.read.return_value = parse(data)
    with pytest.raises(ValueError, match="conflicting.*observation"):
        await collector.poll()


@pytest.mark.parametrize("family,field", [("queues", "backlog_bytes"), ("switches", "rx_bytes")])
async def test_changed_cached_raw_observation_rejected(family, field):
    collector = adapter()
    data = snapshot_data()
    collector.reader.read.return_value = parse(data)
    await collector.acknowledge_batch(await collector.poll())
    data.update(sequence=1, observed_at=(NOW + timedelta(seconds=5)).isoformat())
    target = data[family][0]["ports"][0] if family == "switches" else data[family][0]
    target[field] += 1
    collector.reader.read.return_value = parse(data)
    with pytest.raises(ValueError, match="conflicting"):
        await collector.poll()


def test_rate_uses_openflow_duration_not_delayed_flow_completion():
    data = snapshot_data(1)
    data["switches"][0]["observed_at"] = (NOW + timedelta(seconds=12)).isoformat()
    metrics = {s["metric"]: s for s in adapter().derive(parse(data), binding_data(), parse(snapshot_data()))}
    assert metrics["throughput_mbps"]["value"] == 2
    assert metrics["throughput_mbps"]["tags"]["interval_seconds"] == 5
    assert metrics["throughput_mbps"]["tags"]["interval_clock"] == "openflow_port_duration"


async def test_pending_expiry_blocks_without_reading_newer_snapshot():
    collector = adapter()
    collector.reader.read.return_value = parse(snapshot_data())
    first = await collector.poll()
    collector.reader.read.return_value = parse(snapshot_data(1))
    collector.reader.assert_snapshot_fresh.side_effect = ValueError("stale")
    with pytest.raises(ValueError, match="pending.*expired.*retained"):
        await collector.poll()
    assert collector.reader.read.await_count == 1
    assert collector._previous is None and collector._samples is first


async def test_identity_state_is_bounded_fail_closed():
    collector = adapter()
    collector._identity_limit = 1
    collector.reader.read.return_value = parse(snapshot_data())
    with pytest.raises(ValueError, match="state limit"):
        await collector.poll()
    assert collector._pending is None and collector._previous is None


def test_ids_ignore_transport_sequence_but_include_observation_and_rate_interval():
    data = snapshot_data(1)
    collector = adapter()
    first = collector.derive(parse(data), binding_data(), parse(snapshot_data()))
    data["sequence"] = 99
    repeated = collector.derive(parse(data), binding_data(), parse(snapshot_data()))
    assert [s["event_id"] for s in first] == [s["event_id"] for s in repeated]
    prior = snapshot_data()
    prior["switches"][0]["ports"][0]["duration_sec"] = 11.0
    changed_interval = collector.derive(parse(data), binding_data(), parse(prior))
    ids = {s["metric"]: s["event_id"] for s in first}
    changed = {s["metric"]: s["event_id"] for s in changed_interval}
    assert ids["throughput_mbps"] != changed["throughput_mbps"]
    assert ids["port_rx_bytes"] == changed["port_rx_bytes"]
