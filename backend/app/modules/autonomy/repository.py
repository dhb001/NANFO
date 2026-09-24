"""Short transactions, per-network fenced leases and bounded read history."""

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import case, event, func, inspect, literal_column, or_, select, text, type_coerce, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.autonomy.confidence import explainability_reasons
from app.modules.autonomy.models import (
    AutonomyControl,
    AutonomyDecision,
    ConfigurationRevision,
    TimedOverride,
)
from app.modules.autonomy.schemas import COALESCED_CYCLES_PREFIX, OperationalSettings, Proposal, coalesced_cycles

#: Terminal outcomes that carry no provider output and may be coalesced/retained (fix 6).
COALESCIBLE_STATUSES = frozenset({"observed", "blocked"})
#: STOP never queues behind another transaction for longer than this (ADR-028 fix 1).
STOP_LOCK_TIMEOUT_MS = 1000

_SUMMARY_COLUMNS = (
    AutonomyDecision.decision_id, AutonomyDecision.network_id, AutonomyDecision.workspace_id,
    AutonomyDecision.actor_id, AutonomyDecision.mode, AutonomyDecision.control_revision, AutonomyDecision.status,
    AutonomyDecision.reasons, AutonomyDecision.checkpoint_sha256, AutonomyDecision.proposal,
    AutonomyDecision.evidence, AutonomyDecision.execution_id, AutonomyDecision.verification,
    AutonomyDecision.created_at, AutonomyDecision.updated_at,
)
# Server-side list projections: observation without samples (plus their count) and safety
# without the bound provider inputs; authorization is never selected. NULL stays NULL.
def _jsonb_op(left, operator, right):
    return left.op(operator, return_type=JSONB)(right)


_OBSERVATION_SUMMARY = type_coerce(_jsonb_op(
    _jsonb_op(AutonomyDecision.observation, "-", literal_column("'samples'")), "||",
    func.jsonb_build_object(literal_column("'sample_count'"), func.coalesce(func.jsonb_array_length(
        _jsonb_op(AutonomyDecision.observation, "->", literal_column("'samples'"))), 0))), JSONB).label("observation")
_SAFETY_SUMMARY = AutonomyDecision.safety
for _path in ("'{selected_action}'", "'{binding,observation}'", "'{binding,policy}'",
              "'{binding,calibration}'", "'{binding,state}'"):
    _SAFETY_SUMMARY = _jsonb_op(_SAFETY_SUMMARY, "#-", literal_column(_path))
_SAFETY_SUMMARY = type_coerce(_SAFETY_SUMMARY, JSONB).label("safety")


def plain_reasons(reasons):
    return [reason for reason in reasons or () if not str(reason).startswith(COALESCED_CYCLES_PREFIX)]


def bump_coalesced_cycles(row, now):
    """Record one more identical cycle; reasons are not a telemetry-evidence field (no re-pinning)."""
    count = coalesced_cycles(row.reasons)
    row.reasons = [*plain_reasons(row.reasons), f"{COALESCED_CYCLES_PREFIX}{count + 1}"]
    row.updated_at = now


def coalescible(row, *, status=None) -> bool:
    return ((status or row.status) in COALESCIBLE_STATUSES and row.proposal is None and row.safety is None
            and row.execution_id is None and row.authorization is None and row.verification is None)


def _json_absent(column):
    return or_(column.is_(None), column == literal_column("'null'::jsonb"))


def _lock_not_available(exc) -> bool:
    orig = getattr(exc, "orig", None)
    return "55P03" in {getattr(orig, "sqlstate", None), getattr(orig, "pgcode", None),
                       getattr(getattr(orig, "__cause__", None), "sqlstate", None)}


