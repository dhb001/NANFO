"""Telemetry-owned canonical replay after an idempotent persistence no-op."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TelemetryReplay:
    status: Literal["active_exact", "active_conflict", "tombstone"]
    event: dict | None = None


async def replay_event(service, event: dict) -> TelemetryReplay:
    """Caller holds its session through downstream recovery, serializing archival.

    Envelope timestamp/source are not stored; replay uses observed_at and the
    Telemetry source. Exactness compares every persisted field, including identity,
    scopes, provenance/tags and correlation, never just event_id.
    """
    event_id = service._parse_uuid(event.get("event_id"), field_name="event_id")
    await service._dedup.lock(event_id)
    if await service._dedup.archived(event_id):
        return TelemetryReplay("tombstone")
    record = await service._repo.get_by_event_id(event_id)
    if record is None:
        raise RuntimeError("Persisted telemetry replay record missing")
    canonical_payload = {
        "device_id": str(record.device_id), "network_id": str(record.network_id),
        "workspace_id": str(record.workspace_id), "metric": record.metric,
        "value": record.value, "unit": record.unit, "observed_at": record.observed_at.isoformat(),
        "source": record.source, "tags": deepcopy(record.tags),
    }
    try:
        payload = event["payload"]
        candidate = {
            name: str(service._parse_uuid(payload.get(name), field_name=name))
            for name in ("device_id", "network_id", "workspace_id")
        }
        candidate.update(
            metric=service._parse_metric(payload.get("metric")),
            value=service._parse_value(payload.get("value")),
            unit=service._parse_optional_text(payload.get("unit")),
            observed_at=service._parse_datetime(payload.get("observed_at"), field_name="observed_at").astimezone(
                record.observed_at.tzinfo).isoformat(),
            source=service._parse_source(payload.get("source")),
            tags=payload.get("tags") if isinstance(payload.get("tags"), dict) else {},
        )
        exact = (candidate == canonical_payload
                 and service._parse_uuid(event.get("correlation_id"), field_name="correlation_id") == record.correlation_id
                 and event.get("event_type") == "telemetry.metric.ingested")
    except (ValueError, TypeError, KeyError, AttributeError):
        exact = False
    if not exact:
        return TelemetryReplay("active_conflict")
    return TelemetryReplay("active_exact", {
        "event_id": str(record.event_id), "event_type": "telemetry.metric.ingested", "source": "telemetry",
        "correlation_id": str(record.correlation_id), "timestamp": record.observed_at.isoformat(),
        "payload": canonical_payload,
    })
