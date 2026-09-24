"""Transactional inventory outbox and leased, at-least-once Redis publisher (ADR021).

Enqueue never commits. The owning inventory service commits mutation and event
together. Publication uses fresh sessions and never holds a DB lock over Redis I/O.
The publisher also applies bounded retention to *published* rows (ADR-028, F18) and
refuses to publish while Redis is near its memory bound (C14 admission).
"""

from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.logging import get_logger
from app.events.publisher import admit_publication
from app.modules.network.models import Network
from app.modules.network.outbox_models import NetworkOutbox

logger = get_logger(__name__)
INVENTORY_EVENTS = frozenset({
    "network.network.created", "network.network.updated", "network.network.deleted",
    "network.device.added", "network.device.updated", "network.device.deleted",
})
#: Published rows are kept this many days unless NETWORK_OUTBOX_RETENTION_DAYS says otherwise.
DEFAULT_RETENTION_DAYS = 30
#: Rows deleted per retention statement (one short transaction) and minimum spacing.
RETENTION_BATCH_ROWS = 500
RETENTION_INTERVAL_SECONDS = 60.0
_MAX_RETENTION_DAYS = 36_500
_FROM_SETTINGS = object()


def configured_retention_days() -> int | None:
    """``NETWORK_OUTBOX_RETENTION_DAYS`` (default 30); ``None`` disables deletion.

    ``0`` explicitly disables retention. Any other non-positive, non-integer or
    absurd value also disables it (logged): deleting is the unsafe direction.
    """
    from app.core.config import get_settings

    value = getattr(get_settings(), "NETWORK_OUTBOX_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)
    if value is None:
        return DEFAULT_RETENTION_DAYS
    if type(value) is int and 1 <= value <= _MAX_RETENTION_DAYS:
        return value
    if value != 0:
        logger.warning("network_outbox_retention_disabled_invalid_setting")
    return None


@dataclass(frozen=True)
class OutboxClaim:
    event_id: uuid.UUID
    lease_token: uuid.UUID
    envelope: dict[str, str]
    attempts: int


class NetworkOutboxRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def lock_inventory(self, network_id: uuid.UUID) -> None:
        """Serialize event-bearing writes per network, including sequence allocation.

        This transaction-scoped lock is released by the inventory commit/rollback.
        Hash collisions only serialize unrelated networks; they cannot lose events.
        Callers authorize *before* requesting it (``NetworkAccessGuard``) and
        re-check authority after it is granted.
        """
        key = int.from_bytes(network_id.bytes[:8], "big", signed=True)
        await self._db.execute(select(func.pg_advisory_xact_lock(key)))
        # Spatial writes acquire a shared parent lock before device/scene locks.
        # Take the parent first too, so deletion cannot race a scene association.
        await self._db.execute(select(Network.network_id).where(
            Network.network_id == network_id,
        ).with_for_update())
        # Current authority must be loaded again after a potentially blocking lock,
        # including when an internal caller reused a session with cached memberships.
        await self._db.run_sync(lambda session: session.expire_all())

    async def allocate_sequence(self) -> int:
        """Draw the next outbox sequence before building the envelope (C13).

        Writers hold the per-network inventory lock from allocation until commit,
        so per-network sequence order is also commit and publication order.
        """
        value = await self._db.scalar(select(func.nextval(
            func.pg_get_serial_sequence(NetworkOutbox.__tablename__, "sequence"),
        )))
        return int(value)

    async def watermark(self) -> int:
        """Highest committed outbox sequence (index-backed; 0 when empty).

        Read under a network's inventory lock it is a safe projection watermark for
        that network: every earlier event of the network is committed, and every
        later one will draw a larger sequence.
        """
        return int(await self._db.scalar(select(func.coalesce(func.max(NetworkOutbox.sequence), 0))) or 0)

    async def enqueue(
        self, *, network_id: uuid.UUID, event_type: str, payload: dict, correlation_id: str,
    ) -> NetworkOutbox:
        if event_type not in INVENTORY_EVENTS:
            raise ValueError("Undocumented Network inventory event")
        event_id = uuid.uuid4()
        sequence = await self.allocate_sequence()
        row = NetworkOutbox(
            event_id=event_id,
            sequence=sequence,
            network_id=network_id,
            envelope={
                "event_id": str(event_id),
                "event_type": event_type,
                "timestamp": datetime.now(UTC).isoformat(),
                "source": "network",
                "correlation_id": correlation_id,
                "version": "1",
                # Persist the wire payload too, so every replay is byte-stable. The
                # additive ``sequence`` lets consumers order per network (C13).
                "payload": json.dumps({**payload, "sequence": sequence}, allow_nan=False),
            },
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def claim(self, *, lease_seconds: float) -> OutboxClaim | None:
        older = aliased(NetworkOutbox)
        row = (await self._db.execute(
            select(NetworkOutbox).where(
                NetworkOutbox.published_at.is_(None),
                NetworkOutbox.next_attempt_at <= func.now(),
                or_(NetworkOutbox.lease_until.is_(None), NetworkOutbox.lease_until <= func.now()),
                ~exists().where(
                    older.network_id == NetworkOutbox.network_id,
                    older.sequence < NetworkOutbox.sequence,
                    older.published_at.is_(None),
                ),
            ).order_by(NetworkOutbox.sequence).limit(1).with_for_update(skip_locked=True)
        )).scalar_one_or_none()
        if row is None:
            return None
        token = uuid.uuid4()
        claim = OutboxClaim(row.event_id, token, dict(row.envelope), row.attempts + 1)
        row.lease_token = token
        row.lease_until = func.now() + timedelta(seconds=lease_seconds)
        row.attempts = claim.attempts
        await self._db.commit()
        return claim

    def _owned(self, claim: OutboxClaim):
        return update(NetworkOutbox).where(
            NetworkOutbox.event_id == claim.event_id,
            NetworkOutbox.lease_token == claim.lease_token,
            NetworkOutbox.lease_until > func.now(),
            NetworkOutbox.published_at.is_(None),
        )

    async def acknowledge(self, claim: OutboxClaim) -> bool:
        result = await self._db.execute(self._owned(claim).values(
            published_at=func.now(), lease_token=None, lease_until=None, last_error=None,
        ).returning(NetworkOutbox.event_id))
        acknowledged = result.scalar_one_or_none() is not None
        await self._db.commit()
        return acknowledged

    async def defer(self, claim: OutboxClaim, *, delay_seconds: float, error: str) -> bool:
        result = await self._db.execute(self._owned(claim).values(
            next_attempt_at=func.now() + timedelta(seconds=delay_seconds),
            lease_token=None, lease_until=None, last_error=error[:128],
        ).returning(NetworkOutbox.event_id))
        deferred = result.scalar_one_or_none() is not None
        await self._db.commit()
        return deferred

    async def purge_published(self, *, older_than: timedelta, limit: int) -> int:
        """Delete at most ``limit`` rows published before ``now() - older_than``; one statement.

        * Unpublished rows are never touched (at-least-once delivery is preserved).
        * The highest-sequence row is always retained: it anchors :meth:`watermark`
          for topology reconcile even when every other row has aged out.
        * ``FOR UPDATE SKIP LOCKED`` lets concurrent publisher replicas share the work
          without waiting on each other. Oldest sequences go first (unique index).

        The caller commits.
        """
        if type(limit) is not int or not 1 <= limit <= 10_000:
            raise ValueError("Retention batch must be between 1 and 10000 rows")
        if older_than <= timedelta(0):
            raise ValueError("Retention age must be positive")
        newest = select(func.max(NetworkOutbox.sequence)).scalar_subquery()
        victims = select(NetworkOutbox.event_id).where(
            NetworkOutbox.published_at.is_not(None),
            NetworkOutbox.published_at < func.now() - older_than,
            NetworkOutbox.sequence < newest,
        ).order_by(NetworkOutbox.sequence).limit(limit).with_for_update(skip_locked=True)
        purged = delete(NetworkOutbox).where(NetworkOutbox.event_id.in_(victims)).returning(
            NetworkOutbox.event_id,
        ).cte("purged")
        return int(await self._db.scalar(select(func.count()).select_from(purged)) or 0)


class NetworkOutboxPublisher:
    def __init__(
        self, *, sessions, redis, lease_seconds: float = 30, publish_timeout: float = 5,
        retry_base_seconds: float = 1, retry_max_seconds: float = 300,
        retention_days: int | None | object = _FROM_SETTINGS, retention_batch: int = RETENTION_BATCH_ROWS,
        retention_interval_seconds: float = RETENTION_INTERVAL_SECONDS, clock=time.monotonic,
    ):
        values = (lease_seconds, publish_timeout, retry_base_seconds, retry_max_seconds, retention_interval_seconds)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("Outbox durations must be finite and positive")
        if publish_timeout >= lease_seconds or retry_base_seconds > retry_max_seconds:
            raise ValueError("Publish timeout must be shorter than lease; retry bounds must be ordered")
        if retention_days is _FROM_SETTINGS:
            retention_days = configured_retention_days()
        if retention_days is not None and (type(retention_days) is not int
                                           or not 1 <= retention_days <= _MAX_RETENTION_DAYS):
            raise ValueError("Outbox retention must be None or 1..36500 days")
        if type(retention_batch) is not int or not 1 <= retention_batch <= 10_000:
            raise ValueError("Outbox retention batch must be between 1 and 10000 rows")
        self._sessions = sessions
        self._redis = redis
        self._lease_seconds = lease_seconds
        self._publish_timeout = publish_timeout
        self._retry_base = retry_base_seconds
        self._retry_max = retry_max_seconds
        self._retention_days = retention_days
        self._retention_batch = retention_batch
        self._retention_interval = retention_interval_seconds
        self._clock = clock
        self._next_purge: float | None = None

    async def publish_one(self) -> bool:
        async with self._sessions() as db:
            claim = await NetworkOutboxRepository(db).claim(lease_seconds=self._lease_seconds)
        if claim is None:
            return False
        try:
            async with asyncio.timeout(self._publish_timeout):
                # Shared publish_event regenerates timestamps; send the stored
                # EventAPI envelope directly, as required for stable replay.
                await self._redis.xadd("stream:network", claim.envelope)
        except Exception as exc:  # noqa: BLE001 - retain every failed publication for retry
            delay = min(self._retry_max, self._retry_base * 2 ** min(claim.attempts - 1, 30))
            async with self._sessions() as db:
                await NetworkOutboxRepository(db).defer(
                    claim, delay_seconds=delay, error=type(exc).__name__,
                )
            logger.warning("network_outbox_deferred", event_id=str(claim.event_id), attempts=claim.attempts)
            raise
        # Cancellation/process death/DB failure after XADD leaves a reclaimable lease.
        async with self._sessions() as db:
            acknowledged = await NetworkOutboxRepository(db).acknowledge(claim)
        if not acknowledged:
            logger.warning("network_outbox_lease_lost", event_id=str(claim.event_id))
        return True

    async def drain(self, *, limit: int = 32) -> int:
        if not 1 <= limit <= 1024:
            raise ValueError("Outbox batch limit must be between 1 and 1024")
        try:
            await self.purge_published()
        except Exception as exc:  # noqa: BLE001 - retention is best effort; publication must not stall
            logger.warning("network_outbox_retention_deferred", error_type=type(exc).__name__)
        # C14 producer admission: while Redis is near its memory bound, leave every
        # row unclaimed (no lease, no attempt, no backoff) and let the loop retry.
        await admit_publication(self._redis)
        processed = 0
        for _ in range(limit):
            if not await self.publish_one():
                break
            processed += 1
        return processed

    async def purge_published(self) -> int:
        """One bounded retention batch, at most once per retention interval.

        A full batch schedules the next batch for the following iteration, so a
        backlog drains in short transactions instead of one long delete.
        """
        if self._retention_days is None:
            return 0
        now = self._clock()
        if self._next_purge is not None and now < self._next_purge:
            return 0
        self._next_purge = now + self._retention_interval
        async with self._sessions() as db:
            try:
                deleted = await NetworkOutboxRepository(db).purge_published(
                    older_than=timedelta(days=self._retention_days), limit=self._retention_batch,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        if deleted >= self._retention_batch:
            self._next_purge = now
        if deleted:
            logger.info("network_outbox_retention_purged", deleted=deleted, retention_days=self._retention_days)
        return deleted
