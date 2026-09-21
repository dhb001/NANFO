"""Durable joined loop: commit intent before I/O, restore after every uncertainty."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4, uuid5

from sqlalchemy import select

from app.modules.telemetry.pins import EvidenceOwnerScope, EvidenceReference, TelemetryEvidenceService

from .authority import active, frame_allowed, inference_allowed, simulation_allowed, verification_allowed
from .models import LabAction, LabReceipt, LabRun
from .persistence import LabRepository
from .schemas import (
    ActionCommand, BootstrapCommand, BootstrapReceipt, BootstrapRecoveryReceipt,
    ExecutionReceipt, ExperimentalPolicy, InferenceRecord, MeasuredFrame,
    PreparedAction, RecoveryReceipt, SimulationRecord, VerificationRecord, contract_digest, utcnow,
)


class ExperimentalController:
    def __init__(self, sessions, authority, ports, policy):
        self.sessions, self.authority, self.ports = sessions, authority, ports
        # Snapshot JSON prevents caller mutation of nested containers during a run.
        self.policy = ExperimentalPolicy.model_validate_json(policy.model_dump_json())
        self.token = uuid4()
        if ports is not None:
            ports.bind_checkpoint(self.checkpoint)

    async def _io(self, method, *args, recovery=False):
        """Supervise authority/STOP/lease even while an external operation blocks."""
        task = asyncio.create_task(method(*(arg if callable(arg) else deepcopy(arg) for arg in args)))
        try:
            async with asyncio.timeout(self.policy.io_timeout_seconds):
                while not task.done():
                    done, _ = await asyncio.wait({task}, timeout=self.policy.poll_seconds)
                    if done:
                        break
                    await self.checkpoint(recovery=recovery)
                return await task
        finally:
            if not task.done():
                task.cancel()
                # Cancellation is not a receipt; caller enters exact recovery.
                await asyncio.gather(task, return_exceptions=True)

    @asynccontextmanager
    async def transaction(self):
        # Both async_sessionmaker and the application's lazy AsyncSessionLocal work.
        async with self.sessions() as db, db.begin():
            yield db

    async def status(self):
        await self.authority.check(self.policy, write=False)
        async with self.sessions() as db:
            run = await db.get(LabRun, self.policy.run_id)
            if run is None:
                return {"run_id": str(self.policy.run_id), "phase": "not_started"}
            if run.policy_sha256 != contract_digest(self.policy):
                raise ValueError("experimental_run_policy_mismatch")
            receipts = (await db.scalars(select(LabReceipt).where(LabReceipt.run_id == run.run_id)
                .order_by(LabReceipt.created_at.desc()).limit(100))).all()
            return {"run_id": str(run.run_id), "phase": run.phase, "stopped": run.stopped,
                    "released": run.released, "fence": run.fence, "action_count": run.action_count,
                    "receipts": [{"kind": r.kind, "sha256": r.payload_sha256,
                                  "payload": r.payload} for r in receipts]}

    async def stop(self):
        await self.authority.check(self.policy)
        async with self.transaction() as db:
            repo = LabRepository(db)
            # Create a durable tombstone even when STOP wins the initial run race.
            await repo.create(self.policy, self.token, stopping=True)
            resource, run = await repo.lock(self.policy)
            run.stopped = True
            repo.receipt(run, None, "stop", {"actor_id": self.policy.actor_id})
            if (await repo.pending(run.run_id) is None and not run.released
                    and await self._bootstrap_record(db, "bootstrap_prepared") is None):
                repo.release(resource, run)
        return {"run_id": str(self.policy.run_id), "stopped": True}

    async def checkpoint(self, *, recovery=False, request_id=None, fresh_frame=False):
        # Finish initial owner-lock waits before reading current Identity/Network.
        # Recheck durable STOP/time after that service I/O, with no transaction open.
        await self._checkpoint_state(recovery=recovery, request_id=request_id, fresh_frame=fresh_frame)
        if not recovery:
            await self.authority.check(self.policy)
            deadline = await self._checkpoint_state(request_id=request_id, fresh_frame=fresh_frame)
            # Last owning-service read follows journal flush/commit and lock waits.
            # Receiver invokes this callback after its own durable write-ahead I/O.
            await self.authority.check(self.policy)
            active(self.policy)
            if utcnow() >= deadline:
                raise ValueError("experimental_checkpoint_elapsed_during_authority")
            # Identity above can block while STOP commits. Finish with one bounded
            # serialized decision: lock current control, flush, current DB authority,
            # then time/ownership validation. Never alternate unbounded rechecks.
            async with asyncio.timeout(min(5., self.policy.io_timeout_seconds)):
                deadline = await self._checkpoint_state(request_id=request_id,
                    fresh_frame=fresh_frame, final_authority=True)
            if utcnow() >= deadline:
                raise ValueError("experimental_checkpoint_elapsed_during_commit")

    async def _checkpoint_state(self, *, recovery=False, request_id=None, fresh_frame=False, final_authority=False):
        p = self.policy
        async with self.transaction() as db:
            repo = LabRepository(db)
            resource, run = await repo.lock(p)
            repo.owned(resource, run, self.token)
            if not recovery:
                active(p)
                if run.stopped:
                    raise ValueError("experimental_stop_latched")
                pending = await repo.pending(run.run_id)
                if pending is not None and pending.command is not None:
                    if utcnow() >= ActionCommand.model_validate(pending.command).expires_at:
                        raise ValueError("experimental_action_expired")
                if request_id is not None:
                    action = await db.get(LabAction, request_id)
                    if action is None or action.run_id != run.run_id:
                        raise ValueError("experimental_action_missing")
                    command = ActionCommand.model_validate(action.command)
                    if utcnow() >= command.expires_at:
                        raise ValueError("experimental_action_expired")
                    if fresh_frame:
                        if action.phase not in ("prepared", "dispatching"):
                            raise ValueError("experimental_execute_phase_closed")
                        frame_allowed(p, MeasuredFrame.model_validate(action.frame),
                                      measurement_run_id=await self._measurement_identity(db))
            run.lease_until = utcnow() + timedelta(seconds=p.lease_seconds)
            deadline = min(run.lease_until, p.expires_at)
            if not recovery and pending is not None and pending.command is not None:
                deadline = min(deadline, ActionCommand.model_validate(pending.command).expires_at)
                if fresh_frame:
                    observed = MeasuredFrame.model_validate(pending.frame).snapshot.observed_at
                    deadline = min(deadline, observed + timedelta(seconds=p.max_observation_age_seconds))
            if final_authority:
                # This tuple is the current immutable control identity plus its
                # monotone STOP latch; no extra migration/control enum is needed.
                revision = (run.policy_sha256, run.fence, run.lease_token, run.stopped, run.released)
                await db.flush()
                check = getattr(type(self.authority), "check_in_transaction", None)
                if check is None:
                    # Injected test/in-process authority must obey the same bounded
                    # read-only contract. Production uses CurrentAuthority above.
                    await self.authority.check(p)
                else:
                    await check(self.authority, db, p)
                if revision != (run.policy_sha256, run.fence, run.lease_token, run.stopped, run.released):
                    raise ValueError("experimental_control_changed_during_authority")
                if run.stopped:
                    raise ValueError("experimental_stop_latched")
                repo.owned(resource, run, self.token)
                active(p)
                if utcnow() >= deadline:
                    raise ValueError("experimental_checkpoint_elapsed_during_authority")
            return deadline

    async def _bootstrap_record(self, db, kind):
        row = await db.scalar(select(LabReceipt).where(LabReceipt.run_id == self.policy.run_id,
                                                       LabReceipt.kind == kind))
        return row.payload if row else None

    async def _measurement_identity(self, db):
        command = await self._bootstrap_record(db, "bootstrap_prepared")
        receipt = await self._bootstrap_record(db, "bootstrap_completed")
        if command and not receipt:
            raise ValueError("experimental_bootstrap_incomplete_recover_required")
        return BootstrapReceipt.model_validate(receipt).measurement_run_id if receipt else None

    async def admit_bootstrap(self, command):
        """Campaign calls BEFORE reset I/O; baseline capture itself must be read-only."""
        command = BootstrapCommand.model_validate(command)
        p = self.policy
        if command.run_id != p.run_id or command.runtime != p.runtime or command.policy_sha256 != contract_digest(p):
            raise ValueError("experimental_bootstrap_scope_mismatch")
        await self.authority.check(p)
        active(p)
        async with self.transaction() as db:
            repo = LabRepository(db)
            run = await repo.create(p, self.token)
            run.phase = "bootstrap_prepared"
            repo.receipt(run, None, "bootstrap_prepared", command.model_dump(mode="json"))

    async def complete_bootstrap(self, receipt):
        """Retain authoritative receiver episode and model bindings after reset."""
        receipt = BootstrapReceipt.model_validate(receipt)
        p = self.policy
        async with self.transaction() as db:
            repo = LabRepository(db)
            resource, run = await repo.lock(p)
            repo.owned(resource, run, self.token)
            command = BootstrapCommand.model_validate(await self._bootstrap_record(db, "bootstrap_prepared"))
            if (await self._bootstrap_record(db, "bootstrap_completed") is not None
                    or receipt.request_id != command.request_id or receipt.command_sha256 != contract_digest(command)
                    or receipt.runtime != p.runtime or receipt.baseline_sha256 != command.baseline_sha256
                    or receipt.ownership_sha256 != command.ownership_sha256
                    or any(getattr(receipt, key) != getattr(p, key) for key in (
                        "registry_sha256", "checkpoint_sha256", "weights_sha256", "model_source_sha256"))
                    or p.measurement_run_id is not None and receipt.measurement_run_id != p.measurement_run_id):
                raise ValueError("experimental_bootstrap_receipt_mismatch")
            run.phase = "bootstrapped"
            repo.receipt(run, None, "bootstrap_completed", receipt.model_dump(mode="json"))

    async def bootstrap(self, command, reset):
        """Commit ownership then supervise campaign reset(command, checkpoint).

        Reset returns BootstrapReceipt; failure recovers without replaying reset.
        """
        command = BootstrapCommand.model_validate(command)
        await self.admit_bootstrap(command)
        try:
            receipt = await self._io(reset, command, self.checkpoint)
            await self.complete_bootstrap(receipt)
            return BootstrapReceipt.model_validate(receipt)
        except (Exception, asyncio.CancelledError):
            await asyncio.shield(self.recover())
            raise

    async def _frame_allowed(self, frame):
        async with self.sessions() as db:
            identity = await self._measurement_identity(db)
        frame_allowed(self.policy, frame, measurement_run_id=identity)

    async def _phase(self, request_id, phase, *, field=None, record=None, recovery=False):
        async with self.transaction() as db:
            repo = LabRepository(db)
            resource, run = await repo.lock(self.policy)
            repo.owned(resource, run, self.token)
            if not recovery:
                active(self.policy)
                if run.stopped:
                    raise ValueError("experimental_stop_latched")
            action = await db.get(LabAction, request_id)
            if action is None or action.run_id != run.run_id:
                raise ValueError("experimental_action_missing")
            if field:
                if getattr(action, field) is not None:
                    raise ValueError("experimental_record_already_written")
                setattr(action, field, record.model_dump(mode="json"))
            if field == "frame":
                service = TelemetryEvidenceService(db, scope=EvidenceOwnerScope(
                    owner="autonomy", workspace_id=self.policy.workspace_id))
                for record_id in record.telemetry_record_ids:
                    await service.pin(EvidenceReference(network_id=self.policy.network_id, record_id=record_id,
                        reference_id=uuid5(request_id, str(record_id))))
            action.phase = run.phase = phase
            run.lease_until = utcnow() + timedelta(seconds=self.policy.lease_seconds)
            repo.receipt(run, action, phase, record.model_dump(mode="json") if record else {"phase": phase})

    async def _begin_action(self):
        await self.checkpoint()
        p = self.policy
        async with self.transaction() as db:
            repo = LabRepository(db)
            resource, run = await repo.lock(p)
            repo.owned(resource, run, self.token)
            active(p)
            if run.stopped or await repo.pending(run.run_id):
                raise ValueError("experimental_stopped_or_pending")
            await self._measurement_identity(db)
            if (run.action_count >= p.max_actions
                    or await repo.count_window(run.run_id, p.action_window_seconds) >= p.max_actions_per_window
                    or run.last_dispatched_at is not None
                    and (utcnow() - run.last_dispatched_at).total_seconds() < p.min_dwell_seconds):
                raise ValueError("experimental_action_budget_or_dwell")
            action = LabAction(request_id=uuid4(), run_id=run.run_id, phase="observing")
            db.add(action)
            await db.flush()
            repo.receipt(run, action, "observing", {"fence": run.fence})
            return action.request_id, run.fence

    async def _dispatch(self, request_id):
        await self.checkpoint(request_id=request_id, fresh_frame=True)
        async with self.transaction() as db:
            repo = LabRepository(db)
            resource, run = await repo.lock(self.policy)
            repo.owned(resource, run, self.token)
            active(self.policy)
            action = await db.get(LabAction, request_id)
            if run.stopped or action.phase != "prepared":
                raise ValueError("experimental_dispatch_denied")
            action.phase = run.phase = "dispatching"
            action.dispatched_at = run.last_dispatched_at = utcnow()
            run.action_count += 1
            repo.receipt(run, action, "dispatching", {"command_sha256": contract_digest(action.command)})

    async def step(self):
        """One freshly admitted action; caller must first admit the run with run()."""
        request_id, fence = await self._begin_action()
        p = self.policy
        frame = MeasuredFrame.model_validate(await self._io(self.ports.observer.observe))
        await self._phase(request_id, "observed", field="frame", record=frame)
        await self._frame_allowed(frame)
        inference = InferenceRecord.model_validate(await self._io(self.ports.model.infer, frame))
        await self._phase(request_id, "inferred", field="inference", record=inference)
        route = inference_allowed(p, frame, inference)
        simulation = SimulationRecord.model_validate(await self._io(self.ports.simulator.simulate, frame, inference, p))
        # Persist negative simulation results as evidence before rejection.
        await self._phase(request_id, "simulated", field="simulation", record=simulation)
        simulation_allowed(p, frame, inference, simulation)
        await self._frame_allowed(frame)
        now = utcnow()
        command = ActionCommand(request_id=request_id, run_id=p.run_id, resource_id=p.runtime.resource_id,
            fence=fence, network_id=p.network_id, workspace_id=p.workspace_id, runtime=p.runtime, route=route,
            policy_sha256=contract_digest(p), frame_sha256=contract_digest(frame),
            inference_sha256=contract_digest(inference), simulation_sha256=contract_digest(simulation),
            created_at=now, expires_at=min(p.expires_at, now + timedelta(seconds=p.max_action_duration_seconds)))
        await self._phase(request_id, "preparing", field="command", record=command)
        prepared = PreparedAction.model_validate(await self._io(self.ports.transport.prepare, command))
        if prepared.command != command:
            raise ValueError("experimental_preparation_changed_command")
        await self._phase(request_id, "prepared", field="prepared", record=prepared)
        await self._dispatch(request_id)

        async def checkpoint():
            await self.checkpoint(request_id=request_id, fresh_frame=True)

        receipt = ExecutionReceipt.model_validate(await self._io(self.ports.transport.execute, prepared, checkpoint))
        await self._phase(request_id, "verifying", record=receipt)
        if (receipt.request_id != request_id or receipt.action_sha256 != contract_digest(prepared)
                or receipt.action_id != route.action_id or receipt.status != "applied"):
            raise ValueError("experimental_execution_uncertain")
        while True:
            await self.checkpoint(request_id=request_id)
            verification = VerificationRecord.model_validate(await self._io(self.ports.transport.verify, prepared))
            await self._phase(request_id, "verified", record=verification)
            verification_allowed(p, prepared, verification)
            await self.checkpoint(request_id=request_id)
            await self._phase(request_id, "holding")
            remaining = (command.expires_at - utcnow()).total_seconds()
            if remaining <= p.poll_seconds:
                await self._restore(request_id)
                return
            await asyncio.sleep(p.poll_seconds)

    async def _restore(self, request_id):
        async with self.transaction() as db:
            repo = LabRepository(db)
            resource, run = await repo.lock(self.policy)
            repo.owned(resource, run, self.token)
            action = await db.get(LabAction, request_id)
            if action is None or action.run_id != run.run_id:
                raise ValueError("experimental_action_missing")
            if action.prepared is None:
                # prepare is strictly read-only, so no owned mutation can exist here.
                action.phase = "rejected"
                repo.receipt(run, action, "rejected", {"reason": "not_dispatched"})
                return
            prepared = PreparedAction.model_validate(action.prepared)
            action.phase = run.phase = "recovering"
            run.lease_until = utcnow() + timedelta(seconds=self.policy.lease_seconds)
            repo.receipt(run, action, "recovering", {"action_sha256": contract_digest(prepared)})

        async def checkpoint():
            await self.checkpoint(recovery=True)

        try:
            result = RecoveryReceipt.model_validate(await self._io(
                self.ports.transport.recover, prepared, checkpoint, recovery=True))
            if (result.request_id != request_id or result.action_sha256 != contract_digest(prepared)
                    or result.baseline_sha256 != prepared.baseline_sha256 or result.status != "restored"):
                raise ValueError("experimental_recovery_uncertain")
            await self._phase(request_id, "restored", record=result, recovery=True)
        except Exception:
            await self._phase(request_id, "uncertain", recovery=True)
            raise

    async def recover(self):
        """Protected installed policy + durable ownership, never fresh user approval."""
        async with self.transaction() as db:
            repo = LabRepository(db)
            run = await repo.claim_recovery(self.policy, self.token)
            if run.released:
                return {"phase": "restored", "released": True}
            pending = await repo.pending(run.run_id)
            request_id = pending.request_id if pending else None
            repo.receipt(run, pending, "recovery_claimed", {"fence": run.fence})
        if request_id:
            await self._restore(request_id)
        await self._recover_bootstrap()
        async with self.transaction() as db:
            repo = LabRepository(db)
            resource, run = await repo.lock(self.policy)
            repo.owned(resource, run, self.token)
            if await repo.pending(run.run_id):
                raise ValueError("experimental_unresolved_action")
            repo.release(resource, run)
        return {"phase": "restored", "released": True}

    async def _recover_bootstrap(self):
        async with self.transaction() as db:
            repo = LabRepository(db)
            resource, run = await repo.lock(self.policy)
            repo.owned(resource, run, self.token)
            data = await self._bootstrap_record(db, "bootstrap_prepared")
            if data is None or await self._bootstrap_record(db, "bootstrap_restored"):
                return
            command = BootstrapCommand.model_validate(data)
            run.phase = "bootstrap_recovering"
            repo.receipt(run, None, "bootstrap_recovering", {"command_sha256": contract_digest(command)})

        async def checkpoint():
            await self.checkpoint(recovery=True)

        # Missing transport support must retain ownership, never silently release.
        try:
            result = BootstrapRecoveryReceipt.model_validate(await self._io(
                self.ports.transport.recover_bootstrap, command, checkpoint, recovery=True))
            if (result.status != "restored" or result.request_id != command.request_id
                    or result.command_sha256 != contract_digest(command)
                    or result.baseline_sha256 != command.baseline_sha256
                    or result.ownership_sha256 != command.ownership_sha256):
                raise ValueError("experimental_bootstrap_recovery_uncertain")
        except Exception as exc:
            async with self.transaction() as db:
                repo = LabRepository(db)
                resource, run = await repo.lock(self.policy)
                repo.owned(resource, run, self.token)
                run.phase = "uncertain"
                repo.receipt(run, None, "bootstrap_uncertain", {"error_type": type(exc).__name__})
            raise
        async with self.transaction() as db:
            repo = LabRepository(db)
            resource, run = await repo.lock(self.policy)
            repo.owned(resource, run, self.token)
            repo.receipt(run, None, "bootstrap_restored", result.model_dump(mode="json"))

    async def run(self, *, admitted_bootstrap=False):
        active(self.policy)
        await self.authority.check(self.policy)
        async with self.transaction() as db:
            active(self.policy)
            repo = LabRepository(db)
            if admitted_bootstrap:
                resource, run = await repo.lock(self.policy)
                repo.owned(resource, run, self.token)
                if run.phase != "bootstrapped" or run.stopped:
                    raise ValueError("experimental_bootstrap_not_ready")
                await self._measurement_identity(db)
            else:
                await repo.create(self.policy, self.token)
        try:
            for index in range(self.policy.max_actions):
                await self.step()
                if index == self.policy.max_actions - 1:
                    break
                # Refresh lease during dwell, with STOP/current authority checks.
                until = utcnow() + timedelta(seconds=self.policy.min_dwell_seconds)
                while utcnow() < until:
                    await self.checkpoint()
                    await asyncio.sleep(min(self.policy.poll_seconds, (until - utcnow()).total_seconds()))
        except (Exception, asyncio.CancelledError) as exc:
            # Failure class only: adapter exception strings may contain secrets.
            async with self.transaction() as db:
                repo = LabRepository(db)
                _, run = await repo.lock(self.policy)
                repo.receipt(run, await repo.pending(run.run_id), "interrupted", {"error_type": type(exc).__name__})
            await asyncio.shield(self.recover())
            raise
        return await self.recover()
