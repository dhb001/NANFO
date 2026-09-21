"""Measured sealed-epoch FIFO qualification, explicitly not an FRR installation.

No positive wall-clock service lower bound is assumed on a non-real-time host.
Admission is physically closed (socket closed) before each observation epoch.
Only dequeue and action-selection operations exist during that epoch.
"""

from __future__ import annotations

import hashlib
import itertools
import time
from collections import deque
from pathlib import Path
import socket
from typing import Literal

from pydantic import Field, model_validator

from app.modules.autonomy.artifact_io import ArtifactRef, ArtifactStore, EvidenceError, StrictEvidence, parse_json
from app.modules.simulation.qualification_acquisition import write_new
from app.modules.simulation.qualification_protocol import Name

RUNTIME = "isolated-controlled-sealed-fifo/v1"


class ControlledPlan(StrictEvidence):
    schema_version: Literal["nanfo.controlled-fifo-protocol.v1"]
    environment: Literal["isolated-emulation"]
    runtime: Literal["isolated-controlled-sealed-fifo/v1"]
    network_id: Name
    run_id: Name
    resource_id: Name
    collector_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_at_unix_ns: int = Field(gt=0)
    queue_id: Literal["sealed-application-fifo"]
    demand_id: Literal["owned-loopback-prefill"]
    packet_bytes: int = Field(ge=32, le=1400)
    prefill_packets: int = Field(ge=2, le=100)
    capacity_bytes: int = Field(ge=64, le=140000)
    epoch_ns: int = Field(ge=10000000, le=1000000000)
    transition_after_ns: int = Field(ge=0)
    action_packet_interval_ns: dict[Name, int] = Field(min_length=2, max_length=2)
    # Entire independent socket/queue sessions, immutable before acquisition.
    groups: dict[Literal["train", "holdout"], list[Name]]
    plans: dict[Name, dict]

    @model_validator(mode="after")
    def valid(self):
        if (self.capacity_bytes != self.packet_bytes * self.prefill_packets
                or self.transition_after_ns >= self.epoch_ns
                or any(type(v) is not int or not 1000000 <= v <= 1000000000 for v in self.action_packet_interval_ns.values())
                or set(self.groups) != {"train", "holdout"}):
            raise ValueError("invalid_controlled_fifo_scope")
        actions = sorted(self.action_packet_interval_ns)
        expected = {f"{split}-{old}-{new}": {"previous_action_id": old, "action_id": new,
                    "operation": "set_dequeue_interval", "queue_id": self.queue_id,
                    "packet_interval_ns": self.action_packet_interval_ns[new]}
                    for split in self.groups for old, new in itertools.product(actions, repeat=2)}
        ids = [key for group in self.groups.values() for key in group]
        if (len(ids) != len(set(ids)) or set(ids) != set(expected) or self.plans != expected
                or any(set(values) != {k for k in expected if k.startswith(split + "-")} for split, values in self.groups.items())):
            raise ValueError("controlled_fifo_plan_split_mismatch")
        return self


def source_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def prepare(output: Path, *, network_id: str, run_id: str) -> dict:
    output.mkdir(mode=0o700, exist_ok=False)
    actions = {"slow": 20000000, "fast": 5000000}
    groups, plans = {}, {}
    for split in ("train", "holdout"):
        groups[split] = []
        for old, new in itertools.product(sorted(actions), repeat=2):
            key = f"{split}-{old}-{new}"
            groups[split].append(key)
            plans[key] = dict(previous_action_id=old, action_id=new, operation="set_dequeue_interval",
                              queue_id="sealed-application-fifo", packet_interval_ns=actions[new])
    plan = ControlledPlan.model_validate(dict(
        schema_version="nanfo.controlled-fifo-protocol.v1", environment="isolated-emulation", runtime=RUNTIME,
        network_id=network_id, run_id=run_id, resource_id=output.name, collector_sha256=source_digest(),
        declared_at_unix_ns=time.time_ns(), queue_id="sealed-application-fifo", demand_id="owned-loopback-prefill",
        packet_bytes=128, prefill_packets=16, capacity_bytes=2048, epoch_ns=100000000,
        transition_after_ns=25000000, action_packet_interval_ns=actions, groups=groups, plans=plans,
    ))
    ref = write_new(output / "protocol.json", plan.model_dump(mode="json"))
    return {"protocol": ref.model_dump(), "requires_external_registration": True,
            "physical_qualified": False, "receiver_installable": False}


