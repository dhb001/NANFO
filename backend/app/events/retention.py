"""ADR027/ADR-028 bounded archive-before-delete for durable domain streams and the DLQ.

Eligibility assumes enrolled groups use XREADGROUP without NOACK, ACK only after
durable handling, and never skip/reset cursors or destroy consumers with pending
work. Redis has no historical ACK ledger: administrative violations are not provable
from a PEL. Unknown groups/state fail closed. Races that invalidate a planned batch
(cursor moved backwards, entry now pending or changed) refuse that batch and it is
re-planned from current state a bounded number of times; harmless concurrency (ACKs,
new consumers, appends) no longer aborts. The dead-letter stream has no consumer
groups: its entries are eligible by age alone and are archived before deletion.

Refusals carry a stable machine-readable ``reason`` (see :func:`refusal_reason`).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
from contextlib import nullcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from redis.asyncio import Redis

from redis.exceptions import RedisError, ResponseError

from app.events.bus import DEAD_LETTER_STREAM, STREAM_GROUPS
from app.events.retention_archive import MAX_BUNDLE_BYTES, StreamArchive
from app.events.retention_lua import DELETE, PLAN, RESTORE, RETRYABLE_REFUSALS

RETAINED_STREAMS = frozenset({*STREAM_GROUPS, DEAD_LETTER_STREAM})
MAX_PENDING_CONSUMERS = 64
MARKER_PATTERN = "event:completed:*"


class RetentionRefused(ValueError):
    """A precondition refused retention; ``reason`` is machine-readable."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason


_VALUE_REASONS = (
    ("archive_disk_admission", "archive_disk_admission"),
    ("archive root requires owner mode0700", "archive_root_unprotected"),
    ("unprotected archive ancestor", "archive_root_unprotected"),
    ("absolute private archive root required", "archive_root_invalid"),
    ("archive path identity changed", "archive_path_changed"),
    ("archive verification failed", "archive_verification_failed"),
    ("archive readback mismatch", "archive_verification_failed"),
    ("archive checksum mismatch", "archive_verification_failed"),
    ("archive bundle", "archive_bundle_invalid"),
    ("archive file protection or size invalid", "archive_file_invalid"),
    ("invalid archive", "archive_invalid"),
    ("archive manifest mismatch", "archive_invalid"),
    ("archive source stream mismatch", "archive_stream_mismatch"),
    ("durable streams require noeviction", "unsafe_eviction_policy"),
    ("unknown group count", "retention_group_count"),
    ("consumer groups on a group-less stream", "retention_unknown_groups"),
    ("explicit dry-run/apply", "invalid_mode"),
    ("archive and isolated recovery", "invalid_recovery_target"),
    ("archive required", "archive_required"),
)


def refusal_reason(exc: BaseException) -> str:
    """Stable reason code for an exception; never includes exception text."""
    if isinstance(exc, RetentionRefused):
        return exc.reason
    if isinstance(exc, ResponseError):
        match = re.search(r"retention_[a-z_]+", str(exc))
        return match.group(0) if match else "redis_response_error"
    if isinstance(exc, RedisError):
        return "redis_unavailable"
    if isinstance(exc, BlockingIOError):
        return "archive_locked"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, OSError):
        return "archive_io_failed"
    if isinstance(exc, KeyError):
        return "missing_environment"
    if isinstance(exc, ValueError):
        text = str(exc)
        if "validation error" in text:
            return "invalid_policy"
        for needle, reason in _VALUE_REASONS:
            if needle in text:
                return reason
        return "precondition_failed"
    return "unexpected_failure"


