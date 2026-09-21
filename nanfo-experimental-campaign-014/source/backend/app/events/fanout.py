"""Independent bounded broadcast cursors; never use a domain consumer group."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from pydantic import ValidationError
from redis.client import NEVER_DECODE

from app.core.logging import get_logger
from app.events.fanout_contract import FanoutEnvelope, FanoutSettings

logger = get_logger(__name__)

_PUBLISH = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return false end
local seq = redis.call('INCR', KEYS[2])
local body = cjson.decode(ARGV[2])
body.sequence = seq
local encoded = cjson.encode(body)
if string.len(encoded) > tonumber(ARGV[4]) then return -1 end
return redis.call('XADD', KEYS[3], 'MAXLEN', ARGV[3], '*', 'body', encoded)
"""

_QUARANTINE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return false end
redis.call('XADD', KEYS[4], 'MAXLEN', ARGV[4], '*', 'receipt', ARGV[2])
local body = cjson.decode(ARGV[3])
body.sequence = redis.call('INCR', KEYS[2])
return redis.call('XADD', KEYS[3], 'MAXLEN', ARGV[4], '*', 'body', cjson.encode(body))
"""


class PermanentFanoutError(ValueError):
    """Deterministic envelope failure; quarantine instead of cancelling leadership."""


class FanoutPublisher:
    def __init__(self, redis, *, token: str, settings: FanoutSettings):
        self.redis, self.token, self.settings = redis, token, settings

    async def publish(self, *, channel: str | None = None, delivery_id: str = "heartbeat",
                      kwargs: dict | None = None) -> None:
        try:
            try:
                # JsonValue permits floating values; reject NaN/Infinity before
                # Lua cjson can turn a deterministic encoding fault into retries.
                json.dumps(kwargs, allow_nan=False).encode("utf-8")
                envelope = FanoutEnvelope.model_validate({
                    "kind": "heartbeat" if channel is None else "delta",
                    "epoch": self.token, "sequence": 1, "published_at": time.time(),
                    "delivery_id": delivery_id, "channel": channel, "kwargs": kwargs,
                })
                body = envelope.model_dump_json(exclude_none=True)
                encoded_size = len(body.encode())
            except (ValueError, TypeError, RecursionError, OverflowError) as exc:
                raise PermanentFanoutError("invalid_envelope") from exc
            if encoded_size + 128 > self.settings.max_payload_bytes:
                raise PermanentFanoutError("oversized_envelope")
        except PermanentFanoutError as exc:
            await self.quarantine(delivery_id=delivery_id, reason=str(exc))
            return
        # Only transport, uncertain append and lease failures cancel durable work.
        try:
            async with asyncio.timeout(self.settings.io_timeout_seconds):
                result = await self.redis.eval(
                    _PUBLISH, 3, self.settings.lease_key, self.settings.sequence_key,
                    self.settings.stream_key, self.token, body, self.settings.max_entries,
                    self.settings.max_payload_bytes,
                )
            if result == -1:
                await self.quarantine(delivery_id=delivery_id, reason="encoded_envelope_oversized")
            elif not result:
                raise RuntimeError("Fanout leader fenced")
        except Exception as exc:
            logger.error("fanout_publish_failed", error_type=type(exc).__name__)
            raise asyncio.CancelledError("Unpublished durable work must remain pending") from exc

    async def quarantine(self, *, delivery_id: str, reason: str) -> None:
        """Bounded receipt + ordered reset must succeed before durable completion.

        No raw poison bytes or validation errors are retained in this diagnostic
        stream. Original durable domain storage remains the owning source of truth.
        """
        identity = hashlib.sha256(delivery_id.encode("utf-8", errors="replace")).hexdigest()
        receipt = json.dumps({"version": 1, "delivery_sha256": identity, "reason": reason,
                              "quarantined_at": time.time()})
        reset = FanoutEnvelope(kind="reset", epoch=self.token, sequence=1,
                               published_at=time.time(), delivery_id=f"reset:{identity}").model_dump_json(exclude_none=True)
        try:
            async with asyncio.timeout(self.settings.io_timeout_seconds):
                result = await self.redis.eval(
                    _QUARANTINE, 4, self.settings.lease_key, self.settings.sequence_key,
                    self.settings.stream_key, f"{self.settings.stream_key}:quarantine",
                    self.token, receipt, reset, self.settings.max_entries,
                )
            if not result:
                raise RuntimeError("Quarantine leader fenced")
        except Exception as exc:
            raise asyncio.CancelledError("Unconfirmed quarantine/reset must remain pending") from exc
        logger.error("fanout_quarantined", delivery_sha256=identity, reason=reason)


_publisher: ContextVar[FanoutPublisher | None] = ContextVar("realtime_publisher", default=None)


async def push_realtime_delta(manager, *, channel: str, event: dict, **kwargs) -> None:
    """Minimal consumer bridge. Only leader descendants inherit the publisher."""
    publisher = _publisher.get()
    if publisher is None:
        await manager.push_delta(**kwargs)
        return
    event_id = str(event.get("event_id", ""))
    if not event_id:
        await publisher.quarantine(delivery_id=f"{channel}:missing", reason="missing_event_id")
        return
    await publisher.publish(channel=channel, delivery_id=f"{channel}:{event_id}", kwargs=kwargs)


class FanoutSubscriber:
    def __init__(self, redis, *, settings: FanoutSettings,
                 dispatch: Callable[[FanoutEnvelope], Awaitable[None]],
                 availability: Callable[[bool], Awaitable[None]]):
        self.redis, self.settings = redis, settings
        self.dispatch, self.availability = dispatch, availability
        self.cursor = "0-0"
        self.sequence: int | None = None
        self.epoch: str | None = None
        self.seen: OrderedDict[str, None] = OrderedDict()
        self.last_received = 0.0
        self.available = False
        self.ready = asyncio.Event()
        self.task: asyncio.Task | None = None

    @property
    def healthy(self) -> bool:
        return (self.available and self.task is not None and not self.task.done()
                and time.monotonic() - self.last_received < self.settings.stale_seconds)

    async def verify(self) -> bool:
        # Includes a live Redis check without extending last-received freshness.
        try:
            async with asyncio.timeout(self.settings.io_timeout_seconds):
                await self.redis.ping()
            return self.healthy
        except Exception:
            return False

    async def _baseline(self) -> None:
        async with asyncio.timeout(self.settings.io_timeout_seconds):
            rows = await self.redis.execute_command(
                "XREVRANGE", self.settings.stream_key, "+", "-", "COUNT", 1,
                **{NEVER_DECODE: True},
            )
        self.cursor = rows[0][0] if rows else "0-0"
        self.sequence = self.epoch = None
        if rows:
            envelope = self._decode(rows[0][1])
            self.sequence, self.epoch = envelope.sequence, envelope.epoch

    def _decode(self, fields: dict) -> FanoutEnvelope:
        if set(fields) != {b"body"}:
            raise ValueError("Unknown fanout entry fields")
        body = fields[b"body"]
        if len(body) > self.settings.max_payload_bytes:
            raise ValueError("Oversized fanout entry")
        return FanoutEnvelope.model_validate_json(body)

    async def _lost(self) -> None:
        self.available = False
        self.ready.clear()
        self.seen.clear()
        await self.availability(False)

    async def start(self) -> None:
        await self._lost()
        # Cursor establishment precedes leader startup and socket admission.
        try:
            await self._baseline()
        except (ValueError, ValidationError):
            # Poison tail is skipped, but never permits sockets until fresh data.
            pass
        self.task = asyncio.create_task(self._run(), name="realtime-fanout-subscriber")

    async def _accept(self, fields: dict) -> None:
        if self.available and time.monotonic() - self.last_received >= self.settings.stale_seconds:
            # A suspended event loop must not hide a freshness outage merely by
            # receiving a new heartbeat immediately after it resumes.
            await self._lost()
        envelope = self._decode(fields)
        age = time.time() - envelope.published_at
        if age > self.settings.stale_seconds or age < -self.settings.io_timeout_seconds:
            raise ValueError("Stale/future fanout envelope")
        if self.sequence is not None and (
            envelope.sequence != self.sequence + 1 or envelope.epoch != self.epoch
        ):
            await self._lost()
        self.sequence, self.epoch = envelope.sequence, envelope.epoch
        self.last_received = time.monotonic()
        if envelope.kind == "reset":
            await self._lost()
            return  # Only a subsequent fresh frame reopens admission.
        if not self.available:
            await self.availability(True)
            self.available = True
            self.ready.set()
        if envelope.kind == "delta" and envelope.delivery_id not in self.seen:
            async with asyncio.timeout(self.settings.io_timeout_seconds):
                await self.dispatch(envelope)
            self.seen[envelope.delivery_id] = None
            if len(self.seen) > self.settings.dedup_entries:
                self.seen.popitem(last=False)
        elif envelope.kind == "delta":
            self.seen.move_to_end(envelope.delivery_id)

    async def _run(self) -> None:
        try:
            while True:
                try:
                    async with asyncio.timeout(self.settings.io_timeout_seconds):
                        messages = await self.redis.execute_command(
                            "XREAD", "COUNT", self.settings.batch_size, "BLOCK",
                            max(1, int(self.settings.heartbeat_seconds * 500)),
                            "STREAMS", self.settings.stream_key, self.cursor,
                            **{NEVER_DECODE: True},
                        )
                    for _, rows in messages or ():
                        for cursor, fields in rows:
                            self.cursor = cursor
                            await self._accept(fields)
                    if self.available and not self.healthy:
                        await self._lost()
                except Exception as exc:
                    logger.warning("fanout_subscription_lost", error_type=type(exc).__name__)
                    await self._lost()
                    await asyncio.sleep(self.settings.retry_seconds)
                    # On IO failure resume the existing cursor: sequence checks
                    # detect trim/reset; stale entries are never delivered.
        finally:
            await self._lost()

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self._lost()
