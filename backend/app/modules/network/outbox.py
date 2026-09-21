"""Transactional inventory outbox and leased, at-least-once Redis publisher (ADR021).

Enqueue never commits. The owning inventory service commits mutation and event
together. Publication uses fresh sessions and never holds a DB lock over Redis I/O.
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.logging import get_logger
from app.modules.network.models import Network
from app.modules.network.outbox_models import NetworkOutbox

logger = get_logger(__name__)
INVENTORY_EVENTS = frozenset({
    "network.network.created", "network.network.updated", "network.network.deleted",
    "network.device.added", "network.device.updated", "network.device.deleted",
})


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

    async def enqueue(
        self, *, network_id: uuid.UUID, event_type: str, payload: dict, correlation_id: str,
    ) -> NetworkOutbox:
        if event_type not in INVENTORY_EVENTS:
            raise ValueError("Undocumented Network inventory event")
        event_id = uuid.uuid4()
        row = NetworkOutbox(
            event_id=event_id,
            network_id=network_id,
            envelope={
                "event_id": str(event_id),
                "event_type": event_type,
                "timestamp": datetime.now(UTC).isoformat(),
                "source": "network",
                "correlation_id": correlation_id,
                "version": "1",
                # Persist the wire payload too, so every replay is byte-stable.
                "payload": json.dumps(payload, allow_nan=False),
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


class NetworkOutboxPublisher:
    def __init__(
        self, *, sessions, redis, lease_seconds: float = 30, publish_timeout: float = 5,
        retry_base_seconds: float = 1, retry_max_seconds: float = 300,
    ):
        values = (lease_seconds, publish_timeout, retry_base_seconds, retry_max_seconds)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("Outbox durations must be finite and positive")
        if publish_timeout >= lease_seconds or retry_base_seconds > retry_max_seconds:
            raise ValueError("Publish timeout must be shorter than lease; retry bounds must be ordered")
        self._sessions = sessions
        self._redis = redis
        self._lease_seconds = lease_seconds
        self._publish_timeout = publish_timeout
        self._retry_base = retry_base_seconds
        self._retry_max = retry_max_seconds

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
        processed = 0
        for _ in range(limit):
            if not await self.publish_one():
                break
            processed += 1
        return processed
