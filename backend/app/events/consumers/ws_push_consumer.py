"""NANFO Backend — WebSocket push consumer.

Consumes network.device.* events from Redis Stream and pushes topology deltas
to subscribed WebSocket clients via channel managers.
Routes `network.device.*` -> `/ws/topology`, `alert.*` -> `/ws/alerts`, and
`simulation.*` -> `/ws/digital-twin` scene deltas.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.db.redis import get_redis_client
from app.websocket.manager import (
    alerts_ws_manager,
    digital_twin_ws_manager,
    topology_ws_manager,
)

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

_SIMULATION_EVENT_TO_DELTA: dict[str, str] = {
    "simulation.started": "update",
    "simulation.completed": "update",
    "simulation.paused": "update",
    "simulation.cancelled": "update",
    "simulation.branch_created": "update",
}

_INTENT_EVENT_TO_DELTA: dict[str, str] = {
    "intent.validated": "update",
    "intent.execution_started": "update",
    "intent.execution_completed": "update",
    "intent.execution_failed": "update",
}


def _get_alert_counter_client():
    try:
        return get_redis_client()
    except RuntimeError as exc:
        logger.warning("ws_alert_counter_client_unavailable", error=str(exc))
        return None


def _extract_uuid_text(payload: dict, *keys: str) -> str | None:
    for key in keys:
        raw = payload.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        try:
            return str(uuid.UUID(text))
        except (TypeError, ValueError, AttributeError):
            continue
    return None


def _extract_verification_and_rollback_status(payload: dict) -> tuple[str | None, str | None]:
    execution_provenance_raw = payload.get("execution_provenance")
    if not isinstance(execution_provenance_raw, dict):
        return None, None

    verification_status = None
    verification_raw = execution_provenance_raw.get("verification")
    if isinstance(verification_raw, dict):
        status_value = str(verification_raw.get("status", "")).strip()
        if status_value:
            verification_status = status_value

    rollback_status = None
    rollback_raw = execution_provenance_raw.get("rollback")
    if isinstance(rollback_raw, dict):
        status_value = str(rollback_raw.get("status", "")).strip()
        if status_value:
            rollback_status = status_value

    return verification_status, rollback_status


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


async def handle_ws_digital_twin_event(event: dict) -> None:
    """Translate a simulation.* event into a /ws/digital-twin scene delta push."""
    event_type = str(event.get("event_type", ""))
    delta_type = _SIMULATION_EVENT_TO_DELTA.get(event_type)
    if delta_type is None:
        return

    payload_raw = event.get("payload")
    payload = payload_raw if isinstance(payload_raw, dict) else {}

    network_id = _extract_uuid_text(payload, "network_id") or ""
    if not network_id:
        logger.warning("ws_digital_twin_missing_network_id", event_type=event_type)
        return

    scene_object_id = str(payload.get("scene_object_id", "")).strip() or "simulation-state"
    state = str(payload.get("state", "unknown")).strip() or "unknown"
    simulation_id = str(payload.get("simulation_id", "")).strip()
    scenario_id = str(payload.get("scenario_id", "")).strip()
    risk_gate = str(payload.get("risk_gate", "pending")).strip() or "pending"
    status = str(payload.get("status", "pending")).strip() or "pending"
    spatial_ref_present = "spatial_ref_id" in payload
    spatial_ref_id = None
    if spatial_ref_present:
        raw_spatial_ref = payload.get("spatial_ref_id")
        if raw_spatial_ref is not None:
            normalized_spatial_ref = str(raw_spatial_ref).strip()
            spatial_ref_id = normalized_spatial_ref or None

    spatial_metadata_raw = payload.get("spatial_metadata")
    has_spatial_metadata = isinstance(spatial_metadata_raw, dict)

    changed_fields = {
        "state": state,
        "status": status,
        "risk_gate": risk_gate,
        "scenario_id": scenario_id,
    }
    if spatial_ref_present:
        changed_fields["spatial_ref_id"] = spatial_ref_id
    if has_spatial_metadata:
        changed_fields["spatial_metadata"] = spatial_metadata_raw

    scene_object = {
        "id": scene_object_id,
        "object_type": "simulation_state",
        "state": state,
        "simulation_id": simulation_id,
        "scenario_id": scenario_id,
        "risk_gate": risk_gate,
        "status": status,
        "changed_fields": changed_fields,
    }
    if spatial_ref_present:
        scene_object["spatial_ref_id"] = spatial_ref_id
    if has_spatial_metadata:
        scene_object["spatial_metadata"] = spatial_metadata_raw

    await digital_twin_ws_manager.push_delta(
        network_id=network_id,
        event_type=event_type,
        delta_type=delta_type,
        scene_object=scene_object,
        correlation_id=str(event.get("correlation_id", "")),
        timestamp=str(event.get("timestamp", datetime.now(UTC).isoformat())),
    )
    logger.info(
        "ws_digital_twin_delta_pushed",
        event_type=event_type,
        network_id=network_id,
        scene_object_id=scene_object_id,
        simulation_id=simulation_id,
        scenario_id=scenario_id,
        delta_type=delta_type,
    )


async def handle_ws_intent_event(event: dict) -> None:
    """Translate intent.* events into /ws/digital-twin baseline intent state deltas."""
    event_type = str(event.get("event_type", ""))
    delta_type = _INTENT_EVENT_TO_DELTA.get(event_type)
    if delta_type is None:
        return

    payload_raw = event.get("payload")
    payload = payload_raw if isinstance(payload_raw, dict) else {}

    network_id = _extract_uuid_text(payload, "network_id") or ""
    if not network_id:
        logger.warning("ws_intent_missing_network_id", event_type=event_type)
        return

    intent_id = _extract_uuid_text(payload, "intent_id") or ""
    status = str(payload.get("status", "unknown")).strip() or "unknown"
    scene_object_id = f"intent-{intent_id}" if intent_id else "intent-state"

    verification_status, rollback_status = _extract_verification_and_rollback_status(payload)
    changed_fields = {
        "status": status,
        "intent_kind": str(payload.get("intent_kind", "")).strip(),
        "confidence": payload.get("confidence") if isinstance(payload.get("confidence"), dict) else {},
    }
    if verification_status is not None:
        changed_fields["verification_status"] = verification_status
    if rollback_status is not None:
        changed_fields["rollback_status"] = rollback_status

    scene_object = {
        "id": scene_object_id,
        "object_type": "intent_state",
        "intent_id": intent_id,
        "status": status,
        "changed_fields": changed_fields,
    }

    await digital_twin_ws_manager.push_delta(
        network_id=network_id,
        event_type=event_type,
        delta_type=delta_type,
        scene_object=scene_object,
        correlation_id=str(event.get("correlation_id", "")),
        timestamp=str(event.get("timestamp", datetime.now(UTC).isoformat())),
    )
    logger.info(
        "ws_intent_delta_pushed",
        event_type=event_type,
        network_id=network_id,
        scene_object_id=scene_object_id,
        intent_id=intent_id,
        delta_type=delta_type,
    )


WS_PUSH_HANDLERS: dict[str, object] = {
    "network.device.added": handle_ws_push_event,
    "network.device.updated": handle_ws_push_event,
    "network.device.deleted": handle_ws_push_event,
    "alert.generated": handle_ws_alert_event,
    "alert.resolved": handle_ws_alert_event,
    "simulation.started": handle_ws_digital_twin_event,
    "simulation.completed": handle_ws_digital_twin_event,
    "simulation.paused": handle_ws_digital_twin_event,
    "simulation.cancelled": handle_ws_digital_twin_event,
    "simulation.branch_created": handle_ws_digital_twin_event,
    "intent.validated": handle_ws_intent_event,
    "intent.execution_started": handle_ws_intent_event,
    "intent.execution_completed": handle_ws_intent_event,
    "intent.execution_failed": handle_ws_intent_event,
}
