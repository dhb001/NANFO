"""ADR-028 retention invariants executed on the production Lua (tests.lua_streams).

Complements the opt-in real-Redis suite (test_stream_retention_redis.py) so every CI
run exercises consumer bounds, bounded re-planning and dead-letter retention.
"""

import json

import pytest
from redis.exceptions import ResponseError

from app.events.bus import _DELETE_IDLE_CONSUMER
from app.events.retention import (
    RetentionPolicy,
    RetentionRefused,
    StreamRetention,
    dead_letter_policy,
    decode_bundle,
    refusal_reason,
)
from app.events.retention_archive import StreamArchive
from app.events.retention_lua import DELETE
from tests.lua_streams import LuaStreams

STREAM, GROUP = "stream:telemetry", "nanfo-consumers"


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "archive"
    root.mkdir(mode=0o700)
    return StreamArchive(root)


def seed(count=5, *, groups=(GROUP,), ack=True):
    redis = LuaStreams()
    for index in range(1, count + 1):
        redis.add(STREAM, f"{index}-0", "event_id", "same", "payload", b"\xff\x00")
    for group in groups:
        redis.create_group(STREAM, group)
        delivered = redis.deliver(STREAM, group, "api-host")
        if ack:
            redis.ack(STREAM, group, *delivered)
    return redis


def operator(redis, archive, **kwargs):
    options = dict(stream=STREAM, groups=(GROUP,), min_age_seconds=60, min_free_bytes=1024**2)
    options.update(kwargs)
    return StreamRetention(redis, RetentionPolicy(**options), archive)


def before_delete(redis, action):
    async def hook(script):
        if script == DELETE:
            await action()
    redis.hooks.append(hook)


async def test_idle_consumers_without_pending_never_block_retention(archive):
    redis = seed()
    for index in range(70):  # e.g. one per historical restart before stable names
        redis.groups[STREAM.encode()][GROUP.encode()].consumers[f"api-{index}".encode()] = 0
    op = operator(redis, archive)
    health = await op.diagnostics()
    assert "consumer_churn" in health["alerts"] and health["groups"][0]["pending_consumers"] == 0
    result = await op.run(mode="apply")
    assert result["deleted"] == 5 and await redis.xlen(STREAM) == 0


async def test_pending_holder_bound_refuses_with_reason(archive):
    redis = seed(ack=False)
    group = redis.groups[STREAM.encode()][GROUP.encode()]
    for index, entry_id in enumerate(list(group.pending)):
        group.pending[entry_id][0] = f"holder-{index}".encode()
    for index in range(70):
        redis.add(STREAM, f"{100 + index}-0", "k", "v")
        group.pending[f"{100 + index}-0".encode()] = [f"extra-{index}".encode(), 0, 1]
    with pytest.raises(ResponseError) as error:
        await operator(redis, archive).run(mode="apply")
    assert refusal_reason(error.value) == "retention_pending_consumers"
    assert await redis.xlen(STREAM) == 75


@pytest.mark.parametrize("race", ["ack", "consumer", "append"])
async def test_harmless_concurrency_no_longer_aborts_delete(archive, race):
    redis = seed(ack=False)
    redis.ack(STREAM, GROUP, "1-0", "2-0", "3-0", "4-0", "5-0")

    async def action():
        if race == "ack":
            redis.ack(STREAM, GROUP, "5-0")
        elif race == "consumer":
            redis.groups[STREAM.encode()][GROUP.encode()].consumers[b"new-consumer"] = 0
        else:
            redis.add(STREAM, "6-0", "payload", "new")

    before_delete(redis, action)
    result = await operator(redis, archive).run(mode="apply")
    assert result["deleted"] == 5 and "replans" not in result
    assert [row[0] for row in await redis.xrange(STREAM)] == ([b"6-0"] if race == "append" else [])


async def test_ack_race_now_proceeds_with_the_planned_batch(archive):
    redis = seed(ack=False)
    redis.ack(STREAM, GROUP, "1-0")

    async def action():
        redis.ack(STREAM, GROUP, "2-0")

    before_delete(redis, action)
    result = await operator(redis, archive).run(mode="apply")
    # Batch 1 deletes the planned 1-0; the ACKed 2-0 becomes eligible for batch 2.
    assert result["deleted"] == 2 and await redis.xlen(STREAM) == 3
    assert "replans" not in result


@pytest.mark.parametrize("race,remaining", [
    ("reset", 5),        # cursor moved backwards: re-plan sees nothing delivered
    ("pending", 4),      # entry 2-0 became pending inside the batch: only 1-0 remains eligible
    ("entry", 0),        # entry changed (deleted): re-plan archives/deletes the rest
])
async def test_invalidated_batch_is_replanned_from_current_state(archive, race, remaining):
    redis = seed()
    fired = []

    async def action():
        if fired:
            return
        fired.append(race)
        group = redis.groups[STREAM.encode()][GROUP.encode()]
        if race == "reset":
            group.last, group.entries_read = b"0-0", 0
        elif race == "pending":
            group.pending[b"2-0"] = [b"new-consumer", 0, 1]
        else:
            redis.command(b"XDEL", STREAM.encode(), b"5-0")

    before_delete(redis, action)
    result = await operator(redis, archive).run(mode="apply")
    assert result["replans"] == 1
    assert await redis.xlen(STREAM) == remaining
    # The refused attempt's bundle is a safe orphan; nothing was deleted unarchived.
    archived = [entry for digest in result["archives"] for entry in decode_bundle(archive.read(digest))[1]]
    assert {entry_id for entry_id, _ in archived} >= {entry_id for entry_id in (b"1-0",)}


