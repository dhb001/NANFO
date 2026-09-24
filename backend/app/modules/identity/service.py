"""NANFO Backend — Identity module service layer.

AuthService: login, logout, refresh, me and session revocation.
Implements:
  - Login throttling (Authentication.md §5, ADR-028 C11): the per-IP bucket
    counts every attempt; the per-email bucket (keyed by a SHA-256 of the
    normalized address, never the raw email) counts failed attempts only and is
    cleared on success; only the first throttled attempt per window is audited.
  - JWT issuance with full claim baseline (Authentication.md §8, ADR-028 C10)
  - Redis session families with atomic rotation, a 20 s retry grace, reuse
    detection, sliding idle expiry and a per-user session index (ADR-028 C9)
  - Audit log writes for auth events (Authentication.md §2, §6). Audits that
    follow an already-committed session change are best-effort: they are logged
    and rolled back on failure but never change the authentication outcome.
  - Event publication for auth domain events (EventAPI.md)
IdentityAccountService: deactivation, password change and role replacement; each
  revokes every session of the user after commit (ADR-028 C9).
IdentityDirectoryService: read-only identity lookups for other modules.

Each authorization loads the user and its roles exactly once (permissions come
from the declared policy). ``/auth/me`` reuses the identity loaded by request
authentication; every other identity read stays fresh.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.correlation import normalize_audit_correlation  # re-exported (ADR-028)
from app.core.errors import DependencyUnavailableError
from app.core.logging import get_logger
from app.core.request_context import normalize_request_id
from app.core.security import (
    JWTError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    password_within_bcrypt_limit,
    verify_password,
)
from app.events.publisher import publish_event
from app.modules.identity.policy import is_capability_downgrade
from app.modules.identity.repository import AuditLogRepository, UserRepository
from app.modules.identity.schemas import TokenPair, UserProfile
from app.modules.identity.sessions import RefreshTokenReuse, SessionRepository, invalid_session

logger = get_logger(__name__)

__all__ = [
    "SESSION_REVOCATION_REASONS",
    "AuthService",
    "IdentityAccountService",
    "IdentityDirectoryService",
    "IdentitySnapshot",
    "append_audit_log",
    "login_email_bucket_key",
    "login_ip_bucket_key",
    "normalize_audit_correlation",
]

# Public, non-account hash at the same cost as hash_password (12 rounds).
# Missing users still incur one bcrypt check; this is not an account credential.
_DUMMY_PASSWORD_HASH = "$2b$12$B5Pqr01aw1aZiGdFIoc8oOwOrCfvhI3/N26ouHW060.2Q8REvU1iG"

_STORE_FAILURES = (RedisError, RuntimeError, OSError)
_INVALID_TOKEN_DETAIL = "Invalid or expired token."

SESSION_REVOCATION_REASONS = frozenset({
    "deactivated", "password_changed", "role_downgrade", "operator_request",
})


async def append_audit_log(
    *, db: AsyncSession, event_type: str, actor_id: uuid.UUID | None,
    resource_type: str | None, resource_id: uuid.UUID | None, correlation_id: str | uuid.UUID,
    metadata: dict, org_id: uuid.UUID | None = None, event_id: uuid.UUID | None = None,
) -> None:
    """Public append boundary; caller commits audit and owned mutation atomically."""
    correlation_id, metadata = normalize_audit_correlation(correlation_id, metadata)
    await AuditLogRepository(db).append(
        event_type=event_type, actor_id=actor_id, resource_type=resource_type,
        resource_id=resource_id, correlation_id=correlation_id, metadata=metadata,
        org_id=org_id, event_id=event_id,
    )


# ── Login throttle keys (ADR-028 C11) ─────────────────────────────────────────

def login_ip_bucket_key(ip_address: str) -> str:
    """Fixed-window bucket counting every login attempt from one client address."""
    return f"ratelimit:login:{ip_address}"


def login_email_digest(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def login_email_bucket_key(email: str) -> str:
    """Fixed-window bucket counting failed attempts for one (hashed) account address."""
    return f"ratelimit:login:email:{login_email_digest(email)}"


def _throttle_audit_marker(bucket_key: str) -> str:
    # Outside the ratelimit:login:* namespace so markers never look like buckets.
    return "ratelimit:login-audited:" + bucket_key.removeprefix("ratelimit:login:")


# ── Request-scoped current identity ───────────────────────────────────────────

@dataclass(frozen=True)
class IdentitySnapshot:
    """Current identity, global roles and declared permissions of one user."""

    user_id: uuid.UUID
    email: str
    display_name: str | None
    is_active: bool
    roles: tuple[str, ...]
    permissions: tuple[str, ...]


_IDENTITY_MEMO_KEY = "nanfo.identity.snapshots"


def _identity_memo(db) -> dict | None:
    """Per-session (per-request) memo; disabled for sessions without an info dict."""
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return None
    memo = info.get(_IDENTITY_MEMO_KEY)
    if not isinstance(memo, dict):
        memo = info[_IDENTITY_MEMO_KEY] = {}
    return memo


def forget_identity(db, user_id: uuid.UUID | None = None) -> None:
    """Drop memoized identity after an account mutation in the same session."""
    memo = _identity_memo(db)
    if memo is None:
        return
    if user_id is None:
        memo.clear()
    else:
        memo.pop(user_id, None)


async def load_identity_snapshot(
    db, users: UserRepository, user_id: uuid.UUID, *, reuse_request_identity: bool = False,
) -> IdentitySnapshot | None:
    """Load user and roles (one query each); permissions come from the declared policy.

    Every load records the snapshot for the session. Only callers that opt in with
    ``reuse_request_identity`` (the profile read right after request
    authentication) reuse it; every other read is fresh, so deliberate re-checks
    after lock waits still observe revocations.
    """
    memo = _identity_memo(db)
    if reuse_request_identity and memo is not None and user_id in memo:
        return memo[user_id]
    user = await users.get_by_id(user_id)
    snapshot = None
    if user is not None:
        active = bool(user.is_active)
        roles = await users.get_roles_for_user(user) if active else []
        permissions = await users.get_permissions_for_roles(roles) if active else []
        snapshot = IdentitySnapshot(
            user_id=user.user_id, email=user.email, display_name=getattr(user, "display_name", None),
            is_active=active, roles=tuple(roles), permissions=tuple(permissions),
        )
    if memo is not None:
        memo[user_id] = snapshot
    return snapshot


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class AuthService:

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._user_repo = UserRepository(db)
        self._audit_repo = AuditLogRepository(db)
        self._sessions = SessionRepository(redis)

    async def _identity(self, user_id: uuid.UUID, *, reuse_request_identity: bool = False) -> IdentitySnapshot | None:
        return await load_identity_snapshot(self._db, self._user_repo, user_id,
                                            reuse_request_identity=reuse_request_identity)

    async def _discard_family(self, sid: str, user_id: str, *, reason: str) -> None:
        """Delete a session family whose account is gone/inactive; denial never depends on it."""
        try:
            await self._sessions.revoke(sid, user_id)
        except DependencyUnavailableError:
            logger.warning("auth_session_family_discard_failed", session_id=sid, reason=reason)

    async def _append_best_effort(self, *, failure_log: str, **entry) -> None:
        """Audit after an irreversible session change: log + rollback, never fail the request."""
        try:
            await self._audit_repo.append(**entry)
            await self._db.commit()
        except Exception as exc:  # noqa: BLE001 - the auth outcome is already decided
            logger.warning(failure_log, event_type=entry.get("event_type"), error_type=type(exc).__name__)
            try:
                await self._db.rollback()
            except Exception as rollback_exc:  # noqa: BLE001
                logger.warning("auth_audit_rollback_failed", event_type=entry.get("event_type"),
                               error_type=type(rollback_exc).__name__)

    async def _publish_best_effort(self, *, event_type: str, payload: dict, correlation_id: str,
                                   failure_log: str, **log_fields) -> None:
        try:
            await publish_event(
                redis=self._redis, event_type=event_type, source="auth",
                payload=payload, correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(failure_log, correlation_id=correlation_id, error=str(exc), **log_fields)

    async def authenticate_access(self, token: str) -> dict:
        """Shared REST/WS identity check; signed role snapshots are not authoritative."""
        try:
            claims = decode_token(token)
        except JWTError:
            raise invalid_session() from None
        await self._sessions.validate(claims)
        snapshot = await self._identity(uuid.UUID(claims["sub"]))
        if snapshot is None or not snapshot.is_active:
            await self._discard_family(claims["sid"], claims["sub"], reason="inactive_user")
            raise invalid_session()
        claims.update(email=snapshot.email, roles=list(snapshot.roles), permissions=list(snapshot.permissions))
        return claims

    # ── Login ─────────────────────────────────────────────────────────────────

    async def _first_throttle_in_window(self, bucket_key: str, ttl_ms: object, window_seconds: int) -> bool:
        """SET NX marker aligned with the bucket window: audit one throttled attempt per window."""
        expiry_ms = ttl_ms if isinstance(ttl_ms, int) and ttl_ms > 0 else window_seconds * 1000
        try:
            return bool(await self._redis.set(_throttle_audit_marker(bucket_key), "1", px=expiry_ms, nx=True))
        except _STORE_FAILURES:
            logger.warning("login_throttle_marker_unavailable")
            return True  # cannot prove this is a repeat: audit it

    async def login(
        self,
        email: str,
        password: str,
        ip_address: str,
        correlation_id: str,
    ) -> TokenPair:
        """Authenticate user and issue JWT pair. Throttled per IP and per email.

        Authentication.md §6 AC: 401 must not indicate whether email or password was wrong.
        All outcomes are appended to audit_logs (throttling: first attempt per window).
        """
        correlation_id = normalize_request_id(correlation_id)
        audit_correlation_id, audit_metadata = normalize_audit_correlation(
            correlation_id, {"ip_address": ip_address},
        )
        settings = get_settings()
        limit = settings.RATE_LIMIT_LOGIN_MAX_ATTEMPTS
        window = settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS
        email_digest = login_email_digest(email)
        ip_key = login_ip_bucket_key(ip_address)
        email_key = f"ratelimit:login:email:{email_digest}"

        # ── Throttling (Authentication.md §5, ADR-028 C11) ────────────────────
        limited_by: str | None = None
        bucket_key, bucket_ttl_ms = ip_key, None
        try:
            # MULTI/EXEC prevents cancellation/disconnect between INCR and EXPIRE.
            # Redis 7 EXPIRE NX preserves fixed windows and repairs legacy no-TTL keys.
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(ip_key)
                pipe.expire(ip_key, window, nx=True)
                pipe.pttl(ip_key)
                ip_count, _, ip_ttl_ms = await pipe.execute()
            if ip_count > limit:
                limited_by, bucket_key, bucket_ttl_ms = "ip", ip_key, ip_ttl_ms
            else:
                # Reserve a failure slot atomically (concurrency-safe); cleared on success.
                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe.incr(email_key)
                    pipe.expire(email_key, window, nx=True)
                    pipe.pttl(email_key)
                    email_count, _, email_ttl_ms = await pipe.execute()
                if email_count > limit:
                    limited_by, bucket_key, bucket_ttl_ms = "email", email_key, email_ttl_ms
        except _STORE_FAILURES as exc:
            raise DependencyUnavailableError("redis") from exc

        if limited_by is not None:
            logger.warning("login_rate_limited", ip=ip_address, email_sha256=email_digest[:16], limited_by=limited_by)
            if await self._first_throttle_in_window(bucket_key, bucket_ttl_ms, window):
                await self._append_best_effort(
                    failure_log="auth_login_throttle_audit_failed",
                    event_type="auth.user.login_failed",
                    actor_id=None,
                    org_id=None,
                    correlation_id=audit_correlation_id,
                    metadata={**audit_metadata, "reason": "rate_limited", "limited_by": limited_by},
                )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Please try again later.",
            )

        # ── Credential validation ─────────────────────────────────────────────
        user = await self._user_repo.get_by_email(email)
        # bcrypt would silently truncate >72 bytes: such secrets only ever meet the dummy hash.
        within_limit = password_within_bcrypt_limit(password)
        candidate_hash = user.hashed_password if user is not None and within_limit else _DUMMY_PASSWORD_HASH
        password_valid = await run_in_threadpool(verify_password, password, candidate_hash)
        invalid = user is None or not within_limit or not password_valid or not user.is_active

        if invalid:
            # Intentionally generic error — do not reveal whether email or password failed
            await self._audit_repo.append(
                event_type="auth.user.login_failed",
                actor_id=user.user_id if user else None,
                org_id=None,
                correlation_id=audit_correlation_id,
                metadata={**audit_metadata, "reason": "invalid_credentials"},
            )
            await self._db.commit()
            await self._publish_best_effort(
                event_type="auth.user.login_failed", payload={"ip_address": ip_address},
                correlation_id=correlation_id, failure_log="auth_login_failed_event_publish_failed",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials.",
            )

        # ── Issue tokens ──────────────────────────────────────────────────────
        roles = await self._user_repo.get_roles_for_user(user)
        permissions = await self._user_repo.get_permissions_for_roles(roles)

        sid = str(uuid.uuid4())
        access_token, _access_jti = create_access_token(
            sid=sid,
            user_id=str(user.user_id),
            email=user.email,
            roles=roles,
            permissions=permissions,
        )
        refresh_token, _ = create_refresh_token(user_id=str(user.user_id), sid=sid)
        await self._sessions.create(decode_token(refresh_token, token_type="refresh"), refresh_token)

        # ── Audit log + event publication ─────────────────────────────────────
        try:
            await self._audit_repo.append(
                event_type="auth.user.logged_in",
                actor_id=user.user_id,
                org_id=None,
                correlation_id=audit_correlation_id,
                metadata=audit_metadata,
            )
            await self._db.commit()
        except BaseException:
            # No unaudited session may survive a failed login response.
            await self._discard_family(sid, str(user.user_id), reason="login_audit_failed")
            raise

        try:
            # Failed attempts only: a successful login clears the per-email bucket.
            await self._redis.delete(email_key)
        except _STORE_FAILURES:
            logger.warning("login_email_bucket_clear_failed", email_sha256=email_digest[:16])

        await self._publish_best_effort(
            event_type="auth.user.logged_in",
            payload={"user_id": str(user.user_id), "ip_address": ip_address},
            correlation_id=correlation_id, failure_log="auth_logged_in_event_publish_failed",
            user_id=str(user.user_id),
        )

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    # ── Logout ────────────────────────────────────────────────────────────────

    async def logout(self, jti: str, exp: int, user_id: str, correlation_id: str, sid: str) -> None:
        """Revoke every access/refresh token associated with the login session."""
        correlation_id = normalize_request_id(correlation_id)
        audit_correlation_id, audit_metadata = normalize_audit_correlation(correlation_id, {"jti": jti})
        await self._sessions.revoke(sid, user_id)

        # Audit log
        await self._audit_repo.append(
            event_type="auth.user.logged_out",
            actor_id=uuid.UUID(user_id),
            correlation_id=audit_correlation_id,
            metadata=audit_metadata,
        )
        await self._db.commit()
        await self._publish_best_effort(
            event_type="auth.user.logged_out", payload={"user_id": user_id, "jti": jti},
            correlation_id=correlation_id, failure_log="auth_logged_out_event_publish_failed",
            user_id=user_id,
        )

    # ── Refresh ───────────────────────────────────────────────────────────────

    async def _audit_refresh_failure(
        self, *, reason: str, ip_address: str | None, correlation_id: str,
        audit_correlation_id: uuid.UUID, audit_metadata: dict,
        user_id: str | None = None, session_id: str | None = None,
    ) -> None:
        """Audit a rejected refresh once per (reason, client, session) per throttle window.

        The endpoint is unauthenticated; the marker bounds audit amplification while
        every rejection is still logged.
        """
        window = get_settings().RATE_LIMIT_LOGIN_WINDOW_SECONDS
        marker = f"auth:refresh-failure-audited:{reason}:{ip_address or 'unknown'}:{session_id or '-'}"
        try:
            first = bool(await self._redis.set(marker, "1", ex=window, nx=True))
        except _STORE_FAILURES:
            first = True
        logger.warning("auth_refresh_rejected", reason=reason, ip=ip_address, session_id=session_id,
                       user_id=user_id, request_id=correlation_id, audited=first)
        if not first:
            return
        await self._append_best_effort(
            failure_log="auth_refresh_failure_audit_failed",
            event_type="auth.token.refresh_failed",
            actor_id=uuid.UUID(user_id) if user_id else None,
            resource_type="auth_session" if session_id else None,
            resource_id=uuid.UUID(session_id) if session_id else None,
            correlation_id=audit_correlation_id,
            metadata={**audit_metadata, "reason": reason},
        )

    async def refresh(self, refresh_token: str, correlation_id: str, *, ip_address: str | None = None) -> TokenPair:
        """Consume a refresh token once; a spent token is idempotent only inside the grace.

        Re-presenting the token rotated ≤20 s ago returns the same issued pair.
        Any other reuse revokes the family and is audited ``auth.token.reuse_detected``.
        """
        correlation_id = normalize_request_id(correlation_id)
        audit_correlation_id, audit_metadata = normalize_audit_correlation(
            correlation_id, {"ip_address": ip_address} if ip_address else {},
        )
        failure = {"ip_address": ip_address, "correlation_id": correlation_id,
                   "audit_correlation_id": audit_correlation_id, "audit_metadata": audit_metadata}
        try:
            payload = decode_token(refresh_token, token_type="refresh")
        except JWTError:
            await self._audit_refresh_failure(reason="invalid_token", **failure)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_TOKEN_DETAIL) from None

        sid, user_id = payload["sid"], payload["sub"]
        try:
            entry = await self._sessions.validate(payload)
        except HTTPException:
            await self._audit_refresh_failure(reason="session_invalid", user_id=user_id, session_id=sid, **failure)
            raise

        snapshot = await self._identity(uuid.UUID(user_id))
        if snapshot is None or not snapshot.is_active:
            await self._discard_family(sid, user_id, reason="inactive_user")
            await self._audit_refresh_failure(reason="inactive_user", user_id=user_id, session_id=sid, **failure)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_TOKEN_DETAIL)

        settings = get_settings()
        expires_in = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        access_token, _ = create_access_token(
            sid=sid,
            org_id=payload.get("org_id"),
            workspace_id=payload.get("workspace_id"),
            user_id=user_id,
            email=snapshot.email,
            roles=list(snapshot.roles),
            permissions=list(snapshot.permissions),
        )
        new_refresh_token, _ = create_refresh_token(
            user_id=user_id, sid=sid, exp=entry["exp"],
            org_id=payload.get("org_id"), workspace_id=payload.get("workspace_id"),
        )
        try:
            outcome = await self._sessions.rotate(
                payload, refresh_token,
                decode_token(new_refresh_token, token_type="refresh"), new_refresh_token,
                access_token=access_token, expires_in=expires_in,
            )
        except RefreshTokenReuse:
            logger.warning("auth_refresh_token_reuse_detected", session_id=sid, user_id=user_id,
                           ip=ip_address, request_id=correlation_id)
            await self._append_best_effort(
                failure_log="auth_reuse_audit_failed",
                event_type="auth.token.reuse_detected",
                actor_id=uuid.UUID(user_id),
                resource_type="auth_session",
                resource_id=uuid.UUID(sid),
                correlation_id=audit_correlation_id,
                metadata={**audit_metadata, "session_id": sid},
            )
            raise
        except HTTPException:
            await self._audit_refresh_failure(reason="session_invalid", user_id=user_id, session_id=sid, **failure)
            raise

        # The rotation is committed in Redis: auditing can no longer change the outcome.
        await self._append_best_effort(
            failure_log="auth_token_refresh_audit_failed",
            event_type="auth.token.refreshed",
            actor_id=uuid.UUID(user_id),
            correlation_id=audit_correlation_id,
            metadata={**audit_metadata, "retry_grace": True} if outcome.replayed else audit_metadata,
        )
        if not outcome.replayed:
            await self._publish_best_effort(
                event_type="auth.token.refreshed", payload={"user_id": user_id},
                correlation_id=correlation_id, failure_log="auth_token_refreshed_event_publish_failed",
                user_id=user_id,
            )
        return TokenPair(
            access_token=outcome.pair.access_token,
            refresh_token=outcome.pair.refresh_token,
            token_type="bearer",
            expires_in=outcome.pair.expires_in,
        )

    # ── Profile and session revocation ────────────────────────────────────────

    async def get_profile(self, user_id: str, *, reuse_request_identity: bool = False) -> UserProfile:
        """Return the user's current profile and permissions.

        ``reuse_request_identity`` lets the caller reuse the identity this request
        already authenticated (``/auth/me``); by default the read is fresh.
        """
        snapshot = await self._identity(_as_uuid(user_id), reuse_request_identity=reuse_request_identity)
        if snapshot is None or not snapshot.is_active:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        return UserProfile(
            user_id=snapshot.user_id,
            email=snapshot.email,
            display_name=snapshot.display_name,
            roles=list(snapshot.roles),
            permissions=list(snapshot.permissions),
        )

    async def revoke_user_sessions(
        self,
        user_id: uuid.UUID | str,
        *,
        reason: str,
        correlation_id: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> int:
        """Revoke every indexed session family of a user and audit it (ADR-028 C9).

        Returns the number of families removed. Raises DependencyUnavailableError
        when Redis is unavailable (revocation must never be silently skipped).
        """
        if reason not in SESSION_REVOCATION_REASONS:
            raise ValueError(f"Unsupported session revocation reason: {reason!r}.")
        subject = _as_uuid(user_id)
        correlation_id = normalize_request_id(correlation_id)
        revoked = await self._sessions.revoke_user(str(subject))
        audit_correlation_id, metadata = normalize_audit_correlation(
            correlation_id, {"reason": reason, "revoked_sessions": revoked},
        )
        await self._audit_repo.append(
            event_type="auth.user.sessions_revoked",
            actor_id=actor_id or subject,
            resource_type="user",
            resource_id=subject,
            correlation_id=audit_correlation_id,
            metadata=metadata,
        )
        await self._db.commit()
        logger.info("auth_user_sessions_revoked", user_id=str(subject), reason=reason, revoked_sessions=revoked)
        return revoked


class IdentityAccountService:
    """Account mutations that end every session of the affected user (ADR-028 C9).

    The database change and its audit commit first; sessions are then revoked
    through the per-user index. A Redis outage surfaces as 503 after the durable
    change (re-run ``scripts.revoke_user_sessions``); access is still denied
    because every request reloads current identity.
    """

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._users = UserRepository(db)
        self._audit = AuditLogRepository(db)
        self._auth = AuthService(db, redis)

    async def _audit_change(self, *, event_type: str, subject: uuid.UUID, actor_id: uuid.UUID | None,
                            correlation_id: str, metadata: dict) -> None:
        audit_correlation_id, audit_metadata = normalize_audit_correlation(correlation_id, metadata)
        await self._audit.append(
            event_type=event_type, actor_id=actor_id or subject, resource_type="user",
            resource_id=subject, correlation_id=audit_correlation_id, metadata=audit_metadata,
        )

    async def deactivate_user(
        self, user_id: uuid.UUID | str, *, actor_id: uuid.UUID | None = None, correlation_id: str | None = None,
    ) -> int:
        subject = _as_uuid(user_id)
        correlation_id = normalize_request_id(correlation_id)
        changed = await self._users.set_active(subject, False)
        if not changed and await self._users.get_by_id(subject) is None:
            raise LookupError("User not found.")
        if changed:
            await self._audit_change(event_type="auth.user.deactivated", subject=subject, actor_id=actor_id,
                                     correlation_id=correlation_id, metadata={})
        await self._db.commit()
        forget_identity(self._db, subject)
        return await self._auth.revoke_user_sessions(
            subject, reason="deactivated", correlation_id=correlation_id, actor_id=actor_id,
        )

    async def change_password(
        self, user_id: uuid.UUID | str, new_password: str, *,
        actor_id: uuid.UUID | None = None, correlation_id: str | None = None,
    ) -> int:
        subject = _as_uuid(user_id)
        correlation_id = normalize_request_id(correlation_id)
        hashed = await run_in_threadpool(hash_password, new_password)  # ValueError beyond 72 bytes
        if not await self._users.set_password_hash(subject, hashed):
            raise LookupError("User not found.")
        await self._audit_change(event_type="auth.user.password_changed", subject=subject, actor_id=actor_id,
                                 correlation_id=correlation_id, metadata={})
        await self._db.commit()
        forget_identity(self._db, subject)
        return await self._auth.revoke_user_sessions(
            subject, reason="password_changed", correlation_id=correlation_id, actor_id=actor_id,
        )

    async def replace_roles(
        self, user_id: uuid.UUID | str, roles: Iterable[str], *,
        actor_id: uuid.UUID | None = None, correlation_id: str | None = None,
    ) -> int:
        """Replace global roles; any lost role or capability revokes every session."""
        subject = _as_uuid(user_id)
        correlation_id = normalize_request_id(correlation_id)
        if await self._users.get_by_id(subject) is None:
            raise LookupError("User not found.")
        before, after = await self._users.replace_roles(subject, roles)
        await self._audit_change(event_type="auth.user.roles_changed", subject=subject, actor_id=actor_id,
                                 correlation_id=correlation_id, metadata={"before": before, "after": after})
        await self._db.commit()
        forget_identity(self._db, subject)
        if not is_capability_downgrade(before, after):
            return 0
        return await self._auth.revoke_user_sessions(
            subject, reason="role_downgrade", correlation_id=correlation_id, actor_id=actor_id,
        )


class IdentityDirectoryService:
    """Read-only identity lookup contract for cross-module validation flows."""

    def __init__(self, db: AsyncSession):
        self._db = db
        self._user_repo = UserRepository(db)

    async def user_exists(self, user_id: uuid.UUID) -> bool:
        snapshot = await load_identity_snapshot(self._db, self._user_repo, _as_uuid(user_id))
        return snapshot is not None and snapshot.is_active

    async def can_administer_organization(self, user_id: uuid.UUID) -> bool:
        """Check live identity capability; Organization owns the org-role check."""
        snapshot = await load_identity_snapshot(self._db, self._user_repo, _as_uuid(user_id))
        return snapshot is not None and snapshot.is_active and "write:config" in snapshot.permissions
