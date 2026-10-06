"""NANFO Backend — Domain event publisher.

Publishes domain events to Redis Streams (ADR-006, EventAPI.md §2).
All events carry the mandatory envelope: event_id, event_type, timestamp,
source, correlation_id, version, payload.

Naming convention: module.entity.action (EventAPI.md §1).

Producer admission (ADR-028): durable streams are never trimmed (no MAXLEN), so
Redis memory is the only bound. Before appending, the publisher consults a cached
(<= 5 s) ``INFO memory`` sample and refuses with ``DependencyUnavailableError``
("redis", HTTP 503) once ``used_memory / maxmemory`` reaches
``EVENT_PUBLISH_MAX_MEMORY_RATIO``. The remaining headroom keeps consumers able to
ACK, dead-letter and write completion markers. Unknown/unbounded capacity admits
(an unreachable Redis then fails on XADD with its native error, which HTTP maps to 503).
"""

from __future__ import annotations

import json
import time
import uuid
import weakref
from datetime import UTC, datetime

import redis.asyncio as aioredis

from app.core.errors import DependencyUnavailableError
from app.core.logging import get_logger
from app.events.contracts import SUPPORTED_MAJOR_VERSION, major_version

logger = get_logger(__name__)

# Stream key mapping — one stream per owning module (matches design_package §5.5)
_STREAM_KEYS: dict[str, str] = {
    "auth": "stream:auth",
    "intent": "stream:intent",
    "network": "stream:network",
    "org": "stream:org",
    "telemetry": "stream:telemetry",
    "alert": "stream:alert",
    "simulation": "stream:simulation",
    "plugin": "stream:plugin",
    "report": "stream:report",
}
MEMORY_SAMPLE_TTL_SECONDS = 5.0
_memory_samples: "weakref.WeakKeyDictionary[object, tuple[float, float | None]]" = weakref.WeakKeyDictionary()
_clock = time.monotonic


def _max_memory_ratio() -> float:
    from app.core.config import get_settings

    return get_settings().EVENT_PUBLISH_MAX_MEMORY_RATIO


async def _memory_ratio(redis) -> float | None:
    """used_memory/maxmemory, cached per client; None when unknown or unbounded."""
    now = _clock()
    try:
        sampled_at, ratio = _memory_samples[redis]
        if now - sampled_at < MEMORY_SAMPLE_TTL_SECONDS:
            return ratio
    except (KeyError, TypeError):
        pass
    ratio = None
    try:
        info = await redis.info("memory")
    except Exception:  # noqa: BLE001 - unknown capacity admits; XADD reports real outages
        return None
    if isinstance(info, dict):
        used, maximum = info.get("used_memory"), info.get("maxmemory")
        if isinstance(used, int) and isinstance(maximum, int) and maximum > 0:
            ratio = used / maximum
    try:
        _memory_samples[redis] = (now, ratio)
    except TypeError:
        pass  # Unhashable/unweakrefable test doubles are simply not cached.
    return ratio


async def admit_publication(redis) -> None:
    """Raise DependencyUnavailableError('redis') when Redis memory is near its bound."""
    ratio = await _memory_ratio(redis)
    if ratio is not None and ratio >= _max_memory_ratio():
        logger.warning("event_publish_refused_memory", memory_ratio=round(ratio, 4))
        raise DependencyUnavailableError("redis", retry_after_seconds=10)


async def publish_event(
    *,
    redis: aioredis.Redis,
    event_type: str,
    source: str,
    payload: dict,
    correlation_id: str,
    event_id: str | None = None,
    version: str = "1",
) -> str:
    """Publish a domain event to the appropriate Redis Stream.

    Returns the Redis stream entry ID.
    event_type must follow the module.entity.action convention (EventAPI.md §1).
    All four mandatory fields are set here; callers provide only the payload.
    """
    module = event_type.split(".")[0]
    stream_key = _STREAM_KEYS.get(module)
    if stream_key is None:
        raise ValueError(f"No stream registered for module '{module}'. event_type={event_type!r}")
    if major_version(version) != SUPPORTED_MAJOR_VERSION:
        # Consumers dead-letter unknown majors; never emit one (EventAPI.md §3).
        raise ValueError("Unsupported event envelope version")

    normalized_event_id: str
    if event_id is None:
        normalized_event_id = str(uuid.uuid4())
    else:
        normalized_event_id = str(uuid.UUID(str(event_id)))

    envelope = {
        "event_id": normalized_event_id,
        "event_type": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "source": source,
        "correlation_id": correlation_id,
        "version": version,
        "payload": json.dumps(payload),
    }

    await admit_publication(redis)
    entry_id = await redis.xadd(stream_key, envelope)
    logger.info("event_published", event_type=event_type, stream=stream_key, entry_id=entry_id)
    return entry_id
