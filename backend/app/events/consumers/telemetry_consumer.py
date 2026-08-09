"""Telemetry event consumer stub.

VS2 Step 6 scope: persist normalized telemetry ingestion events.
"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.db.postgres import AsyncSessionLocal
from app.modules.telemetry.service import TelemetryPersistenceService

logger = get_logger(__name__)


async def handle_telemetry_event(event: dict) -> None:
    """Persist telemetry events with idempotent event-level semantics."""
    payload = event.get("payload", {})
    logger.info(
        "telemetry_event_received",
        event_type=event.get("event_type", ""),
        correlation_id=event.get("correlation_id", ""),
        event_id=event.get("event_id", ""),
        device_id=payload.get("device_id", ""),
        network_id=payload.get("network_id", ""),
        metric=payload.get("metric", ""),
        value=payload.get("value"),
        observed_at=payload.get("observed_at", ""),
    )

    try:
        async with AsyncSessionLocal() as db:
            persisted = await TelemetryPersistenceService(db).persist_event(event)
            if persisted:
                await db.commit()
                logger.info(
                    "telemetry_record_persisted",
                    event_id=event.get("event_id", ""),
                    correlation_id=event.get("correlation_id", ""),
                    metric=payload.get("metric", ""),
                    device_id=payload.get("device_id", ""),
                )
            else:
                logger.info(
                    "telemetry_record_duplicate_skipped",
                    event_id=event.get("event_id", ""),
                    correlation_id=event.get("correlation_id", ""),
                )
    except (ValueError, TypeError) as exc:
        logger.warning(
            "telemetry_record_validation_failed",
            event_id=event.get("event_id", ""),
            correlation_id=event.get("correlation_id", ""),
            error=str(exc),
        )
    except SQLAlchemyError as exc:
        logger.warning(
            "telemetry_record_persist_failed",
            event_id=event.get("event_id", ""),
            correlation_id=event.get("correlation_id", ""),
            error=str(exc),
        )
        raise


TELEMETRY_HANDLERS: dict[str, object] = {
    "telemetry.metric.ingested": handle_telemetry_event,
}
