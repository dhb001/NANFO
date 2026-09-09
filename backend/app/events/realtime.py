"""Single active API process until cross-process realtime fanout exists (ADR-010)."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Callable

from app.core.logging import get_logger

logger = get_logger(__name__)

API_REALTIME_LEASE_KEY = "nanfo:api:realtime:lease"
_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def terminate_api() -> None:
    # A graceful server shutdown may wait indefinitely for websocket clients.
    # The supervisor must restart us; never leave an unfenced realtime process up.
    os._exit(1)


class ApiRealtimeLease:
    def __init__(self, redis, *, ttl_seconds: float = 30,
                 key: str = API_REALTIME_LEASE_KEY,
                 on_lost: Callable[[], None] = terminate_api):
        if ttl_seconds <= 0:
            raise ValueError("Lease TTL must be positive")
        self.redis = redis
        self.key = key
        self.ttl_seconds = ttl_seconds
        self.token = uuid.uuid4().hex
        self.on_lost = on_lost
        self.deadline = 0.0
        self.task: asyncio.Task | None = None

    @property
    def healthy(self) -> bool:
        return time.monotonic() < self.deadline

    async def __aenter__(self):
        started = time.monotonic()
        async with asyncio.timeout(self.ttl_seconds / 6):
            acquired = await self.redis.set(
                self.key, self.token, nx=True, px=int(self.ttl_seconds * 1000),
            )
        if not acquired:
            raise RuntimeError("Another API realtime process is active; run exactly one API worker")
        self.deadline = started + self.ttl_seconds
        self.task = asyncio.create_task(self._renew(), name="api-realtime-lease")
        return self

    async def _renew(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.ttl_seconds / 3)
                if not self.healthy:
                    raise RuntimeError("API realtime lease expired")
                started = time.monotonic()
                async with asyncio.timeout(self.ttl_seconds / 6):
                    renewed = await self.redis.eval(
                        _RENEW, 1, self.key, self.token, int(self.ttl_seconds * 1000),
                    )
                if not renewed or not self.healthy:
                    raise RuntimeError("API realtime lease lost")
                self.deadline = started + self.ttl_seconds
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.deadline = 0.0
            logger.critical("api_realtime_lease_lost", error_type=type(exc).__name__)
            self.on_lost()

    async def __aexit__(self, *_):
        self.deadline = 0.0
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        try:
            async with asyncio.timeout(self.ttl_seconds / 6):
                await self.redis.eval(_RELEASE, 1, self.key, self.token)
        except Exception as exc:  # noqa: BLE001
            # Safe to let this owner's key expire; never DEL a successor's lease.
            logger.warning("api_realtime_lease_release_failed", error_type=type(exc).__name__)
