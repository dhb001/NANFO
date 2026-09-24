"""Archive integrity, private path binding, policy and CLI safety gates."""

import hashlib
import json
import os
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.events.retention import RetentionPolicy, StreamRetention, decode_bundle, encode_bundle
from app.events.retention_archive import StreamArchive
from scripts.stream_retention import main, parser


def policy(**kwargs):
    return RetentionPolicy(stream='stream:telemetry', groups=('nanfo-consumers',),
                           min_age_seconds=60, **kwargs)


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / 'archive'
    root.mkdir(mode=0o700)
    return StreamArchive(root)


def test_exact_ordered_binary_roundtrip_and_manifest(archive):
    entries = [(b'1-1', [b'payload', b'\xff\x00', b'payload', b'  {"x":1}  ']),
               (b'1-2', [b'', b''])]
    data = encode_bundle(policy(), '10-0', b'\x00state', entries)
    digest = archive.write(data, min_free_bytes=1024**2)
    assert archive.read(digest) == data
    manifest, decoded = decode_bundle(data)
    assert decoded == entries
    assert manifest['first_id'] == '1-1' and manifest['last_id'] == '1-2'
    assert archive.write(data, min_free_bytes=1024**2) == digest
    assert len(list(archive.root.iterdir())) == 1
    assert (archive.root / digest).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('attack', ['bytes', 'mode', 'symlink', 'hardlink'])
def test_archive_tamper_rejected(archive, tmp_path, attack):
    digest = archive.write(b'original', min_free_bytes=1024**2)
    target = archive.root / digest
    if attack == 'bytes':
        target.write_bytes(b'changed!')
    elif attack == 'mode':
        target.chmod(0o644)
    elif attack == 'hardlink':
        os.link(target, tmp_path / 'duplicate')
    else:
        target.unlink()
        other = tmp_path / 'other'
        other.write_bytes(b'original')
        target.symlink_to(other)
    with pytest.raises((OSError, ValueError)):
        archive.read(digest)


@pytest.mark.parametrize('which', ['root', 'ancestor'])
def test_directory_replacement_rejected(archive, which):
    target = archive.root if which == 'root' else archive.root.parent
    renamed = target.with_name(target.name + '-moved')
    target.rename(renamed)
    target.mkdir(mode=0o700)
    if which == 'ancestor':
        (target / 'archive').mkdir(mode=0o700)
    with pytest.raises(ValueError, match='identity changed'):
        archive.write(b'content', min_free_bytes=1024**2)


def test_archive_admission_failure_and_fsync_failure(archive, monkeypatch):
    with pytest.raises(ValueError, match='disk_admission'):
        archive.write(b'content', min_free_bytes=archive.free_bytes())
    assert not list(archive.root.iterdir())
    monkeypatch.setattr(os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('fsync failed')))
    with pytest.raises(OSError):
        archive.write(b'content', min_free_bytes=1024**2)
    assert not list(archive.root.iterdir())


def test_archive_exclusion_and_symlink_root(archive, tmp_path):
    with archive.exclusive(), pytest.raises(BlockingIOError), archive.exclusive():
        pass
    link = tmp_path / 'link'
    link.symlink_to(archive.root)
    with pytest.raises(OSError):
        StreamArchive(link)


@pytest.mark.parametrize('key,value', [
    ('batch_size', 101), ('max_batches', 1001), ('max_entries', 100001),
    ('max_seconds', 301), ('max_archive_bytes', 1024**3 + 1), ('min_free_bytes', 0),
    ('memory_warn_ratio', float('nan')),
])
def test_finite_policy_limits(key, value):
    with pytest.raises(ValidationError):
        policy(**{key: value})


def test_no_implicit_cli_mode_or_credentials(capsys, monkeypatch):
    with pytest.raises(SystemExit):
        parser().parse_args([])
    monkeypatch.delenv('STREAM_RETENTION_REDIS_URL', raising=False)
    assert main(['apply', '--stream', 'stream:telemetry', '--group', 'nanfo-consumers',
                 '--min-age-seconds', '60']) == 1
    assert 'refused_or_incomplete' in capsys.readouterr().out


def test_recovery_manifest_hash_mismatch():
    data = encode_bundle(policy(), '10-0', b'state', [(b'1-0', [b'a', b'b'])])
    value = json.loads(data)
    value['manifest']['entries_sha256'] = hashlib.sha256(b'wrong').hexdigest()
    from app.events.retention import canonical
    with pytest.raises(ValueError, match='manifest mismatch'):
        decode_bundle(canonical(value))


@pytest.mark.parametrize('data', [b'[]', b'null',
    b'{"entries":null,"format":"nanfo-domain-stream-archive-v1","manifest":{}}'])
def test_recovery_rejects_non_bundle_structure(data):
    with pytest.raises(ValueError):
        decode_bundle(data)


async def test_no_implicit_apply():
    redis = AsyncMock()
    redis.connection_pool.connection_kwargs = {'decode_responses': False}
    operator = StreamRetention(redis, policy())
    with pytest.raises(ValueError):
        await operator.run(mode='apply')
    with pytest.raises(ValueError):
        await operator.run(mode='other')
    redis.eval.assert_not_awaited()


# ── ADR-028 C14: supervised schedule, machine-readable refusals ──────────────

