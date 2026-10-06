"""Dead-letter stream operator tool (ADR-028 C14).

From backend: poetry run python -m scripts.dead_letter {list,replay,purge} --help

  list    bounded, redacted listing: routing metadata, failure reason/handler/type
          and payload size only; never payload contents or other fields.
  replay  atomically re-appends the original envelope to its source stream with
          replay metadata and deletes the DLQ entry in the same Lua script (the entry
          is only removed if the append succeeded).
  purge   archive-before-delete of entries older than --older-than-seconds using
          the domain-stream retention archive (StreamArchive bundles).

Redis credentials come only from the environment (DEAD_LETTER_REDIS_URL, else
STREAM_RETENTION_REDIS_URL, else REDIS_HOST/REDIS_PORT/REDIS_PASSWORD/REDIS_DB).
Output is JSON; failures print a machine-readable ``reason`` and never secrets.
"""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

from redis.exceptions import RedisError

from app.events.bus import DEAD_LETTER_STREAM, STREAM_GROUPS
from app.events.retention import RetentionRefused, StreamRetention, dead_letter_policy, refusal_reason
from app.events.retention_archive import StreamArchive
from scripts.stream_retention import connect, redis_url_from_environment

MAX_LIST = 100
MAX_REPLAY = 100
_ENTRY_ID = re.compile(r"(0|[1-9][0-9]*)-(0|[1-9][0-9]*)")
DLQ_METADATA = ("failed_entry_id", "failed_stream", "failed_group", "failure_reason",
                "failed_handler", "delivery_count", "error_type")
_LISTED = ("event_id", "event_type", "timestamp", "source", "version", *DLQ_METADATA)
# Envelope-level rejections would be dead-lettered again unchanged.
DETERMINISTIC_REASONS = frozenset({"malformed_envelope", "unsupported_version", "invalid_payload"})
_HANDLED = (ValueError, OSError, KeyError, TypeError, RedisError, TimeoutError)

# KEYS[1] = DLQ, KEYS[2] = destination stream; ARGV[1] = DLQ entry id.
_REPLAY = """
local rows = redis.call('XRANGE', KEYS[1], ARGV[1], ARGV[1], 'COUNT', 1)
if #rows == 0 then return {0, ''} end
local fields = rows[1][2]
local meta = {}
for i = 1, #fields, 2 do meta[fields[i]] = fields[i + 1] end
if meta['failed_stream'] ~= KEYS[2] then return {-1, ''} end
local skip = {failed_entry_id=1, failed_stream=1, failed_group=1, failure_reason=1,
              failed_handler=1, delivery_count=1, error_type=1, replayed_from=1, replay_count=1}
local envelope = {}
for i = 1, #fields, 2 do
    if not skip[fields[i]] then
        envelope[#envelope + 1] = fields[i]
        envelope[#envelope + 1] = fields[i + 1]
    end
end
local count = tonumber(meta['replay_count'] or '0') or 0
envelope[#envelope + 1] = 'replayed_from'
envelope[#envelope + 1] = ARGV[1]
envelope[#envelope + 1] = 'replay_count'
envelope[#envelope + 1] = tostring(count + 1)
local id = redis.call('XADD', KEYS[2], '*', unpack(envelope))
redis.call('XDEL', KEYS[1], ARGV[1])
return {1, id}
"""


def parser():
    value = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = value.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--count", type=int, default=20)
    listing.add_argument("--start", default="-")
    replay = commands.add_parser("replay")
    replay.add_argument("--id", action="append", required=True, dest="ids")
    replay.add_argument("--force", action="store_true",
                        help="also replay envelope-level (deterministic) rejections")
    purge = commands.add_parser("purge")
    purge.add_argument("--older-than-seconds", type=int, required=True)
    purge.add_argument("--archive-root", type=Path, required=True)
    purge.add_argument("--max-entries", type=int, default=1000)
    purge.add_argument("--min-free-bytes", type=int, default=1024**3)
    purge.add_argument("--dry-run", action="store_true")
    return value


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _entry_id(value: str) -> str:
    if not _ENTRY_ID.fullmatch(value or ""):
        raise RetentionRefused("invalid_entry_id")
    return value


