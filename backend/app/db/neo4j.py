"""NANFO Backend — Neo4j async driver wrapper.

Per ADR-002: Neo4j stores semantic topology and multi-hop graph dependencies.
The Network module is the exclusive writer; Topology Query Service is the reader.
Both operate within the same module boundary — no cross-module Neo4j access.

Deadlines (ADR-028): connect, pool acquisition and managed-transaction retry are
bounded so an unreachable graph surfaces as ServiceUnavailable (HTTP 503) instead
of blocking request workers for the driver defaults (30 s / 60 s / 30 s).
"""

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_driver: AsyncDriver | None = None


def get_neo4j_driver() -> AsyncDriver:
    """Return the shared Neo4j async driver. Call init_neo4j() at startup first."""
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialised. Call init_neo4j() at application startup.")
    return _driver


def driver_options(settings) -> dict:
    return {
        "connection_timeout": settings.NEO4J_CONNECTION_TIMEOUT_SECONDS,
        "connection_acquisition_timeout": settings.NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS,
        "max_transaction_retry_time": settings.NEO4J_MAX_TRANSACTION_RETRY_TIME_SECONDS,
        "max_connection_pool_size": settings.NEO4J_MAX_CONNECTION_POOL_SIZE,
    }


async def init_neo4j() -> None:
    """Initialise the Neo4j async driver and verify connectivity."""
    global _driver
    settings = get_settings()
    _driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URI,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        **driver_options(settings),
    )
    await _driver.verify_connectivity()
    logger.info("neo4j_connected")


async def close_neo4j() -> None:
    """Close the Neo4j driver gracefully on application shutdown."""
    global _driver
    if _driver is not None:
        driver, _driver = _driver, None
        await driver.close()
        logger.info("neo4j_closed")
