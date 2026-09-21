"""Unit tests for alert lifecycle event consumer wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.events.consumers.alert_consumer import (
    ALERT_HANDLERS,
    handle_alert_lifecycle_event,
)


def _session_context_manager(db: AsyncMock) -> AsyncMock:
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None
    return session_cm


@pytest.mark.asyncio
async def test_alert_consumer_routes_event_to_alert_service_ingestion():
    event = {
        "event_type": "alert.generated",
        "correlation_id": "00000000-0000-0000-0000-000000000001",
        "payload": {"alert_key": "telemetry_runtime_adapter_slo_threshold_breach"},
    }
    db = AsyncMock()

    with (
        patch(
            "app.events.consumers.alert_consumer.AsyncSessionLocal",
            return_value=_session_context_manager(db),
        ),
        patch("app.events.consumers.alert_consumer.AlertService") as mock_service,
    ):
        service_instance = AsyncMock()
        service_instance.ingest_alert_event = AsyncMock()
        mock_service.return_value = service_instance

        await handle_alert_lifecycle_event(event)

    mock_service.assert_called_once_with(db=db, redis=None)
    service_instance.ingest_alert_event.assert_awaited_once_with(event)


def test_alert_handlers_include_generated_acknowledged_and_resolved_events():
    assert "alert.generated" in ALERT_HANDLERS
    assert "alert.acknowledged" in ALERT_HANDLERS
    assert "alert.resolved" in ALERT_HANDLERS
    assert ALERT_HANDLERS["alert.generated"] is handle_alert_lifecycle_event
    assert ALERT_HANDLERS["alert.acknowledged"] is handle_alert_lifecycle_event
    assert ALERT_HANDLERS["alert.resolved"] is handle_alert_lifecycle_event
