"""Durable autonomous executor/recovery and PostgreSQL-backed receiver journal."""

import asyncio
import hashlib
import uuid

from sqlalchemy import text

from app.modules.autonomy.execution_authority import ExecutionAuthority
from app.modules.autonomy.execution_client import JournalReferences
from app.modules.autonomy.execution_contract import AutonomousCommand
from app.modules.autonomy.execution_repository import ExecutionRepository
from app.modules.autonomy.provider_state import ProviderStateRepository
from app.modules.autonomy.safety_provider import CalibratedSafetyProvider
from app.modules.autonomy.schemas import ProviderStatus, SafetyAssessment, Verification
from emulation.autonomous_receiver import AutonomousReceiver


def valid_readback(evidence, *, recovery=False):
    digest = evidence.get("readback_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        return False
    if recovery:
        return evidence.get("restoration_verified") is True
    probe = evidence.get("probe", {})
    return (evidence.get("readback_verified") is True and type(probe.get("sent")) is int
            and probe["sent"] > 0 and probe.get("received") == probe["sent"])


class ReceiverJournal:
    def __init__(self, sessions, authority, command, token, *, exclusion_check=None):
        self.sessions, self.authority, self.command, self.token = sessions, authority, command, token
        self.exclusion_check = exclusion_check

    async def exclusion(self):
        if self.exclusion_check is not None:
            await self.exclusion_check()

    async def inspect(self, command):
        async with self.sessions() as db:
            row = await ExecutionRepository(db).owned(command, self.token)
            result = {key: getattr(row, key) for key in ("released", "result", "phase", "prepared", "cancel_requested")}
            await db.commit()
            return result

    async def checkpoint(self, command, *, mutation):
        await self.exclusion()
        async with self.sessions() as db:
            installation = self.authority.safety.installation
            if installation.data.version.endswith("/v2"):
                command.validate_installed_service(installation)
            safety = SafetyAssessment.model_validate_json(command.authorization.safety_evidence_json)
            if (command.installation_sha256 != installation.sha256
                    or command.plan != installation.action(safety.action_id).plan):
                raise ValueError("receiver_installed_plan_mismatch")
            await self.authority.check(db, command.authorization, accepted=True)
            row = await ExecutionRepository(db).owned(command, self.token)
            if row.cancel_requested or (mutation and row.phase != "applying"):
                raise ValueError("receiver_cancelled_or_wrong_phase")
            await db.flush()
            await self.exclusion()
            # Control was locked first. Re-read current membership and clocks only
            # after the execution/resource lock waits and flush are complete.
            await self.authority.check(db, command.authorization, accepted=True)
            await db.commit()

    async def recovery_checkpoint(self, command):
        await self.exclusion()
        async with self.sessions() as db:
            row = await ExecutionRepository(db).owned(command, self.token)
            if row.phase != "recovering" or row.prepared is None:
                raise ValueError("exact_compensation_not_owned")
            await db.commit()

    async def prepare(self, command, prepared):
        async with self.sessions() as db:
            row = await ExecutionRepository(db).owned(command, self.token)
            if row.phase != "accepted" or row.prepared is not None:
                raise ValueError("preparation_already_persisted")
            row.prepared, row.phase = prepared, "prepared"
            await db.commit()

    async def begin_apply(self, command):
        await self.exclusion()
        async with self.sessions() as db:
            await self.authority.check(db, command.authorization, accepted=True)
            repo = ExecutionRepository(db)
            row = await repo.owned(command, self.token)
            if row.phase != "prepared" or row.cancel_requested:
                raise ValueError("dispatch_not_owned")
            safety = SafetyAssessment.model_validate_json(command.authorization.safety_evidence_json)
            history = await ProviderStateRepository(db).history(row.network_id, lock=True)
            original = safety.binding.state
            expected = original.model_dump(mode="json")
            if (history is None or any(history.state[key] != expected[key] for key in expected
                                       if key not in {"snapshot_id", "observed_at_unix_seconds"})):
                raise ValueError("dispatch_history_changed")
            await self.exclusion()
            await self.authority.check(db, command.authorization, accepted=True)
            now = await repo.now()
            state = dict(history.state)
            state["last_evaluated_sequence"] = safety.binding.observation.sequence
            state["last_applied_at_unix_seconds"] = now.timestamp()
            state["recent_dispatch_at_unix_seconds"] = [t for t in state["recent_dispatch_at_unix_seconds"]
                if t >= now.timestamp() - max(60, safety.binding.policy.rate_window_seconds)] + [now.timestamp()]
            history.state = state
            row.phase, row.dispatched_at = "applying", now
            await db.flush()
            await self.authority.check(db, command.authorization, accepted=True)
            await db.commit()

    async def begin_recovery(self, command):
        await self.exclusion()
        async with self.sessions() as db:
            row = await ExecutionRepository(db).owned(command, self.token)
            row.phase, row.cancel_requested = "recovering", True
            await db.commit()

    async def verified(self, command, evidence):
        if not valid_readback(evidence):
            raise ValueError("device_readback_invalid")
        return await self.finish(command, "verified", evidence, released=False)

    async def cancelled(self, command, evidence):
        return await self.finish(command, "cancelled", evidence, released=True)

    async def uncertain(self, command):
        return await self.finish(command, "uncertain", {}, released=False)

    async def finish(self, command, phase, evidence, *, released):
        async with self.sessions() as db:
            if phase == "verified":
                await self.authority.check(db, command.authorization, accepted=True)
            repo = ExecutionRepository(db)
            row = await repo.owned(command, self.token)
            no_dispatch = row.phase in {"accepted", "prepared"} and row.dispatched_at is None
            if released and not ((no_dispatch and evidence.get("not_dispatched") is True)
                                 or valid_readback(evidence, recovery=True)):
                raise ValueError("compensation_not_verified")
            if phase in {"verified", "cancelled"} and row.dispatched_at:
                history = await ProviderStateRepository(db).history(row.network_id, lock=True)
                safety = SafetyAssessment.model_validate_json(command.authorization.safety_evidence_json)
                state = dict(history.state)
                routes = safety.selected_action.routes if phase == "verified" else safety.binding.state.active_routes
                state["active_routes"] = [route.model_dump(mode="json") for route in routes]
                if row.phase != phase:
                    stamp = (await repo.now()).timestamp()
                    state["route_since_unix_seconds"] = stamp
                    state["last_applied_at_unix_seconds"] = stamp
                    state["recent_dispatch_at_unix_seconds"] = [t for t in state["recent_dispatch_at_unix_seconds"]
                        if t >= stamp - max(60, safety.binding.policy.rate_window_seconds)] + [stamp]
                history.state = state
            result = Verification(execution_id=row.execution_id, status=phase, safe_to_release=released,
                evidence=["autonomous_execution:" + str(row.execution_id),
                          "readback:" + evidence["readback_sha256"]] if evidence.get("readback_sha256") else
                         ["persisted_no_dispatch:" + str(row.execution_id)] if no_dispatch and released else [],
                reasons=["policy_remains_owned"] if phase == "verified" else
                        ["exact_recovery_required"] if phase == "uncertain" else [])
            row.phase, row.released = phase, released
            row.result = {**result.model_dump(mode="json"), "device_evidence": evidence}
            row.updated_at = await repo.now()
            await db.flush()
            if phase == "verified":
                await self.exclusion()
                await self.authority.check(db, command.authorization, accepted=True)
            await db.commit()
            return result


class AutonomousExecutor(JournalReferences):
    def __init__(self, sessions, redis, installation, driver, resource_id, *, execution_mode="emulation"):
        if (not driver or driver.resource_id != resource_id or str(driver.run_id) != installation.data.calibration.run_id
                or driver.driver_id != installation.data.runtime_action):
            raise ValueError("installed_lab_driver_scope_mismatch")
        if execution_mode != "emulation":
            raise ValueError("production_autonomous_driver_unavailable")
        self.sessions, self.redis, self.installation = sessions, redis, installation
        self.driver, self.resource_id = driver, resource_id
        self.authority = ExecutionAuthority(redis, CalibratedSafetyProvider(sessions, installation), execution_mode=execution_mode)
        if driver.driver_id == "isolated-linux-frr-host-route/v1":
            if not callable(getattr(driver, "dispatch_guard", None)):
                raise ValueError("frr_independent_dispatch_guard_required")
            self.authority.runtime_guard = driver.dispatch_guard
        self.status = ProviderStatus(provider_id="durable-autonomous-lab/v1", status="ready")
        self.health_publisher = None

    async def publish_health(self):
        if self.health_publisher is not None:
            await self.driver.healthcheck()
            await self.health_publisher.completed()

    async def accept(self, db, authorization):
        await self.authority.check(db, authorization)
        await ExecutionRepository(db).stage(authorization, self.installation, self.resource_id)
        await self.authority.check(db, authorization)

    async def run_one(self, *, execution_id=None, recovery_only=False):
        if recovery_only and execution_id is None:
            raise ValueError("exact_recovery_execution_required")
        # Session advisory lock survives commits; losing Redis expiry cannot allow
        # a successor to overlap a still-running device call. No transaction spans I/O.
        lock_id = int.from_bytes(hashlib.sha256(self.resource_id.encode()).digest()[:8], "big", signed=True)
        async with self.sessions() as lock_session:
            connection = await lock_session.connection()
            acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_id})
            backend_pid = await connection.scalar(text("SELECT pg_backend_pid()"))
            await connection.commit()
            if not acquired:
                return False
            redis_key, redis_token = "autonomous:resource:" + self.resource_id, str(uuid.uuid4())
            redis_owned = False
            try:
                redis_owned = bool(await self.redis.set(redis_key, redis_token, nx=True, ex=30))
                if not redis_owned:
                    return False
                async with self.sessions() as db:
                    row = await ExecutionRepository(db).claim(self.resource_id, execution_id=execution_id, recovery_only=recovery_only)
                    if row is None:
                        await db.commit()
                        if not recovery_only:
                            await self.publish_health()
                        return False
                    command = AutonomousCommand.model_validate(row.command)
                    if command.installation_sha256 != self.installation.sha256:
                        if recovery_only:
                            raise ValueError("recovery_installation_identity_mismatch")
                        # Old exact compensation remains permitted under its original journal.
                        row.cancel_requested = True
                    token = row.lease_token
                    await db.commit()
                if recovery_only:
                    command = command.model_copy(update={"operation": "recover"})
                async def exclusion_check():
                    # A reconnected SQLAlchemy connection must not inherit the old
                    # process's advisory authority. Refresh Redis without extending
                    # a successor's key, and test the original DB session identity.
                    pid = await connection.scalar(text("SELECT pg_backend_pid()"))
                    await connection.commit()
                    if pid != backend_pid:
                        raise ValueError("receiver_advisory_session_lost")
                    renewed = await self.redis.eval(
                        "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('expire',KEYS[1],30) else return 0 end",
                        1, redis_key, redis_token)
                    if not renewed:
                        raise ValueError("receiver_distributed_lock_lost")

                journal = ReceiverJournal(self.sessions, self.authority, command, token, exclusion_check=exclusion_check)
                result = await AutonomousReceiver(self.driver).receive(command, journal)
                async with self.sessions() as db:
                    current = await ExecutionRepository(db).get(command.execution_id, lock=True)
                    if current.lease_token == token:
                        current.lease_token, current.lease_until = None, None
                    await db.commit()
                if not recovery_only and result.status != "uncertain":
                    await self.publish_health()
                return True
            finally:
                try:
                    if redis_owned:
                        await self.redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
                                              1, redis_key, redis_token)
                finally:
                    try:
                        await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id})
                        await connection.commit()
                    except BaseException:
                        await connection.invalidate()
                        raise

    async def run(self):
        from app.core.logging import get_logger
        logger = get_logger(__name__)
        while True:
            try:
                await self.run_one()
            except Exception:
                logger.warning("autonomous_receiver_iteration_failed")
            await asyncio.sleep(1)


def build_execution_providers(sessions, redis, installation, driver, resource_id, *, execution_mode="emulation"):
    executor = AutonomousExecutor(sessions, redis, installation, driver, resource_id, execution_mode=execution_mode)
    return executor, executor
