"""Unit tests for AuthService (app/modules/identity/service.py).

All external dependencies (DB, Redis, UserRepository) are mocked.
Per testing.md: unit tests must not hit databases or external services.
"""

import asyncio
import threading
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError

from app.modules.identity.models import Role, User, UserRole
from app.modules.identity.service import AuthService


def _make_user(roles: list[str] | None = None) -> User:
    """Build a mock User ORM object."""
    user = MagicMock(spec=User)
    user.user_id = uuid.uuid4()
    user.email = "test@example.com"
    user.is_active = True
    user.display_name = "Test User"

    mock_roles = []
    for r in (roles or ["Admin"]):
        role_obj = MagicMock(spec=Role)
        role_obj.name = r
        ur = MagicMock(spec=UserRole)
        ur.role = role_obj
        mock_roles.append(ur)
    user.user_roles = mock_roles
    return user


@pytest.fixture
def user(fake_redis, mock_db) -> User:
    return _make_user(roles=["Admin"])


@pytest.fixture
def auth_svc(mock_db, fake_redis) -> AuthService:
    return AuthService(db=mock_db, redis=fake_redis)


class TestLogin:
    @pytest.mark.asyncio
    async def test_successful_login_returns_token_pair(self, auth_svc, user, fake_redis):
        """Successful login issues access + refresh tokens."""
        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=user) as _,
            patch.object(auth_svc._user_repo, "get_roles_for_user", return_value=["Admin"]) as _,
            patch.object(auth_svc._user_repo, "get_permissions_for_roles", return_value=["write:config"]) as _,
            patch("app.modules.identity.service.verify_password", return_value=True),
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock) as mock_publish,
        ):
            result = await auth_svc.login(
                email="test@example.com",
                password="correct",
                ip_address="127.0.0.1",
                correlation_id=str(uuid.uuid4()),
            )
        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"
        assert mock_publish.await_count >= 1

    @pytest.mark.asyncio
    async def test_successful_login_event_publish_failure_is_fail_open(self, auth_svc, user):
        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=user),
            patch.object(auth_svc._user_repo, "get_roles_for_user", return_value=["Admin"]),
            patch.object(auth_svc._user_repo, "get_permissions_for_roles", return_value=["write:config"]),
            patch("app.modules.identity.service.verify_password", return_value=True),
            patch(
                "app.modules.identity.service.publish_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("stream unavailable"),
            ),
        ):
            result = await auth_svc.login(
                email="test@example.com",
                password="correct",
                ip_address="127.0.0.1",
                correlation_id=str(uuid.uuid4()),
            )

        assert result.access_token
        assert result.refresh_token

    @pytest.mark.asyncio
    async def test_invalid_password_raises_401(self, auth_svc, user):
        """Bad password must return 401; must not reveal which field was wrong (Authentication.md §6)."""
        from fastapi import HTTPException
        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=user),
            patch("app.modules.identity.service.verify_password", return_value=False),
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
            pytest.raises(HTTPException) as exc_info,
        ):
            await auth_svc.login("test@example.com", "wrong", "127.0.0.1", str(uuid.uuid4()))
        assert exc_info.value.status_code == 401
        # Error message must not say 'password' or 'email' specifically
        detail = exc_info.value.detail.lower()
        assert "password" not in detail
        assert "email" not in detail

    @pytest.mark.asyncio
    async def test_invalid_password_event_publish_failure_preserves_401(self, auth_svc, user):
        from fastapi import HTTPException

        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=user),
            patch("app.modules.identity.service.verify_password", return_value=False),
            patch(
                "app.modules.identity.service.publish_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("stream unavailable"),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await auth_svc.login("test@example.com", "wrong", "127.0.0.1", str(uuid.uuid4()))

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_unknown_user_raises_401(self, auth_svc):
        """Non-existent user must give same 401 as wrong password (no email enumeration)."""
        from fastapi import HTTPException
        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=None),
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
            pytest.raises(HTTPException) as exc_info,
        ):
            await auth_svc.login("ghost@example.com", "any", "127.0.0.1", str(uuid.uuid4()))
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_raises_429(self, auth_svc, fake_redis):
        """IP exceeding RATE_LIMIT_LOGIN_MAX_ATTEMPTS in window must get 429."""
        from fastapi import HTTPException
        # Simulate 5 prior attempts for this IP
        ip = "10.0.0.1"
        key = f"ratelimit:login:{ip}"
        await fake_redis.set(key, "5", ex=60)

        with (
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
            pytest.raises(HTTPException) as exc_info,
        ):
            await auth_svc.login("x@y.com", "p", ip, str(uuid.uuid4()))
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_inactive_user_raises_401(self, auth_svc):
        """Deactivated user must not be able to log in."""
        from fastapi import HTTPException
        inactive = _make_user()
        inactive.is_active = False
        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=inactive),
            patch("app.modules.identity.service.verify_password", return_value=True),
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
            pytest.raises(HTTPException) as exc_info,
        ):
            await auth_svc.login("test@example.com", "pass", "127.0.0.1", str(uuid.uuid4()))
        assert exc_info.value.status_code == 401


