"""Unprivileged durable acceptance/readback/recovery request client. No driver loop."""

import asyncio
import time
import os

from app.modules.autonomy.execution_repository import ExecutionRepository
from app.modules.autonomy.schemas import ProviderStatus, SafetyAssessment, Verification, contract_digest


class JournalReferences:
    """Shared exact-identity readback and cancellation request operations."""

    async def verify(self, reference):
        async with self.sessions() as db:
            row = await ExecutionRepository(db).reference(reference)
            if row.result:
                return Verification.model_validate({k: v for k, v in row.result.items() if k != "device_evidence"})
            return Verification(execution_id=reference.execution_id, status="pending", reasons=["durable_work_pending"])

    async def cancel(self, reference):
        # Exact persisted identity only. No current actor/health dependency for recovery.
        async with self.sessions() as db:
            row = await ExecutionRepository(db).reference(reference, lock=True)
            row.cancel_requested = True
            await db.commit()
        return await self.verify(reference)


class JournalExecutionClient(JournalReferences):
    def __init__(self, sessions, redis, installation, resource_id, health, *, reload_installation=None,
                 config_identity=None):
        self.sessions, self.redis, self.installation = sessions, redis, installation
        self.resource_id, self.health, self.reload_installation = resource_id, health, reload_installation
        self._ready_until = 0.
        self.config_identity = config_identity

    @property
    def status(self):
        ready = time.monotonic() < self._ready_until
        return ProviderStatus(provider_id="autonomous-journal-client/v1", status="ready" if ready else "unavailable",
                              reasons=[] if ready else ["receiver_progress_unavailable_or_stale"])

    async def refresh_status(self):
        self._ready_until = 0.
        try:
            if self.reload_installation is not None:
                current, key, identity = await asyncio.to_thread(self.reload_installation)
                if (identity != self.config_identity or current.sha256 != self.installation.sha256
                        or key != self.health.key):
                    raise ValueError("autonomous_installation_changed")
            self.installation.assert_reviewed_execution()
            body = await self.health.check()
            remaining = self.health.max_age - (time.time() - body["completed_at"])
            self._ready_until = time.monotonic() + max(0, remaining)
        except Exception:
            return self.status
        return self.status

    async def accept(self, db, authorization):
        from app.core.config import get_settings
        from app.modules.autonomy.execution_authority import ExecutionAuthority
        from app.modules.autonomy.safety_provider import CalibratedSafetyProvider
        if get_settings().EXECUTION_MODE != "emulation" or (await self.refresh_status()).status != "ready":
            raise ValueError("autonomous_receiver_not_ready")
        authority = ExecutionAuthority(self.redis, CalibratedSafetyProvider(self.sessions, self.installation), execution_mode="emulation")
        await authority.check(db, authorization)
        await ExecutionRepository(db).stage(authorization, self.installation, self.resource_id)
        if (await self.refresh_status()).status != "ready":
            raise ValueError("autonomous_receiver_not_ready_after_staging")
        await authority.check(db, authorization)

class BlockedExecutionInstallation(JournalReferences):
    status = ProviderStatus(provider_id="autonomous-configured-invalid/v1", status="unavailable",
                            reasons=["autonomous_installation_invalid_or_incompatible"])

    def __init__(self, sessions):
        self.sessions = sessions

    async def assess(self, observation, proposal):
        return SafetyAssessment(admissible=False, model_version="unavailable", reasons=self.status.reasons)

    async def accept(self, db, authorization):
        raise ValueError(self.status.reasons[0])

def installed_execution_clients(sessions, redis):
    from app.core.config import get_settings
    from app.modules.autonomy.execution_settings import CONFIG_HASH, CONFIG_PATH, load_config
    from app.modules.autonomy.receiver_health import ReceiverHealth
    from app.modules.autonomy.safety_provider import CalibratedSafetyProvider
    try:
        if get_settings().EXECUTION_MODE != "emulation":
            raise ValueError("autonomous_emulation_required")
        config = load_config()
        def identity(value):
            return (os.environ.get(CONFIG_PATH), os.environ.get(CONFIG_HASH), contract_digest(value))
        config_identity = identity(config)
        installation, key = config.load()
        health = ReceiverHealth(redis, installation, config.resource_id, key, max_age_seconds=config.health_max_age_seconds)
        def reload():
            current = load_config()
            current_identity = identity(current)
            if current_identity != config_identity:
                raise ValueError("autonomous_config_changed_restart_required")
            updated, updated_key = current.load()
            return updated, updated_key, current_identity
        client = JournalExecutionClient(sessions, redis, installation, config.resource_id, health,
                                       reload_installation=reload, config_identity=config_identity)
        return CalibratedSafetyProvider(sessions, installation), client, client
    except Exception:
        blocked = BlockedExecutionInstallation(sessions)
        return blocked, blocked, blocked
