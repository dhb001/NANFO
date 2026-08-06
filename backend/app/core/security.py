"""NANFO Backend — JWT utility functions.

Implements the JWT Claim Baseline defined in Authentication.md §8:
  Required claims: sub, email, roles, permissions, iat, exp, jti
  Optional claims: org_id, workspace_id
  Revocation:      jti deny-list in Redis (TTL = remaining token lifetime)

Security guardrails (security.md):
  - Secrets loaded from config, never hardcoded.
  - hashed_password and credential derivatives NEVER appear in token payloads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt as _bcrypt

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# bcrypt rounds (cost factor) — 12 is the OWASP minimum recommendation
_BCRYPT_ROUNDS: int = 12


# ── Password utilities ────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the given plaintext password.

    Uses bcrypt.hashpw() directly — avoids passlib 1.7.4 incompatibility
    with bcrypt 4.0+ (which removed the __about__ attribute passlib relied on).
    """
    salt = _bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    hashed = _bcrypt.hashpw(plain.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plaintext matches the bcrypt hash."""
    return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

from jose import JWTError, jwt


def _settings():
    return get_settings()


def create_access_token(
    *,
    user_id: str,
    email: str,
    roles: list[str],
    permissions: list[str],
    org_id: str | None = None,
    workspace_id: str | None = None,
) -> tuple[str, str]:
    """Issue a signed JWT access token.

    Returns (token, jti). The jti is stored by the caller for revocation support.
    Implements Authentication.md §8.1 required claims and §8.2 optional claims.
    Claims excluded per §8.4: hashed_password, raw row IDs beyond user_id, sensitive PII.
    """
    settings = _settings()
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        # Standard JWT claims
        "sub": user_id,
        "iat": now,
        "exp": expire,
        "jti": jti,
        # NANFO custom required claims (Authentication.md §8.1)
        "email": email,
        "roles": roles,
        "permissions": permissions,
    }

    # Optional claims (Authentication.md §8.2) — only included when present
    if org_id is not None:
        payload["org_id"] = org_id
    if workspace_id is not None:
        payload["workspace_id"] = workspace_id

    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def create_refresh_token(*, user_id: str) -> tuple[str, str]:
    """Issue a signed JWT refresh token (contains only sub + jti + exp)."""
    settings = _settings()
    now = datetime.now(UTC)
    expire = now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": expire,
        "jti": jti,
        "token_type": "refresh",
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises JWTError on any failure.

    Callers must additionally check the jti deny-list in Redis for revoked tokens.
    """
    settings = _settings()
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def remaining_ttl_seconds(exp: int) -> int:
    """Calculate seconds remaining until token expiry (for deny-list TTL)."""
    now = datetime.now(UTC)
    expiry = datetime.fromtimestamp(exp, tz=UTC)
    delta = expiry - now
    return max(0, int(delta.total_seconds()))
