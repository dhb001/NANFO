"""Bounded retention of Alert observation receipts (ADR-028).

``alert_observations`` gains one row per accepted measured sample. The alert
worker loop calls :meth:`ObservationRetention.maybe_purge` every iteration; it
runs at most once per interval and deletes at most ``max_batches`` batches of
``batch_size`` receipts older than ``ALERT_OBSERVATION_RETENTION_DAYS`` that no
open incident window or incident lifecycle record needs (see
:meth:`AlertRepository.purge_observations`). ``0`` days disables the purge.

Optional settings (read with ``getattr``; out-of-range values are clamped):
``ALERT_OBSERVATION_RETENTION_DAYS`` (30, 0..36500),
``ALERT_OBSERVATION_PURGE_BATCH_SIZE`` (1000, 1..10000),
``ALERT_OBSERVATION_PURGE_MAX_BATCHES`` (10, 1..1000),
``ALERT_OBSERVATION_PURGE_INTERVAL_SECONDS`` (300, 30..86400).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.alert.repository import AlertRepository

logger = get_logger(__name__)

DEFAULT_RETENTION_DAYS = 30
DEFAULT_BATCH_SIZE = 1000
DEFAULT_MAX_BATCHES = 10
DEFAULT_INTERVAL_SECONDS = 300
PURGE_TIMEOUT_SECONDS = 60


def bounded_setting(settings, name: str, default: int, low: int, high: int) -> int:
    """Optional integer setting via ``getattr``; invalid -> default, out of range -> clamped."""
    value = getattr(settings, name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return int(min(max(value, low), high))


@dataclass(frozen=True)
class ObservationRetentionPolicy:
    retention_days: int = DEFAULT_RETENTION_DAYS
    batch_size: int = DEFAULT_BATCH_SIZE
    max_batches: int = DEFAULT_MAX_BATCHES
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS

    @classmethod
    def from_settings(cls, settings) -> ObservationRetentionPolicy:
        return cls(
            retention_days=bounded_setting(settings, "ALERT_OBSERVATION_RETENTION_DAYS",
                                           DEFAULT_RETENTION_DAYS, 0, 36500),
            batch_size=bounded_setting(settings, "ALERT_OBSERVATION_PURGE_BATCH_SIZE",
                                       DEFAULT_BATCH_SIZE, 1, 10000),
            max_batches=bounded_setting(settings, "ALERT_OBSERVATION_PURGE_MAX_BATCHES",
                                        DEFAULT_MAX_BATCHES, 1, 1000),
            interval_seconds=bounded_setting(settings, "ALERT_OBSERVATION_PURGE_INTERVAL_SECONDS",
                                             DEFAULT_INTERVAL_SECONDS, 30, 86400),
        )

    @property
    def enabled(self) -> bool:
        return self.retention_days > 0


class ObservationRetention:
    """Interval-gated, bounded purge driven by the alert worker loop."""

    def __init__(self, *, sessions, settings=None, clock=time.monotonic):
        self.sessions = sessions
        self.policy = ObservationRetentionPolicy.from_settings(settings or get_settings())
        self.clock = clock
        self._next_run = 0.0

    async def maybe_purge(self, *, force: bool = False) -> dict | None:
        """Run one bounded purge when due; ``None`` when skipped (disabled or not due)."""
        if not self.policy.enabled:
            return None
        now = self.clock()
        if not force and now < self._next_run:
            return None
        # Schedule first: a failing purge retries next interval, never in a hot loop.
        self._next_run = now + self.policy.interval_seconds
        deleted, batches = 0, 0
        async with asyncio.timeout(PURGE_TIMEOUT_SECONDS):
            while batches < self.policy.max_batches:
                async with self.sessions() as db:
                    count = await AlertRepository(db).purge_observations(
                        retention_days=self.policy.retention_days, batch_size=self.policy.batch_size)
                batches += 1
                deleted += count
                if count < self.policy.batch_size:
                    break
        result = {"deleted": deleted, "batches": batches, "retention_days": self.policy.retention_days}
        if deleted:
            logger.info("alert_observation_retention", **result)
        return result
