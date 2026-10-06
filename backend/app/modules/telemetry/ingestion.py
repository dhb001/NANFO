"""Normalize raw collector samples and publish them onto the internal event bus."""

from __future__ import annotations

import uuid
from typing import Any

import redis.asyncio as aioredis

from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.telemetry.counters import TelemetryHealthCounterService
from app.modules.telemetry.validation import parse_observed_at, parse_value, utc_now

logger = get_logger(__name__)

TELEMETRY_INGESTED_EVENT_TYPE = "telemetry.metric.ingested"


class TelemetryIngestionService:
    """Normalize and publish telemetry ingestion events to internal bus."""

    def __init__(
        self,
        redis: aioredis.Redis,
        counter_service: TelemetryHealthCounterService | None = None,
    ):
        self._redis = redis
        self._counter_service = counter_service or TelemetryHealthCounterService(redis)

    @property
    def counter_service(self) -> TelemetryHealthCounterService:
        return self._counter_service

    @property
    def redis(self) -> aioredis.Redis:
        return self._redis

    def normalize_payload(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize vendor-specific telemetry into canonical internal shape.

        A missing ``observed_at`` is stamped with the ingestion time. A supplied
        value must be timezone-aware and not beyond the permitted future skew; it
        is re-encoded as a canonical UTC ISO-8601 string.
        """
        observed_raw = raw.get("observed_at")
        if observed_raw is None or observed_raw == "":
            observed_at = utc_now()
        else:
            observed_at = parse_observed_at(observed_raw, field_name="observed_at")

        value = parse_value(raw.get("value"))

        tags_raw = raw.get("tags")
        tags = tags_raw if isinstance(tags_raw, dict) else {}

        return {
            "device_id": str(raw.get("device_id", "")),
            "network_id": str(raw.get("network_id", "")),
            "workspace_id": str(raw.get("workspace_id", "")),
            "metric": str(raw.get("metric", "")),
            "value": value,
            "unit": str(raw.get("unit", "")),
            "observed_at": observed_at.isoformat(),
            "source": str(raw.get("source", "collector")),
            "tags": tags,
        }

    async def ingest(self, raw: dict[str, Any], correlation_id: str, *, event_id: str | None = None) -> str:
        payload = self.normalize_payload(raw)
        event_options = {"event_id": str(uuid.UUID(event_id))} if event_id is not None else {}
        entry_id = await publish_event(
            redis=self._redis,
            event_type=TELEMETRY_INGESTED_EVENT_TYPE,
            source="telemetry",
            payload=payload,
            correlation_id=correlation_id,
            **event_options,
        )
        await self._increment_ingested_counter(correlation_id=correlation_id)
        logger.info(
            "telemetry_event_published",
            correlation_id=correlation_id,
            event_type=TELEMETRY_INGESTED_EVENT_TYPE,
            metric=payload["metric"],
            device_id=payload["device_id"],
            stream_entry_id=entry_id,
        )
        return entry_id

    async def _increment_ingested_counter(self, correlation_id: str) -> None:
        try:
            await self._counter_service.increment_ingested()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry_ingested_counter_increment_failed",
                correlation_id=correlation_id,
                error_type=type(exc).__name__,
            )
