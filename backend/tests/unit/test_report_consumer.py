"""Unit tests for report lifecycle event consumer wiring."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.core.errors import DeterministicEventError
from app.events.bus import ACKED, process_entry
from app.events.consumers import report_consumer
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


# ── ADR-028 C14 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("payload", [None, [], {}, {"report_id": None}, {"report_id": "not-a-uuid"},
                                     {"report_id": 7}])
async def test_malformed_report_notification_is_poison(payload):
    db = AsyncMock()
    event = {"event_type": "report.requested", "event_id": str(uuid.uuid4()), "payload": payload}
    with patch.object(report_consumer, "AsyncSessionLocal", return_value=_session_context_manager(db)):
        with pytest.raises(DeterministicEventError):
            await handle_report_lifecycle_event(event)
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_well_formed_notification_is_a_no_op_and_transient_errors_propagate():
    db = AsyncMock()
    event = {"event_type": "report.requested", "event_id": str(uuid.uuid4()),
             "payload": {"report_id": str(uuid.uuid4()), "workspace_id": str(uuid.uuid4())}}
    with patch.object(report_consumer, "AsyncSessionLocal", return_value=_session_context_manager(db)):
        assert await handle_report_lifecycle_event(event) is None
    db.execute.assert_not_awaited()
    outage = OperationalError("SELECT 1", {}, ConnectionError("database down"))
    failing = AsyncMock()
    failing.__aenter__.side_effect = outage
    with patch.object(report_consumer, "AsyncSessionLocal", return_value=failing):
        with pytest.raises(OperationalError):
            await handle_report_lifecycle_event(event)


async def test_poison_report_notification_is_dead_lettered_on_first_delivery(fake_redis):
    fields = {"event_id": str(uuid.uuid4()), "event_type": "report.requested", "version": "1",
              "payload": json.dumps({"report_id": "nope"})}
    with patch.object(report_consumer, "AsyncSessionLocal", return_value=_session_context_manager(AsyncMock())):
        assert await process_entry(fake_redis, "stream:report", "nanfo-consumers", "1-0", fields, REPORT_HANDLERS,
                                   dead_letter_key="dlq", retry_backoff_seconds=0) == ACKED
    (_, entry), = await fake_redis.xrange("dlq")
    assert entry["error_type"] == "DeterministicEventError" and entry["delivery_count"] == "1"
