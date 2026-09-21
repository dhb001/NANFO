"""Independent bounded report worker with durable lease fencing and outbox replay."""

import asyncio

from fastapi import HTTPException

from app.core.config import get_settings
from app.modules.report.artifacts import (
    ArtifactStore,
    ReportCapacityError,
    digest,
    render,
)
from app.modules.report.repository import ReportRepository
from app.modules.report.schemas import GenerateReportRequest
from app.modules.report.service import ReportService
from app.modules.report.sources import ReportSources


class ReportWorker:
    def __init__(self, *, sessions, redis, settings=None):
        self.sessions, self.redis = sessions, redis
        self.settings = settings or get_settings()

    async def run_one(self):
        async with self.sessions() as db:
            claimed = await ReportRepository(db).claim(
                self.settings.REPORTS_LEASE_SECONDS
            )
        if claimed is None:
            return False
        receipt, error = None, None
        try:
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
            if digest(claimed.snapshot) != claimed.snapshot_sha256:
                raise ValueError("Invalid snapshot")
            store = ArtifactStore(
                self.settings.REPORTS_STORAGE_PATH, self.settings.REPORTS_MAX_BYTES
            )
            await asyncio.to_thread(
                store.require_capacity, self.settings.REPORTS_MIN_FREE_BYTES
            )
            data = await asyncio.to_thread(
                render,
                claimed.snapshot,
                claimed.output_format,
                self.settings.REPORTS_MAX_BYTES,
            )
            receipt = await asyncio.to_thread(
                store.write,
                claimed.report_id,
                claimed.lease_token,
                claimed.output_format,
                data,
                min_free_bytes=self.settings.REPORTS_MIN_FREE_BYTES,
            )
            await asyncio.to_thread(
                store.read, claimed.report_id, claimed.output_format, receipt
            )
            async with asyncio.timeout(20), self.sessions() as db:
                await ReportService(db=db, redis=self.redis).authorize_generation(
                    claimed.workspace_id,
                    claimed.network_id,
                    claimed.requested_by_user_id,
                )
                await ReportRepository(db).finish(claimed, receipt=receipt)
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
        async with self.sessions() as db:
            await ReportRepository(db).finish(claimed, error=error)
        return True

    async def publish_one(self):
        async with self.sessions() as db:
            return await ReportRepository(db).publish_one(self.redis)
