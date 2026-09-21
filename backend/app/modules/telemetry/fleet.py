"""Bounded fleet scheduler, fresh authority and crash-safe measured delivery."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from app.modules.telemetry.fleet_config import FleetManifest, FleetSettings, FleetTarget
from app.modules.telemetry.snmp import MeasuredSNMPAdapter
from app.modules.telemetry.snmp_config import SNMPBinding, SNMPCredentials, SNMPError, load_protected_json
from app.modules.telemetry.snmp_ownership import SNMPOwnerBoundary
from app.modules.telemetry.snmp_transport import NetSNMPTransport


class FleetWorker:
    def __init__(self, *, settings: FleetSettings, execution_mode: str, repository, locks,
                 sessions, redis, ingestion, transport_factory=NetSNMPTransport,
                 boundary_factory=SNMPOwnerBoundary):
        self.settings, self.execution_mode = settings, execution_mode
        self.repository, self.locks = repository, locks
        self.sessions, self.redis, self.ingestion = sessions, redis, ingestion
        self.transport_factory, self.boundary_factory = transport_factory, boundary_factory
        self.manifest = load_protected_json(settings.manifest_path, FleetManifest)
        self.owner_id = uuid.uuid4()
        self.adapters: dict[uuid.UUID, MeasuredSNMPAdapter] = {}
        self._active: dict[uuid.UUID, asyncio.Task] = {}
        self._rotation = 0

    def check_manifest(self) -> None:
        if load_protected_json(self.settings.manifest_path, FleetManifest) != self.manifest:
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

    async def _deliver(self, target: FleetTarget, lease, check) -> str:
        # Expire even revoked/missing bindings without requiring external authority;
        # terminalizing stale data never authorizes reads or publication.
        batch = await self.repository.pending(lease)
        if batch is not None:
            batch = await self.repository.ready(lease, batch.batch_id, batch.binding_sha256)
            if batch.status != "pending":
                self.adapters.pop(target.device_id, None)
                return batch.status
        binding = self.load_binding(target)
        digest = hashlib.sha256(binding.model_dump_json().encode()).hexdigest()
        boundary = self.boundary_factory(binding_path=target.binding_path, session_factory=self.sessions, redis=self.redis)

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
                return batch.status
            sample = batch.samples[batch.cursor]
            # Also enforce the absolute deadline across the bounded Redis call.
            remaining = (batch.expires_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise SNMPError("fleet_sample_expired")
            async with asyncio.timeout(min(remaining, self.settings.publish_timeout_seconds)):
                await self.ingestion.ingest(raw=sample, correlation_id=str(batch.batch_id), event_id=sample["event_id"])
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
                except Exception:
                    # Neither driver exceptions nor operator-file input is logged.
                    outcome, failed = "collection_deferred", True
                    self.adapters.pop(target.device_id, None)
                await self.repository.finish(lease, outcome=outcome, interval=target.interval_seconds,
                                             backoff_max=target.backoff_max_seconds, failed=failed)
                return outcome
        except Exception:
            self.adapters.pop(target.device_id, None)
            return "lease_or_storage_unavailable"

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
                    "configured_devices": len(self.manifest.targets), "devices": devices}
        await self.redis.set(f"nanfo:fleet:health:v1:{self.owner_id}", json.dumps(document),
                             ex=self.settings.health_ttl_seconds)
        return document

    async def run_once(self) -> list[str]:
        semaphore = asyncio.Semaphore(self.settings.concurrency)

        async def collect(target):
            async with semaphore:
                return await self.collect_target(target)

        return await asyncio.gather(*(collect(target) for target in self.manifest.targets))

    async def run(self, stop: asyncio.Event) -> None:
        try:
            while not stop.is_set():
                self.check_manifest()
                for device_id, task in list(self._active.items()):
                    if task.done():
                        task.result()
                        del self._active[device_id]
                targets = self.manifest.targets
                for offset in range(len(targets)):
                    if len(self._active) >= self.settings.concurrency:
                        break
                    index = (self._rotation + offset) % len(targets)
                    target = targets[index]
                    if target.device_id not in self._active:
                        self._active[target.device_id] = asyncio.create_task(self.collect_target(target))
                self._rotation = (self._rotation + 1) % len(targets)
                try:
                    async with asyncio.timeout(self.settings.db_timeout_seconds + self.settings.publish_timeout_seconds):
                        await self.health()
                except Exception:
                    # Do not let unavailable health transport cancel healthy
                    # targets. Last worker heartbeat expires rather than lying.
                    pass
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.settings.scan_seconds)
                except TimeoutError:
                    pass
        finally:
            for task in self._active.values():
                task.cancel()
            await asyncio.gather(*self._active.values(), return_exceptions=True)
            self._active.clear()
