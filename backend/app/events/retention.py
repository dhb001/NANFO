"""ADR027 bounded operator-only archive-before-delete for durable domain streams.

Eligibility assumes enrolled groups use XREADGROUP without NOACK, ACK only after
durable handling, and never skip/reset cursors or destroy consumers with pending
work. Redis has no historical ACK ledger: administrative violations are not provable
from a PEL. Unknown group/state and all observed state races fail closed.
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

from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.asyncio import Redis

from app.events.bus import STREAM_GROUPS
from app.events.retention_archive import MAX_BUNDLE_BYTES, StreamArchive
from app.events.retention_lua import DELETE, PLAN, RESTORE


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

    @field_validator('stream')
    @classmethod
    def domain_stream(cls, value):
        if value not in STREAM_GROUPS:
            raise ValueError('registered domain stream required; DLQ/fanout excluded')
        return value

    @field_validator('groups')
    @classmethod
    def known_groups(cls, value):
        if (not 1 <= len(value) <= 64 or len(set(value)) != len(value)
                or any(not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}', item) for item in value)):
            raise ValueError('explicit unique group allowlist required')
        return tuple(sorted(value))


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
    if (manifest['stream'] not in STREAM_GROUPS or not 1 <= len(encoded) <= 100
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

    async def diagnostics(self):
        """Bounded read-only health sample; errors are unknown, never healthy."""
        p = self.policy
        memory = await self.redis.info('memory')
        used, maximum = memory['used_memory'], memory['maxmemory']
        info = await self.redis.xinfo_stream(p.stream)
        if not 1 <= info['groups'] <= 64:
            raise ValueError('unknown group count')
        groups = await self.redis.xinfo_groups(p.stream)
        alerts = []
        if tuple(sorted(g['name'].decode('ascii') for g in groups)) != p.groups:
            alerts.append('unknown_groups')
        details = []
        now = int(time.time() * 1000)
        for g in groups:
            if g['consumers'] > 64:
                raise ValueError('consumer count exceeds diagnostic bound')
            pending = await self.redis.xpending(p.stream, g['name'])
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
            raise ValueError('explicit dry-run/apply and apply archive required')
        p = self.policy
        start = time.monotonic()
        async with asyncio.timeout(p.max_seconds):
            seconds, micros = await self.redis.time()
        cutoff = f'{seconds * 1000 + micros // 1000 - p.min_age_seconds * 1000}-0'
        result = {'mode': mode, 'stream': p.stream, 'cutoff_exclusive': cutoff,
                  'batches': 0, 'entries': 0, 'deleted': 0, 'archive_bytes': 0,
                  'archives': [], 'stop': 'max_batches'}
        # Total budget includes diagnostics, archive I/O and Redis round trips.
        deadline = start + p.max_seconds
        cursor = '-'
        lock = self.archive.exclusive() if mode == 'apply' else nullcontext()
        with lock:
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                result['health'] = await self.diagnostics()
                if mode == 'apply' and 'unsafe_eviction_policy' in result['health']['alerts']:
                    raise ValueError('durable streams require noeviction')
                for _ in range(p.max_batches):
                    if time.monotonic() >= deadline:
                        result['stop'] = 'max_seconds'
                        break
                    remaining = p.max_entries - result['entries']
                    if remaining <= 0:
                        result['stop'] = 'max_entries'
                        break
                    state, entries, _ = await self.redis.eval(
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
                            raise ValueError('archive verification failed')
                        result['archives'].append(digest)
                        if time.monotonic() >= deadline:
                            result['stop'] = 'max_seconds'
                            break
                        result['deleted'] += await self.redis.eval(
                            DELETE, 1, p.stream, json.dumps(p.groups), state, cutoff,
                            len(entries), *entry_arguments(entries))
                    result['batches'] += 1
                    result['entries'] += len(entries)
                    result['archive_bytes'] += len(data)
                    cursor = '(' + entries[-1][0].decode('ascii')
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        return result

    async def restore(self, digest: str, target: str):
        """Restore one verified bundle into an isolated, group-free recovery stream."""
        if self.archive is None or not re.fullmatch(r'recovery:[A-Za-z0-9:_-]{1,128}', target):
            raise ValueError('archive and isolated recovery: target required')
        async with asyncio.timeout(self.policy.max_seconds):
            with self.archive.exclusive():
                manifest, entries = decode_bundle(self.archive.read(digest))
                if manifest['stream'] != self.policy.stream:
                    raise ValueError('archive source stream mismatch')
                return await self.redis.eval(RESTORE, 1, target, len(entries), *entry_arguments(entries))
