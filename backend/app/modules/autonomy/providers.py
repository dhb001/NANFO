"""Installed providers fail closed. Test providers are injected, never auto-installed."""

from __future__ import annotations

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
from app.modules.intent.service import IntentExecutionService
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


class CancellationProvider(Protocol):
    async def cancel(self, *, network_id: uuid.UUID, workspace_id: uuid.UUID,
                     intent_id: uuid.UUID, execution_id: uuid.UUID, actor_id: str,
                     permissions: list[str]) -> Verification: ...


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


class IntentCancellation:
    def __init__(self, sessions, redis):
        self.sessions, self.redis = sessions, redis

    async def cancel(self, *, network_id, workspace_id, intent_id, execution_id, actor_id, permissions):
        async with self.sessions() as db:
            service = IntentExecutionService(db=db, redis=self.redis)
            detail = await service.get_intent_detail(workspace_id=workspace_id, intent_id=intent_id, user_id=actor_id)
            provenance = detail.get("execution_provenance", {})
            if (str(detail.get("network_id")) != str(network_id)
                    or str(provenance.get("execution_id")) != str(execution_id)):
                return Verification(execution_id=execution_id, status="uncertain",
                                    reasons=["owned_execution_identity_mismatch"])
            result = await service.execute_intent(
                workspace_id=workspace_id, intent_id=intent_id, requested_by_user_id=actor_id,
                requested_permissions=permissions, correlation_id=str(uuid.uuid4()),
                idempotency_key=None, cancel=True,
            )
        provenance = result.get("execution_provenance", {})
        if str(provenance.get("execution_id")) != str(execution_id):
            return Verification(execution_id=execution_id, status="uncertain",
                                reasons=["owned_execution_identity_mismatch"])
        # Intent's durable worker alone asserts release after verified compensation
        # or cancellation before dispatch possibility. Enqueue is not cancellation.
        released = (provenance.get("phase") == "cancelled"
                    and provenance.get("cancel_requested") is True
                    and provenance.get("blocks_lab") is False)
        return Verification(execution_id=execution_id, status="cancelled" if released else "pending",
                            safe_to_release=released,
                            evidence=[f"intent:{intent_id}:execution:{execution_id}"],
                            reasons=[] if released else ["awaiting_verified_cancellation"])


@dataclass(frozen=True)
class Providers:
    observer: Observer
    model: ModelProvider
    safety: SafetyProvider
    executor: DurableExecutor
    cancellation: CancellationProvider
    recovery: RecoveryProvider

    def statuses(self) -> ProviderStatuses:
        return ProviderStatuses(observer=self.observer.status, qualification=self.model.qualification_status,
            inference=self.model.inference_status, safety=self.safety.status, executor=self.executor.status)


def installed_providers(sessions, redis) -> Providers:
    return Providers(TelemetryObserver(sessions), UnavailableModel(), UnavailableSafety(),
                     UnavailableExecutor(), IntentCancellation(sessions, redis), UnavailableRecovery())
