"""At-least-once Redis Streams delivery with bounded pending recovery (ADR-010)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Sequence

import redis.asyncio as aioredis
from redis.client import NEVER_DECODE
from redis.exceptions import ResponseError

from app.core.logging import get_logger

logger = get_logger(__name__)

STREAM_GROUPS = {
    f"stream:{module}": "nanfo-consumers"
    for module in ("auth", "intent", "network", "org", "telemetry", "alert", "simulation", "plugin", "report")
}
EventHandler = Callable[[dict], Awaitable[None]]


async def ensure_consumer_groups(redis: aioredis.Redis) -> None:
    """Provision groups; infrastructure failure must prevent partial startup."""
    for stream_key, group in STREAM_GROUPS.items():
        try:
            await redis.xgroup_create(stream_key, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise


def completion_key(stream: str, group: str, event_id: str, handler: EventHandler) -> str:
    identity = json.dumps([stream, group, event_id, handler.__module__, handler.__qualname__])
    return "event:completed:" + hashlib.sha256(identity.encode()).hexdigest()


async def process_entry(
    redis: aioredis.Redis,
    stream_key: str,
    group: str,
    entry_id: str,
    fields: dict,
    handlers: dict[str, EventHandler | Sequence[EventHandler]],
    *,
    dead_letter_key: str = "stream:dead_letter",
    max_retries: int = 3,
    completion_ttl_seconds: int = 86400,
    handler_timeout_seconds: float = 30,
) -> None:
    """ACK only successful handlers or a confirmed, untrimmed DLQ append.

    Completion is an optimization, not a transaction with the side effect. Owning
    modules must protect durable effects against the commit-to-marker crash window.
    """
    reason = ""
    try:
        fields = {
            key.decode() if isinstance(key, bytes) else key:
            value.decode() if isinstance(value, bytes) else value
            for key, value in fields.items()
        }
        event_id = str(uuid.UUID(fields["event_id"]))
        event_type = fields["event_type"]
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("Missing event type")
        payload = json.loads(fields["payload"])
        if not isinstance(payload, dict):
            raise TypeError("Payload must be an object")
    except (ValueError, TypeError, KeyError, UnicodeError):
        reason = "malformed_envelope"
    else:
        registered = handlers.get(event_type, ())
        selected = (registered,) if callable(registered) else registered
        event = {**fields, "event_id": event_id, "payload": payload}
        for handler in selected:
            key = completion_key(stream_key, group, event_id, handler)
            if await redis.exists(key):
                continue
            for attempt in range(1, max_retries + 1):
                try:
                    async with asyncio.timeout(handler_timeout_seconds):
                        await handler(event)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("event_handler_failed", event_id=event_id,
                                   handler=handler.__qualname__, attempt=attempt,
                                   error_type=type(exc).__name__)
                    if attempt == max_retries:
                        reason = "handler_retries_exhausted"
                        break
                    await asyncio.sleep(attempt * 0.5)
                else:
                    # Never consult legacy event:seen keys, or mark before success.
                    await redis.set(key, "1", ex=completion_ttl_seconds)
                    break
            if reason:
                break

    if reason:
        # Keep original bytes, even for invalid UTF-8 poison. No MAXLEN truncation.
        await redis.xadd(dead_letter_key, {
            **fields, "failed_entry_id": entry_id, "failed_stream": stream_key,
            "failed_group": group, "failure_reason": reason,
        })
        logger.error("event_dead_lettered", stream=stream_key, entry_id=entry_id, reason=reason)
    # Unknown, well-formed events retain the existing ACK-and-ignore behavior.
    await redis.xack(stream_key, group, entry_id)


async def run_consumer_loop(
    redis: aioredis.Redis,
    stream_key: str,
    group: str,
    consumer_name: str,
    handlers: dict[str, EventHandler | Sequence[EventHandler]],
    dead_letter_key: str = "stream:dead_letter",
    max_retries: int = 3,
    *,
    reclaim_idle_ms: int = 60000,
    batch_size: int = 10,
    completion_ttl_seconds: int = 86400,
    handler_timeout_seconds: float = 30,
) -> None:
    """One XAUTOCLAIM page per round, then new entries, without draining the PEL."""
    if not 1 <= batch_size <= 100 or reclaim_idle_ms <= 0 or max_retries < 1:
        raise ValueError("Invalid consumer recovery bounds")
    # Unique across restarts, even if a caller reuses its descriptive prefix.
    consumer_name = f"{consumer_name}-{uuid.uuid4().hex}"
    cursor = "0-0"
    while True:
        try:
            # Decode inside process_entry: one invalid UTF-8 field must not make
            # redis-py discard the entire response before poison can reach DLQ.
            claimed = await redis.execute_command(
                "XAUTOCLAIM", stream_key, group, consumer_name, reclaim_idle_ms,
                cursor, "COUNT", batch_size, **{NEVER_DECODE: True},
            )
            cursor, recovered = claimed[:2]
            for entry_id, fields in recovered:
                await process_entry(
                    redis, stream_key, group, entry_id, fields, handlers,
                    dead_letter_key=dead_letter_key, max_retries=max_retries,
                    completion_ttl_seconds=completion_ttl_seconds,
                    handler_timeout_seconds=handler_timeout_seconds,
                )
            messages = await redis.execute_command(
                "XREADGROUP", "GROUP", group, consumer_name, "COUNT", batch_size,
                "BLOCK", 2000, "STREAMS", stream_key, ">", **{NEVER_DECODE: True},
            )
            for _, entries in messages:
                for entry_id, fields in entries:
                    await process_entry(
                        redis, stream_key, group, entry_id, fields, handlers,
                        dead_letter_key=dead_letter_key, max_retries=max_retries,
                        completion_ttl_seconds=completion_ttl_seconds,
                        handler_timeout_seconds=handler_timeout_seconds,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("consumer_loop_error", stream=stream_key, error_type=type(exc).__name__)
            await asyncio.sleep(1)
