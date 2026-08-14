"""NANFO Backend - Report lifecycle event consumer.

Consumes report lifecycle events and advances report generation state.
"""

from __future__ import annotations

from app.db.postgres import AsyncSessionLocal
from app.modules.report.service import ReportService


async def handle_report_lifecycle_event(event: dict) -> None:
    """Process report lifecycle events for queue-to-artifact transitions."""
    async with AsyncSessionLocal() as db:
        service = ReportService(db=db, redis=None)
        await service.process_requested_event(event)


REPORT_HANDLERS: dict[str, object] = {
    "report.requested": handle_report_lifecycle_event,
}
