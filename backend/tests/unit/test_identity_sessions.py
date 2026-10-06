"""Real fakeredis transactions: rotation, replay grace, concurrency, logout and live RBAC."""

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError

from app.core.errors import DependencyUnavailableError
from app.core.security import create_refresh_token, decode_token
from app.modules.identity.service import AuthService
from app.modules.identity.sessions import SessionRepository


@pytest.fixture
async def login_session(mock_db, fake_redis):
    svc = AuthService(mock_db, fake_redis)
    user = SimpleNamespace(user_id=uuid.UUID(int=1), email="session@example.com", is_active=True,
                           hashed_password="unused")
    with (
        patch.object(svc._user_repo, "get_by_email", return_value=user),
        patch.object(svc._user_repo, "get_by_id", return_value=user),
        patch.object(svc._user_repo, "get_roles_for_user", return_value=["Admin"]),
        patch.object(svc._user_repo, "get_permissions_for_roles", return_value=["read:topology"]),
        patch("app.modules.identity.service.verify_password", return_value=True),
        patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
    ):
        pair = await svc.login(user.email, "password", "127.0.0.1", str(uuid.uuid4()))
        yield svc, pair, user


async def test_rotation_and_replay_revoke_entire_family(login_session, fake_redis):
    svc, pair, _ = login_session
    old = decode_token(pair.refresh_token, token_type="refresh")
    rotated = await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    new = decode_token(rotated.refresh_token, token_type="refresh")
    assert old["sid"] == new["sid"] == decode_token(rotated.access_token)["sid"]
    assert old["jti"] != new["jti"] and old["exp"] == new["exp"]
    entry = json.loads(await fake_redis.get(SessionRepository.key(old["sid"])))
    assert entry["refresh_jti"] == new["jti"]
    assert pair.refresh_token not in json.dumps(entry)
    assert 0 < await fake_redis.ttl(SessionRepository.key(old["sid"])) <= 30 * 86400
    await svc.authenticate_access(pair.access_token)
    # ADR-028 C9: an in-grace retry of the just-rotated token is idempotent.
    retried = await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    assert (retried.access_token, retried.refresh_token) == (rotated.access_token, rotated.refresh_token)
    await svc.authenticate_access(rotated.access_token)
    # Once the grace window has lapsed the same presentation is reuse.
    await fake_redis.delete(SessionRepository.rotation_key(pair.refresh_token))
    with pytest.raises(HTTPException):
        await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    for token in (pair.access_token, rotated.access_token):
        with pytest.raises(HTTPException):
            await svc.authenticate_access(token)
    with pytest.raises(HTTPException):
        await svc.refresh(rotated.refresh_token, str(uuid.uuid4()))


async def test_concurrent_refresh_within_grace_returns_one_pair(login_session):
    """C9: concurrent presentations of one token (two tabs, retried request) share one rotation."""
    svc, pair, _ = login_session
    results = await asyncio.gather(
        *(svc.refresh(pair.refresh_token, str(uuid.uuid4())) for _ in range(2)),
        return_exceptions=True,
    )
    assert not any(isinstance(result, BaseException) for result in results)
    assert results[0].refresh_token == results[1].refresh_token
    assert results[0].access_token == results[1].access_token
    await svc.authenticate_access(results[0].access_token)
    # The shared pair is the live head: its refresh token rotates normally.
    await svc.refresh(results[0].refresh_token, str(uuid.uuid4()))


async def test_refresh_logout_race_cannot_resurrect_session(login_session):
    svc, pair, _ = login_session
    claims = decode_token(pair.access_token)
    await asyncio.gather(
        svc.refresh(pair.refresh_token, str(uuid.uuid4())),
        svc.logout(jti=claims["jti"], exp=claims["exp"], sid=claims["sid"],
                   user_id=claims["sub"], correlation_id=str(uuid.uuid4())),
        return_exceptions=True,
    )
    with pytest.raises(HTTPException):
        await svc.authenticate_access(pair.access_token)


def _fail_pipelines_containing(fake_redis, command):
    """Fail only transactions that queue ``command`` (e.g. the session SET), like a lost connection."""
    pipeline_type = type(fake_redis.pipeline())
    execute = pipeline_type.execute

    async def failing(pipe, *args, **kwargs):
        if any(str(args_[0]).upper() == command for args_, _ in pipe.command_stack):
            raise ConnectionError("unavailable")
        return await execute(pipe, *args, **kwargs)

    return patch.object(pipeline_type, "execute", failing)


async def test_login_storage_failure_does_not_issue_pair(login_session, fake_redis):
    """ADR-028 C2: a session-store outage is 503 (DependencyUnavailableError), never a pair."""
    svc, _, user = login_session
    with _fail_pipelines_containing(fake_redis, "SET"), pytest.raises(DependencyUnavailableError):
        await svc.login(user.email, "password", "127.0.0.2", str(uuid.uuid4()))


