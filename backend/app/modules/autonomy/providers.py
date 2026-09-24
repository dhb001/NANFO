"""Installed providers fail closed. Test providers are injected, never auto-installed."""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.autonomy.schemas import (
    ExecutionAuthorization,
    ExecutionReference,
    Observation,
    ObservationSample,
    Proposal,
    ProviderStatus,
    ProviderStatuses,
    Qualification,
    SafetyAssessment,
    Verification,
)
from app.modules.telemetry.service import TelemetryQueryService


class Observer(Protocol):
    status: ProviderStatus

    async def observe(self, network_id: uuid.UUID, workspace_id: uuid.UUID) -> Observation: ...


class ModelProvider(Protocol):
    qualification_status: ProviderStatus
    inference_status: ProviderStatus

    async def qualify(self, checkpoint_sha256: str | None) -> Qualification: ...

    async def infer(self, observation: Observation, qualification: Qualification) -> Proposal: ...


class SafetyProvider(Protocol):
    status: ProviderStatus

    async def assess(self, observation: Observation, proposal: Proposal) -> SafetyAssessment: ...


class DurableExecutor(Protocol):
    status: ProviderStatus

    async def accept(self, db: AsyncSession, authorization: ExecutionAuthorization) -> None:
        """Enlist durable work in db, no commit, external I/O or manual approval.

        Receiver MUST recheck server-owned authorization, deadline, stop/revision,
        current actor and distributed actuation lock. IDs are fixed by authorization.
        MUST validate canonical safety/action hashes, trusted calibration binding,
        exact selected routes and exclusive certificate expiry at the receiver.
        Returning only means staged acceptance, never verification.
        """
        ...

    async def verify(self, reference: ExecutionReference) -> Verification:
        """Read-only exact persisted ownership verification, independent of actor revocation."""
        ...


class RecoveryProvider(Protocol):
    async def cancel(self, reference: ExecutionReference) -> Verification:
        """Separately governed server authority; recheck ownership/fence at receiver.

        No impersonation, permission synthesis, manual approval or new execution.
        May only compensate the exact persisted Autonomy execution.
        """
        ...


class UnavailableRecovery:
    async def cancel(self, reference):
        return Verification(execution_id=reference.execution_id, status="uncertain",
                            reasons=["autonomous_recovery_unavailable", "operator_recovery_required"])


class TelemetryObserver:
    status = ProviderStatus(provider_id="adr009_history_v1", status="incompatible",
                            reasons=["observation_contract_incompatible"])

    def __init__(self, sessions):
        self.sessions = sessions

    async def observe(self, network_id, workspace_id):
        now = datetime.now(UTC)
        async with self.sessions() as db:
            history = await TelemetryQueryService(db=db).get_history(
                network_id=network_id, workspace_id=workspace_id, metric=None, page=1, page_size=100,
                start_time=now - timedelta(minutes=5), end_time=now,
            )
        samples = [ObservationSample(
            record_id=row.record_id, device_id=row.device_id, metric=row.metric, value=row.value,
            unit=row.unit, observed_at=row.observed_at, source=row.source,
            run_id=str(row.tags["run_id"]) if row.tags.get("run_id") else None,
            port_no=str(row.tags["port_no"]) if row.tags.get("port_no") is not None else None,
        ) for row in history.items if row.network_id == network_id and row.workspace_id == workspace_id
            and row.tags.get("synthetic") is False and row.tags.get("execution_mode") == "emulation"]
        observed_at = max((sample.observed_at for sample in samples), default=None)
        age = (now - observed_at).total_seconds() if observed_at else None
        fresh = age is not None and 0 <= age <= 30
        reasons = ["observation_contract_incompatible"]
        if not samples:
            reasons.append("observation_unavailable")
        elif not fresh:
            reasons.append("observation_stale")
        return Observation(network_id=network_id, workspace_id=workspace_id,
            provider_id=self.status.provider_id, contract="adr009.telemetry.v1", observed_at=observed_at,
            collected_at=now, age_seconds=age, fresh=fresh, compatible=False, reasons=reasons,
            samples=samples, evidence=[f"telemetry_record:{sample.record_id}" for sample in samples])


class UnavailableModel:
    qualification_status = ProviderStatus(provider_id="uninstalled", status="unavailable",
                                          reasons=["qualified_checkpoint_unavailable"])
    inference_status = ProviderStatus(provider_id="uninstalled", status="unavailable",
                                      reasons=["frozen_inference_unavailable"])

    async def qualify(self, checkpoint_sha256):
        # No AI imports, mutable best.json pointers or self-asserted JSON qualification.
        return Qualification(qualified=False, checkpoint_sha256=checkpoint_sha256,
                             reasons=["qualified_checkpoint_unavailable"])

    async def infer(self, observation, qualification):
        raise RuntimeError("frozen_inference_unavailable")


class UnavailableSafety:
    status = ProviderStatus(provider_id="uninstalled", status="uncalibrated",
                            reasons=["calibrated_safety_unavailable"])

    async def assess(self, observation, proposal):
        return SafetyAssessment(admissible=False, model_version="unavailable",
                                reasons=["calibrated_safety_unavailable"])


