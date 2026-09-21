"""Bounded archive-before-delete and restore; unknown history always retained."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.telemetry.pin_repository import TelemetryPinRepository
from app.modules.telemetry.pins import REQUIRED_EVIDENCE_OWNERS
from app.modules.telemetry.schemas import TelemetryTimeRange


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


class TelemetryRetentionService:
    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = TelemetryPinRepository(db)

    async def apply(self, request: ArchivalAssessmentRequest, *, store):
        from app.modules.telemetry.archive import canonical_record
        from app.modules.telemetry.archive_repository import TelemetryArchiveRepository

        request = ArchivalAssessmentRequest.model_validate(request)
        archive = TelemetryArchiveRepository(self._db)
        # Revoke and delete serialize on coverage, then pin/delete serialize on rows.
        await archive.lock_coverage(request.workspace_id)
        result = await self.assess(request)
        result.dry_run = False
        for record_id in sorted(result.prospective_candidates):
            row = await archive.lock_record(request.workspace_id, record_id)
            if row is None:
                continue
            if await archive.ever_pinned(record_id):
                result.pinned.append(record_id)
                continue
            data = canonical_record(row)
            digest = await asyncio.to_thread(store.write, data)
            await archive.archive_and_delete(row, digest, len(data))
            result.deleted += 1
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
        data = await asyncio.to_thread(store.read, receipt.sha256, receipt.size_bytes)
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

    async def assess(self, request: ArchivalAssessmentRequest) -> ArchivalAssessment:
        request = ArchivalAssessmentRequest.model_validate(request)
        coverage = await self._repo.coverage(request.workspace_id)
        valid = {item.owner: item.registered_at for item in coverage
                 if item.owner in REQUIRED_EVIDENCE_OWNERS and item.version == 1
                 and item.contract == "pin-before-reference/v1" and item.revoked_at is None}
        missing = sorted(REQUIRED_EVIDENCE_OWNERS - valid.keys())
        # Unknown future owner/version contracts block rather than disappear.
        unknown = any(item.owner not in REQUIRED_EVIDENCE_OWNERS for item in coverage)
        since = max(valid.values()) if not missing and not unknown else None
        rows = await self._repo.assessment_batch(
            workspace_id=request.workspace_id, start_time=request.start_time,
            end_time=request.end_time, batch_size=request.batch_size,
            after=(request.after.observed_at, request.after.record_id) if request.after else None,
        )
        result = ArchivalAssessment(
            pinned=[], coverage_unknown=[], prospective_candidates=[], missing_owners=missing,
            prospective_since=since, next_position=None,
        )
        for row in rows[:request.batch_size]:
            if row.pinned:
                result.pinned.append(row.record_id)
            elif since is None or row.created_at < since or row.observed_at < since:
                result.coverage_unknown.append(row.record_id)
            else:
                result.prospective_candidates.append(row.record_id)
        if len(rows) > request.batch_size:
            last = rows[request.batch_size - 1]
            result.next_position = AssessmentPosition(observed_at=last.observed_at, record_id=last.record_id)
        return result
