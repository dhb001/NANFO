"""ADR018 provider replays actual packet bytes; no JSON-only success fixtures."""

import copy
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from emulation.probe_paths import captureInterfaces, digest, observedPaths
from emulation.tests.test_probe_paths import (
    IDENTIFIER,
    SECONDS,
    WINDOW,
    captureFixture,
    decodedFixture,
)
from emulation.topology import expectedLinks, manifest

from app.api.v1.telemetry_paths import read_paths
from app.modules.network.emulation import EmulationBinding
from app.modules.telemetry.emulation import SnapshotReader
from app.modules.telemetry.paths import ProbePathsReader

NOW = datetime.fromtimestamp(SECONDS + 1, UTC)


@pytest.fixture
def path_evidence(tmp_path):
    expected = manifest()
    output = tmp_path / "output"
    output.mkdir()
    binding_dir = tmp_path / "operator"
    binding_dir.mkdir(mode=0o700)
    binding = EmulationBinding.model_validate_json(json.dumps({
        "version": 1, "topology_id": expected["topology_id"],
        "network_id": str(uuid.uuid4()), "workspace_id": str(uuid.uuid4()), "actor_user_id": str(uuid.uuid4()),
        "switches": {s["dpid"]: str(uuid.uuid4()) for s in expected["switches"]},
        "hosts": {h["name"]: str(uuid.uuid4()) for h in expected["hosts"]},
        "port_capacities_mbps": expected["port_capacities_mbps"],
    }))
    binding_path = binding_dir / "binding.json"
    binding_path.write_text(binding.model_dump_json())
    run_id = str(uuid.uuid4())
    snapshot = {"version": 1, "topology_id": expected["topology_id"], "run_id": run_id,
                "sequence": 1, "observed_at": NOW.isoformat(), "hosts": expected["hosts"],
                "switches": [{"dpid": s["dpid"], "name": s["name"], "observed_at": NOW.isoformat(),
                              "flows": [], "ports": [
                                  {"port_no": int(k.split(":")[1]), "rx_bytes": 0, "tx_bytes": 0,
                                   "rx_packets": 0, "tx_packets": 0, "rx_dropped": 0, "tx_dropped": 0,
                                   "duration_sec": 1.0} for k in expected["port_capacities_mbps"]
                                  if k.startswith(s["dpid"] + ":")]} for s in expected["switches"]],
                "links": [dict(zip(("src_dpid", "src_port", "dst_dpid", "dst_port"), link))
                          for link in sorted(expectedLinks())], "queues": [], "probes": []}
    snapshot_path = output / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot))
    capture_dir = output / ("probe-capture-" + WINDOW)
    capture_dir.mkdir()
    captures = []
    for key, data in captureFixture().items():
        relative = f"probe-capture-{WINDOW}/{key}.pcap"
        (output / relative).write_bytes(data)
        captures.append({"capture_id": key, **captureInterfaces()[key], "file": relative,
                         "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    packets = decodedFixture()
    artifact = {"version": 1, "topology_id": expected["topology_id"], "run_id": run_id,
                "window_id": WINDOW, "window_start": datetime.fromtimestamp(SECONDS, UTC).isoformat(),
                "window_end": (NOW - timedelta(seconds=.5)).isoformat(), "icmp_id": IDENTIFIER,
                "scope": "selected_probe_only", "captures": captures, "packets": packets,
                "paths": observedPaths(packets, WINDOW, IDENTIFIER)}
    artifact_path = output / "probe-paths.json"

    def publish():
        artifact.pop("evidence_sha256", None)
        artifact["evidence_sha256"] = digest(artifact)
        artifact_path.write_text(json.dumps(artifact))

    publish()
    return SimpleNamespace(binding=binding, binding_path=binding_path, snapshot=snapshot,
                           snapshot_path=snapshot_path, artifact=artifact, artifact_path=artifact_path,
                           output=output, publish=publish, reader=ProbePathsReader(SnapshotReader(snapshot_path)),
                           args={"binding": binding, "network_id": binding.network_id,
                                 "workspace_id": binding.workspace_id, "now": NOW})


async def test_reader_replays_raw_packets_and_maps_exact_trusted_uuids(path_evidence):
    e = path_evidence
    result = await e.reader.read(**e.args)
    assert result.status == "measured"
    assert result.evidence_verification == "raw_pcap_replayed"
    assert result.captured_packet_count == 24 and result.measured_path_count == 3
    assert result.paths[0].source_device_id == e.binding.hosts["h1"]
    assert result.paths[0].observed_hops[1].device_id == e.binding.switches["0000000000000002"]
    assert result.configuration_comparison == "unavailable"


@pytest.mark.parametrize("fault", ["hop", "packet", "digest", "pcap", "raw_missing", "raw_symlink",
                                   "raw_parent_symlink", "artifact_symlink", "pointer", "capture_scope",
                                   "mixed_run", "future", "duplicate", "oversize", "bool_version",
                                   "snapshot_host", "snapshot_port", "snapshot_link"])
async def test_reader_rejects_untrusted_or_unproven_claims(path_evidence, fault, tmp_path):
    e = path_evidence
    raw_path = e.output / e.artifact["captures"][0]["file"]
    if fault == "hop":
        e.artifact["paths"][0]["observed_hops"][0]["egress_port"] = 2
    elif fault == "packet":
        e.artifact["packets"][0]["packet_sha256"] = "a" * 64
    elif fault == "pcap":
        raw_path.write_bytes(b"x" * 24)
    elif fault == "raw_missing":
        raw_path.unlink()
    elif fault == "raw_symlink":
        other = tmp_path / "elsewhere.pcap"
        raw_path.rename(other)
        raw_path.symlink_to(other)
    elif fault == "raw_parent_symlink":
        other = tmp_path / "elsewhere"
        raw_path.parent.rename(other)
        raw_path.parent.symlink_to(other, target_is_directory=True)
    elif fault == "pointer":
        e.artifact["captures"][0]["file"] = "../../operator/binding.json"
    elif fault == "capture_scope":
        e.artifact["captures"].pop()
    elif fault == "mixed_run":
        e.artifact["run_id"] = str(uuid.uuid4())
    elif fault == "future":
        e.artifact["window_end"] = (NOW + timedelta(seconds=1)).isoformat()
    elif fault == "duplicate":
        e.artifact["packets"].append(copy.deepcopy(e.artifact["packets"][0]))
    elif fault == "bool_version":
        e.artifact["version"] = True
    elif fault == "snapshot_host":
        e.snapshot["hosts"][0]["dpid"] = "0000000000000001"
    elif fault == "snapshot_port":
        e.snapshot["switches"][1]["ports"] = []
    elif fault == "snapshot_link":
        e.snapshot["links"] = []
    e.publish()
    e.snapshot_path.write_text(json.dumps(e.snapshot))
    if fault == "artifact_symlink":
        other = tmp_path / "elsewhere.json"
        e.artifact_path.rename(other)
        e.artifact_path.symlink_to(other)
    elif fault == "oversize":
        e.artifact_path.write_bytes(b" " * 1048577)
    elif fault == "digest":
        e.artifact["evidence_sha256"] = "a" * 64
        e.artifact_path.write_text(json.dumps(e.artifact))
    result = await e.reader.read(**e.args)
    assert result.status == ("run_mismatch" if fault == "mixed_run" else "invalid")
    assert not result.paths and result.evidence_verification is None


async def test_stale_window_is_historical_not_current_and_old_snapshot_is_unavailable(path_evidence):
    e = path_evidence
    later = NOW + timedelta(seconds=31)
    e.snapshot["observed_at"] = later.isoformat()
    for switch in e.snapshot["switches"]:
        switch["observed_at"] = later.isoformat()
    e.snapshot_path.write_text(json.dumps(e.snapshot))
    result = await e.reader.read(**{**e.args, "now": later})
    assert result.status == result.freshness == "stale"
    assert result.measured_path_count == 3 and len(result.paths) == 3
    result = await e.reader.read(**{**e.args, "now": later + timedelta(seconds=31)})
    assert result.status == "unavailable" and not result.paths


async def test_missing_capture_is_partial_only_when_raw_evidence_agrees(path_evidence):
    from emulation.tests.test_probe_paths import pcap

    e = path_evidence
    key = "dist1-eth3-in"
    capture = next(c for c in e.artifact["captures"] if c["capture_id"] == key)
    raw = pcap([])
    (e.output / capture["file"]).write_bytes(raw)
    capture.update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    e.artifact["packets"] = [p for p in e.artifact["packets"] if p["capture_id"] != key]
    e.artifact["paths"] = observedPaths(e.artifact["packets"], WINDOW, IDENTIFIER)
    e.publish()
    result = await e.reader.read(**e.args)
    assert result.status == "partial" and result.measured_path_count == 0


async def test_other_network_cannot_read_bound_evidence(path_evidence):
    result = await path_evidence.reader.read(**{**path_evidence.args, "network_id": uuid.uuid4()})
    assert result.status == "unavailable" and not result.paths


async def test_run_swap_during_raw_read_is_rejected(path_evidence, monkeypatch):
    e = path_evidence
    snapshot = await e.reader.reader.read(now=NOW)
    monkeypatch.setattr(e.reader.reader, "read", AsyncMock(side_effect=[
        snapshot, snapshot.model_copy(update={"run_id": uuid.uuid4()})]))
    assert (await e.reader.read(**e.args)).status == "run_mismatch"


async def test_composition_rechecks_binding_owner_and_actual_network(path_evidence, monkeypatch):
    from app.core.config import get_settings
    from app.core.dependencies import TokenClaims

    e = path_evidence
    settings = get_settings().model_copy(update={
        "EXECUTION_MODE": "emulation", "EMULATION_BINDING_PATH": str(e.binding_path),
        "EMULATION_SNAPSHOT_PATH": str(e.snapshot_path)})
    claims = TokenClaims({"sub": str(uuid.uuid4()), "email": "reader@example.com", "roles": [],
                          "permissions": ["read:telemetry"], "jti": "test", "sid": "test", "exp": 9999999999})
    access = AsyncMock(return_value=SimpleNamespace(network_id=e.binding.network_id,
                                                   workspace_id=e.binding.workspace_id))
    monkeypatch.setattr("app.modules.telemetry.probe_paths.NetworkService.assert_network_workspace_access", access)
    validation = AsyncMock()
    monkeypatch.setattr("app.modules.telemetry.probe_paths.EmulationDiscoveryService.validate_binding", validation)
    reader = AsyncMock(return_value=await e.reader.read(**e.args))
    monkeypatch.setattr("app.modules.telemetry.probe_paths.ProbePathsReader.read", reader)
    args = dict(settings=settings, db=None, redis=None, claims=claims, network_id=e.binding.network_id)
    assert (await read_paths(**args)).status == "measured"
    assert validation.await_args.args[0].actor_user_id == e.binding.actor_user_id
    assert access.await_args.kwargs["actor_user_id"] == claims.user_id
    validation.side_effect = ValueError("owner revoked")
    assert (await read_paths(**args)).reason == "trusted_binding_unavailable"
    assert reader.await_count == 1


async def test_binding_symlink_is_not_accepted(path_evidence, monkeypatch):
    from app.core.config import get_settings
    from app.core.dependencies import TokenClaims

    e = path_evidence
    alias = e.binding_path.parent / "alias.json"
    alias.symlink_to(e.binding_path)
    settings = get_settings().model_copy(update={"EXECUTION_MODE": "emulation",
        "EMULATION_BINDING_PATH": str(alias), "EMULATION_SNAPSHOT_PATH": str(e.snapshot_path)})
    monkeypatch.setattr("app.modules.telemetry.probe_paths.NetworkService.assert_network_workspace_access",
                        AsyncMock(return_value=SimpleNamespace(network_id=e.binding.network_id,
                                                               workspace_id=e.binding.workspace_id)))
    claims = TokenClaims({"sub": str(uuid.uuid4()), "email": "reader@example.com", "roles": [],
                          "permissions": ["read:telemetry"], "jti": "test", "sid": "test", "exp": 9999999999})
    result = await read_paths(settings=settings, db=None, redis=None, claims=claims, network_id=e.binding.network_id)
    assert result.reason == "trusted_binding_unavailable" and not result.paths


def test_router_holds_no_cross_module_repository_or_identity_composition():
    """ADR-028: composition moved from the router into Telemetry's ProbePathsService."""
    import app.api.v1.telemetry_paths as router_module

    for name in ("DeviceRepository", "AuthService", "NetworkService", "EmulationDiscoveryService"):
        assert not hasattr(router_module, name), name


def test_emulation_discovery_composition_is_built_per_session():
    from app.modules.telemetry.probe_paths import build_emulation_discovery

    first = build_emulation_discovery(object(), None, expected_topology={"topology_id": "t"})
    second = build_emulation_discovery(object(), None, expected_topology={"topology_id": "t"})
    assert first.devices is not second.devices and first.topology is None
