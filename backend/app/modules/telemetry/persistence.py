"""Persist normalized telemetry events into the Telemetry-owned ``telemetry_records``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.telemetry import validation
from app.modules.telemetry.dedup import TelemetryDedupRepository
from app.modules.telemetry.repository import TelemetryRecordRepository


class TelemetryPersistenceService:
    """Persist normalized telemetry events into telemetry_records."""

    def __init__(self, db: AsyncSession):
        self._repo = TelemetryRecordRepository(db)
        self._dedup = TelemetryDedupRepository(db)

    async def replay_event(self, event: dict[str, Any]):
        """Public owning replay contract: exact active record, conflict or tombstone."""
        from app.modules.telemetry.replay import replay_event

        return await replay_event(self, event)

    async def persist_event(self, event: dict[str, Any]) -> bool:
        event_id = self._parse_uuid(event.get("event_id"), field_name="event_id")
        await self._dedup.lock(event_id)
        if await self._dedup.archived(event_id):
            return False
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

    # Stable delegates: replay and existing callers use these names.
    @staticmethod
    def _parse_uuid(value: Any, *, field_name: str) -> uuid.UUID:
        return validation.parse_uuid(value, field_name=field_name)

    @staticmethod
    def _parse_metric(value: Any) -> str:
        return validation.parse_metric(value)

    @staticmethod
    def _parse_source(value: Any) -> str:
        return validation.parse_source(value)

    @staticmethod
    def _parse_value(value: Any) -> float:
        return validation.parse_value(value)

    @staticmethod
    def _parse_optional_text(value: Any) -> str | None:
        return validation.parse_optional_text(value)

    @staticmethod
    def _parse_datetime(value: Any, *, field_name: str) -> datetime:
        return validation.parse_observed_at(value, field_name=field_name)
