"""Real Redis, exact-owned helper only. Never accepts external/shared Redis URLs.

STREAM_RETENTION_TEST_IMAGE must be an already installed sha256 image ID. The
existing LocalLab/DockerRedis helper creates, verifies and removes exact resources.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError, ResponseError

from app.events.retention import RetentionPolicy, StreamRetention, decode_bundle
from app.events.retention_archive import StreamArchive
from app.events.retention_lua import DELETE, PLAN
from scripts.stream_retention import execute, parser
from scripts.verify_measured_twin import LocalLab

STREAM = 'stream:telemetry'
GROUP = 'nanfo-consumers'


@pytest.fixture(scope='module')
def owned_lab():
    image = os.environ.get('STREAM_RETENTION_TEST_IMAGE')
    if not image:
        pytest.skip('explicit exact disposable Redis image required')
    root = Path(tempfile.mkdtemp(prefix='nanfo-stream-retention-', dir='/tmp/opencode'))
    lab = LocalLab(root, None, image)
    try:
        lab.start_redis()
        yield lab
    finally:
        cleanup = lab.cleanup()
        assert cleanup['owned_container_removed'] and cleanup['owned_volume_removed']
        assert cleanup['redis_port_closed'] and cleanup['private_tree_removed']


@pytest.fixture
async def redis(owned_lab):
    async with Redis(host='127.0.0.1', port=owned_lab.redis_port,
                     password=owned_lab.env['REDIS_PASSWORD'], decode_responses=False,
                     socket_timeout=3) as client:
        # Entire database belongs to the exact newly created test container.
        await client.flushdb()
        await client.config_set('maxmemory', 64 * 1024**2)
        await client.config_set('maxmemory-policy', 'noeviction')
        yield client


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / 'archive'
    root.mkdir(mode=0o700)
    return StreamArchive(root)


def operator(redis, archive, **kwargs):
    options = dict(stream=STREAM, groups=(GROUP,), min_age_seconds=60, min_free_bytes=1024**2)
    options.update(kwargs)
    return StreamRetention(redis, RetentionPolicy(**options), archive)


async def seed(redis, count=5, *, groups=(GROUP,), ack=True):
    for i in range(1, count + 1):
        # Duplicate field names, invalid UTF-8 and exact JSON whitespace survive.
        await redis.execute_command('XADD', STREAM, f'{i}-0', 'event_id', 'same-event',
                                    'payload', b'\xff\x00', 'payload', b' {"value": 1} ')
    for group in groups:
        await redis.xgroup_create(STREAM, group, '0')
        await redis.xreadgroup(group, 'consumer', {STREAM: '>'}, count=count)
        if ack:
            await redis.xack(STREAM, group, *[f'{i}-0' for i in range(1, count + 1)])


async def test_archive_delete_binary_restore_duplicate_ids(redis, archive):
    await seed(redis)
    op = operator(redis, archive, batch_size=2)
    dry = await op.run(mode='dry-run')
    assert dry['entries'] == 5 and dry['deleted'] == 0 and await redis.xlen(STREAM) == 5
    assert not list(archive.root.iterdir())
    result = await op.run(mode='apply')
    assert result['deleted'] == 5 and await redis.xlen(STREAM) == 0
    assert len(result['archives']) == 3
    for digest in result['archives']:
        manifest, entries = decode_bundle(archive.read(digest))
        assert entries[0][1][3] == b'\xff\x00'
        assert await op.restore(digest, 'recovery:test') == manifest['count']
        assert await op.restore(digest, 'recovery:test') == 0
    assert await redis.xlen('recovery:test') == 5  # same event UUID: distinct stream IDs retained
    await redis.xgroup_create('recovery:test', 'reader', '0')
    with pytest.raises(ResponseError, match='recovery_has_groups'):
        await op.restore(result['archives'][0], 'recovery:test')


async def test_all_groups_earliest_pending_unread_cutoff(redis, archive):
    await seed(redis, groups=(GROUP, 'audit'), ack=False)
    await redis.xack(STREAM, GROUP, '1-0', '2-0', '4-0', '5-0')
    await redis.xack(STREAM, 'audit', '1-0', '3-0', '4-0', '5-0')
    result = await operator(redis, archive, groups=(GROUP, 'audit')).run(mode='apply')
    assert result['deleted'] == 1  # acknowledged holes above earliest pending retained
    assert await redis.xlen(STREAM) == 4
    await redis.xack(STREAM, GROUP, '3-0')
    await redis.xack(STREAM, 'audit', '2-0')
    await redis.xadd(STREAM, {'payload': 'unread'}, id='6-0')
    result = await operator(redis, archive, groups=(GROUP, 'audit')).run(mode='apply')
    assert result['deleted'] == 4
    assert [row[0] for row in await redis.xrange(STREAM)] == [b'6-0']
    await redis.xreadgroup(GROUP, 'consumer', {STREAM: '>'})
    await redis.xreadgroup('audit', 'consumer', {STREAM: '>'})
    await redis.xack(STREAM, GROUP, '6-0')
    await redis.xack(STREAM, 'audit', '6-0')
    fresh = await redis.xadd(STREAM, {'payload': 'fresh'})
    for group in (GROUP, 'audit'):
        await redis.xreadgroup(group, 'consumer', {STREAM: '>'})
        await redis.xack(STREAM, group, fresh)
    result = await operator(redis, archive, groups=(GROUP, 'audit')).run(mode='apply')
    assert result['deleted'] == 1 and await redis.xlen(STREAM) == 1


@pytest.mark.parametrize('race,refused,remaining,bundles', [
    # Group-set changes are configuration faults: refused, never retried.
    ('new_group', 'retention_unknown_groups', 5, 1),
    ('destroy_group', 'retention_group_count', 5, 1),
    # ADR-028: invalidated batches are re-planned from current state (bounded).
    ('reset', None, 5, 1),        # cursor moved backwards: nothing delivered any more
    ('pending', None, 4, 2),      # 2-0 claimed inside the batch: only 1-0 stays eligible
    ('consumer', None, 0, 1),     # a new consumer without pending work is harmless
    ('entry', None, 0, 2),        # changed entry: the rest is re-archived and deleted
])
async def test_atomic_race_recheck_no_partial_delete(redis, archive, race, refused, remaining, bundles):
    await seed(redis)
    original = redis.eval

    async def racing(script, *args):
        if script == DELETE:
            if race == 'new_group':
                await redis.xgroup_create(STREAM, 'unregistered', '0')
            elif race == 'destroy_group':
                await redis.xgroup_destroy(STREAM, GROUP)
            elif race == 'reset':
                await redis.xgroup_setid(STREAM, GROUP, '0', entries_read=0)
            elif race == 'pending':
                await redis.xclaim(STREAM, GROUP, 'new-consumer', 0, ['2-0'], force=True)
            elif race == 'consumer':
                await redis.xgroup_createconsumer(STREAM, GROUP, 'new-consumer')
            else:
                await redis.xdel(STREAM, '5-0')
        return await original(script, *args)

    with patch.object(redis, 'eval', racing):
        if refused:
            with pytest.raises(ResponseError, match=refused):
                await operator(redis, archive).run(mode='apply')
        else:
            await operator(redis, archive).run(mode='apply')
    assert await redis.xlen(STREAM) == remaining
    assert len(list(archive.root.iterdir())) == bundles


@pytest.mark.parametrize('failure', ['write', 'readback', 'disk', 'path', 'permissions'])
async def test_archive_failure_never_deletes(redis, archive, failure):
    await seed(redis)
    op = operator(redis, archive)
    if failure == 'disk':
        op = operator(redis, archive, min_free_bytes=archive.free_bytes())
    elif failure == 'path':
        archive.root.rename(archive.root.with_name('moved'))
        archive.root.mkdir(mode=0o700)
    elif failure == 'permissions':
        archive.root.chmod(0o755)
    method = 'write' if failure == 'write' else 'read'
    if failure in {'write', 'readback'}:
        with patch.object(archive, method, side_effect=OSError('archive unavailable')):
            with pytest.raises(OSError):
                await op.run(mode='apply')
    else:
        with pytest.raises(ValueError):
            await op.run(mode='apply')
    assert await redis.xlen(STREAM) == 5


async def test_unknown_and_missing_groups_and_unknown_cursor(redis, archive):
    await seed(redis, groups=(GROUP, 'new'))
    with pytest.raises(ResponseError, match='unknown_groups'):
        await operator(redis, archive).run(mode='apply')
    await redis.xgroup_destroy(STREAM, 'new')
    await redis.xgroup_setid(STREAM, GROUP, '3-0')  # Redis reports unknown entries-read/lag
    with pytest.raises(ResponseError, match='unknown_state'):
        await operator(redis, archive).run(mode='apply')
    await redis.xgroup_destroy(STREAM, GROUP)
    with pytest.raises(ValueError, match='group count'):
        await operator(redis, archive).run(mode='apply')
    assert await redis.xlen(STREAM) == 5


@pytest.mark.parametrize('limits,expected', [
    ({'batch_size': 2, 'max_batches': 1}, 2),
    ({'batch_size': 2, 'max_entries': 3}, 3),
    ({'max_archive_bytes': 1}, 0),
])
async def test_bounded_work(redis, archive, limits, expected):
    await seed(redis)
    result = await operator(redis, archive, **limits).run(mode='apply')
    assert result['deleted'] == expected and await redis.xlen(STREAM) == 5 - expected


async def test_time_limit_after_archive_blocks_delete(redis, archive):
    await seed(redis)
    original = archive.write
    clock = [0.0]

    def delayed(*args, **kwargs):
        digest = original(*args, **kwargs)
        clock[0] = 2.0
        return digest

    with patch.object(archive, 'write', delayed), patch('app.events.retention.time') as timer:
        timer.time.return_value = time.time()
        timer.monotonic.side_effect = lambda: clock[0]
        result = await operator(redis, archive, max_seconds=1).run(mode='apply')
    assert result['stop'] == 'max_seconds' and await redis.xlen(STREAM) == 5


async def test_lost_delete_reply_and_orphan_archive_recovery(redis, archive):
    await seed(redis)
    original = redis.eval

    async def lost(script, *args):
        result = await original(script, *args)
        if script == DELETE:
            raise ConnectionError('lost reply')
        return result

    op = operator(redis, archive)
    with patch.object(redis, 'eval', lost), pytest.raises(ConnectionError):
        await op.run(mode='apply')
    assert await redis.xlen(STREAM) == 0
    digest = next(archive.root.iterdir()).name
    assert await op.restore(digest, 'recovery:lost') == 5
    assert (await op.run(mode='apply'))['deleted'] == 0


async def test_concurrent_append_preserved(redis, archive):
    await seed(redis)
    original = redis.eval

    async def append(script, *args):
        if script == DELETE:
            await redis.xadd(STREAM, {'payload': 'new'}, id='6-0')
        return await original(script, *args)

    with patch.object(redis, 'eval', append):
        result = await operator(redis, archive).run(mode='apply')
    assert result['deleted'] == 5
    assert [row[0] for row in await redis.xrange(STREAM)] == [b'6-0']


@pytest.mark.parametrize('kind', ['bytes', 'fields'])
async def test_oversized_entry_fail_closed(redis, archive, kind):
    fields = {'payload': b'x' * 65536} if kind == 'bytes' else {str(i): b'' for i in range(129)}
    await redis.xadd(STREAM, fields, id='1-0')
    await redis.xgroup_create(STREAM, GROUP, '0')
    await redis.xreadgroup(GROUP, 'consumer', {STREAM: '>'})
    await redis.xack(STREAM, GROUP, '1-0')
    with pytest.raises(ResponseError, match='entry_too_large'):
        await operator(redis, archive).run(mode='apply')
    assert await redis.xlen(STREAM) == 1 and not list(archive.root.iterdir())


async def test_explicit_known_new_group_blocks_until_processed(redis, archive):
    await seed(redis)
    await redis.xgroup_create(STREAM, 'new', '0')
    op = operator(redis, archive, groups=(GROUP, 'new'))
    # Redis7 reports unknown entries-read for an untouched new group. Fail closed
    # until the actual reader establishes delivery state; never infer zero lag.
    with pytest.raises(ResponseError, match='unknown_state'):
        await op.run(mode='apply')
    assert await redis.xlen(STREAM) == 5
    await redis.xreadgroup('new', 'consumer', {STREAM: '>'})
    assert (await op.run(mode='apply'))['deleted'] == 0
    await redis.xack(STREAM, 'new', *[f'{i}-0' for i in range(1, 6)])
    assert (await op.run(mode='apply'))['deleted'] == 5


async def test_ack_race_proceeds_from_current_state(redis, archive):
    await seed(redis, ack=False)
    await redis.xack(STREAM, GROUP, '1-0')
    original = redis.eval

    async def ack(script, *args):
        if script == DELETE:
            await redis.xack(STREAM, GROUP, '2-0')
        return await original(script, *args)

    with patch.object(redis, 'eval', ack):
        result = await operator(redis, archive).run(mode='apply')
    # ADR-028: an ACK can only widen eligibility; the planned 1-0 and then 2-0 go.
    assert result['deleted'] == 2 and await redis.xlen(STREAM) == 3


async def test_eviction_policy_blocks_apply(redis, archive):
    await seed(redis)
    await redis.config_set('maxmemory-policy', 'allkeys-lru')
    with pytest.raises(ValueError, match='noeviction'):
        await operator(redis, archive).run(mode='apply')
    assert await redis.xlen(STREAM) == 5 and not list(archive.root.iterdir())


async def test_recovery_conflict_order_and_uint64_comparison(redis, archive):
    await seed(redis)
    op = operator(redis, archive, batch_size=2)
    result = await op.run(mode='apply')
    await redis.execute_command('XADD', 'recovery:conflict', '1-0', 'bad', 'data')
    with pytest.raises(ResponseError, match='recovery_conflict'):
        await op.restore(result['archives'][0], 'recovery:conflict')
    assert await redis.xlen('recovery:conflict') == 1
    await op.restore(result['archives'][-1], 'recovery:reverse')
    with pytest.raises(ResponseError, match='recovery_order'):
        await op.restore(result['archives'][0], 'recovery:reverse')
    await redis.xadd(STREAM, {'x': 'y'}, id='100-9007199254740993')
    await redis.xreadgroup(GROUP, 'consumer', {STREAM: '>'})
    await redis.xack(STREAM, GROUP, '100-9007199254740993')
    _, entries, _ = await redis.eval(PLAN, 1, STREAM, json.dumps([GROUP]), '-',
                                     '100-9007199254740993', 100)
    assert entries == []
    _, entries, _ = await redis.eval(PLAN, 1, STREAM, json.dumps([GROUP]), '-',
                                     '100-9007199254740994', 100)
    assert entries[0][0] == b'100-9007199254740993'


async def test_health_cli_and_capacity_soak(redis, archive, owned_lab, monkeypatch):
    await seed(redis, ack=False)
    op = operator(redis, archive, lag_warn_entries=1, pending_warn_seconds=1,
                  memory_warn_ratio=0.00001)
    health = await op.diagnostics()
    assert {'old_pending_entry', 'redis_memory_pressure'} <= set(health['alerts'])
    assert health['groups'][0]['pending'] == 5
    monkeypatch.setenv('STREAM_RETENTION_REDIS_URL',
                       f'redis://:{owned_lab.env["REDIS_PASSWORD"]}@127.0.0.1:{owned_lab.redis_port}/0')
    args = ['--stream', STREAM, '--group', GROUP, '--min-age-seconds', '60',
            '--archive-root', str(archive.root), '--min-free-bytes', str(1024**2)]
    assert (await execute(parser().parse_args(['dry-run', *args])))['deleted'] == 0
    await redis.xack(STREAM, GROUP, *[f'{i}-0' for i in range(1, 6)])
    assert (await execute(parser().parse_args(['apply', *args])))['deleted'] == 5
    # Finite append/ACK/retain cycles demonstrate capacity reuse under actual Redis.
    for cycle in range(5):
        for index in range(100):
            await redis.xadd(STREAM, {'payload': 'x' * 1024}, id=f'{1000 + cycle * 100 + index}-0')
        rows = await redis.xreadgroup(GROUP, 'consumer', {STREAM: '>'}, count=100)
        await redis.xack(STREAM, GROUP, *[row[0] for row in rows[0][1]])
        assert (await op.run(mode='apply'))['deleted'] == 100
        assert await redis.xlen(STREAM) == 0
        assert await redis.memory_usage(STREAM) < 16384


async def test_many_idle_consumers_without_pending_do_not_block(redis, archive):
    await seed(redis)
    for index in range(70):
        await redis.xgroup_createconsumer(STREAM, GROUP, f'restart-{index}')
    result = await operator(redis, archive).run(mode='apply')
    assert result['deleted'] == 5
    assert 'consumer_churn' in result['health']['alerts']


async def test_dead_letter_stream_archived_before_delete(redis, archive):
    from app.events.retention import dead_letter_policy

    for index in range(1, 4):
        await redis.execute_command('XADD', 'stream:dead_letter', f'{index}-0', 'event_id', 'e',
                                    'failure_reason', 'malformed_envelope', 'payload', b'\xff')
    op = StreamRetention(redis, dead_letter_policy(min_age_seconds=60, min_free_bytes=1024**2), archive)
    result = await op.run(mode='apply')
    assert result['deleted'] == 3 and await redis.xlen('stream:dead_letter') == 0
    manifest, entries = decode_bundle(archive.read(result['archives'][0]))
    assert manifest['stream'] == 'stream:dead_letter' and entries[0][1][-1] == b'\xff'
