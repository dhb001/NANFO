"""Unprivileged loopback acquisition, with real sockets and observed byte queues.

Measures an instrumented application FIFO, NOT kernel qdisc or hardware queues.
There is no device access, routing mutation, privileged subprocess or synthetic
measurement path. Configuration and source identity are preregistered before I/O.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import select
import socket
import time
from collections import deque
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.modules.autonomy.artifact_io import ArtifactRef, ArtifactStore, EvidenceError, StrictEvidence, parse_json
from app.modules.simulation.qualification_protocol import (
    AcquisitionProtocol, InstrumentExport, Name, Positive, RawCapture,
)


class LocalWindow(StrictEvidence):
    sample_id: Name
    previous_action_id: Name
    action_id: Name
    offered_packets: int = Field(ge=1, le=1000)
    packet_bytes: int = Field(ge=32, le=1400)
    dispatch_delay_seconds: float = Field(ge=0, le=1)


class LocalAcquisitionRecipe(StrictEvidence):
    schema_version: Literal["nanfo.loopback-acquisition.v1"]
    collector_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    instrument_id: Name
    egress_id: Name
    demand_id: Name
    queue_kind: Literal["instrumented-application-fifo"]
    dt_seconds: int = Field(ge=1, le=10)
    action_service_packets_per_second: dict[Name, Positive]
    windows: list[LocalWindow] = Field(min_length=4, max_length=1000)

    @model_validator(mode="after")
    def bounded(self):
        if len({w.sample_id for w in self.windows}) != len(self.windows):
            raise ValueError("duplicate_acquisition_window")
        if self.dt_seconds * len(self.windows) > 300:
            raise ValueError("acquisition_duration_exceeds_300_seconds")
        for window in self.windows:
            if (window.action_id not in self.action_service_packets_per_second
                    or window.previous_action_id not in self.action_service_packets_per_second
                    or window.dispatch_delay_seconds >= self.dt_seconds):
                raise ValueError("invalid_acquisition_action_or_delay")
        return self


def write_new(path: Path, value: dict) -> ArtifactRef:
    """Exclusive durable write; caller supplies a new operator-owned directory."""
    content = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with path.open("xb") as target:
        target.write(content)
        target.flush()
        os.fsync(target.fileno())
    return ArtifactRef(path=path.name, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))


def collector_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def measure_window(window: LocalWindow, recipe: LocalAcquisitionRecipe) -> tuple[dict, dict]:
    """Measure native recv/enqueue/dequeue events; preserve loss as incompleteness."""
    pending, events = deque(), []
    arrived = departed = queued_bytes = sent = 0
    payload = bytes(window.packet_bytes)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as source, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sink:
        sink.bind(("127.0.0.1", 0))
        sink.setblocking(False)
        source.settimeout(0.5)
        # Start on the next second, retaining actual wall/monotonic start times.
        scheduled_start = float(math.ceil(time.time()))
        time.sleep(max(0.0, scheduled_start - time.time()))
        start = time.time()
        monotonic_start = time.monotonic()
        current_action = window.previous_action_id
        next_service = monotonic_start
        dispatched = applied = None
        while (elapsed := time.monotonic() - monotonic_start) < recipe.dt_seconds:
            now = time.monotonic()
            if sent < window.offered_packets and elapsed >= sent * recipe.dt_seconds / window.offered_packets:
                source.sendto(payload, sink.getsockname())
                events.append({"event": "send", "elapsed_seconds": elapsed, "bytes": len(payload)})
                sent += 1
            ready, _, _ = select.select([sink], [], [], 0.001)
            if ready:
                packet = sink.recv(65535)
                pending.append(len(packet))
                queued_bytes += len(packet)
                arrived += len(packet)
                events.append({"event": "enqueue", "elapsed_seconds": time.monotonic() - monotonic_start, "bytes": len(packet)})
            elapsed = time.monotonic() - monotonic_start
            if applied is None and elapsed >= window.dispatch_delay_seconds:
                dispatched = start + elapsed
                current_action = window.action_id
                applied = start + (time.monotonic() - monotonic_start)
                events.append({"event": "action_applied", "elapsed_seconds": applied - start, "action_id": current_action})
            if pending and now >= next_service:
                count = pending.popleft()
                queued_bytes -= count
                departed += count
                events.append({"event": "dequeue", "elapsed_seconds": time.monotonic() - monotonic_start, "bytes": count})
                next_service = time.monotonic() + 1 / recipe.action_service_packets_per_second[current_action]
        actual_end = time.monotonic() - monotonic_start
    # Endpoint timing uncertainty is retained, never claimed as synchronized kernel
    # telemetry. Qualification still requires operator-reviewed error/guarantee evidence.
    complete = sent == window.offered_packets and arrived == sent * window.packet_bytes and applied is not None
    reading = {
        "action_id": window.action_id, "previous_action_id": window.previous_action_id,
        "start_unix_seconds": start, "end_unix_seconds": start + actual_end,
        "dispatch_unix_seconds": dispatched if dispatched is not None else start + recipe.dt_seconds,
        "applied_unix_seconds": applied if applied is not None else start + recipe.dt_seconds,
        "transition_complete_unix_seconds": applied if applied is not None else start + recipe.dt_seconds,
        "queue_units": "bytes", "rate_units": "bytes/second", "time_units": "unix-seconds",
        "measurement_complete": complete, "attribution_complete": True, "counter_reset": False,
        "unknown_demand_ids": [],
        "queues": [{"egress_id": recipe.egress_id, "queue_before_bytes": 0.0,
                    "queue_after_bytes": float(queued_bytes),
                    "arrivals": {"before": 0, "after": arrived},
                    "departures": {"before": 0, "after": departed},
                    "drops": {"before": 0, "after": 0},
                    "demand_arrivals": {recipe.demand_id: {"before": 0, "after": arrived}},
                    "unknown_arrival_bytes": 0, "measurement_error_bytes": 0.0}],
    }
    native = {"schema_version": "nanfo.loopback-events.v1", "queue_kind": recipe.queue_kind,
              "collector_sha256": collector_digest(), "start_unix_seconds": start,
              "actual_elapsed_seconds": actual_end, "events": events,
              "physical_qualified": False, "kernel_queue_measured": False}
    return reading, native


def acquire_local(
    store: ArtifactStore, protocol_ref: ArtifactRef, *, output: Path,
    registered_at: float, expected_protocol_sha256: str,
) -> list[ArtifactRef]:
    protocol = AcquisitionProtocol.model_validate(parse_json(store.referenced(protocol_ref)))
    if (protocol_ref.sha256 != expected_protocol_sha256 or protocol.domain != "network"
            or protocol.environment != "isolated-emulation" or protocol.acquisition_recipe is None
            or not protocol.declared_at_unix_seconds <= registered_at < time.time()):
        raise EvidenceError("local_acquisition_requires_preregistered_emulation_protocol")
    recipe = LocalAcquisitionRecipe.model_validate(parse_json(store.referenced(protocol.acquisition_recipe)))
    if recipe.collector_sha256 != collector_digest() or recipe.instrument_id not in protocol.instrument_ids:
        raise EvidenceError("acquisition_collector_identity_mismatch")
    expected = {key for group in protocol.groups for key in group.sample_ids}
    if {w.sample_id for w in recipe.windows} != expected:
        raise EvidenceError("acquisition_recipe_sample_scope_mismatch")
    # Existing parent required; never touch a shared or pre-existing campaign.
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    write_new(output / "acquisition-start.json", {
        "protocol_sha256": protocol_ref.sha256, "registered_at": registered_at,
        "started_at": time.time(), "collector_sha256": collector_digest(),
        "environment": "isolated-emulation", "physical_qualified": False,
    })
    windows = {w.sample_id: w for w in recipe.windows}
    captures = []
    for group in protocol.groups:
        records, native_refs, exports = [], [], []
        for sample_id in group.sample_ids:
            reading, native = measure_window(windows[sample_id], recipe)
            native_refs.append(write_new(output / f"{sample_id}.events.json", native))
            row = {"source_record_id": sample_id, "observed_at_unix_seconds": reading["start_unix_seconds"], "measurement": reading}
            exports.append(row)
            records.append({**row, "sample_id": sample_id, "instrument_id": recipe.instrument_id})
        instrument = InstrumentExport.model_validate({"schema_version": "nanfo.instrument-records.v1",
                                                      "instrument_id": recipe.instrument_id, "records": exports})
        native_refs.append(write_new(output / f"{group.group_id}.instrument.json", instrument.model_dump(mode="json")))
        capture = RawCapture.model_validate({
            "schema_version": "nanfo.raw-capture.v1", "protocol_sha256": protocol_ref.sha256,
            "dataset_id": protocol.dataset_id, "group_id": group.group_id,
            "environment": protocol.environment,
            "native_sources": [r.model_dump() for r in native_refs], "records": records,
        })
        captures.append(write_new(output / f"{group.group_id}.capture.json", capture.model_dump(mode="json")))
    write_new(output / "acquisition-complete.json", {"completed_at": time.time(),
              "captures": [r.model_dump() for r in captures], "physical_qualified": False,
              "requires_operator_attestation": True})
    return captures


def verify_native_events(native: dict, reading: dict) -> None:
    """Replay real acquisition events without using the acquisition's counters."""
    from app.modules.autonomy.calibration_verification_models import NetworkReading

    measured = NetworkReading.model_validate(reading)
    if (native.get("schema_version") != "nanfo.loopback-events.v1"
            or native.get("queue_kind") != "instrumented-application-fifo"
            or native.get("physical_qualified") is not False
            or native.get("kernel_queue_measured") is not False
            or native.get("start_unix_seconds") != measured.start_unix_seconds
            or measured.start_unix_seconds + native.get("actual_elapsed_seconds", -1) != measured.end_unix_seconds
            or len(measured.queues) != 1):
        raise EvidenceError("native_acquisition_scope_mismatch")
    queue, sent, arrived, served, applied, last = deque(), 0, 0, 0, [], 0.
    events = native.get("events")
    if not isinstance(events, list) or len(events) > 40000:
        raise EvidenceError("native_acquisition_event_limit")
    for event in events:
        elapsed = event.get("elapsed_seconds")
        if (type(elapsed) not in (int, float)
                or not last <= elapsed <= native["actual_elapsed_seconds"]):
            raise EvidenceError("native_event_time_mismatch")
        last = elapsed
        kind = event.get("event")
        if kind == "action_applied":
            if event.get("action_id") != measured.action_id:
                raise EvidenceError("native_action_mismatch")
            applied.append(measured.start_unix_seconds + elapsed)
            continue
        count = event.get("bytes")
        if type(count) is not int or not 1 <= count <= 65535:
            raise EvidenceError("native_event_bytes_invalid")
        if kind == "send":
            sent += count
        elif kind == "enqueue":
            queue.append(count)
            arrived += count
        elif kind == "dequeue":
            if not queue or queue.popleft() != count:
                raise EvidenceError("native_fifo_conservation_failed")
            served += count
        else:
            raise EvidenceError("native_event_unknown")
    q = measured.queues[0]
    if (q.queue_before_bytes != 0 or q.queue_after_bytes != sum(queue)
            or q.arrivals.delta != arrived or q.departures.delta != served or q.drops.delta != 0
            or applied != [measured.applied_unix_seconds]
            or measured.transition_complete_unix_seconds != measured.applied_unix_seconds
            or (measured.measurement_complete and sent != arrived)):
        raise EvidenceError("native_acquisition_counter_mismatch")


