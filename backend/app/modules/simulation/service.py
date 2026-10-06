"""Simulation services.

Scope:
- Deterministic scenario validation handoff payload shaping (legacy unconfigured runs)
- Lifecycle events: state and a durable outbox copy commit first, publication follows
  (ADR-028); the simulation worker republishes any unpublished outbox envelope
- VS7 simulation persistence baseline integration
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.network.service import NetworkService
from app.modules.organization.service import WorkspaceService as OrgWorkspaceService
from app.modules.simulation.modeled import (
    configured,
    create_modeled,
    limits_respect_policy,
    policy_floors,
    transition_modeled,
    validate_execution_reference,
    verified_output_async,
)
from app.modules.simulation.repository import SimulationRepository, normalize_correlation
from app.modules.simulation.schemas import ScenarioConfig

logger = get_logger(__name__)

_DEFAULT_SCENARIO_ID_NAMESPACE = "scenario"
_DEFAULT_SIMULATION_OBJECT_ID = "simulation-state"
# No evaluator is installed for unconfigured runs: they always end cancelled/blocked.
_LEGACY_TERMINAL_STATE = "cancelled"
_LEGACY_TERMINAL_RISK_GATE = "blocked"
_LEGACY_TERMINAL_EVENT = "simulation.cancelled"


def _derive_terminal_event_id(*, simulation_id: uuid.UUID, event_type: str) -> str:
    """Return a deterministic lifecycle event UUID for idempotent (re)publication."""
    return str(uuid.uuid5(simulation_id, event_type))


def _coerce_non_empty_text(value: Any, fallback: str) -> str:
    text = str(value).strip()
    return text or fallback


def _coerce_uuid_string(value: Any) -> str:
    return str(uuid.UUID(str(value)))


def _coerce_requested_by_user_id(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return "unknown"
    try:
        return str(uuid.UUID(text))
    except (TypeError, ValueError, AttributeError):
        return text


def _normalize_validation_checks(values: Any) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []

    normalized: list[str] = []
    for raw in values:
        item = str(raw).strip()
        if item:
            normalized.append(item)
    return normalized


def _derive_scenario_id(network_id: str, scenario_label: str) -> str:
    deterministic_name = f"{network_id}:{scenario_label}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, deterministic_name))


def _coerce_iso_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(UTC)


def _unavailable_metrics() -> dict[str, None]:
    """No evaluator exists, including for historical baseline output records."""
    return {
        "latency_ms": None,
        "loss_pct": None,
        "throughput_mbps": None,
    }


class ScenarioValidationHandoffService:
    """Build deterministic simulation validation handoff payloads."""

    def build_handoff_payload(
        self,
        *,
        network_id: Any,
        scenario_name: Any,
        validation_checks: Any,
        correlation_id: Any,
        requested_by_user_id: Any,
    ) -> dict[str, Any]:
        normalized_network_id = _coerce_uuid_string(network_id)
        # ADR-028 C20: shared request-id mapping; the original id stays in metadata.
        normalized_correlation_id, correlation_meta = normalize_correlation(correlation_id)
        normalized_requested_by = _coerce_requested_by_user_id(requested_by_user_id)

        normalized_scenario_name = _coerce_non_empty_text(
            scenario_name,
            fallback=f"{_DEFAULT_SCENARIO_ID_NAMESPACE}-{normalized_network_id[:8]}",
        )
        normalized_checks = _normalize_validation_checks(validation_checks)
        if not normalized_checks:
            normalized_checks = ["simulation_before_deployment"]

        scenario_id = _derive_scenario_id(normalized_network_id, normalized_scenario_name)
        simulation_id = str(uuid.uuid4())
        now_iso = datetime.now(UTC).isoformat()

        return {
            "simulation_id": simulation_id,
            "scenario_id": scenario_id,
            "network_id": normalized_network_id,
            "scene_object_id": _DEFAULT_SIMULATION_OBJECT_ID,
            "state": "queued",
            "status": "queued",
            "risk_gate": "required",
            "scenario_name": normalized_scenario_name,
            "validation": {
                "pipeline_stage": "handoff_queued",
                "required_checks": normalized_checks,
                "policy_reference": "ADR-008",
                "status": "pending",
                "queued_at": now_iso,
                "requested_by_user_id": normalized_requested_by,
                "evaluator_status": "unavailable",
            },
            "requested_at": now_iso,
            "correlation_id": normalized_correlation_id,
            **correlation_meta,
        }


class SimulationEventService:
    """Publish simulation lifecycle events for digital twin consumers."""

    def __init__(self, *, redis: aioredis.Redis):
        self._redis = redis

    async def publish_lifecycle_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str,
        event_id: str | None = None,
    ) -> str:
        return await publish_event(
            redis=self._redis,
            event_type=event_type,
            source="simulation",
            payload=payload,
            correlation_id=correlation_id,
            event_id=event_id,
        )


class SimulationTerminalEventService:
    """Process started simulation events into terminal lifecycle outcomes."""

    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = SimulationRepository(db)

    async def process_started_event(self, *, event: dict[str, Any]) -> None:
        payload_raw = event.get("payload")
        payload = payload_raw if isinstance(payload_raw, dict) else {}
        simulation_id_raw = payload.get("simulation_id")
        simulation_id_text = str(simulation_id_raw).strip()
        if not simulation_id_text:
            logger.warning(
                "simulation_terminal_transition_missing_simulation_id",
                event_type=str(event.get("event_type", "")),
            )
            return

        try:
            simulation_id = uuid.UUID(simulation_id_text)
        except (TypeError, ValueError, AttributeError):
            logger.warning(
                "simulation_terminal_transition_invalid_simulation_id",
                event_type=str(event.get("event_type", "")),
                simulation_id=simulation_id_text,
            )
            return

        simulation = await self._repo.get_by_id(simulation_id)
        if simulation is None:
            logger.warning(
                "simulation_terminal_transition_simulation_not_found",
                simulation_id=str(simulation_id),
            )
            return

        if configured(simulation):
            return  # Dedicated worker exclusively owns versioned computation.

        current_state = str(simulation.state).strip().lower()
        current_status = str(simulation.status).strip().lower()
        if current_state in {"completed", "cancelled"} or current_status in {"completed", "cancelled"}:
            logger.info(
                "simulation_terminal_transition_deduped",
                simulation_id=str(simulation.simulation_id),
                state=current_state,
                status=current_status,
            )
            return

        terminal_state, terminal_risk_gate = _LEGACY_TERMINAL_STATE, _LEGACY_TERMINAL_RISK_GATE
        terminal_event_type = _LEGACY_TERMINAL_EVENT

        workspace_id = str(simulation.workspace_id)
        if not workspace_id:
            logger.warning(
                "simulation_terminal_transition_missing_workspace_id",
                simulation_id=str(simulation.simulation_id),
            )
            return

        normalized_validation = dict(simulation.validation) if isinstance(simulation.validation, dict) else {}
        normalized_validation["pipeline_stage"] = "terminal"
        normalized_validation["status"] = terminal_state
        normalized_validation["terminal_event_type"] = terminal_event_type
        normalized_validation["failure_reason"] = "evaluator_unavailable"
        normalized_validation["evaluator_status"] = "unavailable"
        await self._repo.update_state(
            simulation,
            state=terminal_state,
            status=terminal_state,
            risk_gate=terminal_risk_gate,
            validation=normalized_validation,
            run_output=_unavailable_metrics(),
        )

        terminal_payload = {
            "simulation_id": str(simulation.simulation_id),
            "scenario_id": str(simulation.scenario_id),
            "network_id": str(simulation.network_id),
            "workspace_id": workspace_id,
            "scene_object_id": _DEFAULT_SIMULATION_OBJECT_ID,
            "state": terminal_state,
            "status": terminal_state,
            "risk_gate": terminal_risk_gate,
            "validation": normalized_validation,
            "run_output": _unavailable_metrics(),
            "failure_reason": "evaluator_unavailable",
        }
        correlation_id, _ = normalize_correlation(event.get("correlation_id"))
        event_id = _derive_terminal_event_id(
            simulation_id=simulation.simulation_id,
            event_type=terminal_event_type,
        )

        # State and its durable outbox copy commit together before any publication.
        # This consumer commits exactly once; the worker's later outbox publication of
        # the same event ID is an at-least-once duplicate that consumers deduplicate.
        self._repo.enqueue_legacy(simulation, event_type=terminal_event_type, payload=terminal_payload,
                                  correlation_id=correlation_id, event_id=event_id)
        await self._db.commit()

        try:
            await SimulationEventService(redis=self._redis).publish_lifecycle_event(
                event_type=terminal_event_type,
                payload=terminal_payload,
                correlation_id=correlation_id,
                event_id=event_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "simulation_terminal_event_publish_failed",
                simulation_id=str(simulation.simulation_id),
                event_type=terminal_event_type,
                correlation_id=correlation_id,
                error=str(exc),
            )


class SimulationStartService:
    """Simulation lifecycle service for start/resume/pause/branch flows."""

    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = SimulationRepository(db)
        self._network_svc = NetworkService(db=db, redis=redis)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def validate_execution_reference(self, **kwargs):
        return await validate_execution_reference(self, **kwargs)

    async def _assert_simulation_workspace_access(
        self,
        *,
        simulation,
        requested_workspace_id: uuid.UUID | None,
        actor_user_id: str,
        claim_org_id: uuid.UUID | None,
        require_write: bool = False,
    ) -> None:
        if requested_workspace_id is not None and simulation.workspace_id != requested_workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

        await self._workspace_svc.get_active_workspace(
            simulation.workspace_id,
            user_id=actor_user_id,
            claim_org_id=claim_org_id,
            require_write=require_write,
        )

    async def start_simulation(
        self,
        *,
        network_id: uuid.UUID,
        scenario_name: str,
        simulation_id: uuid.UUID | None,
        validation_checks: list[str],
        correlation_id: str,
        requested_by_user_id: str,
        requested_workspace_id: uuid.UUID | None,
        claim_org_id: uuid.UUID | None,
        scenario_config: ScenarioConfig | None = None,
    ) -> dict[str, Any]:
        if simulation_id is not None:
            return await self._resume_simulation(
                simulation_id=simulation_id,
                correlation_id=correlation_id,
                requested_by_user_id=requested_by_user_id,
                requested_workspace_id=requested_workspace_id,
                claim_org_id=claim_org_id,
                network_id=network_id,
                scenario_config=scenario_config,
            )

        network = await self._network_svc.assert_network_workspace_access(
            network_id=network_id,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=requested_by_user_id,
            claim_org_id=claim_org_id,
            require_write=True,
        )

        if scenario_config is not None:
            return await create_modeled(self, network=network, config=scenario_config,
                scenario_name=scenario_name, actor_id=requested_by_user_id, correlation_id=correlation_id)

        handoff = ScenarioValidationHandoffService().build_handoff_payload(
            network_id=network_id,
            scenario_name=scenario_name,
            validation_checks=validation_checks,
            correlation_id=correlation_id,
            requested_by_user_id=requested_by_user_id,
        )
        validation = handoff.get("validation") if isinstance(handoff.get("validation"), dict) else {}
        handoff.update(state="cancelled", status="cancelled", risk_gate="blocked", workspace_id=str(network.workspace_id))
        validation.update(pipeline_stage="terminal", status="cancelled", failure_reason="evaluator_unavailable",
                          terminal_event_type="simulation.cancelled")

        record = await self._repo.create(
            simulation_id=uuid.UUID(str(handoff["simulation_id"])),
            parent_simulation_id=None,
            network_id=network.network_id,
            workspace_id=network.workspace_id,
            scenario_id=uuid.UUID(str(handoff["scenario_id"])),
            scenario_name=str(handoff.get("scenario_name", "")).strip() or "scenario",
            state=str(handoff.get("state", "queued")),
            status=str(handoff.get("status", "queued")),
            risk_gate=str(handoff.get("risk_gate", "required")),
            validation=validation,
            run_output=_unavailable_metrics(),
            model_versions={},
            audit_provenance={
                "correlation_id": handoff.get("correlation_id"),
                **({"request_id": handoff["request_id"]} if handoff.get("request_id") else {}),
                "requested_by_user_id": validation.get("requested_by_user_id"),
                "policy_reference": validation.get("policy_reference"),
            },
            queue_status="pending",
            stream_entry_id=None,
            warning=None,
            requested_by_user_id=str(validation.get("requested_by_user_id", requested_by_user_id)),
            requested_at=_coerce_iso_datetime(handoff.get("requested_at")),
        )
        return await self._publish_cancelled(record=record, handoff=handoff)

    async def _commit_and_publish_legacy(
        self,
        *,
        record,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str,
        event_id: str,
        record_outcome: bool = True,
    ) -> tuple[str, str | None, str | None]:
        """ADR-028: commit state plus a durable outbox copy, then publish.

        The same stable event ID is published immediately (best effort). On success
        the outbox copy is marked published; otherwise the simulation worker's outbox
        publisher delivers the stored envelope later. Nothing is published before the
        state it describes is committed.
        """
        outbox = self._repo.enqueue_legacy(record, event_type=event_type, payload=payload,
                                           correlation_id=correlation_id, event_id=event_id)
        await self._db.commit()
        try:
            stream_entry_id = await SimulationEventService(redis=self._redis).publish_lifecycle_event(
                event_type=event_type, payload=payload, correlation_id=correlation_id, event_id=event_id,
            )
            queue_status, warning = "queued", None
            outbox.published_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001 - the committed outbox copy is retried
            logger.warning("simulation_event_publish_deferred", simulation_id=str(payload.get("simulation_id")),
                           event_type=event_type, correlation_id=correlation_id, error=str(exc))
            stream_entry_id, queue_status, warning = None, "deferred", "event_queue_unavailable"
        if record_outcome:
            await self._repo.update_queue_outcome(
                record, queue_status=queue_status, stream_entry_id=stream_entry_id, warning=warning,
            )
        await self._db.commit()
        return queue_status, stream_entry_id, warning

    async def _publish_cancelled(self, *, record, handoff: dict[str, Any]) -> dict[str, Any]:
        """Publish only after the unavailable outcome is durably stored."""
        queue_status, stream_entry_id, warning = await self._commit_and_publish_legacy(
            record=record, event_type="simulation.cancelled",
            payload={**handoff, "run_output": _unavailable_metrics()},
            correlation_id=str(handoff["correlation_id"]),
            event_id=_derive_terminal_event_id(
                simulation_id=uuid.UUID(handoff["simulation_id"]), event_type="simulation.cancelled",
            ),
        )
        return {"handoff": handoff, "queue_status": queue_status, "stream_entry_id": stream_entry_id, "warning": warning}

    async def _resume_simulation(
        self,
        *,
        simulation_id: uuid.UUID,
        correlation_id: str,
        requested_by_user_id: str,
        requested_workspace_id: uuid.UUID | None,
        claim_org_id: uuid.UUID | None,
        network_id: uuid.UUID | None = None,
        scenario_config: ScenarioConfig | None = None,
    ) -> dict[str, Any]:
        simulation = await self._repo.get_by_id(simulation_id)
        if simulation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found.")

        await self._assert_simulation_workspace_access(
            simulation=simulation,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=requested_by_user_id,
            claim_org_id=claim_org_id,
            require_write=True,
        )

        if configured(simulation):
            simulation = await self._repo.lock(simulation_id)
            if network_id is not None and simulation.network_id != network_id:
                raise HTTPException(409, detail="Resume network mismatch.")
            await self._network_svc.assert_network_workspace_access(network_id=simulation.network_id,
                requested_workspace_id=simulation.workspace_id, actor_user_id=requested_by_user_id,
                claim_org_id=claim_org_id, require_write=True)
            if scenario_config is not None:
                from app.modules.simulation.evaluator import canonical_config
                if canonical_config(scenario_config) != simulation.scenario_config:
                    raise HTTPException(409, detail="Resume cannot change input; branch with an override instead.")
            return await transition_modeled(self, record=simulation, state="queued", correlation_id=correlation_id)
        if scenario_config is not None:
            raise HTTPException(409, detail="Legacy resume cannot install new input; create a configured branch.")

        if simulation.state not in {"paused", "queued"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Simulation is not resumable.",
            )

        handoff = ScenarioValidationHandoffService().build_handoff_payload(
            network_id=simulation.network_id,
            scenario_name=simulation.scenario_name,
            validation_checks=(
                simulation.validation.get("required_checks")
                if isinstance(simulation.validation, dict)
                else ["simulation_before_deployment"]
            ),
            correlation_id=correlation_id,
            requested_by_user_id=requested_by_user_id,
        )
        handoff["simulation_id"] = str(simulation.simulation_id)
        handoff["scenario_id"] = str(simulation.scenario_id)
        handoff.update(state="cancelled", status="cancelled", risk_gate="blocked",
                       workspace_id=str(simulation.workspace_id), resumed_from_simulation_id=str(simulation.simulation_id))
        handoff["validation"].update(pipeline_stage="terminal", status="cancelled", failure_reason="evaluator_unavailable",
                                     terminal_event_type="simulation.cancelled")

        await self._repo.update_state(
            simulation,
            state="cancelled",
            status="cancelled",
            risk_gate="blocked",
            validation=handoff["validation"],
            run_output=_unavailable_metrics(),
        )
        return await self._publish_cancelled(record=simulation, handoff=handoff)

    async def pause_simulation(
        self,
        *,
        simulation_id: uuid.UUID,
        correlation_id: str,
        requested_by_user_id: str,
        requested_workspace_id: uuid.UUID | None,
        claim_org_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        simulation = await self._repo.get_by_id(simulation_id)
        if simulation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found.")

        await self._assert_simulation_workspace_access(
            simulation=simulation,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=requested_by_user_id,
            claim_org_id=claim_org_id,
            require_write=True,
        )

        if configured(simulation):
            simulation = await self._repo.lock(simulation_id)
            return await transition_modeled(self, record=simulation, state="paused", correlation_id=correlation_id)

        normalized_correlation_id, correlation_meta = normalize_correlation(correlation_id)
        if simulation.state == "paused":
            return {
                "simulation_id": str(simulation.simulation_id),
                "network_id": str(simulation.network_id),
                "scene_object_id": _DEFAULT_SIMULATION_OBJECT_ID,
                "state": "paused",
                "status": "paused",
                "risk_gate": str(simulation.risk_gate),
                "scenario_id": str(simulation.scenario_id),
                "correlation_id": normalized_correlation_id,
            }

        if simulation.state not in {"queued", "running"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Simulation is not pausable.",
            )

        await self._repo.update_state(
            simulation,
            state="paused",
            status="paused",
            risk_gate="required",
        )

        event_payload = {
            "simulation_id": str(simulation.simulation_id),
            "scenario_id": str(simulation.scenario_id),
            "network_id": str(simulation.network_id),
            "scene_object_id": _DEFAULT_SIMULATION_OBJECT_ID,
            "state": "paused",
            "status": "paused",
            "risk_gate": "required",
            "validation": simulation.validation,
            **correlation_meta,
        }
        # ADR-028: previously published before commit; now committed state first.
        await self._commit_and_publish_legacy(
            record=simulation, event_type="simulation.paused", payload=event_payload,
            correlation_id=normalized_correlation_id,
            event_id=_derive_terminal_event_id(simulation_id=simulation.simulation_id, event_type="simulation.paused"),
            record_outcome=False,
        )
        return {
            "simulation_id": str(simulation.simulation_id),
            "network_id": str(simulation.network_id),
            "scene_object_id": _DEFAULT_SIMULATION_OBJECT_ID,
            "state": "paused",
            "status": "paused",
            "risk_gate": "required",
            "scenario_id": str(simulation.scenario_id),
            "correlation_id": normalized_correlation_id,
        }

    async def branch_simulation(
        self,
        *,
        parent_simulation_id: uuid.UUID,
        scenario_name: str,
        correlation_id: str,
        requested_by_user_id: str,
        requested_workspace_id: uuid.UUID | None,
        claim_org_id: uuid.UUID | None,
        scenario_config: ScenarioConfig | None = None,
    ) -> dict[str, Any]:
        parent = await self._repo.get_by_id(parent_simulation_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found.")

        await self._assert_simulation_workspace_access(
            simulation=parent,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=requested_by_user_id,
            claim_org_id=claim_org_id,
            require_write=True,
        )

        if configured(parent) or scenario_config is not None:
            parent = await self._repo.lock(parent_simulation_id)
            network = await self._network_svc.assert_network_workspace_access(network_id=parent.network_id,
                requested_workspace_id=parent.workspace_id, actor_user_id=requested_by_user_id,
                claim_org_id=claim_org_id, require_write=True)
            try:
                config = scenario_config or ScenarioConfig.model_validate(parent.scenario_config)
            except ValueError as exc:
                raise HTTPException(409, detail="Parent simulation input invalid.") from exc
            return await create_modeled(self, network=network, config=config, scenario_name=scenario_name,
                actor_id=requested_by_user_id, correlation_id=correlation_id, parent=parent)

        normalized_scenario_name = _coerce_non_empty_text(
            scenario_name,
            fallback=f"branch-{str(parent.simulation_id)[:8]}",
        )
        normalized_requested_by = _coerce_requested_by_user_id(requested_by_user_id)
        requested_at = datetime.now(UTC)
        requested_at_iso = requested_at.isoformat()

        required_checks = ["simulation_before_deployment"]
        policy_reference = "ADR-008"
        if isinstance(parent.validation, dict):
            candidate_checks = _normalize_validation_checks(parent.validation.get("required_checks"))
            if candidate_checks:
                required_checks = candidate_checks
            candidate_policy = str(parent.validation.get("policy_reference", "")).strip()
            if candidate_policy:
                policy_reference = candidate_policy

        validation = {
            "pipeline_stage": "branch_draft",
            "required_checks": required_checks,
            "policy_reference": policy_reference,
            "status": "pending",
            "queued_at": requested_at_iso,
            "requested_by_user_id": normalized_requested_by,
        }

        run_output = _unavailable_metrics()
        model_versions = {}
        normalized_correlation_id, correlation_meta = normalize_correlation(correlation_id)
        audit_provenance = {"evaluator_status": "unavailable"}
        audit_provenance["branch_from_simulation_id"] = str(parent.simulation_id)
        audit_provenance["branch_correlation_id"] = normalized_correlation_id
        audit_provenance.update(correlation_meta)

        branch_simulation_id = uuid.uuid4()
        branch_scenario_id = uuid.UUID(
            _derive_scenario_id(str(parent.network_id), normalized_scenario_name)
        )

        branch = await self._repo.create(
            simulation_id=branch_simulation_id,
            parent_simulation_id=parent.simulation_id,
            network_id=parent.network_id,
            workspace_id=parent.workspace_id,
            scenario_id=branch_scenario_id,
            scenario_name=normalized_scenario_name,
            state="draft",
            status="draft",
            risk_gate="required",
            validation=validation,
            run_output=run_output,
            model_versions=model_versions,
            audit_provenance=audit_provenance,
            queue_status="draft",
            stream_entry_id=None,
            warning=None,
            requested_by_user_id=normalized_requested_by,
            requested_at=requested_at,
        )
        event_payload = {
            "simulation_id": str(branch.simulation_id),
            "parent_simulation_id": str(parent.simulation_id),
            "scenario_id": str(branch.scenario_id),
            "network_id": str(branch.network_id),
            "scene_object_id": _DEFAULT_SIMULATION_OBJECT_ID,
            "state": str(branch.state),
            "status": str(branch.status),
            "risk_gate": str(branch.risk_gate),
            "scenario_name": str(branch.scenario_name),
            "validation": validation,
            "requested_at": requested_at_iso,
            "correlation_id": normalized_correlation_id,
        }

        publish_payload = {
            "simulation_id": event_payload["simulation_id"],
            "parent_simulation_id": event_payload["parent_simulation_id"],
            "scenario_id": event_payload["scenario_id"],
            "network_id": event_payload["network_id"],
            "scene_object_id": event_payload["scene_object_id"],
            "state": event_payload["state"],
            "status": event_payload["status"],
            "risk_gate": event_payload["risk_gate"],
            "validation": event_payload["validation"],
            **correlation_meta,
        }

        # ADR-028: previously published before commit; now committed state first.
        await self._commit_and_publish_legacy(
            record=branch, event_type="simulation.branch_created", payload=publish_payload,
            correlation_id=normalized_correlation_id,
            event_id=_derive_terminal_event_id(simulation_id=branch.simulation_id,
                                               event_type="simulation.branch_created"),
            record_outcome=False,
        )
        return event_payload

    async def get_simulation_detail(
        self,
        *,
        simulation_id: uuid.UUID,
        requested_by_user_id: str,
        requested_workspace_id: uuid.UUID | None,
        claim_org_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        simulation = await self._repo.get_by_id(simulation_id)
        if simulation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found.")

        await self._assert_simulation_workspace_access(
            simulation=simulation,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=requested_by_user_id,
            claim_org_id=claim_org_id,
        )

        validation = dict(simulation.validation) if isinstance(simulation.validation, dict) else {}
        modeled = configured(simulation)
        # ADR-028: whole-checkpoint re-verification runs in a worker thread and is
        # cached per (simulation, revision); it never blocks the event loop.
        result = await verified_output_async(simulation) if modeled else None
        if not modeled:
            validation.update(evaluator_status="unavailable", failure_reason="evaluator_unavailable")
        legacy_completed = not modeled and (simulation.state == "completed" or simulation.status == "completed")
        invalid_completed = modeled and simulation.state == "completed" and result is None
        if invalid_completed:
            validation.update(failure_reason="model_evidence_invalid", status="blocked")
        if legacy_completed:
            validation.update(status="cancelled", pipeline_stage="terminal", legacy_baseline_unverified=True)
        execution_policy = None
        if modeled:
            # ADR-028 C18 (additive): whether these limits could ever authorize execution.
            floors = policy_floors()
            execution_policy = {"policy_floors": floors, "limits_respect_policy": limits_respect_policy(
                simulation.scenario_config.get("limits"), floors)}
        return {
            "simulation_id": str(simulation.simulation_id),
            "parent_simulation_id": (
                str(simulation.parent_simulation_id)
                if simulation.parent_simulation_id is not None
                else None
            ),
            "scenario_id": str(simulation.scenario_id),
            "network_id": str(simulation.network_id),
            "workspace_id": str(simulation.workspace_id),
            "scene_object_id": f"simulation:{simulation.simulation_id}" if modeled else _DEFAULT_SIMULATION_OBJECT_ID,
            "state": "cancelled" if legacy_completed else str(simulation.state),
            "status": "cancelled" if legacy_completed else str(simulation.status),
            "risk_gate": "blocked" if legacy_completed or invalid_completed else str(simulation.risk_gate),
            "scenario_name": str(simulation.scenario_name),
            "validation": validation,
            "run_output": result or _unavailable_metrics(),
            "scenario_config": simulation.scenario_config if modeled else None,
            "input_sha256": simulation.input_sha256 if modeled else None,
            "checkpoint_sha256": simulation.checkpoint.get("checkpoint_sha256") if modeled and simulation.checkpoint else None,
            "revision": simulation.revision if modeled else 0,
            "progress": {"tick": simulation.checkpoint.get("state", {}).get("tick", 0),
                         "duration_ticks": simulation.scenario_config.get("duration_ticks", 0)} if modeled and simulation.checkpoint else None,
            "completed_at": simulation.completed_at.isoformat() if modeled and simulation.completed_at else None,
            "evidence_expires_at": simulation.evidence_expires_at.isoformat() if modeled and simulation.evidence_expires_at else None,
            "execution_policy": execution_policy,
            "model_versions": (
                dict(simulation.model_versions)
                if isinstance(simulation.model_versions, dict)
                else {}
            ),
            "audit_provenance": (
                dict(simulation.audit_provenance)
                if isinstance(simulation.audit_provenance, dict)
                else {}
            ),
            "queue_status": str(simulation.queue_status),
            "stream_entry_id": simulation.stream_entry_id,
            "warning": simulation.warning,
            "requested_by_user_id": str(simulation.requested_by_user_id),
            "requested_at": simulation.requested_at.isoformat(),
            "created_at": simulation.created_at.isoformat(),
            "updated_at": simulation.updated_at.isoformat(),
        }

    async def compare_simulations(
        self,
        *,
        simulation_id: uuid.UUID,
        baseline_simulation_id: uuid.UUID,
        requested_by_user_id: str,
        requested_workspace_id: uuid.UUID | None,
        claim_org_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        simulation = await self._repo.get_by_id(simulation_id)
        if simulation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found.")

        baseline = await self._repo.get_by_id(baseline_simulation_id)
        if baseline is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline simulation not found.")

        await self._assert_simulation_workspace_access(
            simulation=simulation,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=requested_by_user_id,
            claim_org_id=claim_org_id,
        )
        await self._assert_simulation_workspace_access(
            simulation=baseline,
            requested_workspace_id=requested_workspace_id,
            actor_user_id=requested_by_user_id,
            claim_org_id=claim_org_id,
        )

        if simulation.network_id != baseline.network_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Simulations belong to different networks.",
            )

        simulation_metrics = _unavailable_metrics()
        baseline_metrics = _unavailable_metrics()
        deltas = _unavailable_metrics()
        current_output = await verified_output_async(simulation)
        baseline_output = await verified_output_async(baseline)
        compatible = bool(current_output and baseline_output and simulation.state == baseline.state == "completed"
            and current_output["workload_sha256"] == baseline_output["workload_sha256"]
            and current_output["elapsed_ms"] == baseline_output["elapsed_ms"])
        if compatible:
            simulation_metrics = {key: current_output[key] for key in deltas}
            baseline_metrics = {key: baseline_output[key] for key in deltas}
            deltas = {key: simulation_metrics[key] - baseline_metrics[key]
                      if simulation_metrics[key] is not None and baseline_metrics[key] is not None else None for key in deltas}

        return {
            "simulation_id": str(simulation.simulation_id),
            "baseline_simulation_id": str(baseline.simulation_id),
            "scenario_id": str(simulation.scenario_id),
            "baseline_scenario_id": str(baseline.scenario_id),
            "network_id": str(simulation.network_id),
            "simulation_metrics": simulation_metrics,
            "baseline_metrics": baseline_metrics,
            "deltas": deltas,
            "compatible": compatible,
            "comparison_reason": None if compatible else "completed_common_modeled_workload_required",
            "simulation_trace": current_output["trace"] if compatible else None,
            "baseline_trace": baseline_output["trace"] if compatible else None,
        }

