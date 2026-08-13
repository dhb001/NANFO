"""NANFO Backend — Domain event publisher.

Publishes domain events to Redis Streams (ADR-006, EventAPI.md §2).
All events carry the mandatory envelope: event_id, event_type, timestamp,
source, correlation_id, version, payload.

Naming convention: module.entity.action (EventAPI.md §1).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis

from app.core.logging import get_logger

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
}


async def publish_event(
    *,
    redis: aioredis.Redis,
    event_type: str,
    source: str,
    payload: dict,
    correlation_id: str,
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

    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "source": source,
        "correlation_id": correlation_id,
        "version": version,
        "payload": json.dumps(payload),
    }

    entry_id = await redis.xadd(stream_key, envelope)
    logger.info("event_published", event_type=event_type, stream=stream_key, entry_id=entry_id)
    return entry_id