def redacted(entry_id, fields: dict) -> dict:
    decoded = {_text(key): value for key, value in fields.items()}
    row = {"id": _text(entry_id)}
    for name in _LISTED:
        if name in decoded:
            row[name] = _text(decoded[name])[:256]
    payload = decoded.get("payload")
    row["payload_bytes"] = len(payload) if isinstance(payload, (bytes, str)) else 0
    return row


async def list_entries(redis, *, count: int = 20, start: str = "-") -> dict:
    if not 1 <= count <= MAX_LIST:
        raise RetentionRefused("list_count_out_of_bounds")
    if start != "-":
        _entry_id(start.removeprefix("("))
    rows = await redis.xrange(DEAD_LETTER_STREAM, min=start, max="+", count=count)
    return {"command": "list", "stream": DEAD_LETTER_STREAM, "total": await redis.xlen(DEAD_LETTER_STREAM),
            "entries": [redacted(entry_id, fields) for entry_id, fields in rows]}


async def replay_entries(redis, ids: list[str], *, force: bool = False) -> dict:
    if not 1 <= len(ids) <= MAX_REPLAY:
        raise RetentionRefused("replay_count_out_of_bounds")
    results = []
    for entry_id in ids:
        entry_id = _entry_id(entry_id)
        rows = await redis.xrange(DEAD_LETTER_STREAM, min=entry_id, max=entry_id, count=1)
        if not rows:
            results.append({"id": entry_id, "status": "missing"})
            continue
        fields = {_text(key): _text(value) for key, value in rows[0][1].items()}
        stream, reason = fields.get("failed_stream", ""), fields.get("failure_reason", "")
        if stream not in STREAM_GROUPS:
            results.append({"id": entry_id, "status": "refused", "reason": "unknown_source_stream"})
            continue
        if reason in DETERMINISTIC_REASONS and not force:
            results.append({"id": entry_id, "status": "refused", "reason": "deterministic_failure"})
            continue
        outcome, new_id = await redis.eval(_REPLAY, 2, DEAD_LETTER_STREAM, stream, entry_id)
        status = {1: "replayed", 0: "missing", -1: "refused"}[int(outcome)]
        row = {"id": entry_id, "status": status, "stream": stream}
        if status == "replayed":
            row["replayed_id"] = _text(new_id)
        results.append(row)
    return {"command": "replay", "results": results}


async def purge_entries(redis, *, archive_root: Path, older_than_seconds: int, max_entries: int = 1000,
                        min_free_bytes: int = 1024**3, dry_run: bool = False) -> dict:
    policy = dead_letter_policy(min_age_seconds=older_than_seconds, max_entries=max_entries,
                                max_batches=1000, min_free_bytes=min_free_bytes)
    operator = StreamRetention(redis, policy, StreamArchive(archive_root))
    result = await operator.run(mode="dry-run" if dry_run else "apply")
    return {"command": "purge", "mode": result["mode"], "deleted": result["deleted"],
            "entries": result["entries"], "archives": result["archives"], "stop": result["stop"]}


async def execute(args, *, redis=None) -> dict:
    owned = redis is None
    if owned:
        url = os.environ.get("DEAD_LETTER_REDIS_URL") or redis_url_from_environment()
        redis = connect(url)
    try:
        if args.command == "list":
            return await list_entries(redis, count=args.count, start=args.start)
        if args.command == "replay":
            return await replay_entries(redis, args.ids, force=args.force)
        return await purge_entries(redis, archive_root=args.archive_root,
                                   older_than_seconds=args.older_than_seconds, max_entries=args.max_entries,
                                   min_free_bytes=args.min_free_bytes, dry_run=args.dry_run)
    finally:
        if owned:
            await redis.aclose()


def main(argv=None, *, redis=None) -> int:
    args = parser().parse_args(argv)
    try:
        result = asyncio.run(execute(args, redis=redis))
    except _HANDLED as exc:
        print(json.dumps({"status": "refused_or_incomplete", "reason": refusal_reason(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
