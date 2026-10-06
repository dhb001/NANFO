"""Backing-service failure classification shared by HTTP, WebSocket and events (ADR-028).

* ``dependency_name`` recognises outages of PostgreSQL, Redis and Neo4j (and the
  explicit :class:`DependencyUnavailableError`). HTTP maps them to 503
  ``DEPENDENCY_UNAVAILABLE``; WebSockets to ``WS_UNAVAILABLE`` + close 1013.
* ``is_transient`` additionally covers generic transport faults. Event handlers
  failing transiently stay pending for reclaim instead of being dead-lettered.
* ``is_deterministic`` marks failures that no redelivery can fix.
"""

from __future__ import annotations

import asyncio

from neo4j.exceptions import ServiceUnavailable, SessionExpired, TransientError
from pydantic import ValidationError
from redis.exceptions import BusyLoadingError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import DBAPIError, DisconnectionError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.errors import DependencyUnavailableError, DeterministicEventError

_REDIS = (RedisConnectionError, RedisTimeoutError, BusyLoadingError)
_POSTGRES = (OperationalError, InterfaceError, PoolTimeoutError, DisconnectionError)
_NEO4J = (ServiceUnavailable, SessionExpired)


def dependency_name(exc: BaseException) -> str | None:
    """Name of the unavailable backing service, or None if ``exc`` is not an outage."""
    if isinstance(exc, DependencyUnavailableError):
        return exc.dependency
    if isinstance(exc, _REDIS):
        return "redis"
    if isinstance(exc, _POSTGRES):
        return "postgres"
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return "postgres"
    if isinstance(exc, _NEO4J):
        return "neo4j"
    return None


def is_transient(exc: BaseException) -> bool:
    """Outages and transport faults that a later redelivery may overcome."""
    return (
        dependency_name(exc) is not None
        or isinstance(exc, (TransientError, asyncio.TimeoutError, TimeoutError, ConnectionError, OSError))
    )


def is_deterministic(exc: BaseException) -> bool:
    """Failures inherent to the delivered event; redelivery cannot succeed."""
    if is_transient(exc):
        return False
    return isinstance(exc, (DeterministicEventError, ValidationError, KeyError, ValueError, TypeError))
