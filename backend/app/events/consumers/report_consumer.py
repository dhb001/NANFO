"""NANFO Backend - Report lifecycle event consumer.

Report lifecycle events are notifications; durable jobs are owned by the worker.

A notification without the report identity Report publishes is poison and raises
:class:`DeterministicEventError` (dead-lettered on first delivery, ADR-028 C14);
transient failures propagate unchanged and stay pending for reclaim.
"""

from __future__ import annotations

from app.core.errors import DeterministicEventError
from app.db.postgres import AsyncSessionLocal
from app.modules.report.service import ReportEventRejected, ReportService


async def handle_report_lifecycle_event(event: dict) -> None:
    """Never render or terminalize jobs in the shared event consumer."""
    try:
        async with AsyncSessionLocal() as db:
            service = ReportService(db=db, redis=None)
            await service.process_requested_event(event)
    except ReportEventRejected as exc:
        raise DeterministicEventError(exc.reason) from None


REPORT_HANDLERS: dict[str, object] = {
    "report.requested": handle_report_lifecycle_event,
}