class TestLoginHardening:
    @pytest.mark.parametrize("account", ["active", "inactive", "missing"])
    async def test_bcrypt_runs_off_loop_for_all_credentials(self, auth_svc, user, account):
        """A blocked password worker must not block other event-loop work."""
        user.is_active = account != "inactive"
        selected = None if account == "missing" else user
        loop_thread = threading.get_ident()
        entered = threading.Event()
        release = threading.Event()
        worker_threads = []

        def verify(plain, hashed):
            worker_threads.append(threading.get_ident())
            entered.set()
            assert release.wait(timeout=3), "event loop could not release bcrypt worker"
            return False

        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=selected),
            patch("app.modules.identity.service.verify_password", side_effect=verify),
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
        ):
            task = asyncio.create_task(auth_svc.login(
                user.email, "wrong", "127.0.0.1", str(uuid.uuid4()),
            ))
            try:
                async with asyncio.timeout(2):
                    while not entered.is_set():
                        await asyncio.sleep(0.001)
            finally:
                release.set()
            with pytest.raises(HTTPException) as error:
                await task
        assert worker_threads and worker_threads[0] != loop_thread
        assert (error.value.status_code, error.value.detail) == (401, "Invalid credentials.")

    async def test_dummy_hash_never_authenticates_missing_user(self, auth_svc):
        from app.modules.identity.service import _DUMMY_PASSWORD_HASH

        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=None),
            patch("app.modules.identity.service.verify_password", return_value=True) as verify,
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
            patch.object(auth_svc._sessions, "create") as create,
            pytest.raises(HTTPException) as error,
        ):
            await auth_svc.login("missing@example.com", "candidate", "127.0.0.1", str(uuid.uuid4()))
        verify.assert_called_once_with("candidate", _DUMMY_PASSWORD_HASH)
        create.assert_not_called()
        assert error.value.detail == "Invalid credentials."

    async def test_dummy_hash_is_valid_and_cost_matched(self):
        from app.core.security import _BCRYPT_ROUNDS, verify_password
        from app.modules.identity.service import _DUMMY_PASSWORD_HASH

        assert int(_DUMMY_PASSWORD_HASH.split("$")[2]) == _BCRYPT_ROUNDS
        assert not await asyncio.to_thread(verify_password, "wrong", _DUMMY_PASSWORD_HASH)

    @pytest.mark.parametrize("limited_by", ["ip", "email"])
    async def test_concurrent_attempts_keep_both_fixed_windows(self, auth_svc, fake_redis, limited_by):
        """Changing the other identity cannot bypass either five-attempt limit."""
        async def login(index):
            ip = "127.0.0.1" if limited_by == "ip" else f"127.0.0.{index + 1}"
            email = "test@example.com" if limited_by == "email" else f"user{index}@example.com"
            with pytest.raises(HTTPException) as error:
                await auth_svc.login(email, "wrong", ip, str(uuid.uuid4()))
            return error.value.status_code

        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=None),
            patch("app.modules.identity.service.verify_password", return_value=False) as verify,
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
        ):
            statuses = await asyncio.gather(*(login(index) for index in range(12)))
        assert statuses.count(401) == 5
        assert statuses.count(429) == 7
        assert verify.call_count == 5
        keys = await fake_redis.keys("ratelimit:login:*")
        assert len(keys) == 13
        for key in keys:
            assert 0 < await fake_redis.ttl(key) <= 60

    @pytest.mark.parametrize("ttl", [None, 15])
    async def test_preserves_existing_expiry_and_repairs_legacy_counter(self, auth_svc, fake_redis, ttl):
        keys = ["ratelimit:login:127.0.0.1", "ratelimit:login:email:test@example.com"]
        for key in keys:
            await fake_redis.set(key, "5", ex=ttl)
        with pytest.raises(HTTPException) as error:
            await auth_svc.login("test@example.com", "wrong", "127.0.0.1", str(uuid.uuid4()))
        assert error.value.status_code == 429
        for key in keys:
            assert await fake_redis.get(key) == "6"
            assert 0 < await fake_redis.ttl(key) <= (ttl or 60)

    async def test_expired_windows_admit_new_attempt(self, auth_svc, fake_redis):
        keys = ["ratelimit:login:127.0.0.1", "ratelimit:login:email:test@example.com"]
        for key in keys:
            await fake_redis.set(key, "5")
            await fake_redis.pexpireat(key, 1)
        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=None),
            patch("app.modules.identity.service.verify_password", return_value=False),
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
            pytest.raises(HTTPException) as error,
        ):
            await auth_svc.login("test@example.com", "wrong", "127.0.0.1", str(uuid.uuid4()))
        assert error.value.status_code == 401
        for key in keys:
            assert await fake_redis.get(key) == "1"
            assert 0 < await fake_redis.ttl(key) <= 60

    @pytest.mark.parametrize("failure", [RedisConnectionError("offline"), RuntimeError("closed")])
    async def test_transaction_failure_denies_before_credentials(self, auth_svc, fake_redis, failure):
        with (
            patch.object(type(fake_redis.pipeline()), "execute", side_effect=failure),
            patch.object(auth_svc._user_repo, "get_by_email") as lookup,
            patch("app.modules.identity.service.verify_password") as verify,
            pytest.raises(HTTPException) as error,
        ):
            await auth_svc.login("test@example.com", "wrong", "127.0.0.1", str(uuid.uuid4()))
        assert (error.value.status_code, error.value.detail) == (401, "Invalid or expired token.")
        lookup.assert_not_called()
        verify.assert_not_called()
        assert await fake_redis.keys("ratelimit:login:*") == []

    async def test_cancellation_before_exec_leaves_no_partial_counter(self, auth_svc, fake_redis):
        with (
            patch.object(type(fake_redis.pipeline()), "execute", side_effect=asyncio.CancelledError),
            pytest.raises(asyncio.CancelledError),
        ):
            await auth_svc.login("test@example.com", "wrong", "127.0.0.1", str(uuid.uuid4()))
        assert await fake_redis.keys("ratelimit:login:*") == []


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_adds_jti_to_deny_list(self, auth_svc, fake_redis):
        """Logout removes the entire session family, not just one access jti."""
        jti = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        await fake_redis.set(f"auth:session:{sid}", "session")
        from datetime import timedelta
        exp = int((datetime.now(UTC) + timedelta(minutes=14)).timestamp())

        with patch("app.modules.identity.service.publish_event", new_callable=AsyncMock):
            await auth_svc.logout(jti=jti, exp=exp, user_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()), sid=sid)

        assert await fake_redis.exists(f"auth:session:{sid}") == 0

    @pytest.mark.asyncio
    async def test_logout_event_publish_failure_is_fail_open(self, auth_svc, fake_redis):
        from datetime import timedelta

        jti = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        await fake_redis.set(f"auth:session:{sid}", "session")
        exp = int((datetime.now(UTC) + timedelta(minutes=14)).timestamp())
        with patch(
            "app.modules.identity.service.publish_event",
            new_callable=AsyncMock,
            side_effect=RuntimeError("stream unavailable"),
        ):
            await auth_svc.logout(jti=jti, exp=exp, user_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()), sid=sid)

        assert await fake_redis.exists(f"auth:session:{sid}") == 0


