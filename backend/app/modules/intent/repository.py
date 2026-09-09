"""NANFO Backend - Intent module repository.

Persistence operations for intent lifecycle records.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.intent.models import Intent, IntentExecution, IntentOutbox

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

    async def lock_intent(self, intent_id: uuid.UUID, workspace_id: uuid.UUID) -> Intent | None:
        return (await self._db.execute(select(Intent).where(
            Intent.intent_id == intent_id, Intent.workspace_id == workspace_id,
        ).with_for_update())).scalar_one_or_none()

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


class ExecutionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def existing(self, workspace_id, intent_id, request_key):
        return list((await self.db.execute(select(IntentExecution).where(
            IntentExecution.workspace_id == workspace_id,
            or_(IntentExecution.intent_id == intent_id, IntentExecution.request_key == request_key),
        ))).scalars())

    async def claim(self, owner: str, lease_seconds: int):
        row = (await self.db.execute(select(IntentExecution).where(
            IntentExecution.blocks_lab.is_(True),
            or_(IntentExecution.lease_until.is_(None), IntentExecution.lease_until < func.now()),
        ).order_by(IntentExecution.created_at).with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
        if row is not None:
            row.lease_owner = owner
            row.fence += 1
            row.lease_until = func.now() + timedelta(seconds=lease_seconds)
        await self.db.commit()
        if row is not None:
            await self.db.refresh(row)
            await self.db.commit()
        return row

    async def owned(self, execution_id, owner, fence):
        return (await self.db.execute(select(IntentExecution).where(
            IntentExecution.execution_id == execution_id, IntentExecution.lease_owner == owner,
            IntentExecution.fence == fence, IntentExecution.lease_until > func.now(),
        ).with_for_update())).scalar_one_or_none()

    async def renew(self, execution_id, owner, fence, seconds):
        result = await self.db.execute(update(IntentExecution).where(
            IntentExecution.execution_id == execution_id, IntentExecution.lease_owner == owner,
            IntentExecution.fence == fence, IntentExecution.lease_until > func.now(),
        ).values(lease_until=func.now() + timedelta(seconds=seconds)))
        await self.db.commit()
        return result.rowcount == 1

    async def request_cancel(self, execution_id, actor_id):
        result = await self.db.execute(update(IntentExecution).where(
            IntentExecution.execution_id == execution_id,
            IntentExecution.cancel_requested.is_(False),
            or_(IntentExecution.blocks_lab.is_(True), IntentExecution.phase == "completed"),
        ).values(cancel_requested=True, blocks_lab=True, cancelled_by_user_id=actor_id,
                 cancellation_requested_at=func.now()))
        return result.rowcount == 1

    async def claim_event(self, owner, seconds):
        earlier = aliased(IntentOutbox)
        row = (await self.db.execute(select(IntentOutbox).where(
            IntentOutbox.published_at.is_(None),
            or_(IntentOutbox.lease_until.is_(None), IntentOutbox.lease_until < func.now()),
            ~select(earlier.event_id).where(
                earlier.execution_id == IntentOutbox.execution_id,
                earlier.sequence < IntentOutbox.sequence, earlier.published_at.is_(None),
            ).exists(),
        ).order_by(IntentOutbox.created_at).with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
        if row is not None:
            row.lease_owner = owner
            row.lease_until = func.now() + timedelta(seconds=seconds)
        await self.db.commit()
        return row

    async def acknowledge_event(self, event_id, owner):
        await self.db.execute(update(IntentOutbox).where(
            IntentOutbox.event_id == event_id, IntentOutbox.lease_owner == owner,
            IntentOutbox.lease_until > func.now(),
        ).values(published_at=func.now(), lease_owner=None, lease_until=None))
        await self.db.commit()
