"""Intent services.

Scope:
- Intent payload normalization and validation reason generation
- C5-safe workspace/network boundary checks
- Baseline explainability and confidence shaping for validated/rejected intents
- ADR-028: workspace-unique idempotent validation (replay or 409), commit-before-publish
  with deterministic event IDs, and a deferred-event sweep for the execution worker
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.canonical import canonical_json_bytes, canonical_sha256
from app.core.config import get_settings
from app.core.correlation import normalize_audit_correlation
from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.intent.hypervisor import HypervisorExecutionService
from app.modules.intent.models import Intent, IntentExecution, IntentOutbox
from app.modules.intent.repository import IntentRepository
from app.modules.intent.schemas import ApprovalBinding, SimulationActionBinding
from app.modules.network.service import NetworkService
from app.modules.organization.service import WorkspaceService as OrgWorkspaceService
from app.modules.telemetry.references import evidence_item, install_owner_guard, page_position, reference_page


def intent_telemetry_references(row):
    if row.intent_id is None:
        row.intent_id = uuid.uuid4()
    return evidence_item(identity=f"intent:{row.intent_id}", network_id=row.network_id,
        fields={name: getattr(row, name) for name in (
            "intent_payload", "validation_result", "execution_provenance", "explainability")})


def execution_telemetry_references(row):
    command = row.command or {}
    network = (row.simulation_evidence or {}).get("network_id") or command.get("network_id")
    return evidence_item(identity=f"execution:{row.execution_id}", network_id=network,
        fields={"simulation_evidence": row.simulation_evidence, "command": command, "result": row.result})


def outbox_telemetry_references(row):
    import json

    payload = row.envelope["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return evidence_item(identity=f"intent-outbox:{row.event_id}", network_id=payload.get("network_id"),
                         fields={"payload": payload})


install_owner_guard(Intent, owner="intent", extractor=intent_telemetry_references,
    fields=("intent_payload", "validation_result", "execution_provenance", "explainability", "workspace_id", "network_id"))
install_owner_guard(IntentExecution, owner="intent", extractor=execution_telemetry_references,
    fields=("simulation_evidence", "command", "result", "workspace_id"))


async def telemetry_reference_page(db, *, workspace_id, after=None, limit=100):
    """Internal owner keyset over intents and immutable execution evidence."""
    from sqlalchemy import select

    stage, last = page_position(after, stages=3, limit=limit)
    if stage == 2:
        query = select(IntentOutbox).join(IntentExecution,
            IntentExecution.execution_id == IntentOutbox.execution_id).where(IntentExecution.workspace_id == workspace_id)
        if last:
            query = query.where(IntentOutbox.event_id > last)
        rows = list((await db.scalars(query.order_by(IntentOutbox.event_id).limit(limit + 1))).all())
        return reference_page(rows, extractor=outbox_telemetry_references, key=lambda row: row.event_id,
                              limit=limit, stage=stage, stages=3)
    model, key, extractor = ((Intent, Intent.intent_id, intent_telemetry_references),
        (IntentExecution, IntentExecution.execution_id, execution_telemetry_references))[stage]
    query = select(model).where(model.workspace_id == workspace_id)
    if last:
        query = query.where(key > last)
    rows = list((await db.scalars(query.order_by(key).limit(limit + 1))).all())
    return reference_page(rows, extractor=extractor, key=lambda row: getattr(row, key.key),
                          limit=limit, stage=stage, stages=3)

logger = get_logger(__name__)

_SUPPORTED_ACTIONS = {
    "optimize_wireless_capacity",
    "reroute_path",
    "isolate_vlan",
    "throttle_qos",
}

_HIGH_IMPACT_ACTIONS = {
    "isolate_vlan",
    "reroute_path",
}

_EXECUTION_STATUSES = {"execution_started", "execution_completed", "execution_failed"}
_DEFERRED = "deferred"
_QUEUE_UNAVAILABLE = "event_queue_unavailable"
_STARTED_SUMMARY = "Execution requested; no controller is installed and no dispatch occurred."
MAX_IDEMPOTENCY_KEY_LENGTH = 120
# Deferred rows younger than this are left to the request that is publishing them.
DEFERRED_EVENT_GRACE_SECONDS = 30


def is_high_impact(intent) -> bool:
    """High-impact actions need blast-radius review and, in the lab, simulation (C18)."""
    payload = intent.intent_payload if isinstance(getattr(intent, "intent_payload", None), dict) else {}
    action = _coerce_non_empty_text(payload.get("action")) or _coerce_non_empty_text(getattr(intent, "intent_kind", ""))
    return action in _HIGH_IMPACT_ACTIONS


def require_distinct_approver() -> bool:
    """Four-eyes rule for manual lab approval; read with a default until the platform declares it."""
    return bool(getattr(get_settings(), "INTENT_REQUIRE_DISTINCT_APPROVER", True))


def request_fingerprint(*, network_id, intent: dict[str, Any]) -> str:
    """Identity of a validate submission: same network + same normalized intent."""
    return canonical_sha256({"version": 1, "network_id": str(network_id) if network_id else None, "intent": intent})


def _coerce_non_empty_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _extract_unil_intent(intent_payload: Any) -> dict[str, Any]:
    if not isinstance(intent_payload, dict):
        return {}
    nested_intent = intent_payload.get("intent")
    if isinstance(nested_intent, dict):
        return nested_intent
    return intent_payload


def _build_reason(code: str, message: str, path: str | None = None) -> dict[str, str]:
    reason = {"code": code, "message": message}
    if path:
        reason["path"] = path
    return reason


def _coerce_permissions_for_execute(raw_permissions: Any) -> set[str]:
    if not isinstance(raw_permissions, list):
        return set()
    normalized: set[str] = set()
    for raw in raw_permissions:
        permission = str(raw).strip().lower()
        if permission:
            normalized.add(permission)
    return normalized


def _confidence_band(score: float) -> str:
    if score >= 0.95:
        return "95-100"
    if score >= 0.80:
        return "80-94"
    if score >= 0.60:
        return "60-79"
    return "below_60"


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def approval_binding_of(intent) -> dict[str, Any] | None:
    """The approved lab identity: the durable execution's, else the validate-time one."""
    provenance = _as_dict(getattr(intent, "execution_provenance", None))
    candidate = None
    if provenance.get("execution_id"):
        candidate = {key: provenance.get(key) for key in ("plan_hash", "binding_digest", "run_id")}
    if candidate is None or not all(candidate.values()):
        candidate = _as_dict(getattr(intent, "validation_result", None)).get("approval_binding")
    try:
        return ApprovalBinding.model_validate(candidate).model_dump(mode="json") if candidate else None
    except ValidationError:
        return None


