"""Retention eligibility, one-segment archival, chunked sweeps and the --loop worker (ADR-028 fix 8)."""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.telemetry import archive as archive_module
from app.modules.telemetry.archive import (
    MAX_SEGMENT_BYTES,
    TelemetryArchiveStore,
    build_segment,
    extract_record,
)
from app.modules.telemetry.pins import REQUIRED_EVIDENCE_OWNERS
from app.modules.telemetry.retention import (
    APPLY_MAX_BATCH,
    ArchivalAssessmentRequest,
    TelemetryRetentionService,
    coverage_eligibility,
)

NOW = datetime(2026, 9, 23, tzinfo=UTC)
WORKSPACE = uuid.uuid4()


def coverage(owner, **overrides):
    return SimpleNamespace(**{"owner": owner, "version": 1, "contract": "pin-before-reference/v1",
                              "registered_at": NOW, "revoked_at": None, **overrides})


def progress(owner, **overrides):
    return SimpleNamespace(**{"owner": owner, "complete": True, "unknown": 0, "started_at": NOW, **overrides})


def row(number, *, created_at=NOW - timedelta(days=90), pinned=False):
    return SimpleNamespace(record_id=uuid.UUID(int=number), observed_at=created_at + timedelta(seconds=number),
                           created_at=created_at, pinned=pinned)


def service(rows, *, reconciled=True, unknown=0):
    svc = TelemetryRetentionService(AsyncMock())
    svc._repo = AsyncMock()
    svc._repo.coverage.return_value = [coverage(owner) for owner in REQUIRED_EVIDENCE_OWNERS]
    svc._repo.reconciliation_progress.return_value = (
        {owner: progress(owner, unknown=unknown) for owner in REQUIRED_EVIDENCE_OWNERS} if reconciled else {})
    svc._repo.assessment_batch.return_value = rows
    return svc


def request(**overrides):
    return ArchivalAssessmentRequest(**{"workspace_id": WORKSPACE, "start_time": NOW - timedelta(days=120),
                                        "end_time": NOW - timedelta(days=90) + timedelta(days=1), **overrides})


async def test_fully_reconciled_owners_make_rows_older_than_registration_deletable():
    """Regression: rows created before the latest registration were stranded forever."""
    old, pinned = row(1), row(2, pinned=True)
    result = await service([old, pinned]).assess(request())
    assert result.prospective_candidates == [old.record_id] and result.pinned == [pinned.record_id]
    assert result.coverage_basis == "reconciled" and result.prospective_since is None
    assert all(item.basis == "reconciled" for item in result.owner_coverage.values())


async def test_reconciliation_with_unknown_history_keeps_older_rows_retained():
    old, new = row(1), row(2, created_at=NOW + timedelta(seconds=1))
    result = await service([old, new], unknown=3).assess(
        request(start_time=NOW - timedelta(days=20), end_time=NOW + timedelta(days=1)))
    assert result.coverage_unknown == [old.record_id] and result.prospective_candidates == [new.record_id]
    assert result.coverage_basis == "prospective" and result.prospective_since == NOW


@pytest.mark.parametrize("registrations", [
    [coverage(owner, revoked_at=NOW if owner == "intent" else None) for owner in REQUIRED_EVIDENCE_OWNERS],
    [coverage(owner) for owner in REQUIRED_EVIDENCE_OWNERS if owner != "alert"],
    [coverage(owner) for owner in REQUIRED_EVIDENCE_OWNERS] + [coverage("future-owner")],
])
def test_revoked_missing_or_unknown_owner_blocks_even_when_reconciled(registrations):
    missing, owners = coverage_eligibility(registrations, {o: progress(o) for o in REQUIRED_EVIDENCE_OWNERS})
    assert owners is None


def test_incomplete_scan_is_prospective_only():
    scans = {owner: progress(owner, complete=owner != "report") for owner in REQUIRED_EVIDENCE_OWNERS}
    _, owners = coverage_eligibility([coverage(owner) for owner in REQUIRED_EVIDENCE_OWNERS], scans)
    assert owners["report"].basis == "prospective" and owners["intent"].basis == "reconciled"


def canonical_row(number):
    stamp = NOW - timedelta(days=90)
    return SimpleNamespace(record_id=uuid.UUID(int=number), event_id=uuid.UUID(int=10_000 + number),
                           correlation_id=uuid.UUID(int=1), device_id=uuid.UUID(int=2), network_id=uuid.UUID(int=3),
                           workspace_id=WORKSPACE, metric="latency_ms", value=float(number), unit="ms",
                           observed_at=stamp, source="emulation", tags={}, created_at=stamp)


