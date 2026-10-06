"""Independent ADR019 report rendering and outbox worker. No lab integration.

ADR-028: one poisoned or transient iteration never stops the loop. The failing
job keeps its lease until expiry (natural backoff), ``claim_attempts`` bounds its
redelivery (``REPORTS_MAX_CLAIM_ATTEMPTS``, then terminal ``attempts_exhausted``)
and consecutive iteration failures back off exponentially with jitter.
"""

import argparse
import asyncio
import random

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.runtime_health import worker_iteration
from app.db.postgres import AsyncSessionLocal
from app.modules.report.worker import ReportWorker

MAX_BACKOFF_SECONDS = 30.0


def iteration_delay(*, busy, failures, rng=random.random):
    """Idle/busy polling cadence; capped exponential backoff with jitter on failures."""
    if failures:
        return min(MAX_BACKOFF_SECONDS, 0.5 * 2 ** min(failures - 1, 6)) * (0.5 + rng() / 2)
    return 0.05 if busy else 0.5


async def run(worker, *, once=False, iterations=None, sleep=asyncio.sleep, logger=None):
    """Worker loop; ``iterations`` bounds the loop (None runs until cancelled)."""
    logger = logger or get_logger(__name__)
    failures, completed = 0, 0
    while iterations is None or completed < iterations:
        completed += 1
        busy = False
        try:
            async with worker_iteration("report"):
                busy = await worker.run_one()
            failures = 0
        except Exception as exc:  # noqa: BLE001 - isolate the iteration; claim_attempts bounds retries
            failures += 1
            # Type only: exception text may contain snapshot or storage details.
            logger.warning("report_iteration_failed", error_type=type(exc).__name__,
                           consecutive_failures=failures)
            if once:
                raise
        try:
            async with worker_iteration("outbox"):
                for _ in range(16):
                    if not await worker.publish_one():
                        break
        except Exception:  # noqa: BLE001 - persisted events retry after Redis recovers
            logger.warning("report_outbox_deferred")
        try:
            await worker.maintain()
        except Exception as exc:  # noqa: BLE001 - storage maintenance retries next interval
            logger.warning("report_maintenance_deferred", error_type=type(exc).__name__)
        if once:
            break
        await sleep(iteration_delay(busy=busy, failures=failures))


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    redis = Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    worker = ReportWorker(sessions=AsyncSessionLocal, redis=redis)
    try:
        await run(worker, once=args.once)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
