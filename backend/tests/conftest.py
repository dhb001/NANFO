"""NANFO Backend — pytest configuration and shared fixtures.

Environment variables are set BEFORE any app module is imported so that
the lazy engine in app/db/postgres.py picks them up correctly.
"""

# ── Must be FIRST: set test env vars before any app import ───────────────────
import os

os.environ.update({
    "APP_ENV": "test",
    "EXECUTION_MODE": "demo",
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
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import fakeredis
import pytest

from app.core.config import get_settings
from app.core.logging import configure_logging
from tests.auth_support import SessionIdentities, _current_identities

# Configure structlog at WARNING level for all unit tests.
# Must run before any logger is first used to avoid the 'PrintLogger has no .name'
# AttributeError raised by structlog.stdlib.add_logger_name.
configure_logging("WARNING")


# ── Private evidence gating (ADR-028) ────────────────────────────────────────
# Tests listed in tests/private_artifacts.txt read the ignored local evidence
# store. They are marked `private_artifacts`; when the store is absent they are
# skipped with an explicit reason instead of failing with FileNotFoundError.
_PRIVATE_ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "ai-engine" / "artifacts"
_PRIVATE_ARTIFACT_SENTINELS = (
    "adr014-001/train-06/checkpoint.ptz",
    "adr024-qualified-001/model",
)
_PRIVATE_ARTIFACT_REGISTRY = Path(__file__).with_name("private_artifacts.txt")


def _private_artifact_prefixes() -> tuple[str, ...]:
    lines = _PRIVATE_ARTIFACT_REGISTRY.read_text(encoding="utf-8").splitlines()
    return tuple(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))


def _private_artifacts_available() -> bool:
    return all((_PRIVATE_ARTIFACT_ROOT / sentinel).exists() for sentinel in _PRIVATE_ARTIFACT_SENTINELS)


def _matches_prefix(nodeid: str, prefix: str) -> bool:
    return nodeid == prefix or nodeid.startswith(prefix + "::") or nodeid.startswith(prefix + "[")


def pytest_collection_modifyitems(config, items):
    prefixes = _private_artifact_prefixes()
    available = _private_artifacts_available()
    skip = pytest.mark.skip(reason=f"private evidence store absent: {_PRIVATE_ARTIFACT_ROOT} (ADR-028)")
    for item in items:
        nodeid = item.nodeid
        index = nodeid.find("tests/")
        relative = nodeid[index:] if index >= 0 else nodeid
        if any(_matches_prefix(relative, prefix) for prefix in prefixes):
            item.add_marker(pytest.mark.private_artifacts)
            if not available:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def settings():
    """Return a cached Settings instance using test environment variables."""
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def execution_mode(monkeypatch):
    """Isolate mode changes and clear cached settings both before and after use."""
    def set_mode(mode):
        monkeypatch.setenv("EXECUTION_MODE", mode)
        get_settings.cache_clear()

    set_mode("demo")
    try:
        yield set_mode
    finally:
        get_settings.cache_clear()


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
def session_auth(monkeypatch):
    """Opt-in persistence fixtures, never an authentication dependency override."""
    from app.modules.identity.repository import UserRepository

    identities = SessionIdentities()
    context = _current_identities.set(identities)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(side_effect=identities.users.get))
    monkeypatch.setattr(UserRepository, "get_roles_for_user", AsyncMock(
        side_effect=lambda user: list(identities.roles[user.user_id]),
    ))
    monkeypatch.setattr(UserRepository, "get_permissions_for_roles", AsyncMock(
        side_effect=lambda roles: list(identities.permissions.get(tuple(roles), [])),
    ))
    yield identities
    _current_identities.reset(context)


@pytest.fixture
def tenant_auth(session_auth, monkeypatch):
    """Explicit organization persistence for contracts that exercise membership."""
    from types import SimpleNamespace

    from app.modules.organization.repository import (
        OrganizationRepository,
        OrgMemberRepository,
        WorkspaceRepository,
    )

    org = SimpleNamespace(org_id=session_auth.org_id, name="Test Org", slug="test-org", created_at=datetime.now(UTC))

    def list_orgs(user_id, *, page, page_size, org_id=None):
        rows = [org] if (org.org_id, user_id) in session_auth.memberships and org_id in (None, org.org_id) else []
        return rows[(page - 1) * page_size:page * page_size], len(rows)

    monkeypatch.setattr(OrganizationRepository, "get_by_id", AsyncMock(
        side_effect=lambda org_id: org if org_id == org.org_id else None,
    ))
    monkeypatch.setattr(OrganizationRepository, "list_for_user", AsyncMock(side_effect=list_orgs))
    monkeypatch.setattr(OrgMemberRepository, "get_member", AsyncMock(
        side_effect=lambda org_id, user_id: SimpleNamespace(org_role="Admin")
        if (org_id, user_id) in session_auth.memberships else None,
    ))
    monkeypatch.setattr(WorkspaceRepository, "get_by_id", AsyncMock(side_effect=session_auth.workspaces.get))
    return session_auth


@pytest.fixture
def valid_access_token(test_user_id, session_auth) -> tuple[str, str]:
    """Return (access_token, jti) for a test user with Admin role."""
    token, jti = session_auth.issue(
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
def readonly_access_token(test_user_id, session_auth) -> tuple[str, str]:
    """Return (access_token, jti) for a read-only test user."""
    token, jti = session_auth.issue(
        user_id=test_user_id,
        email="readonly@example.com",
        roles=["Read-Only"],
        permissions=["read:topology", "read:telemetry"],
    )
    return token, jti
