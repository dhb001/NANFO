"""NANFO Backend — JWT and password utility functions.

Implements the JWT Claim Baseline defined in Authentication.md §8 with PyJWT
(ADR-028 C10; python-jose removed):
  Required claims:   sub, email, roles, permissions, iat, exp, jti
  Optional claims:   org_id, workspace_id
  Session:           sid binds access and rotating refresh tokens to Redis state
  Transport claims:  iss="nanfo-api", aud="nanfo" are always issued and always
                     required on decode (30 s leeway); they are verified by PyJWT
                     and stripped from the returned claim dictionary.

Key handling (ADR-028 C10/C19):
  - Tokens are always signed with ``JWT_SECRET_KEY`` and verified against the
    current key, then each verify-only ``JWT_PREVIOUS_SECRET_KEYS`` entry, so the
    signing key can roll without logging users out.
  - Algorithms are restricted to HS256/HS384/HS512 and exactly the configured
    ``JWT_ALGORITHM`` is accepted (no ``none``, no algorithm confusion).
  - Services started without a signing key (``NANFO_SERVICE_ROLE=worker``)
    raise a clear ``RuntimeError`` if they attempt to issue or verify tokens.

Passwords (ADR-028 C11): bcrypt only considers 72 bytes. ``hash_password``
rejects longer secrets and ``verify_password`` never lets an over-long secret
authenticate as its 72-byte prefix.

Security guardrails (security.md):
  - Secrets loaded from config, never hardcoded.
  - hashed_password and credential derivatives NEVER appear in token payloads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt as _bcrypt
import jwt
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

# Historical public name. Every PyJWT failure (signature, expiry, issuer,
# audience, algorithm, malformed claims) derives from PyJWTError; app.main maps
# it to the canonical 401 envelope.
JWTError = jwt.PyJWTError

TOKEN_ISSUER = "nanfo-api"
TOKEN_AUDIENCE = "nanfo"
TOKEN_LEEWAY_SECONDS = 30
ALLOWED_JWT_ALGORITHMS: tuple[str, ...] = ("HS256", "HS384", "HS512")
_REQUIRED_REGISTERED_CLAIMS: tuple[str, ...] = ("exp", "iat", "sub", "jti", "iss", "aud")

# bcrypt rounds (cost factor) — 12 is the OWASP minimum recommendation
_BCRYPT_ROUNDS: int = 12
# bcrypt ignores every byte after the 72nd; bcrypt 4.x truncates silently.
BCRYPT_MAX_PASSWORD_BYTES: int = 72

__all__ = [
    "ALLOWED_JWT_ALGORITHMS",
    "BCRYPT_MAX_PASSWORD_BYTES",
    "JWTError",
    "TOKEN_AUDIENCE",
    "TOKEN_ISSUER",
    "TOKEN_LEEWAY_SECONDS",
    "AccessClaims",
    "RefreshClaims",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "password_within_bcrypt_limit",
    "remaining_ttl_seconds",
    "verify_password",
]


# ── Password utilities ────────────────────────────────────────────────────────

def _password_bytes(plain: str) -> bytes | None:
    try:
        return plain.encode("utf-8")
    except (UnicodeEncodeError, AttributeError):
        return None


def password_within_bcrypt_limit(plain: str) -> bool:
    """Return True when bcrypt will consider every byte of ``plain``."""
    encoded = _password_bytes(plain)
    return encoded is not None and len(encoded) <= BCRYPT_MAX_PASSWORD_BYTES


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the given plaintext password.

    Uses bcrypt.hashpw() directly — avoids passlib 1.7.4 incompatibility
    with bcrypt 4.0+ (which removed the __about__ attribute passlib relied on).
    Raises ValueError for secrets bcrypt would silently truncate (>72 UTF-8 bytes).
    """
    encoded = _password_bytes(plain)
    if encoded is None:
        raise ValueError("Password must be valid UTF-8 text.")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"Password exceeds the {BCRYPT_MAX_PASSWORD_BYTES}-byte bcrypt limit.")
    salt = _bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return _bcrypt.hashpw(encoded, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plaintext matches the bcrypt hash.

    An over-long (or non-encodable) secret never authenticates: bcrypt 4.x would
    otherwise accept any secret sharing the stored password's 72-byte prefix.
    One full-cost comparison is still performed so response time does not
    reveal the length policy.
    """
    stored = hashed.encode("utf-8")
    encoded = _password_bytes(plain)
    if encoded is None or len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        _bcrypt.checkpw((encoded or b"")[:BCRYPT_MAX_PASSWORD_BYTES], stored)
        return False
    return _bcrypt.checkpw(encoded, stored)


# ── Claim schemas ─────────────────────────────────────────────────────────────

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
        # Same 30 s clock-skew allowance PyJWT applies to exp/iat.
        now = int(datetime.now(UTC).timestamp())
        if (
            self.iat < 0
            or self.exp <= self.iat
            or self.iat > now + TOKEN_LEEWAY_SECONDS
            or self.exp <= now - TOKEN_LEEWAY_SECONDS
        ):
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


# ── Key and algorithm configuration ───────────────────────────────────────────

def _settings():
    return get_settings()


def _secret_text(value: object) -> str | None:
    """Return a usable secret string, unwrapping SecretStr; None when unset/blank."""
    if value is None:
        return None
    reveal = getattr(value, "get_secret_value", None)
    if callable(reveal):
        value = reveal()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    text = value if isinstance(value, str) else str(value)
    return text if text.strip() else None


def _previous_secrets(value: object) -> list[str]:
    """Parse verify-only JWT_PREVIOUS_SECRET_KEYS (comma-separated text or a sequence)."""
    if value is None:
        return []
    reveal = getattr(value, "get_secret_value", None)
    if callable(reveal):
        value = reveal()
    if isinstance(value, str):
        candidates: list[object] = list(value.split(","))
    elif isinstance(value, (list, tuple, set, frozenset)):
        candidates = list(value)
    else:
        candidates = [value]
    secrets: list[str] = []
    for candidate in candidates:
        text = _secret_text(candidate)
        if text is not None and text.strip():
            secrets.append(text.strip())
    return secrets


def _signing_key(settings) -> str:
    key = _secret_text(getattr(settings, "JWT_SECRET_KEY", None))
    if key is None:
        role = getattr(settings, "NANFO_SERVICE_ROLE", None)
        scope = f" for NANFO_SERVICE_ROLE={role}" if role else ""
        raise RuntimeError(
            f"JWT_SECRET_KEY is not configured{scope}; this process cannot issue or verify tokens."
        )
    return key


def _verification_keys(settings) -> list[str]:
    keys = [_signing_key(settings)]
    for previous in _previous_secrets(getattr(settings, "JWT_PREVIOUS_SECRET_KEYS", None)):
        if previous not in keys:
            keys.append(previous)
    return keys


def _algorithm(settings) -> str:
    algorithm = str(getattr(settings, "JWT_ALGORITHM", "HS256") or "")
    if algorithm not in ALLOWED_JWT_ALGORITHMS:
        raise RuntimeError(f"JWT_ALGORITHM must be one of {', '.join(ALLOWED_JWT_ALGORITHMS)}.")
    return algorithm


def _encode(payload: dict[str, Any]) -> str:
    settings = _settings()
    return jwt.encode(
        {**payload, "iss": TOKEN_ISSUER, "aud": TOKEN_AUDIENCE},
        _signing_key(settings),
        algorithm=_algorithm(settings),
    )


# ── Token issuance ────────────────────────────────────────────────────────────

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

    return _encode(payload), jti


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
    return _encode(payload), jti


# ── Token verification ────────────────────────────────────────────────────────

def decode_token(token: str, *, token_type: Literal["access", "refresh"] = "access") -> dict[str, Any]:
    """Decode and validate a JWT. Raises JWTError (PyJWTError) on any failure.

    exp/iat/sub/jti/iss/aud are required (30 s leeway); the signature must match
    the current key or one verify-only previous key. Returned claims exclude the
    constant iss/aud transport claims. Callers must additionally validate the
    current Redis session and user state.
    """
    settings = _settings()
    algorithm = _algorithm(settings)
    keys = _verification_keys(settings)
    if not isinstance(token, str) or not token:
        raise jwt.InvalidTokenError("Invalid token")

    payload: dict[str, Any] | None = None
    for position, key in enumerate(keys):
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=TOKEN_AUDIENCE,
                issuer=TOKEN_ISSUER,
                leeway=TOKEN_LEEWAY_SECONDS,
                options={"require": list(_REQUIRED_REGISTERED_CLAIMS), "strict_aud": True},
            )
            break
        except jwt.InvalidSignatureError:
            # Only a signature mismatch may fall through to an older key; expiry,
            # issuer, audience and malformed claims fail immediately.
            if position == len(keys) - 1:
                raise
    if payload is None:  # pragma: no cover - loop either assigns or raises
        raise jwt.InvalidTokenError("Invalid token")

    claims = {key: value for key, value in payload.items() if key not in ("iss", "aud")}
    try:
        schema = AccessClaims if token_type == "access" else RefreshClaims
        return schema.model_validate(claims).model_dump(exclude_none=True)
    except (ValidationError, ValueError, TypeError) as exc:
        raise jwt.InvalidTokenError("Invalid token claims") from exc


def remaining_ttl_seconds(exp: int) -> int:
    """Calculate seconds remaining until token expiry (for deny-list TTL)."""
    now = datetime.now(UTC)
    expiry = datetime.fromtimestamp(exp, tz=UTC)
    delta = expiry - now
    return max(0, int(delta.total_seconds()))
