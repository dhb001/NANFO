"""Public transactional reference contract; owner extractors supply identities.

SQLAlchemy's synchronous flush hook runs in AsyncSession's greenlet, on the same
transaction. Owner services register their own models/extractors; Telemetry never
imports or queries owner tables. Bulk SQL reference writes are not supported.
"""

import hashlib
import json
import uuid
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.modules.telemetry.pins import EvidenceOwnerScope, EvidenceReference, TelemetryEvidenceService


class OwnerReferenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str
    references: list[EvidenceReference] = Field(default_factory=list, max_length=1000)
    unknown: str | None = None


class OwnerReferencePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[OwnerReferenceItem] = Field(max_length=100)
    next_cursor: str | None


def reference_ids(value):
    """Recognized persisted evidence locators, not arbitrary UUID guessing."""
    if len(json.dumps(value, default=str)) > 2 * 1024 * 1024:
        raise ValueError("reference payload exceeds reconciliation bound")
    found = set()

    def walk(item, depth=0):
        if depth > 30:
            raise ValueError("reference nesting exceeds bound")
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {"record_id", "source_record_id", "telemetry_record_id"}:
                    found.add(uuid.UUID(str(child)))
                elif key in {"record_ids", "telemetry_record_ids", "source_record_ids"}:
                    if not isinstance(child, list):
                        raise ValueError("invalid telemetry reference list")
                    found.update(uuid.UUID(str(identity)) for identity in child)
                elif key in {"safety_evidence_json", "observation_json"}:
                    if not isinstance(child, str):
                        raise ValueError("invalid serialized evidence")
                    walk(json.loads(child), depth + 1)
                else:
                    walk(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
        elif isinstance(item, str) and item.startswith("telemetry_record:"):
            found.add(uuid.UUID(item.removeprefix("telemetry_record:")))
    walk(value)
    if len(found) > 1000:
        raise ValueError("too many telemetry references")
    return sorted(found)


def evidence_item(*, identity, network_id, fields):
    refs = []
    for field, value in fields.items():
        ids = reference_ids(value)
        if not ids:
            continue
        if network_id is None:
            raise ValueError("telemetry evidence has no network scope")
        # Immutable identity of this evidence version, not a mutable latest pointer.
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                            default=str, allow_nan=False).encode()).hexdigest()
        reference_id = uuid.uuid5(uuid.NAMESPACE_URL, f"nanfo:{identity}:{field}:{digest}")
        refs.extend(EvidenceReference(network_id=network_id, reference_id=reference_id,
                                      record_id=record_id) for record_id in ids)
    return OwnerReferenceItem(identity=str(identity), references=refs)


def historical_item(extractor, row):
    try:
        item = extractor(row)
        if not item.references and not item.unknown:
            item.unknown = "legacy_no_enumerable_telemetry_identity"
        return item
    except (ValueError, TypeError, KeyError, AttributeError):
        return OwnerReferenceItem(identity="legacy", unknown="legacy_reference_unenumerable")


def page_position(after, *, stages, limit, text_key=False):
    if not 1 <= limit <= 100:
        raise ValueError("owner page limit must be 1..100")
    position = json.loads(after) if after else [0, None]
    if not isinstance(position, list) or len(position) != 2 or type(position[0]) is not int or not 0 <= position[0] < stages:
        raise ValueError("invalid owner continuation")
    if position[1] is not None and (not isinstance(position[1], str) or len(position[1]) > 128):
        raise ValueError("invalid owner continuation key")
    return position[0], (position[1] if text_key else uuid.UUID(position[1])) if position[1] else None


def reference_page(rows, *, extractor, key, limit, stage=0, stages=1):
    more = len(rows) > limit
    cursor = (json.dumps([stage, str(key(rows[limit - 1]))]) if more
              else json.dumps([stage + 1, None]) if stage + 1 < stages else None)
    return OwnerReferencePage(items=[historical_item(extractor, row) for row in rows[:limit]], next_cursor=cursor)


_GUARDS: dict[type, tuple[str, Callable, Callable, tuple[str, ...]]] = {}
_DIRECT_OWNERS: set[str] = set()


def install_direct_owner(owner):
    """Owner with an explicit async pin call before its durable write."""
    _DIRECT_OWNERS.add(owner)


def install_owner_guard(model, *, owner, extractor, workspace=lambda row: row.workspace_id, fields=()):
    _GUARDS[model] = (owner, extractor, workspace, fields)


def wired_owners():
    return {owner for owner, _, _, _ in _GUARDS.values()} | _DIRECT_OWNERS


@event.listens_for(Session, "before_flush")
def _pin_before_flush(session, flush_context, instances):
    for row in list(session.new) + list(session.dirty):
        guard = _GUARDS.get(type(row))
        if guard is None:
            continue
        owner, extractor, workspace, fields = guard
        if row not in session.new and fields and not any(inspect(row).attrs[name].history.has_changes() for name in fields):
            continue
        item = extractor(row)
        if item.unknown:
            raise ValueError(item.unknown)
        if item.references:
            scope = EvidenceOwnerScope(owner=owner, workspace_id=workspace(row))
            for ref in sorted(item.references, key=lambda ref: (ref.record_id, ref.reference_id)):
                TelemetryEvidenceService.pin_in_transaction(session.connection(), scope=scope, reference=ref)
