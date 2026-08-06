"""NANFO Backend — Redis async client.

Redis serves multiple roles (database.md §1, ADR-005):
  - Session cache / JWT deny-list (Identity module)
  - Rate limiting (API Gateway)
  - Event Bus via Redis Streams (auth.stream, network.stream, org.stream)
  - WebSocket subscription sets (ws:subs:topology:{network_id})
  - Distributed idempotency locks
"""

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    """Return the shared async Redis client."""
    if _client is None:
        raise RuntimeError("Redis client not initialised. Call init_redis() at application startup.")
    return _client


async def init_redis() -> None:
    """Create the Redis connection pool and verify connectivity."""
    global _client
    settings = get_settings()
    _client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
    )
    # Verify connectivity
    await _client.ping()
    logger.info("redis_connected", host=settings.REDIS_HOST, port=settings.REDIS_PORT)


async def close_redis() -> None:
    """Close the Redis connection pool gracefully."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("redis_closed")
