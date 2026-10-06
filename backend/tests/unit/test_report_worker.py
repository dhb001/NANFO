import asyncio
import os
import time
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.report.artifacts import ArtifactStore, digest
from app.modules.report.models import ReportOutbox
from app.modules.report.repository import ReportRepository
from app.modules.report.worker import ReportWorker, bounded_setting
from tests.report_support import snapshot


async def test_worker_revoked_actor_fails_without_rendering(mock_db, tmp_path):
    value = snapshot()
    row = SimpleNamespace(
        snapshot=value,
        snapshot_sha256=digest(value),
        workspace_id=uuid.uuid4(),
        network_id=None,
        requested_by_user_id=str(uuid.uuid4()),
    )

    def sessions():
        return mock_db

    mock_db.__aenter__.return_value = mock_db
    settings = SimpleNamespace(
        REPORTS_LEASE_SECONDS=30,
        REPORTS_MAX_BYTES=100000,
        REPORTS_STORAGE_PATH=str(tmp_path),
    )
    with (
        patch(
            "app.modules.report.worker.ReportRepository.claim",
            AsyncMock(return_value=row),
        ),
        patch(
            "app.modules.report.worker.ReportRepository.finish", AsyncMock()
        ) as finish,
        patch(
            "app.modules.report.worker.ReportService.authorize_generation",
            AsyncMock(side_effect=HTTPException(403)),
        ),
        patch("app.modules.report.worker.render") as renderer,
    ):
        assert await ReportWorker(
            sessions=sessions, redis=None, settings=settings
        ).run_one()
    renderer.assert_not_called()
    assert finish.await_args.kwargs["error"]["code"] == "REPORT_AUTHORITY_REVOKED"


async def test_worker_no_job_is_idle(mock_db):
    mock_db.__aenter__.return_value = mock_db
    with patch(
        "app.modules.report.worker.ReportRepository.claim", AsyncMock(return_value=None)
    ):
        assert not await ReportWorker(sessions=lambda: mock_db, redis=None).run_one()


# ---------------------------------------------------------------- ADR-028 ---

NOW = datetime(2026, 9, 23, tzinfo=UTC)


class ClaimSession:
    """Fake session: FOR UPDATE selects pop queued jobs, other scalars return now()."""

    def __init__(self, records):
        self.records, self.added, self.commits = list(records), [], 0

    async def scalar(self, statement):
        if getattr(statement, "_for_update_arg", None) is not None:
            return self.records.pop(0) if self.records else None
        return NOW

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1


def job(**overrides):
    value = snapshot()
    return SimpleNamespace(**{
        "report_id": uuid.uuid4(), "workspace_id": uuid.uuid4(), "network_id": None,
        "report_type": "executive_summary", "output_format": "csv", "status": "running",
        "status_version": 2, "snapshot": value, "snapshot_sha256": digest(value),
        "requested_by_user_id": str(uuid.uuid4()), "requested_at": NOW, "artifact_refs": [],
        "error_context": {}, "completed_at": None, "correlation_id": uuid.uuid4(),
        "lease_token": uuid.uuid4(), "lease_expires_at": NOW, "claim_attempts": 0,
        "receipt": None, "queue_status": "queued", **overrides,
    })


async def test_claim_counts_attempts_and_terminalizes_exhausted_jobs():
    # Regression: a poisoned FIFO head was re-claimed forever (crash loop).
    exhausted, runnable = job(claim_attempts=5), job(claim_attempts=2, status="requested", status_version=1)
    db = ClaimSession([exhausted, runnable])
    claimed = await ReportRepository(db).claim(30, max_attempts=5)
    assert claimed is runnable
    assert runnable.claim_attempts == 3 and runnable.status == "running" and runnable.status_version == 2
    assert exhausted.status == "failed" and exhausted.status_version == 3
    assert exhausted.error_context["reason"] == "attempts_exhausted"
    assert exhausted.error_context["code"] == "REPORT_ATTEMPTS_EXHAUSTED"
    assert exhausted.lease_token is None and exhausted.lease_expires_at is None and exhausted.completed_at == NOW
    (event,) = db.added
    assert isinstance(event, ReportOutbox) and event.envelope["event_type"] == "report.failed"
    assert '"reason":"attempts_exhausted"' in event.envelope["payload"]
    assert db.commits == 2


async def test_claim_below_the_bound_increments_and_idles_when_empty():
    db = ClaimSession([job(claim_attempts=4, status="requested", status_version=1)])
    claimed = await ReportRepository(db).claim(30, max_attempts=5)
    assert claimed.claim_attempts == 5 and claimed.status == "running"
    assert await ReportRepository(db).claim(30, max_attempts=5) is None


