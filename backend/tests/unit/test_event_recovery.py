"""Crash boundaries in event dispatch; no external service access."""

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError, ResponseError

from app.events.bus import (
    ACKED,
    PENDING,
    completion_key,
    ensure_consumer_groups,
    process_entry,
    run_consumer_loop,
)


def envelope():
    return {"event_id": str(uuid.uuid4()), "event_type": "intent.validated", "payload": "{}"}


async def test_failed_handler_is_not_seen_and_prior_handler_stays_completed(fake_redis, monkeypatch):
    event = envelope()
    calls = []

    async def first(event):
        calls.append("first")

    async def second(event):
        calls.append("second")
        if calls.count("second") == 1:
            raise RuntimeError("side effect failed")

    await fake_redis.set(f"event:seen:{event['event_id']}", "1")
    # Unclassified failures stay pending for reclaim: never dead-lettered, never ACKed.
    xadd = AsyncMock(side_effect=ResponseError("WRONGTYPE"))
    ack = AsyncMock()
    monkeypatch.setattr(fake_redis, "xadd", xadd)
    monkeypatch.setattr(fake_redis, "xack", ack)
    handlers = {event["event_type"]: [first, second]}
    assert await process_entry(fake_redis, "s", "g", "1-0", event, handlers,
                               max_retries=1, dead_letter_key="dlq") == PENDING
    xadd.assert_not_awaited()
    ack.assert_not_awaited()
    assert await fake_redis.exists(completion_key("s", "g", event["event_id"], first))
    assert not await fake_redis.exists(completion_key("s", "g", event["event_id"], second))
    assert await process_entry(fake_redis, "s", "g", "1-0", event, handlers, max_retries=1) == ACKED
    await process_entry(fake_redis, "s", "g", "2-0", event, handlers, max_retries=1)
    assert calls == ["first", "second", "second"]
    await process_entry(fake_redis, "s", "another-group", "1-0", event, handlers, max_retries=1)
    assert calls[-2:] == ["first", "second"]


@pytest.mark.parametrize("poison", [
    {"payload": "{"}, {"payload": "[]"}, {"payload": "null"},
    {"event_id": "bad"}, {"event_type": ""}, {"payload": b"\xff"},
])
async def test_poison_dlq_before_ack(poison):
    redis = AsyncMock()
    calls = []
    redis.xadd.side_effect = lambda *a, **k: calls.append("dlq")
    redis.xack.side_effect = lambda *a, **k: calls.append("ack")
    await process_entry(redis, "s", "g", "1-0", {**envelope(), **poison}, {})
    assert calls == ["dlq", "ack"]
    assert redis.xadd.call_args.args[1]["failure_reason"] == "malformed_envelope"


async def test_unavailable_dlq_never_acknowledges():
    redis = AsyncMock()
    redis.xadd.side_effect = ConnectionError("offline")
    with pytest.raises(ConnectionError):
        await process_entry(redis, "s", "g", "1-0", {}, {})
    redis.xack.assert_not_awaited()


async def test_crash_after_success_before_ack_skips_completed_handler(fake_redis, monkeypatch):
    event = envelope()
    calls = []

    async def handler(event):
        calls.append(event)

    ack = AsyncMock(side_effect=ConnectionError("lost ack"))
    monkeypatch.setattr(fake_redis, "xack", ack)
    with pytest.raises(ConnectionError):
        await process_entry(fake_redis, "s", "g", "1-0", event, {event["event_type"]: handler})
    ack.side_effect = None
    await process_entry(fake_redis, "s", "g", "1-0", event, {event["event_type"]: handler})
    assert len(calls) == 1


async def test_cancelled_handler_remains_pending_without_completion(fake_redis, monkeypatch):
    event = envelope()

    async def handler(event):
        raise asyncio.CancelledError

    ack = AsyncMock()
    monkeypatch.setattr(fake_redis, "xack", ack)
    with pytest.raises(asyncio.CancelledError):
        await process_entry(fake_redis, "s", "g", "1-0", event, {event["event_type"]: handler})
    assert not await fake_redis.exists(completion_key("s", "g", event["event_id"], handler))
    ack.assert_not_awaited()


async def test_unknown_events_ack_without_marker():
    redis = AsyncMock()
    await process_entry(redis, "s", "g", "1-0", envelope(), {})
    redis.xack.assert_awaited_once()
    redis.set.assert_not_awaited()
    redis.xadd.assert_not_awaited()


async def test_reclaim_is_bounded_advances_cursor_and_uses_stable_consumer_name():
    redis = AsyncMock()
    redis.execute_command.side_effect = [["7-0", [], []], [], ["0-0", [], []], asyncio.CancelledError]
    with pytest.raises(asyncio.CancelledError):
        await run_consumer_loop(redis, "s", "g", "api", {}, batch_size=2)
    claims = [c for c in redis.execute_command.call_args_list if c.args[0] == "XAUTOCLAIM"]
    assert [c.args[5] for c in claims] == ["0-0", "7-0"]
    assert all(c.args[7] == 2 for c in claims)
    # ADR-028: one stable name per instance; restarts reuse (and reclaim) it.
    assert {c.args[3] for c in claims} == {"api"}
    redis.execute_command.side_effect = [["0-0", [], []], asyncio.CancelledError]
    with pytest.raises(asyncio.CancelledError):
        await run_consumer_loop(redis, "s", "g", "api", {})
    assert redis.execute_command.call_args.args[3] == "api"
    with pytest.raises(ValueError):
        await run_consumer_loop(redis, "s", "g", "", {})


async def test_group_provisioning_fails_closed():
    redis = AsyncMock()
    redis.xgroup_create.side_effect = ConnectionError("offline")
    with pytest.raises(ConnectionError):
        await ensure_consumer_groups(redis)


async def test_handler_timeout_stays_pending_without_completion_or_dlq(fake_redis, monkeypatch):
    event = envelope()
    attempts = []

    async def handler(event):
        attempts.append(1)
        await asyncio.Event().wait()

    ack = AsyncMock()
    monkeypatch.setattr(fake_redis, "xack", ack)
    outcome = await process_entry(fake_redis, "s", "g", "1-0", event, {event["event_type"]: handler},
                                  max_retries=3, handler_timeout_seconds=0.01)
    assert outcome == PENDING and attempts == [1]  # a hung handler is not re-run in-process
    assert not await fake_redis.exists(completion_key("s", "g", event["event_id"], handler))
    assert await fake_redis.xlen("stream:dead_letter") == 0
    ack.assert_not_awaited()
