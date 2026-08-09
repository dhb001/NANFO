"""Telemetry ingestion scaffold service.

VS2 Step 5 scope:
- Collector lifecycle contract
- Payload normalization
- Internal event publish path only (no persistence)
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.telemetry.repository import TelemetryRecordRepository

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


class TelemetryPersistenceService:
    """Persist normalized telemetry events into telemetry_records."""

    def __init__(self, db: AsyncSession):
        self._repo = TelemetryRecordRepository(db)

    async def persist_event(self, event: dict[str, Any]) -> bool:
        event_id = self._parse_uuid(event.get("event_id"), field_name="event_id")
        existing = await self._repo.get_by_event_id(event_id)
        if existing is not None:
            return False

        correlation_id = self._parse_uuid(event.get("correlation_id"), field_name="correlation_id")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("payload must be an object")

        device_id = self._parse_uuid(payload.get("device_id"), field_name="payload.device_id")
        network_id = self._parse_uuid(payload.get("network_id"), field_name="payload.network_id")
        workspace_id = self._parse_uuid(payload.get("workspace_id"), field_name="payload.workspace_id")

        metric = self._parse_metric(payload.get("metric"))
        value = self._parse_value(payload.get("value"))
        unit = self._parse_optional_text(payload.get("unit"))
        observed_at = self._parse_datetime(payload.get("observed_at"), field_name="payload.observed_at")
        source = self._parse_source(payload.get("source"))

        tags_raw = payload.get("tags")
        tags = tags_raw if isinstance(tags_raw, dict) else {}

        await self._repo.create(
            event_id=event_id,
            correlation_id=correlation_id,
            device_id=device_id,
            network_id=network_id,
            workspace_id=workspace_id,
            metric=metric,
            value=value,
            unit=unit,
            observed_at=observed_at,
            source=source,
            tags=tags,
        )
        return True

    @staticmethod
    def _parse_uuid(value: Any, *, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError(f"invalid uuid for {field_name}") from exc

    @staticmethod
    def _parse_metric(value: Any) -> str:
        metric = str(value or "").strip()
        if not metric:
            raise ValueError("payload.metric is required")
        return metric

    @staticmethod
    def _parse_source(value: Any) -> str:
        source = str(value or "collector").strip()
        if not source:
            raise ValueError("payload.source is required")
        return source

    @staticmethod
    def _parse_value(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload.value must be numeric") from exc

    @staticmethod
    def _parse_optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _parse_datetime(value: Any, *, field_name: str) -> datetime:
        if value is None:
            raise ValueError(f"{field_name} is required")

        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError(f"invalid datetime for {field_name}") from exc

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