def apply_service(count, *, reconciled=True):
    rows = [row(number) for number in range(1, count + 1)]
    svc = service(rows, reconciled=reconciled)
    return svc, rows


def patch_archive(monkeypatch, *, receipts=None):
    repo = SimpleNamespace(
        lock_coverage=AsyncMock(), lock_record=AsyncMock(side_effect=lambda ws, rid: canonical_row(rid.int)),
        ever_pinned=AsyncMock(return_value=False),
        receipts=AsyncMock(side_effect=lambda ids: {rid: r for rid, r in (receipts or {}).items() if rid in ids}),
        archive_and_delete_batch=AsyncMock(), delete_rearchived=AsyncMock(),
    )
    monkeypatch.setattr("app.modules.telemetry.archive_repository.TelemetryArchiveRepository", lambda db: repo)
    return repo


async def test_apply_archives_the_batch_as_one_segment(monkeypatch):
    svc, rows = apply_service(250)
    repo = patch_archive(monkeypatch)
    store = SimpleNamespace(write_segment=MagicMock(return_value="a" * 64))
    result = await svc.apply(request(batch_size=1000), store=store)
    # Apply is capped at 200 rows per chunk even if 1000 were requested.
    assert svc._repo.assessment_batch.await_args.kwargs["batch_size"] == APPLY_MAX_BATCH
    store.write_segment.assert_called_once()
    (segment,) = store.write_segment.call_args.args
    assert segment.count(b"\n") == APPLY_MAX_BATCH + 1  # header + one line per record
    fresh, digest, size = repo.archive_and_delete_batch.await_args.args
    assert len(fresh) == APPLY_MAX_BATCH and digest == "a" * 64 and size == len(segment)
    assert result.deleted == APPLY_MAX_BATCH and result.archive_segment_sha256 == "a" * 64
    assert result.next_position.record_id == rows[APPLY_MAX_BATCH - 1].record_id
    assert svc._repo.reconciliation_progress.await_args.kwargs == {"lock": True}
    repo.receipts.assert_awaited_once()  # one receipt lookup per batch, not per row


async def test_apply_deadline_stops_locking_and_resumes_exactly(monkeypatch):
    svc, rows = apply_service(5)
    repo = patch_archive(monkeypatch)
    clock = iter([0.0, 0.0, 10.0, 10.0, 10.0])
    store = SimpleNamespace(write_segment=MagicMock(return_value="b" * 64))
    result = await svc.apply(request(), store=store, deadline=5.0, clock=lambda: next(clock))
    assert result.stopped == "deadline" and result.deleted == 2
    assert result.next_position.record_id == rows[1].record_id
    assert repo.lock_record.await_count == 2


async def test_apply_stops_before_the_segment_bound(monkeypatch):
    svc, rows = apply_service(3)
    patch_archive(monkeypatch)
    monkeypatch.setattr(archive_module, "MAX_SEGMENT_BYTES", 1024 + 700)
    store = SimpleNamespace(write_segment=MagicMock(return_value="c" * 64))
    result = await svc.apply(request(), store=store)
    assert result.stopped == "segment_bytes" and 1 <= result.deleted < 3
    assert result.next_position is not None


async def test_restored_rows_are_rearchived_against_their_original_receipt(monkeypatch):
    svc, rows = apply_service(2)
    original = archive_module.canonical_record(canonical_row(1))
    receipts = {rows[0].record_id: SimpleNamespace(sha256="d" * 64, size_bytes=99)}
    repo = patch_archive(monkeypatch, receipts=receipts)
    store = SimpleNamespace(write_segment=MagicMock(return_value="e" * 64),
                            read_record=MagicMock(return_value=original))
    result = await svc.apply(request(), store=store)
    assert [item.record_id for item in repo.delete_rearchived.await_args.args[0]] == [rows[0].record_id]
    assert [item.record_id for item in repo.archive_and_delete_batch.await_args.args[0]] == [rows[1].record_id]
    assert result.deleted == 2
    store.read_record.return_value = b"tampered"
    with pytest.raises(ValueError, match="immutable archive identity conflict"):
        await svc.apply(request(), store=store)


def test_segment_round_trip_and_legacy_objects():
    records = [archive_module.canonical_record(canonical_row(number)) for number in (1, 2, 3)]
    segment = build_segment(records)
    assert extract_record(segment, uuid.UUID(int=2)) == records[1]
    assert extract_record(records[0], uuid.UUID(int=1)) == records[0]  # legacy single-record object
    with pytest.raises(ValueError, match="does not contain"):
        extract_record(segment, uuid.UUID(int=9))
    with pytest.raises(ValueError, match="header"):
        extract_record(segment.replace(b'"count":3', b'"count":4'), uuid.UUID(int=1))


