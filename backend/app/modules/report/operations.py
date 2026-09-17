"""Report-owned maintenance inventory, receipt verification and bounded orphan GC.

Caller must stop every application writer before invoking this service. A
repeatable-read inventory is not a substitute for that operational exclusion.
No report records, snapshots or receipts are changed by these operations.
"""

import asyncio
import os
import re
import stat
import time

from sqlalchemy import func, select

from app.core.config import get_settings
from app.modules.report.artifacts import ArtifactStore, valid_receipt
from app.modules.report.models import ReportRecord

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ATTEMPT = re.compile(rf"{UUID}-{UUID}\.(csv|pdf)\Z")


class ReportOperationsService:
    def __init__(self, db, *, store=None):
        self.db = db
        settings = get_settings()
        self.store = store or ArtifactStore(
            settings.REPORTS_STORAGE_PATH, settings.REPORTS_MAX_BYTES
        )

    async def inventory(self, *, verify=False, max_records=100_000):
        active = await self.db.scalar(
            select(func.count())
            .select_from(ReportRecord)
            .where(ReportRecord.status.not_in(["generated", "failed"]))
        )
        total = await self.db.scalar(select(func.count()).select_from(ReportRecord))
        if total > max_records:
            raise ValueError("Report inventory cap exceeded; nothing may be removed")
        names, verified, legacy = set(), 0, 0
        rows = await self.db.stream_scalars(
            select(ReportRecord).execution_options(yield_per=100)
        )
        async for row in rows:
            # All recorded references are pins, including failed/legacy/uncertain ones.
            for reference in [row.receipt, *(row.artifact_refs or [])]:
                if isinstance(reference, dict) and reference.get("filename"):
                    names.add(reference["filename"])
            if row.artifact_version != 1:
                legacy += 1
                continue
            if row.status == "generated":
                if not valid_receipt(row):
                    raise ValueError("Registered report receipt is invalid")
                if verify:
                    await asyncio.to_thread(
                        self.store.read, row.report_id, row.output_format, row.receipt
                    )
                    verified += 1
        return {
            "active_jobs": active,
            "registered_files": sorted(names),
            "verified_reports": verified,
            "legacy_reports": legacy,
            "total_reports": total,
        }

    async def cleanup(
        self,
        *,
        apply=False,
        grace_seconds=86400,
        batch_size=100,
        max_scan=100_000,
        now=None,
    ):
        if not 86400 <= grace_seconds <= 3650 * 86400 or not 1 <= batch_size <= 1000:
            raise ValueError("Grace must be at least 24h; batch must be 1..1000")
        inventory = await self.inventory(verify=True)
        if inventory["active_jobs"] or inventory["legacy_reports"]:
            raise ValueError(
                "Active or legacy report jobs prevent proven orphan cleanup"
            )
        pinned = set(inventory["registered_files"])
        cutoff = (time.time() if now is None else now) - grace_seconds
        directory = self.store._directory()
        candidates = []
        try:
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    if index >= max_scan:
                        raise ValueError(
                            "Directory inventory cap exceeded; nothing removed"
                        )
                    if entry.name in pinned or not ATTEMPT.fullmatch(entry.name):
                        continue
                    info = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_nlink != 1
                        or info.st_uid != os.geteuid()
                        or info.st_mode & 0o077
                        or max(info.st_mtime, info.st_ctime) > cutoff
                    ):
                        continue
                    if len(candidates) < batch_size:
                        candidates.append((entry.name, info))
            removed = 0
            if apply:
                for name, before in candidates:
                    current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if (
                        current.st_dev,
                        current.st_ino,
                        current.st_size,
                        current.st_mtime_ns,
                        current.st_ctime_ns,
                    ) != (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                        before.st_ctime_ns,
                    ):
                        raise ValueError(
                            "Artifact changed after inventory; cleanup stopped"
                        )
                    os.unlink(name, dir_fd=directory)
                    removed += 1
                os.fsync(directory)
            return {
                "mode": "apply" if apply else "dry_run",
                "candidates": len(candidates),
                "candidate_bytes": sum(info.st_size for _, info in candidates),
                "removed": removed,
                "batch_limit": batch_size,
                "grace_seconds": grace_seconds,
                "registered_files": len(pinned),
                "verified_reports": inventory["verified_reports"],
            }
        finally:
            os.close(directory)
