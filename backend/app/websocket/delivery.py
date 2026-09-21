"""Bounded FIFO delivery with one lazily started writer per connection."""

from __future__ import annotations

import asyncio
import math
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class DeliveryLimits:
    """Injectable limits; pending bytes exclude the one in-flight frame."""

    max_pending: int = 64
    max_pending_bytes: int = 1024 * 1024
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.max_pending <= 0 or self.max_pending_bytes <= 0:
            raise ValueError("Delivery queue limits must be positive")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Delivery timeout must be finite and positive")


@dataclass(frozen=True)
class PendingDelta:
    message: str
    workspace_id: str | None
    network_id: str | None
    size: int


class DeliveryDenied(Exception):
    """Authorization failure handled outside the per-delta IO deadline."""


class ConnectionDelivery:
    """No per-message tasks, unbounded queues, or concurrent socket writers.

    Overflow cancels an in-flight operation and discards the entire backlog. The
    same writer then emits a best-effort recovery signal and closes. Cancellation
    from unsubscribe instead suppresses recovery and waits for writer cleanup.
    """

    def __init__(
        self,
        limits: DeliveryLimits,
        deliver: Callable[[PendingDelta], Awaitable[bool]],
        backpressure: Callable[[], Awaitable[None]],
        denied: Callable[[str], Awaitable[None]],
        finished: Callable[[], None],
    ) -> None:
        self.limits = limits
        self.deliver = deliver
        self.backpressure = backpressure
        self.denied = denied
        self.finished = finished
        self.pending: deque[PendingDelta] = deque()
        self.pending_bytes = 0
        self.task: asyncio.Task | None = None
        self.current: PendingDelta | None = None
        self.closed = False
        self.overflowed = False
        self.discarding_current = False

    def enqueue(self, delta: PendingDelta) -> None:
        if self.closed or self.overflowed:
            return
        if (len(self.pending) >= self.limits.max_pending
                or self.pending_bytes + delta.size > self.limits.max_pending_bytes):
            self.overflowed = True
            self._clear()
            if self.task is not None and self.current is not None:
                self.task.cancel()
        else:
            self.pending.append(delta)
            self.pending_bytes += delta.size
        if self.task is None:
            self.task = asyncio.create_task(self._run(), name="ws-connection-delivery")

    def _clear(self) -> None:
        self.pending.clear()
        self.pending_bytes = 0

    def invalidate(self) -> None:
        """Loss of upstream continuity follows the same single-writer close path."""
        if self.closed or self.overflowed:
            return
        self.overflowed = True
        self._clear()
        if self.task is not None and self.current is not None:
            self.task.cancel()
        if self.task is None:
            self.task = asyncio.create_task(self._run(), name="ws-connection-delivery")

    def discard_network(self, network_id: str) -> None:
        self.pending = deque(item for item in self.pending if item.network_id != network_id)
        self.pending_bytes = sum(item.size for item in self.pending)
        if self.current is not None and self.current.network_id == network_id and self.task:
            self.discarding_current = True
            self.task.cancel()

    async def stop(self) -> None:
        self.closed = True
        self._clear()
        task = self.task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        try:
            while self.pending and not self.closed and not self.overflowed:
                self.current = self.pending.popleft()
                self.pending_bytes -= self.current.size
                try:
                    async with asyncio.timeout(self.limits.timeout_seconds):
                        if not await self.deliver(self.current):
                            self.closed = True
                except asyncio.CancelledError:
                    # Unsubscribe/overflow owns cancellation; never resume this frame.
                    if not self.closed and not self.overflowed:
                        if self.discarding_current:
                            self.discarding_current = False
                            continue
                        self.closed = True
                        raise
                except TimeoutError:
                    self.overflowed = True
                except DeliveryDenied as exc:
                    self.closed = True
                    self._clear()
                    await self.denied(str(exc))
                except Exception:  # Transport/auth failure must terminate this writer.
                    self.closed = True
                finally:
                    self.current = None
            if self.overflowed and not self.closed:
                self._clear()
                await self.backpressure()
                self.closed = True
        finally:
            self.task = None
            if self.closed or self.overflowed:
                self._clear()
                self.finished()
