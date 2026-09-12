"""ADR018 read-only selected-probe evidence, independently replayed from bounded pcaps."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.modules.telemetry.emulation import (
    DPID,
    Name,
    SnapshotReader,
    StrictSchema,
    UTCTime,
    read_bounded_file,
    validate_json,
)

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Interface = Annotated[str, Field(pattern=r"^[a-z0-9-]{1,80}$")]
ProbeNumber = Annotated[int, Field(ge=1, le=65535)]
ProbePort = Annotated[int, Field(ge=0, le=65535)]


class Capture(StrictSchema):
    capture_id: Interface
    interface: Interface
    direction: Literal["in", "out"]
    dpid: DPID | None
    port_no: ProbePort
    host: Name | None
    file: Annotated[str, Field(pattern=r"^probe-capture-[0-9a-f-]{36}/[a-z0-9-]{1,80}\.pcap$")]
    sha256: Hash
    size_bytes: Annotated[int, Field(ge=24, le=65536)]


class CapturedPacket(StrictSchema):
    capture_id: Interface
    record_index: Annotated[int, Field(ge=1, le=512)]
    timestamp: UTCTime
    icmp_id: ProbeNumber
    icmp_seq: Annotated[int, Field(ge=1, le=3)]
    src_ip: Literal["10.77.0.1"]
    dst_ip: Literal["10.77.0.3"]
    payload_sha256: Hash
    packet_sha256: Hash


class ObservedHop(StrictSchema):
    dpid: DPID
    ingress_port: ProbePort | None
    egress_port: ProbePort | None
    received_at: UTCTime | None
    sent_at: UTCTime | None


class ProbePath(StrictSchema):
    packet_id: Annotated[str, Field(max_length=48)]
    icmp_id: ProbeNumber
    icmp_seq: Annotated[int, Field(ge=1, le=3)]
    src_host: Literal["h1"]
    dst_host: Literal["h3"]
    src_ip: Literal["10.77.0.1"]
    dst_ip: Literal["10.77.0.3"]
    source_timestamp: UTCTime | None
    destination_timestamp: UTCTime | None
    status: Literal["measured", "partial", "ambiguous"]
    observed_hops: Annotated[list[ObservedHop], Field(max_length=64)]
    captured_packet_count: Annotated[int, Field(ge=0, le=512)]


class ProbeArtifact(StrictSchema):
    version: Literal[1]
    topology_id: Literal["campus-small-v1"]
    run_id: uuid.UUID
    window_id: uuid.UUID
    window_start: UTCTime
    window_end: UTCTime
    icmp_id: ProbeNumber
    scope: Literal["selected_probe_only"]
    captures: Annotated[list[Capture], Field(min_length=1, max_length=64)]
    packets: Annotated[list[CapturedPacket], Field(max_length=512)]
    paths: Annotated[list[ProbePath], Field(min_length=3, max_length=3)]
    evidence_sha256: Hash

    @model_validator(mode="after")
    def bounded_window(self):
        if not 0 < (self.window_end - self.window_start).total_seconds() <= 30:
            raise ValueError("invalid probe window")
        if any(not self.window_start <= p.timestamp <= self.window_end for p in self.packets):
            raise ValueError("packet outside probe window")
        if len({c.capture_id for c in self.captures}) != len(self.captures):
            raise ValueError("duplicate capture identity")
        if len({(p.capture_id, p.record_index) for p in self.packets}) != len(self.packets):
            raise ValueError("duplicate capture record")
        return self


class BoundHop(ObservedHop):
    device_id: uuid.UUID


class BoundPath(ProbePath):
    source_device_id: uuid.UUID
    destination_device_id: uuid.UUID
    observed_hops: list[BoundHop]


class ProbePathsResponse(BaseModel):
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    status: Literal["measured", "partial", "ambiguous", "stale", "unavailable", "invalid", "run_mismatch"]
    reason: str | None = None
    scope: Literal["selected_probe_only"] = "selected_probe_only"
    freshness: Literal["fresh", "stale", "unavailable"] = "unavailable"
    run_id: uuid.UUID | None = None
    window_id: uuid.UUID | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    age_seconds: float | None = None
    max_age_seconds: float = 30
    evidence_sha256: str | None = None
    evidence_verification: Literal["raw_pcap_replayed"] | None = None
    captured_packet_count: int = 0
    measured_path_count: int = 0
    paths: list[BoundPath] = Field(default_factory=list)
    captures: list[Capture] = Field(default_factory=list)
    packets: list[CapturedPacket] = Field(default_factory=list)
    configuration_comparison: Literal["unavailable"] = "unavailable"
    path_variation: Literal["single_observed_path", "multiple_observed_paths", "unknown"] = "unknown"


class ProbePathsReader:
    """Fixed sibling artifact, no caller paths, writes, DB queries or historical scans.

    The caller must supply an operator binding freshly authorized by Network. Raw
    pointers are checked against a generated allowlist before any filesystem read.
    Hashes provide integrity, not cryptographic attestation of a compromised lab.
    """

    def __init__(self, reader: SnapshotReader):
        self.reader = reader
        self.max_age = min(30, reader.max_age_seconds)

    async def read(self, *, binding, network_id: uuid.UUID, workspace_id: uuid.UUID,
                   now: datetime | None = None) -> ProbePathsResponse:
        from emulation.probe_paths import (
            MAX_PCAP_BYTES,
            captureInterfaces,
            decodePcap,
            digest,
            observedPaths,
        )
        from emulation.topology import expectedLinks, manifest

        now = now or datetime.now(UTC)
        result = ProbePathsResponse(network_id=network_id, workspace_id=workspace_id,
                                    status="unavailable", max_age_seconds=self.max_age)
        if binding.network_id != network_id or binding.workspace_id != workspace_id:
            return result.model_copy(update={"reason": "binding_scope_mismatch"})
        try:
            snapshot = await self.reader.read(now=now)
        except ValueError:
            return result.model_copy(update={"reason": "current_snapshot_unavailable"})
        try:
            raw = await asyncio.to_thread(read_bounded_file,
                                         self.reader.path.parent / "probe-paths.json", 1048576)
        except FileNotFoundError:
            return result.model_copy(update={"reason": "capture_not_recorded"})
        except (OSError, ValueError):
            return result.model_copy(update={"status": "invalid", "reason": "artifact_unreadable"})
        try:
            artifact = validate_json(ProbeArtifact, raw)
            # Preserve the exact timestamp spelling when checking producer digests.
            import json

            document = json.loads(raw)
            evidence_hash = document.pop("evidence_sha256")
            if digest(document) != evidence_hash:
                raise ValueError("artifact digest differs")
            if artifact.run_id != snapshot.run_id:
                return result.model_copy(update={"status": "run_mismatch", "reason": "not_current_run"})
            if artifact.window_end > snapshot.observed_at or artifact.window_end > now:
                raise ValueError("probe window newer than current snapshot")
            expected = manifest()
            if (snapshot.topology_id != binding.topology_id
                    or {s.name: s.dpid for s in snapshot.switches}
                    != {s["name"]: s["dpid"] for s in expected["switches"]}
                    or {h.name: h.model_dump(mode="json") for h in snapshot.hosts}
                    != {h["name"]: h for h in expected["hosts"]}
                    or set(binding.switches) != {s["dpid"] for s in expected["switches"]}
                    or set(binding.hosts) != {h["name"] for h in expected["hosts"]}
                    or binding.port_capacities_mbps != expected["port_capacities_mbps"]):
                raise ValueError("untrusted inventory identity")
            links = {(link.src_dpid, link.src_port, link.dst_dpid, link.dst_port) for link in snapshot.links}
            if not links.issubset(expectedLinks()):
                raise ValueError("untrusted snapshot links")
            expected_captures = captureInterfaces()
            if {c.capture_id for c in artifact.captures} != set(expected_captures):
                raise ValueError("incomplete capture coverage")
            packets = []
            for capture in artifact.captures:
                metadata = expected_captures[capture.capture_id]
                if any(getattr(capture, key) != value for key, value in metadata.items()):
                    raise ValueError("capture interface identity differs")
                # Never dereference the producer's file field. Derive the same safe name.
                relative = f"probe-capture-{artifact.window_id}/{capture.capture_id}.pcap"
                if capture.file != relative:
                    raise ValueError("capture pointer differs")
                data = await asyncio.to_thread(read_bounded_file, self.reader.path.parent / relative,
                                               MAX_PCAP_BYTES)
                if len(data) != capture.size_bytes or hashlib.sha256(data).hexdigest() != capture.sha256:
                    raise ValueError("capture hash differs")
                packets.extend(decodePcap(data, capture.capture_id, str(artifact.window_id), artifact.icmp_id))
                if len(packets) > 512:
                    raise ValueError("capture packet bound exceeded")
            if packets != document["packets"]:
                raise ValueError("packet claims differ from raw captures")
            paths = observedPaths(packets, str(artifact.window_id), artifact.icmp_id)
            if paths != document["paths"]:
                raise ValueError("hop claims differ from raw captures")
            ports = {s.dpid: {p.port_no for p in s.ports} for s in snapshot.switches}
            for path in paths:
                for hop in path["observed_hops"]:
                    if any(port is not None and port not in ports[hop["dpid"]]
                           for port in (hop["ingress_port"], hop["egress_port"])):
                        raise ValueError("observed port absent from active snapshot")
                for before, after in zip(path["observed_hops"], path["observed_hops"][1:]):
                    if path["status"] == "measured" and (
                        before["dpid"], before["egress_port"], after["dpid"], after["ingress_port"]
                    ) not in links:
                        raise ValueError("measured link absent from active snapshot")
            current = await self.reader.read(now=now)
            if current.run_id != snapshot.run_id:
                return result.model_copy(update={"status": "run_mismatch", "reason": "run_changed_during_read"})
            if current.sequence < snapshot.sequence or current.observed_at < snapshot.observed_at:
                raise ValueError("snapshot regressed during read")
            if (current.hosts != snapshot.hosts or current.links != snapshot.links
                    or {s.dpid: {p.port_no for p in s.ports} for s in current.switches} != ports):
                raise ValueError("topology changed during read")
            age = (now - artifact.window_end).total_seconds()
            stale = (now - artifact.window_start).total_seconds() > self.max_age
            states = {p.status for p in artifact.paths}
            state = "ambiguous" if "ambiguous" in states else "partial" if "partial" in states else "measured"
            routes = {tuple((h.dpid, h.ingress_port, h.egress_port) for h in p.observed_hops)
                      for p in artifact.paths if p.status == "measured"}
            return ProbePathsResponse(
                network_id=network_id, workspace_id=workspace_id, status="stale" if stale else state,
                reason="measurement_window_expired" if stale else None,
                freshness="stale" if stale else "fresh", run_id=artifact.run_id,
                window_id=artifact.window_id, window_start=artifact.window_start, window_end=artifact.window_end,
                age_seconds=age, max_age_seconds=self.max_age, evidence_sha256=evidence_hash,
                evidence_verification="raw_pcap_replayed", captured_packet_count=len(packets),
                measured_path_count=sum(p.status == "measured" for p in artifact.paths),
                paths=[BoundPath(**{**p.model_dump(),
                    "source_device_id": binding.hosts[p.src_host],
                    "destination_device_id": binding.hosts[p.dst_host],
                    "observed_hops": [BoundHop(**h.model_dump(), device_id=binding.switches[h.dpid])
                                      for h in p.observed_hops]}) for p in artifact.paths],
                captures=artifact.captures, packets=artifact.packets,
                path_variation="multiple_observed_paths" if len(routes) > 1 else
                    "single_observed_path" if routes else "unknown",
            )
        except (OSError, ValueError, KeyError, OverflowError):
            return result.model_copy(update={"status": "invalid", "reason": "evidence_validation_failed"})
