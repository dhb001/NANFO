"""ADR-028 C14 delivery policy: transient -> pending/reclaim, deterministic -> DLQ once.

No external services: fakeredis supplies real stream/PEL semantics (XAUTOCLAIM,
XPENDING delivery counters, XACK); AsyncMock is used only to observe calls.
"""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import fakeredis
import pytest
from neo4j.exceptions import ServiceUnavailable, SessionExpired, TransientError
from pydantic import BaseModel, ValidationError
from redis.exceptions import BusyLoadingError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError, OperationalError

from app.core.errors import DependencyUnavailableError, DeterministicEventError
from app.events import bus
from app.events.bus import (
    ACKED,
    OUTAGE,
    PENDING,
    _process_batch,
    completion_key,
    entity_key,
    idempotent,
    idempotent_handlers,
    janitor_min_idle_ms,
    merge_handlers,
    process_entry,
    prune_idle_consumers,
    run_consumer_loop,
)

SECRET = "secret-payload-detail"


def envelope(event_type="intent.validated", payload=None, **extra):
    return {"event_id": str(uuid.uuid4()), "event_type": event_type,
            "payload": json.dumps(payload if payload is not None else {}), **extra}


class Strict(BaseModel):
    value: int


def validation_error():
    try:
        Strict.model_validate({"value": SECRET})
    except ValidationError as exc:
        return exc
    raise AssertionError("validation expected")


OUTAGES = [
    RedisConnectionError(SECRET), RedisTimeoutError(SECRET), BusyLoadingError(SECRET),
    OperationalError("SELECT", {}, Exception(SECRET)), InterfaceError("SELECT", {}, Exception(SECRET)),
    DBAPIError("SELECT", {}, Exception(SECRET), connection_invalidated=True),
    ServiceUnavailable(SECRET), SessionExpired(SECRET), DependencyUnavailableError("redis"),
]
TRANSIENT = [TransientError(), ConnectionError(SECRET), TimeoutError(SECRET), OSError(SECRET),
             RuntimeError(SECRET), IntegrityError("INSERT", {}, Exception(SECRET))]
DETERMINISTIC = [ValueError(SECRET), KeyError(SECRET), TypeError(SECRET), DeterministicEventError(SECRET)]


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


def recorder():
    calls = []

    async def handler(event):
        calls.append(event)

    handler.calls = calls
    return handler


async def dead_letters(redis, key="stream:dead_letter"):
    return [fields for _, fields in await redis.xrange(key)]


@pytest.mark.parametrize("error", OUTAGES, ids=lambda error: type(error).__name__)
async def test_dependency_outage_stays_pending_without_retry_dlq_or_ack(redis, monkeypatch, error):
    attempts = []

    async def handler(event):
        attempts.append(event)
        raise error

    ack = AsyncMock()
    monkeypatch.setattr(redis, "xack", ack)
    event = envelope()
    outcome = await process_entry(redis, "s", "g", "1-0", event, {event["event_type"]: handler},
                                  retry_backoff_seconds=60)  # would hang if it retried in-process
    assert outcome == OUTAGE and len(attempts) == 1
    ack.assert_not_awaited()
    assert await dead_letters(redis) == []
    assert not await redis.exists(completion_key("s", "g", event["event_id"], handler))


@pytest.mark.parametrize("error", TRANSIENT, ids=lambda error: type(error).__name__)
async def test_transient_and_unclassified_failures_retry_then_stay_pending(redis, monkeypatch, error):
    attempts = []

    async def handler(event):
        attempts.append(event)
        raise error

    ack = AsyncMock()
    monkeypatch.setattr(redis, "xack", ack)
    event = envelope()
    outcome = await process_entry(redis, "s", "g", "1-0", event, {event["event_type"]: handler},
                                  max_retries=3, retry_backoff_seconds=0)
    assert outcome == PENDING
    assert len(attempts) == (1 if isinstance(error, TimeoutError) else 3)
    ack.assert_not_awaited()
    assert await dead_letters(redis) == []


@pytest.mark.parametrize("error", [*DETERMINISTIC, "validation"], ids=str)
async def test_deterministic_failure_dead_letters_once_with_redacted_metadata(redis, error):
    error = validation_error() if error == "validation" else error
    attempts = []

    async def handler(event):
        attempts.append(event)
        raise error

    event = envelope()
    await redis.xgroup_create("s", "g", id="0", mkstream=True)
    entry_id = await redis.xadd("s", event)
    await redis.xreadgroup("g", "c", {"s": ">"})
    assert await process_entry(redis, "s", "g", entry_id, event, {event["event_type"]: handler},
                               delivery_count=2, max_retries=3) == ACKED
    assert len(attempts) == 1
    [letter] = await dead_letters(redis)
    assert letter["failure_reason"] == "handler_failed_deterministic"
    assert letter["failed_handler"] == f"{handler.__module__}:{handler.__qualname__}"
    assert letter["delivery_count"] == "2" and letter["error_type"] == type(error).__name__
    assert letter["failed_entry_id"] == entry_id and letter["event_id"] == event["event_id"]
    assert SECRET not in json.dumps(letter)
    assert (await redis.xpending("s", "g"))["pending"] == 0