def test_optional_settings_are_read_with_getattr_and_bounded():
    assert bounded_setting(SimpleNamespace(), "REPORTS_MAX_CLAIM_ATTEMPTS", 5, 1, 100) == 5
    assert bounded_setting(SimpleNamespace(REPORTS_MAX_CLAIM_ATTEMPTS=0), "REPORTS_MAX_CLAIM_ATTEMPTS", 5, 1, 100) == 1
    assert bounded_setting(SimpleNamespace(REPORTS_MAX_CLAIM_ATTEMPTS=True), "REPORTS_MAX_CLAIM_ATTEMPTS", 5, 1, 100) == 5
    worker = ReportWorker(sessions=None, redis=None, settings=SimpleNamespace(REPORTS_MAX_CLAIM_ATTEMPTS=3))
    assert worker.max_attempts == 3 and worker.retention_days == 0


def storage_settings(tmp_path, **extra):
    os.chmod(tmp_path, 0o700)
    return SimpleNamespace(REPORTS_LEASE_SECONDS=30, REPORTS_MAX_BYTES=100000, REPORTS_STORAGE_PATH=str(tmp_path),
                           REPORTS_MIN_FREE_BYTES=0, **extra)


def patched_worker_io(row, *, authorize=None, finish_result=True):
    return (
        patch("app.modules.report.worker.ReportRepository.claim", AsyncMock(return_value=row)),
        patch("app.modules.report.worker.ReportService.authorize_generation", authorize or AsyncMock()),
        patch("app.modules.report.worker.ReportSources.revalidate", AsyncMock()),
        patch("app.modules.report.worker.ReportRepository.finish", AsyncMock(return_value=finish_result)),
    )


async def test_generated_artifact_is_kept_when_the_terminal_cas_wins(mock_db, tmp_path):
    mock_db.__aenter__.return_value = mock_db
    row = job()
    claim, authorize, revalidate, finish = patched_worker_io(row)
    with claim, authorize, revalidate, finish as finished:
        assert await ReportWorker(sessions=lambda: mock_db, redis=None, settings=storage_settings(tmp_path)).run_one()
    receipt = finished.await_args.kwargs["receipt"]
    assert [path.name for path in tmp_path.iterdir()] == [receipt["filename"]]


async def test_lost_terminal_cas_deletes_its_own_attempt_file(mock_db, tmp_path):
    # Regression: attempts that lost the lease left unreferenced files behind.
    mock_db.__aenter__.return_value = mock_db
    claim, authorize, revalidate, finish = patched_worker_io(job(), finish_result=False)
    with claim, authorize, revalidate, finish as finished:
        assert await ReportWorker(sessions=lambda: mock_db, redis=None, settings=storage_settings(tmp_path)).run_one()
    finished.assert_awaited_once()
    assert list(tmp_path.iterdir()) == []


async def test_authority_revoked_after_write_fails_job_and_deletes_file(mock_db, tmp_path):
    mock_db.__aenter__.return_value = mock_db
    authorize = AsyncMock(side_effect=[None, HTTPException(403)])
    claim, authorize_patch, revalidate, finish = patched_worker_io(job(), authorize=authorize)
    with claim, authorize_patch, revalidate, finish as finished:
        assert await ReportWorker(sessions=lambda: mock_db, redis=None, settings=storage_settings(tmp_path)).run_one()
    assert finished.await_args.kwargs["error"]["code"] == "REPORT_AUTHORITY_REVOKED"
    assert list(tmp_path.iterdir()) == []


async def test_lease_is_renewed_while_rendering_and_loss_aborts_without_terminal_write(mock_db, tmp_path):
    mock_db.__aenter__.return_value = mock_db
    settings = storage_settings(tmp_path)
    settings.REPORTS_LEASE_SECONDS = 0.15  # renewal every 50 ms in this test
    original_open = ArtifactStore.open_verified

    def slow_verify(self, *args, **kwargs):
        time.sleep(0.3)  # the lease is lost while this attempt still works
        return original_open(self, *args, **kwargs)

    claim, authorize, revalidate, finish = patched_worker_io(job())
    with claim, authorize, revalidate, finish as finished, \
            patch.object(ArtifactStore, "open_verified", slow_verify), \
            patch("app.modules.report.worker.ReportRepository.renew_lease", AsyncMock(return_value=False)) as renew:
        assert await ReportWorker(sessions=lambda: mock_db, redis=None, settings=settings).run_one()
    renew.assert_awaited()
    finished.assert_not_awaited()  # another worker owns the job now
    assert list(tmp_path.iterdir()) == []


