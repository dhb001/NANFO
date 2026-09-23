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
