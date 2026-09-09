"""Restartable bounded I/O worker; every lab wait occurs outside a DB transaction."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger
from app.modules.intent.execution import project_execution
from app.modules.intent.lab import (
    LabCommand,
    Mailbox,
    PendingLabCommand,
    digest,
    prepare_plan,
    verified_completion,
    verified_no_mutation,
    verified_rollback,
)
from app.modules.intent.repository import ExecutionRepository, IntentRepository

logger = get_logger(__name__)


class LeaseAuthority(asyncio.Event):
    """Monotonic local expiry is checked even by a delayed filesystem thread."""

    def __init__(self, expires):
        super().__init__()
        self.expires = expires

    def is_set(self):
        return super().is_set() or time.monotonic() >= self.expires

_RENEW_LOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_LOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end
return 0
"""


class ExecutionWorker:
    def __init__(self, *, settings, sessions, redis):
        self.settings = settings
        self.sessions = sessions
        self.redis = redis
        self.owner = str(uuid.uuid4())
        self.mailbox = Mailbox(settings)

    async def publish_one(self) -> bool:
        async with self.sessions() as db:
            row = await ExecutionRepository(db).claim_event(self.owner, self.settings.EMULATION_EXECUTION_LEASE_SECONDS)
            if row is None:
                return False
            event_id, envelope = row.event_id, dict(row.envelope)
        # The stored full envelope is immutable, including timestamp and payload bytes.
        # XADD-before-ack crashes deliberately replay the same event_id (at least once).
        await self.redis.xadd("stream:intent", envelope)
        async with self.sessions() as db:
            await ExecutionRepository(db).acknowledge_event(event_id, self.owner)
        return True

    async def _renew(self, job, lock_key, token, lost):
        seconds = self.settings.EMULATION_EXECUTION_LEASE_SECONDS
        try:
            while True:
                await asyncio.sleep(seconds / 3)
                started = time.monotonic()
                async with asyncio.timeout(max(0, min(seconds / 3, lost.expires - started))):
                    if lost.is_set() or not await self.redis.eval(_RENEW_LOCK, 1, lock_key, token, seconds * 1000):
                        lost.set()
                        return
                    async with self.sessions() as db:
                        if not await ExecutionRepository(db).renew(job.execution_id, self.owner, job.fence, seconds):
                            lost.set()
                            return
                if lost.is_set():
                    lost.set()
                    return
                lost.expires = started + seconds * .9
        except Exception:  # noqa: BLE001
            lost.set()

    async def run_one(self) -> bool:
        seconds = self.settings.EMULATION_EXECUTION_LEASE_SECONDS
        started = time.monotonic()
        async with asyncio.timeout(seconds / 3), self.sessions() as db:
            job = await ExecutionRepository(db).claim(self.owner, self.settings.EMULATION_EXECUTION_LEASE_SECONDS)
        if job is None:
            return False
        key = f"intent:lab:lock:{job.lab_key}"
        token = f"{self.owner}:{job.execution_id}:{job.fence}"
        async with asyncio.timeout(seconds / 3):
            if not await self.redis.set(key, token, nx=True, px=seconds * 1000):
                return False
        lost = LeaseAuthority(started + seconds * .9)
        renewer = asyncio.create_task(self._renew(job, key, token, lost))
        reconcile = asyncio.create_task(self._reconcile(job, lost))
        try:
            while not reconcile.done() and not lost.is_set():
                await asyncio.sleep(min(.1, seconds / 10))
            if reconcile.done():
                await reconcile
        finally:
            lost.set()
            reconcile.cancel()
            renewer.cancel()
            await asyncio.gather(renewer, reconcile, return_exceptions=True)
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(seconds / 3):
                    await self.redis.eval(_RELEASE_LOCK, 1, key, token)
        return True

    async def _transition(self, job, *, phase, reason=None, result=None, safe=False):
        async with self.sessions() as db:
            current = await ExecutionRepository(db).owned(job.execution_id, self.owner, job.fence)
            if current is None:
                return False
            if phase == "completed" and current.cancel_requested:
                return False
            changed = current.phase != phase
            current.phase = phase
            current.failure_reason = reason
            if reason == "awaiting_verified_cancellation":
                current.cancel_requested = True
            current.result = result
            current.blocks_lab = not safe
            intent = await IntentRepository(db).get_by_id(current.intent_id)
            project_execution(intent, current, event=changed and (safe or phase == "uncertain"), db=db)
            await db.commit()
        return True

    async def _reconcile(self, job, lost):
        command = (PendingLabCommand if job.dispatched_at is None else LabCommand).model_validate_json(json.dumps(job.command))
        # Persist dispatch *possibility* before writing. Crash in between cannot be
        # distinguished from a lost acknowledgment and must reconcile this identity.
        if job.dispatched_at is None:
            async with self.sessions() as db:
                current = await ExecutionRepository(db).owned(job.execution_id, self.owner, job.fence)
                if current is None:
                    return
                cancelled = current.cancel_requested
                intent = await IntentRepository(db).get_by_id(current.intent_id)
                payload, network_id, workspace_id = intent.intent_payload, intent.network_id, intent.workspace_id
                await db.commit()
            if cancelled or datetime.now(UTC) >= command.deadline:
                await self._transition(job, phase="cancelled" if cancelled else "failed",
                    reason="cancelled_before_dispatch" if cancelled else "deadline_before_dispatch", safe=True)
                return
            try:
                async with self.sessions() as db:
                    plan, binding, snapshot = await prepare_plan(settings=self.settings, db=db, redis=self.redis,
                        workspace_id=workspace_id, network_id=network_id, actor_id=job.actor_id, payload=payload)
                if (digest(plan.model_dump(mode="json")) != command.plan_hash
                        or digest(binding.model_dump(mode="json")) != command.binding_digest or snapshot.run_id != command.run_id):
                    raise ValueError("approved lab identity changed")
            except Exception:  # noqa: BLE001 - deny before any dispatch on authority/infrastructure failure
                await self._transition(job, phase="failed", reason="dispatch_precondition_failed", safe=True)
                return
            if lost.is_set():
                return
            async with self.sessions() as db:
                current = await ExecutionRepository(db).owned(job.execution_id, self.owner, job.fence)
                if current is None:
                    return
                # A cancel racing the authorization check never authorizes execute.
                if current.cancel_requested or datetime.now(UTC) >= command.deadline:
                    await db.commit()
                    await self._transition(job, phase="cancelled", reason="cancelled_before_dispatch", safe=True)
                    return
                # Sample UTC before monotonic remaining authority: a pause between
                # samples can only shorten the authorization, never extend it.
                issued = datetime.now(UTC)
                remaining = min(5.0, lost.expires - time.monotonic(),
                                (current.lease_until - issued).total_seconds() - .1)
                if lost.is_set() or remaining <= 0:
                    return
                expires = min(command.deadline, issued + timedelta(seconds=remaining))
                command = LabCommand.model_validate({**command.model_dump(), "dispatch_expires_at": expires})
                current.command = command.model_dump(mode="json")
                current.dispatched_at = issued
                current.phase = "dispatching"
                intent = await IntentRepository(db).get_by_id(current.intent_id)
                project_execution(intent, current)
                await db.commit()
            if lost.is_set():
                return
            command.assert_new_dispatch(datetime.now(UTC))
            await asyncio.to_thread(self.mailbox.write, command, can_publish=lambda: not lost.is_set())
        # Recovered workers do not rewrite execute or change its fence. The lab
        # journal sees the original mailbox command and reconciles its before-state.
        while not lost.is_set():
            async with self.sessions() as db:
                current = await ExecutionRepository(db).owned(job.execution_id, self.owner, job.fence)
                if current is None:
                    return
                cancel_requested = current.cancel_requested
                await db.commit()
            try:
                result = await self.mailbox.read(job.execution_id)
                if result is not None:
                    if not result.matches(command):
                        raise ValueError("result identity mismatch")
                    now = datetime.now(UTC)
                    if result.completed_at < job.approved_at or result.completed_at > now:
                        raise ValueError("result time invalid")
                    probe = result.verification.get("probe", {})
                    verified = (verified_completion(result.verification)
                                and probe.get("source_host") == command.plan.source_host
                                and probe.get("destination_host") == command.plan.destination_host)
                    rollback_verified = verified_rollback(result.rollback)
                    safe = (result.status == "completed" and verified) or (
                        result.status in {"failed", "cancelled"}
                        and (rollback_verified or (result.rollback is None and verified_no_mutation(result.verification))))
                    if result.status == "completed" and (cancel_requested or result.completed_at > command.deadline):
                        if lost.is_set():
                            return
                        await asyncio.to_thread(self.mailbox.write, command.model_copy(update={"operation": "cancel"}),
                                                can_publish=lambda: not lost.is_set())
                        await self._transition(job, phase="uncertain", reason="awaiting_verified_cancellation")
                        return
                    phase = result.status if safe else "uncertain"
                    await self._transition(job, phase=phase, reason=result.failure_reason or (None if safe else "unverified_lab_state"),
                                           result=result.model_dump(mode="json"), safe=safe)
                    return
            except (OSError, ValueError):
                await self._transition(job, phase="uncertain", reason="invalid_or_unavailable_lab_evidence")
                return
            async with self.sessions() as db:
                current = await ExecutionRepository(db).owned(job.execution_id, self.owner, job.fence)
                if current is None:
                    return
                cancel = current.cancel_requested or datetime.now(UTC) >= command.deadline
                await db.commit()
            if cancel:
                if not lost.is_set():
                    # Only the operation changes; approval identity/fence/deadline
                    # stay fixed. Lab cancellation must reconcile/verify rollback.
                    await asyncio.to_thread(self.mailbox.write, command.model_copy(update={"operation": "cancel"}),
                                            can_publish=lambda: not lost.is_set())
                    await self._transition(job, phase="uncertain", reason="awaiting_verified_cancellation")
                return
            await asyncio.sleep(self.settings.EMULATION_EXECUTION_POLL_SECONDS)

    async def _publish_loop(self):
        while True:
            try:
                await self.publish_one()
            except Exception:
                logger.exception("intent_outbox_publication_failed", worker_id=self.owner)
            await asyncio.sleep(self.settings.EMULATION_EXECUTION_POLL_SECONDS)

    async def run(self):
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self._publish_loop())
            tasks.create_task(self._execution_loop())

    async def _execution_loop(self):
        while True:
            try:
                await self.run_one()
            except Exception:
                logger.exception("intent_execution_worker_iteration_failed", worker_id=self.owner)
            await asyncio.sleep(self.settings.EMULATION_EXECUTION_POLL_SECONDS)
