"""ADR027 HTTP regressions using signed JWTs and isolated fakeredis sessions."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_db, get_redis
from app.core.security import decode_token
from app.main import app
from app.modules.identity.repository import AuditLogRepository, UserRepository
from app.modules.identity.service import AuthService
from app.modules.identity.sessions import SessionRepository


@pytest.fixture
async def identity_client(mock_db, fake_redis, monkeypatch):
    user = SimpleNamespace(user_id=uuid.UUID(int=27), email="identity@example.com",
                           is_active=True, hashed_password="unused", display_name="Identity")
    monkeypatch.setattr(UserRepository, "get_by_email", AsyncMock(return_value=user))
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(return_value=user))
    monkeypatch.setattr(UserRepository, "get_roles_for_user", AsyncMock(return_value=["Admin"]))
    monkeypatch.setattr(UserRepository, "get_permissions_for_roles", AsyncMock(return_value=["read:topology"]))
    monkeypatch.setattr("app.modules.identity.service.verify_password", lambda plain, hashed: plain == "correct")
    audit = AsyncMock()
    monkeypatch.setattr(AuditLogRepository, "append", audit)
    published = AsyncMock()
    monkeypatch.setattr("app.modules.identity.service.publish_event", published)
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url="http://test") as client:
            yield client, audit, published
    finally:
        app.dependency_overrides.clear()


async def login(client, request_id, password="correct"):
    return await client.post("/api/v1/auth/login", headers={"X-Request-ID": request_id},
                             json={"email": "identity@example.com", "password": password})


@pytest.mark.parametrize("request_id", ["req_adr027/login", str(uuid.UUID(int=27))])
@pytest.mark.parametrize("outcome", ["success", "invalid", "rate_limit"])
async def test_login_outcomes(identity_client, fake_redis, request_id, outcome):
    client, audit, published = identity_client
    if outcome == "rate_limit":
        await fake_redis.set("ratelimit:login:email:identity@example.com", "5", ex=60)
    response = await login(client, request_id, "wrong" if outcome == "invalid" else "correct")
    assert response.status_code == {"success": 200, "invalid": 401, "rate_limit": 429}[outcome]
    assert response.json()["meta"]["request_id"] == request_id
    assert response.json()["meta"]["timestamp"]
    row = audit.await_args.kwargs
    expected = (uuid.UUID(request_id) if request_id[0].isdigit() else
                uuid.uuid5(uuid.NAMESPACE_URL, f"nanfo:audit-correlation:{request_id}"))
    assert row["correlation_id"] == expected
    assert row["metadata"]["ip_address"] == "127.0.0.1"
    if request_id.startswith("req_"):
        assert row["metadata"]["request_id"] == request_id
    else:
        assert "request_id" not in row["metadata"]
    if outcome != "success":
        assert row["metadata"]["reason"] == ("rate_limited" if outcome == "rate_limit" else "invalid_credentials")
    if outcome != "rate_limit":
        assert published.await_args.kwargs["correlation_id"] == request_id


@pytest.mark.parametrize("termination", ["replay", "logout"])
async def test_opaque_refresh_and_family_revocation(identity_client, fake_redis, termination):
    client, audit, _ = identity_client
    # A UUID login isolates the original post-rotation refresh failure.
    response = await login(client, str(uuid.UUID(int=27)))
    assert response.status_code == 200
    pair = response.json()["data"]
    old = decode_token(pair["refresh_token"], token_type="refresh")
    response = await client.post("/api/v1/auth/refresh", headers={"X-Request-ID": "req_refresh/27"},
                                 json={"refresh_token": pair["refresh_token"]})
    assert response.status_code == 200
    rotated = response.json()["data"]
    new = decode_token(rotated["refresh_token"], token_type="refresh")
    assert new["sid"] == old["sid"] and new["exp"] == old["exp"]
    assert new["jti"] != old["jti"]
    entry = json.loads(await fake_redis.get(SessionRepository.key(old["sid"])))
    assert entry["refresh_jti"] == new["jti"]
    assert audit.await_args.kwargs["metadata"]["request_id"] == "req_refresh/27"
    for tokens in (pair, rotated):
        assert (await client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {tokens['access_token']}"})).status_code == 200
    if termination == "replay":
        response = await client.post("/api/v1/auth/refresh", headers={"X-Request-ID": "req_replay/27"},
                                     json={"refresh_token": pair["refresh_token"]})
        assert response.status_code == 401
    else:
        response = await client.post("/api/v1/auth/logout", headers={
            "Authorization": f"Bearer {rotated['access_token']}", "X-Request-ID": "req_logout/27"})
        assert response.status_code == 200
        assert audit.await_args.kwargs["metadata"]["request_id"] == "req_logout/27"
        assert audit.await_args.kwargs["metadata"]["jti"] == decode_token(rotated["access_token"])["jti"]
    assert not await fake_redis.exists(SessionRepository.key(old["sid"]))
    for tokens in (pair, rotated):
        assert (await client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {tokens['access_token']}"})).status_code == 401
        assert (await client.post("/api/v1/auth/refresh", headers={"X-Request-ID": "req_denied"},
                                  json={"refresh_token": tokens["refresh_token"]})).status_code == 401


@pytest.mark.parametrize("operation", ["login", "refresh", "logout"])
async def test_invalid_header_has_no_auth_side_effects(identity_client, fake_redis, mock_db, operation):
    client, audit, published = identity_client
    response = await login(client, str(uuid.UUID(int=27)))
    pair = response.json()["data"]
    claims = decode_token(pair["access_token"])
    session_key = SessionRepository.key(claims["sid"])
    before = await fake_redis.get(session_key)
    audit.reset_mock()
    published.reset_mock()
    mock_db.commit.reset_mock()
    headers = {"X-Request-ID": "x" * 129, "Authorization": f"Bearer {pair['access_token']}"}
    payload = ({"email": "identity@example.com", "password": "correct"} if operation == "login" else
               {"refresh_token": pair["refresh_token"]})
    response = await client.post(f"/api/v1/auth/{operation}", headers=headers, json=payload)
    assert response.status_code == 400
    assert response.json()["errors"]["code"] == "REQUEST_ID_INVALID"
    assert await fake_redis.get(session_key) == before
    assert await fake_redis.get("ratelimit:login:email:identity@example.com") == "1"
    audit.assert_not_awaited()
    published.assert_not_awaited()
    mock_db.commit.assert_not_awaited()
    # Rejection did not consume the token: a valid opaque retry still rotates it.
    response = await client.post("/api/v1/auth/refresh", headers={"X-Request-ID": "req_valid_retry"},
                                 json={"refresh_token": pair["refresh_token"]})
    assert response.status_code == 200


@pytest.mark.parametrize("operation", ["login", "refresh", "logout"])
async def test_direct_auth_boundary_validates_before_storage(mock_db, fake_redis, operation):
    svc = AuthService(mock_db, fake_redis)
    with pytest.raises(HTTPException) as error:
        if operation == "login":
            await svc.login("identity@example.com", "correct", "127.0.0.1", "x" * 129)
        elif operation == "refresh":
            await svc.refresh("unused", "x" * 129)
        else:
            await svc.logout("unused", 1, str(uuid.UUID(int=27)), "x" * 129, "unused")
    assert error.value.status_code == 400
    assert await fake_redis.keys("*") == []
    mock_db.commit.assert_not_awaited()


async def test_opaque_logout_without_refresh(identity_client, fake_redis):
    client, audit, _ = identity_client
    response = await login(client, str(uuid.UUID(int=27)))
    pair = response.json()["data"]
    claims = decode_token(pair["access_token"])
    response = await client.post("/api/v1/auth/logout", headers={
        "X-Request-ID": "req_logout_only", "Authorization": f"Bearer {pair['access_token']}"})
    assert response.status_code == 200
    assert response.json()["meta"]["request_id"] == "req_logout_only"
    assert audit.await_args.kwargs["metadata"] == {"jti": claims["jti"], "request_id": "req_logout_only"}
    assert not await fake_redis.exists(SessionRepository.key(claims["sid"]))
