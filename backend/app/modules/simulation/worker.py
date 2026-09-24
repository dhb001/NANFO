"""Independent bounded worker; no simulation computation in HTTP/event consumers.

Unit of work (ADR-028): the repository never commits; this worker commits each short
transaction — claim, fenced batch result, outbox claim, acknowledgement — and runs
model computation and Redis I/O only between transactions, never under a row lock.

Outbox retention (ADR-028): published ``simulation_outbox`` rows older than
``SIMULATION_OUTBOX_RETENTION_DAYS`` (default 30, 0 disables) are deleted in bounded
batches from the outbox publication path, at most once per interval unless a full
batch shows a backlog. Retention failures never block publication.
"""

import asyncio
import time
from datetime import timedelta

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.simulation.evaluator import advance, canonical_config, digest, output
from app.modules.simulation.repository import SimulationRepository
from app.modules.simulation.schemas import ScenarioConfig

logger = get_logger(__name__)
# Per-call XADD bound (persistence F28); a timeout leaves the row unpublished for retry.
PUBLISH_TIMEOUT_SECONDS = 10.0
DEFAULT_OUTBOX_RETENTION_DAYS = 30
RETENTION_BATCH_ROWS = 500
RETENTION_INTERVAL_SECONDS = 60.0
_MAX_RETENTION_DAYS = 36_500
_FROM_SETTINGS = object()


def max_claim_attempts(settings=None) -> int:
    """ADR-028 C20 cap (``SIMULATION_MAX_CLAIM_ATTEMPTS``); getattr keeps test doubles simple."""
    settings = settings or get_settings()
    return int(getattr(settings, "SIMULATION_MAX_CLAIM_ATTEMPTS", 5))


def outbox_retention_days(settings=None) -> int | None:
    """``SIMULATION_OUTBOX_RETENTION_DAYS``; ``None`` (retention off) for 0 or invalid values."""
    settings = settings or get_settings()
    value = getattr(settings, "SIMULATION_OUTBOX_RETENTION_DAYS", DEFAULT_OUTBOX_RETENTION_DAYS)
    if type(value) is int and 1 <= value <= _MAX_RETENTION_DAYS:
        return value
    if value != 0:
        # Deleting is the unsafe direction: an unusable value disables retention.
        logger.warning("simulation_outbox_retention_disabled_invalid_setting")
    return None


class SimulationWorker:
    def __init__(self, *, sessions, redis, batch_ticks: int = 8, max_attempts: int | None = None,
                 publish_timeout_seconds: float = PUBLISH_TIMEOUT_SECONDS,
                 retention_days: int | None | object = _FROM_SETTINGS,
                 retention_batch: int = RETENTION_BATCH_ROWS,
                 retention_interval_seconds: float = RETENTION_INTERVAL_SECONDS, clock=time.monotonic):
        if type(batch_ticks) is not int or not 1 <= batch_ticks <= 32:
            raise ValueError("batch_ticks must be 1..32")
        if not 0 < publish_timeout_seconds <= 60:
            raise ValueError("publish_timeout_seconds must be within (0, 60]")
        self.sessions, self.redis, self.batch_ticks = sessions, redis, batch_ticks
        self.publish_timeout_seconds = publish_timeout_seconds
        self.max_attempts = max_claim_attempts() if max_attempts is None else max_attempts
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if retention_days is _FROM_SETTINGS:
            retention_days = outbox_retention_days()
        if retention_days is not None and (type(retention_days) is not int
                                           or not 1 <= retention_days <= _MAX_RETENTION_DAYS):
            raise ValueError("retention_days must be None or 1..36500")
        if type(retention_batch) is not int or not 1 <= retention_batch <= 10_000:
            raise ValueError("retention_batch must be 1..10000 rows")
        if not 0 < retention_interval_seconds <= 86400:
            raise ValueError("retention_interval_seconds must be within (0, 86400]")
        self.retention_days, self.retention_batch = retention_days, retention_batch
        self.retention_interval_seconds, self._clock = retention_interval_seconds, clock
        self._next_purge: float | None = None

    async def run_one(self) -> bool:
        async with self.sessions() as db:
            # Claims without committed progress are counted; a job that keeps
            # crashing its worker becomes terminal failed/attempts_exhausted. The
            # commit also persists exhaustions when no runnable job remains.
            claimed = await SimulationRepository(db).claim(max_attempts=self.max_attempts)
            await db.commit()
        if claimed is None:
            return False
        try:
            config = ScenarioConfig.model_validate(claimed.scenario_config)
            if digest(canonical_config(config)) != claimed.input_sha256:
                raise ValueError("Input hash mismatch")
            checkpoint = await asyncio.to_thread(
                advance, config, claimed.checkpoint, ticks=self.batch_ticks
            )
            result = await asyncio.to_thread(output, config, checkpoint)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            await self._finish(claimed, checkpoint=None, run_output=None, failure="model_checkpoint_invalid")
            return True
        await self._finish(claimed, checkpoint=checkpoint, run_output=result)
        return True

    async def _finish(self, claimed, **values) -> bool:
        async with self.sessions() as db:
            if await SimulationRepository(db).finish_batch(claimed, **values):
                await db.commit()
                return True
            # Lease lost or fenced by pause/cancel: nothing of this batch is written.
            await db.rollback()
            return False

    async def purge_published(self) -> int:
        """One bounded retention batch when due; a full batch makes the next one due at once."""
        if self.retention_days is None:
            return 0
        now = self._clock()
        if self._next_purge is not None and now < self._next_purge:
            return 0
        self._next_purge = now + self.retention_interval_seconds
        async with self.sessions() as db:
            purged = await SimulationRepository(db).purge_published_events(
                older_than=timedelta(days=self.retention_days), limit=self.retention_batch)
            await db.commit()
        if purged >= self.retention_batch:
            self._next_purge = now  # backlog: continue on the next call, one short transaction each
        if purged:
            logger.info("simulation_outbox_retention_purged", rows=purged, retention_days=self.retention_days)
        return purged

    async def publish_one(self) -> bool:
        """Claim -> commit -> XADD (bounded) -> acknowledge; never XADD inside a transaction."""
        try:
            await self.purge_published()
        except Exception as exc:  # noqa: BLE001 - retention is best effort; publication must not stall
            logger.warning("simulation_outbox_retention_deferred", error_type=type(exc).__name__)
        async with self.sessions() as db:
            event = await SimulationRepository(db).claim_next_event()
            await db.commit()
        if event is None:
            return False
        async with asyncio.timeout(self.publish_timeout_seconds):
            await self.redis.xadd("stream:simulation", event.envelope)
        # Process death or a DB failure here republishes the same stable event later.
        async with self.sessions() as db:
            acknowledged = await SimulationRepository(db).acknowledge_event(event.event_id)
            await db.commit()
        if not acknowledged:
            logger.info("simulation_outbox_already_acknowledged", event_id=str(event.event_id))
        return True