import asyncio  # noqa: E402

from scripts import stream_retention  # noqa: E402
from tests.lua_streams import LuaStreams  # noqa: E402


def schedule_env(root, **overrides):
    env = {"NANFO_STREAM_ARCHIVE_ROOT": str(root), "STREAM_RETENTION_REDIS_URL": "redis://unused",
           "NANFO_STREAM_RETENTION_INTERVAL_SECONDS": "5", "NANFO_STREAM_RETENTION_JITTER_SECONDS": "0"}
    env.update(overrides)
    return env


def test_schedule_config_defaults_and_bounds(archive):
    config = stream_retention.schedule_config({"NANFO_STREAM_ARCHIVE_ROOT": str(archive.root)})
    assert config["interval_seconds"] == 300 and config["max_entries"] == 1000
    assert config["jitter_seconds"] == 30 and config["max_refusals"] == 5
    assert config["min_age_seconds"] == 86400 and config["dlq_min_age_seconds"] == 604800
    with pytest.raises(KeyError):
        stream_retention.schedule_config({})
    with pytest.raises(ValueError):
        stream_retention.schedule_config({"NANFO_STREAM_ARCHIVE_ROOT": "/x",
                                          "NANFO_STREAM_RETENTION_MAX_ENTRIES": "0"})
    policies = stream_retention.schedule_policies(config)
    assert [policy.stream for policy in policies][-1] == "stream:dead_letter"
    assert {policy.stream for policy in policies} >= {"stream:network", "stream:telemetry"}


def test_redis_url_from_application_environment():
    url = stream_retention.redis_url_from_environment(
        {"REDIS_HOST": "redis", "REDIS_PASSWORD": "p@ss/word", "REDIS_PORT": "6380", "REDIS_DB": "2"})
    assert url == "redis://:p%40ss%2Fword@redis:6380/2"
    assert stream_retention.redis_url_from_environment({"STREAM_RETENTION_REDIS_URL": "redis://x"}) == "redis://x"


def test_schedule_without_archive_root_refuses_with_reason(capsys, monkeypatch):
    monkeypatch.delenv("NANFO_STREAM_ARCHIVE_ROOT", raising=False)
    assert main(["schedule"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output == {"status": "refused_or_incomplete", "reason": "missing_environment",
                      "recovery": "inspect verified archives; earlier batches may have completed"}


def test_one_shot_refusals_are_machine_readable(capsys, monkeypatch, archive):
    monkeypatch.setenv("STREAM_RETENTION_REDIS_URL", "redis://127.0.0.1:1/0")
    assert main(["apply", "--stream", "stream:telemetry", "--group", "nanfo-consumers",
                 "--min-age-seconds", "60"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "archive_required"
    assert main(["apply", "--stream", "stream:unknown", "--group", "g", "--min-age-seconds", "60"]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "invalid_policy"
    assert main(["dry-run"]) == 1  # one-shot modes still require an explicit stream/group/age
    assert json.loads(capsys.readouterr().out)["reason"] == "precondition_failed"


def seeded_streams():
    redis = LuaStreams()
    for stream, group in stream_retention.STREAM_GROUPS.items():
        redis.add(stream, "1-0", "event_id", "e")
        redis.create_group(stream, group)
        redis.ack(stream, group, *redis.deliver(stream, group, "api-host"))
    redis.add("stream:dead_letter", "1-0", "event_id", "poison")
    return redis


async def test_schedule_cycles_every_stream_including_dlq_until_stopped(archive):
    redis, stop, lines = seeded_streams(), asyncio.Event(), []

    def emit(line):
        lines.append(json.loads(line))
        stop.set()

    code = await stream_retention.schedule(schedule_env(archive.root), stop=stop, emit=emit,
                                           connect_redis=lambda url: redis)
    assert code == 0 and redis.closed
    [cycle] = lines
    assert cycle["status"] == "ok" and cycle["consecutive_refusals"] == 0
    assert cycle["streams"]["stream:dead_letter"]["deleted"] == 1
    assert all(result["deleted"] == 1 for result in cycle["streams"].values())
    assert sum(1 for _ in archive.root.iterdir()) == len(cycle["streams"])


async def test_schedule_isolates_refusals_and_exits_after_consecutive_limit(archive, monkeypatch):
    redis = seeded_streams()
    redis.create_group("stream:network", "unregistered")  # misconfiguration on one stream
    lines = []
    monkeypatch.setattr(stream_retention.asyncio, "wait_for", _no_wait)
    code = await stream_retention.schedule(
        schedule_env(archive.root, NANFO_STREAM_RETENTION_MAX_REFUSALS="3"),
        emit=lambda line: lines.append(json.loads(line)), connect_redis=lambda url: redis)
    assert code == stream_retention.EXIT_REPEATED_REFUSALS
    assert [cycle["consecutive_refusals"] for cycle in lines] == [1, 2, 3]
    first = lines[0]
    assert first["refusals"] == ["retention_unknown_groups"]
    assert first["streams"]["stream:network"] == {"status": "refused", "reason": "retention_unknown_groups"}
    assert first["streams"]["stream:telemetry"]["deleted"] == 1  # other streams still retained


async def _no_wait(awaitable, timeout):
    awaitable.close()
    raise TimeoutError