class StopLockTimeout(Exception):
    """The STOP latch could not take the control row within its lock timeout."""


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

    async def latch_stop(self, *, network_id, workspace_id, actor_id, lock_timeout_ms=STOP_LOCK_TIMEOUT_MS):
        """One conditional upsert latching STOP; never waits beyond ``lock_timeout_ms``.

        Provider-independent. The row keeps its own workspace scope (a mismatching scope
        returns None). STOP bumps the revision (fencing older PUTs and in-flight cycles),
        drops the cycle claim and makes an owned execution due for reconciliation now.
        """
        await self.db.execute(text(f"SET LOCAL lock_timeout = '{int(lock_timeout_ms)}ms'"))
        table = AutonomyControl.__table__
        statement = insert(AutonomyControl).values(
            network_id=network_id, workspace_id=workspace_id, mode="monitor", emergency_stopped=True,
            stopped_at=func.now(), stopped_by_user_id=actor_id, revision=1, cancellation_status="none",
            next_cycle_at=func.now(), updated_at=func.now(),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[AutonomyControl.network_id],
            set_={
                "emergency_stopped": True, "stopped_at": func.now(), "stopped_by_user_id": actor_id,
                "revision": table.c.revision + 1, "claim_token": None, "lease_expires_at": None,
                "next_cycle_at": func.now(), "updated_at": func.now(),
                "cancellation_status": case((table.c.active_execution_id.is_not(None), "requested"),
                                            else_=table.c.cancellation_status),
            },
            where=table.c.workspace_id == workspace_id,
        ).returning(
            table.c.network_id, table.c.workspace_id, table.c.mode, table.c.revision, table.c.checkpoint_sha256,
            table.c.approved_by_user_id, table.c.active_execution_id, table.c.active_intent_id,
            table.c.active_decision_id, table.c.cancellation_status,
        )
        try:
            return (await self.db.execute(statement)).one_or_none()
        except DBAPIError as exc:
            if _lock_not_available(exc):
                raise StopLockTimeout from exc
            raise

    async def settle_stop_cancellation(self, *, network_id, execution_id, stop_revision, status,
                                       lock_timeout_ms=STOP_LOCK_TIMEOUT_MS):
        """Conditional post-STOP cancellation outcome; a newer control state always wins."""
        await self.db.execute(text(f"SET LOCAL lock_timeout = '{int(lock_timeout_ms)}ms'"))
        values = {"cancellation_status": status, "updated_at": func.now()}
        if status == "verified":
            values.update(active_execution_id=None, active_intent_id=None, active_decision_id=None)
        try:
            result = await self.db.execute(update(AutonomyControl).where(
                AutonomyControl.network_id == network_id, AutonomyControl.active_execution_id == execution_id,
                AutonomyControl.revision == stop_revision,
            ).values(**values).returning(AutonomyControl.network_id))
        except DBAPIError as exc:
            if _lock_not_available(exc):
                raise StopLockTimeout from exc
            raise
        return result.scalar_one_or_none() is not None

    async def history(self, network_id, limit=20, *, summary=False):
        order = (AutonomyDecision.created_at.desc(), AutonomyDecision.decision_id.desc())
        bounded = min(100, max(1, limit))
        if summary:
            result = await self.db.execute(select(*_SUMMARY_COLUMNS, _OBSERVATION_SUMMARY, _SAFETY_SUMMARY).where(
                AutonomyDecision.network_id == network_id).order_by(*order).limit(bounded))
            return list(result.all())
        result = await self.db.execute(select(AutonomyDecision).where(
            AutonomyDecision.network_id == network_id,
        ).order_by(*order).limit(bounded))
        return list(result.scalars())

    async def previous_decision(self, network_id, decision_id):
        """Latest terminal decision other than the in-flight one, locked against retention."""
        return await self.db.scalar(select(AutonomyDecision).where(
            AutonomyDecision.network_id == network_id, AutonomyDecision.decision_id != decision_id,
            AutonomyDecision.status != "observing",
        ).order_by(AutonomyDecision.created_at.desc(), AutonomyDecision.decision_id.desc())
            .limit(1).with_for_update().execution_options(populate_existing=True))

    async def discard(self, row):
        await self.db.delete(row)

    async def control_network_ids(self):
        return list((await self.db.scalars(select(AutonomyControl.network_id).order_by(AutonomyControl.network_id))).all())

    async def prune_coalescible(self, network_id, *, before, limit=100):
        """Delete coalescible rows last seen before ``before``; release their telemetry pins first."""
        rows = list((await self.db.scalars(select(AutonomyDecision).where(
            AutonomyDecision.network_id == network_id,
            AutonomyDecision.created_at < before, AutonomyDecision.updated_at < before,
            AutonomyDecision.status.in_(sorted(COALESCIBLE_STATUSES)),
            _json_absent(AutonomyDecision.proposal), _json_absent(AutonomyDecision.safety),
            _json_absent(AutonomyDecision.authorization), _json_absent(AutonomyDecision.verification),
            AutonomyDecision.execution_id.is_(None),
        ).order_by(AutonomyDecision.created_at, AutonomyDecision.decision_id)
            .limit(limit).with_for_update(skip_locked=True))).all())
        for row in rows:
            await release_decision_pins(self.db, row)
            await self.db.delete(row)
        await self.db.flush()
        return len(rows)

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


async def release_decision_pins(db, row):
    """Release the deleted decision's own telemetry evidence pins (same transaction)."""
    from app.modules.autonomy.service import autonomy_telemetry_references
    from app.modules.telemetry.pins import EvidenceOwnerScope, TelemetryEvidenceService

    item = autonomy_telemetry_references(row)
    if not item.references:
        return 0
    pins = TelemetryEvidenceService(db, scope=EvidenceOwnerScope(owner="autonomy", workspace_id=row.workspace_id))
    released = 0
    for reference in sorted(item.references, key=lambda ref: (ref.record_id, ref.reference_id)):
        released += bool(await pins.release(reference))
    return released


def require_explainable_proposal(mapper, connection, target):
    """Flush-time constitution guard: no decision persists a proposal lacking evidence + confidence."""
    proposal = target.proposal
    if proposal is None:
        return
    state = inspect(target)
    if state.persistent and not state.attrs.proposal.history.has_changes():
        return  # untouched historical (pre-C17) proposals are never rewritten
    try:
        parsed = Proposal.model_validate(proposal)
    except ValidationError as exc:
        raise ValueError("proposal_contract_invalid") from exc
    if explainability_reasons(parsed):
        raise ValueError("proposal_evidence_and_confidence_required")


event.listen(AutonomyDecision, "before_insert", require_explainable_proposal)
event.listen(AutonomyDecision, "before_update", require_explainable_proposal)
