"""NANFO Backend — Event bus background consumer runner.

Reads from Redis Streams in a background asyncio task.
Per ADR-006 and EventAPI.md §4:
  - At-least-once delivery via consumer groups
  - Consumers must ACK after successful processing
  - Duplicate event_id must be discarded (idempotency)
  - Dead-letter queue for repeated failures
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import redis.asyncio as aioredis
from redis.exceptions import RedisError, ResponseError

from app.core.logging import get_logger

logger = get_logger(__name__)

# Stream → consumer group mappings
STREAM_GROUPS: dict[str, str] = {
    "stream:auth": "nanfo-consumers",
    "stream:intent": "nanfo-consumers",
    "stream:network": "nanfo-consumers",
    "stream:org": "nanfo-consumers",
    "stream:telemetry": "nanfo-consumers",
    "stream:alert": "nanfo-consumers",
    "stream:simulation": "nanfo-consumers",
    "stream:plugin": "nanfo-consumers",
    "stream:report": "nanfo-consumers",
}


async def ensure_consumer_groups(redis: aioredis.Redis) -> None:
    """Create consumer groups if they don't exist. Safe to call multiple times."""
    for stream_key, group in STREAM_GROUPS.items():
        try:
            await redis.xgroup_create(stream_key, group, id="0", mkstream=True)
            logger.info("consumer_group_created", stream=stream_key, group=group)
        except ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                continue
            logger.warning("consumer_group_create_failed", stream=stream_key, error=str(exc))
        except RedisError as exc:
            logger.warning("consumer_group_create_failed", stream=stream_key, error=str(exc))


EventHandler = Callable[[dict], Awaitable[None]]


async def run_consumer_loop(
    redis: aioredis.Redis,
    stream_key: str,
    group: str,
    consumer_name: str,
    handlers: dict[str, EventHandler],
    dead_letter_key: str = "stream:dead_letter",
    max_retries: int = 3,
) -> None:
    """Continuously read events from a Redis Stream and dispatch to handlers.

    Per EventAPI.md §4: ACK on success, dead-letter on repeated failure.
    Idempotency: duplicate event_id is discarded via Redis SET NX.
    """
    while True:
        try:
            messages = await redis.xreadgroup(
                groupname=group,
                consumername=consumer_name,
                streams={stream_key: ">"},
                count=10,
                block=2000,
            )
            if not messages:
                continue

            for _, entries in messages:
                for entry_id, fields in entries:
                    event_type = fields.get("event_type", "")
                    event_id = fields.get("event_id", "")

                    # Idempotency check (EventAPI.md §4)
                    dedup_key = f"event:seen:{event_id}"
                    already_seen = await redis.set(dedup_key, "1", nx=True, ex=3600)
                    if not already_seen:
                        logger.info("event_duplicate_discarded", event_id=event_id, event_type=event_type)
                        await redis.xack(stream_key, group, entry_id)
                        continue

                    handler = handlers.get(event_type)
                    if handler is None:
                        logger.debug("event_no_handler", event_type=event_type)
                        await redis.xack(stream_key, group, entry_id)
                        continue

                    payload = json.loads(fields.get("payload", "{}"))
                    event_data = {**fields, "payload": payload}

                    success = False
                    for attempt in range(1, max_retries + 1):
                        try:
                            await handler(event_data)
                            success = True
                            break
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "event_handler_failed",
                                event_type=event_type,
                                attempt=attempt,
                                error=str(exc),
                            )
                            await asyncio.sleep(attempt * 0.5)

                    if success:
                        await redis.xack(stream_key, group, entry_id)
                    else:
                        # Dead-letter (EventAPI.md §4)
                        await redis.xadd(dead_letter_key, {**fields, "failed_entry_id": entry_id})
                        await redis.xack(stream_key, group, entry_id)
                        logger.error("event_dead_lettered", event_type=event_type, entry_id=entry_id)

        except asyncio.CancelledError:
            logger.info("consumer_loop_cancelled", stream=stream_key)
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("consumer_loop_error", stream=stream_key, error=str(exc))
            await asyncio.sleep(1)
