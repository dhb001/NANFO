"""Short transactions, per-network fenced leases and bounded read history."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.autonomy.models import (
    AutonomyControl,
    AutonomyDecision,
    ConfigurationRevision,
    TimedOverride,
)
from app.modules.autonomy.schemas import OperationalSettings


class AutonomyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, network_id, *, lock=False):
        query = select(AutonomyControl).where(AutonomyControl.network_id == network_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return (await self.db.execute(query)).scalar_one_or_none()

    async def ensure(self, network_id, workspace_id):
        await self.db.execute(insert(AutonomyControl).values(
            network_id=network_id, workspace_id=workspace_id,
        ).on_conflict_do_nothing(index_elements=[AutonomyControl.network_id]))
        return await self.get(network_id, lock=True)

    async def history(self, network_id, limit=20):
        result = await self.db.execute(select(AutonomyDecision).where(
            AutonomyDecision.network_id == network_id,
        ).order_by(AutonomyDecision.created_at.desc(), AutonomyDecision.decision_id.desc()).limit(min(100, max(1, limit))))
        return list(result.scalars())

    def record(self, control, *, status, reasons, actor_id=None):
        now = datetime.now(UTC)
        decision = AutonomyDecision(
            decision_id=uuid.uuid4(), network_id=control.network_id, workspace_id=control.workspace_id,
            actor_id=actor_id or control.approved_by_user_id or "unassigned", mode=control.mode,
            control_revision=control.revision, checkpoint_sha256=control.checkpoint_sha256,
            status=status, reasons=reasons, evidence=[], created_at=now, updated_at=now,
        )
        self.db.add(decision)
        return decision

    async def claim(self, *, lease_seconds=30, interval_seconds=10):
        result = await self.db.execute(select(AutonomyControl).where(
            or_(AutonomyControl.approved_by_user_id.is_not(None), AutonomyControl.active_execution_id.is_not(None)),
            or_(AutonomyControl.emergency_stopped.is_(False), AutonomyControl.active_execution_id.is_not(None)),
            AutonomyControl.next_cycle_at <= func.now(),
            or_(AutonomyControl.lease_expires_at.is_(None), AutonomyControl.lease_expires_at <= func.now()),
        ).order_by(AutonomyControl.next_cycle_at, AutonomyControl.network_id).with_for_update(skip_locked=True).limit(1))
        control = result.scalar_one_or_none()
        if control is None:
            await self.db.commit()
            return None
        # Expired read/inference cycles cannot later overwrite the successor's evidence.
        abandoned = await self.db.execute(select(AutonomyDecision).where(
            AutonomyDecision.network_id == control.network_id, AutonomyDecision.status == "observing",
        ))
        for decision in abandoned.scalars():
            decision.status, decision.reasons = "blocked", ["cycle_lease_expired"]
            decision.updated_at = datetime.now(UTC)
        now = (await self.db.execute(select(func.clock_timestamp()))).scalar_one()
        control.claim_token = uuid.uuid4()
        control.lease_expires_at = now + timedelta(seconds=lease_seconds)
        settings = await self.operational(control.network_id)
        control.next_cycle_at = now + timedelta(seconds=settings.decision_interval_seconds)
        decision = self.record(control, status="observing", reasons=[])
        await self.db.commit()
        return control, decision

    async def owned(self, network_id, token):
        control = await self.get(network_id, lock=True)
        now = (await self.db.execute(select(func.clock_timestamp()))).scalar_one()
        if control is None or control.claim_token != token or control.lease_expires_at is None or control.lease_expires_at <= now:
            return None
        return control

    async def decision(self, decision_id):
        return (await self.db.execute(select(AutonomyDecision).where(
            AutonomyDecision.decision_id == decision_id,
        ).execution_options(populate_existing=True))).scalar_one()

    async def invalidate_observing(self, network_id, reason):
        result = await self.db.execute(select(AutonomyDecision).where(
            AutonomyDecision.network_id == network_id, AutonomyDecision.status == "observing",
        ))
        for row in result.scalars():
            row.status, row.reasons, row.updated_at = "blocked", [reason], datetime.now(UTC)

    async def configurations(self, network_id, limit=100):
        return list((await self.db.scalars(select(ConfigurationRevision).where(
            ConfigurationRevision.network_id == network_id,
        ).order_by(ConfigurationRevision.revision.desc()).limit(limit))).all())

    async def operational(self, network_id):
        rows = await self.configurations(network_id, 1)
        return OperationalSettings.model_validate(rows[0].operational) if rows else OperationalSettings()

    async def unresolved_override(self, network_id):
        return await self.db.scalar(select(TimedOverride).where(
            TimedOverride.network_id == network_id, TimedOverride.status.in_(["holding", "restoring"])))

    async def override(self, override_id, *, lock=False):
        query = select(TimedOverride).where(TimedOverride.override_id == override_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.db.scalar(query)

    async def overrides(self, network_id):
        return list((await self.db.scalars(select(TimedOverride).where(
            TimedOverride.network_id == network_id,
        ).order_by(TimedOverride.created_at.desc(), TimedOverride.override_id.desc()).limit(100))).all())

    async def claim_override(self, lease_seconds=30):
        row = await self.db.scalar(select(TimedOverride).where(
            TimedOverride.status.in_(["holding", "restoring", "restored"]), TimedOverride.next_check_at <= func.now(),
            or_(TimedOverride.lease_expires_at.is_(None), TimedOverride.lease_expires_at <= func.now()),
        ).order_by(TimedOverride.next_check_at, TimedOverride.override_id).with_for_update(skip_locked=True).limit(1))
        if row:
            now = (await self.db.execute(select(func.clock_timestamp()))).scalar_one()
            row.claim_token = uuid.uuid4()
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        await self.db.commit()
        return row

    async def owned_override(self, override_id, token):
        row = await self.override(override_id, lock=True)
        now = (await self.db.execute(select(func.clock_timestamp()))).scalar_one()
        if row is None or row.claim_token != token or row.lease_expires_at is None or row.lease_expires_at <= now:
            return None
        return row
