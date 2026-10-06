"""NANFO Backend - Intent module repository.

Persistence operations for intent lifecycle records. Repositories never commit or
roll back (ADR-028): services and the execution worker own each unit of work, so a
lease is durable before any lab/Redis I/O and no transaction spans that I/O.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.intent.models import Intent, IntentExecution, IntentOutbox

_UNSET: Any = object()
MAX_RETENTION_BATCH_ROWS = 10_000


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

    async def get_by_id(self, intent_id: uuid.UUID, *, lock: bool = False) -> Intent | None:
        query = select(Intent).where(Intent.intent_id == intent_id)
        if lock:
            # Serializes concurrent executes of one intent (ADR-028 C3).
            query = query.with_for_update().execution_options(populate_existing=True)
        result = await self._db.execute(query)
        return result.scalar_one_or_none()

    async def lock_intent(self, intent_id: uuid.UUID, workspace_id: uuid.UUID) -> Intent | None:
        return (await self._db.execute(select(Intent).where(
            Intent.intent_id == intent_id, Intent.workspace_id == workspace_id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()

    async def get_by_idempotency_key(
        self,
        *,
        workspace_id: uuid.UUID,
        idempotency_key: str,
    ) -> Intent | None:
        # Unique per workspace after migration 0030; the deterministic earliest-row
        # choice also keeps pre-migration duplicate keys from raising.
        result = await self._db.execute(
            select(Intent).where(
                Intent.workspace_id == workspace_id,
                Intent.idempotency_key == idempotency_key,
            ).order_by(Intent.requested_at, Intent.intent_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def claim_for_execution(self, *, intent_id: uuid.UUID, workspace_id: uuid.UUID) -> bool:
        """Conditional ``validated -> execution_started`` transition (compare-and-set).

        Together with the row lock, two concurrent executes can never both transition.
        """
        claimed = await self._db.scalar(
            update(Intent)
            .where(Intent.intent_id == intent_id, Intent.workspace_id == workspace_id,
                   Intent.status == "validated")
            .values(status="execution_started")
            .returning(Intent.intent_id)
        )
        return claimed is not None

    async def claim_deferred(self, *, limit: int, older_than_seconds: float) -> list[Intent]:
        """Committed intents whose lifecycle events were never confirmed published.

        ``stream_entry_id IS NULL``: nothing of the row's event sequence was confirmed
        (rows partially published by pre-ADR-028 code are left for operators).
        """
        result = await self._db.execute(
            select(Intent).where(
                Intent.queue_status == "deferred",
                Intent.stream_entry_id.is_(None),
                or_(Intent.warning.is_(None), Intent.warning == "event_queue_unavailable"),
                Intent.updated_at < func.now() - timedelta(seconds=older_than_seconds),
            ).order_by(Intent.updated_at, Intent.intent_id).with_for_update(skip_locked=True).limit(limit)
        )
        return list(result.scalars().all())

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

    async def get_execution(self, execution_id, *, lock=False):
        query = select(IntentExecution).where(IntentExecution.execution_id == execution_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(query)

    async def existing(self, workspace_id, intent_id, request_key):
        return list((await self.db.execute(select(IntentExecution).where(
            IntentExecution.workspace_id == workspace_id,
            or_(IntentExecution.intent_id == intent_id, IntentExecution.request_key == request_key),
        ))).scalars())

    async def claim(self, owner: str, lease_seconds: int):
        """Lease the oldest lab-blocking job (fence + 1); the caller commits."""
        row = (await self.db.execute(select(IntentExecution).where(
            IntentExecution.blocks_lab.is_(True),
            or_(IntentExecution.lease_until.is_(None), IntentExecution.lease_until < func.now()),
        ).order_by(IntentExecution.created_at).with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
        if row is not None:
            row.lease_owner = owner
            row.fence += 1
            row.lease_until = func.now() + timedelta(seconds=lease_seconds)
            await self.db.flush()
            # Load the server-computed lease expiry (and every column) inside this transaction.
            await self.db.refresh(row)
        return row

    async def owned(self, execution_id, owner, fence):
        return (await self.db.execute(select(IntentExecution).where(
            IntentExecution.execution_id == execution_id, IntentExecution.lease_owner == owner,
            IntentExecution.fence == fence, IntentExecution.lease_until > func.now(),
        ).with_for_update())).scalar_one_or_none()

    async def renew(self, execution_id, owner, fence, seconds):
        """Fenced lease extension; the caller commits when True."""
        result = await self.db.execute(update(IntentExecution).where(
            IntentExecution.execution_id == execution_id, IntentExecution.lease_owner == owner,
            IntentExecution.fence == fence, IntentExecution.lease_until > func.now(),
        ).values(lease_until=func.now() + timedelta(seconds=seconds)))
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
        """Lease the earliest unpublished event of an execution; the caller commits before XADD."""
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
            await self.db.flush()
        return row

    async def acknowledge_event(self, event_id, owner) -> bool:
        """Owned, unexpired lease only; False when the lease was lost. The caller commits."""
        result = await self.db.execute(update(IntentOutbox).where(
            IntentOutbox.event_id == event_id, IntentOutbox.lease_owner == owner,
            IntentOutbox.lease_until > func.now(),
        ).values(published_at=func.now(), lease_owner=None, lease_until=None))
        return result.rowcount == 1

    async def purge_published_events(self, *, older_than: timedelta, limit: int) -> int:
        """Delete at most ``limit`` outbox rows published before ``now() - older_than``.

        One statement; unpublished (or leased) rows are never touched, and claim order
        only consults unpublished rows, so old published rows carry no ordering role.
        Execution records themselves are kept. The caller commits.
        """
        if type(limit) is not int or not 1 <= limit <= MAX_RETENTION_BATCH_ROWS:
            raise ValueError("Retention batch must be between 1 and 10000 rows")
        if older_than <= timedelta(0):
            raise ValueError("Retention age must be positive")
        cutoff = func.now() - older_than
        victims = select(IntentOutbox.event_id).where(
            IntentOutbox.published_at.is_not(None), IntentOutbox.published_at < cutoff,
            IntentOutbox.created_at < cutoff,
        ).order_by(IntentOutbox.created_at, IntentOutbox.event_id).limit(limit).with_for_update(skip_locked=True)
        purged = delete(IntentOutbox).where(IntentOutbox.event_id.in_(victims)).returning(
            IntentOutbox.event_id,
        ).cte("purged")
        return int(await self.db.scalar(select(func.count()).select_from(purged)) or 0)