async def test_renewal_keeps_a_live_lease(mock_db, tmp_path):
    mock_db.__aenter__.return_value = mock_db
    settings = storage_settings(tmp_path)
    settings.REPORTS_LEASE_SECONDS = 0.15
    original_render = __import__("app.modules.report.worker", fromlist=["render"]).render

    def slow_render(*args):
        time.sleep(0.2)
        return original_render(*args)

    claim, authorize, revalidate, finish = patched_worker_io(job())
    with claim, authorize, revalidate, finish as finished, patch("app.modules.report.worker.render", slow_render), \
            patch("app.modules.report.worker.ReportRepository.renew_lease", AsyncMock(return_value=True)) as renew:
        assert await ReportWorker(sessions=lambda: mock_db, redis=None, settings=settings).run_one()
    assert renew.await_count >= 1
    finished.assert_awaited_once()
    assert len(list(tmp_path.iterdir())) == 1


async def test_maintenance_is_interval_gated_and_retention_is_opt_in(mock_db, tmp_path):
    mock_db.__aenter__.return_value = mock_db
    clock = [1000.0]
    orphans = AsyncMock(return_value={"removed": 2, "mode": "apply"})
    expire = AsyncMock(return_value={"expired": 1})
    outbox = AsyncMock(return_value=0)
    with patch("app.modules.report.worker.ReportOperationsService.cleanup_orphans", orphans), \
            patch("app.modules.report.worker.ReportOperationsService.expire_generated", expire), \
            patch("app.modules.report.worker.ReportRepository.purge_published_outbox", outbox):
        keep = ReportWorker(sessions=lambda: mock_db, redis=None, settings=storage_settings(tmp_path),
                            clock=lambda: clock[0])
        first = await keep.maintain()
        assert first["orphans"]["removed"] == 2
        assert first["outbox"] == {"deleted": 0, "batches": 1, "retention_days": 30}  # outbox default: 30 days
        expire.assert_not_awaited()  # REPORTS_RETENTION_DAYS defaults to 0 = keep
        assert orphans.await_args.kwargs == {"apply": True, "grace_seconds": 86400}
        assert await keep.maintain() is None  # within the interval
        clock[0] += 3600
        assert await keep.maintain() is not None
        expiring = ReportWorker(sessions=lambda: mock_db, redis=None,
                                settings=storage_settings(tmp_path, REPORTS_RETENTION_DAYS=30), clock=lambda: clock[0])
        result = await expiring.maintain()
    assert result["retention"] == {"expired": 1}
    expire.assert_awaited_once_with(retention_days=30)


async def test_worker_loop_isolates_failed_iterations_with_backoff():
    # Regression: an unguarded run_one exception terminated the worker process.
    from scripts.run_report_worker import iteration_delay, run

    worker = SimpleNamespace(run_one=AsyncMock(side_effect=[RuntimeError("poisoned job"), True, False]),
                             publish_one=AsyncMock(return_value=False), maintain=AsyncMock())
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    await run(worker, iterations=3, sleep=sleep, logger=SimpleNamespace(warning=lambda *a, **k: None))
    assert worker.run_one.await_count == 3 and worker.publish_one.await_count == 3
    assert 0.25 <= delays[0] <= 0.5 and delays[1:] == [0.05, 0.5]
    assert iteration_delay(busy=False, failures=12, rng=lambda: 1.0) == 30.0
    assert iteration_delay(busy=False, failures=3, rng=lambda: 0.0) == 1.0
    with pytest.raises(RuntimeError):
        await run(SimpleNamespace(run_one=AsyncMock(side_effect=RuntimeError("x")), publish_one=AsyncMock(),
                                  maintain=AsyncMock()), once=True, sleep=sleep,
                  logger=SimpleNamespace(warning=lambda *a, **k: None))


async def test_worker_loop_survives_outbox_and_maintenance_failures():
    from scripts.run_report_worker import run

    worker = SimpleNamespace(run_one=AsyncMock(return_value=False),
                             publish_one=AsyncMock(side_effect=ConnectionError("redis down")),
                             maintain=AsyncMock(side_effect=OSError("storage")))
    await run(worker, iterations=2, sleep=lambda seconds: asyncio.sleep(0),
              logger=SimpleNamespace(warning=lambda *a, **k: None))
    assert worker.run_one.await_count == 2 and worker.maintain.await_count == 2


