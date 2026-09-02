"""Integration tests for global error envelope handlers in app.main."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import fakeredis
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.core.security import create_access_token
from app.main import app


@pytest.fixture
def client() -> TestClient:
    fake_r = fakeredis.FakeAsyncRedis(decode_responses=True)
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
        permissions=["read:telemetry"],
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
    assert response.headers.get("access-control-allow-credentials") == "true"
