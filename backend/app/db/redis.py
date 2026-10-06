"""NANFO Backend — Redis async client.

Redis serves multiple roles (database.md §1, ADR-005):
  - Session cache / JWT deny-list (Identity module)
  - Rate limiting (API Gateway)
  - Event Bus via Redis Streams (auth.stream, network.stream, org.stream)
  - WebSocket subscription sets (ws:subs:topology:{network_id})
  - Distributed idempotency locks

Connection policy (ADR-028): bounded connect/read deadlines (the read deadline
exceeds the 2 s XREADGROUP BLOCK), periodic health checks and a *blocking* pool
whose acquisition timeout surfaces exhaustion as a Redis ConnectionError instead
of an unbounded wait. Commands are never retried blindly: a retried XADD could
append a domain event twice. Blocking stream reads use a separate pool so they
cannot starve request-path commands.

Authentication (C24): ``Settings.REDIS_URL`` carries the ACL user when
``REDIS_USERNAME`` is set (deployments disable the ``default`` user); without it
clients authenticate as ``default`` with the password, as before.
"""

import redis.asyncio as aioredis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: aioredis.Redis | None = None
_stream_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    """Return the shared async Redis client."""
    if _client is None:
        raise RuntimeError("Redis client not initialised. Call init_redis() at application startup.")
    return _client


def get_stream_redis_client() -> aioredis.Redis | None:
    """Client reserved for blocking stream reads; None until init_redis() runs."""
    return _stream_client


def client_options(settings, *, max_connections: int) -> dict:
    """Pool/connection keyword arguments shared by both clients (testable)."""
    return {
        "encoding": "utf-8",
        "decode_responses": True,
        "max_connections": max_connections,
        "timeout": settings.REDIS_POOL_TIMEOUT_SECONDS,
        "socket_connect_timeout": settings.REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        "socket_timeout": settings.REDIS_SOCKET_TIMEOUT_SECONDS,
        "health_check_interval": settings.REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
        "retry_on_timeout": False,
        "retry": Retry(NoBackoff(), 0),
    }


def build_client(settings, *, max_connections: int) -> aioredis.Redis:
    pool = aioredis.BlockingConnectionPool.from_url(
        settings.REDIS_URL, **client_options(settings, max_connections=max_connections),
    )
    return aioredis.Redis.from_pool(pool)


async def init_redis() -> None:
    """Create the Redis connection pools and verify connectivity."""
    global _client, _stream_client
    settings = get_settings()
    _client = build_client(settings, max_connections=settings.REDIS_MAX_CONNECTIONS)
    _stream_client = build_client(settings, max_connections=settings.REDIS_STREAM_MAX_CONNECTIONS)
    # Verify connectivity
    await _client.ping()
    # The ACL user name is not a secret; it identifies NOAUTH/WRONGPASS misconfiguration.
    logger.info("redis_connected", host=settings.REDIS_HOST, port=settings.REDIS_PORT,
                acl_user=settings.REDIS_USERNAME or "default")


async def close_redis() -> None:
    """Close both Redis connection pools gracefully."""
    global _client, _stream_client
    clients, _client, _stream_client = (_client, _stream_client), None, None
    closed = False
    for client in clients:
        if client is not None:
            try:
                await client.aclose()
                closed = True
            except Exception as exc:  # noqa: BLE001 - shutdown must continue
                logger.warning("redis_close_failed", error_type=type(exc).__name__)
    if closed:
        logger.info("redis_closed")
