"""Configured bounded retention sweeps and the supervised ``--loop`` pass driver.

Each batch runs in its own session/transaction and commits before the next one
(chunks of at most ``APPLY_MAX_BATCH`` rows). A sweep-wide monotonic deadline
stops scheduling new batches, and inside a batch row locking stops at half the
batch budget so the segment write and commit always finish inside the batch
timeout instead of being cancelled mid-transaction.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.core.logging import get_logger
from app.modules.telemetry.archive import TelemetryArchiveStore
from app.modules.telemetry.reconciliation import TelemetryReconciliationService
from app.modules.telemetry.retention import (
    APPLY_MAX_BATCH,
    ArchivalAssessmentRequest,
    AssessmentPosition,
    TelemetryRetentionService,
)

logger = get_logger(__name__)

WINDOW = timedelta(days=31)


class RetentionWorkerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_batches: int = Field(default=10, ge=1, le=1000)
    batch_timeout_seconds: int = Field(default=30, ge=1, le=300)
    interval_seconds: float = Field(default=1, ge=0, le=3600)
    sweep_deadline_seconds: float = Field(default=900, ge=1, le=86400)


@dataclass
class _Cursor:
    window_start: datetime
    after: AssessmentPosition | None


class TelemetryRetentionWorker:
    def __init__(self, sessions, *, settings=None, clock: Callable[[], float] = time.monotonic):
        self.sessions = sessions
        self.settings = RetentionWorkerSettings.model_validate(settings or {})
        self._clock = clock
        self._cursors: dict[uuid.UUID, _Cursor] = {}

    async def sweep(self, request, *, apply=False, archive_root=None, deadline: float | None = None):
        request = ArchivalAssessmentRequest.model_validate(request)
        store = TelemetryArchiveStore(archive_root) if apply else None
        sweep_deadline = deadline if deadline is not None else self._clock() + self.settings.sweep_deadline_seconds
        results = []
        for _ in range(self.settings.max_batches):
            remaining = sweep_deadline - self._clock()
            if remaining <= 0:
                break
            timeout = min(float(self.settings.batch_timeout_seconds), remaining)
            async with asyncio.timeout(timeout):
                async with self.sessions() as db:
                    service = TelemetryRetentionService(db)
                    if apply:
                        result = await service.apply(request, store=store, deadline=self._clock() + timeout / 2)
                        await db.commit()
                    else:
                        result = await service.assess(request)
                    results.append(result.model_dump(mode="json"))
            if result.next_position is None:
                break
            request = request.model_copy(update={"after": result.next_position})
            await asyncio.sleep(self.settings.interval_seconds)
        return results

    async def reconcile(self, *, workspace_id, owner, limit=100):
        results = []
        for _ in range(self.settings.max_batches):
            async with asyncio.timeout(self.settings.batch_timeout_seconds):
                async with self.sessions() as db:
                    result = await TelemetryReconciliationService(db).step(
                        workspace_id=workspace_id, owner=owner, limit=limit)
                    await db.commit()
                    results.append(result)
            if result["complete"]:
                break
            await asyncio.sleep(self.settings.interval_seconds)
        return results

    # -- supervised loop -----------------------------------------------------------
    async def enrolled_workspaces(self) -> list[uuid.UUID]:
        """Workspaces with any coverage row: the only ones where deletion can happen."""
        from app.modules.telemetry.pin_models import TelemetryReferenceCoverage

        async with self.sessions() as db:
            rows = await db.scalars(select(TelemetryReferenceCoverage.workspace_id).distinct()
                                    .order_by(TelemetryReferenceCoverage.workspace_id))
            return list(rows.all())

    async def oldest_observation(self, workspace_id: uuid.UUID) -> datetime | None:
        from app.modules.telemetry.models import TelemetryRecord

        async with self.sessions() as db:
            return await db.scalar(select(func.min(TelemetryRecord.observed_at))
                                   .where(TelemetryRecord.workspace_id == workspace_id))

    async def run_pass(self, *, apply: bool, archive_root, min_age: timedelta,
                       workspace_ids: list[uuid.UUID] | None = None, now: datetime | None = None) -> dict:
        """Walk each workspace from its oldest window up to ``now - min_age``.

        An unfinished window (batch budget or deadline) is resumed by the next
        pass from its exact keyset position; a completed walk restarts from the
        oldest remaining observation next time.
        """
        cutoff = (now or datetime.now(UTC)) - min_age
        deadline = self._clock() + self.settings.sweep_deadline_seconds
        summary = {"cutoff": cutoff.isoformat(), "workspaces": 0, "deleted": 0, "batches": 0,
                   "incomplete_workspaces": 0}
        for workspace_id in workspace_ids or await self.enrolled_workspaces():
            summary["workspaces"] += 1
            cursor = self._cursors.pop(workspace_id, None)
            start = cursor.window_start if cursor else await self.oldest_observation(workspace_id)
            after = cursor.after if cursor else None
            while start is not None and start < cutoff:
                if self._clock() >= deadline:
                    self._cursors[workspace_id] = _Cursor(start, after)
                    summary["incomplete_workspaces"] += 1
                    break
                end = min(start + WINDOW, cutoff)
                request = ArchivalAssessmentRequest(
                    workspace_id=workspace_id, start_time=start, end_time=end, after=after,
                    batch_size=APPLY_MAX_BATCH if apply else 1000)
                results = await self.sweep(request, apply=apply, archive_root=archive_root, deadline=deadline)
                summary["batches"] += len(results)
                summary["deleted"] += sum(item["deleted"] for item in results)
                position = results[-1]["next_position"] if results else None
                if not results or position is not None:
                    resume = AssessmentPosition.model_validate(position) if position else after
                    self._cursors[workspace_id] = _Cursor(start, resume)
                    summary["incomplete_workspaces"] += 1
                    break
                start, after = end, None
        return summary

    async def run_forever(self, stop: asyncio.Event, *, interval_seconds: float, **pass_options) -> None:
        while not stop.is_set():
            try:
                summary = await self.run_pass(**pass_options)
                logger.info("telemetry_retention_pass_completed", **summary)
            except Exception as exc:  # noqa: BLE001 - supervised loop; the next pass retries
                logger.warning("telemetry_retention_pass_failed", error_code="retention_pass_failed",
                               error_type=type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass
