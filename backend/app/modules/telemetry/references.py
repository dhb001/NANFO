"""Public transactional reference contract; owner extractors supply identities.

SQLAlchemy's synchronous flush hook runs in AsyncSession's greenlet, on the same
transaction. Owner services register their own models/extractors; Telemetry never
imports or queries owner tables. Bulk SQL reference writes are not supported.

Locator grammar (ADR-028). Only *typed* evidence locators are recognised:

- typed: ``"telemetry_record:<uuid>"`` strings and ``telemetry_record_id(s)`` keys;
- generic evidence keys ``record_id``/``source_record_id`` (and ``*_ids`` lists)
  only when the value is a UUID. Other values under those keys belong to foreign
  identifier grammars (simulation value sources, qualification record names)
  and are ignored instead of failing the owner's write;
- ``safety_evidence_json``/``observation_json`` serialized evidence documents.

Scanning is iterative (no recursion or depth limit) and never raises from
free-form payloads. In the prospective flush path malformed typed locators are
logged with fixed codes and counted; a UUID that is not a telemetry identity at
all is skipped, while archived or foreign-scope telemetry identities still fail
closed (pin-before-reference). Historical enumeration reports scan problems as
``unknown`` so such history stays retained.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.modules.telemetry.diagnostics import FailureCounter
from app.modules.telemetry.pins import EvidenceOwnerScope, EvidenceReference, TelemetryEvidenceService

logger = get_logger(__name__)

LOCATOR_PREFIX = "telemetry_record:"
_TYPED_SINGLE = frozenset({"telemetry_record_id"})
_TYPED_LIST = frozenset({"telemetry_record_ids"})
_GENERIC_SINGLE = frozenset({"record_id", "source_record_id"})
_GENERIC_LIST = frozenset({"record_ids", "source_record_ids"})
_SERIALIZED = frozenset({"safety_evidence_json", "observation_json"})
MAX_SCAN_NODES = 5_000_000
MAX_ITEM_REFERENCES = 100_000
LEGACY_MAX_REFERENCES = 1000

SCAN_UNENUMERABLE = "telemetry_reference_unenumerable"
SCOPE_UNAVAILABLE = "telemetry_evidence_scope_unavailable"

REFERENCE_SCAN_ISSUES = FailureCounter()
_MODE: ContextVar[str] = ContextVar("telemetry_reference_scan_mode", default="prospective")


class OwnerReferenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str
    references: list[EvidenceReference] = Field(default_factory=list, max_length=MAX_ITEM_REFERENCES)
    unknown: str | None = None
    # Record ids found without a network scope (checked by the flush hook).
    _unscoped: tuple[uuid.UUID, ...] = PrivateAttr(default=())


class OwnerReferencePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[OwnerReferenceItem] = Field(max_length=100)
    next_cursor: str | None


@dataclass
class ReferenceScan:
    record_ids: set[uuid.UUID] = field(default_factory=set)
    issues: list[str] = field(default_factory=list)


def _uuid(value) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def scan_references(value, *, strict: bool = False) -> ReferenceScan:
    """Iteratively collect recognised telemetry locators; never raises unless ``strict``."""
    result = ReferenceScan()

    def issue(code: str) -> None:
        if strict:
            raise ValueError(code)
        result.issues.append(code)

    stack = [value]
    visited = 0
    while stack:
        visited += 1
        if visited > MAX_SCAN_NODES:
            issue("reference_scan_truncated")
            break
        item = stack.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if child is None:
                    continue
                if key in _TYPED_SINGLE or key in _GENERIC_SINGLE:
                    identity = _uuid(child)
                    if identity is not None:
                        result.record_ids.add(identity)
                    elif key in _TYPED_SINGLE or strict:
                        issue("reference_locator_malformed")
                    elif isinstance(child, (dict, list)) or (
                            isinstance(child, str) and child.startswith(LOCATOR_PREFIX)):
                        stack.append(child)
                elif key in _TYPED_LIST or key in _GENERIC_LIST:
                    if not isinstance(child, list):
                        if key in _TYPED_LIST or strict:
                            issue("reference_locator_list_invalid")
                        elif isinstance(child, dict):
                            stack.append(child)
                        continue
                    for entry in child:
                        identity = _uuid(entry)
                        if identity is not None:
                            result.record_ids.add(identity)
                        elif key in _TYPED_LIST or strict:
                            issue("reference_locator_malformed")
                        elif isinstance(entry, (dict, list)) or (
                                isinstance(entry, str) and entry.startswith(LOCATOR_PREFIX)):
                            stack.append(entry)
                elif key in _SERIALIZED and isinstance(child, str):
                    try:
                        stack.append(json.loads(child))
                    except (ValueError, RecursionError):
                        issue("serialized_evidence_invalid")
                elif key in _SERIALIZED and strict:
                    issue("serialized_evidence_invalid")
                else:
                    stack.append(child)
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
        elif isinstance(item, str) and item.startswith(LOCATOR_PREFIX):
            identity = _uuid(item.removeprefix(LOCATOR_PREFIX))
            if identity is None:
                issue("reference_locator_malformed")
            else:
                result.record_ids.add(identity)
    return result


def reference_ids(value):
    """Strict legacy contract (owners that deliberately fail closed on malformed locators)."""
    found = scan_references(value, strict=True).record_ids
    if len(found) > LEGACY_MAX_REFERENCES:
        raise ValueError("too many telemetry references")
    return sorted(found)


def _version_digest(value, ids) -> str:
    try:
        # allow_nan=True is byte-identical to the historical encoding for every
        # NaN-free document, and no longer fails documents that contain NaN.
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=True)
    except (RecursionError, ValueError, TypeError):
        data = "nanfo:deep-evidence:" + ",".join(sorted(str(identity) for identity in ids))
    return hashlib.sha256(data.encode()).hexdigest()


def evidence_item(*, identity, network_id, fields):
    historical = _MODE.get() == "historical"
    refs, unscoped, issues = [], [], []
    for name, value in fields.items():
        scan = scan_references(value)
        issues.extend(scan.issues)
        if not scan.record_ids:
            continue
        network = network_id if isinstance(network_id, uuid.UUID) else _uuid(str(network_id)) if network_id else None
        if network is None:
            unscoped.extend(scan.record_ids)
            continue
        # Immutable identity of this evidence version, not a mutable latest pointer.
        digest = _version_digest(value, scan.record_ids)
        reference_id = uuid.uuid5(uuid.NAMESPACE_URL, f"nanfo:{identity}:{name}:{digest}")
        refs.extend(EvidenceReference(network_id=network, reference_id=reference_id, record_id=record_id)
                    for record_id in sorted(scan.record_ids))
    unknown = None
    if historical and issues:
        unknown = SCAN_UNENUMERABLE
    elif historical and unscoped:
        unknown = SCOPE_UNAVAILABLE
    for code in sorted(set(issues)) if not historical else ():
        REFERENCE_SCAN_ISSUES.note(logger, "telemetry_reference_scan_issue", code, identity=str(identity))
    if len(refs) > MAX_ITEM_REFERENCES:
        item = OwnerReferenceItem.model_construct(identity=str(identity), references=refs,
                                                  unknown=unknown or (SCAN_UNENUMERABLE if historical else None))
    else:
        item = OwnerReferenceItem(identity=str(identity), references=refs, unknown=unknown)
    item._unscoped = tuple(sorted(set(unscoped)))
    return item


def historical_item(extractor, row):
    token = _MODE.set("historical")
    try:
        item = extractor(row)
        if not item.references and not item.unknown:
            item.unknown = "legacy_no_enumerable_telemetry_identity"
        return item
    except (ValueError, TypeError, KeyError, AttributeError):
        return OwnerReferenceItem(identity="legacy", unknown="legacy_reference_unenumerable")
    finally:
        _MODE.reset(token)


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


def _extract(extractor, row):
    token = _MODE.set("prospective")
    try:
        return extractor(row)
    finally:
        _MODE.reset(token)


def _reject_known_unscoped(connection, identities, *, reason: str) -> None:
    from app.modules.telemetry.pin_repository import TelemetryPinRepository

    for record_id in identities:
        if TelemetryPinRepository.known_identity_sync(connection, record_id):
            # A real telemetry reference that cannot be scoped cannot be pinned.
            raise ValueError(reason)


@event.listens_for(Session, "before_flush")
def _pin_before_flush(session, flush_context, instances):
    for row in list(session.new) + list(session.dirty):
        guard = _GUARDS.get(type(row))
        if guard is None:
            continue
        owner, extractor, workspace, fields = guard
        if row not in session.new and fields and not any(inspect(row).attrs[name].history.has_changes() for name in fields):
            continue
        item = _extract(extractor, row)
        if item.unknown:
            raise ValueError(item.unknown)  # owner-declared, never a free-form scan result
        unscoped = getattr(item, "_unscoped", ())
        if not item.references and not unscoped:
            continue
        connection = session.connection()
        workspace_id = workspace(row)
        if workspace_id is None:
            _reject_known_unscoped(connection, [ref.record_id for ref in item.references] + list(unscoped),
                                   reason="telemetry evidence has no workspace scope")
            continue
        _reject_known_unscoped(connection, unscoped, reason="telemetry evidence has no network scope")
        scope = EvidenceOwnerScope(owner=owner, workspace_id=workspace_id)
        for ref in sorted(item.references, key=lambda ref: (ref.record_id, ref.reference_id)):
            pinned = TelemetryEvidenceService.pin_in_transaction(connection, scope=scope, reference=ref,
                                                                 skip_unknown_identity=True)
            if not pinned:
                REFERENCE_SCAN_ISSUES.note(logger, "telemetry_reference_scan_issue",
                                           "reference_not_a_telemetry_identity", identity=item.identity)
