"""Operational health counters for telemetry pipeline (VS2 Step 8)."""

from __future__ import annotations

import redis.asyncio as aioredis

COUNTER_INGESTED_EVENTS = "telemetry:health:ingested_events"
COUNTER_PERSISTED_EVENTS = "telemetry:health:persisted_events"
COUNTER_FANOUT_EVENTS = "telemetry:health:fanout_events"
COUNTER_DROPPED_EVENTS = "telemetry:health:dropped_events"


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

    async def get_snapshot(self) -> dict[str, int]:
        ingested, persisted, fanout, dropped = await self._redis.mget(
            COUNTER_INGESTED_EVENTS,
            COUNTER_PERSISTED_EVENTS,
            COUNTER_FANOUT_EVENTS,
            COUNTER_DROPPED_EVENTS,
        )
        return {
            "ingested_events": self._to_int(ingested),
            "persisted_events": self._to_int(persisted),
            "fanout_events": self._to_int(fanout),
            "dropped_events": self._to_int(dropped),
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
