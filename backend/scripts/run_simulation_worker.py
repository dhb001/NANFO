"""Run the independent ADR-017 modeled simulation worker. No lab integration."""

import argparse
import asyncio

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.postgres import AsyncSessionLocal
from app.modules.simulation.worker import SimulationWorker


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-ticks", type=int, choices=range(1, 33), default=8)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    worker = SimulationWorker(
        sessions=AsyncSessionLocal, redis=redis, batch_ticks=args.batch_ticks
    )
    try:
        while True:
            busy = await worker.run_one()
            try:
                for _ in range(16):
                    if not await worker.publish_one():
                        break
            except Exception:  # noqa: BLE001 - durable outbox retries without stopping evaluation
                get_logger(__name__).warning("simulation_outbox_deferred")
            if args.once:
                break
            await asyncio.sleep(0.05 if busy else 0.5)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
