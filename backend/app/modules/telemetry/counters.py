"""Operational health counters for telemetry pipeline (VS2 Step 8)."""

from __future__ import annotations

import redis.asyncio as aioredis

COUNTER_INGESTED_EVENTS = "telemetry:health:ingested_events"
COUNTER_PERSISTED_EVENTS = "telemetry:health:persisted_events"
COUNTER_FANOUT_EVENTS = "telemetry:health:fanout_events"
COUNTER_DROPPED_EVENTS = "telemetry:health:dropped_events"
COUNTER_RUNTIME_EXHAUSTED_CYCLES = "telemetry:health:runtime_exhausted_cycles"
COUNTER_RUNTIME_EXHAUSTED_STREAK = "telemetry:health:runtime_exhausted_streak"
COUNTER_RUNTIME_SUSTAINED_FAILURE_WINDOWS = "telemetry:health:runtime_sustained_failure_windows"
COUNTER_RUNTIME_SUSTAINED_FAILURE_ACTIVE = "telemetry:health:runtime_sustained_failure_active"
COUNTER_RUNTIME_ADAPTER_LAST_BATCH_SIZE = "telemetry:health:runtime_adapter_last_batch_size"
COUNTER_RUNTIME_ADAPTER_INVALID_SAMPLES = "telemetry:health:runtime_adapter_invalid_samples"
COUNTER_RUNTIME_ADAPTER_INGEST_ATTEMPTS = "telemetry:health:runtime_adapter_ingest_attempts"
COUNTER_RUNTIME_ADAPTER_INGEST_FAILURES = "telemetry:health:runtime_adapter_ingest_failures"
COUNTER_RUNTIME_ADAPTER_ANOMALY_STREAK = "telemetry:health:runtime_adapter_anomaly_streak"


class TelemetryHealthCounterService:
    """Redis-backed operational counters for telemetry health visibility."""

    def __init__(self, redis: aioredis.Redis):
        self._redis = redis

    async def increment_ingested(self) -> int:
        return int(await self._redis.incr(COUNTER_INGESTED_EVENTS))

    async def increment_persisted(self) -> int:
        return int(await self._redis.incr(COUNTER_PERSISTED_EVENTS))

    async def increment_fanout(self) -> int:
        return int(await self._redis.incr(COUNTER_FANOUT_EVENTS))

    async def increment_dropped(self) -> int:
        return int(await self._redis.incr(COUNTER_DROPPED_EVENTS))

    async def increment_runtime_exhausted_cycle(self) -> int:
        return int(await self._redis.incr(COUNTER_RUNTIME_EXHAUSTED_CYCLES))

    async def set_runtime_exhausted_streak(self, streak: int) -> int:
        value = max(0, int(streak))
        await self._redis.set(COUNTER_RUNTIME_EXHAUSTED_STREAK, value)
        return value

    async def increment_runtime_sustained_failure_window(self) -> int:
        return int(await self._redis.incr(COUNTER_RUNTIME_SUSTAINED_FAILURE_WINDOWS))

    async def set_runtime_sustained_failure_active(self, active: bool) -> int:
        value = 1 if active else 0
        await self._redis.set(COUNTER_RUNTIME_SUSTAINED_FAILURE_ACTIVE, value)
        return value

    async def set_runtime_adapter_last_batch_size(self, batch_size: int) -> int:
        value = max(0, int(batch_size))
        await self._redis.set(COUNTER_RUNTIME_ADAPTER_LAST_BATCH_SIZE, value)
        return value

    async def increment_runtime_adapter_invalid_sample(self) -> int:
        return int(await self._redis.incr(COUNTER_RUNTIME_ADAPTER_INVALID_SAMPLES))

    async def increment_runtime_adapter_ingest_attempt(self) -> int:
        return int(await self._redis.incr(COUNTER_RUNTIME_ADAPTER_INGEST_ATTEMPTS))

    async def increment_runtime_adapter_ingest_failure(self) -> int:
        return int(await self._redis.incr(COUNTER_RUNTIME_ADAPTER_INGEST_FAILURES))

    async def set_runtime_adapter_anomaly_streak(self, streak: int) -> int:
        value = max(0, int(streak))
        await self._redis.set(COUNTER_RUNTIME_ADAPTER_ANOMALY_STREAK, value)
        return value

    async def get_snapshot(self) -> dict[str, int]:
        (
            ingested,
            persisted,
            fanout,
            dropped,
            runtime_exhausted_cycles,
            runtime_exhausted_streak,
            runtime_sustained_failure_windows,
            runtime_sustained_failure_active,
            runtime_adapter_last_batch_size,
            runtime_adapter_invalid_samples,
            runtime_adapter_ingest_attempts,
            runtime_adapter_ingest_failures,
            runtime_adapter_anomaly_streak,
        ) = await self._redis.mget(
            COUNTER_INGESTED_EVENTS,
            COUNTER_PERSISTED_EVENTS,
            COUNTER_FANOUT_EVENTS,
            COUNTER_DROPPED_EVENTS,
            COUNTER_RUNTIME_EXHAUSTED_CYCLES,
            COUNTER_RUNTIME_EXHAUSTED_STREAK,
            COUNTER_RUNTIME_SUSTAINED_FAILURE_WINDOWS,
            COUNTER_RUNTIME_SUSTAINED_FAILURE_ACTIVE,
            COUNTER_RUNTIME_ADAPTER_LAST_BATCH_SIZE,
            COUNTER_RUNTIME_ADAPTER_INVALID_SAMPLES,
            COUNTER_RUNTIME_ADAPTER_INGEST_ATTEMPTS,
            COUNTER_RUNTIME_ADAPTER_INGEST_FAILURES,
            COUNTER_RUNTIME_ADAPTER_ANOMALY_STREAK,
        )
        return {
            "ingested_events": self._to_int(ingested),
            "persisted_events": self._to_int(persisted),
            "fanout_events": self._to_int(fanout),
            "dropped_events": self._to_int(dropped),
            "runtime_exhausted_cycles": self._to_int(runtime_exhausted_cycles),
            "runtime_exhausted_streak": self._to_int(runtime_exhausted_streak),
            "runtime_sustained_failure_windows": self._to_int(runtime_sustained_failure_windows),
            "runtime_sustained_failure_active": self._to_int(runtime_sustained_failure_active),
            "runtime_adapter_last_batch_size": self._to_int(runtime_adapter_last_batch_size),
            "runtime_adapter_invalid_samples": self._to_int(runtime_adapter_invalid_samples),
            "runtime_adapter_ingest_attempts": self._to_int(runtime_adapter_ingest_attempts),
            "runtime_adapter_ingest_failures": self._to_int(runtime_adapter_ingest_failures),
            "runtime_adapter_anomaly_streak": self._to_int(runtime_adapter_anomaly_streak),
        }

    @staticmethod
    def _to_int(raw: str | bytes | int | None) -> int:
        if raw is None:
            return 0
        if isinstance(raw, int):
            return raw
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
