"""NANFO Backend - Report module repository.

Persistence operations for report lifecycle records.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    Numeric, any_, bindparam, case, delete, func, literal, literal_column, or_, select, text, true, update,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.report.models import ReportOutbox, ReportRecord

# ADR-028 C20: default bound on worker claims per report (REPORTS_MAX_CLAIM_ATTEMPTS).
DEFAULT_MAX_CLAIM_ATTEMPTS = 5
# Exhausted jobs terminalized per claim call before giving the worker back control.
_EXHAUSTED_PER_CLAIM = 16
# Columns a history page needs; never the (up to 1 MiB) snapshot itself.
HISTORY_COLUMNS = (
    "report_id", "workspace_id", "network_id", "report_type", "output_format", "status",
    "date_range", "scope", "filters", "artifact_refs", "error_context", "queue_status",
    "stream_entry_id", "warning", "idempotency_key", "correlation_id", "requested_by_user_id",
    "requested_at", "completed_at", "created_at", "updated_at", "artifact_version",
    "status_version", "snapshot_sha256", "receipt",
)
# ADR-028: published lifecycle events are kept REPORT_OUTBOX_RETENTION_DAYS (getattr).
DEFAULT_OUTBOX_RETENTION_DAYS = 30
OUTBOX_PURGE_BATCH = 500


def outbox_age_column():
    """``report_outbox.created_at`` (migration 0030), or None while the model lacks it.

    Without it the purge ages rows by ``published_at`` alone: a row published N
    days ago was created at least N days ago, so it only ever deletes a subset.
    """
    return getattr(ReportOutbox, "created_at", None)


def attempts_exhausted_error(attempts: int) -> dict:
    return {
        "code": "REPORT_ATTEMPTS_EXHAUSTED",
        "reason": "attempts_exhausted",
        "message": (
            f"Report rendering did not complete after {attempts} worker attempts; "
            "submit a narrower report request."
        ),
    }


def snapshot_summary_expression():
    """Per-section summary computed in SQL: section metadata without ``rows`` plus
    ``row_count``. Only the small summary leaves the database."""
    sections = func.jsonb_each(
        case(
            (func.jsonb_typeof(ReportRecord.snapshot["sections"]) == "object", ReportRecord.snapshot["sections"]),
            else_=literal_column("'{}'::jsonb"),
        )
    ).table_valued("key", "value", name="section")
    rows = sections.c.value.op("->")(literal_column("'rows'"))
    row_count = case((func.jsonb_typeof(rows) == "array", func.jsonb_array_length(rows)), else_=literal_column("0"))
    summary = func.jsonb_object_agg(
        sections.c.key,
        sections.c.value.op("-")(literal_column("'rows'")).op("||")(
            func.jsonb_build_object(literal_column("'row_count'"), row_count)
        ),
    )
    return func.coalesce(
        select(summary).select_from(sections).scalar_subquery(), literal_column("'{}'::jsonb")
    ).cast(JSONB)


class ReportRepository:
    """Repository for report lifecycle persistence."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def history(self, workspace_id, user_id, page, page_size):
        """Exact scoped total plus one page of summary rows (no snapshots)."""
        scope = (
            ReportRecord.workspace_id == workspace_id,
            ReportRecord.requested_by_user_id == user_id,
        )
        total = (
            select(func.count())
            .select_from(ReportRecord)
            .where(*scope)
            .scalar_subquery()
        )
        # Page keys come from the (workspace, user, requested_at, report_id) index;
        # summary columns are then read for at most page_size rows.
        keys = (
            select(ReportRecord.report_id)
            .where(*scope)
            .order_by(ReportRecord.requested_at.desc(), ReportRecord.report_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .subquery("page_keys")
        )
        page_rows = (
            select(
                *(getattr(ReportRecord, name) for name in HISTORY_COLUMNS),
                snapshot_summary_expression().label("snapshot_summary"),
            )
            .join(keys, keys.c.report_id == ReportRecord.report_id)
            .subquery("page_rows")
        )
        counted = select(total.label("total")).subquery("counted")
        # One statement supplies an exact total even when the requested page is empty.
        rows = (
            await self._db.execute(
                select(counted.c.total, *(page_rows.c[name] for name in (*HISTORY_COLUMNS, "snapshot_summary")))
                .select_from(counted)
                .outerjoin(page_rows, true())
                .order_by(page_rows.c.requested_at.desc(), page_rows.c.report_id.desc())
            )
        ).all()
        return [row for row in rows if row.report_id is not None], rows[0].total

    def enqueue(self, record, *, metadata=None):
        """Stage the lifecycle event for ``record``'s current status version.

        ``metadata`` carries request provenance (for example the original opaque
        ``request_id``) in the event payload only; it is never part of the frozen,
        hashed snapshot (ADR-028).
        """
        event_type = f"report.{record.status}"
        event_id = uuid.uuid5(record.report_id, f"{record.status_version}:{event_type}")
        payload = {
            "report_id": str(record.report_id),
            "workspace_id": str(record.workspace_id),
            "network_id": str(record.network_id) if record.network_id else None,
            "report_type": record.report_type,
            "format": record.output_format,
            "status": record.status,
            "status_version": record.status_version,
            "snapshot_sha256": record.snapshot_sha256,
            "requested_by_user_id": record.requested_by_user_id,
            "requested_at": record.requested_at.isoformat(),
            "artifacts": record.artifact_refs,
            "error": record.error_context or None,
            "completed_at": record.completed_at.isoformat()
            if record.completed_at
            else None,
        }
        if metadata:
            payload = {**metadata, **payload}
        self._db.add(
            ReportOutbox(
                event_id=event_id,
                report_id=record.report_id,
                status_version=record.status_version,
                envelope={
                    "event_id": str(event_id),
                    "event_type": event_type,
                    "source": "report",
                    "version": "1",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "correlation_id": str(record.correlation_id),
                    "payload": json.dumps(
                        payload, sort_keys=True, separators=(",", ":")
                    ),
                },
            )
        )

    async def claim(self, lease_seconds, *, max_attempts=DEFAULT_MAX_CLAIM_ATTEMPTS):
        """Lease the oldest runnable job; ``claim_attempts`` bounds redelivery.

        A job already claimed ``max_attempts`` times (each attempt crashed, timed
        out or lost its lease) becomes terminal ``failed`` with reason
        ``attempts_exhausted`` in its own transaction instead of being leased
        again, so one poisoned snapshot cannot crash-loop the worker.
        """
        for _ in range(_EXHAUSTED_PER_CLAIM):
            record = await self._db.scalar(
                select(ReportRecord)
                .where(
                    ReportRecord.artifact_version == 1,
                    ReportRecord.status.in_(["requested", "running"]),
                    or_(
                        ReportRecord.lease_expires_at.is_(None),
                        ReportRecord.lease_expires_at < func.now(),
                    ),
                )
                .order_by(ReportRecord.requested_at, ReportRecord.report_id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            attempts = record.claim_attempts or 0
            if max_attempts is not None and attempts >= max_attempts:
                record.status_version += 1
                record.status = "failed"
                record.error_context = attempts_exhausted_error(attempts)
                record.receipt = None
                record.artifact_refs = []
                record.completed_at = await self._db.scalar(select(func.now()))
                record.lease_token = None
                record.lease_expires_at = None
                record.queue_status = "outbox_pending"
                self.enqueue(record)
                await self._db.commit()
                continue
            record.claim_attempts = attempts + 1
            record.lease_token = uuid.uuid4()
            record.lease_expires_at = await self._db.scalar(
                select(func.now() + timedelta(seconds=lease_seconds))
            )
            record.status_version += 1
            record.status = "running"
            await self._db.commit()
            return record
        return None

    async def renew_lease(self, claimed, lease_seconds) -> bool:
        """Extend a live lease while rendering; False once it was lost or fenced."""
        renewed = await self._db.scalar(
            update(ReportRecord)
            .where(
                ReportRecord.report_id == claimed.report_id,
                ReportRecord.status == "running",
                ReportRecord.status_version == claimed.status_version,
                ReportRecord.lease_token == claimed.lease_token,
                ReportRecord.lease_expires_at > func.now(),
            )
            .values(lease_expires_at=func.now() + timedelta(seconds=lease_seconds))
            .returning(ReportRecord.report_id)
        )
        await self._db.commit()
        return renewed is not None

    async def finish(self, claimed, *, receipt=None, error=None):
        from app.modules.report.artifacts import digest

        version = claimed.status_version + 1
        now = datetime.now(UTC)
        if receipt:
            receipt = {
                **receipt,
                "snapshot_sha256": claimed.snapshot_sha256,
                "status_version": version,
                "generated_at": now.isoformat(),
            }
            receipt["receipt_sha256"] = digest(receipt)
        artifacts = (
            [
                {
                    key: value
                    for key, value in receipt.items()
                    if key
                    not in {"receipt_sha256", "status_version", "snapshot_sha256"}
                }
            ]
            if receipt
            else []
        )
        if artifacts:
            artifacts[0]["uri"] = (
                f"/api/v1/reports/{claimed.report_id}/download?workspace_id={claimed.workspace_id}"
            )
        row = await self._db.scalar(
            update(ReportRecord)
            .where(
                ReportRecord.report_id == claimed.report_id,
                ReportRecord.status == "running",
                ReportRecord.status_version == claimed.status_version,
                ReportRecord.lease_token == claimed.lease_token,
                ReportRecord.lease_expires_at > func.now(),
            )
            .values(
                status="generated" if receipt else "failed",
                status_version=version,
                receipt=receipt,
                artifact_refs=artifacts,
                error_context=error or {},
                completed_at=now,
                lease_token=None,
                lease_expires_at=None,
                queue_status="outbox_pending",
            )
            .returning(ReportRecord)
        )
        if row is None:
            await self._db.rollback()
            return False
        self.enqueue(row)
        await self._db.commit()
        return True

    async def publish_one(self, redis):
        prior = aliased(ReportOutbox)
        row = await self._db.scalar(
            select(ReportOutbox)
            .where(
                ReportOutbox.published_at.is_(None),
                ~select(prior.event_id)
                .where(
                    prior.report_id == ReportOutbox.report_id,
                    prior.status_version < ReportOutbox.status_version,
                    prior.published_at.is_(None),
                )
                .exists(),
            )
            .order_by(ReportOutbox.report_id, ReportOutbox.status_version)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return False
        async with asyncio.timeout(10):
            entry = await redis.xadd("stream:report", row.envelope)
        row.stream_entry_id = entry.decode() if isinstance(entry, bytes) else entry
        row.published_at = datetime.now(UTC)
        await self._db.execute(
            update(ReportRecord)
            .where(
                ReportRecord.report_id == row.report_id,
                ReportRecord.status_version == row.status_version,
            )
            .values(queue_status="queued", stream_entry_id=row.stream_entry_id)
        )
        await self._db.commit()
        return True

    async def purge_published_outbox(self, *, retention_days: int, batch_size: int = OUTBOX_PURGE_BATCH) -> int:
        """Delete ONE bounded batch of published outbox rows past retention; commits.

        A row goes only once it was published AND (when the column exists)
        created more than ``retention_days`` ago. Unpublished rows are the pending
        delivery queue and gate per-report publication order: never touched.
        """
        if not 1 <= retention_days <= 36500 or not 1 <= batch_size <= 10000:
            raise ValueError("retention must be 1..36500 days and batch size 1..10000")
        cutoff = func.now() - timedelta(days=retention_days)
        conditions = [ReportOutbox.published_at.is_not(None), ReportOutbox.published_at < cutoff]
        created = outbox_age_column()
        if created is not None:
            conditions.append(created < cutoff)
        batch = (select(ReportOutbox.event_id).where(*conditions)
                 .limit(batch_size).with_for_update(skip_locked=True))
        result = await self._db.execute(
            delete(ReportOutbox).where(ReportOutbox.event_id.in_(batch)).returning(ReportOutbox.event_id))
        deleted = len(result.all())
        await self._db.commit()
        return deleted

    async def get_by_id(self, report_id: uuid.UUID) -> ReportRecord | None:
        result = await self._db.execute(
            select(ReportRecord).where(ReportRecord.report_id == report_id)
        )
        return result.scalar_one_or_none()

    async def lock_org_storage(self, org_id: uuid.UUID) -> None:
        """Serialize C26 storage admission per organisation until this transaction ends."""
        await self._db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"report:org-storage:{org_id}"},
        )

    async def storage_usage(self, workspace_ids, *, in_flight_reserve_bytes: int) -> int:
        """Report storage attributed to these workspaces (Report-owned rows only).

        Generated reports count their recorded artifact size; requested/running
        jobs reserve one full artifact until they finish. Failed jobs hold no file
        (an attempt's file is discarded), and rows without a numeric receipt size
        count zero.
        """
        workspaces = sorted(set(workspace_ids))
        if not workspaces:
            return 0
        size = case(
            (func.jsonb_typeof(ReportRecord.receipt["size_bytes"]) == "number",
             ReportRecord.receipt["size_bytes"].astext.cast(Numeric)),
            else_=literal(0),
        )
        usage = func.coalesce(func.sum(case(
            (ReportRecord.status == "generated", size),
            (ReportRecord.status.in_(("requested", "running")), literal(int(in_flight_reserve_bytes))),
            else_=literal(0),
        )), 0)
        scope = (ReportRecord.workspace_id == workspaces[0] if len(workspaces) == 1 else
                 ReportRecord.workspace_id == any_(bindparam(
                     "workspace_ids", workspaces, type_=ARRAY(PG_UUID(as_uuid=True)), unique=True)))
        return int(await self._db.scalar(select(usage).where(scope)) or 0)

    async def get_by_idempotency_key(
        self,
        *,
        workspace_id: uuid.UUID,
        idempotency_key: str,
    ) -> ReportRecord | None:
        result = await self._db.execute(
            select(ReportRecord).where(
                ReportRecord.workspace_id == workspace_id,
                ReportRecord.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()
