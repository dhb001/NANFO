"""NANFO Backend - Intent module repository.

Persistence operations for intent lifecycle records.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.intent.models import Intent

_UNSET: Any = object()


class IntentRepository:
    """Repository for intent lifecycle persistence."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(
        self,
        *,
        intent_id: uuid.UUID,
        workspace_id: uuid.UUID,
        network_id: uuid.UUID | None,
        intent_kind: str,
        intent_payload: dict,
        status: str,
        validation_result: dict,
        execution_provenance: dict,
        explainability: dict,
        confidence_score: float | None,
        confidence_band: str | None,
        approval_required: bool,
        idempotency_key: str | None,
        correlation_id: uuid.UUID,
        queue_status: str,
        stream_entry_id: str | None,
        warning: str | None,
        requested_by_user_id: str,
        requested_at: datetime,
    ) -> Intent:
        intent = Intent(
            intent_id=intent_id,
            workspace_id=workspace_id,
            network_id=network_id,
            intent_kind=intent_kind,
            intent_payload=intent_payload,
            status=status,
            validation_result=validation_result,
            execution_provenance=execution_provenance,
            explainability=explainability,
            confidence_score=confidence_score,
            confidence_band=confidence_band,
            approval_required=approval_required,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
            requested_by_user_id=requested_by_user_id,
            requested_at=requested_at,
        )
        self._db.add(intent)
        await self._db.flush()
        return intent

    async def get_by_id(self, intent_id: uuid.UUID) -> Intent | None:
        result = await self._db.execute(select(Intent).where(Intent.intent_id == intent_id))
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self,
        *,
        workspace_id: uuid.UUID,
        idempotency_key: str,
    ) -> Intent | None:
        result = await self._db.execute(
            select(Intent).where(
                Intent.workspace_id == workspace_id,
                Intent.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        intent: Intent,
        *,
        status: str,
        validation_result: dict | None = None,
        execution_provenance: dict | None = None,
        explainability: dict | None = None,
        confidence_score: float | None = None,
        confidence_band: str | None = None,
        approval_required: bool | None = None,
        idempotency_key: str | None | Any = _UNSET,
        queue_status: str | None = None,
        stream_entry_id: str | None | Any = _UNSET,
        warning: str | None | Any = _UNSET,
    ) -> Intent:
        intent.status = status
        if validation_result is not None:
            intent.validation_result = validation_result
        if execution_provenance is not None:
            intent.execution_provenance = execution_provenance
        if explainability is not None:
            intent.explainability = explainability
        if confidence_band is not None:
            intent.confidence_band = confidence_band
        if confidence_score is not None:
            intent.confidence_score = confidence_score
        if approval_required is not None:
            intent.approval_required = approval_required
        if idempotency_key is not _UNSET:
            intent.idempotency_key = idempotency_key
        if queue_status is not None:
            intent.queue_status = queue_status
        if stream_entry_id is not _UNSET:
            intent.stream_entry_id = stream_entry_id
        if warning is not _UNSET:
            intent.warning = warning
        await self._db.flush()
        return intent
