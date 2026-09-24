"""ADR-028 C2/C9 session lifecycle: retry grace, reuse audit, per-user index, idle expiry, revocation."""

from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from redis.exceptions import WatchError

from app.core.errors import DependencyUnavailableError
from app.core.security import create_refresh_token, decode_token
from app.modules.identity.models import AuditLog
from app.modules.identity.policy import is_capability_downgrade
from app.modules.identity.repository import UserRepository
from app.modules.identity.service import AuthService, IdentityAccountService
from app.modules.identity.sessions import (
    DEFAULT_IDLE_TIMEOUT_SECONDS,
    DEFAULT_MAX_ROTATION_ATTEMPTS,
    SessionRepository,
    open_issued_pair,
    token_digest,
)

ALICE, BOB = uuid.UUID(int=501), uuid.UUID(int=502)


@pytest.fixture
def directory(monkeypatch):
    users = {
        user_id: SimpleNamespace(user_id=user_id, email=f"{user_id.int}@example.com", is_active=True,
                                 hashed_password="unused", display_name=f"user-{user_id.int}")
        for user_id in (ALICE, BOB)
    }
    roles = {ALICE: ["Admin"], BOB: ["Operator"]}
    by_id = AsyncMock(side_effect=users.get)
    monkeypatch.setattr(UserRepository, "get_by_id", by_id)
    monkeypatch.setattr(UserRepository, "get_by_email", AsyncMock(
        side_effect=lambda email: next((u for u in users.values() if u.email == email), None)))
    role_reader = AsyncMock(side_effect=lambda user: list(roles[user.user_id]))
    monkeypatch.setattr(UserRepository, "get_roles_for_user", role_reader)
    monkeypatch.setattr("app.modules.identity.service.verify_password", lambda plain, hashed: True)
    monkeypatch.setattr("app.modules.identity.service.publish_event", AsyncMock())
    return SimpleNamespace(users=users, roles=roles, by_id=by_id, role_reader=role_reader)


@pytest.fixture
def svc(mock_db, fake_redis, directory):
    return AuthService(mock_db, fake_redis)


async def _login(svc, user_id, ip="127.0.0.1"):
    return await svc.login(f"{user_id.int}@example.com", "secret", ip, str(uuid.uuid4()))


def _audits(mock_db, event_type):
    return [call.args[0] for call in mock_db.add.call_args_list
            if isinstance(call.args[0], AuditLog) and call.args[0].event_type == event_type]


# ── Retry grace (C9) ─────────────────────────────────────────────────────────

async def test_rotation_seals_the_issued_pair_for_twenty_seconds(svc, fake_redis):
    pair = await _login(svc, ALICE)
    rotated = await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    key = f"auth:rotation:{token_digest(pair.refresh_token)}"
    assert key == SessionRepository.rotation_key(pair.refresh_token)
    assert 0 < await fake_redis.ttl(key) <= 20
    sealed = await fake_redis.get(key)
    # Redis never holds a usable token: the pair is sealed with the presented token.
    assert rotated.access_token not in sealed and rotated.refresh_token not in sealed
    assert open_issued_pair(rotated.refresh_token, sealed, now=int(time.time())) is None
    opened = open_issued_pair(pair.refresh_token, sealed, now=int(time.time()))
    assert (opened.access_token, opened.refresh_token) == (rotated.access_token, rotated.refresh_token)
    tampered = sealed[:-4] + ("AAAA" if not sealed.endswith("AAAA") else "BBBB")
    assert open_issued_pair(pair.refresh_token, tampered, now=int(time.time())) is None


async def test_grace_is_not_honoured_once_the_family_rotated_again(svc, fake_redis, mock_db):
    pair = await _login(svc, ALICE)
    second = await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    third = await svc.refresh(second.refresh_token, str(uuid.uuid4()))
    # R1's sealed pair (R2) is no longer the head: re-presenting R1 is reuse.
    with pytest.raises(HTTPException) as error:
        await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    assert error.value.status_code == 401
    with pytest.raises(HTTPException):
        await svc.authenticate_access(third.access_token)
    assert len(_audits(mock_db, "auth.token.reuse_detected")) == 1


