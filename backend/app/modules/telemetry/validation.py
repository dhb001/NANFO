"""Canonical telemetry field validation shared by ingestion, persistence and replay.

Every parser raises ``ValueError`` with a fixed, input-free message. Timestamps
must carry an explicit UTC offset (naive values are rejected rather than
silently assumed to be UTC) and may not lie further in the future than
``MAX_FUTURE_SKEW`` relative to the validating host clock.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_FUTURE_SKEW = timedelta(minutes=5)


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_uuid(value: Any, *, field_name: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"invalid uuid for {field_name}") from exc


def parse_metric(value: Any) -> str:
    metric = str(value or "").strip()
    if not metric:
        raise ValueError("payload.metric is required")
    return metric


def parse_source(value: Any) -> str:
    source = str(value or "collector").strip()
    if not source:
        raise ValueError("payload.source is required")
    return source


def parse_value(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("payload.value must be a finite measurement")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload.value must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError("payload.value must be a finite measurement")
    return parsed


def parse_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_observed_at(
    value: Any,
    *,
    field_name: str,
    now: Callable[[], datetime] = utc_now,
    max_future_skew: timedelta = MAX_FUTURE_SKEW,
) -> datetime:
    """Return an aware UTC datetime; reject missing, naive and far-future values."""
    if value is None or value == "":
        raise ValueError(f"{field_name} is required")
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"invalid datetime for {field_name}") from exc
    else:
        raise ValueError(f"invalid datetime for {field_name}")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} requires an explicit UTC offset")
    parsed = parsed.astimezone(UTC)
    if parsed > now() + max_future_skew:
        raise ValueError(f"{field_name} is too far in the future")
    return parsed