async def test_max_deliveries_exceeded_dead_letters_without_running_handlers(redis):
    handler = recorder()
    event = envelope()
    assert await process_entry(redis, "s", "g", "1-0", event, {event["event_type"]: handler},
                               delivery_count=21, max_deliveries=20) == ACKED
    assert handler.calls == []
    [letter] = await dead_letters(redis)
    assert letter["failure_reason"] == "max_deliveries_exceeded" and letter["delivery_count"] == "21"


@pytest.mark.parametrize("event,reason", [
    (envelope(version="2"), "unsupported_version"),
    (envelope(version="banana"), "unsupported_version"),
    (envelope("network.device.added", {"network_id": "n"}, timestamp="2026-09-23T00:00:00Z"), "invalid_payload"),
    (envelope("network.device.updated", {"device_id": "d"}, timestamp="2026-09-23T00:00:00Z"), "invalid_payload"),
    (envelope("network.device.deleted", {"device_id": "d"}), "invalid_payload"),
])
async def test_envelope_contract_rejections_are_deterministic(redis, event, reason):
    handler = recorder()
    assert await process_entry(redis, "s", "g", "1-0", event, {event["event_type"]: handler}) == ACKED
    assert handler.calls == []
    [letter] = await dead_letters(redis)
    assert letter["failure_reason"] == reason and letter["error_type"] == "EnvelopeRejected"


@pytest.mark.parametrize("event", [
    envelope(version="1"), envelope(version="1.4"), envelope(),
    envelope("network.device.deleted", {"device_id": "d"}, timestamp="2026-09-23T00:00:00Z", version="1"),
])
async def test_supported_versions_and_complete_payloads_are_delivered(redis, event):
    handler = recorder()
    assert await process_entry(redis, "s", "g", "1-0", event, {event["event_type"]: handler}) == ACKED
    assert len(handler.calls) == 1
    assert await dead_letters(redis) == []


async def test_idempotent_registration_skips_markers_but_keeps_identity(redis):
    calls = []

    async def persist(event):
        calls.append(event["event_id"])

    wrapped = idempotent(persist)
    assert idempotent(wrapped) is wrapped
    assert completion_key("s", "g", "id", wrapped) == completion_key("s", "g", "id", persist)
    event = envelope()
    for entry_id in ("1-0", "2-0"):
        assert await process_entry(redis, "s", "g", entry_id, event, {event["event_type"]: wrapped}) == ACKED
    assert calls == [event["event_id"]] * 2  # unique-keyed store absorbs the redelivery
    assert not await redis.keys("event:completed:*")
    await process_entry(redis, "s", "g", "3-0", event, {event["event_type"]: recorder()})
    assert len(await redis.keys("event:completed:*")) == 1
    assert bus.bus_diagnostics()["idempotent_runs"] >= 2


def test_merge_keeps_order_and_marks_only_selected_events():
    async def audit(event):
        pass

    async def metric(event):
        pass

    async def transition(event):
        pass

    merged = merge_handlers(
        idempotent_handlers({"a": audit}),
        idempotent_handlers({"metric": metric, "transition": transition}, only=("metric",)),
        {"a": transition},
    )
    assert [bus.is_idempotent(item) for item in merged["a"]] == [True, False]
    assert bus.is_idempotent(merged["metric"][0]) and not bus.is_idempotent(merged["transition"][0])
    assert merged["a"][0].__qualname__ == audit.__qualname__


@pytest.mark.parametrize("payload,expected", [
    ({"network_id": "n1", "device_id": "d1"}, "network_id:n1"),
    ({"device_id": "d1"}, "device_id:d1"),
    ({}, None), ("[]", None),
])
def test_entity_key(payload, expected):
    fields = {"payload": payload if isinstance(payload, str) else json.dumps(payload)}
    assert entity_key(fields) == expected
    assert entity_key({"payload": b"\xff"}) is None


@pytest.fixture
def fast_backoff(monkeypatch):
    monkeypatch.setattr(bus, "MIN_DEFERRAL_BACKOFF_SECONDS", 0.001)
    monkeypatch.setattr(bus, "MAX_OUTAGE_BACKOFF_SECONDS", 0.001)


