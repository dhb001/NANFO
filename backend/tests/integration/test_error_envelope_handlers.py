"""Integration tests for global error envelope handlers in app.main."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app
from tests.auth_support import create_session_access_token as create_access_token


@pytest.fixture
def client(session_auth) -> TestClient:
    fake_r = session_auth.redis
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    async def _redis():
        yield fake_r

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _make_token() -> str:
    token, _ = create_access_token(
        user_id=str(uuid.uuid4()),
        email="errors@example.com",
        roles=["Admin"],
        permissions=["read:telemetry", "read:topology", "write:config"],
    )
    return token


def test_validation_error_uses_canonical_envelope(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    response = client.post(
        "/api/v1/organizations",
        json={"slug": "valid-slug"},
        headers=headers,
    )

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert isinstance(body["meta"], dict)
    assert body["errors"]["code"] == "VALIDATION_ERROR"
    assert isinstance(body["errors"]["message"], str)


def test_http_exception_uses_canonical_envelope(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    with patch(
        "app.modules.simulation.service.SimulationStartService.get_simulation_detail",
        new=AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Simulation not found."),
        ),
    ):
        response = client.get(
            f"/api/v1/simulations/{uuid.uuid4()}",
            headers=headers,
        )

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert isinstance(body["meta"], dict)
    assert body["errors"]["code"] == "NOT_FOUND"


def test_unhandled_exception_uses_canonical_envelope(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    with patch(
        "app.modules.organization.service.OrgService.create_org",
        new=AsyncMock(side_effect=Exception("boom")),
    ):
        response = client.post(
            "/api/v1/organizations",
            json={"name": "Example", "slug": "example-org"},
            headers=headers,
        )

    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert isinstance(body["meta"], dict)
    assert body["errors"]["code"] == "INTERNAL_ERROR"


def test_unhandled_exception_includes_allowed_origin_cors_headers(client):
    headers = {
        "Authorization": f"Bearer {_make_token()}",
        "Origin": "http://127.0.0.1:5173",
    }
    with patch(
        "app.modules.organization.service.OrgService.create_org",
        new=AsyncMock(side_effect=Exception("boom")),
    ):
        response = client.post(
            "/api/v1/organizations",
            json={"name": "Example", "slug": "example-org"},
            headers=headers,
        )

    assert response.status_code == 500
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
    # ADR-028: bearer tokens only; a reflected origin must vary caches on Origin.
    assert response.headers.get("access-control-allow-credentials") is None
    assert "Origin" in response.headers.get("vary", "")


# ── ADR-028 C2: outages, oversize bodies, validation details, docs, CORS ─────

from neo4j.exceptions import ServiceUnavailable, SessionExpired  # noqa: E402
from redis.exceptions import ConnectionError as RedisConnectionError  # noqa: E402
from redis.exceptions import TimeoutError as RedisTimeoutError  # noqa: E402
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError, OperationalError  # noqa: E402
from sqlalchemy.exc import TimeoutError as PoolTimeoutError  # noqa: E402

from app.core.errors import DependencyUnavailableError  # noqa: E402

SECRET = "postgresql://user:secret-password@db"


@pytest.mark.parametrize("failure,retry_after", [
    (DependencyUnavailableError("redis", retry_after_seconds=9), "9"),
    (RedisConnectionError(SECRET), "5"), (RedisTimeoutError(SECRET), "5"),
    (OperationalError("SELECT", {}, Exception(SECRET)), "5"), (InterfaceError("SELECT", {}, Exception(SECRET)), "5"),
    (PoolTimeoutError(SECRET), "5"), (ServiceUnavailable(SECRET), "5"), (SessionExpired(SECRET), "5"),
    (DBAPIError("SELECT", {}, Exception(SECRET), connection_invalidated=True), "5"),
], ids=lambda value: type(value).__name__ if isinstance(value, Exception) else value)
def test_backing_service_outage_maps_to_503_with_retry_after(client, failure, retry_after):
    headers = {"Authorization": f"Bearer {_make_token()}", "Origin": "http://127.0.0.1:5173"}
    with patch("app.modules.organization.service.OrgService.create_org", new=AsyncMock(side_effect=failure)):
        response = client.post("/api/v1/organizations", json={"name": "Example", "slug": "example-org"},
                               headers=headers)
    assert response.status_code == 503
    assert response.headers["retry-after"] == retry_after
    body = response.json()
    assert body["success"] is False and body["data"] is None and body["meta"]["request_id"]
    assert body["errors"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert SECRET not in response.text and "redis" not in body["errors"]["message"].lower()
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"


def test_non_outage_database_error_stays_500(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    failure = IntegrityError("INSERT", {}, Exception(SECRET))
    with patch("app.modules.organization.service.OrgService.create_org", new=AsyncMock(side_effect=failure)):
        response = client.post("/api/v1/organizations", json={"name": "Example", "slug": "example-org"},
                               headers=headers)
    assert response.status_code == 500 and response.json()["errors"]["code"] == "INTERNAL_ERROR"
    assert SECRET not in response.text


def test_declared_oversize_body_rejected_before_routing(client):
    body = b"x" * (1024 * 1024 + 1)
    with patch("app.modules.organization.service.OrgService.create_org", new=AsyncMock()) as create:
        response = client.post("/api/v1/organizations", content=body,
                               headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1:5173"})
    assert response.status_code == 413
    assert response.json()["errors"]["code"] == "REQUEST_TOO_LARGE"
    assert response.json()["meta"]["request_id"] == response.headers["x-request-id"]
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
    create.assert_not_awaited()


def test_streamed_oversize_body_counted_without_content_length(client):
    def chunks():
        for _ in range(17):
            yield b"x" * 65536  # 1.06 MiB, no Content-Length (chunked)

    response = client.post("/api/v1/organizations", content=chunks(),
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413 and response.json()["errors"]["code"] == "REQUEST_TOO_LARGE"


def test_asset_upload_route_has_the_larger_limit(client):
    network_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {_make_token()}", "Content-Type": "application/json"}
    large = b"{" + b" " * (2 * 1024 * 1024) + b"}"
    response = client.post(f"/api/v1/networks/{network_id}/campus/model-assets", content=large, headers=headers)
    assert response.status_code != 413  # reaches validation/authorization (<= 12 MiB)
    too_large = b" " * (12 * 1024 * 1024 + 1)
    response = client.post(f"/api/v1/networks/{network_id}/campus/model-assets", content=too_large, headers=headers)
    assert response.status_code == 413
    response = client.patch(f"/api/v1/networks/{network_id}", content=large, headers=headers)
    assert response.status_code == 413  # other routes keep the 1 MiB default


def test_validation_errors_stay_422_with_location_details(client):
    headers = {"Authorization": f"Bearer {_make_token()}"}
    response = client.post("/api/v1/organizations", json={"slug": "valid-slug"}, headers=headers)
    assert response.status_code == 422
    details = response.json()["errors"]["details"]
    assert {"loc": ["body", "name"], "type": "missing"} in details
    assert all(set(item) == {"loc", "type"} for item in details)


def test_docs_routes_are_opt_in_but_schema_generation_always_works(monkeypatch):
    import app.main as main

    settings = main.get_settings().model_copy(update={"API_DOCS_ENABLED": False})
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    closed = main.create_app()
    assert closed.docs_url is None and closed.redoc_url is None and closed.openapi_url is None
    with TestClient(closed, raise_server_exceptions=False) as test_client:
        for path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
            assert test_client.get(path).status_code == 404
    assert closed.openapi()["paths"]
    assert app.openapi_url == "/api/openapi.json"  # test environment keeps docs enabled


def test_cors_preflight_uses_explicit_methods_and_headers(client):
    allowed = client.options("/api/v1/intents/validate", headers={
        "Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,idempotency-key,x-request-id",
    })
    assert allowed.status_code == 200
    assert allowed.headers.get("access-control-allow-credentials") is None
    assert "PATCH" in allowed.headers["access-control-allow-methods"]
    rejected = client.options("/api/v1/intents/validate", headers={
        "Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-unlisted-header",
    })
    assert rejected.status_code == 400