# ---------------------------------------------- ADR-028 report outbox retention ---

class PurgeSession:
    def __init__(self, deleted=0):
        self.deleted, self.statements, self.commits = deleted, [], 0

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: [(index,) for index in range(self.deleted)])

    async def commit(self):
        self.commits += 1


@pytest.mark.parametrize("created_at", [True, False], ids=["created_at-column", "column-absent-guard"])
async def test_published_outbox_purge_is_one_bounded_batch_of_published_rows_only(monkeypatch, created_at):
    from sqlalchemy import literal_column
    from sqlalchemy.dialects import postgresql

    from app.modules.report import repository

    column = literal_column("report_outbox.created_at") if created_at else None
    monkeypatch.setattr(repository, "outbox_age_column", lambda: column)
    db = PurgeSession(deleted=4)
    assert await ReportRepository(db).purge_published_outbox(retention_days=30, batch_size=200) == 4
    assert db.commits == 1
    compiled = db.statements[0].compile(dialect=postgresql.dialect())
    sql = " ".join(str(compiled).split())
    assert sql.startswith("DELETE FROM report_outbox WHERE report_outbox.event_id IN (SELECT report_outbox.event_id")
    # Unpublished rows (the pending delivery queue) are never candidates.
    assert "report_outbox.published_at IS NOT NULL AND report_outbox.published_at < now() - %(now_1)s" in sql
    assert ("report_outbox.created_at < now() - %(now_1)s" in sql) is created_at
    assert "LIMIT %(param_1)s FOR UPDATE SKIP LOCKED" in sql and "RETURNING report_outbox.event_id" in sql
    assert compiled.params["now_1"].days == 30 and compiled.params["param_1"] == 200


def test_outbox_age_column_is_the_migrated_created_at_when_the_model_has_it():
    from app.modules.report.repository import outbox_age_column

    assert outbox_age_column() is getattr(ReportOutbox, "created_at", None)


@pytest.mark.parametrize("kwargs", [dict(retention_days=0), dict(retention_days=36501),
                                    dict(retention_days=1, batch_size=0), dict(retention_days=1, batch_size=10001)])
async def test_published_outbox_purge_refuses_unbounded_parameters(kwargs):
    db = PurgeSession()
    with pytest.raises(ValueError):
        await ReportRepository(db).purge_published_outbox(**kwargs)
    assert db.statements == []


async def test_maintenance_purges_published_outbox_in_bounded_batches_and_isolates_steps(mock_db, tmp_path):
    mock_db.__aenter__.return_value = mock_db
    purge = AsyncMock(side_effect=[500, 500, 3])
    orphans = AsyncMock(side_effect=ValueError("storage root is not private"))
    with patch("app.modules.report.worker.ReportRepository.purge_published_outbox", purge), \
            patch("app.modules.report.worker.ReportOperationsService.cleanup_orphans", orphans):
        worker = ReportWorker(sessions=lambda: mock_db, redis=None, settings=storage_settings(tmp_path))
        assert worker.outbox_retention_days == 30  # REPORT_OUTBOX_RETENTION_DAYS default
        result = await worker.maintain()
    # A storage fault in orphan cleanup never starves the database-only outbox purge.
    assert "orphans" not in result
    assert result["outbox"] == {"deleted": 1003, "batches": 3, "retention_days": 30}
    assert purge.await_args.kwargs == {"retention_days": 30}
    capped = AsyncMock(return_value=500)
    with patch("app.modules.report.worker.ReportRepository.purge_published_outbox", capped), \
            patch("app.modules.report.worker.ReportOperationsService.cleanup_orphans", AsyncMock(return_value={})):
        worker = ReportWorker(sessions=lambda: mock_db, redis=None,
                              settings=storage_settings(tmp_path, REPORT_OUTBOX_RETENTION_DAYS=7))
        assert (await worker.maintain())["outbox"] == {"deleted": 5000, "batches": 10, "retention_days": 7}


async def test_outbox_retention_zero_keeps_published_rows(mock_db, tmp_path):
    mock_db.__aenter__.return_value = mock_db
    purge = AsyncMock()
    with patch("app.modules.report.worker.ReportRepository.purge_published_outbox", purge), \
            patch("app.modules.report.worker.ReportOperationsService.cleanup_orphans", AsyncMock(return_value={})):
        worker = ReportWorker(sessions=lambda: mock_db, redis=None,
                              settings=storage_settings(tmp_path, REPORT_OUTBOX_RETENTION_DAYS=0))
        assert "outbox" not in await worker.maintain()
    purge.assert_not_awaited()
