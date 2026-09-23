"""Optional bounded ADR027 operator. No background worker or implicit deletion.

From backend: poetry run python -m scripts.stream_retention --help
Credentials are accepted only from STREAM_RETENTION_REDIS_URL in the environment.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.events.retention import RetentionPolicy, StreamRetention
from app.events.retention_archive import StreamArchive


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument('mode', choices=('dry-run', 'apply', 'health', 'restore'))
    value.add_argument('--stream', required=True)
    value.add_argument('--group', action='append', required=True)
    value.add_argument('--min-age-seconds', type=int, required=True)
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


async def execute(args):
    fields = vars(args).copy()
    mode, root = fields.pop('mode'), fields.pop('archive_root')
    digest, target = fields.pop('digest'), fields.pop('target')
    fields['groups'] = tuple(fields.pop('group'))
    policy = RetentionPolicy(**fields)
    if mode in {'apply', 'restore'} and root is None:
        raise ValueError('archive required')
    if mode == 'restore' and (not digest or not target):
        raise ValueError('restore requires digest and target')
    if mode != 'restore' and (digest or target):
        raise ValueError('recovery arguments require restore')
    archive = StreamArchive(root) if root else None
    url = os.environ['STREAM_RETENTION_REDIS_URL']
    async with Redis.from_url(url, decode_responses=False, socket_connect_timeout=3,
                              socket_timeout=3, retry_on_timeout=False) as redis:
        operator = StreamRetention(redis, policy, archive)
        if mode == 'health':
            async with asyncio.timeout(policy.max_seconds):
                return await operator.diagnostics()
        if mode == 'restore':
            return {'mode': mode, 'restored': await operator.restore(digest, target)}
        return await operator.run(mode=mode)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = asyncio.run(execute(args))
    except (ValueError, OSError, KeyError, TypeError, RedisError, TimeoutError):
        # Never print credentials, raw envelopes, Redis errors or exception traces.
        print(json.dumps({'status': 'refused_or_incomplete',
                          'reason': 'retention_preconditions_or_io_failed',
                          'recovery': 'inspect verified archives; earlier batches may have completed'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    health = result.get('health', result)
    return 2 if health.get('status') == 'warning' else 0


if __name__ == '__main__':
    os.umask(0o077)
    raise SystemExit(main())
