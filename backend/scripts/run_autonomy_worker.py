"""Operator-started ADR-012 I/O worker. Never starts training or an emulation lab."""

import asyncio

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.postgres import AsyncSessionLocal, get_engine
from app.modules.autonomy.worker import AutonomyWorker


async def main():
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await AutonomyWorker(sessions=AsyncSessionLocal, redis=redis).run()
    finally:
        await redis.aclose()
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
