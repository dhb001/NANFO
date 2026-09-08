"""Redis-owned session families with optimistic, atomic refresh rotation."""

from __future__ import annotations

import hashlib
import json
import time

from fastapi import HTTPException
from redis.exceptions import RedisError, WatchError


def invalid_session() -> HTTPException:
    return HTTPException(status_code=401, detail="Invalid or expired token.")


class SessionRepository:
    def __init__(self, redis):
        self._redis = redis

    @staticmethod
    def key(sid: str) -> str:
        return f"auth:session:{sid}"

    @staticmethod
    def _entry(claims: dict, token: str) -> dict:
        return {
            "user_id": claims["sub"],
            "refresh_jti": claims["jti"],
            "refresh_hash": hashlib.sha256(token.encode()).hexdigest(),
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

    async def create(self, claims: dict, token: str) -> None:
        try:
            created = await self._redis.set(
                self.key(claims["sid"]), json.dumps(self._entry(claims, token)),
                exat=claims["exp"], nx=True,
            )
            if not created:
                raise invalid_session()
        except (RedisError, RuntimeError):
            raise invalid_session() from None

    async def validate(self, claims: dict) -> dict:
        try:
            entry = self._validate(await self._redis.get(self.key(claims["sid"])), claims)
            if await self._redis.exists(f"jti:deny:{claims['jti']}"):
                raise invalid_session()
            return entry
        except (RedisError, RuntimeError):
            raise invalid_session() from None

    async def rotate(self, claims: dict, token: str, new_claims: dict, new_token: str) -> None:
        key = self.key(claims["sid"])
        try:
            # WATCH serializes competing refresh/logout operations across workers.
            # A loser retries, sees the spent token, and deletes the whole family.
            while True:
                async with self._redis.pipeline(transaction=True) as pipe:
                    try:
                        await pipe.watch(key)
                        entry = self._validate(await pipe.get(key), claims)
                        replay = (
                            entry["refresh_jti"] != claims["jti"]
                            or entry["refresh_hash"] != hashlib.sha256(token.encode()).hexdigest()
                        )
                        pipe.multi()
                        if replay:
                            pipe.delete(key)
                        else:
                            pipe.set(key, json.dumps(self._entry(new_claims, new_token)), exat=entry["exp"])
                        await pipe.execute()
                        if replay:
                            raise invalid_session()
                        return
                    except WatchError:
                        continue
        except (RedisError, RuntimeError):
            raise invalid_session() from None

    async def revoke(self, sid: str) -> None:
        try:
            await self._redis.delete(self.key(sid))
        except (RedisError, RuntimeError):
            raise invalid_session() from None
