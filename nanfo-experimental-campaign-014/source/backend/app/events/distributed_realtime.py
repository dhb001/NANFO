"""Opt-in composition: supervised leader work plus a subscriber in every API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from functools import wraps

from app.core.logging import get_logger
from app.events.fanout import FanoutPublisher, FanoutSubscriber, _publisher
from app.events.fanout_contract import FanoutEnvelope, FanoutSettings
from app.events.realtime import ApiRealtimeLease, RealtimeLeaseBusy, terminate_api

logger = get_logger(__name__)
LeaderFactory = Callable[[ApiRealtimeLease], AbstractAsyncContextManager[Sequence[asyncio.Task]]]


async def require_leadership(lease: ApiRealtimeLease) -> None:
    """Use before collector poll/ingestion and each durable domain handler."""
    try:
        if await lease.verify():
            return
    except Exception:
        pass
    raise asyncio.CancelledError("Domain leadership is no longer valid")


def fenced_handlers(handlers: dict, lease: ApiRealtimeLease) -> dict:
    """Preserve completion-marker identity; loss never enters retry/DLQ/ACK."""
    def wrap(handler):
        @wraps(handler)
        async def fenced(event):
            await require_leadership(lease)
            await handler(event)
            await require_leadership(lease)
        return fenced

    return {name: wrap(value) if callable(value) else [wrap(item) for item in value]
            for name, value in handlers.items()}


class DistributedRealtime:
    """Factory must clean up ALL domain/collector work on exit, including startup.

    Tasks yielded by the factory are mandatory long-running work. Any completion
    (including cancellation) restarts leadership after bounded teardown. A lease
    renewal failure terminates this process: no unfenced collector survives it.
    """

    def __init__(self, redis, *, leader_factory: LeaderFactory,
                 settings: FanoutSettings | None = None, managers: dict | None = None,
                 on_lost: Callable[[], None] = terminate_api):
        if managers is None:
            from app.websocket.manager import (
                alerts_ws_manager, digital_twin_ws_manager, telemetry_ws_manager, topology_ws_manager,
            )
            managers = {"topology": topology_ws_manager, "telemetry": telemetry_ws_manager,
                        "digital-twin": digital_twin_ws_manager, "alerts": alerts_ws_manager}
        self.redis, self.leader_factory = redis, leader_factory
        self.settings = settings or FanoutSettings()
        self.managers, self.on_lost = managers, on_lost
        self.lease: ApiRealtimeLease | None = None
        self.task: asyncio.Task | None = None
        self.subscriber = FanoutSubscriber(redis, settings=self.settings,
                                          dispatch=self._dispatch, availability=self._availability)

    async def _dispatch(self, envelope: FanoutEnvelope) -> None:
        await self.managers[envelope.channel].push_delta(**envelope.arguments())

    async def _availability(self, available: bool) -> None:
        for manager in self.managers.values():
            await manager.set_realtime_available(available)

    @property
    def healthy(self) -> bool:
        return self.subscriber.healthy and self.task is not None and not self.task.done()

    async def verify(self) -> bool:
        return self.healthy and await self.subscriber.verify()

    async def _heartbeat(self, publisher: FanoutPublisher):
        while True:
            await publisher.publish()
            await asyncio.sleep(self.settings.heartbeat_seconds)

    async def _work(self, lease: ApiRealtimeLease, failed: asyncio.Event):
        publisher = FanoutPublisher(self.redis, token=lease.token, settings=self.settings)
        context = _publisher.set(publisher)
        domain_ready = asyncio.Event()
        async def heartbeats():
            # Independent timer: a factory stuck cleaning up partial startup
            # cannot prevent the supervisor from enforcing its shutdown deadline.
            async with asyncio.timeout(self.settings.lease_ttl_seconds + self.settings.stale_seconds):
                await domain_ready.wait()
            await self._heartbeat(publisher)
        heartbeat = asyncio.create_task(heartbeats(), name="realtime-leader-heartbeat")
        async def domain():
            async with AsyncExitStack() as stack:
                tasks = await stack.enter_async_context(self.leader_factory(lease))
                if not tasks:
                    raise RuntimeError("Leader factory must yield supervised work")
                domain_ready.set()
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                failed.set()
        domain_task = asyncio.create_task(domain(), name="realtime-domain-lifecycle")
        try:
            # Startup failure and heartbeat failure share the same teardown path.
            await asyncio.wait([heartbeat, domain_task], return_when=asyncio.FIRST_COMPLETED)
        finally:
            failed.set()
            heartbeat.cancel()
            domain_task.cancel()
            await asyncio.gather(heartbeat, domain_task, return_exceptions=True)
            _publisher.reset(context)

    async def _supervise(self):
        while True:
            lease = ApiRealtimeLease(self.redis, key=self.settings.lease_key,
                                     ttl_seconds=self.settings.lease_ttl_seconds, on_lost=self.on_lost)
            try:
                async with lease:
                    self.lease = lease
                    failed = asyncio.Event()
                    failure = asyncio.create_task(failed.wait(), name="realtime-leader-failure")
                    work = asyncio.create_task(self._work(lease, failed), name="realtime-leader-work")
                    try:
                        # A cancelled child is not cancellation of the supervisor.
                        await asyncio.wait([work, lease.task, failure], return_when=asyncio.FIRST_COMPLETED)
                        try:
                            owned = await lease.verify()
                        except Exception:
                            owned = False
                        if not owned:
                            self.on_lost()
                    finally:
                        failure.cancel()
                        await asyncio.gather(failure, return_exceptions=True)
                        work.cancel()
                        done, _ = await asyncio.wait([work], timeout=self.settings.shutdown_seconds)
                        if not done:
                            self.on_lost()
                            # Production callback never returns. Tests must not
                            # accidentally release while uncancelled effects live.
                            await work
                        await asyncio.gather(work, return_exceptions=True)
            except RealtimeLeaseBusy:
                pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("realtime_leadership_retry", error_type=type(exc).__name__)
            finally:
                self.lease = None
            await asyncio.sleep(self.settings.retry_seconds)

    async def __aenter__(self):
        try:
            await self.subscriber.start()
            self.task = asyncio.create_task(self._supervise(), name="realtime-leader-supervisor")
            async with asyncio.timeout(self.settings.lease_ttl_seconds + self.settings.stale_seconds):
                await self.subscriber.ready.wait()
            return self
        except BaseException:
            await self.__aexit__()
            raise

    async def __aexit__(self, *_):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.subscriber.stop()
        await asyncio.gather(*(manager.stop_realtime() for manager in self.managers.values()))
