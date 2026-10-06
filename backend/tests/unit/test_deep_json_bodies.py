"""ADR-028 C2 regression: deeply nested JSON bodies never produce a 500.

Verified with FastAPI 0.135.4 / Python 3.12: ``json.loads`` raises ``RecursionError``
beyond ~10k nesting levels, which FastAPI's body parser turns into
``HTTPException(400, "There was an error parsing the body")``; the platform handler
wraps it in the standard envelope. Parseable depths reach schema validation and get
``422 VALIDATION_ERROR`` whose ``details`` carry only ``{loc, type}`` — the (deep)
input is never serialized, so the error handler cannot recurse either. No platform
change was needed; these cases pin the behaviour across framework upgrades.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db, get_redis
from app.main import app
from tests.auth_support import create_session_access_token

VALIDATE_ENDPOINTS = ("/api/v1/intents/validate", "/api/v1/simulations/start", "/api/v1/plugins/install",
                      "/api/v1/auth/login")
UNPARSEABLE = {
    "open_arrays_200k": "[" * 200_000,
    "closed_arrays_200k": "[" * 200_000 + "]" * 200_000,
    "objects_100k": '{"a":' * 100_000 + "1" + "}" * 100_000,
}


@pytest.fixture
def client(session_auth):
    database = AsyncMock()

    async def _redis():
        yield session_auth.redis

    async def _db():
        yield database

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def _headers() -> dict[str, str]:
    token, _ = create_session_access_token(
        user_id=str(uuid.uuid4()), email="deep-json@example.com", roles=["Admin"],
        permissions=["read:telemetry", "read:topology", "write:config"],
    )
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _assert_envelope(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text[:300]
    body = response.json()
    assert body["success"] is False and body["data"] is None
    assert body["errors"]["code"] == code and isinstance(body["errors"]["message"], str)
    assert body["meta"]["request_id"]
    text = response.text
    for leaked in ("Traceback", "RecursionError", "recursion", "[[[["):
        assert leaked not in text
    return body


@pytest.mark.parametrize("path", VALIDATE_ENDPOINTS)
@pytest.mark.parametrize("name", sorted(UNPARSEABLE))
def test_nesting_beyond_the_parser_limit_is_a_400_envelope(client, path, name):
    body = UNPARSEABLE[name].encode()
    assert len(body) <= 1024 * 1024  # inside the default body limit: the parser, not the size, rejects it
    response = client.post(path, content=body, headers=_headers())
    _assert_envelope(response, 400, "BAD_REQUEST")


@pytest.mark.parametrize("path", VALIDATE_ENDPOINTS)
@pytest.mark.parametrize("depth", [900, 5_000, 9_000])
def test_parseable_deep_bodies_fail_validation_with_a_422_envelope(client, path, depth):
    response = client.post(path, content=("[" * depth + "]" * depth).encode(), headers=_headers())
    body = _assert_envelope(response, 422, "VALIDATION_ERROR")
    assert body["errors"]["details"] == [{"loc": ["body"], "type": "model_attributes_type"}]


@pytest.mark.parametrize("depth", [11, 900, 9_000])
def test_deep_intent_documents_are_rejected_before_any_service_work(client, depth):
    deep = "[" * depth + "]" * depth
    body = ('{"workspace_id":"%s","network_id":"%s","intent":{"action":"reroute","parameters":%s}}'
            % (uuid.uuid4(), uuid.uuid4(), deep))
    response = client.post("/api/v1/intents/validate", content=body.encode(),
                           headers={**_headers(), "Idempotency-Key": "deep-json-regression"})
    envelope = _assert_envelope(response, 422, "VALIDATION_ERROR")
    assert {"loc": ["body", "intent"], "type": "value_error"} in envelope["errors"]["details"]


def test_deep_bodies_are_rejected_before_authentication(client):
    # Body parsing precedes dependency resolution; no token is needed to get the envelope,
    # and none of the failure paths fall through to the 500 handler.
    response = client.post("/api/v1/intents/validate", content=UNPARSEABLE["closed_arrays_200k"].encode(),
                           headers={"Content-Type": "application/json"})
    _assert_envelope(response, 400, "BAD_REQUEST")
