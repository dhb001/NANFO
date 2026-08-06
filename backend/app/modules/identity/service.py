"""NANFO Backend — Identity module service layer.

AuthService: login, logout, refresh, me endpoints.
Implements:
  - Rate limiting per IP and per email (Authentication.md §5)
  - JWT issuance with full claim baseline (Authentication.md §8)
  - jti deny-list on logout (Authentication.md §8.3)
  - Audit log writes for all auth events (Authentication.md §2, §6)
  - Event publication for auth domain events (EventAPI.md)
"""

from __future__ import annotations

import uuid

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    remaining_ttl_seconds,
    verify_password,
)
from app.events.publisher import publish_event
from app.modules.identity.models import User
from app.modules.identity.repository import AuditLogRepository, UserRepository
from app.modules.identity.schemas import AccessToken, TokenPair, UserProfile

logger = get_logger(__name__)


class AuthService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._user_repo = UserRepository(db)
        self._audit_repo = AuditLogRepository(db)

    async def login(
        self,
        email: str,
        password: str,
        ip_address: str,
        correlation_id: str,
    ) -> TokenPair:
        """Authenticate user and issue JWT pair. Rate-limited per IP and per email.

        Authentication.md §6 AC: 401 must not indicate whether email or password was wrong.
        All outcomes are appended to audit_logs.
        """
        settings = get_settings()

        # ── Rate limiting (Authentication.md §5) ──────────────────────────────
        ip_key = f"ratelimit:login:{ip_address}"
        email_key = f"ratelimit:login:email:{email}"
        ip_count = await self._redis.incr(ip_key)
        if ip_count == 1:
            await self._redis.expire(ip_key, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)
        email_count = await self._redis.incr(email_key)
        if email_count == 1:
            await self._redis.expire(email_key, settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS)

        if ip_count > settings.RATE_LIMIT_LOGIN_MAX_ATTEMPTS or email_count > settings.RATE_LIMIT_LOGIN_MAX_ATTEMPTS:
            logger.warning("login_rate_limited", ip=ip_address, email=email)
            await self._audit_repo.append(
                event_type="auth.user.login_failed",
                actor_id=None,
                org_id=None,
                correlation_id=uuid.UUID(correlation_id),
                metadata={"reason": "rate_limited", "ip_address": ip_address},
            )
            await self._db.commit()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Please try again later.",
            )

        # ── Credential validation ─────────────────────────────────────────────
        user = await self._user_repo.get_by_email(email)
        invalid = user is None or not verify_password(password, user.hashed_password) or not user.is_active

        if invalid:
            # Intentionally generic error — do not reveal whether email or password failed
            await self._audit_repo.append(
                event_type="auth.user.login_failed",
                actor_id=user.user_id if user else None,
                org_id=None,
                correlation_id=uuid.UUID(correlation_id),
                metadata={"reason": "invalid_credentials", "ip_address": ip_address},
            )
            await self._db.commit()
            await publish_event(
                redis=self._redis,
                event_type="auth.user.login_failed",
                source="auth",
                payload={"ip_address": ip_address},
                correlation_id=correlation_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials.",
            )

        # ── Issue tokens ──────────────────────────────────────────────────────
        roles = await self._user_repo.get_roles_for_user(user)
        permissions = await self._user_repo.get_permissions_for_roles(roles)

        access_token, access_jti = create_access_token(
            user_id=str(user.user_id),
            email=user.email,
            roles=roles,
            permissions=permissions,
        )
        refresh_token, _ = create_refresh_token(user_id=str(user.user_id))

        # ── Audit log + event publication ─────────────────────────────────────
        await self._audit_repo.append(
            event_type="auth.user.logged_in",
            actor_id=user.user_id,
            org_id=None,
            correlation_id=uuid.UUID(correlation_id),
            metadata={"ip_address": ip_address},
        )
        await self._db.commit()

        await publish_event(
            redis=self._redis,
            event_type="auth.user.logged_in",
            source="auth",
            payload={"user_id": str(user.user_id), "ip_address": ip_address},
            correlation_id=correlation_id,
        )

        settings2 = get_settings()
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings2.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def logout(self, jti: str, exp: int, user_id: str, correlation_id: str) -> None:
        """Revoke the current access token by adding its jti to the Redis deny-list."""
        ttl = remaining_ttl_seconds(exp)
        if ttl > 0:
            deny_key = f"jti:deny:{jti}"
            await self._redis.set(deny_key, "revoked", ex=ttl)

        # Audit log
        await self._audit_repo.append(
            event_type="auth.user.logged_out",
            actor_id=uuid.UUID(user_id),
            correlation_id=uuid.UUID(correlation_id),
            metadata={"jti": jti},
        )
        await self._db.commit()

        await publish_event(
            redis=self._redis,
            event_type="auth.user.logged_out",
            source="auth",
            payload={"user_id": user_id, "jti": jti},
            correlation_id=correlation_id,
        )

    async def refresh(self, refresh_token: str, correlation_id: str) -> AccessToken:
        """Issue a new access token from a valid refresh token."""
        from jose import JWTError
        try:
            payload = decode_token(refresh_token)
        except JWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")

        if payload.get("token_type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type.")

        user_id = payload.get("sub")
        user = await self._user_repo.get_by_id(uuid.UUID(user_id))
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")

        roles = await self._user_repo.get_roles_for_user(user)
        permissions = await self._user_repo.get_permissions_for_roles(roles)
        access_token, _ = create_access_token(
            user_id=str(user.user_id),
            email=user.email,
            roles=roles,
            permissions=permissions,
        )

        await self._audit_repo.append(
            event_type="auth.token.refreshed",
            actor_id=user.user_id,
            correlation_id=uuid.UUID(correlation_id),
        )
        await self._db.commit()
        await publish_event(
            redis=self._redis,
            event_type="auth.token.refreshed",
            source="auth",
            payload={"user_id": user_id},
            correlation_id=correlation_id,
        )

        settings = get_settings()
        return AccessToken(
            access_token=access_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def get_profile(self, user_id: str) -> UserProfile:
        """Return the authenticated user's profile and permissions."""
        user = await self._user_repo.get_by_id(uuid.UUID(user_id))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        roles = await self._user_repo.get_roles_for_user(user)
        permissions = await self._user_repo.get_permissions_for_roles(roles)
        return UserProfile(
            user_id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            roles=roles,
            permissions=permissions,
        )