def prepare_local(output: Path, *, network_id: str, run_id: str) -> dict:
    """Create a NEW preregistration candidate, not a trusted receipt or measurement.

    Broad no-service diagnostic bounds are declared before acquisition. They are
    illustrative empirical checks for a tiny application FIFO, not enforced caps.
    """
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    actions = ["slow", "fast"]
    windows = []
    groups = []
    for split in ("train", "holdout"):
        ids = []
        for old, new in (("slow", "slow"), ("slow", "fast"), ("fast", "slow"), ("fast", "fast")):
            name = f"{split}-{old}-{new}"
            ids.append(name)
            windows.append(dict(sample_id=name, previous_action_id=old, action_id=new,
                                offered_packets=20, packet_bytes=128, dispatch_delay_seconds=0.1))
        groups.append(dict(group_id=split, split=split, sample_ids=ids))
    recipe = LocalAcquisitionRecipe.model_validate(dict(
        schema_version="nanfo.loopback-acquisition.v1", collector_sha256=collector_digest(),
        instrument_id="loopback-fifo-v1", egress_id="application-fifo", demand_id="loopback-demand",
        queue_kind="instrumented-application-fifo", dt_seconds=1,
        action_service_packets_per_second={"slow": 10., "fast": 40.}, windows=windows,
    ))
    recipe_ref = write_new(output / "recipe.json", recipe.model_dump(mode="json"))
    config = dict(
        schema_version="nanfo.network-qualification-config.v1", provider_id="loopback-fifo-v1",
        egress_ids=[recipe.egress_id], demand_ids=[recipe.demand_id],
        actions=[dict(action_id=action, demand_egress_ids={recipe.demand_id: [recipe.egress_id]},
                      bounds=[dict(egress_id=recipe.egress_id, capacity_bytes_per_second=1e6,
                                   arrival_upper_bytes_per_second=3000., service_lower_bytes_per_second=0.,
                                   service_upper_bytes_per_second=1e6, error_upper_bytes=128.)]) for action in actions],
        queue_units="bytes", rate_units="bytes/second", time_units="unix-seconds",
        dt_seconds=1.1, max_delay_seconds=0.5, queue_threshold_bytes=10000.,
        drift_budget_bytes_squared=1e8, min_samples_per_action_per_split=2,
        required_transitions=[[old, new] for old in actions for new in actions],
    )
    config_ref = write_new(output / "configuration.json", config)
    protocol = AcquisitionProtocol.model_validate(dict(
        schema_version="nanfo.independent-protocol.v1", campaign_id=output.name,
        dataset_id=output.name, domain="network", environment="isolated-emulation",
        network_id=network_id, run_id=run_id, declared_at_unix_seconds=time.time(),
        configuration=config_ref.model_dump(), acquisition_recipe=recipe_ref.model_dump(),
        group_basis="Separate socket sessions by capture group on the same local host; no hardware independence claimed.",
        groups=groups, instrument_ids=[recipe.instrument_id],
    ))
    ref = write_new(output / "protocol.json", protocol.model_dump(mode="json"))
    return {"protocol": ref.model_dump(), "requires_external_preregistration": True,
            "requires_operator_attestation_after_capture": True, "physical_qualified": False}
