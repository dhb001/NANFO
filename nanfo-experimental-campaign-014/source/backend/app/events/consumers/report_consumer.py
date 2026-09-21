"""NANFO Backend - Report lifecycle event consumer.

Report lifecycle events are notifications; durable jobs are owned by the worker.
"""

from __future__ import annotations

from app.db.postgres import AsyncSessionLocal
from app.modules.report.service import ReportService


async def handle_report_lifecycle_event(event: dict) -> None:
    """Never render or terminalize jobs in the shared event consumer."""
    async with AsyncSessionLocal() as db:
        service = ReportService(db=db, redis=None)
        await service.process_requested_event(event)


REPORT_HANDLERS: dict[str, object] = {
    "report.requested": handle_report_lifecycle_event,
}