async def test_persistent_race_is_bounded_then_refused(archive):
    redis = seed()

    async def action():
        group = redis.groups[STREAM.encode()][GROUP.encode()]
        group.pending[b"1-0"] = [b"racer", 0, 1]

    async def release(script):
        redis.groups[STREAM.encode()][GROUP.encode()].pending.pop(b"1-0", None)

    redis.hooks.append(release)  # PLAN sees a clean state every time...
    before_delete(redis, action)  # ...and DELETE always sees the batch pending
    with pytest.raises(ResponseError) as error:
        await operator(redis, archive, max_delete_attempts=3).run(mode="apply")
    assert refusal_reason(error.value) == "retention_boundary_changed"
    assert await redis.xlen(STREAM) == 5
    assert len(list(archive.root.iterdir())) == 1  # identical batch: one content address


@pytest.mark.parametrize("race,reason", [
    ("new_group", "retention_unknown_groups"), ("destroy_group", "retention_group_count"),
])
async def test_group_set_changes_are_not_retried(archive, race, reason):
    redis = seed()

    async def action():
        if race == "new_group":
            redis.create_group(STREAM, "unregistered")
        else:
            redis.groups[STREAM.encode()].clear()

    before_delete(redis, action)
    with pytest.raises(ResponseError) as error:
        await operator(redis, archive).run(mode="apply")
    assert refusal_reason(error.value) == reason
    assert await redis.xlen(STREAM) == 5


async def test_dead_letter_stream_is_archived_before_delete_by_age(archive):
    redis = LuaStreams()
    for index in range(1, 4):
        redis.add("stream:dead_letter", f"{index}-0", "event_id", "e", "failure_reason", "malformed_envelope")
    redis.add("stream:dead_letter", f"{2**62}-0", "event_id", "young")  # younger than min age
    op = StreamRetention(redis, dead_letter_policy(min_age_seconds=60, min_free_bytes=1024**2), archive)
    result = await op.run(mode="apply")
    assert result["deleted"] == 3 and await redis.xlen("stream:dead_letter") == 1
    manifest, entries = decode_bundle(archive.read(result["archives"][0]))
    assert manifest["stream"] == "stream:dead_letter" and manifest["groups"] == []
    assert [entry_id for entry_id, _ in entries] == [b"1-0", b"2-0", b"3-0"]


async def test_dead_letter_retention_refuses_when_a_group_reads_it(archive):
    redis = LuaStreams()
    redis.add("stream:dead_letter", "1-0", "event_id", "e")
    redis.create_group("stream:dead_letter", "operator-reader")
    op = StreamRetention(redis, dead_letter_policy(min_age_seconds=60, min_free_bytes=1024**2), archive)
    with pytest.raises(RetentionRefused) as error:
        await op.run(mode="apply")
    assert error.value.reason == "retention_group_count"
    assert await redis.xlen("stream:dead_letter") == 1


@pytest.mark.parametrize("policy", [
    lambda: dead_letter_policy(min_age_seconds=60, min_free_bytes=1024**2),
    lambda: RetentionPolicy(stream=STREAM, groups=(GROUP,), min_age_seconds=60, min_free_bytes=1024**2),
])
async def test_absent_stream_is_a_no_op_not_a_refusal(archive, policy):
    op = StreamRetention(LuaStreams(), policy(), archive)
    result = await op.run(mode="apply")
    assert result["deleted"] == 0 and result["stop"] == "stream_absent"
    assert not list(archive.root.iterdir())


@pytest.mark.parametrize("groups,stream", [((), STREAM), ((GROUP,), "stream:dead_letter")])
def test_policy_requires_groups_exactly_for_domain_streams(groups, stream):
    with pytest.raises(ValueError):
        RetentionPolicy(stream=stream, groups=groups, min_age_seconds=60)


async def test_janitor_lua_deletes_only_idle_consumers_without_pending():
    redis = seed(ack=False)
    group = redis.groups[STREAM.encode()][GROUP.encode()]
    group.consumers[b"old"] = 0  # idle since the epoch, no pending
    group.consumers[b"fresh"] = 10**13  # idle is negative/small: alive
    assert await redis.eval(_DELETE_IDLE_CONSUMER, 1, STREAM, GROUP, "old", 3_600_000) == 0
    assert b"old" not in group.consumers
    assert await redis.eval(_DELETE_IDLE_CONSUMER, 1, STREAM, GROUP, "fresh", 3_600_000) == -1
    group.consumers[b"api-host"] = 0  # idle, but holds the five pending entries
    assert await redis.eval(_DELETE_IDLE_CONSUMER, 1, STREAM, GROUP, "api-host", 3_600_000) == -1
    assert len(group.pending) == 5
    assert await redis.eval(_DELETE_IDLE_CONSUMER, 1, STREAM, GROUP, "missing", 3_600_000) == -2


@pytest.mark.parametrize("exc,reason", [
    (ResponseError("ERR Error running script: retention_boundary_changed"), "retention_boundary_changed"),
    (ResponseError("WRONGTYPE"), "redis_response_error"),
    (RetentionRefused("unsafe_eviction_policy", "durable streams require noeviction"), "unsafe_eviction_policy"),
    (ValueError("archive_disk_admission"), "archive_disk_admission"),
    (ValueError("archive root requires owner mode0700"), "archive_root_unprotected"),
    (BlockingIOError(), "archive_locked"), (OSError("disk"), "archive_io_failed"),
    (KeyError("STREAM_RETENTION_REDIS_URL"), "missing_environment"), (TimeoutError(), "timeout"),
    (ValueError("something new"), "precondition_failed"),
])
def test_refusal_reasons_are_machine_readable(exc, reason):
    assert refusal_reason(exc) == reason
    json.dumps(reason)
