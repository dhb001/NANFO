"""Integration test conftest — mocks all external service connections.

The FastAPI lifespan in main.py tries to connect to real Redis and Neo4j.
Integration tests run without infrastructure, so all init/close functions
are patched with AsyncMocks at the test session level.

The FakeAsyncRedis instance from this conftest is also used as the return
value of get_redis_client() so that the consumer startup code in the lifespan
receives a working in-memory Redis, not None.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest

# ── Shared fake Redis for the whole session ───────────────────────────────────
_FAKE_REDIS = fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def mock_app_lifespan():
    """Prevent app lifespan from connecting to real Redis or Neo4j.

    Patches:
    - init_redis / close_redis         → AsyncMock (no-op)
    - init_neo4j / close_neo4j         → AsyncMock (no-op)
    - ensure_consumer_groups           → AsyncMock (no-op)
    - run_consumer_loop                → AsyncMock (yields immediately)
    - get_redis_client                 → returns _FAKE_REDIS
    """
    with (
        patch("app.main.init_redis", AsyncMock()),
        patch("app.main.init_neo4j", AsyncMock()),
        patch("app.main.close_redis", AsyncMock()),
        patch("app.main.close_neo4j", AsyncMock()),
        patch("app.main.ensure_consumer_groups", AsyncMock()),
        patch("app.main.run_consumer_loop", AsyncMock()),
        patch("app.main.get_redis_client", return_value=_FAKE_REDIS),
    ):
        yield


@pytest.fixture
def integration_fake_redis() -> fakeredis.FakeAsyncRedis:
    """Return the shared integration fake Redis instance."""
    return _FAKE_REDIS
