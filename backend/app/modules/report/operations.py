"""Report-owned maintenance inventory, receipt verification and bounded orphan GC.

``inventory``/``cleanup`` are the offline operator tools: the caller must stop
every application writer first. A repeatable-read inventory is not a substitute
for that operational exclusion, and no report records, snapshots or receipts are
changed by them.

ADR-028 adds two online operations used by the report worker:
``cleanup_orphans`` removes attempt files that no row references even while jobs
are active (the in-flight attempt of every leased job is protected and a grace
period covers attempts that have not committed yet), and ``expire_generated``
implements the opt-in ``REPORTS_RETENTION_DAYS`` policy.
"""

import asyncio
import os
import re
import stat
import time
import uuid
from datetime import timedelta

from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.modules.report.artifacts import ArtifactStore, valid_receipt
from app.modules.report.models import ReportOutbox, ReportRecord

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ATTEMPT = re.compile(rf"({UUID})-({UUID})\.(csv|pdf)\Z")


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

    async def _references(self, *, max_records=100_000):
        """Filenames referenced by any row, and each active job's in-flight attempt."""
        total = await self.db.scalar(select(func.count()).select_from(ReportRecord))
        if total > max_records:
            raise ValueError("Report inventory cap exceeded; nothing may be removed")
        pinned, in_flight = set(), set()
        rows = await self.db.stream(
            select(
                ReportRecord.report_id,
                ReportRecord.status,
                ReportRecord.lease_token,
                ReportRecord.receipt["filename"].astext,
                ReportRecord.artifact_refs,
            ).execution_options(yield_per=500)
        )
        async for report_id, status, lease_token, receipt_file, references in rows:
            if receipt_file:
                pinned.add(receipt_file)
            for reference in references or []:
                if isinstance(reference, dict) and isinstance(reference.get("filename"), str):
                    pinned.add(reference["filename"])
            if status in {"requested", "running"} and lease_token is not None:
                in_flight.add((str(report_id), str(lease_token)))
        return pinned, in_flight

    async def cleanup_orphans(
        self,
        *,
        apply=False,
        grace_seconds=86400,
        batch_size=100,
        max_scan=100_000,
        now=None,
    ):
        """Remove attempt files that no report row references (ADR-028).

        Unlike ``cleanup`` this does not require zero active jobs: the current
        attempt of every requested/running job (file ``<report>-<lease>``) is never
        a candidate, and files younger than ``grace_seconds`` (>= 1 h) may belong to
        an attempt that has not committed yet. Registered artifacts, symlinks,
        foreign/non-private files and unknown names are never touched.
        """
        if not 3600 <= grace_seconds <= 3650 * 86400 or not 1 <= batch_size <= 1000:
            raise ValueError("Grace must be at least 1h; batch must be 1..1000")
        pinned, in_flight = await self._references()
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
                    match = ATTEMPT.fullmatch(entry.name)
                    if (
                        match is None
                        or entry.name in pinned
                        or (match.group(1), match.group(2)) in in_flight
                    ):
                        continue
                    try:
                        info = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
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
            removed = changed = 0
            if apply:
                for name, before in candidates:
                    try:
                        current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    except FileNotFoundError:
                        continue  # already removed by a concurrent worker
                    if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns,
                            current.st_ctime_ns) != (before.st_dev, before.st_ino, before.st_size,
                                                     before.st_mtime_ns, before.st_ctime_ns):
                        changed += 1
                        continue
                    try:
                        os.unlink(name, dir_fd=directory)
                    except FileNotFoundError:
                        continue
                    removed += 1
                if removed:
                    os.fsync(directory)
            return {
                "mode": "apply" if apply else "dry_run",
                "candidates": len(candidates),
                "candidate_bytes": sum(info.st_size for _, info in candidates),
                "removed": removed,
                "changed": changed,
                "batch_limit": batch_size,
                "grace_seconds": grace_seconds,
                "registered_files": len(pinned),
                "active_attempts": len(in_flight),
            }
        finally:
            os.close(directory)

    async def expire_generated(self, *, retention_days, batch_size=100):
        """Opt-in retention: delete generated reports completed > N days ago.

        Rows are deleted first (committed), then their artifact files; a file whose
        removal fails becomes an unreferenced orphan for ``cleanup_orphans``. Rows
        with unpublished lifecycle events are kept until their outbox drains.
        """
        if not 1 <= retention_days <= 36500 or not 1 <= batch_size <= 1000:
            raise ValueError("Retention must be 1..36500 days; batch must be 1..1000")
        unpublished = (
            select(ReportOutbox.event_id)
            .where(
                ReportOutbox.report_id == ReportRecord.report_id,
                ReportOutbox.published_at.is_(None),
            )
            .exists()
        )
        rows = (
            await self.db.execute(
                select(ReportRecord.report_id, ReportRecord.output_format, ReportRecord.receipt)
                .where(
                    ReportRecord.status == "generated",
                    ReportRecord.completed_at < func.now() - timedelta(days=retention_days),
                    ~unpublished,
                )
                .order_by(ReportRecord.completed_at, ReportRecord.report_id)
                .limit(batch_size)
                .with_for_update(of=ReportRecord, skip_locked=True)
            )
        ).all()
        if not rows:
            await self.db.rollback()
            return {"expired": 0, "removed_files": 0, "retention_days": retention_days}
        await self.db.execute(
            delete(ReportRecord).where(ReportRecord.report_id.in_([row[0] for row in rows]))
        )
        await self.db.commit()
        removed = 0
        for report_id, output_format, receipt in rows:
            if not isinstance(receipt, dict):
                continue
            try:
                if await asyncio.to_thread(
                    self.store.remove, uuid.UUID(str(report_id)), output_format, receipt
                ):
                    removed += 1
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return {"expired": len(rows), "removed_files": removed, "retention_days": retention_days}
