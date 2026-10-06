"""ADR-028 C2: the whole-scene PUT has its own 8 MiB body bound; every other route keeps its limit.

The 1 MiB default capped real scenes near 3,000 objects although a scene may hold
10,000 (``spatial_schemas.MAX_OBJECTS``); ``PUT /api/v1/networks/{id}/spatial-scene``
is therefore bounded by ``API_MAX_SPATIAL_SCENE_BYTES`` (default 8 MiB).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.body_limit import DEFAULT_SPATIAL_SCENE_BYTES, BodyLimitMiddleware
from app.core.config import Settings
from app.core.dependencies import get_db, get_redis
from app.main import app
from tests.auth_support import create_session_access_token

MIB = 1024 * 1024
NETWORK = uuid.UUID(int=77)
SCENE = f"/api/v1/networks/{NETWORK}/spatial-scene"


def _middleware(**overrides) -> BodyLimitMiddleware:
    async def handler(request, exc):  # pragma: no cover - not invoked by limit_for
        raise AssertionError

    values = {"default_limit": MIB, "asset_limit": 12 * MIB, "error_handler": handler, **overrides}
    return BodyLimitMiddleware(object(), **values)


def test_scene_limit_defaults_to_eight_mib_in_code_and_settings():
    assert DEFAULT_SPATIAL_SCENE_BYTES == 8 * MIB
    assert _middleware().scene_limit == 8 * MIB
    assert Settings(_env_file=None).API_MAX_SPATIAL_SCENE_BYTES == 8 * MIB


@pytest.mark.parametrize(("method", "path", "expected"), [
    ("PUT", SCENE, 8 * MIB),
    ("PUT", SCENE + "/", 8 * MIB),
    ("GET", SCENE, MIB),
    ("POST", SCENE, MIB),
    ("PUT", SCENE + "/history", MIB),
    ("PUT", f"/api/v1/networks/{NETWORK}", MIB),
    ("PATCH", f"/api/v1/networks/{NETWORK}", MIB),
    ("PUT", f"/api/v1/networks/{NETWORK}/campus/buildings", MIB),
    ("POST", f"/api/v1/networks/{NETWORK}/campus/model-assets", 12 * MIB),
    ("PUT", f"/api/v1/networks/{NETWORK}/extra/spatial-scene", MIB),  # exact route only
])
def test_only_the_scene_put_gets_the_scene_limit(method, path, expected):
    assert _middleware().limit_for(method, path) == expected


def test_scene_limit_is_configurable_and_positive():
    assert _middleware(scene_limit=2 * MIB).limit_for("PUT", SCENE) == 2 * MIB
    with pytest.raises(ValueError):
        _middleware(scene_limit=0)
    for invalid in (1023, 64 * MIB + 1):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, API_MAX_SPATIAL_SCENE_BYTES=invalid)


@pytest.fixture
def client(session_auth):
    async def _redis():
        yield session_auth.redis

    async def _db():
        from unittest.mock import AsyncMock

        yield AsyncMock()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    token, _ = create_session_access_token(user_id=str(uuid.uuid4()), email="scene@example.com", roles=["Admin"],
                                           permissions=["read:topology", "write:config"])
    try:
        yield TestClient(app, raise_server_exceptions=False), {"Authorization": f"Bearer {token}",
                                                               "Content-Type": "application/json"}
    finally:
        app.dependency_overrides.clear()


def _body(size: int) -> bytes:
    return b"{" + b" " * (size - 2) + b"}"


def test_scene_put_above_the_default_reaches_the_route_and_above_eight_mib_is_413(client):
    http, headers = client
    response = http.put(SCENE, content=_body(3 * MIB), headers=headers)
    assert response.status_code != 413  # validated/authorized by the route, not the size gate
    response = http.put(SCENE, content=_body(8 * MIB + 1), headers=headers)
    assert response.status_code == 413 and response.json()["errors"]["code"] == "REQUEST_TOO_LARGE"


def test_streamed_scene_put_is_counted_against_the_scene_limit(client):
    http, headers = client

    def chunks(total):
        sent = 0
        while sent < total:
            size = min(65536, total - sent)
            sent += size
            yield b" " * size

    response = http.put(SCENE, content=chunks(8 * MIB + 65536), headers=headers)  # no Content-Length
    assert response.status_code == 413 and response.json()["errors"]["code"] == "REQUEST_TOO_LARGE"


def test_other_network_writes_keep_the_one_mib_default(client):
    http, headers = client
    response = http.patch(f"/api/v1/networks/{NETWORK}", content=_body(2 * MIB), headers=headers)
    assert response.status_code == 413 and response.json()["errors"]["code"] == "REQUEST_TOO_LARGE"
    response = http.post(SCENE, content=_body(2 * MIB), headers=headers)
    assert response.status_code == 413  # only PUT replaces a scene
