"""Bounded ADR027/ADR-028 stream retention operator (archive-before-delete).

From backend: poetry run python -m scripts.stream_retention --help

One-shot modes (operator): dry-run | apply | health | restore, as before.
Supervised mode (C14): ``schedule`` runs continuously and is configured purely by
environment variables:

  NANFO_STREAM_ARCHIVE_ROOT                   required; private (0700) archive directory
  NANFO_STREAM_RETENTION_INTERVAL_SECONDS     cycle interval, default 300
  NANFO_STREAM_RETENTION_MAX_ENTRIES          per stream per cycle, default 1000
  NANFO_STREAM_RETENTION_MIN_AGE_SECONDS      domain streams, default 86400
  NANFO_STREAM_RETENTION_DLQ_MIN_AGE_SECONDS  dead-letter stream, default 604800
  NANFO_STREAM_RETENTION_MIN_FREE_BYTES       archive reserve, default 1073741824
  NANFO_STREAM_RETENTION_JITTER_SECONDS       random extra delay, default interval/10
  NANFO_STREAM_RETENTION_MAX_REFUSALS         consecutive refused cycles before exit 3, default 5

Every registered domain stream (its consumer group) and ``stream:dead_letter`` are
processed each cycle. SIGTERM/SIGINT finish the current bounded batch and exit 0.

Redis credentials come only from the environment: STREAM_RETENTION_REDIS_URL, else
REDIS_HOST / REDIS_PORT / REDIS_USERNAME (optional ACL user, C24) / REDIS_PASSWORD /
REDIS_DB (the deployment's secret env).
Output is one JSON object per run/cycle; failures print a machine-readable ``reason``
and never credentials, raw envelopes, Redis errors or exception traces.
"""

import argparse
import asyncio
import json
import os
import random
import signal
import time
from pathlib import Path
from urllib.parse import quote

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.events.bus import DEAD_LETTER_STREAM, STREAM_GROUPS
from app.events.retention import (
    RetentionPolicy,
    StreamRetention,
    completion_marker_count,
    refusal_reason,
)
from app.events.retention_archive import StreamArchive

EXIT_REFUSED = 1
EXIT_WARNING = 2
EXIT_REPEATED_REFUSALS = 3
_HANDLED = (ValueError, OSError, KeyError, TypeError, RedisError, TimeoutError)


def parser():
    value = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    value.add_argument('mode', choices=('dry-run', 'apply', 'health', 'restore', 'schedule'))
    value.add_argument('--stream')
    value.add_argument('--group', action='append')
    value.add_argument('--min-age-seconds', type=int)
    for name, default in (('batch-size', 100), ('max-batches', 10), ('max-entries', 1000),
                          ('max-seconds', 30), ('max-archive-bytes', 16 * 1024**2),
                          ('min-free-bytes', 1024**3), ('lag-warn-entries', 10000),
                          ('pending-warn-seconds', 3600)):
        value.add_argument('--' + name, type=int, default=default)
    value.add_argument('--memory-warn-ratio', type=float, default=0.8)
    value.add_argument('--archive-root', type=Path)
    value.add_argument('--digest')
    value.add_argument('--target')
    return value


def redis_url_from_environment(environ=os.environ) -> str:
    """STREAM_RETENTION_REDIS_URL, else a URL built from the application's REDIS_* env."""
    if environ.get('STREAM_RETENTION_REDIS_URL'):
        return environ['STREAM_RETENTION_REDIS_URL']
    host = environ['REDIS_HOST']
    password = environ['REDIS_PASSWORD']
    port = int(environ.get('REDIS_PORT', '6379'))
    database = int(environ.get('REDIS_DB', '0'))
    # ACL user (C24); unset/blank authenticates as Redis `default` as before.
    username = (environ.get('REDIS_USERNAME') or '').strip()
    user = quote(username, safe='') if username else ''
    return f"redis://{user}:{quote(password, safe='')}@{host}:{port}/{database}"


def connect(url: str) -> Redis:
    return Redis.from_url(url, decode_responses=False, socket_connect_timeout=3,
                          socket_timeout=5, retry_on_timeout=False)


async def execute(args):
    fields = vars(args).copy()
    mode, root = fields.pop('mode'), fields.pop('archive_root')
    digest, target = fields.pop('digest'), fields.pop('target')
    if not fields['stream'] or fields['group'] is None or fields['min_age_seconds'] is None:
        raise ValueError('explicit --stream, --group and --min-age-seconds required')
    fields['groups'] = tuple(fields.pop('group'))
    policy = RetentionPolicy(**fields)
    if mode in {'apply', 'restore'} and root is None:
        raise ValueError('archive required')
    if mode == 'restore' and (not digest or not target):
        raise ValueError('restore requires digest and target')
    if mode != 'restore' and (digest or target):
        raise ValueError('recovery arguments require restore')
    archive = StreamArchive(root) if root else None
    async with connect(os.environ['STREAM_RETENTION_REDIS_URL']) as redis:
        operator = StreamRetention(redis, policy, archive)
        if mode == 'health':
            async with asyncio.timeout(policy.max_seconds):
                health = await operator.diagnostics()
                health.update(await completion_marker_count(redis))
                return health
        if mode == 'restore':
            return {'mode': mode, 'restored': await operator.restore(digest, target)}
        return await operator.run(mode=mode)


