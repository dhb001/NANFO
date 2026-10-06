"""Legacy singleton guard and opt-in distributed composition (ADR010/023, ADR-028).

Renewal tolerates transient Redis failures: it retries until the local deadline minus
a safety margin (one IO deadline). Ownership is only considered lost when another
owner is observed or that margin is reached; the deadline is then cleared first,
which fences every ``healthy``/``verify`` check (collectors, fenced handlers, the
watchdog) before ``on_lost`` runs.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import signal
import threading
import time
import uuid
from collections.abc import Callable

from app.core.logging import get_logger

logger = get_logger(__name__)


class RealtimeLeaseBusy(RuntimeError):
    """A follower may serve sockets while another process owns domain work."""

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
_termination_lock = threading.Lock()
_termination_requested = False


def _exit_nonzero() -> None:
    # A graceful shutdown after lease loss must still look like a failure to the
    # supervisor (restart policies keyed on exit status).
    logging.shutdown()
    os._exit(1)


def termination_requested() -> bool:
    """True once terminate_api() began a shutdown; leadership must not be re-acquired."""
    return _termination_requested


def terminate_api(*, hard_timeout_seconds: float | None = None) -> None:
    """Graceful SIGTERM to this process, with a hard-exit fallback (idempotent).

    Uvicorn drains requests and runs lifespan shutdown on SIGTERM; a daemon timer
    exits the process if that stalls (e.g. websocket clients never closing).
    """
    global _termination_requested
    with _termination_lock:
        if _termination_requested:
            return
        _termination_requested = True
    if hard_timeout_seconds is None:
        try:
            from app.core.config import get_settings

            hard_timeout_seconds = get_settings().API_REALTIME_LEASE_LOSS_EXIT_SECONDS
        except Exception:  # noqa: BLE001 - never block termination on configuration
            hard_timeout_seconds = 20.0
    timer = threading.Timer(hard_timeout_seconds, _exit_nonzero)
    timer.daemon = True
    timer.start()
    atexit.register(_exit_nonzero)
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except OSError:
        _exit_nonzero()


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

    @property
    def io_timeout(self) -> float:
        return self.ttl_seconds / 6

    async def verify(self) -> bool:
        """Read-only ownership check; readiness must not renew a stale lease."""
        if not self.healthy or self.task is None or self.task.done():
            return False
        async with asyncio.timeout(2):
            owner = await self.redis.get(self.key)
        if isinstance(owner, bytes):
            owner = owner.decode("ascii", errors="replace")
        return owner == self.token and self.healthy and not self.task.done()

    async def __aenter__(self):
        started = time.monotonic()
        async with asyncio.timeout(self.io_timeout):
            acquired = await self.redis.set(
                self.key, self.token, nx=True, px=int(self.ttl_seconds * 1000),
            )
        if not acquired:
            raise RealtimeLeaseBusy("Another API realtime process is active; run exactly one API worker")
        self.deadline = started + self.ttl_seconds
        self.task = asyncio.create_task(self._renew(), name="api-realtime-lease")
        return self

    async def _renew_once(self) -> bool:
        """True renewed, False owned by someone else; raises on transport failure."""
        started = time.monotonic()
        async with asyncio.timeout(self.io_timeout):
            renewed = await self.redis.eval(
                _RENEW, 1, self.key, self.token, int(self.ttl_seconds * 1000),
            )
        if renewed:
            # The key expires ttl after the server applied PEXPIRE; our start is earlier.
            self.deadline = started + self.ttl_seconds
            return True
        return False

    async def _renew(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.ttl_seconds / 3)
                # Keep one IO deadline of margin: never act on a lease about to lapse.
                margin = self.io_timeout
                while True:
                    if time.monotonic() >= self.deadline - margin:
                        raise RuntimeError("API realtime lease expired")
                    try:
                        if await self._renew_once():
                            break
                        raise LookupError("API realtime lease owned elsewhere")
                    except LookupError:
                        raise
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - transient; retry within the deadline
                        logger.warning("api_realtime_lease_renew_retry", error_type=type(exc).__name__)
                        await asyncio.sleep(min(self.io_timeout / 2, max(0.0, self.deadline - margin - time.monotonic())))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Fence first: every healthy/verify caller now fails closed.
            self.deadline = 0.0
            logger.critical("api_realtime_lease_lost", error_type=type(exc).__name__)
            self.on_lost()

    async def __aexit__(self, *_):
        self.deadline = 0.0
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        try:
            async with asyncio.timeout(self.io_timeout):
                await self.redis.eval(_RELEASE, 1, self.key, self.token)
        except Exception as exc:  # noqa: BLE001
            # Safe to let this owner's key expire; never DEL a successor's lease.
            logger.warning("api_realtime_lease_release_failed", error_type=type(exc).__name__)
