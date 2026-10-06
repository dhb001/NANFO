"""ADR-028 C14 dead-letter operator tool: bounded redacted list, atomic replay, purge."""

import json
from types import SimpleNamespace

import fakeredis
import pytest
from redis.exceptions import ResponseError

from app.events.bus import DEAD_LETTER_STREAM, process_entry
from app.events.retention import decode_bundle
from app.events.retention_archive import StreamArchive
from scripts import dead_letter
from tests.lua_streams import LuaStreams

SECRET = "payload-secret-value"


@pytest.fixture
def redis():
    return fakeredis.FakeAsyncRedis()


async def dead_letter_one(redis, *, reason_error=ValueError, event_type="intent.validated"):
    """Produce a real DLQ entry through the bus (deterministic handler failure)."""
    async def handler(event):
        raise reason_error(SECRET)

    event = {"event_id": "00000000-0000-0000-0000-000000000001", "event_type": event_type,
             "source": "intent", "version": "1", "timestamp": "2026-09-23T00:00:00+00:00",
             "correlation_id": "c", "payload": json.dumps({"password": SECRET})}
    await redis.xgroup_create("stream:intent", "nanfo-consumers", id="0", mkstream=True)
    entry_id = await redis.xadd("stream:intent", event)
    await process_entry(redis, "stream:intent", "nanfo-consumers", entry_id, event, {event_type: handler})
    [(dlq_id, _)] = await redis.xrange(DEAD_LETTER_STREAM)
    return dlq_id.decode(), entry_id, event


async def test_list_is_bounded_and_redacted(redis):
    dlq_id, entry_id, _ = await dead_letter_one(redis)
    result = await dead_letter.list_entries(redis, count=5)
    [row] = result["entries"]
    assert row["id"] == dlq_id and row["failed_stream"] == "stream:intent"
    assert row["failure_reason"] == "handler_failed_deterministic" and row["error_type"] == "ValueError"
    assert row["failed_entry_id"] == entry_id.decode() and row["payload_bytes"] > 0
    assert SECRET not in json.dumps(result) and "payload" not in row and "correlation_id" not in row
    for count in (0, dead_letter.MAX_LIST + 1):
        with pytest.raises(ValueError):
            await dead_letter.list_entries(redis, count=count)


async def test_replay_reappends_original_envelope_then_removes_dlq_entry(redis):
    dlq_id, _, event = await dead_letter_one(redis)
    result = await dead_letter.replay_entries(redis, [dlq_id])
    [row] = result["results"]
    assert row["status"] == "replayed" and row["stream"] == "stream:intent"
    assert await redis.xlen(DEAD_LETTER_STREAM) == 0
    [(replayed_id, fields)] = [item for item in await redis.xrange("stream:intent") if item[0].decode() == row["replayed_id"]]
    decoded = {key.decode(): value.decode() for key, value in fields.items()}
    for name, value in event.items():
        assert decoded[name] == value  # original envelope bytes, including payload
    assert decoded["replayed_from"] == dlq_id and decoded["replay_count"] == "1"
    assert not set(dead_letter.DLQ_METADATA) & set(decoded)
    again = await dead_letter.replay_entries(redis, [dlq_id])
    assert again["results"] == [{"id": dlq_id, "status": "missing"}]


async def test_failed_append_keeps_the_dead_letter_entry():
    # Real replay Lua on the stream model: an error reply from XADD aborts the script.
    redis = LuaStreams()
    redis.add(DEAD_LETTER_STREAM, "7-0", "event_id", "e", "failed_stream", "stream:intent",
              "failure_reason", "max_deliveries_exceeded", "payload", "{}")
    redis.failing.add(b"XADD")
    with pytest.raises(ResponseError):
        await dead_letter.replay_entries(redis, ["7-0"])
    assert await redis.xlen(DEAD_LETTER_STREAM) == 1 and await redis.xlen("stream:intent") == 0
    redis.failing.clear()
    result = await dead_letter.replay_entries(redis, ["7-0"])
    assert result["results"][0]["status"] == "replayed"
    assert await redis.xlen(DEAD_LETTER_STREAM) == 0 and await redis.xlen("stream:intent") == 1


async def test_replay_refuses_unknown_streams_and_deterministic_envelopes(redis):
    await redis.xadd(DEAD_LETTER_STREAM, {"event_id": "e", "failed_stream": "stream:unregistered",
                                          "failure_reason": "handler_failed_deterministic"}, id="5-0")
    await redis.xadd(DEAD_LETTER_STREAM, {"event_id": "e", "failed_stream": "stream:intent",
                                          "failure_reason": "malformed_envelope", "payload": b"\xff"}, id="6-0")
    result = await dead_letter.replay_entries(redis, ["5-0", "6-0"])
    assert [row["reason"] for row in result["results"]] == ["unknown_source_stream", "deterministic_failure"]
    assert await redis.xlen(DEAD_LETTER_STREAM) == 2
    forced = await dead_letter.replay_entries(redis, ["6-0"], force=True)
    assert forced["results"][0]["status"] == "replayed"
    [(_, fields)] = await redis.xrange("stream:intent")
    assert fields[b"payload"] == b"\xff"  # poison bytes preserved exactly
    with pytest.raises(ValueError):
        await dead_letter.replay_entries(redis, ["not-an-id"])


async def test_purge_archives_before_deleting_old_entries(tmp_path):
    root = tmp_path / "archive"
    root.mkdir(mode=0o700)
    redis = LuaStreams()
    redis.add(DEAD_LETTER_STREAM, "1-0", "event_id", "old", "failure_reason", "max_deliveries_exceeded")
    redis.add(DEAD_LETTER_STREAM, f"{2**62}-0", "event_id", "young")
    result = await dead_letter.purge_entries(redis, archive_root=root, older_than_seconds=3600,
                                             min_free_bytes=1024**2)
    assert result["deleted"] == 1 and await redis.xlen(DEAD_LETTER_STREAM) == 1
    manifest, entries = decode_bundle(StreamArchive(root).read(result["archives"][0]))
    assert manifest["stream"] == DEAD_LETTER_STREAM and entries[0][0] == b"1-0"
    dry = await dead_letter.purge_entries(redis, archive_root=root, older_than_seconds=60,
                                          min_free_bytes=1024**2, dry_run=True)
    assert dry["deleted"] == 0 and dry["mode"] == "dry-run"


def test_cli_errors_are_machine_readable(capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("DEAD_LETTER_REDIS_URL", raising=False)
    monkeypatch.delenv("STREAM_RETENTION_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_HOST", raising=False)
    assert dead_letter.main(["list"]) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "refused_or_incomplete",
                                                   "reason": "missing_environment"}
    with pytest.raises(SystemExit):
        dead_letter.parser().parse_args(["purge", "--older-than-seconds", "60"])  # archive root required


async def test_execute_dispatches_with_injected_client(redis):
    await dead_letter_one(redis)
    result = await dead_letter.execute(SimpleNamespace(command="list", count=1, start="-"), redis=redis)
    assert result["total"] == 1 and len(result["entries"]) == 1
