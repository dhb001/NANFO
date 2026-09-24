"""Read-only Intent answers for other modules (ADR-028 §1.2).

Owner-module query boundary: other modules never read Intent tables directly. Every
function here is read-only (no writes, no locks) and uses indexed predicates on
``intents.network_id`` / ``intents.status``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.intent.models import Intent

#: Statuses that are safe from summary status alone (Network.md §3.2).
SAFE_TERMINAL_STATUSES = frozenset({
    "rejected", "cancelled", "compensated", "execution_cancelled", "execution_compensated",
})
#: Statuses that are safe only with exact, owner-verified restoration evidence.
RESTORATION_STATUSES = frozenset({"execution_failed", "execution_completed"})
_PAGE = 200
_HEX = frozenset("0123456789abcdef")


def verified_restoration(*, status: str, provenance: object) -> bool:
    """Whether a finished lab execution provably left no applied change behind.

    A successful applied policy is not restoration. A rollback belongs to the exact
    execution projected by Intent after its worker matched the fenced receipt;
    a separate restore execution proves only its own verified restore plan.
    """
    from app.modules.intent.lab import LabPlan, digest, verified_completion, verified_rollback

    if not isinstance(provenance, dict):
        return False
    if (provenance.get("executor") != "manual_lab_v1" or provenance.get("blocks_lab") is not False
            or provenance.get("uncertain") is not False or provenance.get("status") != status):
        return False
    try:
        for key in ("execution_id", "run_id"):
            uuid.UUID(provenance[key])
        for key in ("plan_hash", "binding_digest"):
            value = provenance[key]
            if not isinstance(value, str) or len(value) != 64 or not set(value) <= _HEX:
                return False
        approved = datetime.fromisoformat(provenance["approved_at"])
        completed = datetime.fromisoformat(provenance["completed_at"])
        if approved.tzinfo is None or completed.tzinfo is None or not approved <= completed <= datetime.now(UTC):
            return False
        plan = LabPlan.model_validate(provenance["approved_plan"])
        if digest(plan.model_dump(mode="json")) != provenance["plan_hash"]:
            return False
    except (KeyError, TypeError, ValueError, AttributeError, ValidationError):
        return False
    if status == "execution_failed" and provenance.get("phase") in {"failed", "cancelled"}:
        return verified_rollback(provenance.get("rollback"))
    if status == "execution_completed" and provenance.get("phase") == "completed" and plan.operation == "restore":
        verification = provenance.get("verification")
        if not isinstance(verification, dict) or not verified_completion(verification):
            return False
        probe = verification["probe"]
        return probe.get("source_host") == plan.source_host and probe.get("destination_host") == plan.destination_host
    return False


async def has_blocking_work(db: AsyncSession, *, network_id: uuid.UUID) -> bool:
    """Whether any intent of ``network_id`` could still have (or apply) network effects."""
    unsafe = await db.scalar(select(Intent.intent_id).where(
        Intent.network_id == network_id,
        Intent.status.not_in(sorted(SAFE_TERMINAL_STATUSES | RESTORATION_STATUSES)),
    ).limit(1))
    if unsafe is not None:
        return True
    after: uuid.UUID | None = None
    while True:
        query = select(Intent.intent_id, Intent.status, Intent.execution_provenance).where(
            Intent.network_id == network_id, Intent.status.in_(sorted(RESTORATION_STATUSES)),
        )
        if after is not None:
            query = query.where(Intent.intent_id > after)
        rows = (await db.execute(query.order_by(Intent.intent_id).limit(_PAGE))).all()
        if any(not verified_restoration(status=row.status, provenance=row.execution_provenance) for row in rows):
            return True
        if len(rows) < _PAGE:
            return False
        after = rows[-1].intent_id