async def test_logout_storage_failure_is_not_success(login_session, fake_redis):
    svc, pair, _ = login_session
    claims = decode_token(pair.access_token)
    with _fail_pipelines_containing(fake_redis, "DEL"), pytest.raises(DependencyUnavailableError):
        await svc.logout(jti=claims["jti"], exp=claims["exp"], sid=claims["sid"],
                         user_id=claims["sub"], correlation_id=str(uuid.uuid4()))
    # Nothing was revoked, and no success was reported.
    await svc.authenticate_access(pair.access_token)


async def test_session_user_binding_and_independent_logins(login_session, fake_redis):
    svc, pair, user = login_session
    independent = await svc.login(user.email, "password", "127.0.0.2", str(uuid.uuid4()))
    claims = decode_token(pair.access_token)
    key = SessionRepository.key(claims["sid"])
    entry = json.loads(await fake_redis.get(key))
    entry["user_id"] = str(uuid.UUID(int=99))
    await fake_redis.set(key, json.dumps(entry), exat=entry["exp"])
    with pytest.raises(HTTPException):
        await svc.authenticate_access(pair.access_token)
    await svc.authenticate_access(independent.access_token)


async def test_refresh_hash_mismatch_revokes_family(login_session, fake_redis):
    svc, pair, _ = login_session
    claims = decode_token(pair.access_token)
    key = SessionRepository.key(claims["sid"])
    entry = json.loads(await fake_redis.get(key))
    entry["refresh_hash"] = "mismatch"
    await fake_redis.set(key, json.dumps(entry), exat=entry["exp"])
    with pytest.raises(HTTPException):
        await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    assert not await fake_redis.exists(key)


async def test_validly_signed_unknown_refresh_jti_revokes_family(login_session):
    svc, pair, _ = login_session
    claims = decode_token(pair.access_token)
    token, _ = create_refresh_token(user_id=claims["sub"], sid=claims["sid"])
    with pytest.raises(HTTPException):
        await svc.refresh(token, str(uuid.uuid4()))
    with pytest.raises(HTTPException):
        await svc.authenticate_access(pair.access_token)


async def test_logout_invalidates_old_and_rotated_pairs(login_session):
    svc, pair, _ = login_session
    rotated = await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    claims = decode_token(pair.access_token)
    await svc.logout(jti=claims["jti"], exp=claims["exp"], sid=claims["sid"],
                     user_id=claims["sub"], correlation_id=str(uuid.uuid4()))
    for tokens in (pair, rotated):
        with pytest.raises(HTTPException):
            await svc.authenticate_access(tokens.access_token)
        with pytest.raises(HTTPException):
            await svc.refresh(tokens.refresh_token, str(uuid.uuid4()))


async def test_current_user_and_roles_override_signed_snapshot(login_session):
    svc, pair, user = login_session
    with (
        patch.object(svc._user_repo, "get_roles_for_user", return_value=[]),
        patch.object(svc._user_repo, "get_permissions_for_roles", return_value=[]),
    ):
        claims = await svc.authenticate_access(pair.access_token)
        assert claims["roles"] == claims["permissions"] == []
    user.is_active = False
    with pytest.raises(HTTPException):
        await svc.authenticate_access(pair.access_token)
    with pytest.raises(HTTPException):
        await svc.refresh(pair.refresh_token, str(uuid.uuid4()))


@pytest.mark.parametrize("state", ["expired", "missing", "malformed"])
async def test_session_fails_closed(login_session, fake_redis, state):
    svc, pair, _ = login_session
    key = SessionRepository.key(decode_token(pair.access_token)["sid"])
    if state == "expired":
        await fake_redis.expire(key, 0)
    elif state == "missing":
        await fake_redis.delete(key)
    else:
        await fake_redis.set(key, "{}")
    with pytest.raises(HTTPException) as error:
        await svc.authenticate_access(pair.access_token)
    assert error.value.status_code == 401
    with pytest.raises(HTTPException):
        await svc.refresh(pair.refresh_token, str(uuid.uuid4()))


async def test_session_store_outage_is_dependency_unavailable_not_401(login_session, fake_redis):
    """ADR-028 C2: Redis session-store outages return 503, not 401 (still deny access)."""
    svc, pair, _ = login_session
    fake_redis.get = AsyncMock(side_effect=ConnectionError("unavailable"))
    with pytest.raises(DependencyUnavailableError) as error:
        await svc.authenticate_access(pair.access_token)
    assert error.value.dependency == "redis"
    with pytest.raises(DependencyUnavailableError):
        await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
