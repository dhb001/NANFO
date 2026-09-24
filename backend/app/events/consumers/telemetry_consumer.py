"""Telemetry event consumer.

Persists normalized telemetry ingestion events idempotently, then performs
downstream work. Only failures *before* or *during* the owning commit are
raised for retry/dead-lettering. Realtime WebSocket fanout after a successful
commit is best-effort: it is logged with a fixed error code and counted as a
dropped delta, and the persisted event is acknowledged (a retry could not
re-persist it and would only dead-letter valid, durable telemetry).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from app.core.correlation import correlation_uuid
from app.core.logging import get_logger
from app.db.postgres import AsyncSessionLocal
from app.db.redis import get_redis_client
from app.events.publisher import publish_event
from app.events.fanout import push_realtime_delta
from app.events.consumers.alert_consumer import handle_persisted_metric_event
from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.service import TelemetryPersistenceService
from app.websocket.manager import telemetry_ws_manager

logger = get_logger(__name__)

TELEMETRY_FANOUT_FAILED = "TELEMETRY_FANOUT_FAILED"

_RUNTIME_TRANSITION_ALERT_EVENT_MAP: dict[str, str] = {
    "telemetry.collector.sustained_failure_activated": "alert.generated",
    "telemetry.collector.sustained_failure_recovered": "alert.resolved",
}


def _get_counter_service() -> TelemetryHealthCounterService | None:
    try:
        return TelemetryHealthCounterService(get_redis_client())
    except RuntimeError as exc:
        logger.warning("telemetry_health_counter_unavailable", error_code="TELEMETRY_COUNTERS_UNAVAILABLE",
                       error_type=type(exc).__name__)
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
            error_code="TELEMETRY_COUNTER_UPDATE_FAILED",
            error_type=type(exc).__name__,
            counter_name=counter_name,
            event_id=event_id,
            correlation_id=correlation_id,
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

    await push_realtime_delta(telemetry_ws_manager, channel="telemetry", event=event,
        network_id=network_id,
        event_type=str(event.get("event_type", "")),
        metric=metric_delta,
        correlation_id=str(event.get("correlation_id", "")),
        timestamp=str(event.get("timestamp", datetime.now(UTC).isoformat())),
        workspace_id=str(payload.get("workspace_id", "")).strip() or None,
    )


async def _best_effort_fanout(
    event: dict,
    payload: dict,
    *,
    counter_service: TelemetryHealthCounterService | None,
    event_id: str,
    correlation_id: str,
    count_success: bool,
) -> bool:
    """Push the realtime delta; never propagate after the owning commit."""
    try:
        await _push_telemetry_delta(event, payload)
    except Exception as exc:  # noqa: BLE001 - durable record already committed
        logger.warning(
            "telemetry_ws_fanout_failed",
            error_code=TELEMETRY_FANOUT_FAILED,
            error_type=type(exc).__name__,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        await _safe_increment_counter(
            counter_service.increment_dropped if counter_service else None,
            counter_name="dropped_events",
            event_id=event_id,
            correlation_id=correlation_id,
        )
        return False
    if count_success:
        await _safe_increment_counter(
            counter_service.increment_fanout if counter_service else None,
            counter_name="fanout_events",
            event_id=event_id,
            correlation_id=correlation_id,
        )
    return True


async def handle_telemetry_event(event: dict) -> None:
    """Persist telemetry events with idempotent event-level semantics.

    Raised for retry/DLQ: invalid events (deterministic), database failures and
    downstream alert-ingestion failures (recovered by the idempotent replay path).
    Never raised: realtime fanout failures after the commit.
    """
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
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
            service = TelemetryPersistenceService(db)
            persisted = await service.persist_event(event)
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
                await handle_persisted_metric_event(event)
                await _best_effort_fanout(
                    event, payload, counter_service=counter_service, event_id=event_id,
                    correlation_id=correlation_id, count_success=True,
                )
            else:
                logger.info(
                    "telemetry_record_duplicate_skipped",
                    event_id=event_id,
                    correlation_id=correlation_id,
                )
                # A committed active event may need publication recovery, but a
                # duplicate ID is not authority for its incoming payload/scopes.
                replay = await service.replay_event(event)
                if replay.status == "tombstone":
                    return
                if replay.status == "active_conflict":
                    raise ValueError("Telemetry event identity conflicts with persisted record")
                await handle_persisted_metric_event(replay.event)
                await _best_effort_fanout(
                    replay.event, replay.event["payload"], counter_service=counter_service,
                    event_id=event_id, correlation_id=correlation_id, count_success=False,
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
            error_code="TELEMETRY_EVENT_INVALID",
            error_type=type(exc).__name__,
            event_id=event_id,
            correlation_id=correlation_id,
            error=str(exc),
        )
        raise
    except SQLAlchemyError as exc:
        logger.warning(
            "telemetry_record_persist_failed",
            error_code="TELEMETRY_PERSIST_FAILED",
            error_type=type(exc).__name__,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        raise


def _coerce_correlation_id(value: object, *, fallback: str = "") -> str:
    """Stable UUID via the shared ADR-028 mapping; opaque ids never become random.

    A missing correlation falls back to the source event identity so retries of
    the same transition always carry the same correlation.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    text = str(value).strip() if value is not None else ""
    if not text and fallback:
        text = f"telemetry-event:{fallback}"
    return str(correlation_uuid(text or None))


async def handle_telemetry_runtime_transition_event(event: dict) -> None:
    """Publish alert lifecycle events for telemetry sustained-failure transitions."""
    source_event_type = str(event.get("event_type", ""))
    alert_event_type = _RUNTIME_TRANSITION_ALERT_EVENT_MAP.get(source_event_type)
    if alert_event_type is None:
        return

    payload_raw = event.get("payload")
    payload = payload_raw if isinstance(payload_raw, dict) else {}
    event_id = str(event.get("event_id", ""))
    correlation_id = _coerce_correlation_id(event.get("correlation_id"), fallback=event_id)

    try:
        redis = get_redis_client()
    except RuntimeError as exc:
        logger.warning(
            "telemetry_runtime_transition_alert_client_unavailable",
            error_code="TELEMETRY_TRANSITION_ALERT_UNAVAILABLE",
            error_type=type(exc).__name__,
            source_event_type=source_event_type,
            alert_event_type=alert_event_type,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        raise

    try:
        stream_entry_id = await publish_event(
            redis=redis,
            event_type=alert_event_type,
            source="telemetry",
            payload=payload,
            correlation_id=correlation_id,
            event_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{event_id}:{alert_event_type}")),
        )
        logger.info(
            "telemetry_runtime_transition_alert_published",
            source_event_type=source_event_type,
            alert_event_type=alert_event_type,
            event_id=event_id,
            correlation_id=correlation_id,
            stream_entry_id=stream_entry_id,
        )
    except Exception as exc:
        logger.warning(
            "telemetry_runtime_transition_alert_publish_failed",
            error_code="TELEMETRY_TRANSITION_ALERT_PUBLISH_FAILED",
            error_type=type(exc).__name__,
            source_event_type=source_event_type,
            alert_event_type=alert_event_type,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        raise


TELEMETRY_HANDLERS: dict[str, object] = {
    "telemetry.metric.ingested": handle_telemetry_event,
    "telemetry.collector.sustained_failure_activated": handle_telemetry_runtime_transition_event,
    "telemetry.collector.sustained_failure_recovered": handle_telemetry_runtime_transition_event,
}
