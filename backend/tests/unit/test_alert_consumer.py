"""Unit tests for alert lifecycle event consumer wiring."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app.core.errors import DeterministicEventError
from app.events.bus import ACKED, PENDING, process_entry
from app.events.consumers import alert_consumer
from app.events.consumers.alert_consumer import (
    ALERT_HANDLERS,
    handle_alert_lifecycle_event,
    handle_persisted_metric_event,
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


# ── ADR-028 C14: poison events dead-letter at once; transient errors stay pending ──

_WS_A, _WS_B = str(uuid.UUID(int=71)), str(uuid.UUID(int=72))


def _lifecycle(event_type="alert.generated", payload=None, **overrides):
    event = {"event_id": str(uuid.uuid4()), "event_type": event_type, "source": "telemetry",
             "correlation_id": str(uuid.uuid4()), "timestamp": "2026-09-24T00:00:00+00:00",
             "payload": {"alert_key": "k"} if payload is None else payload}
    return {**event, **overrides}


@pytest.mark.parametrize("event", [
    _lifecycle(payload=["not", "an", "object"]),
    _lifecycle(payload={"alert_key": "k", "workspace_id": "not-a-uuid"}),
    _lifecycle(payload={"alert_key": "k", "workspace_id": _WS_A, "scope": {"workspace_id": _WS_B}}),
    _lifecycle(payload={"alert_key": "k", "scope": "not-a-dict"}),
    _lifecycle("alert.resolved", payload={"alert_key": "k", "port_no": -1}),
    _lifecycle(event_id=None),
], ids=["payload-list", "invalid-scope", "conflicting-scope", "scope-not-object", "invalid-port", "no-event-id"])
async def test_poison_lifecycle_events_raise_deterministic_event_error(event):
    db = AsyncMock()
    with patch.object(alert_consumer, "AsyncSessionLocal", return_value=_session_context_manager(db)):
        with pytest.raises(DeterministicEventError):
            await handle_alert_lifecycle_event(event)
    db.commit.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("failure", [
    OperationalError("SELECT 1", {}, ConnectionError("database down")),
    HTTPException(status_code=503, detail="unavailable"),
    HTTPException(status_code=429, detail="throttled"),
    TimeoutError(),
], ids=["postgres-outage", "owner-503", "owner-429", "timeout"])
async def test_transient_lifecycle_failures_propagate_unchanged(failure):
    service = AsyncMock()
    service.ingest_alert_event.side_effect = failure
    with (patch.object(alert_consumer, "AsyncSessionLocal", return_value=_session_context_manager(AsyncMock())),
          patch.object(alert_consumer, "AlertService", return_value=service)):
        with pytest.raises(type(failure)) as raised:
            await handle_alert_lifecycle_event(_lifecycle())
    assert raised.value is failure


@pytest.mark.parametrize("status_code,deterministic", [(400, True), (403, True), (404, True), (422, True),
                                                        (408, False), (429, False), (500, False), (503, False)])
async def test_measured_owner_rejections_are_classified(status_code, deterministic):
    service = AsyncMock()
    service.ingest_persisted_event.side_effect = HTTPException(status_code=status_code, detail="x")
    with (patch.object(alert_consumer, "AsyncSessionLocal", return_value=_session_context_manager(AsyncMock())),
          patch.object(alert_consumer, "MeasuredAlertService", return_value=service)):
        with pytest.raises(DeterministicEventError if deterministic else HTTPException):
            await handle_persisted_metric_event({"event_type": "telemetry.metric.ingested"})


async def test_not_applicable_measured_telemetry_is_acknowledged_quietly():
    db = AsyncMock()
    with patch.object(alert_consumer, "AsyncSessionLocal", return_value=_session_context_manager(db)):
        # Not a measured observation (synthetic/unknown metric): ignored, never poison.
        await handle_persisted_metric_event({"event_type": "telemetry.metric.ingested", "event_id": str(uuid.uuid4()),
                                             "correlation_id": str(uuid.uuid4()), "payload": {"metric": "cpu"}})
    db.commit.assert_not_awaited()


def _stream_fields(event):
    return {**{key: value for key, value in event.items() if key != "payload"},
            "payload": json.dumps(event["payload"]), "version": "1"}


async def test_poison_alert_event_is_dead_lettered_on_the_first_delivery(fake_redis):
    poison = _lifecycle(payload={"alert_key": "k", "workspace_id": _WS_A, "scope": {"workspace_id": _WS_B}})
    with patch.object(alert_consumer, "AsyncSessionLocal", return_value=_session_context_manager(AsyncMock())):
        outcome = await process_entry(fake_redis, "stream:alert", "nanfo-consumers", "1-0", _stream_fields(poison),
                                      ALERT_HANDLERS, dead_letter_key="dlq", delivery_count=1, max_retries=3,
                                      retry_backoff_seconds=0)
    assert outcome == ACKED
    (_, entry), = await fake_redis.xrange("dlq")
    assert entry["failure_reason"] == "handler_failed_deterministic"
    assert entry["error_type"] == "DeterministicEventError" and entry["delivery_count"] == "1"
    assert entry["event_id"] == poison["event_id"]


async def test_transient_alert_failure_stays_pending_and_is_never_dead_lettered(fake_redis):
    service = AsyncMock()
    service.ingest_alert_event.side_effect = OperationalError("SELECT 1", {}, ConnectionError("database down"))
    with (patch.object(alert_consumer, "AsyncSessionLocal", return_value=_session_context_manager(AsyncMock())),
          patch.object(alert_consumer, "AlertService", return_value=service)):
        outcome = await process_entry(fake_redis, "stream:alert", "nanfo-consumers", "1-0",
                                      _stream_fields(_lifecycle()), ALERT_HANDLERS, dead_letter_key="dlq",
                                      max_retries=1, retry_backoff_seconds=0)
    assert outcome != ACKED and outcome in {PENDING, "outage"}
    assert await fake_redis.xrange("dlq") == []
