"""Publish the ADR021 Network inventory outbox using bounded, leased iterations."""

import argparse
import asyncio

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.runtime_health import worker_iteration
from app.db.postgres import AsyncSessionLocal
from app.modules.network.outbox import NetworkOutboxPublisher


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Attempt one bounded batch then exit")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--lease-seconds", type=float, default=30)
    parser.add_argument("--publish-timeout", type=float, default=5)
    parser.add_argument("--retry-base-seconds", type=float, default=1)
    parser.add_argument("--retry-max-seconds", type=float, default=300)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1024 or not 0 < args.poll_seconds <= 60:
        parser.error("batch-size must be 1..1024 and poll-seconds must be >0 and <=60")
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        try:
            publisher = NetworkOutboxPublisher(
                sessions=AsyncSessionLocal, redis=redis, lease_seconds=args.lease_seconds,
                publish_timeout=args.publish_timeout, retry_base_seconds=args.retry_base_seconds,
                retry_max_seconds=args.retry_max_seconds,
            )
        except ValueError as exc:
            parser.error(str(exc))
        while True:
            try:
                async with worker_iteration("outbox"):
                    await publisher.drain(limit=args.batch_size)
            except Exception:  # noqa: BLE001 - rows remain retryable after failure/timeout
                get_logger(__name__).warning("network_outbox_iteration_deferred")
                if args.once:
                    raise
            if args.once:
                break
            await asyncio.sleep(args.poll_seconds)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
