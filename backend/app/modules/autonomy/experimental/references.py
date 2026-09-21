"""Autonomy-owned experimental evidence scopes and transactional pin wiring.

Only Telemetry's recognized locator grammar is used. Scope comes from the owning
immutable run policy, never nested evidence. No controller lifecycle changes.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import object_session

from app.modules.telemetry.references import evidence_item, install_owner_guard, reference_ids

from .schemas import contract_digest


def fields_for(row):
    from .models import LabAction, LabReceipt, LabRun

    if isinstance(row, LabRun):
        return {"policy": row.policy}
    if isinstance(row, LabAction):
        return {name: getattr(row, name) for name in ("frame", "inference", "simulation", "command", "prepared")}
    if isinstance(row, LabReceipt):
        return {"payload": row.payload}
    raise ValueError("experimental_reference_model_invalid")


def policy_scope(policy, digest):
    if not isinstance(policy, dict) or contract_digest(policy) != digest:
        raise ValueError("experimental_reference_policy_invalid")
    return UUID(policy["workspace_id"]), UUID(policy["network_id"])


def owning_scope(row):
    """Flush-safe owning-module reads; new run+child in one flush is supported."""
    from .models import LabRun

    if isinstance(row, LabRun):
        return policy_scope(row.policy, row.policy_sha256)
    session = object_session(row)
    if session is None:
        raise ValueError("experimental_reference_owner_session_required")
    pending = next((r for r in session.new if isinstance(r, LabRun) and r.run_id == row.run_id), None)
    if pending is not None:
        return policy_scope(pending.policy, pending.policy_sha256)
    # Read committed policy bytes rather than caller-supplied/dirty identity-map state.
    result = session.connection().execute(select(LabRun.policy, LabRun.policy_sha256).where(
        LabRun.run_id == row.run_id)).one_or_none()
    if result is None:
        raise ValueError("experimental_reference_owner_missing")
    return policy_scope(*result)


def experimental_telemetry_references(row, *, scope=None):
    from .models import LabAction, LabReceipt

    key = row.request_id if isinstance(row, LabAction) else row.receipt_id if isinstance(row, LabReceipt) else row.run_id
    fields = fields_for(row)
    # Avoid database access entirely for non-reference records, including control receipts.
    has_references = any(reference_ids(value) for value in fields.values())
    network = (scope or owning_scope(row))[1] if has_references else None
    return evidence_item(identity=f"{row.__tablename__}:{key}", network_id=network, fields=fields)


def install_experimental_guards():
    from .models import LabAction, LabReceipt, LabRun

    for model, fields in (
        (LabRun, ("policy", "policy_sha256", "run_id")),
        (LabAction, ("run_id", "frame", "inference", "simulation", "command", "prepared")),
        (LabReceipt, ("run_id", "payload")),
    ):
        install_owner_guard(model, owner="autonomy", extractor=experimental_telemetry_references,
                            workspace=lambda row: owning_scope(row)[0], fields=fields)


async def reference_rows(db, model, key, *, workspace_id, last, limit):
    """Same-owner join for authoritative scope; rows carry no trusted nested scope."""
    from .models import LabRun

    query = select(model, LabRun.policy, LabRun.policy_sha256)
    if model is not LabRun:
        query = query.join(LabRun, model.run_id == LabRun.run_id)
    query = query.where(LabRun.policy["workspace_id"].astext == str(workspace_id))
    if last:
        query = query.where(key > UUID(last))
    return (await db.execute(query.order_by(key).limit(limit + 1))).all()


def historical_reference(row):
    item, policy, digest = row
    return experimental_telemetry_references(item, scope=policy_scope(policy, digest))