def simulation_action_binding_of(intent) -> dict[str, Any] | None:
    candidate = _as_dict(getattr(intent, "validation_result", None)).get("simulation_action_binding")
    try:
        return SimulationActionBinding.model_validate(candidate).model_dump(mode="json") if candidate else None
    except ValidationError:
        return None


def _event_id(intent_id: uuid.UUID, event_type: str) -> str:
    """Stable ID per intent lifecycle event: republication is deduplicated (EventAPI §4)."""
    return str(uuid.uuid5(intent_id, event_type))


def _confidence_payload(intent) -> dict[str, Any]:
    score = float(intent.confidence_score or 0.0)
    return {"score": score, "band": str(intent.confidence_band or _confidence_band(score)),
            "approval_required": bool(intent.approval_required)}


def validated_event(intent, org_id) -> tuple[str, str, dict[str, Any], str]:
    """``intent.validated`` rebuilt from the committed row (request path and sweep agree)."""
    validation = _as_dict(intent.validation_result)
    status_value = "validated" if validation.get("is_valid") else "rejected"
    explainability = {key: value for key, value in _as_dict(intent.explainability).items()
                      if key not in {"execution_posture", "execution_summary", "failure_reason", "model_confidence"}}
    payload = {
        "org_id": str(org_id),
        "intent_id": str(intent.intent_id),
        "workspace_id": str(intent.workspace_id),
        "network_id": str(intent.network_id) if intent.network_id is not None else None,
        "intent_kind": str(intent.intent_kind),
        "status": status_value,
        "validation_result": validation,
        "execution_provenance": {
            "pipeline_stage": "intent_validated",
            "status": status_value,
            "policy_reference": validation.get("policy_reference", "ADR-008"),
            "requested_by_user_id": str(intent.requested_by_user_id),
            "validated_at": validation.get("validated_at"),
        },
        "explainability": explainability,
        "confidence": {"score": 0.0, "band": "below_60", "approval_required": True},
        "requested_by_user_id": str(intent.requested_by_user_id),
    }
    return "intent.validated", _event_id(intent.intent_id, "intent.validated"), payload, str(intent.correlation_id)


def legacy_execution_events(intent, org_id) -> list[tuple[str, str, dict[str, Any], str]]:
    """Started + terminal events of the fail-closed (no controller) execution path."""
    terminal = _as_dict(intent.execution_provenance)
    explainability = _as_dict(intent.explainability)
    correlation = str(terminal.get("correlation_id") or intent.correlation_id)
    started_provenance = {key: value for key, value in terminal.items()
                          if key not in {"execution_failed_at", "failure_reason", "verification"}}
    started_provenance.update(pipeline_stage="execution_started", status="execution_started")
    started_explainability = {key: value for key, value in explainability.items() if key != "failure_reason"}
    started_explainability["execution_summary"] = _STARTED_SUMMARY
    base = {
        "org_id": str(org_id),
        "intent_id": str(intent.intent_id),
        "workspace_id": str(intent.workspace_id),
        "network_id": str(intent.network_id) if intent.network_id is not None else None,
        "intent_kind": str(intent.intent_kind),
        "validation_result": _as_dict(intent.validation_result),
        "confidence": _confidence_payload(intent),
        "requested_by_user_id": str(terminal.get("requested_by_user_id") or intent.requested_by_user_id),
    }
    terminal_type = f"intent.{intent.status}"
    return [
        ("intent.execution_started", _event_id(intent.intent_id, "intent.execution_started"),
         {**base, "status": "execution_started", "execution_provenance": started_provenance,
          "explainability": started_explainability}, correlation),
        (terminal_type, _event_id(intent.intent_id, terminal_type),
         {**base, "status": str(intent.status), "execution_provenance": terminal, "explainability": explainability},
         correlation),
    ]


def intent_event_sequence(intent, org_id) -> list[tuple[str, str, dict[str, Any], str]]:
    events = [validated_event(intent, org_id)]
    provenance = _as_dict(intent.execution_provenance)
    if intent.status in _EXECUTION_STATUSES and provenance.get("executor") == "unavailable":
        events.extend(legacy_execution_events(intent, org_id))
    return events


async def publish_intent_events(redis, events) -> str | None:
    """Publish in order; stop at the first failure so no event overtakes a predecessor."""
    stream_entry_id = None
    for event_type, event_id, payload, correlation_id in events:
        stream_entry_id = await publish_event(redis=redis, event_type=event_type, source="intent",
                                              payload=payload, correlation_id=correlation_id, event_id=event_id)
    return stream_entry_id


async def republish_deferred_intents(*, db: AsyncSession, redis, limit: int = 20,
                                     grace_seconds: float = DEFERRED_EVENT_GRACE_SECONDS) -> int:
    """Sweep committed intents whose events were never confirmed (queue_status=deferred).

    Run by the intent execution worker. Rows are locked ``SKIP LOCKED`` and aged past
    the in-flight grace period. Deterministic event IDs make republication of an
    already delivered event a consumer-side duplicate, never a new event.
    """
    published = 0
    workspaces = OrgWorkspaceService(db=db, redis=redis)
    for intent in await IntentRepository(db).claim_deferred(limit=limit, older_than_seconds=grace_seconds):
        try:
            org_id = (await workspaces.get_active_workspace(intent.workspace_id)).org_id
        except HTTPException:
            # Keep it deferred but out of the sweep; operators can inspect it.
            intent.warning = "event_workspace_unavailable"
            continue
        try:
            stream_entry_id = await publish_intent_events(redis, intent_event_sequence(intent, org_id))
        except Exception as exc:  # noqa: BLE001 - stays deferred for the next sweep
            logger.warning("intent_deferred_event_republish_failed", intent_id=str(intent.intent_id),
                           error_type=type(exc).__name__)
            break
        intent.queue_status = "validated" if intent.status in {"validated", "rejected"} else "queued"
        intent.stream_entry_id, intent.warning = stream_entry_id, None
        published += 1
    await db.commit()
    return published


def validation_response(intent, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "intent_id": str(intent.intent_id),
        "workspace_id": str(intent.workspace_id),
        "network_id": str(intent.network_id) if intent.network_id is not None else None,
        "status": str(intent.status),
        "intent_kind": str(intent.intent_kind),
        "validation": _as_dict(intent.validation_result),
        "explainability": _as_dict(intent.explainability),
        "confidence": {"score": 0.0, "band": "below_60", "approval_required": True},
        "idempotency_key": intent.idempotency_key,
        "correlation_id": str(intent.correlation_id),
        "requested_at": intent.requested_at.isoformat(),
        "queue_status": str(intent.queue_status),
        "stream_entry_id": intent.stream_entry_id,
        "warning": intent.warning,
        "idempotent_replay": idempotent_replay,
        "approval_binding": approval_binding_of(intent),
        "simulation_action_binding": simulation_action_binding_of(intent),
    }


