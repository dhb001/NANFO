"""Unit tests for report lifecycle event consumer wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.events.consumers.report_consumer import (
    REPORT_HANDLERS,
    handle_report_lifecycle_event,
)


def _session_context_manager(db: AsyncMock) -> AsyncMock:
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = db
    session_cm.__aexit__.return_value = None
    return session_cm


@pytest.mark.asyncio
async def test_report_consumer_routes_event_to_report_service_processor():
    event = {
        "event_type": "report.requested",
        "correlation_id": "00000000-0000-0000-0000-000000000001",
        "payload": {"report_id": "00000000-0000-0000-0000-000000000010"},
    }
    db = AsyncMock()

    with (
        patch(
            "app.events.consumers.report_consumer.AsyncSessionLocal",
            return_value=_session_context_manager(db),
        ),
        patch("app.events.consumers.report_consumer.ReportService") as mock_service,
    ):
        service_instance = AsyncMock()
        service_instance.process_requested_event = AsyncMock()
        mock_service.return_value = service_instance

        await handle_report_lifecycle_event(event)

    mock_service.assert_called_once_with(db=db, redis=None)
    service_instance.process_requested_event.assert_awaited_once_with(event)


def test_report_handlers_include_requested_event():
    assert "report.requested" in REPORT_HANDLERS
    assert REPORT_HANDLERS["report.requested"] is handle_report_lifecycle_event
