"""Publish the ADR019 Alert lifecycle outbox and purge expired observation receipts.

No collector or heavy work. ADR-028: each iteration also offers the interval-gated,
bounded observation-receipt retention (``ALERT_OBSERVATION_*`` settings, see
``app.modules.alert.retention``) a chance to run; a failing publish or purge never
stops the loop. ``--once`` drains at most 32 events and exits without maintenance.
"""

import argparse
import asyncio

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.runtime_health import worker_iteration
from app.db.postgres import AsyncSessionLocal
from app.modules.alert.repository import AlertRepository
from app.modules.alert.retention import ObservationRetention

PUBLISH_BATCH = 32
IDLE_SECONDS = 0.5


async def publish_batch(sessions, redis, *, limit=PUBLISH_BATCH) -> int:
    """Publish up to ``limit`` outbox events, one short transaction each."""
    published = 0
    for _ in range(limit):
        async with sessions() as db:
            if not await AlertRepository(db).publish_one(redis):
                break
        published += 1
    return published


async def run(*, sessions, redis, retention, once=False, iterations=None, sleep=asyncio.sleep, logger=None):
    """Worker loop; ``iterations`` bounds it for tests (None runs until cancelled)."""
    logger = logger or get_logger(__name__)
    completed = 0
    while iterations is None or completed < iterations:
        completed += 1
        try:
            async with worker_iteration("outbox"):
                await publish_batch(sessions, redis)
        except Exception:  # noqa: BLE001 - uncommitted outbox rows remain retryable
            logger.warning("alert_outbox_deferred")
            if once:
                raise
        if once:
            break
        try:
            await retention.maybe_purge()
        except Exception as exc:  # noqa: BLE001 - retention retries next interval
            logger.warning("alert_observation_retention_deferred", error_type=type(exc).__name__)
        await sleep(IDLE_SECONDS)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Drain at most 32 events then exit")
    args = parser.parse_args()
    redis = Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    try:
        await run(sessions=AsyncSessionLocal, redis=redis, retention=ObservationRetention(sessions=AsyncSessionLocal),
                  once=args.once)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