async def completion_marker_count(redis: Redis, *, limit: int = 100000, page: int = 1000) -> dict:
    """Bounded SCAN count of bus completion markers (diagnostics only)."""
    count, cursor, scanned = 0, 0, 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=MARKER_PATTERN, count=page)
        count += len(keys)
        scanned += 1
        if not cursor or count >= limit or scanned * page >= limit:
            # Examines at most ``limit`` keys; ``capped`` means the count is a lower bound.
            return {"completion_markers": min(count, limit), "capped": bool(cursor)}


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    stream: str
    groups: tuple[str, ...]
    min_age_seconds: int = Field(ge=60, le=315360000)
    batch_size: int = Field(default=100, ge=1, le=100)
    max_batches: int = Field(default=10, ge=1, le=1000)
    max_entries: int = Field(default=1000, ge=1, le=100000)
    max_seconds: int = Field(default=30, ge=1, le=300)
    max_archive_bytes: int = Field(default=16 * 1024 * 1024, ge=1, le=1024**3)
    min_free_bytes: int = Field(default=1024**3, ge=1024**2, le=1024**5)
    memory_warn_ratio: float = Field(default=0.8, gt=0, le=1)
    lag_warn_entries: int = Field(default=10000, ge=1)
    pending_warn_seconds: int = Field(default=3600, ge=1)

    max_delete_attempts: int = Field(default=3, ge=1, le=10)

    @field_validator('stream')
    @classmethod
    def domain_stream(cls, value):
        if value not in RETAINED_STREAMS:
            raise ValueError('registered domain stream or dead-letter stream required; fanout excluded')
        return value

    @field_validator('groups')
    @classmethod
    def known_groups(cls, value):
        if (not 0 <= len(value) <= 64 or len(set(value)) != len(value)
                or any(not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}', item) for item in value)):
            raise ValueError('explicit unique group allowlist required')
        return tuple(sorted(value))

    @model_validator(mode='after')
    def groups_match_stream_kind(self):
        # Domain streams always have consumer groups; the DLQ never does.
        if (self.stream == DEAD_LETTER_STREAM) != (not self.groups):
            raise ValueError('explicit unique group allowlist required')
        return self

    @property
    def group_less(self) -> bool:
        return not self.groups


def dead_letter_policy(**overrides) -> 'RetentionPolicy':
    return RetentionPolicy(stream=DEAD_LETTER_STREAM, groups=(), **overrides)


def _ascii(value) -> str:
    return value.decode('ascii') if isinstance(value, bytes) else str(value)


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def entry_arguments(entries):
    return [part for entry_id, fields in entries for part in (entry_id, len(fields), *fields)]


def encode_bundle(policy, cutoff, state, entries):
    encoded = [[entry_id.decode('ascii'),
                [base64.b64encode(field).decode('ascii') for field in fields]]
               for entry_id, fields in entries]
    payload = canonical(encoded)
    bundle = canonical({
        'format': 'nanfo-domain-stream-archive-v1',
        'manifest': {'stream': policy.stream, 'groups': list(policy.groups),
                     'cutoff_exclusive': cutoff, 'state_base64': base64.b64encode(state).decode('ascii'),
                     'count': len(entries), 'first_id': encoded[0][0], 'last_id': encoded[-1][0],
                     'entries_sha256': hashlib.sha256(payload).hexdigest(),
                     'entries_bytes': len(payload), 'status': 'archived_before_delete'},
        'entries': encoded,
    })
    if len(bundle) > MAX_BUNDLE_BYTES:
        raise ValueError('archive bundle exceeds bound')
    return bundle


def decode_bundle(data):
    """Validate version, canonical manifest, exact-byte payload hash and ID order."""
    value = json.loads(data)
    if (not isinstance(value, dict) or canonical(value) != data
            or value.get('format') != 'nanfo-domain-stream-archive-v1'):
        raise ValueError('invalid archive format')
    manifest, encoded = value['manifest'], value['entries']
    if (not isinstance(manifest, dict) or not isinstance(encoded, list)
            or any(not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str)
                   or not isinstance(row[1], list) or any(not isinstance(field, str) for field in row[1])
                   for row in encoded)):
        raise ValueError('invalid archive structure')
    payload = canonical(encoded)
    if (manifest['stream'] not in RETAINED_STREAMS or not 1 <= len(encoded) <= 100
            or manifest['count'] != len(encoded) or manifest['first_id'] != encoded[0][0]
            or manifest['last_id'] != encoded[-1][0] or manifest['entries_bytes'] != len(payload)
            or manifest['entries_sha256'] != hashlib.sha256(payload).hexdigest()):
        raise ValueError('archive manifest mismatch')
    previous = (0, 0)
    entries = []
    for entry_id, fields in encoded:
        if not re.fullmatch(r'(0|[1-9][0-9]*)-(0|[1-9][0-9]*)', entry_id):
            raise ValueError('invalid archive entry id')
        identity = tuple(map(int, entry_id.split('-')))
        if identity <= previous or any(part > 2**64 - 1 for part in identity):
            raise ValueError('invalid archive entry order')
        raw = [base64.b64decode(field, validate=True) for field in fields]
        if not raw or len(raw) > 256 or len(raw) % 2 or len(entry_id) + sum(map(len, raw)) > 65536:
            raise ValueError('invalid archive entry fields')
        entries.append((entry_id.encode('ascii'), raw))
        previous = identity
    return manifest, entries


