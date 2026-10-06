"""Independent bounded report worker with durable lease fencing and outbox replay.

ADR-028: claims are bounded by ``claim_attempts`` (``REPORTS_MAX_CLAIM_ATTEMPTS``,
default 5), the lease is renewed while rendering, an attempt whose terminal CAS
loses deletes its own file, and a periodic maintenance step removes unreferenced
attempt files, (opt-in, ``REPORTS_RETENTION_DAYS``) expired generated reports and
published outbox rows older than ``REPORT_OUTBOX_RETENTION_DAYS`` (default 30,
``0`` keeps them).
"""

import asyncio
import contextlib
import time

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.report.artifacts import (
    ArtifactStore,
    ReportCapacityError,
    digest,
    render,
)
from app.modules.report.operations import ReportOperationsService
from app.modules.report.repository import (
    DEFAULT_MAX_CLAIM_ATTEMPTS,
    DEFAULT_OUTBOX_RETENTION_DAYS,
    OUTBOX_PURGE_BATCH,
    ReportRepository,
)
from app.modules.report.schemas import GenerateReportRequest
from app.modules.report.service import ReportService
from app.modules.report.sources import ReportSources

logger = get_logger(__name__)
# Published-outbox batches deleted per maintenance run (bounded work per interval).
OUTBOX_PURGE_MAX_BATCHES = 10


