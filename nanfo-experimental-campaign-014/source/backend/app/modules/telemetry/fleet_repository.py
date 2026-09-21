"""Short owning transactions; no database transaction spans collector I/O."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.modules.telemetry.fleet_models import FleetBatch, FleetDevice
from app.modules.telemetry.snmp_config import SNMPError


@dataclass(frozen=True)
class FleetLease:
    device_id: uuid.UUID
    owner_id: uuid.UUID
    token: uuid.UUID


class FleetRepository:
    def __init__(self, sessions, *, lease_seconds: float, timeout_seconds: float):
        self.sessions = sessions
        self.lease_seconds = lease_seconds
        self.timeout_seconds = timeout_seconds

    @asynccontextmanager
    async def transaction(self):
        async with asyncio.timeout(self.timeout_seconds), self.sessions() as db, db.begin():
            yield db

    async def claim(self, device_id: uuid.UUID, owner_id: uuid.UUID) -> FleetLease | None:
        async with self.transaction() as db:
            await db.execute(insert(FleetDevice).values(device_id=device_id).on_conflict_do_nothing())
            row = await db.get(FleetDevice, device_id, with_for_update=True)
            now = await db.scalar(select(func.clock_timestamp()))
            if row.next_poll_at > now or (row.lease_until is not None and row.lease_until > now):
                return None
            row.owner_id, row.lease_token = owner_id, uuid.uuid4()
            row.lease_until = now + timedelta(seconds=self.lease_seconds)
            row.updated_at = now
            return FleetLease(device_id, owner_id, row.lease_token)

    async def _locked(self, db, lease: FleetLease):
        row = await db.get(FleetDevice, lease.device_id, with_for_update=True)
        now = await db.scalar(select(func.clock_timestamp()))
        if (row is None or row.lease_token != lease.token or row.owner_id != lease.owner_id
                or row.lease_until is None or row.lease_until <= now):
            raise SNMPError("fleet_lease_lost")
        return row, now

    async def check(self, lease: FleetLease, *, renew: bool = False) -> None:
        async with self.transaction() as db:
            row, now = await self._locked(db, lease)
            if renew:
                row.lease_until = now + timedelta(seconds=self.lease_seconds)
                row.updated_at = now

    async def pending(self, lease: FleetLease) -> FleetBatch | None:
        async with self.transaction() as db:
            await self._locked(db, lease)
            return await db.scalar(select(FleetBatch).where(
                FleetBatch.device_id == lease.device_id, FleetBatch.status == "pending",
            ))

    async def stage(self, lease: FleetLease, *, digest: str, samples: list[dict], expires_at: datetime) -> FleetBatch:
        if not 1 <= len(samples) <= 112 or len({s["event_id"] for s in samples}) != len(samples):
            raise SNMPError("fleet_invalid_batch")
        async with self.transaction() as db:
            await self._locked(db, lease)
            batch = FleetBatch(batch_id=uuid.uuid4(), device_id=lease.device_id, binding_sha256=digest,
                               samples=samples, expires_at=expires_at, cursor=0, status="pending")
            db.add(batch)
            await db.flush()
            return batch

    async def ready(self, lease: FleetLease, batch_id: uuid.UUID, digest: str) -> FleetBatch:
        """Check absolute deadline against DB time immediately before publication."""
        async with self.transaction() as db:
            row, now = await self._locked(db, lease)
            batch = await db.get(FleetBatch, batch_id, with_for_update=True)
            if batch is None or batch.device_id != lease.device_id:
                raise SNMPError("fleet_batch_missing")
            if batch.status == "pending" and (batch.expires_at <= now or batch.binding_sha256 != digest):
                batch.status = "expired" if batch.expires_at <= now else "binding_changed"
                batch.completed_at = now
                row.outcome = batch.status
                if batch.status == "expired":
                    row.expired_samples += len(batch.samples) - batch.cursor
            return batch

    async def acknowledge(self, lease: FleetLease, batch_id: uuid.UUID, cursor: int) -> None:
        async with self.transaction() as db:
            row, now = await self._locked(db, lease)
            batch = await db.get(FleetBatch, batch_id, with_for_update=True)
            if (batch is None or batch.device_id != lease.device_id or batch.status != "pending"
                    or batch.cursor != cursor or cursor >= len(batch.samples)):
                raise SNMPError("fleet_acknowledgement_mismatch")
            batch.cursor += 1
            row.last_published_at = now
            row.published_samples += 1
            if batch.cursor == len(batch.samples):
                batch.status, batch.completed_at = "published", now

    async def finish(self, lease: FleetLease, *, outcome: str, interval: float, backoff_max: float,
                     failed: bool, retained_batches: int = 32) -> None:
        async with self.transaction() as db:
            row, now = await self._locked(db, lease)
            row.failures = min(row.failures + 1, 30) if failed else 0
            delay = min(backoff_max, interval * 2 ** min(row.failures, 20)) if failed else interval
            row.next_poll_at = now + timedelta(seconds=delay)
            row.outcome, row.updated_at = outcome, now
            row.owner_id = row.lease_token = row.lease_until = None
            # Spool is delivery state, not the owning telemetry history. Keep a
            # bounded terminal audit tail; lifetime counters survive its compaction.
            old = select(FleetBatch.batch_id).where(
                FleetBatch.device_id == lease.device_id, FleetBatch.status != "pending",
            ).order_by(FleetBatch.created_at.desc(), FleetBatch.batch_id.desc()).offset(retained_batches)
            await db.execute(delete(FleetBatch).where(FleetBatch.batch_id.in_(old)))

    async def health(self, device_ids: list[uuid.UUID]) -> list[dict]:
        async with self.transaction() as db:
            now = await db.scalar(select(func.clock_timestamp()))
            rows = (await db.scalars(select(FleetDevice).where(FleetDevice.device_id.in_(device_ids)))).all()
            return [{"device_id": str(row.device_id), "outcome": row.outcome, "failures": row.failures,
                     "lease_active": row.lease_until is not None and row.lease_until > now,
                     "updated_at": row.updated_at.isoformat(), "next_poll_at": row.next_poll_at.isoformat(),
                     "last_published_at": row.last_published_at.isoformat() if row.last_published_at else None,
                     "published_samples": row.published_samples, "expired_samples": row.expired_samples}
                    for row in rows]


class FleetLock:
    """Session exclusion plus expiring lease. Use a dedicated NullPool engine.

    A live lock prevents expiry from admitting a second replica during a GET.
    Closing/invalidation prevents advisory locks leaking into a connection pool.
    Connection checks are serialized with watchdog checks, never with external I/O.
    """

    def __init__(self, engine, repository: FleetRepository):
        self.engine, self.repository = engine, repository

    @asynccontextmanager
    async def acquire(self, device_id: uuid.UUID, owner_id: uuid.UUID):
        key = int.from_bytes(hashlib.sha256(b"nanfo-fleet/v1/" + device_id.bytes).digest()[:8], "big", signed=True)
        connection = None
        try:
            async with asyncio.timeout(self.repository.timeout_seconds):
                connection = await self.engine.connect()
                await connection.execution_options(isolation_level="AUTOCOMMIT")
                acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
            if not acquired:
                yield None
                return
            lease = await self.repository.claim(device_id, owner_id)
            if lease is None:
                yield None
                return
            gate = asyncio.Lock()

            async def check(*, renew=False):
                async with gate, asyncio.timeout(self.repository.timeout_seconds):
                    # A disconnected SQLAlchemy connection must NOT transparently
                    # reconnect and pretend it still owns a session advisory lock.
                    if connection.invalidated or connection.closed:
                        raise SNMPError("fleet_lock_lost")
                    await connection.scalar(text("SELECT 1"))
                    await self.repository.check(lease, renew=renew)

            yield lease, check
        finally:
            if connection is not None:
                # Always discard the physical session, including cancellation and
                # uncertain acquisition. PostgreSQL releases its session locks.
                await connection.invalidate()
                await connection.close()