class IntentValidationService:
    """Validate intent payloads and persist baseline lifecycle state."""

    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = IntentRepository(db)
        self._network_svc = NetworkService(db, redis)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def _replay(self, existing, *, request_sha256: str, network_id, normalized_intent) -> dict[str, Any]:
        """C3: the same key replays only the same network + normalized intent."""
        stored = _as_dict(existing.validation_result).get("request_sha256")
        if stored is not None:
            same = stored == request_sha256
        else:  # validated before ADR-028: compare the persisted request itself
            same = (existing.network_id == network_id and isinstance(existing.intent_payload, dict)
                    and canonical_json_bytes(existing.intent_payload) == canonical_json_bytes(normalized_intent))
        if not same:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "Idempotency-Key already identifies a different intent submission in this workspace; "
                           "generate a fresh key for each new submission.",
            })
        return validation_response(existing, idempotent_replay=True)

    async def validate_intent(
        self,
        *,
        workspace_id: uuid.UUID,
        network_id: uuid.UUID | None,
        intent_payload: dict[str, Any],
        idempotency_key: str | None,
        correlation_id: str,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        workspace = await self._workspace_svc.get_active_workspace(workspace_id, user_id=requested_by_user_id, require_write=True)

        now = datetime.now(UTC)
        normalized_intent = _extract_unil_intent(intent_payload)
        normalized_idempotency_key = _coerce_non_empty_text(idempotency_key) or None
        if normalized_idempotency_key is not None and len(normalized_idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={
                "code": "IDEMPOTENCY_KEY_INVALID",
                "message": f"Idempotency-Key must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters.",
            })
        request_sha256 = request_fingerprint(network_id=network_id, intent=normalized_intent)
        if normalized_idempotency_key:
            existing = await self._repo.get_by_idempotency_key(
                workspace_id=workspace_id, idempotency_key=normalized_idempotency_key,
            )
            if existing is not None:
                return await self._replay(existing, request_sha256=request_sha256, network_id=network_id,
                                          normalized_intent=normalized_intent)
        # ADR-028 C20: shared mapping; an opaque client id is kept in provenance.
        normalized_correlation_id, correlation_meta = normalize_audit_correlation(correlation_id, None)
        intent_id = uuid.uuid4()
        requested_network_id = network_id
        reasons: list[dict[str, str]] = []

        action = _coerce_non_empty_text(normalized_intent.get("action"))
        if not action:
            reasons.append(
                _build_reason(
                    "ACTION_REQUIRED",
                    "Intent action is required.",
                    path="intent.action",
                )
            )
        elif action not in _SUPPORTED_ACTIONS:
            reasons.append(
                _build_reason(
                    "ACTION_UNSUPPORTED",
                    "Intent action is not supported by the baseline capability map.",
                    path="intent.action",
                )
            )

        scope = normalized_intent.get("scope")
        if not isinstance(scope, dict) or not scope:
            reasons.append(
                _build_reason(
                    "SCOPE_REQUIRED",
                    "Intent scope must be a non-empty object.",
                    path="intent.scope",
                )
            )

        constraints = normalized_intent.get("constraints")
        if constraints is not None and not isinstance(constraints, dict):
            reasons.append(
                _build_reason(
                    "CONSTRAINTS_INVALID",
                    "Intent constraints must be an object when provided.",
                    path="intent.constraints",
                )
            )

        if network_id is None:
            reasons.append(
                _build_reason(
                    "NETWORK_ID_REQUIRED",
                    "network_id is required for capability and dependency validation.",
                    path="network_id",
                )
            )
        else:
            try:
                network = await self._network_svc.assert_network_workspace_access(
                    network_id=network_id, requested_workspace_id=workspace_id,
                    actor_user_id=requested_by_user_id, require_write=True,
                )
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                network = None
            if network is None:
                network_id = None
                reasons.append(
                    _build_reason(
                        "NETWORK_NOT_FOUND",
                        "network_id does not reference an active network.",
                        path="network_id",
                    )
                )
            elif network.workspace_id != workspace_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        high_impact = action in _HIGH_IMPACT_ACTIONS
        required_checks = ["simulation_before_deployment"]
        if high_impact:
            required_checks.append("blast_radius_assessment")

        settings = get_settings()
        lab_validation = settings.EXECUTION_MODE == "emulation" and settings.EMULATION_CONTROL_ENABLED
        approval_binding = simulation_action_binding = None
        if lab_validation and not reasons:
            from app.modules.intent.lab import digest as lab_digest
            from app.modules.intent.lab import prepare_plan
            from app.modules.simulation.modeled import current_network_state_hash

            try:
                plan, binding, snapshot = await prepare_plan(settings=settings, db=self._db, redis=self._redis,
                    workspace_id=workspace_id, network_id=network_id, actor_id=requested_by_user_id,
                    payload=normalized_intent)
                plan_hash = lab_digest(plan.model_dump(mode="json"))
                # ADR-028 contract 3: the identity an approver must echo on execute.
                approval_binding = {"plan_hash": plan_hash, "binding_digest": lab_digest(binding.model_dump(mode="json")),
                                    "run_id": str(snapshot.run_id)}
                # C18: stable topology/configuration digest for scenario_config.action_binding.
                simulation_action_binding = {"intent_id": str(intent_id), "plan_sha256": plan_hash,
                    "network_state_sha256": current_network_state_hash(binding=binding, snapshot=snapshot)}
            except (ValueError, OSError, ImportError):
                reasons.append(_build_reason("LAB_PLAN_INVALID", "Lab plan, capabilities, binding or fresh observation invalid."))
            required_checks = ["explicit_manual_lab_approval", "current_authority_before_dispatch", "actual_lab_readback"]
            if high_impact:
                required_checks.append("simulation_before_deployment")
            if require_distinct_approver():
                required_checks.append("distinct_approver")

        is_valid = len(reasons) == 0
        status_value = "validated" if is_valid else "rejected"
        capability_match = "baseline_schema_match" if is_valid else "failed"
        dependency_analysis = "not_performed"

        confidence_score = 0.0
        confidence_band = _confidence_band(confidence_score)
        approval_required = True

        validation_result = {
            "is_valid": is_valid,
            "reasons": reasons,
            "required_checks": required_checks,
            "capability_match": capability_match,
            "dependency_analysis": dependency_analysis,
            "simulation_required": True,
            "policy_reference": "ADR-008",
            "validated_at": now.isoformat(),
            "validation_kind": "baseline_schema_only",
            "model_evidence": "unavailable",
            "request_sha256": request_sha256,
        }
        explainability = {
            "summary": (
                "Intent passed baseline UNIL validation checks."
                if is_valid
                else "Intent rejected by baseline UNIL validation checks."
            ),
            "evidence": ([reason["code"] for reason in reasons] if reasons else ["BASELINE_SCHEMA_CHECKS_PASSED"])
            + ["MODEL_CONFIDENCE_UNAVAILABLE", "DEPENDENCY_EVALUATOR_UNAVAILABLE"],
            "alternatives_considered": ["manual_review"],
            "policy_reference": "ADR-008",
        }
        execution_provenance = {
            "pipeline_stage": "intent_validated",
            "status": status_value,
            "policy_reference": "ADR-008",
            "requested_by_user_id": requested_by_user_id,
            "validated_at": now.isoformat(),
            **correlation_meta,
        }
        if lab_validation:
            validation_result.update(validation_kind="manual_lab_plan", policy_reference="ADR-010",
                                     capability_match="trusted_lab_plan" if is_valid else "failed",
                                     simulation_required=high_impact)
            if is_valid and approval_binding is not None:
                validation_result.update(approval_binding=approval_binding,
                                         simulation_action_binding=simulation_action_binding)

        # ADR-028: commit first with a pessimistic "deferred" publication state; the
        # event is published afterwards and only its success is recorded.
        try:
            intent = await self._repo.create(
                intent_id=intent_id,
                workspace_id=workspace_id,
                network_id=network_id,
                intent_kind=(action or "unknown"),
                intent_payload=normalized_intent,
                status=status_value,
                validation_result=validation_result,
                execution_provenance=execution_provenance,
                explainability=explainability,
                confidence_score=confidence_score,
                confidence_band=confidence_band,
                approval_required=approval_required,
                idempotency_key=normalized_idempotency_key,
                correlation_id=normalized_correlation_id,
                queue_status=_DEFERRED,
                stream_entry_id=None,
                warning=_QUEUE_UNAVAILABLE,
                requested_by_user_id=requested_by_user_id,
                requested_at=now,
            )
            await self._db.commit()
        except IntegrityError:
            # Concurrent submission with the same key won the unique index.
            await self._db.rollback()
            existing = (await self._repo.get_by_idempotency_key(
                workspace_id=workspace_id, idempotency_key=normalized_idempotency_key,
            ) if normalized_idempotency_key else None)
            if existing is None:
                raise
            return await self._replay(existing, request_sha256=request_sha256, network_id=requested_network_id,
                                      normalized_intent=normalized_intent)

        await self._publish_committed(intent, [validated_event(intent, workspace.org_id)], success="validated")
        return validation_response(intent, idempotent_replay=False)

    async def _publish_committed(self, intent, events, *, success: str) -> bool:
        try:
            stream_entry_id = await publish_intent_events(self._redis, events)
        except Exception as exc:  # noqa: BLE001 - committed row stays deferred for the sweep
            logger.warning("intent_event_publish_deferred", intent_id=str(intent.intent_id),
                           error_type=type(exc).__name__)
            return False
        await self._repo.update_status(intent, status=intent.status, queue_status=success,
                                       stream_entry_id=stream_entry_id, warning=None)
        await self._db.commit()
        return True


class IntentExecutionService:
    """Execute and read validated intents with baseline idempotent semantics."""

    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = IntentRepository(db)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def _serialize_with_fresh_timestamps(
        self,
        intent,
        *,
        idempotent_replay: bool,
        confidence_override: dict[str, Any],
        detail_mode: bool = False,
    ) -> dict[str, Any]:
        # Ensure ORM-backed response attributes are loaded before sync serialization.
        # Refreshing all mapped columns prevents async lazy-load attempts (MissingGreenlet).
        await self._db.refresh(intent)
        return _serialize_intent(
            intent,
            idempotent_replay=idempotent_replay,
            confidence_override=confidence_override,
            detail_mode=detail_mode,
        )

    async def execute_intent(
        self,
        *,
        workspace_id: uuid.UUID,
        intent_id: uuid.UUID,
        idempotency_key: str | None,
        correlation_id: str,
        requested_by_user_id: str,
        requested_permissions: list[str],
        manual_approval: bool = False,
        cancel: bool = False,
        simulation_id: uuid.UUID | None = None,
        approval_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        if simulation_id is not None and not cancel and (settings.EXECUTION_MODE != "emulation"
                                                        or not settings.EMULATION_CONTROL_ENABLED):
            raise HTTPException(409, detail={"code": "SIMULATION_EVIDENCE_REJECTED",
                "message": "Referenced simulation requires a current prepared plan; model evidence cannot authorize production."})
        supplied_key = _coerce_non_empty_text(idempotency_key) or None
        normalized_correlation_id, correlation_meta = normalize_audit_correlation(correlation_id, None)
        if cancel or (settings.EXECUTION_MODE == "emulation" and settings.EMULATION_CONTROL_ENABLED):
            from app.modules.intent.execution import accept_execution

            intent, replay = await accept_execution(db=self._db, redis=self._redis, workspace_id=workspace_id,
                intent_id=intent_id, idempotency_key=supplied_key,
                correlation_id=normalized_correlation_id, actor_id=requested_by_user_id,
                permissions=requested_permissions, manual_approval=manual_approval, cancel=cancel,
                simulation_id=simulation_id, approval_binding=approval_binding)
            return await self._serialize_with_fresh_timestamps(intent, idempotent_replay=replay,
                confidence_override={"score": 0.0, "band": "below_60", "approval_required": True})
        from app.modules.intent.execution import resolve_execution_key

        now = datetime.now(UTC)

        if "execute:rollback" not in _coerce_permissions_for_execute(requested_permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INTENT_EXECUTION_PERMISSION_DENIED",
                    "message": "execute:rollback permission is required for intent execution.",
                },
            )

        workspace = await self._workspace_svc.get_active_workspace(workspace_id, user_id=requested_by_user_id, require_write=True)

        # ADR-028 C3: lock the intent row; concurrent executes serialize here.
        intent = await self._repo.get_by_id(intent_id, lock=True)
        if intent is None or intent.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "INTENT_NOT_FOUND", "message": "Intent not found."},
            )
        stored_key = _coerce_non_empty_text(intent.idempotency_key) or None
        key = await resolve_execution_key(self._repo, workspace_id=workspace_id, intent=intent, supplied=supplied_key)

        if intent.status in _EXECUTION_STATUSES:
            if stored_key is not None and key == stored_key:
                return await self._serialize_with_fresh_timestamps(
                    intent, idempotent_replay=True, confidence_override=_confidence_payload(intent),
                )
            if intent.status == "execution_started":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "INTENT_ALREADY_EXECUTING",
                        "message": "Intent execution has already been started.",
                    },
                )

        if intent.status != "validated":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INTENT_NOT_EXECUTABLE",
                    "message": "Intent must be in validated state before execution.",
                },
            )
        validated_event_pending = intent.queue_status == _DEFERRED
        # Compare-and-set: only one transaction can move validated -> execution_started.
        if not await self._repo.claim_for_execution(intent_id=intent_id, workspace_id=workspace_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INTENT_ALREADY_EXECUTING",
                    "message": "Intent execution has already been started.",
                },
            )

        execution_provenance_started = (
            dict(intent.execution_provenance) if isinstance(intent.execution_provenance, dict) else {}
        )
        execution_provenance_started.update(
            {
                "pipeline_stage": "execution_started",
                "status": "execution_started",
                "executor": "unavailable",
                "policy_reference": "ADR-008",
                "execution_started_at": now.isoformat(),
                "requested_by_user_id": requested_by_user_id,
                "correlation_id": str(normalized_correlation_id),
                **correlation_meta,
            }
        )

        explainability_started = (
            dict(intent.explainability) if isinstance(intent.explainability, dict) else {}
        )
        explainability_started.update(
            {
                "execution_posture": "simulation_required_before_hypervisor",
                "execution_summary": _STARTED_SUMMARY,
            }
        )

        confidence_score = 0.0
        confidence_band = _confidence_band(confidence_score)
        approval_required = True

        hypervisor_outcome = HypervisorExecutionService().execute(
            intent_id=intent.intent_id,
            intent_kind=str(intent.intent_kind),
            validation_result=(
                dict(intent.validation_result)
                if isinstance(intent.validation_result, dict)
                else {}
            ),
            correlation_id=normalized_correlation_id,
            requested_by_user_id=requested_by_user_id,
        )

        terminal_status = hypervisor_outcome.terminal_status
        terminal_time = datetime.now(UTC)
        terminal_execution_provenance = dict(execution_provenance_started)
        terminal_execution_provenance.pop("rollback", None)
        terminal_execution_provenance.pop("execution_completed_at", None)
        terminal_execution_provenance.pop("completion_mode", None)
        terminal_execution_provenance.update(
            {
                "pipeline_stage": "execution_failed",
                "status": "execution_failed",
                "execution_failed_at": terminal_time.isoformat(),
                "failure_reason": hypervisor_outcome.failure_reason,
                "verification": hypervisor_outcome.verification,
            }
        )
        terminal_explainability = dict(explainability_started)
        terminal_explainability.update(
            {
                "execution_summary": hypervisor_outcome.execution_summary,
                "failure_reason": hypervisor_outcome.failure_reason,
            }
        )

        update_kwargs: dict[str, Any] = {
            "status": terminal_status,
            "execution_provenance": terminal_execution_provenance,
            "explainability": terminal_explainability,
            "confidence_score": confidence_score,
            "confidence_band": confidence_band,
            "approval_required": approval_required,
            # ADR-028: committed before any publication; success is recorded after.
            "queue_status": _DEFERRED,
            "stream_entry_id": None,
            "warning": _QUEUE_UNAVAILABLE,
        }
        if stored_key is None and key is not None:
            update_kwargs["idempotency_key"] = key
        await self._repo.update_status(intent, **update_kwargs)
        try:
            await self._db.commit()
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
                "code": "INTENT_IDEMPOTENCY_CONFLICT",
                "message": "idempotency_key is already bound to a different intent.",
            }) from exc

        events = legacy_execution_events(intent, workspace.org_id)
        if validated_event_pending:
            events.insert(0, validated_event(intent, workspace.org_id))
        try:
            stream_entry_id = await publish_intent_events(self._redis, events)
        except Exception as exc:  # noqa: BLE001 - committed row stays deferred for the sweep
            logger.warning(
                "intent_terminal_event_publish_failed",
                intent_id=str(intent.intent_id),
                status=terminal_status,
                correlation_id=str(normalized_correlation_id),
                error_type=type(exc).__name__,
            )
        else:
            await self._repo.update_status(intent, status=terminal_status, queue_status="queued",
                                           stream_entry_id=stream_entry_id, warning=None)
            await self._db.commit()

        return await self._serialize_with_fresh_timestamps(
            intent,
            idempotent_replay=False,
            confidence_override={
                "score": confidence_score,
                "band": confidence_band,
                "approval_required": approval_required,
            },
        )

    async def get_intent_detail(
        self,
        *,
        workspace_id: uuid.UUID,
        intent_id: uuid.UUID,
        user_id: str,
    ) -> dict[str, Any]:
        await self._workspace_svc.get_active_workspace(workspace_id, user_id=user_id)
        intent = await self._repo.get_by_id(intent_id)
        if intent is None or intent.workspace_id != workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "INTENT_NOT_FOUND", "message": "Intent not found."},
            )
        return await self._serialize_with_fresh_timestamps(
            intent,
            idempotent_replay=False,
            confidence_override={
                "score": float(intent.confidence_score or 0.0),
                "band": str(
                    intent.confidence_band
                    or _confidence_band(float(intent.confidence_score or 0.0))
                ),
                "approval_required": bool(intent.approval_required),
            },
            detail_mode=True,
        )


