"""NANFO Backend - Alert lifecycle event consumer.

Consumes alert lifecycle events and persists alert entity state.

Failure policy (ADR-028 C14): a poison event -- one whose own content can never
be ingested (non-object payload, invalid or conflicting recorded scope, a
generation without an event id, or a 4xx owner answer about identifiers the
event carries) -- raises :class:`DeterministicEventError`, so the bus
dead-letters it on the first delivery instead of redelivering it up to
``EVENT_MAX_DELIVERIES`` times. Transient failures (PostgreSQL/Redis outages,
timeouts, lock or uniqueness races, 5xx owner answers) propagate unchanged and
stay pending for reclaim. Well-formed events that do not apply (telemetry that
is not a measured observation, the echo of Alert's own measured incidents,
lifecycle updates for another scope) are acknowledged and ignored.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.core.errors import DeterministicEventError
from app.db.postgres import AsyncSessionLocal
from app.modules.alert.measured import MeasuredAlertService
from app.modules.alert.service import AlertEventRejected, AlertService

# Owner answers that a later redelivery may overcome (timeout, throttling, 5xx).
_TRANSIENT_STATUS = frozenset({408, 425, 429})


def classify_owner_rejection(exc: HTTPException) -> BaseException:
    """Map an owner ``HTTPException`` raised while ingesting an event.

    4xx answers concern identifiers carried by the event itself (unknown device,
    foreign scope) and are deterministic; everything else is returned unchanged
    so it stays pending.
    """
    if 400 <= exc.status_code < 500 and exc.status_code not in _TRANSIENT_STATUS:
        return DeterministicEventError(f"owner_rejected_{exc.status_code}")
    return exc


async def handle_persisted_metric_event(event: dict) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await MeasuredAlertService(db=db).ingest_persisted_event(event)
    except HTTPException as exc:
        classified = classify_owner_rejection(exc)
        if classified is exc:
            raise
        raise classified from None


async def handle_alert_lifecycle_event(event: dict) -> None:
    """Persist alert state transitions from alert lifecycle events."""
    try:
        async with AsyncSessionLocal() as db:
            service = AlertService(db=db, redis=None)
            await service.ingest_alert_event(event)
    except AlertEventRejected as exc:
        raise DeterministicEventError(exc.reason) from None
    except HTTPException as exc:
        classified = classify_owner_rejection(exc)
        if classified is exc:
            raise
        raise classified from None


ALERT_HANDLERS: dict[str, object] = {
    "alert.generated": handle_alert_lifecycle_event,
    "alert.acknowledged": handle_alert_lifecycle_event,
    "alert.resolved": handle_alert_lifecycle_event,
}
