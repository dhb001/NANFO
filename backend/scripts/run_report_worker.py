"""Independent ADR019 report rendering and outbox worker. No lab integration."""

import argparse
import asyncio

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.postgres import AsyncSessionLocal
from app.modules.report.worker import ReportWorker


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    redis = Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    worker = ReportWorker(sessions=AsyncSessionLocal, redis=redis)
    try:
        while True:
            busy = await worker.run_one()
            try:
                for _ in range(16):
                    if not await worker.publish_one():
                        break
            except Exception:  # noqa: BLE001 - persisted events retry after Redis recovers
                get_logger(__name__).warning("report_outbox_deferred")
            if args.once:
                break
            await asyncio.sleep(0.05 if busy else 0.5)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
