"""Configured finite retention sweeps. Each batch has its own transaction/deadline."""

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from app.modules.telemetry.archive import TelemetryArchiveStore
from app.modules.telemetry.reconciliation import TelemetryReconciliationService
from app.modules.telemetry.retention import ArchivalAssessmentRequest, TelemetryRetentionService


class RetentionWorkerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_batches: int = Field(default=10, ge=1, le=1000)
    batch_timeout_seconds: int = Field(default=30, ge=1, le=300)
    interval_seconds: float = Field(default=1, ge=0, le=3600)


class TelemetryRetentionWorker:
    def __init__(self, sessions, *, settings=None):
        self.sessions = sessions
        self.settings = RetentionWorkerSettings.model_validate(settings or {})

    async def sweep(self, request, *, apply=False, archive_root=None):
        request = ArchivalAssessmentRequest.model_validate(request)
        store = TelemetryArchiveStore(archive_root) if apply else None
        results = []
        for _ in range(self.settings.max_batches):
            async with asyncio.timeout(self.settings.batch_timeout_seconds):
                async with self.sessions() as db:
                    service = TelemetryRetentionService(db)
                    result = await (service.apply(request, store=store) if apply else service.assess(request))
                    if apply:
                        await db.commit()
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
