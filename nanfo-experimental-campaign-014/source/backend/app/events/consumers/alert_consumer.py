"""NANFO Backend - Alert lifecycle event consumer.

Consumes alert lifecycle events and persists alert entity state.
"""

from __future__ import annotations

from app.db.postgres import AsyncSessionLocal
from app.modules.alert.service import AlertService
from app.modules.alert.measured import MeasuredAlertService


async def handle_persisted_metric_event(event: dict) -> None:
    async with AsyncSessionLocal() as db:
        await MeasuredAlertService(db=db).ingest_persisted_event(event)


async def handle_alert_lifecycle_event(event: dict) -> None:
    """Persist alert state transitions from alert lifecycle events."""
    async with AsyncSessionLocal() as db:
        service = AlertService(db=db, redis=None)
        await service.ingest_alert_event(event)


ALERT_HANDLERS: dict[str, object] = {
    "alert.generated": handle_alert_lifecycle_event,
    "alert.acknowledged": handle_alert_lifecycle_event,
    "alert.resolved": handle_alert_lifecycle_event,
}