def test_segment_write_uses_one_data_fsync_and_one_directory_fsync(tmp_path, monkeypatch):
    os.chmod(tmp_path, 0o700)
    store = TelemetryArchiveStore(tmp_path)
    records = [archive_module.canonical_record(canonical_row(number)) for number in range(1, 201)]
    segment = build_segment(records)
    calls = []
    real = os.fsync
    monkeypatch.setattr(archive_module.os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    digest = store.write_segment(segment)
    assert len(calls) == 2  # was 2 per record (400 for this batch)
    assert digest == hashlib.sha256(segment).hexdigest()
    assert store.read_record(digest, len(segment), uuid.UUID(int=137)) == records[136]
    assert len(segment) < MAX_SEGMENT_BYTES


# ------------------------------------------------------------------ reconciliation continuity


async def test_enumeration_invalidation_writes_one_marker_to_both_columns():
    from app.modules.telemetry.reconciliation import invalidate_owner_enumeration

    marker = NOW
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=marker)
    await invalidate_owner_enumeration(db, workspace_id=WORKSPACE, owner="autonomy")
    revoke, reset = (call.args[0] for call in db.execute.await_args_list)
    assert revoke.compile().params["revoked_at"] == marker
    assert reset.compile().params["started_at"] == marker
    with pytest.raises(ValueError):
        await invalidate_owner_enumeration(db, workspace_id=WORKSPACE, owner="nobody")


async def test_reactivation_preserves_start_only_for_the_explicit_marker():
    from app.modules.telemetry.reconciliation import TelemetryReconciliationService

    db = AsyncMock()
    await TelemetryReconciliationService(db)._reactivate(workspace_id=WORKSPACE, owner="report", started_at=NOW)
    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect(),
                                                     compile_kwargs={"literal_binds": True}))
    assert "CASE WHEN (telemetry_reference_coverage.revoked_at = '2026-09-23 00:00:00+00:00')" in sql
    assert "THEN telemetry_reference_coverage.registered_at ELSE clock_timestamp() END" in sql
    assert "revoked_at=NULL" in sql.replace(" ", "")


async def test_reconciliation_does_not_count_unrelated_uuids_as_unknown(monkeypatch):
    from app.modules.telemetry import reconciliation
    from app.modules.telemetry.pins import EvidenceReference
    from app.modules.telemetry.references import OwnerReferenceItem, OwnerReferencePage

    stranger, archived = uuid.uuid4(), uuid.uuid4()
    page = OwnerReferencePage(items=[OwnerReferenceItem(identity="i", references=[
        EvidenceReference(network_id=uuid.uuid4(), reference_id=uuid.uuid4(), record_id=record)
        for record in (stranger, archived)])], next_cursor="more")
    monkeypatch.setattr(reconciliation, "owner_contracts", lambda: {"intent": AsyncMock(return_value=page)})
    monkeypatch.setattr(reconciliation, "wired_owners", lambda: {"intent"})
    monkeypatch.setattr(reconciliation.TelemetryEvidenceService, "pin", AsyncMock(side_effect=ValueError("gone")))
    monkeypatch.setattr(reconciliation.TelemetryPinRepository, "known_identity",
                        AsyncMock(side_effect=lambda record_id: record_id == archived))
    state = SimpleNamespace(complete=False, cursor=None, scanned=0, unknown=0, started_at=NOW)
    db = AsyncMock()
    db.scalars = AsyncMock(return_value=SimpleNamespace(one=lambda: state))
    result = await reconciliation.TelemetryReconciliationService(db).step(workspace_id=WORKSPACE, owner="intent")
    assert result["unknown"] == 1 and result["scanned"] == 1 and not result["complete"]


# ------------------------------------------------------------------------ worker and --loop


def worker_sessions(results):
    committed = []

    @asynccontextmanager
    async def sessions():
        db = SimpleNamespace(commit=AsyncMock(side_effect=lambda: committed.append(True)))
        yield db

    return sessions, committed