def _serialize_intent(
    intent,
    *,
    idempotent_replay: bool,
    confidence_override: dict[str, Any],
    detail_mode: bool = False,
) -> dict[str, Any]:
    base = {
        "intent_id": str(intent.intent_id),
        "workspace_id": str(intent.workspace_id),
        "network_id": str(intent.network_id) if intent.network_id is not None else None,
        "status": str(intent.status),
        "intent_kind": str(intent.intent_kind),
        "validation_result": (
            dict(intent.validation_result)
            if isinstance(intent.validation_result, dict)
            else {}
        ),
        "execution_provenance": (
            dict(intent.execution_provenance)
            if isinstance(intent.execution_provenance, dict)
            else {}
        ),
        "explainability": (
            dict(intent.explainability)
            if isinstance(intent.explainability, dict)
            else {}
        ),
        "confidence": {"score": 0.0, "band": "below_60", "approval_required": True},
        "idempotency_key": intent.idempotency_key,
        "queue_status": str(intent.queue_status),
        "stream_entry_id": intent.stream_entry_id,
        "warning": intent.warning,
        "correlation_id": str(intent.correlation_id),
        "requested_by_user_id": str(intent.requested_by_user_id),
        "requested_at": intent.requested_at.isoformat(),
        "updated_at": intent.updated_at.isoformat(),
        "approval_binding": approval_binding_of(intent),
    }
    if base["validation_result"].get("validation_kind") != "manual_lab_plan":
        base["validation_result"].update(
            validation_kind="baseline_schema_only", model_evidence="unavailable", dependency_analysis="not_performed",
        )
    if base["validation_result"].get("capability_match") == "matched":
        base["validation_result"]["capability_match"] = "baseline_schema_match"
    base["explainability"]["model_confidence"] = "unavailable; baseline schema checks are not model evidence"
    provenance = base["execution_provenance"]
    from app.modules.intent.lab import verified_completion

    measured_lab = (provenance.get("executor") == "manual_lab_v1" and provenance.get("phase") == "completed"
                    and verified_completion(provenance.get("verification", {}))
                    and bool(provenance.get("plan_hash")) and bool(provenance.get("execution_id")))
    if (base["status"] == "execution_completed" and not measured_lab) or provenance.get("executor") == "hypervisor_baseline":
        outcome = HypervisorExecutionService().execute(
            intent_id=intent.intent_id, intent_kind=str(intent.intent_kind), validation_result={},
            correlation_id=intent.correlation_id, requested_by_user_id=str(intent.requested_by_user_id),
        )
        base["status"] = outcome.terminal_status
        base["execution_provenance"] = {
            "status": outcome.terminal_status, "pipeline_stage": outcome.terminal_status,
            "executor": "unavailable", "failure_reason": outcome.failure_reason,
            "verification": outcome.verification, "legacy_baseline_unverified": True,
        }
        base["explainability"].update(execution_summary=outcome.execution_summary, failure_reason=outcome.failure_reason)
    if detail_mode:
        base["intent_payload"] = (
            dict(intent.intent_payload)
            if isinstance(intent.intent_payload, dict)
            else {}
        )
        base["created_at"] = intent.created_at.isoformat()
        base["simulation_action_binding"] = simulation_action_binding_of(intent)
        return base

    base["idempotent_replay"] = idempotent_replay
    return base
