"""At-least-once Redis Streams delivery with bounded pending recovery (ADR-010, ADR-028 C14).

Failure policy per handler invocation:
  * success -> completion marker (unless registered idempotent) and, once every
    handler for the event succeeded, XACK;
  * deterministic failure (bad payload, unsupported version, ValueError/KeyError/
    TypeError/ValidationError/DeterministicEventError) -> dead-letter, then XACK;
  * transient or unclassified failure -> bounded in-process retries, then the entry
    is left *pending*. XAUTOCLAIM reclaims it after ``reclaim_idle_ms`` of idleness
    (the redelivery backoff); once XPENDING reports more than ``max_deliveries``
    deliveries it is dead-lettered without running handlers.
An entry is ACKed only after success or a confirmed dead-letter append. Dead-letter
entries keep the original fields/bytes plus handler, reason, delivery count and
error type; exception messages are never stored.

Consumers use one stable name per instance so restarts inherit their own pending
entries instead of adding a consumer per start. ``run_consumer_janitor`` (leader
only) removes long-idle consumers that hold no pending entries.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence

import redis.asyncio as aioredis
from redis.client import NEVER_DECODE
from redis.exceptions import ResponseError

from app.core.errors import DeterministicEventError  # noqa: F401 - re-exported for handlers
from app.core.failures import dependency_name, is_deterministic
from app.core.logging import get_logger
from app.events.contracts import EnvelopeRejected, validate_envelope

logger = get_logger(__name__)

STREAM_GROUPS = {
    f"stream:{module}": "nanfo-consumers"
    for module in ("auth", "intent", "network", "org", "telemetry", "alert", "simulation", "plugin", "report")
}
DEAD_LETTER_STREAM = "stream:dead_letter"
EventHandler = Callable[[dict], Awaitable[None]]
IDEMPOTENT_ATTRIBUTE = "__nanfo_idempotent__"
READ_BLOCK_MS = 2000
MIN_DEFERRAL_BACKOFF_SECONDS = 1.0
MAX_OUTAGE_BACKOFF_SECONDS = 30.0
JANITOR_MIN_IDLE_MS = 3_600_000

# Outcomes of process_entry.
ACKED = "acked"
PENDING = "pending"
OUTAGE = "outage"

# Process-local counters surfaced by readiness diagnostics.
_COUNTERS = {"markers_written": 0, "markers_reused": 0, "idempotent_runs": 0,
             "dead_lettered": 0, "left_pending": 0, "consumers_pruned": 0}


def bus_diagnostics() -> dict[str, int]:
    return dict(_COUNTERS)


def idempotent(handler: EventHandler) -> EventHandler:
    """Register a handler whose durable effect is unique-keyed by ``event_id``.

    Such handlers skip Redis completion markers: a redelivery re-runs them and the
    owning store discards the duplicate. Identity (module/qualname) is preserved.
    """
    if getattr(handler, IDEMPOTENT_ATTRIBUTE, False):
        return handler

    @functools.wraps(handler)
    async def wrapper(event: dict) -> None:
        await handler(event)

    setattr(wrapper, IDEMPOTENT_ATTRIBUTE, True)
    return wrapper


def is_idempotent(handler: EventHandler) -> bool:
    return bool(getattr(handler, IDEMPOTENT_ATTRIBUTE, False))


def idempotent_handlers(handlers: dict, *, only: Iterable[str] | None = None) -> dict:
    selected = set(handlers) if only is None else set(only)
    return {
        name: (_mark(value) if name in selected else value)
        for name, value in handlers.items()
    }


def _mark(value):
    return idempotent(value) if callable(value) else [idempotent(item) for item in value]


def merge_handlers(*handler_dicts: dict) -> dict:
    merged: dict = {}
    for handlers in handler_dicts:
        for name, value in handlers.items():
            merged.setdefault(name, []).extend([value] if callable(value) else list(value))
    return merged


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


def handler_name(handler: EventHandler) -> str:
    return f"{getattr(handler, '__module__', '?')}:{getattr(handler, '__qualname__', '?')}"


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _decode_fields(fields: dict) -> dict:
    return {_text(key): _text(value) for key, value in fields.items()}


def entity_key(fields: dict) -> str | None:
    """Ordering key: payload network_id, else device_id (C13 orders per network)."""
    try:
        payload = json.loads(_decode_fields(fields).get("payload", ""))
    except (ValueError, TypeError, UnicodeError, AttributeError):
        return None
    if not isinstance(payload, dict):
        return None
    for name in ("network_id", "device_id"):
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            return f"{name}:{value.strip()}"
    return None


async def _dead_letter(redis, dead_letter_key: str, raw_fields: dict, *, stream_key: str, group: str,
                       entry_id, reason: str, handler: str, delivery_count: int, error_type: str) -> None:
    # Keep original bytes, even for invalid UTF-8 poison. No MAXLEN truncation.
    await redis.xadd(dead_letter_key, {
        **raw_fields, "failed_entry_id": entry_id, "failed_stream": stream_key,
        "failed_group": group, "failure_reason": reason, "failed_handler": handler,
        "delivery_count": str(delivery_count), "error_type": error_type,
    })
    _COUNTERS["dead_lettered"] += 1
    logger.error("event_dead_lettered", stream=stream_key, entry_id=_text(entry_id), reason=reason,
                 handler=handler, delivery_count=delivery_count, error_type=error_type)


async def process_entry(
    redis: aioredis.Redis,
    stream_key: str,
    group: str,
    entry_id: str,
    fields: dict,
    handlers: dict[str, EventHandler | Sequence[EventHandler]],
    *,
    dead_letter_key: str = DEAD_LETTER_STREAM,
    max_retries: int = 3,
    completion_ttl_seconds: int = 3600,
    handler_timeout_seconds: float = 30,
    delivery_count: int = 1,
    max_deliveries: int = 20,
    retry_backoff_seconds: float = 0.5,
) -> str:
    """Return ACKED, PENDING (retry via reclaim) or OUTAGE (pending; dependency down).

    Completion is an optimization, not a transaction with the side effect. Owning
    modules must protect durable effects against the commit-to-marker crash window.
    """
    raw_fields = fields
    reason = handler_label = error_type = ""
    try:
        fields = _decode_fields(raw_fields)
        event_id = str(uuid.UUID(fields["event_id"]))
        event_type = fields["event_type"]
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("Missing event type")
        payload = json.loads(fields["payload"])
        if not isinstance(payload, dict):
            raise TypeError("Payload must be an object")
        validate_envelope(event_type, fields, payload)
    except EnvelopeRejected as exc:
        reason, error_type = exc.reason, type(exc).__name__
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
        reason, error_type = "malformed_envelope", type(exc).__name__
    else:
        if delivery_count > max_deliveries:
            reason = "max_deliveries_exceeded"
        else:
            registered = handlers.get(event_type, ())
            selected = (registered,) if callable(registered) else registered
            event = {**fields, "event_id": event_id, "payload": payload}
            for handler in selected:
                outcome = await _run_handler(
                    redis, handler, event, stream_key=stream_key, group=group, event_id=event_id,
                    max_retries=max_retries, completion_ttl_seconds=completion_ttl_seconds,
                    handler_timeout_seconds=handler_timeout_seconds,
                    retry_backoff_seconds=retry_backoff_seconds,
                )
                if outcome is None:
                    continue
                if outcome[0] in (PENDING, OUTAGE):
                    _COUNTERS["left_pending"] += 1
                    logger.warning("event_left_pending", stream=stream_key, entry_id=_text(entry_id),
                                   event_id=event_id, handler=handler_name(handler),
                                   delivery_count=delivery_count, error_type=outcome[1])
                    return outcome[0]
                reason, handler_label, error_type = "handler_failed_deterministic", handler_name(handler), outcome[1]
                break

    if reason:
        await _dead_letter(redis, dead_letter_key, raw_fields, stream_key=stream_key, group=group,
                           entry_id=entry_id, reason=reason, handler=handler_label,
                           delivery_count=delivery_count, error_type=error_type)
    # Unknown, well-formed events retain the existing ACK-and-ignore behavior.
    await redis.xack(stream_key, group, entry_id)
    return ACKED


async def _run_handler(redis, handler, event, *, stream_key, group, event_id, max_retries,
                       completion_ttl_seconds, handler_timeout_seconds, retry_backoff_seconds):
    """None on success; (PENDING|OUTAGE|"deterministic", error_type) on failure."""
    marker = not is_idempotent(handler)
    key = completion_key(stream_key, group, event_id, handler)
    if marker and await redis.exists(key):
        _COUNTERS["markers_reused"] += 1
        return None
    failure = None
    for attempt in range(1, max_retries + 1):
        try:
            async with asyncio.timeout(handler_timeout_seconds):
                await handler(event)
        except Exception as exc:  # noqa: BLE001 - classified below, message never logged
            logger.warning("event_handler_failed", event_id=event_id, handler=handler.__qualname__,
                           attempt=attempt, error_type=type(exc).__name__)
            if is_deterministic(exc):
                return ("deterministic", type(exc).__name__)
            failure = (OUTAGE if dependency_name(exc) else PENDING, type(exc).__name__)
            # Outages and timeouts are not retried in-process: reclaim idle time is the backoff.
            if failure[0] == OUTAGE or isinstance(exc, TimeoutError) or attempt == max_retries:
                return failure
            await asyncio.sleep(attempt * retry_backoff_seconds)
        else:
            if marker:
                # Never consult legacy event:seen keys, or mark before success.
                await redis.set(key, "1", ex=completion_ttl_seconds)
                _COUNTERS["markers_written"] += 1
            else:
                _COUNTERS["idempotent_runs"] += 1
            return None
    return failure


async def _delivery_counts(redis, stream_key: str, group: str, consumer_name: str, entries) -> dict[str, int]:
    """Delivery counters for just-claimed entries (XAUTOCLAIM increments them)."""
    ids = [_text(entry_id) for entry_id, _ in entries]
    rows = await redis.xpending_range(stream_key, group, min=ids[0], max=ids[-1],
                                      count=max(len(ids), 1), consumername=consumer_name)
    counts = {}
    for row in rows or ():
        try:
            counts[_text(row["message_id"])] = int(row["times_delivered"])
        except (KeyError, TypeError, ValueError):
            continue
    return counts


async def _process_batch(redis, stream_key, group, entries, counts, handlers, *, concurrency: int, **options) -> bool:
    """Process one page; True when any entry stayed pending (caller backs off).

    Order is preserved per entity key: once an entity's entry stays pending its later
    entries in the page are left pending too; a dependency outage stops the page.
    """
    blocked: set[str | None] = set()
    stop = False
    deferred = False

    async def handle(entry_id, fields) -> None:
        nonlocal stop, deferred
        key = entity_key(fields)
        if stop or key in blocked:
            deferred = True
            return
        outcome = await process_entry(redis, stream_key, group, entry_id, fields, handlers,
                                      delivery_count=counts.get(_text(entry_id), 1), **options)
        if outcome != ACKED:
            deferred = True
            blocked.add(key)
            if outcome == OUTAGE:
                stop = True

    if concurrency <= 1:
        for entry_id, fields in entries:
            await handle(entry_id, fields)
        return deferred

    lanes: dict[str | None, list] = {}
    for entry in entries:
        lanes.setdefault(entity_key(entry[1]), []).append(entry)
    gate = asyncio.Semaphore(concurrency)

    async def lane(items):
        async with gate:
            for entry_id, fields in items:
                await handle(entry_id, fields)

    results = await asyncio.gather(*(lane(items) for items in lanes.values()), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return deferred


async def run_consumer_loop(
    redis: aioredis.Redis,
    stream_key: str,
    group: str,
    consumer_name: str,
    handlers: dict[str, EventHandler | Sequence[EventHandler]],
    dead_letter_key: str = DEAD_LETTER_STREAM,
    max_retries: int = 3,
    *,
    reclaim_idle_ms: int = 60000,
    batch_size: int = 10,
    completion_ttl_seconds: int = 3600,
    handler_timeout_seconds: float = 30,
    max_deliveries: int = 20,
    concurrency: int = 1,
    block_redis: aioredis.Redis | None = None,
    block_ms: int = READ_BLOCK_MS,
) -> None:
    """One XAUTOCLAIM page per round, then new entries, without draining the PEL.

    ``consumer_name`` is used verbatim: a stable per-instance identity lets a
    restarted process reclaim its own pending entries and keeps the group small.
    """
    if (not 1 <= batch_size <= 100 or reclaim_idle_ms <= 0 or max_retries < 1
            or max_deliveries < 1 or not 1 <= concurrency <= 32 or not consumer_name):
        raise ValueError("Invalid consumer recovery bounds")
    reader = block_redis or redis
    options = dict(dead_letter_key=dead_letter_key, max_retries=max_retries,
                   completion_ttl_seconds=completion_ttl_seconds,
                   handler_timeout_seconds=handler_timeout_seconds, max_deliveries=max_deliveries)
    cursor = "0-0"
    backoff = 0.0
    while True:
        try:
            # Decode inside process_entry: one invalid UTF-8 field must not make
            # redis-py discard the entire response before poison can reach DLQ.
            claimed = await redis.execute_command(
                "XAUTOCLAIM", stream_key, group, consumer_name, reclaim_idle_ms,
                cursor, "COUNT", batch_size, **{NEVER_DECODE: True},
            )
            cursor, recovered = claimed[:2]
            deferred = False
            if recovered:
                counts = await _delivery_counts(redis, stream_key, group, consumer_name, recovered)
                deferred = await _process_batch(redis, stream_key, group, recovered, counts, handlers,
                                                concurrency=concurrency, **options)
            if not deferred:
                messages = await reader.execute_command(
                    "XREADGROUP", "GROUP", group, consumer_name, "COUNT", batch_size,
                    "BLOCK", block_ms, "STREAMS", stream_key, ">", **{NEVER_DECODE: True},
                )
                for _, entries in messages or ():
                    deferred = await _process_batch(redis, stream_key, group, entries, {}, handlers,
                                                    concurrency=concurrency, **options) or deferred
            if deferred:
                # Pending entries are retried by reclaim; do not spin through new work.
                backoff = min(max(MIN_DEFERRAL_BACKOFF_SECONDS, backoff * 2), MAX_OUTAGE_BACKOFF_SECONDS)
                await asyncio.sleep(backoff)
            else:
                backoff = 0.0
                # Yield every round even if the client never suspends (fairness).
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("consumer_loop_error", stream=stream_key, error_type=type(exc).__name__)
            await asyncio.sleep(1)


_DELETE_IDLE_CONSUMER = """
local consumers = redis.call('XINFO', 'CONSUMERS', KEYS[1], ARGV[1])
for _, raw in ipairs(consumers) do
    local c = {}
    for i = 1, #raw, 2 do c[raw[i]] = raw[i + 1] end
    if c['name'] == ARGV[2] then
        if c['pending'] == 0 and c['idle'] > tonumber(ARGV[3]) then
            return redis.call('XGROUP', 'DELCONSUMER', KEYS[1], ARGV[1], ARGV[2])
        end
        return -1
    end