async def test_sweep_commits_each_chunk_and_honours_the_deadline(monkeypatch):
    from app.modules.telemetry import retention_worker
    from app.modules.telemetry.retention import ArchivalAssessment, AssessmentPosition

    positions = iter([uuid.UUID(int=1), uuid.UUID(int=2), None])
    deadlines = []

    async def apply(self, req, *, store, deadline):
        deadlines.append(deadline)
        record = next(positions)
        position = AssessmentPosition(observed_at=req.start_time, record_id=record) if record else None
        return ArchivalAssessment(dry_run=False, deleted=1, pinned=[], coverage_unknown=[],
                                  prospective_candidates=[], missing_owners=[], prospective_since=None,
                                  next_position=position)

    monkeypatch.setattr(retention_worker.TelemetryRetentionService, "apply", apply)
    monkeypatch.setattr(retention_worker, "TelemetryArchiveStore", lambda root: object())
    sessions, committed = worker_sessions([])
    worker = retention_worker.TelemetryRetentionWorker(
        sessions, settings={"interval_seconds": 0, "batch_timeout_seconds": 30}, clock=lambda: 100.0)
    results = await worker.sweep(request(), apply=True, archive_root="/unused")
    assert [item["deleted"] for item in results] == [1, 1, 1] and len(committed) == 3
    # Row locking stops at half the batch budget, leaving time to archive and commit.
    assert deadlines == [115.0, 115.0, 115.0]
    clock = iter([0.0, 100.0])
    late = retention_worker.TelemetryRetentionWorker(sessions, settings={"sweep_deadline_seconds": 10},
                                                     clock=lambda: next(clock))
    assert await late.sweep(request(), apply=True, archive_root="/unused") == []


async def test_run_pass_walks_windows_to_the_cutoff_and_resumes(monkeypatch):
    from app.modules.telemetry.retention_worker import TelemetryRetentionWorker

    worker = TelemetryRetentionWorker(None, settings={"interval_seconds": 0})
    oldest = NOW - timedelta(days=100)
    worker.oldest_observation = AsyncMock(return_value=oldest)
    calls = []
    unfinished = {"observed_at": (oldest + timedelta(days=40)).isoformat(), "record_id": str(uuid.uuid4())}

    async def sweep(req, *, apply, archive_root, deadline):
        calls.append((req.start_time, req.end_time, req.after))
        if len(calls) == 2:
            return [{"deleted": 2, "next_position": unfinished}]
        return [{"deleted": 1, "next_position": None}]

    worker.sweep = sweep
    summary = await worker.run_pass(apply=True, archive_root="/a", min_age=timedelta(days=30),
                                    workspace_ids=[WORKSPACE], now=NOW)
    assert calls[0][:2] == (oldest, oldest + timedelta(days=31))
    assert summary["deleted"] == 3 and summary["incomplete_workspaces"] == 1
    summary = await worker.run_pass(apply=True, archive_root="/a", min_age=timedelta(days=30),
                                    workspace_ids=[WORKSPACE], now=NOW)
    assert calls[2][0] == oldest + timedelta(days=31) and str(calls[2][2].record_id) == unfinished["record_id"]
    assert calls[-1][1] == NOW - timedelta(days=30) and summary["incomplete_workspaces"] == 0


async def test_run_forever_survives_failed_passes_and_stops():
    from app.modules.telemetry.retention_worker import TelemetryRetentionWorker

    worker = TelemetryRetentionWorker(None)
    stop = asyncio.Event()
    passes = []

    async def run_pass(**_):
        passes.append(True)
        if len(passes) == 1:
            raise ConnectionError("postgresql://secret@db")
        stop.set()
        return {"deleted": 0}

    worker.run_pass = run_pass
    await asyncio.wait_for(worker.run_forever(stop, interval_seconds=0.01, apply=False,
                                              archive_root=None, min_age=timedelta(days=1)), 2)
    assert len(passes) == 2


def test_cli_loop_requires_interval_environment_and_bounds():
    from scripts import telemetry_retention as cli

    args = cli.parser().parse_args(["apply", "--loop", "--archive-root", "/a"])
    with pytest.raises(ValueError, match="NANFO_TELEMETRY_RETENTION_INTERVAL_SECONDS"):
        cli.loop_settings(args, environ={})
    with pytest.raises(ValueError):
        cli.loop_settings(args, environ={cli.INTERVAL_ENV: "0"})
    interval, min_age = cli.loop_settings(args, environ={cli.INTERVAL_ENV: "3600", cli.MIN_AGE_ENV: "14"})
    assert interval == 3600 and min_age == timedelta(days=14)
    override = cli.parser().parse_args(["dry-run", "--loop", "--min-age-days", "7"])
    assert cli.loop_settings(override, environ={cli.INTERVAL_ENV: "60"})[1] == timedelta(days=7)


@pytest.mark.parametrize("argv,message", [
    (["restore", "--loop"], "dry-run and apply only"),
    (["dry-run"], "--workspace-id is required"),
    (["apply", "--loop"], "requires --archive-root"),
])
async def test_cli_rejects_invalid_loop_combinations(monkeypatch, argv, message):
    from scripts import telemetry_retention as cli

    monkeypatch.setenv("TELEMETRY_RETENTION_DSN", "postgresql+asyncpg://unused/unused")
    with pytest.raises(ValueError, match=message):
        await cli.run(cli.parser().parse_args(argv))
