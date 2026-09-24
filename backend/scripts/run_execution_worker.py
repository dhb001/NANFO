"""Unprivileged ADR-010 worker. Run from backend with PYTHONPATH=..:."""

import asyncio

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.watchdog import watchdog_guard
from app.db.postgres import AsyncSessionLocal, get_engine
from app.modules.intent.worker import ExecutionWorker


async def main():
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    # Mode disables new dispatch in prepare_plan, never recovery/compensation.
    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        # ADR-028: a blocked event loop exits (code 70) so the restart policy restarts it.
        async with watchdog_guard("execution-worker", settings):
            await ExecutionWorker(settings=settings, sessions=AsyncSessionLocal, redis=redis).run()
    finally:
        await redis.aclose()
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
