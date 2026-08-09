"""Telemetry ingestion scaffold service.

VS2 Step 5 scope:
- Collector lifecycle contract
- Payload normalization
- Internal event publish path only (no persistence)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from app.core.logging import get_logger
from app.events.publisher import publish_event

logger = get_logger(__name__)


class TelemetryCollector(ABC):
    """Lifecycle interface for telemetry collectors."""

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass


class TelemetryIngestionService:
    """Normalize and publish telemetry ingestion events to internal bus."""

    def __init__(self, redis: aioredis.Redis):
        self._redis = redis

    def normalize_payload(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize vendor-specific telemetry into canonical internal shape."""
        observed_at = raw.get("observed_at")
        if not observed_at:
            observed_at = datetime.now(UTC).isoformat()

        value_raw = raw.get("value", 0)
        try:
            value = float(value_raw)
        except (TypeError, ValueError):
            value = 0.0

        tags_raw = raw.get("tags")
        tags = tags_raw if isinstance(tags_raw, dict) else {}

        return {
            "device_id": str(raw.get("device_id", "")),
            "network_id": str(raw.get("network_id", "")),
            "workspace_id": str(raw.get("workspace_id", "")),
            "metric": str(raw.get("metric", "")),
            "value": value,
            "unit": str(raw.get("unit", "")),
            "observed_at": observed_at,
            "source": str(raw.get("source", "collector")),
            "tags": tags,
        }

    async def ingest(self, raw: dict[str, Any], correlation_id: str) -> str:
        payload = self.normalize_payload(raw)
        entry_id = await publish_event(
            redis=self._redis,
            event_type="telemetry.metric.ingested",
            source="telemetry",
            payload=payload,
            correlation_id=correlation_id,
        )
        logger.info(
            "telemetry_event_published",
            correlation_id=correlation_id,
            event_type="telemetry.metric.ingested",
            metric=payload["metric"],
            device_id=payload["device_id"],
            stream_entry_id=entry_id,
        )
        return entry_id


class TelemetryCollectorRunner(TelemetryCollector):
    """Minimal no-op collector runner for VS2 bootstrap wiring.

    This runner does not pull real SNMP/gRPC data yet. It only exposes
    lifecycle hooks and a callable ingestion path for tests and future wiring.
    """

    def __init__(self, ingestion_service: TelemetryIngestionService):
        self._ingestion_service = ingestion_service
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self._running = True
        logger.info("telemetry_collector_started")

    async def stop(self) -> None:
        self._running = False
        logger.info("telemetry_collector_stopped")

    async def ingest_once(self, raw: dict[str, Any], correlation_id: str) -> str:
        return await self._ingestion_service.ingest(raw=raw, correlation_id=correlation_id)