async def test_reuse_outside_grace_revokes_family_audits_and_warns(svc, fake_redis, mock_db, caplog):
    pair = await _login(svc, ALICE)
    rotated = await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    await fake_redis.delete(SessionRepository.rotation_key(pair.refresh_token))
    request_id = str(uuid.uuid4())
    with caplog.at_level("WARNING"), pytest.raises(HTTPException) as error:
        await svc.refresh(pair.refresh_token, request_id, ip_address="203.0.113.9")
    assert (error.value.status_code, error.value.detail) == (401, "Invalid or expired token.")
    sid = decode_token(pair.access_token)["sid"]
    assert not await fake_redis.exists(SessionRepository.key(sid))
    assert await fake_redis.zscore(SessionRepository.user_index_key(str(ALICE)), sid) is None
    with pytest.raises(HTTPException):
        await svc.authenticate_access(rotated.access_token)
    [audit] = _audits(mock_db, "auth.token.reuse_detected")
    assert audit.actor_id == ALICE and audit.resource_id == uuid.UUID(sid)
    assert audit.metadata_ == {"ip_address": "203.0.113.9", "session_id": sid}
    assert audit.correlation_id == uuid.UUID(request_id)
    assert "auth_refresh_token_reuse_detected" in caplog.text and sid in caplog.text


async def test_rotation_audit_failure_is_best_effort(svc, fake_redis, mock_db):
    pair = await _login(svc, ALICE)
    mock_db.commit.side_effect = RuntimeError("audit store down")
    rotated = await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    assert rotated.refresh_token != pair.refresh_token
    mock_db.rollback.assert_awaited()
    entry = json.loads(await fake_redis.get(SessionRepository.key(decode_token(pair.access_token)["sid"])))
    assert entry["refresh_hash"] == token_digest(rotated.refresh_token)


async def test_watch_contention_is_bounded_and_retryable(svc, fake_redis):
    pair = await _login(svc, ALICE)
    pipeline_type = type(fake_redis.pipeline())
    attempts = []

    async def contended(pipe, *args, **kwargs):
        attempts.append(1)
        raise WatchError("watched key changed")

    with patch.object(pipeline_type, "execute", contended), pytest.raises(DependencyUnavailableError) as error:
        await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    assert error.value.dependency == "redis"
    assert len(attempts) == DEFAULT_MAX_ROTATION_ATTEMPTS == 5
    await svc.authenticate_access(pair.access_token)  # contention never revokes


# ── Invalid refresh attempts (fix 5) ─────────────────────────────────────────

async def test_invalid_refresh_attempts_are_audited_once_per_client_window(svc, mock_db):
    for _ in range(3):
        with pytest.raises(HTTPException) as error:
            await svc.refresh("not-a-token", str(uuid.uuid4()), ip_address="198.51.100.1")
        assert error.value.status_code == 401
    with pytest.raises(HTTPException):
        await svc.refresh("not-a-token", str(uuid.uuid4()), ip_address="198.51.100.2")
    audits = _audits(mock_db, "auth.token.refresh_failed")
    assert [(a.metadata_["reason"], a.metadata_["ip_address"], a.actor_id) for a in audits] == [
        ("invalid_token", "198.51.100.1", None), ("invalid_token", "198.51.100.2", None),
    ]


async def test_refresh_of_a_revoked_session_is_audited_with_its_subject(svc, mock_db):
    pair = await _login(svc, ALICE)
    claims = decode_token(pair.access_token)
    await svc.logout(jti=claims["jti"], exp=claims["exp"], user_id=claims["sub"],
                     correlation_id=str(uuid.uuid4()), sid=claims["sid"])
    with pytest.raises(HTTPException):
        await svc.refresh(pair.refresh_token, str(uuid.uuid4()), ip_address="198.51.100.3")
    [audit] = _audits(mock_db, "auth.token.refresh_failed")
    assert audit.metadata_["reason"] == "session_invalid"
    assert (audit.actor_id, audit.resource_id) == (ALICE, uuid.UUID(claims["sid"]))


# ── Per-user index, idle expiry and revocation (C9) ──────────────────────────

async def test_user_index_tracks_create_rotate_and_logout(svc, fake_redis):
    first, second = await _login(svc, ALICE), await _login(svc, ALICE, ip="127.0.0.2")
    index = SessionRepository.user_index_key(str(ALICE))
    sids = {decode_token(pair.access_token)["sid"] for pair in (first, second)}
    assert set(await fake_redis.zrange(index, 0, -1)) == sids
    now = int(time.time())
    for sid in sids:
        assert now < await fake_redis.zscore(index, sid) <= now + DEFAULT_IDLE_TIMEOUT_SECONDS + 1
    assert 0 < await fake_redis.ttl(index) <= 30 * 86400
    claims = decode_token(first.access_token)
    await svc.logout(jti=claims["jti"], exp=claims["exp"], user_id=claims["sub"],
                     correlation_id=str(uuid.uuid4()), sid=claims["sid"])
    assert await fake_redis.zrange(index, 0, -1) == [decode_token(second.access_token)["sid"]]


