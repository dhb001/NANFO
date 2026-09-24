"""Envelope version gate and dereferenced-field registry (EventAPI.md §2, §6; ADR-028).

Only fields that the registered consumers *dereference* for event types documented in
``docs/api/EventAPI.md`` are required here, so a malformed event is dead-lettered once
with a precise reason instead of failing every handler on every redelivery. Fields
consumers read with defaults are deliberately not required: historical events that
lack them must keep flowing (EventAPI.md §6, "never repaired by weakening filters").
"""

from __future__ import annotations

import re

from app.core.errors import DeterministicEventError

SUPPORTED_MAJOR_VERSION = 1
_VERSION = re.compile(r"(?P<major>[0-9]{1,6})(?:\.[0-9]{1,6}){0,2}")

# event_type -> {payload field: required JSON type}
REQUIRED_PAYLOAD_FIELDS: dict[str, dict[str, type]] = {
    # Topology projection and websocket deltas dereference payload["device_id"];
    # updates dereference payload["changed_fields"] (EventAPI.md §6).
    "network.device.added": {"device_id": str},
    "network.device.updated": {"device_id": str, "changed_fields": dict},
    "network.device.deleted": {"device_id": str},
}
# event_type -> envelope fields dereferenced by consumers
REQUIRED_ENVELOPE_FIELDS: dict[str, tuple[str, ...]] = {
    "network.device.added": ("timestamp",),
    "network.device.updated": ("timestamp",),
    "network.device.deleted": ("timestamp",),
}


class EnvelopeRejected(DeterministicEventError):
    """Deterministic contract violation; ``reason`` is a stable machine-readable code."""

    def __init__(self, reason: str, fields: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.fields = fields


def major_version(value: object) -> int | None:
    if value is None:
        return SUPPORTED_MAJOR_VERSION  # Pre-versioning producers were v1 by definition.
    if not isinstance(value, str):
        return None
    match = _VERSION.fullmatch(value.strip())
    return int(match.group("major")) if match else None


def validate_envelope(event_type: str, fields: dict, payload: dict) -> None:
    """Raise :class:`EnvelopeRejected` for an unknown major version or missing fields."""
    if major_version(fields.get("version")) != SUPPORTED_MAJOR_VERSION:
        raise EnvelopeRejected("unsupported_version")
    missing = [
        name for name, kind in REQUIRED_PAYLOAD_FIELDS.get(event_type, {}).items()
        if not isinstance(payload.get(name), kind) or (kind is str and not payload[name].strip())
    ]
    missing += [
        name for name in REQUIRED_ENVELOPE_FIELDS.get(event_type, ())
        if not isinstance(fields.get(name), str) or not fields[name].strip()
    ]
    if missing:
        raise EnvelopeRejected("invalid_payload", tuple(sorted(missing)))
