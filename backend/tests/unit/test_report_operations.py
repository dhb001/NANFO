"""ADR-028 online report storage maintenance: orphan cleanup and opt-in retention."""

import os
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.report.artifacts import ArtifactStore
from app.modules.report.operations import ReportOperationsService


def attempt(report=None, artifact=None, fmt="csv"):
    return report or uuid.uuid4(), artifact or uuid.uuid4(), fmt


def name(report, artifact, fmt="csv"):
    return f"{report}-{artifact}.{fmt}"


def service_for(tmp_path, *, pinned=(), in_flight=()):
    os.chmod(tmp_path, 0o700)
    service = ReportOperationsService(SimpleNamespace(), store=ArtifactStore(tmp_path, 100000))
    service._references = AsyncMock(return_value=(set(pinned), set(in_flight)))
    return service


def write(tmp_path, filename):
    path = tmp_path / filename
    path.write_bytes(b"report")
    path.chmod(0o600)
    return path


async def test_orphan_cleanup_runs_with_active_jobs_and_protects_in_flight_attempts(tmp_path):
    # Regression: cleanup refused to run while any report was active, so orphans piled up.
    active_report, active_lease = uuid.uuid4(), uuid.uuid4()
    registered, orphan, old_attempt = name(*attempt()), name(*attempt()), name(active_report, uuid.uuid4())
    in_flight = name(active_report, active_lease)
    for filename in (registered, orphan, old_attempt, in_flight, "unknown.csv"):
        write(tmp_path, filename)
    link = name(*attempt())
    (tmp_path / link).symlink_to(tmp_path / orphan)
    service = service_for(tmp_path, pinned={registered}, in_flight={(str(active_report), str(active_lease))})
    later = time.time() + 7200
    dry = await service.cleanup_orphans(grace_seconds=3600, now=later)
    assert dry["mode"] == "dry_run" and dry["candidates"] == 2 and dry["removed"] == 0
    result = await service.cleanup_orphans(apply=True, grace_seconds=3600, now=later)
    assert result["removed"] == 2 and result["active_attempts"] == 1
    remaining = {path.name for path in tmp_path.iterdir()}
    assert remaining == {registered, in_flight, "unknown.csv", link}


async def test_orphan_cleanup_respects_grace_batch_and_bounds(tmp_path):
    old = [name(*attempt()) for _ in range(3)]
    for filename in old:
        write(tmp_path, filename)
    service = service_for(tmp_path)
    # ctime cannot be backdated: evaluate the grace window from a moving "now".
    created = max((tmp_path / filename).stat().st_ctime for filename in old)
    young = await service.cleanup_orphans(apply=True, now=created + 86400 - 60)
    assert young["candidates"] == 0 and len(list(tmp_path.iterdir())) == 3
    result = await service.cleanup_orphans(apply=True, batch_size=2, now=created + 86400 + 60)
    assert result["removed"] == 2 and len(list(tmp_path.iterdir())) == 1
    with pytest.raises(ValueError, match="Grace"):
        await service.cleanup_orphans(grace_seconds=60)
    with pytest.raises(ValueError, match="cap"):
        await service.cleanup_orphans(apply=True, max_scan=0)


async def test_orphan_cleanup_tolerates_a_concurrent_remover(tmp_path, monkeypatch):
    orphan = name(*attempt())
    write(tmp_path, orphan)
    service = service_for(tmp_path)
    real_unlink = os.unlink

    def racing_unlink(path, *args, **kwargs):
        real_unlink(path, *args, **kwargs)
        raise FileNotFoundError(path)  # another worker got there first

    monkeypatch.setattr(os, "unlink", racing_unlink)
    result = await service.cleanup_orphans(apply=True, now=time.time() + 2 * 86400)
    assert result["candidates"] == 1 and result["removed"] == 0 and not (tmp_path / orphan).exists()


async def test_references_read_only_small_columns_never_snapshots():
    captured = []

    class Rows:
        def __aiter__(self):
            async def generator():
                yield uuid.UUID(int=1), "running", uuid.UUID(int=2), "a.csv", [{"filename": "b.csv"}, "junk"]
                yield uuid.UUID(int=3), "generated", None, None, None
            return generator()

    async def stream(statement):
        captured.append(statement)
        return Rows()

    db = SimpleNamespace(scalar=AsyncMock(return_value=2), stream=stream)
    pinned, in_flight = await ReportOperationsService(db, store=object())._references()
    assert pinned == {"a.csv", "b.csv"}
    assert in_flight == {(str(uuid.UUID(int=1)), str(uuid.UUID(int=2)))}
    text = str(captured[0].compile(dialect=postgresql.dialect()))
    assert "reports.snapshot" not in text and "reports.receipt ->>" in text


async def test_references_refuse_unbounded_inventories():
    db = SimpleNamespace(scalar=AsyncMock(return_value=100_001))
    with pytest.raises(ValueError, match="cap"):
        await ReportOperationsService(db, store=object())._references()


async def test_retention_deletes_rows_first_then_their_artifacts(tmp_path):
    os.chmod(tmp_path, 0o700)
    store = ArtifactStore(tmp_path, 100000)
    report, artifact = uuid.uuid4(), uuid.uuid4()
    receipt = store.write(report, artifact, "csv", b"a,b\r\n", min_free_bytes=0)
    statements, order = [], []

    async def execute(statement):
        statements.append(statement)
        order.append("select" if not statements[1:] else "delete")
        result = MagicMock()
        result.all.return_value = [(report, "csv", receipt), (uuid.uuid4(), "pdf", None)]
        return result

    async def commit():
        order.append("commit")
        assert (tmp_path / receipt["filename"]).exists()  # files only after the commit

    db = SimpleNamespace(execute=execute, commit=commit, rollback=AsyncMock())
    result = await ReportOperationsService(db, store=store).expire_generated(retention_days=30)
    assert result == {"expired": 2, "removed_files": 1, "retention_days": 30}
    assert order == ["select", "delete", "commit"] and list(tmp_path.iterdir()) == []
    select_sql = str(statements[0].compile(dialect=postgresql.dialect()))
    assert "reports.status = " in select_sql and "reports.completed_at < now() - " in select_sql
    assert "report_outbox.published_at IS NULL" in select_sql and "NOT (EXISTS" in select_sql
    assert "FOR UPDATE OF reports SKIP LOCKED" in select_sql
    assert str(statements[1].compile(dialect=postgresql.dialect())).startswith("DELETE FROM reports")


async def test_retention_is_bounded_and_idle_when_nothing_expired():
    result = MagicMock()
    result.all.return_value = []
    db = SimpleNamespace(execute=AsyncMock(return_value=result), commit=AsyncMock(), rollback=AsyncMock())
    assert (await ReportOperationsService(db, store=object()).expire_generated(retention_days=7))["expired"] == 0
    db.commit.assert_not_awaited()
    with pytest.raises(ValueError):
        await ReportOperationsService(db, store=object()).expire_generated(retention_days=0)
