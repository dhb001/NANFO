"""Unit tests for AuthService (app/modules/identity/service.py).

All external dependencies (DB, Redis, UserRepository) are mocked.
Per testing.md: unit tests must not hit databases or external services.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.identity.models import AuditLog, Role, User, UserRole
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
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
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

    @pytest.mark.asyncio
    async def test_invalid_password_raises_401(self, auth_svc, user):
        """Bad password must return 401; must not reveal which field was wrong (Authentication.md §6)."""
        from fastapi import HTTPException
        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=user),
            patch("app.modules.identity.service.verify_password", return_value=False),
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await auth_svc.login("test@example.com", "wrong", "127.0.0.1", str(uuid.uuid4()))
        assert exc_info.value.status_code == 401
        # Error message must not say 'password' or 'email' specifically
        detail = exc_info.value.detail.lower()
        assert "password" not in detail
        assert "email" not in detail

    @pytest.mark.asyncio
    async def test_unknown_user_raises_401(self, auth_svc):
        """Non-existent user must give same 401 as wrong password (no email enumeration)."""
        from fastapi import HTTPException
        with (
            patch.object(auth_svc._user_repo, "get_by_email", return_value=None),
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
        ):
            with pytest.raises(HTTPException) as exc_info:
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

        with patch("app.modules.identity.service.publish_event", new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc_info:
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
        ):
            with pytest.raises(HTTPException) as exc_info:
                await auth_svc.login("test@example.com", "pass", "127.0.0.1", str(uuid.uuid4()))
        assert exc_info.value.status_code == 401


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_adds_jti_to_deny_list(self, auth_svc, fake_redis):
        """Logout must add jti to Redis deny-list so token is revoked (Authentication.md §8.3)."""
        jti = str(uuid.uuid4())
        from datetime import timedelta
        exp = int((datetime.now(UTC) + timedelta(minutes=14)).timestamp())

        with patch("app.modules.identity.service.publish_event", new_callable=AsyncMock):
            await auth_svc.logout(jti=jti, exp=exp, user_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()))

        deny_key = f"jti:deny:{jti}"
        assert await fake_redis.exists(deny_key) == 1


class TestRefresh:
    @pytest.mark.asyncio
    async def test_valid_refresh_token_returns_new_access_token(self, auth_svc, user):
        from app.core.security import create_refresh_token
        refresh_token, _ = create_refresh_token(user_id=str(user.user_id))
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
    async def test_access_token_as_refresh_raises_401(self, auth_svc):
        """Passing an access token to /refresh must be rejected."""
        from fastapi import HTTPException
        from app.core.security import create_access_token
        token, _ = create_access_token(user_id="u1", email="a@b.com", roles=[], permissions=[])
        with pytest.raises(HTTPException) as exc_info:
            await auth_svc.refresh(refresh_token=token, correlation_id=str(uuid.uuid4()))
        assert exc_info.value.status_code == 401