class UnavailableExecutor:
    status = ProviderStatus(provider_id="uninstalled", status="unavailable",
                            reasons=["autonomous_executor_unavailable"])

    async def accept(self, db, authorization):
        raise RuntimeError("autonomous_executor_unavailable")

    async def verify(self, reference):
        return Verification(execution_id=reference.execution_id, status="uncertain",
                            reasons=["autonomous_executor_unavailable"])


@dataclass(frozen=True)
class Providers:
    observer: Observer
    model: ModelProvider
    safety: SafetyProvider
    executor: DurableExecutor
    recovery: RecoveryProvider

    def statuses(self) -> ProviderStatuses:
        return ProviderStatuses(observer=self.observer.status, qualification=self.model.qualification_status,
            inference=self.model.inference_status, safety=self.safety.status, executor=self.executor.status)


def installed_providers(sessions, redis) -> Providers:
    """Fresh fail-closed provider composition (workers construct this once at startup)."""
    from app.modules.autonomy.live_settings import LiveSettings

    observer, model = TelemetryObserver(sessions), UnavailableModel()
    if LiveSettings.configured():
        from app.modules.autonomy.live_observer import LiveObserver
        from app.modules.autonomy.model_provider import FrozenModelProvider
        from app.modules.autonomy.registry import LiveRegistry

        registry = LiveRegistry.from_environment()
        observer, model = LiveObserver(registry), FrozenModelProvider(registry, redis)
    safety, executor, recovery = UnavailableSafety(), UnavailableExecutor(), UnavailableRecovery()
    from app.modules.autonomy.execution_settings import configured
    if configured():
        from app.modules.autonomy.execution_client import installed_execution_clients
        safety, executor, recovery = installed_execution_clients(sessions, redis)
    return Providers(observer, model, safety, executor, recovery)


def stop_recovery(sessions) -> RecoveryProvider:
    """STOP's cancellation path: exact persisted journal identity, never provider construction.

    Marks only the owned autonomous journal row ``cancel_requested`` (the receiver compensates
    under its own lock); it needs no installation, calibration, health key or Intent service.
    """
    from app.modules.autonomy.execution_settings import configured

    if not configured():
        return UnavailableRecovery()
    from app.modules.autonomy.execution_client import JournalRecovery

    return JournalRecovery(sessions)


# ── Process-level provider cache (API requests; ADR-028 fix 1) ─────────────────
# Building providers verifies protected installation evidence (seconds of file I/O and
# hashing). Requests reuse one composition per (sessions, redis, configuration identity);
# the identity is recomputed with cheap stat() calls so a changed configuration is
# rebuilt, and a failed (blocked) composition is retried after a short interval.
_BLOCKED_RETRY_SECONDS = 30.0
_CACHE_LIMIT = 8
_CACHE: dict[tuple[int, int], tuple[object, object, tuple, float, Providers, bool]] = {}
_CACHE_LOCK = threading.Lock()


def _stat_identity(path):
    try:
        info = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def provider_identity() -> tuple:
    from app.core.config import get_settings
    from app.modules.autonomy.execution_settings import CONFIG_HASH, CONFIG_PATH
    from app.modules.autonomy.health_secret import LEGACY_HMAC_ENV, PUBLIC_KEY_ENV
    from app.modules.autonomy.live_settings import CONFIG_KEYS

    names = (*CONFIG_KEYS, CONFIG_PATH, CONFIG_HASH, PUBLIC_KEY_ENV, LEGACY_HMAC_ENV)
    values = tuple(os.environ.get(name) for name in names)
    files = tuple(_stat_identity(os.environ.get(name)) for name in (CONFIG_PATH, PUBLIC_KEY_ENV, CONFIG_KEYS[0]))
    return getattr(get_settings(), "EXECUTION_MODE", None), values, files


def cached_providers(sessions, redis) -> Providers | None:
    """Peek at the cache without constructing anything (safe on the event loop)."""
    identity = provider_identity()
    entry = _CACHE.get((id(sessions), id(redis)))
    if entry is None:
        return None
    cached_sessions, cached_redis, cached_identity, created, providers, blocked = entry
    if cached_sessions is not sessions or cached_redis is not redis or cached_identity != identity:
        return None
    if blocked and time.monotonic() - created > _BLOCKED_RETRY_SECONDS:
        return None
    return providers


def shared_providers(sessions, redis) -> Providers:
    """Cached composition; call from a worker thread (``asyncio.to_thread``) on a miss."""
    cached = cached_providers(sessions, redis)
    if cached is not None:
        return cached
    with _CACHE_LOCK:
        cached = cached_providers(sessions, redis)
        if cached is not None:
            return cached
        identity = provider_identity()
        providers = installed_providers(sessions, redis)
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.pop(min(_CACHE, key=lambda key: _CACHE[key][3]))
        _CACHE[(id(sessions), id(redis))] = (sessions, redis, identity, time.monotonic(), providers,
                                             bool(getattr(providers.executor, "blocked", False)))
        return providers


def clear_provider_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
