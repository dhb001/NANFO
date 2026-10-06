"""Owner-service contract. No public router or automatic coverage enrollment."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.telemetry.pin_repository import TelemetryPinRepository

EvidenceOwner = Literal["report", "intent", "alert", "simulation", "autonomy"]
REQUIRED_EVIDENCE_OWNERS = frozenset({"report", "intent", "alert", "simulation", "autonomy"})


class EvidenceOwnerScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    owner: EvidenceOwner
    workspace_id: uuid.UUID


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    network_id: uuid.UUID
    reference_id: uuid.UUID
    record_id: uuid.UUID


class ProspectiveCoverageContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1]
    contract: Literal["pin-before-reference/v1"]


class TelemetryEvidenceService:
    """Trusted composition binds owner and workspace; caller authorizes its references.

    Pin before publishing a reference. Caller commits/rolls back its transaction;
    independent owner transactions must pin first and tolerate conservative orphans.
    """

    def __init__(self, db: AsyncSession, *, scope: EvidenceOwnerScope):
        self._scope = EvidenceOwnerScope.model_validate(scope)
        self._repo = TelemetryPinRepository(db)

    async def register_prospective(self, contract: ProspectiveCoverageContract):
        ProspectiveCoverageContract.model_validate(contract)
        from app.modules.telemetry.references import wired_owners

        if self._scope.owner not in wired_owners() or not await self._repo.reconciled(**self._scope.model_dump()):
            raise ValueError("Owner wiring and completed reconciliation required")
        coverage = await self._repo.register(**self._scope.model_dump())
        if coverage.revoked_at is not None:
            raise ValueError("Revoked coverage requires explicit reconciliation; cannot reactivate")
        return coverage

    @staticmethod
    def pin_in_transaction(connection, *, scope: EvidenceOwnerScope, reference: EvidenceReference,
                           skip_unknown_identity: bool = False) -> bool:
        """Public synchronous contract for an owner's ORM flush transaction.

        Returns ``False`` only when ``skip_unknown_identity`` skipped a UUID that
        was never a telemetry identity.
        """
        scope = EvidenceOwnerScope.model_validate(scope)
        reference = EvidenceReference.model_validate(reference)
        return TelemetryPinRepository.pin_sync(connection, **scope.model_dump(), **reference.model_dump(),
                                               skip_unknown_identity=skip_unknown_identity)

    async def revoke_coverage(self) -> None:
        await self._repo.revoke(**self._scope.model_dump())

    async def pin(self, reference: EvidenceReference):
        reference = EvidenceReference.model_validate(reference)
        pin = await self._repo.pin(**self._scope.model_dump(), **reference.model_dump())
        if pin.released_at is not None:
            raise ValueError("Released evidence reference cannot be reused")
        return pin

    async def event_reference(self, *, event_id, network_id, reference_id):
        record_id = await self._repo.event_record(workspace_id=self._scope.workspace_id,
                                                  network_id=network_id, event_id=event_id)
        if record_id is None:
            raise ValueError("Evidence event unavailable in owner scope")
        return EvidenceReference(network_id=network_id, reference_id=reference_id, record_id=record_id)

    async def release(self, reference: EvidenceReference) -> bool:
        reference = EvidenceReference.model_validate(reference)
        return await self._repo.release(**self._scope.model_dump(), **reference.model_dump())