async def test_idle_expiry_slides_on_rotation_but_never_exceeds_absolute_expiry(fake_redis):
    sessions = SessionRepository(fake_redis, idle_timeout_seconds=600)
    token, _ = create_refresh_token(user_id=str(ALICE))
    claims = decode_token(token, token_type="refresh")
    await sessions.create(claims, token)
    key = SessionRepository.key(claims["sid"])
    assert 590 <= await fake_redis.ttl(key) <= 600
    await fake_redis.expire(key, 30)  # 9.5 minutes idle
    new_token, _ = create_refresh_token(user_id=str(ALICE), sid=claims["sid"], exp=claims["exp"])
    await sessions.rotate(claims, token, decode_token(new_token, token_type="refresh"), new_token,
                          access_token="access", expires_in=900)
    assert 590 <= await fake_redis.ttl(key) <= 600  # sliding: refreshed activity restarts the idle clock
    near_end = int(time.time()) + 120
    short, _ = create_refresh_token(user_id=str(ALICE), exp=near_end)
    short_claims = decode_token(short, token_type="refresh")
    await sessions.create(short_claims, short)
    assert await fake_redis.ttl(SessionRepository.key(short_claims["sid"])) <= 120


async def test_default_idle_timeout_is_twelve_hours(svc, fake_redis):
    pair = await _login(svc, ALICE)
    ttl = await fake_redis.ttl(SessionRepository.key(decode_token(pair.access_token)["sid"]))
    assert DEFAULT_IDLE_TIMEOUT_SECONDS == 12 * 3600
    assert DEFAULT_IDLE_TIMEOUT_SECONDS - 5 <= ttl <= DEFAULT_IDLE_TIMEOUT_SECONDS


async def test_revoke_user_sessions_ends_every_family_of_that_user_only(svc, fake_redis, mock_db):
    alice = [await _login(svc, ALICE, ip=f"127.0.1.{index}") for index in range(2)]
    bob = await _login(svc, BOB)
    assert await svc.revoke_user_sessions(ALICE, reason="operator_request") == 2
    for pair in alice:
        with pytest.raises(HTTPException):
            await svc.authenticate_access(pair.access_token)
        with pytest.raises(HTTPException):
            await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    await svc.authenticate_access(bob.access_token)
    assert await fake_redis.zcard(SessionRepository.user_index_key(str(ALICE))) == 0
    [audit] = _audits(mock_db, "auth.user.sessions_revoked")
    assert (audit.actor_id, audit.resource_type, audit.resource_id) == (ALICE, "user", ALICE)
    assert audit.metadata_ == {"reason": "operator_request", "revoked_sessions": 2}
    with pytest.raises(ValueError):
        await svc.revoke_user_sessions(ALICE, reason="because")


async def test_revocation_outage_is_reported_not_skipped(svc, fake_redis):
    await _login(svc, ALICE)
    fake_redis.zrange = AsyncMock(side_effect=ConnectionError("down"))
    with pytest.raises(DependencyUnavailableError):
        await svc.revoke_user_sessions(ALICE, reason="operator_request")


@pytest.mark.parametrize("path", ["authenticate", "refresh"])
async def test_inactive_account_deletes_the_presented_family(svc, fake_redis, directory, path):
    pair = await _login(svc, ALICE)
    sid = decode_token(pair.access_token)["sid"]
    directory.users[ALICE].is_active = False
    with pytest.raises(HTTPException) as error:
        if path == "authenticate":
            await svc.authenticate_access(pair.access_token)
        else:
            await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    assert error.value.status_code == 401
    assert not await fake_redis.exists(SessionRepository.key(sid))
    assert await fake_redis.zscore(SessionRepository.user_index_key(str(ALICE)), sid) is None


async def test_access_validation_no_longer_consults_the_unwritten_deny_list(svc, fake_redis):
    pair = await _login(svc, ALICE)
    await fake_redis.set(f"jti:deny:{decode_token(pair.access_token)['jti']}", "1")
    fake_redis.exists = AsyncMock(side_effect=AssertionError("deny-list round trip"))
    assert (await svc.authenticate_access(pair.access_token))["sub"] == str(ALICE)


# ── Account mutations revoke sessions (C9) ───────────────────────────────────

@pytest.fixture
def accounts(mock_db, fake_redis, monkeypatch):
    monkeypatch.setattr(UserRepository, "set_active", AsyncMock(return_value=True))
    monkeypatch.setattr(UserRepository, "set_password_hash", AsyncMock(return_value=True))
    monkeypatch.setattr("app.modules.identity.service.hash_password", lambda plain: "hashed")
    return IdentityAccountService(mock_db, fake_redis)


