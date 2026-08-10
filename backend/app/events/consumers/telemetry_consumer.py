"""Telemetry event consumer stub.

VS2 Step 6 scope: persist normalized telemetry ingestion events.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.db.postgres import AsyncSessionLocal
from app.db.redis import get_redis_client
from app.events.publisher import publish_event
from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.service import TelemetryPersistenceService
from app.websocket.manager import telemetry_ws_manager

logger = get_logger(__name__)

_RUNTIME_TRANSITION_ALERT_EVENT_MAP: dict[str, str] = {
    "telemetry.collector.sustained_failure_activated": "alert.generated",
    "telemetry.collector.sustained_failure_recovered": "alert.resolved",
}


def _get_counter_service() -> TelemetryHealthCounterService | None:
    try:
        return TelemetryHealthCounterService(get_redis_client())
    except RuntimeError as exc:
        logger.warning("telemetry_health_counter_unavailable", error=str(exc))
        return None


async def _safe_increment_counter(
    incrementer: Callable[[], Awaitable[int]] | None,
    *,
    counter_name: str,
    event_id: str,
    correlation_id: str,
) -> None:
    if incrementer is None:
        return
    try:
        await incrementer()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "telemetry_health_counter_increment_failed",
            counter_name=counter_name,
            event_id=event_id,
            correlation_id=correlation_id,
            error=str(exc),
        )


async def _push_telemetry_delta(event: dict, payload: dict) -> None:
    network_id = str(payload.get("network_id", ""))
    metric_delta = {
        "event_id": str(event.get("event_id", "")),
        "device_id": str(payload.get("device_id", "")),
        "network_id": network_id,
        "workspace_id": str(payload.get("workspace_id", "")),
        "metric": str(payload.get("metric", "")),
        "value": payload.get("value"),
        "unit": payload.get("unit"),
        "observed_at": str(payload.get("observed_at", "")),
        "source": str(payload.get("source", "collector")),
        "tags": payload.get("tags") if isinstance(payload.get("tags"), dict) else {},
    }

    await telemetry_ws_manager.push_delta(
        network_id=network_id,
        event_type=str(event.get("event_type", "")),
        metric=metric_delta,
        correlation_id=str(event.get("correlation_id", "")),
        timestamp=str(event.get("timestamp", datetime.now(UTC).isoformat())),
    )


async def handle_telemetry_event(event: dict) -> None:
    """Persist telemetry events with idempotent event-level semantics."""
    payload = event.get("payload", {})
    counter_service = _get_counter_service()
    event_id = str(event.get("event_id", ""))
    correlation_id = str(event.get("correlation_id", ""))

    logger.info(
        "telemetry_event_received",
        event_type=event.get("event_type", ""),
        correlation_id=correlation_id,
        event_id=event_id,
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
                await _safe_increment_counter(
                    counter_service.increment_persisted if counter_service else None,
                    counter_name="persisted_events",
                    event_id=event_id,
                    correlation_id=correlation_id,
                )
                logger.info(
                    "telemetry_record_persisted",
                    event_id=event_id,
                    correlation_id=correlation_id,
                    metric=payload.get("metric", ""),
                    device_id=payload.get("device_id", ""),
                )
                try:
                    await _push_telemetry_delta(event, payload)
                    await _safe_increment_counter(
                        counter_service.increment_fanout if counter_service else None,
                        counter_name="fanout_events",
                        event_id=event_id,
                        correlation_id=correlation_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "telemetry_ws_fanout_failed",
                        event_id=event_id,
                        correlation_id=correlation_id,
                        error=str(exc),
                    )
                    await _safe_increment_counter(
                        counter_service.increment_dropped if counter_service else None,
                        counter_name="dropped_events",
                        event_id=event_id,
                        correlation_id=correlation_id,
                    )
            else:
                logger.info(
                    "telemetry_record_duplicate_skipped",
                    event_id=event_id,
                    correlation_id=correlation_id,
                )
    except (ValueError, TypeError) as exc:
        await _safe_increment_counter(
            counter_service.increment_dropped if counter_service else None,
            counter_name="dropped_events",
            event_id=event_id,
            correlation_id=correlation_id,
        )
        logger.warning(
            "telemetry_record_validation_failed",
            event_id=event_id,
            correlation_id=correlation_id,
            error=str(exc),
        )
    except SQLAlchemyError as exc:
        logger.warning(
            "telemetry_record_persist_failed",
            event_id=event_id,
            correlation_id=correlation_id,
            error=str(exc),
        )
        raise


def _coerce_correlation_id(value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return str(uuid.uuid4())


async def handle_telemetry_runtime_transition_event(event: dict) -> None:
    """Publish alert lifecycle events for telemetry sustained-failure transitions."""
    source_event_type = str(event.get("event_type", ""))
    alert_event_type = _RUNTIME_TRANSITION_ALERT_EVENT_MAP.get(source_event_type)
    if alert_event_type is None:
        return

    payload_raw = event.get("payload")
    payload = payload_raw if isinstance(payload_raw, dict) else {}
    event_id = str(event.get("event_id", ""))
    correlation_id = _coerce_correlation_id(event.get("correlation_id"))

    try:
        redis = get_redis_client()
    except RuntimeError as exc:
        logger.warning(
            "telemetry_runtime_transition_alert_client_unavailable",
            source_event_type=source_event_type,
            alert_event_type=alert_event_type,
            event_id=event_id,
            correlation_id=correlation_id,
            error=str(exc),
        )
        return

    try:
        stream_entry_id = await publish_event(
            redis=redis,
            event_type=alert_event_type,
            source="telemetry",
            payload=payload,
            correlation_id=correlation_id,
        )
        logger.info(
            "telemetry_runtime_transition_alert_published",
            source_event_type=source_event_type,
            alert_event_type=alert_event_type,
            event_id=event_id,
            correlation_id=correlation_id,
            stream_entry_id=stream_entry_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "telemetry_runtime_transition_alert_publish_failed",
            source_event_type=source_event_type,
            alert_event_type=alert_event_type,
            event_id=event_id,
            correlation_id=correlation_id,
            error=str(exc),
        )


TELEMETRY_HANDLERS: dict[str, object] = {
    "telemetry.metric.ingested": handle_telemetry_event,
    "telemetry.collector.sustained_failure_activated": handle_telemetry_runtime_transition_event,
    "telemetry.collector.sustained_failure_recovered": handle_telemetry_runtime_transition_event,
}
