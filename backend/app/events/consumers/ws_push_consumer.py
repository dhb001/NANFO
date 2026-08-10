"""NANFO Backend — WebSocket push consumer.

Consumes network.device.* events from Redis Stream and pushes topology deltas
to subscribed WebSocket clients via channel managers.
Routes `network.device.*` -> `/ws/topology` and `alert.*` -> `/ws/alerts`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.db.redis import get_redis_client
from app.websocket.manager import alerts_ws_manager, topology_ws_manager

logger = get_logger(__name__)

_EVENT_TO_DELTA: dict[str, str] = {
    "network.device.added": "add",
    "network.device.updated": "update",
    "network.device.deleted": "remove",
}

_ALERT_EVENT_TO_DELTA: dict[str, str] = {
    "alert.generated": "add",
    "alert.resolved": "resolve",
}

_ALERT_EVENT_TO_COUNTER_LABEL: dict[str, str] = {
    "alert.generated": "generated",
    "alert.resolved": "resolved",
}

_ALERT_WS_COUNTER_PREFIX = "alerts:ws:fanout"


def _get_alert_counter_client():
    try:
        return get_redis_client()
    except RuntimeError as exc:
        logger.warning("ws_alert_counter_client_unavailable", error=str(exc))
        return None


async def _safe_increment_alert_counter(
    redis,
    *,
    counter_name: str,
    event_type: str,
    event_id: str,
    correlation_id: str,
) -> None:
    if redis is None:
        return
    try:
        await redis.incr(counter_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ws_alert_counter_increment_failed",
            counter_name=counter_name,
            event_type=event_type,
            event_id=event_id,
            correlation_id=correlation_id,
            error=str(exc),
        )


async def handle_ws_push_event(event: dict) -> None:
    """Translate a network.device.* event into a /ws/topology delta push."""
    event_type = event.get("event_type", "")
    delta_type = _EVENT_TO_DELTA.get(event_type)
    if delta_type is None:
        return

    payload = event.get("payload", {})
    network_id = payload.get("network_id")
    if not network_id:
        logger.warning("ws_push_missing_network_id", event_type=event_type)
        return

    # Build the delta node — for 'remove', only device_id is needed (WebSocket.md §4.1)
    if delta_type == "remove":
        node = {"device_id": payload["device_id"]}
    elif delta_type == "update":
        # Only include changed_fields in the node (WebSocket.md §4.1)
        node = {"device_id": payload["device_id"], **payload.get("changed_fields", {})}
    else:
        node = {
            "device_id": payload.get("device_id"),
            "hostname": payload.get("hostname"),
            "device_type": payload.get("device_type"),
            "status": "active",
        }

    await topology_ws_manager.push_delta(
        network_id=network_id,
        event_type=event_type,
        delta_type=delta_type,
        node=node,
        correlation_id=event.get("correlation_id", ""),
        timestamp=event.get("timestamp", datetime.now(UTC).isoformat()),
    )
    logger.info("ws_delta_pushed", event_type=event_type, network_id=network_id, delta_type=delta_type)


async def handle_ws_alert_event(event: dict) -> None:
    """Translate an alert.* event into a /ws/alerts delta push."""
    event_type = str(event.get("event_type", ""))
    delta_type = _ALERT_EVENT_TO_DELTA.get(event_type)
    if delta_type is None:
        return

    counter_label = _ALERT_EVENT_TO_COUNTER_LABEL[event_type]
    event_id = str(event.get("event_id", ""))
    correlation_id = str(event.get("correlation_id", ""))
    counter_client = _get_alert_counter_client()

    payload_raw = event.get("payload")
    payload = payload_raw if isinstance(payload_raw, dict) else {}
    alert = {
        "event_id": event_id,
        "event_type": event_type,
        "source": str(event.get("source", "")),
        "payload": payload,
    }

    try:
        await alerts_ws_manager.push_delta(
            event_type=event_type,
            delta_type=delta_type,
            alert=alert,
            correlation_id=correlation_id,
            timestamp=str(event.get("timestamp", datetime.now(UTC).isoformat())),
        )
        success_counter = f"{_ALERT_WS_COUNTER_PREFIX}:{counter_label}:success"
        await _safe_increment_alert_counter(
            counter_client,
            counter_name=success_counter,
            event_type=event_type,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        logger.info("ws_alert_delta_pushed", event_type=event_type, delta_type=delta_type)
    except Exception as exc:  # noqa: BLE001
        failure_counter = f"{_ALERT_WS_COUNTER_PREFIX}:{counter_label}:failure"
        await _safe_increment_alert_counter(
            counter_client,
            counter_name=failure_counter,
            event_type=event_type,
            event_id=event_id,
            correlation_id=correlation_id,
        )
        logger.warning(
            "ws_alert_delta_push_failed",
            event_type=event_type,
            delta_type=delta_type,
            event_id=event_id,
            correlation_id=correlation_id,
            error=str(exc),
        )


WS_PUSH_HANDLERS: dict[str, object] = {
    "network.device.added": handle_ws_push_event,
    "network.device.updated": handle_ws_push_event,
    "network.device.deleted": handle_ws_push_event,
    "alert.generated": handle_ws_alert_event,
    "alert.resolved": handle_ws_alert_event,
}
