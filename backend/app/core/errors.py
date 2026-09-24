"""Shared, handler-mapped application errors (ADR-028).

Modules raise these instead of inventing ad-hoc status codes. The platform
exception handlers in ``app.main`` map them onto the standard envelope.
"""

from __future__ import annotations


class DependencyUnavailableError(Exception):
    """A required backing service (PostgreSQL, Redis, Neo4j, storage) is unavailable.

    Mapped to HTTP 503 ``DEPENDENCY_UNAVAILABLE`` with a ``Retry-After`` header.
    The ``dependency`` name is logged, never returned to clients.
    """

    def __init__(self, dependency: str, *, retry_after_seconds: int = 5) -> None:
        super().__init__(f"{dependency} unavailable")
        self.dependency = dependency
        self.retry_after_seconds = max(1, int(retry_after_seconds))


class RequestTooLargeError(Exception):
    """Request body exceeded the route's configured byte limit (HTTP 413)."""

    def __init__(self, limit_bytes: int) -> None:
        super().__init__("request body too large")
        self.limit_bytes = int(limit_bytes)


class DeterministicEventError(Exception):
    """An event can never succeed as delivered (bad payload, unsupported version).

    Event handlers raise this to request immediate dead-lettering instead of
    pending-entry redelivery (ADR-028 C14). The message is never persisted.
    """