class TestRefresh:
    @pytest.mark.asyncio
    async def test_valid_refresh_token_returns_new_access_token(self, auth_svc, user):
        from app.core.security import create_refresh_token, decode_token
        refresh_token, _ = create_refresh_token(user_id=str(user.user_id))
        await auth_svc._sessions.create(decode_token(refresh_token, token_type="refresh"), refresh_token)
        with (
            patch.object(auth_svc._user_repo, "get_by_id", return_value=user),
            patch.object(auth_svc._user_repo, "get_roles_for_user", return_value=["Admin"]),
            patch.object(auth_svc._user_repo, "get_permissions_for_roles", return_value=["write:config"]),
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
        ):
            result = await auth_svc.refresh(refresh_token=refresh_token, correlation_id=str(uuid.uuid4()))
        assert result.access_token
        assert result.expires_in > 0

    @pytest.mark.asyncio
    async def test_refresh_event_publish_failure_is_fail_open(self, auth_svc, user):
        from app.core.security import create_refresh_token, decode_token

        refresh_token, _ = create_refresh_token(user_id=str(user.user_id))
        await auth_svc._sessions.create(decode_token(refresh_token, token_type="refresh"), refresh_token)
        with (
            patch.object(auth_svc._user_repo, "get_by_id", return_value=user),
            patch.object(auth_svc._user_repo, "get_roles_for_user", return_value=["Admin"]),
            patch.object(auth_svc._user_repo, "get_permissions_for_roles", return_value=["write:config"]),
            patch(
                "app.modules.identity.service.publish_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("stream unavailable"),
            ),
        ):
            result = await auth_svc.refresh(refresh_token=refresh_token, correlation_id=str(uuid.uuid4()))

        assert result.access_token

    @pytest.mark.asyncio
    async def test_access_token_as_refresh_raises_401(self, auth_svc):
        """Passing an access token to /refresh must be rejected."""
        from fastapi import HTTPException

        from app.core.security import create_access_token

        token, _ = create_access_token(user_id="u1", email="a@b.com", roles=[], permissions=[])
        with pytest.raises(HTTPException) as exc_info:
            await auth_svc.refresh(refresh_token=token, correlation_id=str(uuid.uuid4()))
        assert exc_info.value.status_code == 401
