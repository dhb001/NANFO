"""Redis-owned session families with optimistic, atomic refresh rotation.

ADR-028 contracts implemented here:

* **C2** — session-store failures raise ``DependencyUnavailableError("redis")``
  (HTTP 503 + Retry-After). Only genuine authentication failures are 401.
* **C9 retry grace** — a successful rotation seals the issued pair under
  ``auth:rotation:<sha256(presented refresh token)>`` for 20 s. Re-presenting
  that exact token inside the window (lost response, concurrent tab) returns the
  *same* pair, provided it is still the family head. Any other spent token is
  reuse: the family is revoked and ``RefreshTokenReuse`` (401) is raised so the
  caller can audit ``auth.token.reuse_detected``. The pair is AES-GCM sealed with
  a key derived from the presented token; Redis never stores a usable token.
* **C9 lifetime** — sessions expire after an idle period without refresh
  (default 12 h, sliding on each rotation) and never outlive the absolute
  refresh expiry (default 30 days).
* **C9 per-user index** — sorted set ``auth:user_sessions:<user_id>`` (member =
  sid, score = the session key's current expiry) maintained on create, rotate
  and logout so deactivation, password change and role downgrade can revoke
  every session of a user.
* WATCH contention is retried a bounded number of times, then 503.

The access-token ``jti:deny:*`` lookup was removed: nothing writes those keys.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from redis.exceptions import RedisError, WatchError

from app.core.config import get_settings
from app.core.errors import DependencyUnavailableError

SESSION_KEY_PREFIX = "auth:session:"
USER_INDEX_KEY_PREFIX = "auth:user_sessions:"
ROTATION_KEY_PREFIX = "auth:rotation:"

DEFAULT_IDLE_TIMEOUT_SECONDS = 12 * 60 * 60
DEFAULT_ROTATION_GRACE_SECONDS = 20
DEFAULT_MAX_ROTATION_ATTEMPTS = 5
_REVOKE_BATCH = 200
_GRACE_CONTEXT = b"nanfo:auth:rotation-grace:v1"
_NONCE_BYTES = 12

# Transport/client failures of the session store (redis-py wraps socket errors;
# RuntimeError covers a closed client/event loop). Never used for auth outcomes.
_STORE_FAILURES = (RedisError, RuntimeError, OSError)


def invalid_session() -> HTTPException:
    return HTTPException(status_code=401, detail="Invalid or expired token.")


def session_store_unavailable() -> DependencyUnavailableError:
    return DependencyUnavailableError("redis")


class RefreshTokenReuse(HTTPException):
    """A spent refresh token was presented outside the retry grace; family revoked."""

    def __init__(self, *, session_id: str, user_id: str):
        super().__init__(status_code=401, detail="Invalid or expired token.")
        self.session_id = session_id
        self.user_id = user_id


@dataclass(frozen=True)
class IssuedPair:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True)
class RotationResult:
    pair: IssuedPair
    replayed: bool  # True when an in-grace retry received the already-issued pair


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _grace_cipher(presented_token: str) -> AESGCM:
    # Domain-separated from the Redis key (plain sha256 of the token), so the key
    # name never reveals the sealing key.
    return AESGCM(hashlib.sha256(_GRACE_CONTEXT + b"\x00" + presented_token.encode()).digest())


def seal_issued_pair(presented_token: str, pair: IssuedPair, *, issued_at: int) -> str:
    document = json.dumps({
        "access_token": pair.access_token, "refresh_token": pair.refresh_token,
        "expires_in": pair.expires_in, "issued_at": issued_at,
    }, separators=(",", ":")).encode()
    nonce = os.urandom(_NONCE_BYTES)
    sealed = _grace_cipher(presented_token).encrypt(nonce, document, _GRACE_CONTEXT)
    return base64.b64encode(nonce + sealed).decode("ascii")


def open_issued_pair(presented_token: str, sealed: object, *, now: int) -> IssuedPair | None:
    """Return the sealed pair, or None when absent, tampered or not sealed for this token."""
    if not isinstance(sealed, (str, bytes)):
        return None
    try:
        blob = base64.b64decode(sealed, validate=True)
        if len(blob) <= _NONCE_BYTES:
            return None
        document = json.loads(_grace_cipher(presented_token).decrypt(
            blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], _GRACE_CONTEXT,
        ))
        access, refresh = document["access_token"], document["refresh_token"]
        expires_in, issued_at = document["expires_in"], document["issued_at"]
    except (InvalidTag, ValueError, TypeError, KeyError, binascii.Error):
        return None
    if not (isinstance(access, str) and isinstance(refresh, str)
            and type(expires_in) is int and type(issued_at) is int):
        return None
    return IssuedPair(access_token=access, refresh_token=refresh,
                      expires_in=max(1, expires_in - max(0, now - issued_at)))


def _configured_seconds(name: str, default: int) -> int:
    """Optional platform setting (BE-Platform may add it); positive int or default."""
    try:
        value = getattr(get_settings(), name, default)
    except Exception:  # noqa: BLE001 - settings unavailable: keep the safe default
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    return value


def _text(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _entry_owner(raw: object) -> str | None:
    try:
        owner = json.loads(raw).get("user_id")
    except (ValueError, TypeError, AttributeError):
        return None
    return owner if isinstance(owner, str) else None


class SessionRepository:
    def __init__(
        self,
        redis,
        *,
        idle_timeout_seconds: int | None = None,
        rotation_grace_seconds: int | None = None,
        max_rotation_attempts: int | None = None,
    ):
        self._redis = redis
        self._idle_timeout = idle_timeout_seconds or _configured_seconds(
            "AUTH_SESSION_IDLE_TIMEOUT_SECONDS", DEFAULT_IDLE_TIMEOUT_SECONDS)
        self._grace = rotation_grace_seconds or _configured_seconds(
            "AUTH_REFRESH_GRACE_SECONDS", DEFAULT_ROTATION_GRACE_SECONDS)
        self._max_attempts = max_rotation_attempts or DEFAULT_MAX_ROTATION_ATTEMPTS

    @staticmethod
    def key(sid: str) -> str:
        return f"{SESSION_KEY_PREFIX}{sid}"

    @staticmethod
    def user_index_key(user_id: str) -> str:
        return f"{USER_INDEX_KEY_PREFIX}{user_id}"

    @staticmethod
    def rotation_key(presented_token: str) -> str:
        return f"{ROTATION_KEY_PREFIX}{token_digest(presented_token)}"

    @staticmethod
    def _entry(claims: dict, token: str) -> dict:
        return {
            "user_id": claims["sub"],
            "refresh_jti": claims["jti"],
            "refresh_hash": token_digest(token),
            "exp": claims["exp"],
            "org_id": claims.get("org_id"),
            "workspace_id": claims.get("workspace_id"),
        }

    @staticmethod
    def _validate(raw, claims: dict) -> dict:
        try:
            entry = json.loads(raw)
            if (
                entry["user_id"] != claims["sub"]
                or type(entry["exp"]) is not int
                or entry["exp"] <= time.time()
                or not isinstance(entry["refresh_jti"], str)
                or not isinstance(entry["refresh_hash"], str)
                or entry.get("org_id") != claims.get("org_id")
                or entry.get("workspace_id") != claims.get("workspace_id")
            ):
                raise invalid_session()
            return entry
        except (ValueError, TypeError, KeyError):
            raise invalid_session() from None

    def _deadline(self, absolute_exp: int, now: int) -> int:
        """Sliding idle expiry, never beyond the family's absolute expiry."""
        return min(int(absolute_exp), now + self._idle_timeout)

    async def create(self, claims: dict, token: str) -> None:
        now = int(time.time())
        deadline = self._deadline(claims["exp"], now)
        if deadline <= now:
            raise invalid_session()
        sid, index = claims["sid"], self.user_index_key(claims["sub"])
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(index, "-inf", now)
                pipe.zadd(index, {sid: deadline})
                # EXPIREAT GT ignores keys without a TTL, so NX seeds it first.
                pipe.expireat(index, claims["exp"], nx=True)
                pipe.expireat(index, claims["exp"], gt=True)
                pipe.set(self.key(sid), json.dumps(self._entry(claims, token)), exat=deadline, nx=True)
                results = await pipe.execute()
        except _STORE_FAILURES as exc:
            raise session_store_unavailable() from exc
        if not results[-1]:
            raise invalid_session()

    async def validate(self, claims: dict) -> dict:
        try:
            raw = await self._redis.get(self.key(claims["sid"]))
        except _STORE_FAILURES as exc:
            raise session_store_unavailable() from exc
        return self._validate(raw, claims)

    async def rotate(
        self, claims: dict, token: str, new_claims: dict, new_token: str,
        *, access_token: str, expires_in: int,
    ) -> RotationResult:
        """Atomically replace the family head, or resolve a retry/reuse of a spent token."""
        sid = claims["sid"]
        key, index = self.key(sid), self.user_index_key(claims["sub"])
        presented = token_digest(token)
        grace_key = f"{ROTATION_KEY_PREFIX}{presented}"
        issued = IssuedPair(access_token=access_token, refresh_token=new_token, expires_in=expires_in)
        for _attempt in range(self._max_attempts):
            try:
                # WATCH serializes competing refresh/logout operations across workers.
                async with self._redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(key)
                    entry = self._validate(await pipe.get(key), claims)
                    now = int(time.time())
                    if entry["refresh_jti"] != claims["jti"] or entry["refresh_hash"] != presented:
                        replay = open_issued_pair(token, await pipe.get(grace_key), now=now)
                        if replay is not None and token_digest(replay.refresh_token) == entry["refresh_hash"]:
                            return RotationResult(pair=replay, replayed=True)
                        pipe.multi()
                        pipe.delete(key)
                        pipe.zrem(index, sid)
                        await pipe.execute()
                        raise RefreshTokenReuse(session_id=sid, user_id=claims["sub"])
                    deadline = self._deadline(entry["exp"], now)
                    pipe.multi()
                    pipe.set(key, json.dumps(self._entry(new_claims, new_token)), exat=deadline)
                    pipe.zadd(index, {sid: deadline})
                    pipe.set(grace_key, seal_issued_pair(token, issued, issued_at=now), ex=self._grace)
                    await pipe.execute()
                    return RotationResult(pair=issued, replayed=False)
            except WatchError:
                continue
            except _STORE_FAILURES as exc:
                raise session_store_unavailable() from exc
        # Persistent contention on one family: fail as a retryable outage, never 401.
        raise session_store_unavailable()

    async def revoke(self, sid: str, user_id: str | None = None) -> None:
        """Delete one session family (logout) and drop it from the user's index."""
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.delete(self.key(sid))
                if user_id is not None:
                    pipe.zrem(self.user_index_key(str(user_id)), sid)
                await pipe.execute()
        except _STORE_FAILURES as exc:
            raise session_store_unavailable() from exc

    async def revoke_user(self, user_id: str) -> int:
        """Delete every indexed session family of ``user_id``; returns families removed."""
        owner = str(user_id)
        index = self.user_index_key(owner)
        removed = 0
        try:
            sids = [_text(sid) for sid in await self._redis.zrange(index, 0, -1)]
            for offset in range(0, len(sids), _REVOKE_BATCH):
                chunk = sids[offset:offset + _REVOKE_BATCH]
                keys = [self.key(sid) for sid in chunk]
                raws = await self._redis.mget(keys)
                # Unparsable entries are unusable anyway; never delete another user's.
                owned = [
                    key for key, raw in zip(keys, raws, strict=True)
                    if raw is not None and _entry_owner(raw) in (owner, None)
                ]
                async with self._redis.pipeline(transaction=True) as pipe:
                    if owned:
                        pipe.delete(*owned)
                    pipe.zrem(index, *chunk)
                    results = await pipe.execute()
                removed += int(results[0]) if owned else 0
        except _STORE_FAILURES as exc:
            raise session_store_unavailable() from exc
        return removed
