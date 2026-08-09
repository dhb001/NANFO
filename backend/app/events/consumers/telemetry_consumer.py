"""Telemetry event consumer stub.

VS2 Step 5 scope: parse normalized telemetry events without persistence side effects.
"""

from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)


async def handle_telemetry_event(event: dict) -> None:
    """Parse telemetry events and emit structured logs only (no writes)."""
    payload = event.get("payload", {})
    logger.info(
        "telemetry_event_received",
        event_type=event.get("event_type", ""),
        correlation_id=event.get("correlation_id", ""),
        device_id=payload.get("device_id", ""),
        network_id=payload.get("network_id", ""),
        metric=payload.get("metric", ""),
        value=payload.get("value"),
        observed_at=payload.get("observed_at", ""),
    )


TELEMETRY_HANDLERS: dict[str, object] = {
    "telemetry.metric.ingested": handle_telemetry_event,
}