def bounded_setting(settings, name, default, low, high):
    """Optional numeric setting read with ``getattr``; out-of-range values are clamped."""
    value = getattr(settings, name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return min(max(value, low), high)


class LeaseLost(Exception):
    """The job lease was lost or fenced while this attempt was still working."""


class ReportWorker:
    def __init__(self, *, sessions, redis, settings=None, clock=time.monotonic):
        self.sessions, self.redis = sessions, redis
        self.settings = settings or get_settings()
        self.clock = clock
        self.max_attempts = int(bounded_setting(
            self.settings, "REPORTS_MAX_CLAIM_ATTEMPTS", DEFAULT_MAX_CLAIM_ATTEMPTS, 1, 100))
        self.retention_days = int(bounded_setting(self.settings, "REPORTS_RETENTION_DAYS", 0, 0, 36500))
        self.orphan_grace_seconds = int(bounded_setting(
            self.settings, "REPORTS_ORPHAN_GRACE_SECONDS", 86400, 3600, 3650 * 86400))
        self.maintenance_interval = float(bounded_setting(
            self.settings, "REPORTS_MAINTENANCE_INTERVAL_SECONDS", 3600, 60, 86400))
        self.outbox_retention_days = int(bounded_setting(
            self.settings, "REPORT_OUTBOX_RETENTION_DAYS", DEFAULT_OUTBOX_RETENTION_DAYS, 0, 36500))
        self._next_maintenance = 0.0

    def _store(self):
        return ArtifactStore(self.settings.REPORTS_STORAGE_PATH, self.settings.REPORTS_MAX_BYTES)

    async def _renew(self, claimed, lost):
        # Renew three times per lease (REPORTS_LEASE_SECONDS is validated 30..300).
        interval = max(0.05, self.settings.REPORTS_LEASE_SECONDS / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                async with asyncio.timeout(interval), self.sessions() as db:
                    renewed = await ReportRepository(db).renew_lease(claimed, self.settings.REPORTS_LEASE_SECONDS)
            except Exception as exc:  # noqa: BLE001 - retry; the CAS fences an expired lease
                logger.warning("report_lease_renewal_deferred", error_type=type(exc).__name__)
                continue
            if not renewed:
                lost.set()
                return

    @contextlib.asynccontextmanager
    async def _leased(self, claimed):
        lost = asyncio.Event()
        renewal = asyncio.create_task(self._renew(claimed, lost))
        try:
            yield lost
        finally:
            renewal.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renewal

    @staticmethod
    def _require_lease(lost):
        if lost.is_set():
            raise LeaseLost()

    async def _discard(self, store, claimed, receipt):
        """Remove this attempt's file; it is not (and will never be) referenced."""
        try:
            await asyncio.to_thread(store.remove, claimed.report_id, claimed.output_format, receipt)
        except (OSError, ValueError) as exc:
            # Orphan cleanup removes it later; never fail the iteration for it.
            logger.warning("report_attempt_file_retained", error_type=type(exc).__name__)

    async def run_one(self):
        async with self.sessions() as db:
            claimed = await ReportRepository(db).claim(
                self.settings.REPORTS_LEASE_SECONDS, max_attempts=self.max_attempts
            )
        if claimed is None:
            return False
        store, written, error = self._store(), None, None
        try:
            async with self._leased(claimed) as lost:
                request = GenerateReportRequest.model_validate(claimed.snapshot["request"])
                async with asyncio.timeout(20), self.sessions() as db:
                    await ReportService(db=db, redis=self.redis).authorize_generation(
                        claimed.workspace_id,
                        claimed.network_id,
                        claimed.requested_by_user_id,
                    )
                    await ReportSources(db, self.redis).revalidate(
                        request, claimed.requested_by_user_id
                    )
                if await asyncio.to_thread(digest, claimed.snapshot) != claimed.snapshot_sha256:
                    raise ValueError("Invalid snapshot")
                await asyncio.to_thread(
                    store.require_capacity, self.settings.REPORTS_MIN_FREE_BYTES
                )
                data = await asyncio.to_thread(
                    render,
                    claimed.snapshot,
                    claimed.output_format,
                    self.settings.REPORTS_MAX_BYTES,
                )
                self._require_lease(lost)
                written = await asyncio.to_thread(
                    store.write,
                    claimed.report_id,
                    claimed.lease_token,
                    claimed.output_format,
                    data,
                    min_free_bytes=self.settings.REPORTS_MIN_FREE_BYTES,
                )
                del data
                verified = await asyncio.to_thread(
                    store.open_verified, claimed.report_id, claimed.output_format, written
                )
                verified.close()
                self._require_lease(lost)
                async with asyncio.timeout(20), self.sessions() as db:
                    await ReportService(db=db, redis=self.redis).authorize_generation(
                        claimed.workspace_id,
                        claimed.network_id,
                        claimed.requested_by_user_id,
                    )
                    finished = await ReportRepository(db).finish(claimed, receipt=written)
            if not finished:
                # Lease lost or fenced: the row never references this attempt's file.
                await self._discard(store, claimed, written)
            return True
        except LeaseLost:
            if written is not None:
                await self._discard(store, claimed, written)
            return True
        except ReportCapacityError:
            error = {
                "code": "REPORT_STORAGE_UNAVAILABLE",
                "message": "Report storage reserve exhausted; free capacity before requesting another report.",
            }
        except HTTPException:
            error = {
                "code": "REPORT_AUTHORITY_REVOKED",
                "message": "Current report generation authority or source scope is unavailable.",
            }
        except (ValueError, TypeError, KeyError, OSError, TimeoutError):
            error = {
                "code": "REPORT_GENERATION_FAILED",
                "message": "Snapshot/render/storage validation failed; check protected storage and narrow report scope.",
            }
        if written is not None:
            await self._discard(store, claimed, written)
        async with self.sessions() as db:
            await ReportRepository(db).finish(claimed, error=error)
        return True

    async def _purge_outbox(self):
        deleted, batches = 0, 0
        while batches < OUTBOX_PURGE_MAX_BATCHES:
            async with self.sessions() as db:
                count = await ReportRepository(db).purge_published_outbox(retention_days=self.outbox_retention_days)
            batches += 1
            deleted += count
            if count < OUTBOX_PURGE_BATCH:
                break
        return {"deleted": deleted, "batches": batches, "retention_days": self.outbox_retention_days}

    async def publish_one(self):
        async with self.sessions() as db:
            return await ReportRepository(db).publish_one(self.redis)

    async def maintain(self, *, force=False):
        """Bounded periodic storage maintenance; at most once per interval.

        Removes unreferenced attempt files older than the orphan grace (active
        jobs do not block it; in-flight attempts are protected by their lease),
        only when ``REPORTS_RETENTION_DAYS > 0`` expires generated reports, and
        deletes published outbox rows past ``REPORT_OUTBOX_RETENTION_DAYS``. Steps are
        isolated: a storage fault never starves the database-only outbox purge (a
        failed step is logged and retried next interval).
        """
        now = self.clock()
        if not force and now < self._next_maintenance:
            return None
        self._next_maintenance = now + self.maintenance_interval

        async def expire():
            async with self.sessions() as db:
                return await ReportOperationsService(db, store=self._store()).expire_generated(
                    retention_days=self.retention_days
                )

        async def orphans():
            async with self.sessions() as db:
                return await ReportOperationsService(db, store=self._store()).cleanup_orphans(
                    apply=True, grace_seconds=self.orphan_grace_seconds
                )

        steps = [("retention", expire)] if self.retention_days > 0 else []
        steps.append(("orphans", orphans))
        if self.outbox_retention_days > 0:
            steps.append(("outbox", self._purge_outbox))
        result = {}
        async with asyncio.timeout(120):
            for name, step in steps:
                try:
                    result[name] = await step()
                except Exception as exc:  # noqa: BLE001 - isolated; retried next interval
                    logger.warning("report_maintenance_step_deferred", step=name, error_type=type(exc).__name__)
        logger.info("report_storage_maintenance", **{
            key: {name: value for name, value in section.items() if isinstance(value, int)}
            for key, section in result.items()
        })
        return result
