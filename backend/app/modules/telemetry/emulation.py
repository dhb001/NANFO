"""ADR-009 snapshot boundary and measured counter derivation, without protocol I/O."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    IPvAnyAddress,
    ValidationError,
    model_validator,
)

from app.modules.telemetry.service import RuntimeTelemetryAdapter

DPID = Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
Name = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]
Counter = Annotated[int, Field(ge=0, le=2**64 - 1)]
PortNumber = Annotated[int, Field(ge=1, le=2**32 - 1)]
NonnegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]


def utc_timestamp(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be UTC")
    return value


def parse_utc_timestamp(value: Any) -> datetime:
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(value, datetime):
        return value
    raise ValueError("timestamp must be an ISO UTC string")


UTCTime = Annotated[datetime, BeforeValidator(parse_utc_timestamp), AfterValidator(utc_timestamp)]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def strict_version(cls, value: Any) -> Any:
        if isinstance(value, dict) and "version" in value and type(value["version"]) is not int:
            raise ValueError("version must be an integer")
        return value


class Port(StrictSchema):
    port_no: PortNumber
    rx_bytes: Counter
    tx_bytes: Counter
    rx_packets: Counter
    tx_packets: Counter
    rx_dropped: Counter
    tx_dropped: Counter
    duration_sec: NonnegativeFloat


class Flow(StrictSchema):
    table_id: Annotated[int, Field(ge=0, le=255)]
    priority: Annotated[int, Field(ge=0, le=65535)]
    cookie: Counter
    packet_count: Counter
    byte_count: Counter
    duration_sec: NonnegativeFloat


class Switch(StrictSchema):
    dpid: DPID
    name: Name
    observed_at: UTCTime
    ports: Annotated[list[Port], Field(max_length=256)]
    flows: Annotated[list[Flow], Field(max_length=4096)]

    @model_validator(mode="after")
    def unique_ports(self) -> Self:
        if len({p.port_no for p in self.ports}) != len(self.ports):
            raise ValueError("duplicate switch port")
        return self


class Link(StrictSchema):
    src_dpid: DPID
    src_port: PortNumber
    dst_dpid: DPID
    dst_port: PortNumber

    @model_validator(mode="after")
    def no_self_link(self) -> Self:
        if self.src_dpid == self.dst_dpid:
            raise ValueError("self switch link")
        return self


class Host(StrictSchema):
    name: Name
    mac: Annotated[str, Field(pattern=r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")]
    ipv4: IPvAnyAddress
    dpid: DPID
    port_no: PortNumber

    @model_validator(mode="before")
    @classmethod
    def ip_string(cls, value: Any) -> Any:
        if isinstance(value, dict) and not isinstance(value.get("ipv4"), str):
            raise ValueError("host IPv4 must be a string")  # noqa: TRY004 - Pydantic validation error
        return value

    @model_validator(mode="after")
    def ipv4_only(self) -> Self:
        if self.ipv4.version != 4:
            raise ValueError("host must use IPv4")
        return self


class Queue(StrictSchema):
    dpid: DPID
    port_no: PortNumber
    observed_at: UTCTime
    backlog_bytes: Counter
    backlog_packets: Counter


class Probe(StrictSchema):
    src_host: Name
    dst_host: Name
    observed_at: UTCTime
    sent: Annotated[int, Field(ge=1, le=1000000)]
    received: Annotated[int, Field(ge=0, le=1000000)]
    rtt_avg_ms: NonnegativeFloat | None
    interval_seconds: Annotated[float, Field(gt=0, le=86400, allow_inf_nan=False)]

    @model_validator(mode="after")
    def consistent_results(self) -> Self:
        if self.received > self.sent or self.src_host == self.dst_host:
            raise ValueError("invalid probe counts or endpoints")
        if self.received == 0 and self.rtt_avg_ms is not None:
            raise ValueError("RTT unavailable without replies")
        return self


class EmulationSnapshot(StrictSchema):
    version: Literal[1]
    topology_id: Literal["campus-small-v1"]
    run_id: uuid.UUID
    sequence: Annotated[int, Field(ge=0, le=2**63 - 1)]
    observed_at: UTCTime
    switches: Annotated[list[Switch], Field(max_length=64)]
    links: Annotated[list[Link], Field(max_length=1024)]
    hosts: Annotated[list[Host], Field(max_length=256)]
    queues: Annotated[list[Queue], Field(max_length=4096)]
    probes: Annotated[list[Probe], Field(max_length=1024)]

    @model_validator(mode="after")
    def unique_identities(self) -> Self:
        groups = [
            [s.dpid for s in self.switches],
            [s.name for s in self.switches],
            [h.name for h in self.hosts],
            [h.mac for h in self.hosts],
            [str(h.ipv4) for h in self.hosts],
            [(q.dpid, q.port_no) for q in self.queues],
            [(p.src_host, p.dst_host) for p in self.probes],
            [(link.src_dpid, link.src_port, link.dst_dpid, link.dst_port) for link in self.links],
        ]
        if any(len(set(group)) != len(group) for group in groups):
            raise ValueError("duplicate snapshot identity")
        if sum(len(s.ports) + len(s.flows) for s in self.switches) > 16384:
            raise ValueError("snapshot sample limit exceeded")
        return self


def read_bounded_file(path: Path, max_bytes: int, *, trusted: bool = False) -> bytes:
    """Open every path component without following symlinks; bound even growing files."""
    if max_bytes < 1:
        raise ValueError("invalid file size limit")
    path = Path(os.path.abspath(path))
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        if trusted:
            parent = os.fstat(directory)
            if parent.st_uid not in {0, os.geteuid()} or parent.st_mode & 0o022:
                raise ValueError("binding directory must be operator owned and not group/world writable")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
                raise ValueError("input must be a bounded regular file")
            if trusted and (info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022):
                raise ValueError("binding must be operator owned and not group/world writable")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError("input file size limit exceeded")
            return data
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def validate_json(model: type[StrictSchema], data: bytes) -> Any:
    # Pydantic's JSON mode preserves strict numbers while accepting UUID/UTC strings.
    try:
        json.loads(data, object_pairs_hook=reject_duplicate_keys)
        return model.model_validate_json(data)
    except (ValueError, ValidationError, RecursionError) as exc:
        raise ValueError("invalid emulation document") from exc


class SnapshotReader:
    def __init__(self, path: Path, *, max_bytes: int = 4194304,
                 max_age_seconds: float = 30, future_skew_seconds: float = 2):
        if max_bytes < 1 or not 0 < max_age_seconds <= 3600 or not 0 <= future_skew_seconds <= 30:
            raise ValueError("invalid snapshot limits")
        self.path = path
        self.max_bytes = max_bytes
        self.max_age_seconds = max_age_seconds
        self.future_skew_seconds = future_skew_seconds

    def assert_fresh(self, observed_at: datetime, now: datetime) -> None:
        utc_timestamp(now)
        age = (now - observed_at).total_seconds()
        if age > self.max_age_seconds or age < -self.future_skew_seconds:
            raise ValueError("stale or future emulation observation")

    async def read(self, *, now: datetime | None = None) -> EmulationSnapshot:
        try:
            data = await asyncio.to_thread(read_bounded_file, self.path, self.max_bytes)
            snapshot = validate_json(EmulationSnapshot, data)
        except (OSError, ValueError) as exc:
            raise ValueError("emulation snapshot unavailable or invalid") from exc
        self.assert_snapshot_fresh(snapshot, now=now)
        return snapshot

    def assert_snapshot_fresh(self, snapshot: EmulationSnapshot, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        self.assert_fresh(snapshot.observed_at, now)
        for observation in [*snapshot.switches, *snapshot.queues, *snapshot.probes]:
            self.assert_fresh(observation.observed_at, now)
            if observation.observed_at > snapshot.observed_at + timedelta(seconds=self.future_skew_seconds):
                raise ValueError("observation newer than snapshot")


class EmulationTelemetryAdapter(RuntimeTelemetryAdapter):
    """One collector; retries replay identical samples/IDs, not newly derived rates.

    The composition callback revalidates the trusted binding and projects discovery
    on every fresh poll/retry. It returns the validated binding's JSON data.
    Call acknowledge_batch only after full publication. Expired pending batches
    stay blocked in memory; restart discards them and is not durable recovery.
    """

    def __init__(self, *, reader: SnapshotReader,
                 prepare_snapshot: Callable[[EmulationSnapshot], Awaitable[dict[str, Any]]]):
        self.reader = reader
        self.prepare_snapshot = prepare_snapshot
        self._previous: EmulationSnapshot | None = None
        self._binding_digest: str | None = None
        self._samples: list[dict[str, Any]] = []
        self._pending: EmulationSnapshot | None = None
        self._pending_observations: dict[str, tuple[datetime, str]] = {}
        self._observations: dict[str, tuple[datetime, str]] = {}
        self._seen: dict[str, tuple[datetime, str]] = {}
        self._identity_limit = 131072
        self._retired_runs: set[uuid.UUID] = set()
        self._lock = asyncio.Lock()

    async def poll(self) -> list[dict[str, Any]]:
        async with self._lock:
            if self._pending is not None:
                # Never read a newer file until the complete batch is published.
                # Stale pending batches remain blocked for operator recovery; no
                # silent discard, advancement, or relabeling as fresh is permitted.
                try:
                    self.reader.assert_snapshot_fresh(self._pending)
                except ValueError as exc:
                    raise ValueError("pending emulation batch expired; retained, operator recovery required") from exc
                binding = await self.prepare_snapshot(self._pending)
                self._check_binding(binding)
                return self._samples
            snapshot = await self.reader.read()
            previous = self._previous
            if previous:
                if snapshot.run_id == previous.run_id:
                    if snapshot.sequence < previous.sequence:
                        raise ValueError("snapshot sequence regressed")
                    if snapshot.sequence == previous.sequence and snapshot != previous:
                        raise ValueError("snapshot identity reused with different contents")
                    if snapshot.sequence > previous.sequence and snapshot.observed_at <= previous.observed_at:
                        raise ValueError("snapshot time did not advance")
                elif (snapshot.run_id in self._retired_runs
                      or snapshot.observed_at <= previous.observed_at):
                    raise ValueError("retired or older emulation run")
                elif len(self._retired_runs) >= 1024:
                    raise ValueError("collector run limit reached; restart required")
            binding = await self.prepare_snapshot(snapshot)
            self._check_binding(binding)
            if previous == snapshot:
                return []
            # Retain fingerprints for every timestamp still acceptable at this
            # watermark (including future skew), rather than count-based eviction
            # that could admit a conflicting replay under load.
            cutoff = snapshot.observed_at - timedelta(
                seconds=self.reader.max_age_seconds + 2 * self.reader.future_skew_seconds)
            self._seen = {key: value for key, value in self._seen.items() if value[0] >= cutoff}
            self._observations = {key: value for key, value in self._observations.items() if value[0] >= cutoff}
            observations = {}

            def observe(device, identity, timestamp, observation):
                key = f"{snapshot.run_id}:{device}:{identity}:{timestamp.isoformat()}"
                value = (timestamp, hashlib.sha256(observation.model_dump_json().encode()).hexdigest())
                if key in self._observations and self._observations[key] != value:
                    raise ValueError("conflicting emulation observation identity")
                observations[key] = value

            for switch in snapshot.switches:
                device = binding["switches"][switch.dpid]
                for port in switch.ports:
                    observe(device, f"port:{port.port_no}:{port.duration_sec}", switch.observed_at, port)
                for index, flow in enumerate(switch.flows):
                    observe(device, f"flow:{index}:{flow.table_id}:{flow.priority}:{flow.cookie}",
                            switch.observed_at, flow)
            for queue in snapshot.queues:
                observe(binding["switches"][queue.dpid], f"queue:{queue.port_no}", queue.observed_at, queue)
            for probe in snapshot.probes:
                observe(binding["hosts"][probe.src_host], f"probe:{probe.dst_host}", probe.observed_at, probe)
            samples = self.derive(snapshot, binding, previous)
            fresh_samples = []
            for sample in samples:
                key = sample["event_id"]
                fingerprint = self._fingerprint(sample)
                if key in self._seen:
                    if self._seen[key][1] != fingerprint:
                        raise ValueError("conflicting emulation measurement identity")
                else:
                    fresh_samples.append(sample)
            if len(self._observations.keys() | observations.keys()) + len(self._seen) + len(fresh_samples) > self._identity_limit:
                raise ValueError("emulation identity state limit exceeded; no batch accepted")
            self._pending = snapshot
            self._pending_observations = observations
            self._samples = fresh_samples
            return self._samples

    def _check_binding(self, binding: dict[str, Any]) -> None:
        digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        if self._binding_digest is not None and digest != self._binding_digest:
            raise ValueError("binding changed; restart collector")
        self._binding_digest = digest

    @staticmethod
    def _fingerprint(sample: dict[str, Any]) -> str:
        # Sequence describes transport, and rate availability describes the
        # collector baseline, not the identity/value of a raw observation.
        tags = {k: v for k, v in sample["tags"].items() if k not in {"sequence", "rate_quality"}}
        return hashlib.sha256(json.dumps({**sample, "tags": tags}, sort_keys=True).encode()).hexdigest()

    async def acknowledge_batch(self, samples: list[dict[str, Any]]) -> None:
        async with self._lock:
            if self._pending is None:
                if samples:
                    raise ValueError("no pending emulation batch")
                return
            if samples is not self._samples:
                raise ValueError("acknowledgement does not match pending batch")
            for sample in samples:
                self._seen[sample["event_id"]] = (
                    datetime.fromisoformat(sample["observed_at"]), self._fingerprint(sample))
            self._observations.update(self._pending_observations)
            if self._previous and self._previous.run_id != self._pending.run_id:
                self._retired_runs.add(self._previous.run_id)
            self._previous = self._pending
            self._pending = None
            self._pending_observations = {}
            self._samples = []

    def derive(self, snapshot: EmulationSnapshot, binding: dict[str, Any],
               previous: EmulationSnapshot | None = None) -> list[dict[str, Any]]:
        samples = []
        old_switches = {s.dpid: s for s in previous.switches} if (
            previous and previous.run_id == snapshot.run_id
        ) else {}

        def emit(device: str, metric: str, value: float, unit: str,
                 observed_at: datetime, method: str, identity: str, **tags: Any) -> None:
            sample_id = f"{binding['network_id']}:{device}:{identity}:{observed_at.isoformat()}:{metric}"
            samples.append({
                "event_id": str(uuid.uuid5(snapshot.run_id, sample_id)),
                "device_id": str(device), "network_id": str(binding["network_id"]),
                "workspace_id": str(binding["workspace_id"]), "metric": metric,
                "value": value, "unit": unit, "source": "emulation",
                "observed_at": observed_at.isoformat(),
                "tags": {"synthetic": False, "execution_mode": "emulation",
                         "run_id": str(snapshot.run_id), "sequence": snapshot.sequence,
                         "topology_id": snapshot.topology_id, "measurement_method": method,
                         "quality": "measured", "freshness": "fresh",
                         "max_age_seconds": self.reader.max_age_seconds, **tags},
            })

        counters = ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets", "rx_dropped", "tx_dropped")
        for switch in snapshot.switches:
            device = binding["switches"][switch.dpid]
            old_switch = old_switches.get(switch.dpid)
            old_ports = {p.port_no: p for p in old_switch.ports} if old_switch else {}
            for port in switch.ports:
                identity = f"port:{switch.dpid}:{port.port_no}:{port.duration_sec}"
                old_port = old_ports.get(port.port_no)
                interval = port.duration_sec - old_port.duration_sec if old_port else 0
                wall_interval = (switch.observed_at - old_switch.observed_at).total_seconds() if old_switch else 0
                valid_rate = (old_port is not None and 0 < interval <= self.reader.max_age_seconds
                              and 0 < wall_interval <= self.reader.max_age_seconds
                              and all(getattr(port, key) >= getattr(old_port, key) for key in counters))
                tags = {"dpid": switch.dpid, "port_no": port.port_no, "duration_sec": port.duration_sec,
                        "rate_quality": "measured" if valid_rate else "unavailable"}
                for key in counters:
                    emit(device, f"port_{key}", getattr(port, key),
                         "bytes" if key.endswith("bytes") else "packets", switch.observed_at,
                         "openflow_port_counter", identity, **tags)
                if valid_rate:
                    # Full-duplex utilization uses the busiest direction, not RX+TX.
                    rx = (port.rx_bytes - old_port.rx_bytes) * 8 / interval / 1e6
                    tx = (port.tx_bytes - old_port.tx_bytes) * 8 / interval / 1e6
                    capacity = binding["port_capacities_mbps"].get(f"{switch.dpid}:{port.port_no}")
                    identity += f":from:{old_switch.observed_at.isoformat()}:{old_port.duration_sec}"
                    tags.update(interval_seconds=interval, direction="max_rx_tx",
                                interval_start=old_switch.observed_at.isoformat(),
                                interval_end=switch.observed_at.isoformat(),
                                duration_start_sec=old_port.duration_sec, duration_end_sec=port.duration_sec,
                                interval_clock="openflow_port_duration")
                    emit(device, "throughput_mbps", max(rx, tx), "Mbps", switch.observed_at,
                         "openflow_port_counter_delta", identity, **tags)
                    if capacity is not None:
                        emit(device, "link_utilization_percent", max(rx, tx) / capacity * 100,
                             "%", switch.observed_at, "openflow_port_counter_delta", identity,
                             capacity_mbps=capacity, **tags)
            # V1 lacks flow match fields: use an ordinal to retain distinct entries
            # sharing table/priority/cookie; never derive per-flow rates from that key.
            for index, flow in enumerate(switch.flows):
                for key, unit in (("packet_count", "packets"), ("byte_count", "bytes")):
                    emit(device, f"flow_{key}", getattr(flow, key), unit, switch.observed_at,
                          "openflow_flow_counter", f"flow:{switch.dpid}:{index}:{flow.table_id}:{flow.priority}:{flow.cookie}", dpid=switch.dpid,
                         table_id=flow.table_id, priority=flow.priority, cookie=str(flow.cookie),
                         flow_index=index, duration_sec=flow.duration_sec)
        for queue in snapshot.queues:
            for key, unit in (("backlog_bytes", "bytes"), ("backlog_packets", "packets")):
                emit(binding["switches"][queue.dpid], f"queue_{key}", getattr(queue, key), unit,
                     queue.observed_at, "linux_qdisc_backlog", f"queue:{queue.dpid}:{queue.port_no}",
                     dpid=queue.dpid, port_no=queue.port_no)
        for probe in snapshot.probes:
            tags = {"peer_host": probe.dst_host, "interval_seconds": probe.interval_seconds,
                    "sent": probe.sent, "received": probe.received, "loss_semantics": "probe"}
            identity = f"probe:{probe.src_host}:{probe.dst_host}"
            emit(binding["hosts"][probe.src_host], "packet_loss_percent",
                 (probe.sent - probe.received) / probe.sent * 100, "%", probe.observed_at,
                 "ping_probe", identity, **tags)
            if probe.rtt_avg_ms is not None:
                emit(binding["hosts"][probe.src_host], "latency_ms", probe.rtt_avg_ms, "ms",
                     probe.observed_at, "ping_rtt", identity, latency_semantics="RTT", **tags)
        return samples
