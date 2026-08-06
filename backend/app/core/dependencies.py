"""NANFO Backend — FastAPI dependency injection.

Provides reusable dependencies:
  - get_db()          : async SQLAlchemy session
  - get_redis()       : async Redis client
  - get_current_user(): JWT validation + deny-list check → TokenClaims
  - require_roles()   : RBAC decorator factory
  - get_request_meta(): request_id + timestamp for envelope construction
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import decode_token
from app.db.postgres import AsyncSessionLocal
from app.db.redis import get_redis_client

logger = get_logger(__name__)

_bearer = HTTPBearer(auto_error=True)


# ── Database ──────────────────────────────────────────────────────────────────

async def get_db() -> AsyncSession:  # type: ignore[misc]
    """Yield an async SQLAlchemy session; always closed after request."""
    async with AsyncSessionLocal() as session:
        yield session


# ── Redis ─────────────────────────────────────────────────────────────────────

async def get_redis():  # type: ignore[misc]
    """Yield the shared async Redis client."""
    yield get_redis_client()


# ── Request metadata ──────────────────────────────────────────────────────────

class RequestMeta:
    """Holds request_id and timestamp for envelope construction."""

    def __init__(self, request_id: str, timestamp: str):
        self.request_id = request_id
        self.timestamp = timestamp


async def get_request_meta(request: Request) -> RequestMeta:
    """Return (or generate) request_id and a UTC ISO8601 timestamp.

    If the upstream gateway already set X-Request-ID, use it; otherwise generate.
    """
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    timestamp = datetime.now(UTC).isoformat()
    return RequestMeta(request_id=request_id, timestamp=timestamp)


# ── JWT / Auth ────────────────────────────────────────────────────────────────

class TokenClaims:
    """Parsed, validated JWT claims for the current request."""

    def __init__(self, payload: dict):
        self.user_id: str = payload["sub"]
        self.email: str = payload["email"]
        self.roles: list[str] = payload.get("roles", [])
        self.permissions: list[str] = payload.get("permissions", [])
        self.org_id: str | None = payload.get("org_id")
        self.workspace_id: str | None = payload.get("workspace_id")
        self.jti: str = payload["jti"]
        self.exp: int = payload["exp"]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    redis=Depends(get_redis),
) -> TokenClaims:
    """Validate JWT, check jti deny-list, return TokenClaims.

    Raises HTTP 401 on any failure (missing, expired, revoked, malformed token).
    Per Authentication.md §6 AC: must not specify whether token was revoked vs expired.
    """
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    jti = payload.get("jti")
    if not jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")

    # Deny-list check (jti-based revocation, Authentication.md §8.3)
    deny_key = f"jti:deny:{jti}"
    if await redis.exists(deny_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")

    return TokenClaims(payload)


# ── RBAC ──────────────────────────────────────────────────────────────────────

def require_roles(*required_roles: str):
    """Dependency factory: raise HTTP 403 if the token does not carry at least one required role.

    Authentication.md §8.3: RBAC evaluates roles first (coarse-grained), then permissions.
    """
    async def _check(claims: Annotated[TokenClaims, Depends(get_current_user)]) -> TokenClaims:
        if not any(r in claims.roles for r in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return claims

    return _check


def require_permissions(*required_perms: str):
    """Dependency factory: raise HTTP 403 if the token lacks all required permissions."""
    async def _check(claims: Annotated[TokenClaims, Depends(get_current_user)]) -> TokenClaims:
        if not any(p in claims.permissions for p in required_perms):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
            )
        return claims

    return _check