end
return -2
"""


def janitor_min_idle_ms(reclaim_idle_ms: int) -> int:
    return max(10 * reclaim_idle_ms, JANITOR_MIN_IDLE_MS)


async def prune_idle_consumers(redis, streams: dict[str, str], *, active_consumer: str,
                               min_idle_ms: int) -> list[tuple[str, str, str]]:
    """Delete consumers with no pending entries idle > min_idle_ms (atomic re-check)."""
    removed = []
    for stream_key, group in streams.items():
        try:
            consumers = await redis.xinfo_consumers(stream_key, group)
        except ResponseError:
            continue  # Stream or group not provisioned yet.
        for consumer in consumers:
            name = _text(consumer.get("name"))
            if not isinstance(name, str) or name == active_consumer:
                continue
            if consumer.get("pending") != 0 or int(consumer.get("idle", 0)) <= min_idle_ms:
                continue
            # Re-check inside Redis: a consumer that just claimed work is never removed.
            if await redis.eval(_DELETE_IDLE_CONSUMER, 1, stream_key, group, name, min_idle_ms) == 0:
                removed.append((stream_key, group, name))
                _COUNTERS["consumers_pruned"] += 1
                logger.info("event_consumer_pruned", stream=stream_key, group=group, consumer=name)
    return removed


async def run_consumer_janitor(
    redis, streams: dict[str, str], *, active_consumer: str, reclaim_idle_ms: int,
    interval_seconds: float = 600, initial_delay_seconds: float = 300,
    leadership: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Leader-only periodic cleanup of dead consumer names; never fatal."""
    min_idle_ms = janitor_min_idle_ms(reclaim_idle_ms)
    await asyncio.sleep(initial_delay_seconds)
    while True:
        try:
            if leadership is not None:
                await leadership()
            await prune_idle_consumers(redis, streams, active_consumer=active_consumer, min_idle_ms=min_idle_ms)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("event_consumer_janitor_failed", error_type=type(exc).__name__)
        await asyncio.sleep(interval_seconds)