def refusal(exc: BaseException) -> dict:
    return {'status': 'refused_or_incomplete', 'reason': refusal_reason(exc),
            'recovery': 'inspect verified archives; earlier batches may have completed'}


def _env_int(environ, name, default, *, minimum, maximum):
    raw = environ.get(name)
    value = default if raw in (None, '') else int(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f'{name} outside bounds')
    return value


def schedule_config(environ=os.environ) -> dict:
    """Validated supervised configuration; KeyError when the archive root is absent."""
    root = environ['NANFO_STREAM_ARCHIVE_ROOT']
    interval = _env_int(environ, 'NANFO_STREAM_RETENTION_INTERVAL_SECONDS', 300, minimum=5, maximum=86400)
    return {
        'archive_root': Path(root),
        'interval_seconds': interval,
        'max_entries': _env_int(environ, 'NANFO_STREAM_RETENTION_MAX_ENTRIES', 1000, minimum=1, maximum=100000),
        'min_age_seconds': _env_int(environ, 'NANFO_STREAM_RETENTION_MIN_AGE_SECONDS', 86400,
                                    minimum=60, maximum=315360000),
        'dlq_min_age_seconds': _env_int(environ, 'NANFO_STREAM_RETENTION_DLQ_MIN_AGE_SECONDS', 604800,
                                        minimum=60, maximum=315360000),
        'min_free_bytes': _env_int(environ, 'NANFO_STREAM_RETENTION_MIN_FREE_BYTES', 1024**3,
                                   minimum=1024**2, maximum=1024**5),
        'jitter_seconds': _env_int(environ, 'NANFO_STREAM_RETENTION_JITTER_SECONDS', max(1, interval // 10),
                                   minimum=0, maximum=86400),
        'max_refusals': _env_int(environ, 'NANFO_STREAM_RETENTION_MAX_REFUSALS', 5, minimum=1, maximum=1000),
    }


def schedule_policies(config: dict) -> list[RetentionPolicy]:
    common = {'max_entries': config['max_entries'], 'max_batches': 1000,
              'min_free_bytes': config['min_free_bytes']}
    policies = [RetentionPolicy(stream=stream, groups=(group,), min_age_seconds=config['min_age_seconds'],
                                **common) for stream, group in STREAM_GROUPS.items()]
    policies.append(RetentionPolicy(stream=DEAD_LETTER_STREAM, groups=(),
                                    min_age_seconds=config['dlq_min_age_seconds'], **common))
    return policies


async def run_cycle(redis, archive, policies) -> dict:
    """One bounded pass over every stream; a refusal never stops the other streams."""
    streams, refused = {}, []
    for policy in policies:
        try:
            result = await StreamRetention(redis, policy, archive).run(mode='apply')
            streams[policy.stream] = {'deleted': result['deleted'], 'entries': result['entries'],
                                      'stop': result['stop'], 'archives': len(result['archives']),
                                      'alerts': result['health']['alerts']}
        except _HANDLED as exc:
            reason = refusal_reason(exc)
            streams[policy.stream] = {'status': 'refused', 'reason': reason}
            refused.append(reason)
    return {'status': 'refused' if refused else 'ok', 'refusals': sorted(set(refused)), 'streams': streams}


async def schedule(environ=os.environ, *, stop: asyncio.Event | None = None, emit=print,
                   connect_redis=None, clock=time.time) -> int:
    config = schedule_config(environ)
    archive = StreamArchive(config['archive_root'])
    policies = schedule_policies(config)
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except (NotImplementedError, RuntimeError, ValueError):
            pass  # Non-main thread/test loop: the caller controls ``stop``.
    consecutive = 0
    redis = (connect_redis or connect)(redis_url_from_environment(environ))
    try:
        while not stop.is_set():
            try:
                cycle = await run_cycle(redis, archive, policies)
                markers = await completion_marker_count(redis)
                cycle.update(markers)
            except _HANDLED as exc:
                cycle = {'status': 'refused', 'refusals': [refusal_reason(exc)], 'streams': {}}
            consecutive = consecutive + 1 if cycle['status'] == 'refused' else 0
            cycle.update(mode='schedule', at=int(clock()), consecutive_refusals=consecutive)
            emit(json.dumps(cycle, sort_keys=True))
            if consecutive >= config['max_refusals']:
                return EXIT_REPEATED_REFUSALS
            delay = config['interval_seconds'] + random.uniform(0, config['jitter_seconds'])
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass
    finally:
        await redis.aclose()
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.mode == 'schedule':
            return asyncio.run(schedule())
        result = asyncio.run(execute(args))
    except _HANDLED as exc:
        # Never print credentials, raw envelopes, Redis errors or exception traces.
        print(json.dumps(refusal(exc), sort_keys=True))
        return EXIT_REFUSED
    print(json.dumps(result, sort_keys=True))
    health = result.get('health', result)
    return EXIT_WARNING if health.get('status') == 'warning' else 0


if __name__ == '__main__':
    os.umask(0o077)
    raise SystemExit(main())
