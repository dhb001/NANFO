"""Bounded cross-owner reconciliation through public service contracts only.

Coverage continuity (ADR-028). Completing a scan re-activates revoked coverage.
The coverage start (``registered_at``) is reset to "now" for revocations whose
cause is unknown (conservative: the pin-before-reference guarantee may not have
held during the gap), but it is *preserved* for an explicit enumeration
invalidation (``invalidate_owner_enumeration``): that path only withdraws the
historical-enumeration claim while owner writes keep pinning, and the fresh full
scan it forces re-pins every enumerable reference created during the gap.
The two are distinguished by the exact marker ``started_at == revoked_at`` that
only ``invalidate_owner_enumeration`` writes (one timestamp for both columns).
"""

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.modules.telemetry.archive_models import TelemetryReconciliation
from app.modules.telemetry.pin_models import TelemetryReferenceCoverage
from app.modules.telemetry.pin_repository import TelemetryPinRepository
from app.modules.telemetry.pins import (
    REQUIRED_EVIDENCE_OWNERS,
    EvidenceOwnerScope,
    ProspectiveCoverageContract,
    TelemetryEvidenceService,
)
from app.modules.telemetry.references import OwnerReferencePage, wired_owners


def owner_contracts():
    from app.modules.alert.measured import telemetry_reference_page as alert
    from app.modules.autonomy.service import telemetry_reference_page as autonomy
    from app.modules.intent.service import telemetry_reference_page as intent
    from app.modules.report.service import telemetry_reference_page as report
    from app.modules.simulation.modeled import telemetry_reference_page as simulation

    return dict(alert=alert, autonomy=autonomy, intent=intent, report=report, simulation=simulation)


async def invalidate_owner_enumeration(db, *, workspace_id, owner) -> None:
    """Force a fresh historical scan for ``owner`` without breaking coverage continuity.

    Use when an owner gains new reference-bearing storage whose history was never
    enumerated (the 0029 situation). Owner writes must keep pinning meanwhile.
    Caller commits.
    """
    if owner not in REQUIRED_EVIDENCE_OWNERS:
        raise ValueError("known evidence owner required")
    marker = await db.scalar(select(func.clock_timestamp()))
    await db.execute(update(TelemetryReferenceCoverage).where(
        TelemetryReferenceCoverage.workspace_id == workspace_id,
        TelemetryReferenceCoverage.owner == owner,
        TelemetryReferenceCoverage.revoked_at.is_(None),
    ).values(revoked_at=marker))
    await db.execute(update(TelemetryReconciliation).where(
        TelemetryReconciliation.workspace_id == workspace_id, TelemetryReconciliation.owner == owner,
    ).values(cursor=None, complete=False, scanned=0, unknown=0, started_at=marker))


class TelemetryReconciliationService:
    def __init__(self, db):
        self.db = db

    async def step(self, *, workspace_id, owner, limit=100):
        contracts = owner_contracts()
        if owner not in contracts or owner not in wired_owners() or not 1 <= limit <= 100:
            raise ValueError("wired owner and bounded reconciliation required")
        await self.db.execute(insert(TelemetryReconciliation).values(
            workspace_id=workspace_id, owner=owner, complete=False, scanned=0, unknown=0
        ).on_conflict_do_nothing())
        progress = (await self.db.scalars(select(TelemetryReconciliation).where(
            TelemetryReconciliation.workspace_id == workspace_id, TelemetryReconciliation.owner == owner
        ).with_for_update().execution_options(populate_existing=True))).one()
        if not progress.complete:
            page = OwnerReferencePage.model_validate(await contracts[owner](self.db,
                workspace_id=workspace_id, after=progress.cursor, limit=limit))
            service = TelemetryEvidenceService(self.db, scope=EvidenceOwnerScope(owner=owner, workspace_id=workspace_id))
            pins = TelemetryPinRepository(self.db)
            for item in page.items:
                progress.scanned += 1
                if item.unknown:
                    progress.unknown += 1
                for ref in item.references:
                    try:
                        await service.pin(ref)
                    except ValueError:
                        # A historical missing row is not a proof of absence. Preserve
                        # all pre-enrollment telemetry and record incomplete history,
                        # unless the UUID was never a telemetry identity at all (an
                        # unrelated id under a generic ``record_id`` key).
                        if await pins.known_identity(ref.record_id):
                            progress.unknown += 1
            progress.cursor = page.next_cursor
            progress.complete = page.next_cursor is None
            await self.db.flush()
            if progress.complete:
                await self._reactivate(workspace_id=workspace_id, owner=owner, started_at=progress.started_at)
                await service.register_prospective(ProspectiveCoverageContract(
                    version=1, contract="pin-before-reference/v1"))
        return dict(owner=owner, complete=progress.complete, cursor=progress.cursor,
                    scanned=progress.scanned, unknown=progress.unknown,
                    historical_coverage="unknown_retained" if progress.unknown else "enumerated_retained")

    async def _reactivate(self, *, workspace_id, owner, started_at) -> None:
        # Explicit reconciler can replace0024 revoked prospective claims.
        await self.db.execute(update(TelemetryReferenceCoverage).where(
            TelemetryReferenceCoverage.workspace_id == workspace_id,
            TelemetryReferenceCoverage.owner == owner,
            TelemetryReferenceCoverage.revoked_at.is_not(None),
        ).values(
            # SET expressions see the pre-update row, so this compares the old revoked_at.
            registered_at=case(
                (TelemetryReferenceCoverage.revoked_at == started_at, TelemetryReferenceCoverage.registered_at),
                else_=func.clock_timestamp(),
            ),
            revoked_at=None,
        ))
