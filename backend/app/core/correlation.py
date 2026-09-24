"""Shared request-correlation normalization (ADR-028).

Every module that persists a correlation identifier into UUID-backed storage
must use :func:`normalize_audit_correlation` so the same opaque ``X-Request-ID``
maps to the same stored UUID everywhere and the original client identifier is
always recoverable from metadata.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

_NAMESPACE_PREFIX = "nanfo:audit-correlation:"


def normalize_audit_correlation(
    correlation_id: str | uuid.UUID | None,
    metadata: Mapping[str, Any] | None,
) -> tuple[uuid.UUID, dict]:
    """Return a stable UUID for ``correlation_id`` plus metadata preserving the original.

    * Canonical UUID strings (and ``uuid.UUID`` values) are returned unchanged.
    * Parseable but non-canonical UUID spellings (braces, ``urn:uuid:``, no
      hyphens, upper case) keep their UUID value, and the original spelling is
      recorded as ``metadata["request_id"]`` so it remains searchable.
    * Opaque identifiers map deterministically via UUIDv5 (the historical
      identity-module mapping, unchanged) and are recorded in metadata.
    * Missing identifiers get a random UUID and no ``request_id`` entry.

    The caller's metadata mapping is never mutated.
    """
    base = dict(metadata or {})
    if isinstance(correlation_id, uuid.UUID):
        return correlation_id, base
    if correlation_id is None:
        return uuid.uuid4(), base
    original = str(correlation_id)
    if not original.strip():
        return uuid.uuid4(), base
    try:
        parsed = uuid.UUID(original)
    except (ValueError, AttributeError, TypeError):
        return (
            uuid.uuid5(uuid.NAMESPACE_URL, f"{_NAMESPACE_PREFIX}{original}"),
            {**base, "request_id": original},
        )
    if str(parsed) != original:
        return parsed, {**base, "request_id": original}
    return parsed, base


def correlation_uuid(correlation_id: str | uuid.UUID | None) -> uuid.UUID:
    """Convenience wrapper returning only the normalized UUID."""
    return normalize_audit_correlation(correlation_id, None)[0]
