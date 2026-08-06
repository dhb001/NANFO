"""NANFO Backend — WebSocket push consumer.

Consumes network.device.* events from Redis Stream and pushes topology deltas
to subscribed WebSocket clients via the TopologyWSManager.
Third consumer of network.device.added (EventAPI.md §5 routing table).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.websocket.manager import topology_ws_manager

logger = get_logger(__name__)

_EVENT_TO_DELTA: dict[str, str] = {
    "network.device.added": "add",
    "network.device.updated": "update",
    "network.device.deleted": "remove",
}


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


WS_PUSH_HANDLERS: dict[str, object] = {
    "network.device.added": handle_ws_push_event,
    "network.device.updated": handle_ws_push_event,
    "network.device.deleted": handle_ws_push_event,
}
