"""ADR-028 C11 login throttling and bcrypt-bound regressions (fakeredis, mocked DB)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.modules.identity.service import (
    _DUMMY_PASSWORD_HASH,
    AuthService,
    login_email_bucket_key,
    login_ip_bucket_key,
)

EMAIL = "Throttle.Target@example.com"


@pytest.fixture
def svc(mock_db, fake_redis):
    return AuthService(mock_db, fake_redis)


@pytest.fixture
def account():
    return SimpleNamespace(user_id=uuid.UUID(int=77), email=EMAIL, is_active=True,
                           hashed_password="account-hash", display_name="Target")


def _rate_limited_audits(mock_db):
    return [call.args[0] for call in mock_db.add.call_args_list
            if (call.args[0].metadata_ or {}).get("reason") == "rate_limited"]


async def _attempt(svc, account, *, ip, password_ok, email=EMAIL, password="secret"):
    with (
        patch.object(svc._user_repo, "get_by_email", return_value=account),
        patch.object(svc._user_repo, "get_roles_for_user", return_value=["Operator"]),
        patch("app.modules.identity.service.verify_password", return_value=password_ok) as verify,
        patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
    ):
        try:
            return await svc.login(email, password, ip, str(uuid.uuid4())), verify
        except HTTPException as error:
            return error.status_code, verify


async def test_email_bucket_counts_failures_only_and_is_cleared_on_success(svc, account, fake_redis):
    for index in range(4):
        status_code, _ = await _attempt(svc, account, ip=f"10.0.0.{index}", password_ok=False)
        assert status_code == 401
    assert await fake_redis.get(login_email_bucket_key(EMAIL)) == "4"
    pair, _ = await _attempt(svc, account, ip="10.0.0.9", password_ok=True)
    assert pair.access_token
    assert await fake_redis.exists(login_email_bucket_key(EMAIL)) == 0
    # The per-IP bucket still counts the successful attempt.
    assert await fake_redis.get(login_ip_bucket_key("10.0.0.9")) == "1"


async def test_successful_logins_never_accumulate_toward_email_lockout(svc, account, fake_redis):
    for index in range(8):  # more than RATE_LIMIT_LOGIN_MAX_ATTEMPTS (5)
        pair, _ = await _attempt(svc, account, ip=f"10.1.0.{index}", password_ok=True)
        assert pair.refresh_token
    assert await fake_redis.exists(login_email_bucket_key(EMAIL)) == 0


async def test_email_bucket_is_case_insensitive(svc, account, fake_redis):
    assert login_email_bucket_key(EMAIL) == login_email_bucket_key(EMAIL.lower()) == login_email_bucket_key(
        f"  {EMAIL.upper()} ")
    await fake_redis.set(login_email_bucket_key(EMAIL), "5", ex=60)
    status_code, verify = await _attempt(svc, account, ip="10.2.0.1", password_ok=True, email=EMAIL.upper())
    assert status_code == 429
    verify.assert_not_called()


async def test_ip_bucket_counts_every_attempt_including_success(svc, account, fake_redis):
    for _ in range(5):
        pair, _ = await _attempt(svc, account, ip="10.3.0.1", password_ok=True)
        assert pair.access_token
    status_code, verify = await _attempt(svc, account, ip="10.3.0.1", password_ok=True)
    assert status_code == 429
    verify.assert_not_called()


async def test_only_first_throttled_attempt_per_window_is_audited(svc, account, fake_redis, mock_db):
    ip_key = login_ip_bucket_key("10.4.0.1")
    await fake_redis.set(ip_key, "5", ex=60)
    for _ in range(3):
        status_code, verify = await _attempt(svc, account, ip="10.4.0.1", password_ok=True)
        assert status_code == 429
        verify.assert_not_called()
    audits = _rate_limited_audits(mock_db)
    assert len(audits) == 1
    assert audits[0].metadata_["limited_by"] == "ip" and audits[0].actor_id is None
    marker_ttl = await fake_redis.pttl("ratelimit:login-audited:10.4.0.1")
    assert 0 < marker_ttl <= await fake_redis.pttl(ip_key) + 50
    # A new window audits its first throttled attempt again.
    await fake_redis.delete(ip_key, "ratelimit:login-audited:10.4.0.1")
    await fake_redis.set(ip_key, "5", ex=60)
    await _attempt(svc, account, ip="10.4.0.1", password_ok=True)
    assert len(_rate_limited_audits(mock_db)) == 2


async def test_email_throttle_is_audited_once_and_names_the_bucket(svc, account, fake_redis, mock_db):
    await fake_redis.set(login_email_bucket_key(EMAIL), "5", ex=60)
    for index in range(3):
        status_code, _ = await _attempt(svc, account, ip=f"10.5.0.{index}", password_ok=True)
        assert status_code == 429
    audits = _rate_limited_audits(mock_db)
    assert [audit.metadata_["limited_by"] for audit in audits] == ["email"]


async def test_throttle_logs_and_keys_never_contain_raw_email(svc, account, fake_redis, caplog):
    await fake_redis.set(login_email_bucket_key(EMAIL), "5", ex=60)
    with caplog.at_level("WARNING"):
        status_code, _ = await _attempt(svc, account, ip="10.6.0.1", password_ok=False)
    assert status_code == 429
    assert "login_rate_limited" in caplog.text
    assert EMAIL not in caplog.text and EMAIL.lower() not in caplog.text
    assert login_email_bucket_key(EMAIL).rsplit(":", 1)[1][:16] in caplog.text
    for key in await fake_redis.keys("*"):
        assert EMAIL.lower() not in key.lower()


@pytest.mark.parametrize("password", ["p" * 73, "é" * 37, "\ud800"])
async def test_over_long_password_gets_generic_401_after_dummy_check(svc, account, fake_redis, mock_db, password):
    """C11: >72-byte secrets never meet the account hash (bcrypt would truncate)."""
    status_code, verify = await _attempt(svc, account, ip="10.7.0.1", password_ok=True, password=password)
    assert status_code == 401
    verify.assert_called_once_with(password, _DUMMY_PASSWORD_HASH)
    assert await fake_redis.keys("auth:session:*") == []
    failures = [call.args[0] for call in mock_db.add.call_args_list
                if (call.args[0].metadata_ or {}).get("reason") == "invalid_credentials"]
    assert len(failures) == 1 and failures[0].actor_id == account.user_id
    assert await fake_redis.get(login_email_bucket_key(EMAIL)) == "1"


async def test_seventy_two_byte_password_is_checked_against_the_account_hash(svc, account):
    pair, verify = await _attempt(svc, account, ip="10.8.0.1", password_ok=True, password="é" * 36)
    assert pair.access_token
    verify.assert_called_once_with("é" * 36, "account-hash")


async def test_login_audit_failure_discards_the_new_session(svc, account, fake_redis, mock_db):
    mock_db.commit.side_effect = RuntimeError("audit store unavailable")
    with pytest.raises(RuntimeError):
        with (
            patch.object(svc._user_repo, "get_by_email", return_value=account),
            patch.object(svc._user_repo, "get_roles_for_user", return_value=["Operator"]),
            patch("app.modules.identity.service.verify_password", return_value=True),
        ):
            await svc.login(EMAIL, "secret", "10.9.0.1", str(uuid.uuid4()))
    assert await fake_redis.keys("auth:session:*") == []
    assert await fake_redis.zcard(f"auth:user_sessions:{account.user_id}") == 0