class SealedFIFO:
    """Single-owner finite queue. After seal there is no enqueue method/path."""

    def __init__(self, packets: list[bytes], capacity: int):
        if not packets or sum(map(len, packets)) > capacity:
            raise EvidenceError("finite_fifo_capacity_violation")
        self._packets = deque(packets)
        self.capacity = capacity
        self.next_service_ns = 0

    @property
    def queue_bytes(self):
        return sum(map(len, self._packets))

    def dequeue(self, now_ns: int, interval_ns: int) -> bytes | None:
        if now_ns < self.next_service_ns or not self._packets:
            return None
        packet = self._packets.popleft()
        self.next_service_ns = now_ns + interval_ns
        return packet


def measure(plan: ControlledPlan, sample_id: str) -> dict:
    mapping = plan.plans[sample_id]
    packets, received = [], []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(1.)
        sender.settimeout(1.)
        for sequence in range(plan.prefill_packets):
            payload = sequence.to_bytes(4, "big") + bytes(plan.packet_bytes - 4)
            sender.sendto(payload, receiver.getsockname())
            packet = receiver.recv(65535)
            if packet != payload:
                raise EvidenceError("owned_prefill_payload_mismatch")
            packets.append(packet)
            received.append(dict(sequence=sequence, bytes=len(packet), sha256=hashlib.sha256(packet).hexdigest(),
                                 received_monotonic_ns=time.monotonic_ns()))
    # Both sockets are closed BEFORE the queue epoch. There is no unknown ingress.
    sealed_ns = time.monotonic_ns()
    fifo = SealedFIFO(packets, plan.capacity_bytes)
    start_wall, start = time.time_ns(), time.monotonic_ns()
    initial = fifo.queue_bytes
    current = mapping["previous_action_id"]
    events = []
    applied = None
    while (now := time.monotonic_ns()) - start < plan.epoch_ns:
        if applied is None and now - start >= plan.transition_after_ns:
            current = mapping["action_id"]
            applied = now
            events.append(dict(kind="action", monotonic_ns=now, action_id=current,
                               packet_interval_ns=plan.action_packet_interval_ns[current]))
        packet = fifo.dequeue(now, plan.action_packet_interval_ns[current])
        if packet is not None:
            events.append(dict(kind="dequeue", monotonic_ns=now, bytes=len(packet),
                               sha256=hashlib.sha256(packet).hexdigest(), action_id=current,
                               queue_after_bytes=fifo.queue_bytes))
        time.sleep(.001)
    end = time.monotonic_ns()
    return dict(schema_version="nanfo.controlled-fifo-window.v1", sample_id=sample_id, runtime=RUNTIME,
                plan=mapping, collector_sha256=plan.collector_sha256, socket_closed_monotonic_ns=sealed_ns,
                start_unix_ns=start_wall, start_monotonic_ns=start, end_monotonic_ns=end,
                prefill=received, events=events, queue_before_bytes=initial, queue_after_bytes=fifo.queue_bytes,
                arrivals_during_epoch_bytes=0, unknown_demand_bytes=0, dropped_bytes=0,
                service_lower_bytes_per_second=0, physical_qualified=False)


def acquire(store: ArtifactStore, protocol: ArtifactRef, *, registered_at_unix_ns: int, output: Path) -> dict:
    plan = ControlledPlan.model_validate(parse_json(store.referenced(protocol)))
    if (type(registered_at_unix_ns) is not int
            or not plan.declared_at_unix_ns <= registered_at_unix_ns < time.time_ns()
            or plan.collector_sha256 != source_digest()):
        raise EvidenceError("controlled_protocol_not_preregistered_or_source_changed")
    output.mkdir(mode=0o700, exist_ok=False)
    write_new(output / "start.json", dict(protocol=protocol.model_dump(), registered_at_unix_ns=registered_at_unix_ns,
                                         started_at_unix_ns=time.time_ns(), physical_qualified=False))
    windows = []
    for split in ("train", "holdout"):
        for key in plan.groups[split]:
            windows.append(write_new(output / f"{key}.json", measure(plan, key)).model_dump())
    manifest = dict(schema_version="nanfo.controlled-fifo-measurements.v1", protocol=protocol.model_dump(),
                    registered_at_unix_ns=registered_at_unix_ns, windows=windows,
                    independent_attestation=None, physical_qualified=False)
    ref = write_new(output / "measurements.json", manifest)
    return dict(manifest=ref.model_dump(), physical_qualified=False, receiver_installable=False)
