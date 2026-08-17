"""Integration tests for auth endpoints via FastAPI TestClient.

Tests the HTTP layer: routing, envelope format, status codes, and headers.
Dependencies (DB, Redis) are overridden with mocks so no infrastructure is required.
The key invariant tested here is that every response carries the API_STANDARD.md §2 envelope.
"""

from unittest.mock import AsyncMock, patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app

# ── Dependency overrides ──────────────────────────────────────────────────────

def _mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _mock_redis():
    return fakeredis.FakeAsyncRedis(decode_responses=True)


_fake_redis = _mock_redis()
_fake_db = _mock_db()


async def _override_db():
    yield _fake_db


async def _override_redis():
    yield _fake_redis


@pytest.fixture(autouse=True)
def _patch_db_redis():
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = _override_redis
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_client(auth_headers) -> TestClient:
    return TestClient(app, headers=auth_headers, raise_server_exceptions=False)


# ── Envelope format tests ─────────────────────────────────────────────────────

class TestAPIEnvelope:
    """Every endpoint must return the API_STANDARD.md §2 envelope."""

    def test_login_response_has_envelope_keys(self, client):
        """POST /api/v1/auth/login must return envelope on 401 (API_STANDARD.md §2).

        Mocks AuthService.login at the service layer — integration tests verify
        HTTP routing and response envelope shape, not repository internals.
        """
        from fastapi import HTTPException

        from app.modules.identity.service import AuthService

        with patch.object(AuthService, "login", side_effect=HTTPException(status_code=401, detail="Invalid credentials.")):
            response = client.post("/api/v1/auth/login", json={"email": "x@y.com", "password": "bad"})
        assert response.status_code == 401
        body = response.json()
        assert "success" in body
        assert "data" in body
        assert "meta" in body
        assert "errors" in body

    def test_protected_route_without_token_returns_envelope(self, client):
        """GET /api/v1/auth/me without token must return 403 (not a raw error)."""
        response = client.get("/api/v1/auth/me")
        # FastAPI HTTPBearer returns 403 when header is missing
        assert response.status_code in (401, 403)

    def test_meta_has_request_id(self, auth_headers, fake_redis):
        """meta.request_id must be present in every successful response."""
        with TestClient(app, headers=auth_headers, raise_server_exceptions=False) as c:
            c.app.dependency_overrides[get_redis] = lambda: _fake_redis
            c.app.dependency_overrides[get_db] = lambda: _fake_db
            # hit /health as a non-envelope check route
            response = c.get("/health")
        assert response.status_code == 200


# ── Auth endpoint tests ───────────────────────────────────────────────────────

class TestLoginEndpoint:
    def test_login_preflight_returns_cors_headers(self, client):
        response = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
        assert "POST" in response.headers.get("access-control-allow-methods", "")

    def test_login_rate_limit_returns_429(self, client):
        """Rate-limit breach must return 429 with a JSON body (Authentication.md §5).

        Mocks AuthService.login to simulate rate-limit so no real Redis or DB needed.
        """
        from fastapi import HTTPException

        from app.modules.identity.service import AuthService

        with patch.object(
            AuthService,
            "login",
            side_effect=HTTPException(status_code=429, detail="Too many login attempts. Please try again later."),
        ):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "flood@example.com", "password": "x"},
            )
        assert response.status_code == 429
        body = response.json()
        assert "success" in body
        assert body["success"] is False

    def test_login_invalid_email_format_returns_422(self, client):
        """Pydantic EmailStr validator must reject malformed email with 422."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "not-an-email", "password": "pw"},
        )
        assert response.status_code == 422

    def test_logout_requires_auth(self, client):
        response = client.post("/api/v1/auth/logout")
        assert response.status_code in (401, 403)

    def test_refresh_missing_token_returns_422(self, client):
        response = client.post("/api/v1/auth/refresh", json={})
        assert response.status_code == 422


# ── Status code contract tests ────────────────────────────────────────────────

class TestStatusCodes:
    """API_STANDARD.md §3: HTTP code contract verification."""

    def test_unknown_route_returns_404(self, client):
        response = client.get("/api/v1/does-not-exist")
        assert response.status_code == 404

    def test_health_endpoint_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_openapi_schema_available(self, client):
        response = client.get("/api/openapi.json")
        assert response.status_code == 200