class StreamRetention:
    def __init__(self, redis: Redis, policy: RetentionPolicy, archive: StreamArchive | None = None):
        # Lua returns raw arrays, preserving repeated field names and invalid UTF-8.
        if redis.connection_pool.connection_kwargs.get('decode_responses', False):
            raise ValueError('retention requires decode_responses=False')
        self.redis, self.policy, self.archive = redis, policy, archive

    async def _require_group_less(self):
        if self.policy.group_less and await self.redis.xinfo_groups(self.policy.stream):
            raise RetentionRefused('retention_unknown_groups', 'consumer groups on a group-less stream')

    async def diagnostics(self):
        """Bounded read-only health sample; errors are unknown, never healthy."""
        p = self.policy
        memory = await self.redis.info('memory')
        used, maximum = memory['used_memory'], memory['maxmemory']
        try:
            info = await self.redis.xinfo_stream(p.stream)
        except ResponseError:
            if not p.group_less:
                raise
            info = {'groups': 0, 'length': 0, 'first-entry': None}  # DLQ not created yet
        expected = (0, 0) if p.group_less else (1, 64)
        if not expected[0] <= info['groups'] <= expected[1]:
            raise RetentionRefused('retention_group_count', 'unknown group count')
        groups = await self.redis.xinfo_groups(p.stream) if info['groups'] else []
        alerts = []
        if tuple(sorted(g['name'].decode('ascii') for g in groups)) != p.groups:
            alerts.append('unknown_groups')
        details = []
        now = int(time.time() * 1000)
        for g in groups:
            pending = await self.redis.xpending(p.stream, g['name'])
            holders = len(pending.get('consumers') or ())
            if holders > MAX_PENDING_CONSUMERS:
                # Only consumers that hold pending entries are bounded (ADR-028).
                alerts.append('pending_consumers_exceed_bound')
            if g['consumers'] > MAX_PENDING_CONSUMERS:
                alerts.append('consumer_churn')
            first = pending['min']
            age = max(0, (now - int(first.split(b'-')[0])) // 1000) if first else None
            idle = None
            if first:
                sample = await self.redis.xpending_range(p.stream, g['name'], first, first, 1)
                idle = sample[0]['time_since_delivered'] if sample else None
            lag = g.get('lag')
            if lag is None or g.get('entries-read') is None:
                alerts.append('unknown_group_state')
            elif lag >= p.lag_warn_entries:
                alerts.append('consumer_lag')
            if age is not None and age >= p.pending_warn_seconds:
                alerts.append('old_pending_entry')
            details.append({'name': g['name'].decode('ascii'), 'pending': pending['pending'],
                            'consumers': g['consumers'], 'pending_consumers': holders,
                            'lag': lag, 'last_delivered_id': g['last-delivered-id'].decode('ascii'),
                            'oldest_pending_age_seconds': age, 'oldest_pending_idle_ms': idle})
        ratio = used / maximum if maximum else None
        if ratio is None:
            alerts.append('redis_capacity_unbounded')
        elif ratio >= p.memory_warn_ratio:
            alerts.append('redis_memory_pressure')
        if memory.get('maxmemory_policy') != 'noeviction':
            alerts.append('unsafe_eviction_policy')
        free = self.archive.free_bytes() if self.archive else None
        if free is not None and free < p.min_free_bytes + MAX_BUNDLE_BYTES:
            alerts.append('archive_disk_pressure')
        first = info['first-entry']
        return {'status': 'warning' if alerts else 'ok', 'alerts': sorted(set(alerts)),
                'stream': p.stream, 'length': info['length'], 'groups': details,
                'oldest_entry_age_seconds': max(0, (now - int(first[0].split(b'-')[0])) // 1000)
                if first else None,
                'redis_used_bytes': used, 'redis_max_bytes': maximum, 'redis_memory_ratio': ratio,
                'archive_free_bytes': free, 'archive_min_free_bytes': p.min_free_bytes}

    async def run(self, *, mode: Literal['dry-run', 'apply']):
        if mode not in {'dry-run', 'apply'} or (mode == 'apply' and self.archive is None):
            raise RetentionRefused('invalid_mode', 'explicit dry-run/apply and apply archive required')
        p = self.policy
        start = time.monotonic()
        async with asyncio.timeout(p.max_seconds):
            seconds, micros = await self.redis.time()
            present = await self.redis.exists(p.stream)
        cutoff = f'{seconds * 1000 + micros // 1000 - p.min_age_seconds * 1000}-0'
        result = {'mode': mode, 'stream': p.stream, 'cutoff_exclusive': cutoff,
                  'batches': 0, 'entries': 0, 'deleted': 0, 'archive_bytes': 0,
                  'archives': [], 'stop': 'max_batches'}
        if not present:
            # Nothing was ever appended (or the API has not provisioned it yet).
            result.update(stop='stream_absent', health={'status': 'ok', 'alerts': []},
                          elapsed_seconds=round(time.monotonic() - start, 3))
            return result
        # Total budget includes diagnostics, archive I/O and Redis round trips.
        deadline = start + p.max_seconds
        cursor = '-'
        lock = self.archive.exclusive() if mode == 'apply' else nullcontext()
        with lock:
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                result['health'] = await self.diagnostics()
                if mode == 'apply' and 'unsafe_eviction_policy' in result['health']['alerts']:
                    raise RetentionRefused('unsafe_eviction_policy', 'durable streams require noeviction')
                retries = 0
                batch = 0
                while batch < p.max_batches:
                    if time.monotonic() >= deadline:
                        result['stop'] = 'max_seconds'
                        break
                    remaining = p.max_entries - result['entries']
                    if remaining <= 0:
                        result['stop'] = 'max_entries'
                        break
                    await self._require_group_less()
                    state, entries, groups = await self.redis.eval(
                        PLAN, 1, p.stream, json.dumps(p.groups), cursor, cutoff,
                        min(p.batch_size, remaining))
                    if not entries:
                        result['stop'] = 'no_eligible_entries'
                        break
                    data = encode_bundle(p, cutoff, state, entries)
                    if result['archive_bytes'] + len(data) > p.max_archive_bytes:
                        result['stop'] = 'max_archive_bytes'
                        break
                    if mode == 'apply':
                        digest = self.archive.write(data, min_free_bytes=p.min_free_bytes)
                        # Archive + manifest are one atomic bundle. Re-read immediately
                        # before deletion; an interrupted call can leave a safe orphan.
                        if self.archive.read(digest) != data:
                            raise RetentionRefused('archive_verification_failed', 'archive verification failed')
                        result['archives'].append(digest)
                        if time.monotonic() >= deadline:
                            result['stop'] = 'max_seconds'
                            break
                        planned = json.dumps([[_ascii(g[0]), _ascii(g[1])] for g in groups or ()])
                        try:
                            await self._require_group_less()
                            result['deleted'] += await self.redis.eval(
                                DELETE, 1, p.stream, json.dumps(p.groups), planned, cutoff,
                                len(entries), *entry_arguments(entries))
                        except ResponseError as exc:
                            reason = refusal_reason(exc)
                            if reason not in RETRYABLE_REFUSALS or retries + 1 >= p.max_delete_attempts:
                                raise
                            # Re-plan the same range from current state (bounded).
                            retries += 1
                            result['replans'] = retries
                            result['archive_bytes'] += len(data)
                            continue
                    batch += 1
                    result['batches'] += 1
                    result['entries'] += len(entries)
                    result['archive_bytes'] += len(data)
                    cursor = '(' + entries[-1][0].decode('ascii')
                else:
                    result['stop'] = 'max_batches'
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        return result

    async def restore(self, digest: str, target: str):
        """Restore one verified bundle into an isolated, group-free recovery stream."""
        if self.archive is None or not re.fullmatch(r'recovery:[A-Za-z0-9:_-]{1,128}', target):
            raise RetentionRefused('invalid_recovery_target', 'archive and isolated recovery: target required')
        async with asyncio.timeout(self.policy.max_seconds):
            with self.archive.exclusive():
                manifest, entries = decode_bundle(self.archive.read(digest))
                if manifest['stream'] != self.policy.stream:
                    raise RetentionRefused('archive_stream_mismatch', 'archive source stream mismatch')
                return await self.redis.eval(RESTORE, 1, target, len(entries), *entry_arguments(entries))