async def until(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not await predicate():
            await asyncio.sleep(0.005)


async def test_loop_reclaims_outage_until_max_deliveries_then_dead_letters(redis, fast_backoff):
    await redis.xgroup_create("s", "g", id="0", mkstream=True)
    event = envelope()
    await redis.xadd("s", event)
    attempts = []

    async def handler(event):
        attempts.append(1)
        raise RedisConnectionError(SECRET)

    task = asyncio.create_task(run_consumer_loop(
        redis, "s", "g", "api-host", {event["event_type"]: handler},
        reclaim_idle_ms=1, max_deliveries=3, block_ms=5,
    ))
    try:
        async def dead():
            return len(await dead_letters(redis)) == 1
        await until(dead)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert len(attempts) == 3  # deliveries 1..3 ran; the 4th exceeded the bound
    [letter] = await dead_letters(redis)
    assert letter["failure_reason"] == "max_deliveries_exceeded" and letter["delivery_count"] == "4"
    assert (await redis.xpending("s", "g"))["pending"] == 0
    assert [consumer["name"] for consumer in await redis.xinfo_consumers("s", "g")] == ["api-host"]


async def test_loop_recovers_after_transient_failures_without_dead_letter(redis, fast_backoff):
    await redis.xgroup_create("s", "g", id="0", mkstream=True)
    event = envelope()
    await redis.xadd("s", event)
    attempts = []

    async def handler(event):
        attempts.append(1)
        if len(attempts) < 3:
            raise OperationalError("SELECT", {}, Exception(SECRET))

    task = asyncio.create_task(run_consumer_loop(
        redis, "s", "g", "api-host", {event["event_type"]: handler}, reclaim_idle_ms=1, block_ms=5,
    ))
    try:
        async def acknowledged():
            return len(attempts) >= 3 and (await redis.xpending("s", "g"))["pending"] == 0
        await until(acknowledged)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert await dead_letters(redis) == []


async def seed(redis, *networks):
    await redis.xgroup_create("s", "g", id="0", mkstream=True)
    for index, network in enumerate(networks):
        await redis.xadd("s", envelope(payload={"network_id": network, "index": index}))
    [[_, entries]] = await redis.xreadgroup("g", "c", {"s": ">"})
    return entries


async def test_concurrency_overlaps_entities_but_preserves_per_entity_order(redis):
    entries = await seed(redis, "A", "B", "A")
    order, release = [], asyncio.Event()

    async def handler(event):
        payload = event["payload"]
        if payload["index"] == 0:
            await release.wait()  # A1 blocks until B1 has run concurrently
        order.append((payload["network_id"], payload["index"]))
        if payload["network_id"] == "B":
            release.set()

    await asyncio.wait_for(_process_batch(redis, "s", "g", entries, {}, {"intent.validated": handler},
                                          concurrency=2), 2)
    assert order == [("B", 1), ("A", 0), ("A", 2)]
    assert (await redis.xpending("s", "g"))["pending"] == 0


async def test_default_concurrency_keeps_strict_stream_order(redis):
    entries = await seed(redis, "A", "B", "A")
    order = []

    async def handler(event):
        await asyncio.sleep(0.01 if event["payload"]["index"] == 0 else 0)
        order.append(event["payload"]["index"])

    await _process_batch(redis, "s", "g", entries, {}, {"intent.validated": handler}, concurrency=1)
    assert order == [0, 1, 2]


@pytest.mark.parametrize("concurrency", [1, 3])
async def test_pending_entity_blocks_its_later_entries_but_not_others(redis, concurrency):
    entries = await seed(redis, "A", "B", "A", "B")
    order = []

    async def handler(event):
        payload = event["payload"]
        if payload["index"] == 0:
            raise RuntimeError(SECRET)
        order.append(payload["index"])

    deferred = await _process_batch(redis, "s", "g", entries, {}, {"intent.validated": handler},
                                    concurrency=concurrency, max_retries=1)
    assert deferred and sorted(order) == [1, 3]  # A2 (index 2) waits behind the pending A1
    pending = await redis.xpending_range("s", "g", min="-", max="+", count=10)
    assert [row["message_id"] for row in pending] == [entries[0][0], entries[2][0]]


async def test_outage_stops_the_page(redis):
    entries = await seed(redis, "A", "B", "C")
    calls = []

    async def handler(event):
        calls.append(event["payload"]["index"])
        raise DependencyUnavailableError("postgres")

    assert await _process_batch(redis, "s", "g", entries, {}, {"intent.validated": handler}, concurrency=1)
    assert calls == [0]
    assert (await redis.xpending("s", "g"))["pending"] == 3


def test_janitor_threshold():
    assert janitor_min_idle_ms(60000) == 3_600_000
    assert janitor_min_idle_ms(600000) == 6_000_000


async def test_janitor_prunes_only_idle_consumers_without_pending():
    redis = AsyncMock()
    redis.xinfo_consumers.return_value = [
        {"name": "api-old", "pending": 0, "idle": 7_200_000},
        {"name": "api-busy", "pending": 2, "idle": 9_000_000},
        {"name": "api-recent", "pending": 0, "idle": 60_000},
        {"name": "api-self", "pending": 0, "idle": 9_000_000},
    ]
    redis.eval.return_value = 0
    removed = await prune_idle_consumers(redis, {"s": "g"}, active_consumer="api-self", min_idle_ms=3_600_000)
    assert removed == [("s", "g", "api-old")]
    [call] = redis.eval.await_args_list
    assert call.args[1:] == (1, "s", "g", "api-old", 3_600_000)
    assert "DELCONSUMER" in call.args[0] and "pending" in call.args[0]
    redis.eval.return_value = -1  # the atomic re-check refused: consumer became active
    assert await prune_idle_consumers(redis, {"s": "g"}, active_consumer="api-self", min_idle_ms=3_600_000) == []
