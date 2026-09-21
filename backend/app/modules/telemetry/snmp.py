"""ADR021 measured SNMP adapter and guarded owning-service publication."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.modules.telemetry.service import RuntimeTelemetryAdapter, TelemetryIngestionService
from app.modules.telemetry.snmp_config import InterfaceBinding, SNMPBinding, SNMPError
from app.modules.telemetry.snmp_transport import IF_COLUMNS, InterfaceCounters


class CounterTransport(Protocol):
    async def get(self, binding: SNMPBinding, interface: InterfaceBinding) -> InterfaceCounters: ...


@dataclass(frozen=True)
class Observation:
    counters: InterfaceCounters
    observed_at: datetime
    monotonic_seconds: float
    request_seconds: float


def counter_rates(current: Observation, previous: Observation | None, max_interval: float) -> tuple[str, float | None, tuple[float, float] | None]:
    """Return explicit unavailable reasons; never clamp/reset-fill measurements.

    Counter64 and TimeTicks modular arithmetic is safe only when the elapsed
    interval/capacity makes multiple wraps impossible. Reboot/discontinuity/speed
    transitions establish a new baseline rather than a rate across the transition.
    """
    if previous is None:
        return "baseline", None, None
    now, old = current.counters, previous.counters
    elapsed = current.monotonic_seconds - previous.monotonic_seconds
    interval = ((now.uptime - old.uptime) % 2**32) / 100
    if now.engine_boots != old.engine_boots or now.engine_boots == 2**31 - 1:
        return "agent_restart", None, None
    if now.discontinuity != old.discontinuity:
        return "counter_discontinuity", None, None
    if not 0 < elapsed <= max_interval or not 0 < interval <= max_interval:
        return "interval_unavailable", None, None
    if abs(interval - elapsed) > max(1.0, current.request_seconds + previous.request_seconds, elapsed * 0.05):
        return "agent_clock_discontinuity", None, None
    if now.speed_bps <= 0:
        return "speed_unavailable", interval, None
    if now.speed_bps != old.speed_bps:
        return "speed_changed", interval, None
    capacity_bytes = now.speed_bps * interval / 8
    if capacity_bytes >= 2**64:
        return "ambiguous_counter_wrap", interval, None
    deltas = ((now.rx - old.rx) % 2**64, (now.tx - old.tx) % 2**64)
    if any(delta > capacity_bytes for delta in deltas):
        return "counter_reset_or_capacity_exceeded", interval, None
    return ("measured_wrap" if now.rx < old.rx or now.tx < old.tx else "measured",
            interval, (deltas[0] * 8 / interval, deltas[1] * 8 / interval))


class MeasuredSNMPAdapter(RuntimeTelemetryAdapter):
    """One bounded device; pending batches replay stable IDs until acknowledged.

    authorize must re-read the pinned binding and check current owner authority,
    using a fresh session. Publication additionally checks write authority before
    each sample. The in-memory checkpoint is deliberately not a durable outbox.
    """

    def __init__(self, *, binding: SNMPBinding, transport: CounterTransport,
                 authorize: Callable[[SNMPBinding, bool], Awaitable[None]],
                 monotonic: Callable[[], float] = time.monotonic,
                 utcnow: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.binding = binding
        self.transport = transport
        self.authorize = authorize
        self.monotonic = monotonic
        self.utcnow = utcnow
        self._previous: dict[int, Observation] = {}
        self._pending: dict[int, Observation] | None = None
        self._samples: list[dict[str, Any]] = []
        self._pending_since = 0.0
        self._lock = asyncio.Lock()
        self._publish_lock = asyncio.Lock()
        self._binding_digest = hashlib.sha256(binding.model_dump_json().encode()).hexdigest()

    def _check_fresh(self) -> None:
        if self._pending is not None and self.monotonic() - self._pending_since > self.binding.max_pending_seconds:
            raise SNMPError("pending_batch_expired_operator_recovery_required")

    async def poll(self) -> list[dict[str, Any]]:
        async with self._lock:
            await self.authorize(self.binding, False)
            self._check_fresh()
            if self._pending is not None:
                return copy.deepcopy(self._samples)
            observations = {}
            samples = []
            for interface in self.binding.interfaces:
                # A revocation during the preceding GET must prevent the next
                # external read, even though this batch has not been published.
                await self.authorize(self.binding, False)
                started = self.monotonic()
                counters = await self.transport.get(self.binding, interface)
                ended = self.monotonic()
                observation = Observation(counters, self.utcnow(), ended, ended - started)
                observations[interface.if_index] = observation
                samples.extend(self._derive(interface, observation))
            # Membership can change while requests are outstanding.
            await self.authorize(self.binding, False)
            self._pending = observations
            self._samples = samples
            self._pending_since = min(o.monotonic_seconds for o in observations.values())
            self._check_fresh()
            return copy.deepcopy(samples)

    def _derive(self, interface: InterfaceBinding, observation: Observation) -> list[dict[str, Any]]:
        previous = self._previous.get(interface.if_index)
        quality, interval, rates = counter_rates(observation, previous, self.binding.max_interval_seconds)
        counter = observation.counters
        tags = {
            "adapter_mode": "measured_snmp", "synthetic": False, "quality": "measured",
            "execution_mode": self.binding.execution_mode, "environment": self.binding.environment,
            "protocol": "SNMPv3", "security_level": "authPriv", "org_id": str(self.binding.org_id),
            "actor_user_id": str(self.binding.actor_user_id), "binding_sha256": self._binding_digest,
            "if_index": interface.if_index, "if_name": interface.if_name,
            # Existing history aggregation groups by port_no, not arbitrary tags.
            "port_no": str(interface.if_index), "interface_identity_source": "operator_binding_and_if_mib",
            "sys_uptime_ticks": counter.uptime, "engine_boots": counter.engine_boots,
            "counter_discontinuity_ticks": counter.discontinuity, "counter_bits": 64,
            "rate_quality": quality, "capacity_bps": counter.speed_bps,
            "capacity_oid": counter.speed_oid, "request_seconds": observation.request_seconds,
            "interval_clock": "sysUpTime_centiseconds_checked_against_monotonic",
            "max_age_seconds": self.binding.max_pending_seconds,
        }
        result = []
        batch_id = uuid.uuid4()

        def emit(metric, value, unit, method, **extra):
            result.append({
                "event_id": str(uuid.uuid5(batch_id, metric)),
                "device_id": str(self.binding.device_id), "network_id": str(self.binding.network_id),
                "workspace_id": str(self.binding.workspace_id), "metric": metric, "value": value,
                "unit": unit, "source": "measured_snmp", "observed_at": observation.observed_at.isoformat(),
                "tags": {**tags, "measurement_method": method, **extra},
            })

        for direction, value in (("rx", counter.rx), ("tx", counter.tx)):
            emit(f"port_{direction}_bytes", value, "bytes", "snmp_ifHC_octets",
                 oid=f"{IF_COLUMNS[direction][0]}.{interface.if_index}", counter_decimal=str(value))
        emit("interface_speed_bps", counter.speed_bps, "bps", "snmp_if_speed", oid=counter.speed_oid)
        if rates is not None:
            interval_tags = {"interval_seconds": interval, "interval_start": previous.observed_at.isoformat(),
                             "interval_end": observation.observed_at.isoformat(),
                             "rx_counter_start_decimal": str(previous.counters.rx),
                             "tx_counter_start_decimal": str(previous.counters.tx),
                             "rx_counter_end_decimal": str(counter.rx), "tx_counter_end_decimal": str(counter.tx)}
            for direction, value in zip(("rx", "tx"), rates, strict=True):
                emit(f"port_{direction}_bps", value, "bps", "snmp_ifHC_octet_delta", direction=direction, **interval_tags)
            emit("throughput_mbps", max(rates) / 1e6, "Mbps", "snmp_ifHC_octet_delta", direction="max_rx_tx", **interval_tags)
            emit("link_utilization_percent", max(rates) / counter.speed_bps * 100, "%",
                 "snmp_ifHC_octet_delta", direction="max_rx_tx", **interval_tags)
        return result

    async def acknowledge_batch(self, samples: list[dict[str, Any]]) -> None:
        async with self._lock:
            if self._pending is None or samples != self._samples:
                raise SNMPError("acknowledgement_mismatch")
            self._previous = self._pending
            self._pending = None
            self._samples = []

    async def collect_and_publish(self, ingestion: TelemetryIngestionService) -> int:
        """Use this guarded action rather than the generic runtime poll action."""
        async with self._publish_lock:
            await self.authorize(self.binding, True)
            samples = await self.poll()
            for sample in samples:
                await self.authorize(self.binding, True)
                self._check_fresh()
                await ingestion.ingest(raw=sample, correlation_id=str(uuid.uuid4()), event_id=sample["event_id"])
            await self.acknowledge_batch(samples)
            return len(samples)