async def test_deactivation_revokes_every_session(svc, accounts, mock_db):
    pair = await _login(svc, ALICE)
    assert await accounts.deactivate_user(ALICE, actor_id=BOB) == 1
    UserRepository.set_active.assert_awaited_once_with(ALICE, False)
    with pytest.raises(HTTPException):
        await svc.refresh(pair.refresh_token, str(uuid.uuid4()))
    [changed] = _audits(mock_db, "auth.user.deactivated")
    [revoked] = _audits(mock_db, "auth.user.sessions_revoked")
    assert changed.actor_id == revoked.actor_id == BOB
    assert revoked.metadata_["reason"] == "deactivated"


async def test_password_change_revokes_every_session(svc, accounts, mock_db):
    pair = await _login(svc, ALICE)
    assert await accounts.change_password(ALICE, "new-secret") == 1
    UserRepository.set_password_hash.assert_awaited_once_with(ALICE, "hashed")
    with pytest.raises(HTTPException):
        await svc.authenticate_access(pair.access_token)
    assert _audits(mock_db, "auth.user.password_changed")


async def test_over_long_new_password_is_rejected_before_any_change(svc, mock_db, fake_redis, monkeypatch):
    accounts = IdentityAccountService(mock_db, fake_redis)
    pair = await _login(svc, ALICE)
    with pytest.raises(ValueError):
        await accounts.change_password(ALICE, "x" * 73)
    await svc.authenticate_access(pair.access_token)


@pytest.mark.parametrize(("before", "after", "revoked"), [
    (["Admin"], ["Read-Only"], 1), (["Admin", "Operator"], ["Admin"], 1),
    (["Read-Only"], ["Operator", "Read-Only"], 0), (["Operator"], ["Operator"], 0),
])
async def test_role_downgrade_revokes_but_upgrade_does_not(svc, accounts, monkeypatch, before, after, revoked):
    pair = await _login(svc, ALICE)
    monkeypatch.setattr(UserRepository, "replace_roles", AsyncMock(return_value=(before, sorted(after))))
    assert await accounts.replace_roles(ALICE, after) == revoked
    assert is_capability_downgrade(before, after) is bool(revoked)
    if revoked:
        with pytest.raises(HTTPException):
            await svc.authenticate_access(pair.access_token)
    else:
        await svc.authenticate_access(pair.access_token)


async def test_account_mutation_of_unknown_user_is_rejected(accounts, directory, monkeypatch):
    monkeypatch.setattr(UserRepository, "set_active", AsyncMock(return_value=False))
    with pytest.raises(LookupError):
        await accounts.deactivate_user(uuid.UUID(int=999))


# ── Current identity loaded once per request (fix 11) ────────────────────────

async def test_identity_and_roles_load_once_per_request_session(mock_db, fake_redis, directory):
    pair = await _login(AuthService(mock_db, fake_redis), ALICE)
    directory.by_id.reset_mock()
    directory.role_reader.reset_mock()
    mock_db.info = {}  # a real AsyncSession exposes a per-session info dict
    claims = await AuthService(mock_db, fake_redis).authenticate_access(pair.access_token)
    profile = await AuthService(mock_db, fake_redis).get_profile(claims["sub"], reuse_request_identity=True)
    assert profile.roles == claims["roles"] == ["Admin"]
    assert profile.permissions == claims["permissions"]
    assert directory.by_id.await_count == 1 and directory.role_reader.await_count == 1
    # A new request (new session) reloads current authority.
    directory.roles[ALICE] = []
    fresh = await AuthService(type(mock_db)(), fake_redis).get_profile(claims["sub"], reuse_request_identity=True)
    assert fresh.roles == [] and fresh.permissions == []


async def test_deliberate_rechecks_in_the_same_session_stay_fresh(mock_db, fake_redis, directory):
    """Re-authorization after a lock wait (autonomy/report flows) must observe revocation."""
    pair = await _login(AuthService(mock_db, fake_redis), ALICE)
    mock_db.info = {}
    svc = AuthService(mock_db, fake_redis)
    claims = await svc.authenticate_access(pair.access_token)
    assert (await svc.get_profile(claims["sub"])).roles == ["Admin"]
    directory.roles[ALICE] = ["Read-Only"]
    assert (await svc.get_profile(claims["sub"])).roles == ["Read-Only"]
    directory.users[ALICE].is_active = False
    with pytest.raises(HTTPException) as error:
        await svc.get_profile(claims["sub"])
    assert error.value.status_code == 404
    from app.modules.identity.service import IdentityDirectoryService
    assert not await IdentityDirectoryService(mock_db).user_exists(ALICE)
