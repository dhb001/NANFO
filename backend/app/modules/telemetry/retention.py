"""Bounded archive-before-delete and restore; unknown history always retained.

Eligibility (ADR-028): coverage is evaluated per owner as the interval from which
every reference to a telemetry row is provably pinned:

- ``reconciled``: the owner's latest reconciliation enumerated its complete
  history with zero unknown items while its prospective coverage is active, so
  every historical reference was pinned and every later write pins first. The
  interval is unbounded: older rows are no longer stranded.
- ``prospective``: otherwise only rows created (and observed) at or after the
  start of the owner's continuous coverage (``registered_at``) are covered.

A row is a candidate only if it was never pinned and every required owner covers
it. Missing, revoked, unknown-version or unknown-owner coverage blocks deletion.
Apply archives up to ``APPLY_MAX_BATCH`` rows as ONE durable segment (one data
fsync + one directory fsync), then tombstones, receipts and deletes them in the
same transaction; it stops early at an optional monotonic deadline.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.telemetry.pin_repository import TelemetryPinRepository
from app.modules.telemetry.pins import REQUIRED_EVIDENCE_OWNERS
from app.modules.telemetry.schemas import TelemetryTimeRange

APPLY_MAX_BATCH = 200


class AssessmentPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_at: AwareDatetime
    record_id: uuid.UUID


class ArchivalAssessmentRequest(TelemetryTimeRange):
    model_config = ConfigDict(extra="forbid")
    workspace_id: uuid.UUID
    start_time: AwareDatetime
    end_time: AwareDatetime
    batch_size: int = Field(default=1000, ge=1, le=1000)
    after: AssessmentPosition | None = None

    @model_validator(mode="after")
    def bounded_window(self) -> Self:
        if self.end_time - self.start_time > timedelta(days=31):
            raise ValueError("assessment window must not exceed 31 days")
        if self.after and not self.start_time <= self.after.observed_at < self.end_time:
            raise ValueError("assessment continuation outside window")
        return self


class OwnerCoverage(BaseModel):
    basis: Literal["reconciled", "prospective"]
    covered_since: datetime | None


class ArchivalAssessment(BaseModel):
    dry_run: bool = True
    deleted: int = 0
    pinned: list[uuid.UUID]
    coverage_unknown: list[uuid.UUID]
    prospective_candidates: list[uuid.UUID]
    missing_owners: list[str]
    coverage_version: int = 1
    prospective_since: datetime | None
    next_position: AssessmentPosition | None
    # Additive (ADR-028): how eligibility was decided and why a batch stopped early.
    coverage_basis: Literal["blocked", "prospective", "reconciled"] = "blocked"
    owner_coverage: dict[str, OwnerCoverage] = Field(default_factory=dict)
    archive_segment_sha256: str | None = None
    stopped: Literal["deadline", "segment_bytes"] | None = None


def coverage_eligibility(coverage, progress) -> tuple[list[str], dict[str, OwnerCoverage] | None]:
    """Return missing owners and per-owner coverage (``None`` means deletion blocked)."""
    valid = {item.owner: item for item in coverage
             if item.owner in REQUIRED_EVIDENCE_OWNERS and item.version == 1
             and item.contract == "pin-before-reference/v1" and item.revoked_at is None}
    missing = sorted(REQUIRED_EVIDENCE_OWNERS - valid.keys())
    # Unknown future owner/version contracts block rather than disappear.
    if missing or any(item.owner not in REQUIRED_EVIDENCE_OWNERS for item in coverage):
        return missing, None
    owners = {}
    for owner, item in sorted(valid.items()):
        scan = progress.get(owner) if isinstance(progress, dict) else None
        if scan is not None and scan.complete is True and scan.unknown == 0:
            owners[owner] = OwnerCoverage(basis="reconciled", covered_since=None)
        else:
            owners[owner] = OwnerCoverage(basis="prospective", covered_since=item.registered_at)
    return missing, owners


class TelemetryRetentionService:
    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = TelemetryPinRepository(db)

    async def assess(self, request: ArchivalAssessmentRequest, *, lock_progress: bool = False) -> ArchivalAssessment:
        return (await self._assess(request, lock_progress=lock_progress))[0]

    async def _assess(self, request, *, lock_progress):
        request = ArchivalAssessmentRequest.model_validate(request)
        coverage = await self._repo.coverage(request.workspace_id)
        progress = await self._repo.reconciliation_progress(request.workspace_id, lock=lock_progress)
        missing, owners = coverage_eligibility(coverage, progress)
        since = None
        if owners is not None:
            since = max((item.covered_since for item in owners.values() if item.covered_since), default=None)
        rows = await self._repo.assessment_batch(
            workspace_id=request.workspace_id, start_time=request.start_time,
            end_time=request.end_time, batch_size=request.batch_size,
            after=(request.after.observed_at, request.after.record_id) if request.after else None,
        )
        result = ArchivalAssessment(
            pinned=[], coverage_unknown=[], prospective_candidates=[], missing_owners=missing,
            prospective_since=since, next_position=None, owner_coverage=owners or {},
            coverage_basis="blocked" if owners is None else "prospective" if since else "reconciled",
        )
        scanned = rows[:request.batch_size]
        for row in scanned:
            if row.pinned:
                result.pinned.append(row.record_id)
            elif owners is None or (since is not None and (row.created_at < since or row.observed_at < since)):
                result.coverage_unknown.append(row.record_id)
            else:
                result.prospective_candidates.append(row.record_id)
        if len(rows) > request.batch_size:
            last = rows[request.batch_size - 1]
            result.next_position = AssessmentPosition(observed_at=last.observed_at, record_id=last.record_id)
        return result, scanned

    async def apply(self, request, *, store, deadline: float | None = None, clock=time.monotonic):
        """Archive-before-delete one bounded batch; the caller commits.

        ``deadline`` is a ``time.monotonic()`` value after which no further rows
        are locked; rows already locked are archived and deleted so the caller
        can commit well inside its transaction timeout.
        """
        from app.modules.telemetry.archive import MAX_SEGMENT_BYTES, build_segment, canonical_record
        from app.modules.telemetry.archive_repository import TelemetryArchiveRepository

        request = ArchivalAssessmentRequest.model_validate(request)
        request = request.model_copy(update={"batch_size": min(request.batch_size, APPLY_MAX_BATCH)})
        archive = TelemetryArchiveRepository(self._db)
        # Revoke and delete serialize on coverage (and reconciliation resets on
        # progress), then pin/delete serialize on rows.
        await archive.lock_coverage(request.workspace_id)
        result, scanned = await self._assess(request, lock_progress=True)
        result.dry_run = False
        candidates = set(result.prospective_candidates)
        # Only restored rows have a receipt; one lookup for the whole batch. A receipt
        # created concurrently implies the row was locked and deleted by that apply.
        receipts = await archive.receipts(candidates) if candidates else {}
        fresh, fresh_bytes, rearchived, size = [], [], [], 0
        last_position = None
        for row in scanned:  # keyset order: an early stop can resume exactly here
            if row.record_id in candidates:
                if deadline is not None and clock() >= deadline:
                    result.stopped = "deadline"
                    break
                locked = await archive.lock_record(request.workspace_id, row.record_id)
                if locked is not None:
                    if await archive.ever_pinned(row.record_id):
                        result.pinned.append(row.record_id)
                    elif (receipt := receipts.get(row.record_id)) is not None:
                        # A restored row: its original immutable archive must still match.
                        data = canonical_record(locked)
                        stored = await asyncio.to_thread(store.read_record, receipt.sha256, receipt.size_bytes,
                                                         row.record_id)
                        if stored != data:
                            raise ValueError("immutable archive identity conflict")
                        rearchived.append(locked)
                    else:
                        data = canonical_record(locked)
                        if fresh and size + len(data) + 1 > MAX_SEGMENT_BYTES - 1024:
                            # Row lock is simply released at commit; resume here next batch.
                            result.stopped = "segment_bytes"
                            break
                        fresh.append(locked)
                        fresh_bytes.append(data)
                        size += len(data) + 1
            last_position = AssessmentPosition(observed_at=row.observed_at, record_id=row.record_id)
        if result.stopped is not None:
            result.next_position = last_position or request.after
        if fresh:
            segment = build_segment(fresh_bytes)
            digest = await asyncio.to_thread(store.write_segment, segment)
            await archive.archive_and_delete_batch(fresh, digest, len(segment))
            result.archive_segment_sha256 = digest
        await archive.delete_rearchived(rearchived)
        result.deleted = len(fresh) + len(rearchived)
        return result

    async def restore(self, *, workspace_id, record_id, store):
        from app.modules.telemetry.archive import canonical_record
        from app.modules.telemetry.archive_repository import TelemetryArchiveRepository
        from app.modules.telemetry.dedup import TelemetryDedupRepository
        from app.modules.telemetry.models import TelemetryRecord

        archive = TelemetryArchiveRepository(self._db)
        receipt = await archive.receipt(workspace_id, record_id)
        if receipt is None:
            raise ValueError("Archive unavailable in workspace")
        await TelemetryDedupRepository(self._db).lock(receipt.event_id)
        data = await asyncio.to_thread(store.read_record, receipt.sha256, receipt.size_bytes, record_id)
        values = json.loads(data)
        for key in ("record_id", "event_id", "correlation_id", "device_id", "network_id", "workspace_id"):
            values[key] = uuid.UUID(values[key])
        for key in ("observed_at", "created_at"):
            values[key] = datetime.fromisoformat(values[key])
        if (values["workspace_id"] != workspace_id or values["record_id"] != record_id
                or values["event_id"] != receipt.event_id):
            raise ValueError("Archive identity mismatch")
        row = TelemetryRecord(**values)
        if canonical_record(row) != data:
            raise ValueError("Archive is not canonical")
        existing = await self._db.get(TelemetryRecord, record_id)
        if existing is not None:
            if canonical_record(existing) != data:
                raise ValueError("Restore conflicts with active record")
            return False
        self._db.add(row)
        await self._db.flush()
        await archive.mark_restored(record_id)
        return True
