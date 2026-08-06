"""NANFO Backend — pytest configuration and shared fixtures.

Environment variables are set BEFORE any app module is imported so that
the lazy engine in app/db/postgres.py picks them up correctly.
"""

# ── Must be FIRST: set test env vars before any app import ───────────────────
import os

os.environ.update({
    "APP_ENV": "test",
    "LOG_LEVEL": "WARNING",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": "nanfo_test",
    "POSTGRES_PASSWORD": "nanfo_test",
    "POSTGRES_DB": "nanfo_test",
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "nanfo_test",
    "REDIS_HOST": "localhost",
    "REDIS_PORT": "6379",
    "REDIS_PASSWORD": "nanfo_test",
    "REDIS_DB": "1",
    "JWT_SECRET_KEY": "test-secret-key-32-chars-minimum!",
    "JWT_ALGORITHM": "HS256",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": "15",
    "JWT_REFRESH_TOKEN_EXPIRE_DAYS": "30",
    "RATE_LIMIT_LOGIN_MAX_ATTEMPTS": "5",
    "RATE_LIMIT_LOGIN_WINDOW_SECONDS": "60",
})

# ── Standard imports (after env vars are set) ─────────────────────────────────
import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import create_access_token, hash_password

# Configure structlog at WARNING level for all unit tests.
# Must run before any logger is first used to avoid the 'PrintLogger has no .name'
# AttributeError raised by structlog.stdlib.add_logger_name.
configure_logging("WARNING")


@pytest.fixture(scope="session")
def settings():
    """Return a cached Settings instance using test environment variables."""
    from app.core.config import get_settings
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def fake_redis() -> fakeredis.FakeAsyncRedis:
    """Return an isolated in-memory async Redis instance for each test."""
    return fakeredis.FakeAsyncRedis(decode_responses=True)


@pytest.fixture
def mock_db() -> AsyncMock:
    """Return a mock SQLAlchemy session for unit tests.

    session.add() and session.expunge() are synchronous in SQLAlchemy 2.0 —
    they must use MagicMock (not AsyncMock) to avoid 'coroutine never awaited' warnings.
    """
    db = AsyncMock()
    db.add = MagicMock()           # synchronous in SQLAlchemy 2.0
    db.expunge = MagicMock()       # synchronous
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
def test_user_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def test_org_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def test_workspace_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def test_network_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def valid_access_token(test_user_id) -> tuple[str, str]:
    """Return (access_token, jti) for a test user with Admin role."""
    token, jti = create_access_token(
        user_id=test_user_id,
        email="test@example.com",
        roles=["Admin"],
        permissions=["write:config", "read:topology", "read:telemetry"],
    )
    return token, jti


@pytest.fixture
def auth_headers(valid_access_token) -> dict:
    """Return Authorization headers for test requests."""
    token, _ = valid_access_token
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def readonly_access_token(test_user_id) -> tuple[str, str]:
    """Return (access_token, jti) for a read-only test user."""
    token, jti = create_access_token(
        user_id=test_user_id,
        email="readonly@example.com",
        roles=["Read-Only"],
        permissions=["read:topology", "read:telemetry"],
    )
    return token, jti
