"""Bounded fleet scheduler, fresh authority and crash-safe measured delivery.

Scheduling (ADR-028): every target has an in-memory next-due time. Free worker
slots are filled with the most overdue due targets, and a finished collection is
rescheduled at ``finish + interval`` (or bounded exponential backoff after a
failure), so each device is polled at ~its configured interval as long as
``concurrency / collection_time`` covers the fleet. The database lease
(``next_poll_at``) stays authoritative across replicas; the in-memory schedule
only avoids needless claims.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger
from app.modules.telemetry.diagnostics import FailureCounter
from app.modules.telemetry.fleet_config import FleetManifest, FleetSettings, FleetTarget
from app.modules.telemetry.snmp import MeasuredSNMPAdapter
from app.modules.telemetry.snmp_config import (
    ProtectedRevision,
    SNMPBinding,
    SNMPCredentials,
    SNMPError,
    binding_sha256,
    load_protected_json,
)
from app.modules.telemetry.snmp_ownership import SNMPOwnerBoundary
from app.modules.telemetry.snmp_transport import NetSNMPTransport

logger = get_logger(__name__)

_FAILED_OUTCOMES = frozenset({"collection_deferred", "lease_or_storage_unavailable"})
# 256 targets with realistic absolute paths exceed the 64 KiB per-secret bound.
MANIFEST_MAX_BYTES = 512 * 1024


def load_manifest(path) -> FleetManifest:
    return load_protected_json(path, FleetManifest, max_bytes=MANIFEST_MAX_BYTES)


class FleetWorker:
    def __init__(self, *, settings: FleetSettings, execution_mode: str, repository, locks,
                 sessions, redis, ingestion, transport_factory=NetSNMPTransport,
                 boundary_factory=SNMPOwnerBoundary, slo_evaluator=None,
                 clock: Callable[[], float] = time.monotonic):
        self.settings, self.execution_mode = settings, execution_mode
        self.repository, self.locks = repository, locks
        self.sessions, self.redis, self.ingestion = sessions, redis, ingestion
        self.transport_factory, self.boundary_factory = transport_factory, boundary_factory
        self.slo_evaluator = slo_evaluator
        self.manifest = load_manifest(settings.manifest_path)
        self.owner_id = uuid.uuid4()
        self.adapters: dict[uuid.UUID, MeasuredSNMPAdapter] = {}
        self.failures = FailureCounter()
        self._clock = clock
        self._active: dict[uuid.UUID, asyncio.Task] = {}
        self._next_due: dict[uuid.UUID, float] = {}
        self._consecutive_failures: dict[uuid.UUID, int] = {}
        self._next_housekeeping = 0.0
        self._manifest_revision = ProtectedRevision(settings.manifest_path, FleetManifest,
                                                    max_bytes=MANIFEST_MAX_BYTES)

    # -- configuration -----------------------------------------------------
    def check_manifest(self) -> None:
        """Operator revocation check on every authorization: an exact byte
        comparison of the securely re-read manifest (re-parsed only on change)."""
        if not self._manifest_revision.matches(self.manifest):
            raise SNMPError("fleet_manifest_changed_restart_required")

    def load_binding(self, target: FleetTarget) -> SNMPBinding:
        self.check_manifest()
        binding = load_protected_json(target.binding_path, SNMPBinding)
        load_protected_json(target.credentials_path, SNMPCredentials)
        if binding.device_id != target.device_id or binding.execution_mode != self.execution_mode:
            raise SNMPError("fleet_binding_scope_mismatch")
        budget = len(binding.interfaces) * (binding.timeout_seconds + 1)
        if budget >= min(target.poll_timeout_seconds, binding.max_pending_seconds):
            raise SNMPError("fleet_transport_budget_exceeded")
        if target.interval_seconds + budget >= binding.max_interval_seconds:
            raise SNMPError("fleet_rate_window_exceeded")
        return binding

    # -- delivery ----------------------------------------------------------
    async def _count(self, name: str, times: int = 1) -> None:
        counters = getattr(self.ingestion, "counter_service", None)
        update = getattr(counters, name, None) if counters is not None else None
        if update is None:
            return
        for _ in range(max(0, times)):
            try:
                await update()
            except Exception as exc:  # noqa: BLE001 - counters never block delivery
                self.failures.record(logger, "fleet_counter_update_failed", exc, default="fleet_counter_unavailable")
                return

    async def _deliver(self, target: FleetTarget, lease, check) -> str:
        # Expire even revoked/missing bindings without requiring external authority;
        # terminalizing stale data never authorizes reads or publication.
        batch = await self.repository.pending(lease)
        if batch is not None:
            batch = await self.repository.ready(lease, batch.batch_id, batch.binding_sha256)
            if batch.status != "pending":
                self.adapters.pop(target.device_id, None)
                if batch.status == "expired":
                    await self._count("increment_runtime_adapter_dropped_sample", len(batch.samples) - batch.cursor)
                return batch.status
        binding = self.load_binding(target)
        digest = binding_sha256(binding)
        # A fresh boundary per batch: the first call is the full owner check, later
        # per-GET/per-sample calls hit its short revision-keyed authority cache.
        boundary = self.boundary_factory(binding_path=target.binding_path, session_factory=self.sessions,
                                         redis=self.redis)

        async def authorize(current, publish):
            self.check_manifest()
            await boundary.authorize(current, publish)
            await check()

        await authorize(binding, True)
        if batch is None:
            adapter = self.adapters.get(target.device_id)
            if adapter is None or adapter.binding != binding:
                transport = self.transport_factory(credentials_path=target.credentials_path)
                transport.check_available()
                adapter = MeasuredSNMPAdapter(binding=binding, transport=transport, authorize=authorize)
                self.adapters[target.device_id] = adapter
            else:
                adapter.authorize = authorize
            samples = await adapter.poll()
            expires_at = min(datetime.fromisoformat(sample["observed_at"]) for sample in samples)
            expires_at += timedelta(seconds=binding.max_pending_seconds)
            batch = await self.repository.stage(lease, digest=digest, samples=samples, expires_at=expires_at)
            # Durable ownership has transferred to the spool; no in-memory replay
            # is needed and no new poll can occur until the pending spool drains.
            await adapter.acknowledge_batch(samples)
        while True:
            await authorize(binding, True)
            batch = await self.repository.ready(lease, batch.batch_id, digest)
            if batch.status != "pending":
                if batch.status != "published":
                    self.adapters.pop(target.device_id, None)
                if batch.status == "expired":
                    await self._count("increment_runtime_adapter_dropped_sample", len(batch.samples) - batch.cursor)
                return batch.status
            sample = batch.samples[batch.cursor]
            # Also enforce the absolute deadline across the bounded Redis call.
            remaining = (batch.expires_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise SNMPError("fleet_sample_expired")
            await self._count("increment_runtime_adapter_ingest_attempt")
            try:
                async with asyncio.timeout(min(remaining, self.settings.publish_timeout_seconds)):
                    await self.ingestion.ingest(raw=sample, correlation_id=str(batch.batch_id),
                                                event_id=sample["event_id"])
            except Exception:
                await self._count("increment_runtime_adapter_ingest_failure")
                raise
            await self.repository.acknowledge(lease, batch.batch_id, batch.cursor)

    async def _watched(self, target, lease, check) -> str:
        async def watchdog():
            while True:
                await asyncio.sleep(self.settings.lease_seconds / 3)
                await check(renew=True)

        work = asyncio.create_task(self._deliver(target, lease, check))
        watch = asyncio.create_task(watchdog())
        try:
            async with asyncio.timeout(target.poll_timeout_seconds):
                done, _ = await asyncio.wait({work, watch}, return_when=asyncio.FIRST_COMPLETED)
                if watch in done:
                    # Cancellation propagates into NetSNMPTransport, which kills
                    # and reaps its child before the session lock is released.
                    await watch
                    raise SNMPError("fleet_watchdog_stopped")
                return await work
        finally:
            work.cancel()
            watch.cancel()
            await asyncio.gather(work, watch, return_exceptions=True)

    async def collect_target(self, target: FleetTarget) -> str:
        try:
            async with self.locks.acquire(target.device_id, self.owner_id) as acquired:
                if acquired is None:
                    return "not_due_or_owned"
                lease, check = acquired
                failed = False
                try:
                    outcome = await self._watched(target, lease, check)
                except Exception as exc:
                    # Fixed code + class only: driver/operator-file errors are never logged.
                    self.failures.record(logger, "fleet_collection_deferred", exc,
                                         default="fleet_collection_failed", device_id=str(target.device_id))
                    outcome, failed = "collection_deferred", True
                    self.adapters.pop(target.device_id, None)
                await self.repository.finish(lease, outcome=outcome, interval=target.interval_seconds,
                                             backoff_max=target.backoff_max_seconds, failed=failed)
                return outcome
        except Exception as exc:
            self.failures.record(logger, "fleet_lease_or_storage_unavailable", exc,
                                 default="fleet_lease_or_storage_unavailable", device_id=str(target.device_id))
            self.adapters.pop(target.device_id, None)
            return "lease_or_storage_unavailable"

    # -- health ------------------------------------------------------------
    async def health(self) -> dict:
        devices = await self.repository.health([target.device_id for target in self.manifest.targets])
        complete = len(devices) == len(self.manifest.targets)
        now = datetime.now(UTC)
        targets = {str(target.device_id): target for target in self.manifest.targets}
        for row in devices:
            target = targets[row["device_id"]]
            last = datetime.fromisoformat(row["last_published_at"]) if row["last_published_at"] else None
            age = (now - last).total_seconds() if last is not None else None
            row["publish_age_seconds"] = age
            row["fresh"] = age is not None and 0 <= age <= target.interval_seconds + target.poll_timeout_seconds + self.settings.scan_seconds
        healthy = complete and all(row["outcome"] == "published" and row["fresh"] for row in devices)
        document = {"version": 1, "worker_id": str(self.owner_id), "observed_at": datetime.now(UTC).isoformat(),
                    "status": "healthy" if healthy else "degraded", "active": len(self._active),
                    "configured_devices": len(self.manifest.targets), "devices": devices,
                    "scheduler": self.schedule_summary(self._clock()), "errors": self.failures.snapshot()}
        await self.redis.set(f"nanfo:fleet:health:v1:{self.owner_id}", json.dumps(document),
                             ex=self.settings.health_ttl_seconds)
        return document

    async def run_once(self) -> list[str]:
        semaphore = asyncio.Semaphore(self.settings.concurrency)

        async def collect(target):
            async with semaphore:
                return await self.collect_target(target)

        return await asyncio.gather(*(collect(target) for target in self.manifest.targets))

    # -- scheduler ---------------------------------------------------------
    def _delay(self, target: FleetTarget, outcome: str) -> float:
        if outcome in _FAILED_OUTCOMES:
            failures = min(self._consecutive_failures.get(target.device_id, 0) + 1, 30)
            self._consecutive_failures[target.device_id] = failures
            return min(target.backoff_max_seconds, target.interval_seconds * 2 ** min(failures, 20))
        if outcome != "not_due_or_owned":
            self._consecutive_failures[target.device_id] = 0
        return target.interval_seconds

    def _reap(self, now: float) -> None:
        targets = {target.device_id: target for target in self.manifest.targets}
        for device_id, task in list(self._active.items()):
            if not task.done():
                continue
            del self._active[device_id]
            if task.cancelled():
                outcome = "lease_or_storage_unavailable"
            elif (exc := task.exception()) is not None:
                self.failures.record(logger, "fleet_collection_crashed", exc, default="fleet_collection_crashed",
                                     device_id=str(device_id))
                outcome = "lease_or_storage_unavailable"
            else:
                outcome = task.result()
            self._next_due[device_id] = now + self._delay(targets[device_id], outcome)

    def due_targets(self, now: float) -> list[FleetTarget]:
        """Most overdue first, limited to free slots; never a target already running."""
        free = self.settings.concurrency - len(self._active)
        if free <= 0:
            return []
        due = [(self._next_due.get(target.device_id, now), index, target)
               for index, target in enumerate(self.manifest.targets)
               if target.device_id not in self._active and self._next_due.get(target.device_id, now) <= now]
        due.sort(key=lambda item: (item[0], item[1]))
        return [target for _, _, target in due[:free]]

    def schedule_summary(self, now: float) -> dict:
        idle = [self._next_due.get(t.device_id, now) for t in self.manifest.targets if t.device_id not in self._active]
        overdue = [now - due for due in idle if due <= now]
        return {"active": len(self._active), "due": len(overdue),
                "max_overdue_seconds": round(max(overdue, default=0.0), 3)}

    def _wake_after(self, now: float) -> float:
        candidates = [self.settings.scan_seconds, self._next_housekeeping - now]
        if len(self._active) < self.settings.concurrency:
            waiting = [self._next_due.get(t.device_id, now) - now
                       for t in self.manifest.targets if t.device_id not in self._active]
            candidates.extend(waiting)
        return max(0.0, min(candidates))

    async def _pause(self, stop: asyncio.Event, timeout: float) -> None:
        """Wake on stop, on any collection finishing (a free slot) or at ``timeout``."""
        stopper = asyncio.ensure_future(stop.wait())
        try:
            await asyncio.wait({stopper, *self._active.values()}, timeout=timeout,
                               return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopper.cancel()

    async def _housekeeping(self, now: float) -> None:
        self.check_manifest()  # a changed manifest stops the worker (restart required)
        try:
            async with asyncio.timeout(self.settings.db_timeout_seconds + self.settings.publish_timeout_seconds):
                await self.health()
        except Exception as exc:  # noqa: BLE001
            # Do not let unavailable health transport cancel healthy targets. The
            # last worker heartbeat expires rather than lying.
            self.failures.record(logger, "fleet_health_publish_failed", exc, default="fleet_health_unavailable")
        if self.slo_evaluator is not None:
            try:
                async with asyncio.timeout(self.settings.db_timeout_seconds + self.settings.publish_timeout_seconds):
                    await self.slo_evaluator.maybe_evaluate()
            except Exception as exc:  # noqa: BLE001
                self.failures.record(logger, "fleet_slo_evaluation_failed", exc, default="fleet_slo_unavailable")
        self._next_housekeeping = now + self.settings.scan_seconds

    async def run(self, stop: asyncio.Event) -> None:
        try:
            while not stop.is_set():
                now = self._clock()
                self._reap(now)
                if now >= self._next_housekeeping:
                    await self._housekeeping(now)
                for target in self.due_targets(now):
                    self._active[target.device_id] = asyncio.create_task(
                        self.collect_target(target), name=f"fleet-collect-{target.device_id}")
                await self._pause(stop, self._wake_after(self._clock()))
        finally:
            for task in self._active.values():
                task.cancel()
            await asyncio.gather(*self._active.values(), return_exceptions=True)
            self._active.clear()
