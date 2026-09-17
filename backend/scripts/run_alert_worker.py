"""Publish the ADR019 Alert lifecycle outbox. No collector or heavy work."""

import argparse
import asyncio

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.runtime_health import worker_iteration
from app.db.postgres import AsyncSessionLocal
from app.modules.alert.repository import AlertRepository


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Drain at most 32 events then exit")
    args = parser.parse_args()
    redis = Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    try:
        while True:
            try:
                async with worker_iteration("outbox"):
                    for _ in range(32):
                        async with AsyncSessionLocal() as db:
                            if not await AlertRepository(db).publish_one(redis):
                                break
            except Exception:  # noqa: BLE001 - uncommitted outbox rows remain retryable
                get_logger(__name__).warning("alert_outbox_deferred")
                if args.once:
                    raise
            if args.once:
                break
            await asyncio.sleep(0.5)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
