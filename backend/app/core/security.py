"""NANFO Backend — JWT utility functions.

Implements the JWT Claim Baseline defined in Authentication.md §8:
  Required claims: sub, email, roles, permissions, iat, exp, jti
  Optional claims: org_id, workspace_id
  Session:         sid binds access and rotating refresh tokens to Redis state

Security guardrails (security.md):
  - Secrets loaded from config, never hardcoded.
  - hashed_password and credential derivatives NEVER appear in token payloads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt as _bcrypt
from jose import JWTError, jwt
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

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

class RefreshClaims(BaseModel):
    """Strict wire claims. Legacy tokens without a session require re-login."""

    model_config = ConfigDict(strict=True, extra="forbid")

    sub: StrictStr
    sid: StrictStr
    jti: StrictStr
    iat: StrictInt
    exp: StrictInt
    token_type: Literal["refresh"]
    org_id: StrictStr | None = None
    workspace_id: StrictStr | None = None

    @field_validator("sub", "sid", "jti", "org_id", "workspace_id")
    @classmethod
    def validate_uuid(cls, value: str | None) -> str | None:
        if value is not None:
            return str(uuid.UUID(value))
        return value

    @model_validator(mode="after")
    def validate_times(self):
        now = int(datetime.now(UTC).timestamp())
        if self.iat > now or self.iat < 0 or self.exp <= now or self.exp <= self.iat:
            raise ValueError("Invalid token lifetime")
        return self


class AccessClaims(RefreshClaims):
    token_type: Literal["access"]
    email: StrictStr
    roles: list[StrictStr]
    permissions: list[StrictStr]

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if not value or "@" not in value:
            raise ValueError("Invalid email")
        return value


def _settings():
    return get_settings()


def create_access_token(
    *,
    user_id: str,
    email: str,
    roles: list[str],
    permissions: list[str],
    sid: str | None = None,
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
        "sid": sid or str(uuid.uuid4()),
        "token_type": "access",
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


def create_refresh_token(
    *, user_id: str, sid: str | None = None, exp: int | None = None,
    org_id: str | None = None, workspace_id: str | None = None,
) -> tuple[str, str]:
    """Issue a refresh token, preserving the session's absolute expiry on rotation."""
    settings = _settings()
    now = datetime.now(UTC)
    expire = now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": exp if exp is not None else expire,
        "jti": jti,
        "sid": sid or str(uuid.uuid4()),
        "token_type": "refresh",
    }
    if org_id is not None:
        payload["org_id"] = org_id
    if workspace_id is not None:
        payload["workspace_id"] = workspace_id
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def decode_token(token: str, *, token_type: Literal["access", "refresh"] = "access") -> dict[str, Any]:
    """Decode and validate a JWT. Raises JWTError on any failure.

    Callers must additionally validate the current Redis session and user state.
    """
    settings = _settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        schema = AccessClaims if token_type == "access" else RefreshClaims
        return schema.model_validate(payload).model_dump(exclude_none=True)
    except (ValidationError, ValueError, TypeError) as exc:
        raise JWTError("Invalid token claims") from exc


def remaining_ttl_seconds(exp: int) -> int:
    """Calculate seconds remaining until token expiry (for deny-list TTL)."""
    now = datetime.now(UTC)
    expiry = datetime.fromtimestamp(exp, tz=UTC)
    delta = expiry - now
    return max(0, int(delta.total_seconds()))
