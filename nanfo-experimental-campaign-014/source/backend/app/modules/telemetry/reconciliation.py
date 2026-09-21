"""Bounded cross-owner reconciliation through public service contracts only."""

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.modules.telemetry.archive_models import TelemetryReconciliation
from app.modules.telemetry.pin_models import TelemetryReferenceCoverage
from app.modules.telemetry.pins import EvidenceOwnerScope, ProspectiveCoverageContract, TelemetryEvidenceService
from app.modules.telemetry.references import OwnerReferencePage, wired_owners


def owner_contracts():
    from app.modules.alert.measured import telemetry_reference_page as alert
    from app.modules.autonomy.service import telemetry_reference_page as autonomy
    from app.modules.intent.service import telemetry_reference_page as intent
    from app.modules.report.service import telemetry_reference_page as report
    from app.modules.simulation.modeled import telemetry_reference_page as simulation

    return dict(alert=alert, autonomy=autonomy, intent=intent, report=report, simulation=simulation)


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
            for item in page.items:
                progress.scanned += 1
                if item.unknown:
                    progress.unknown += 1
                for ref in item.references:
                    try:
                        await service.pin(ref)
                    except ValueError:
                        # A historical missing row is not a proof of absence. Preserve
                        # all pre-enrollment telemetry and record incomplete history.
                        progress.unknown += 1
            progress.cursor = page.next_cursor
            progress.complete = page.next_cursor is None
            await self.db.flush()
            if progress.complete:
                # Explicit reconciler can replace0024 revoked prospective claims.
                await self.db.execute(update(TelemetryReferenceCoverage).where(
                    TelemetryReferenceCoverage.workspace_id == workspace_id,
                    TelemetryReferenceCoverage.owner == owner,
                    TelemetryReferenceCoverage.revoked_at.is_not(None),
                ).values(revoked_at=None, registered_at=func.clock_timestamp()))
                await service.register_prospective(ProspectiveCoverageContract(
                    version=1, contract="pin-before-reference/v1"))
        return dict(owner=owner, complete=progress.complete, cursor=progress.cursor,
                    scanned=progress.scanned, unknown=progress.unknown,
                    historical_coverage="unknown_retained" if progress.unknown else "enumerated_retained")
