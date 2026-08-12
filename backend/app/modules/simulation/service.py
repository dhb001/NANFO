"""Simulation services.

Scope:
- Deterministic scenario validation handoff payload shaping
- Internal simulation lifecycle event publication (`simulation.started`)
- Fail-open publication path to preserve API availability
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
from app.modules.network.repository import NetworkRepository
from app.modules.organization.service import WorkspaceService as OrgWorkspaceService
from app.modules.simulation.repository import SimulationRepository

logger = get_logger(__name__)

_DEFAULT_SCENARIO_ID_NAMESPACE = "scenario"
_DEFAULT_SIMULATION_OBJECT_ID = "simulation-state"


def _coerce_non_empty_text(value: Any, fallback: str) -> str:
    text = str(value).strip()
    return text or fallback


def _coerce_uuid_string(value: Any) -> str:
    return str(uuid.UUID(str(value)))


def _coerce_correlation_id(value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return str(uuid.uuid4())


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


def _coerce_metric_value(raw: Any) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _extract_metrics(run_output: Any) -> dict[str, float]:
    payload = run_output if isinstance(run_output, dict) else {}
    return {
        "latency_ms": _coerce_metric_value(payload.get("latency_ms")),
        "loss_pct": _coerce_metric_value(payload.get("loss_pct")),
        "throughput_mbps": _coerce_metric_value(payload.get("throughput_mbps")),
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
        normalized_correlation_id = _coerce_correlation_id(correlation_id)
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
            },
            "requested_at": now_iso,
            "correlation_id": normalized_correlation_id,
        }


class SimulationEventService:
    """Publish simulation lifecycle events for digital twin consumers."""

    def __init__(self, *, redis: aioredis.Redis):
        self._redis = redis

    async def publish_simulation_started_handoff(
        self,
        *,
        handoff_payload: dict[str, Any],
        correlation_id: str,
    ) -> str:
        return await publish_event(
            redis=self._redis,
            event_type="simulation.started",
            source="simulation",
            payload=handoff_payload,
            correlation_id=correlation_id,
        )


class SimulationStartService:
    """Simulation lifecycle service for start/resume/pause/branch flows."""

    def __init__(self, *, db: AsyncSession, redis: aioredis.Redis):
        self._db = db
        self._redis = redis
        self._repo = SimulationRepository(db)
        self._network_repo = NetworkRepository(db)
        self._workspace_svc = OrgWorkspaceService(db=db, redis=redis)

    async def start_simulation(
        self,
        *,
        network_id: uuid.UUID,
        scenario_name: str,
        simulation_id: uuid.UUID | None,
        validation_checks: list[str],
        correlation_id: str,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        if simulation_id is not None:
            return await self._resume_simulation(
                simulation_id=simulation_id,
                correlation_id=correlation_id,
                requested_by_user_id=requested_by_user_id,
            )

        network = await self._network_repo.get_by_id(network_id)
        if network is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

        # C5-safe validation via Organization service boundary.
        await self._workspace_svc.get_active_workspace(network.workspace_id)

        result = await queue_scenario_validation_handoff(
            redis=self._redis,
            network_id=network_id,
            scenario_name=scenario_name,
            validation_checks=validation_checks,
            correlation_id=correlation_id,
            requested_by_user_id=requested_by_user_id,
        )
        handoff = result["handoff"]
        validation = handoff.get("validation") if isinstance(handoff.get("validation"), dict) else {}

        await self._repo.create(
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
            run_output={
                "latency_ms": 0.0,
                "loss_pct": 0.0,
                "throughput_mbps": 0.0,
            },
            model_versions={},
            audit_provenance={
                "correlation_id": handoff.get("correlation_id"),
                "requested_by_user_id": validation.get("requested_by_user_id"),
                "policy_reference": validation.get("policy_reference"),
            },
            queue_status=str(result.get("queue_status", "queued")),
            stream_entry_id=result.get("stream_entry_id"),
            warning=result.get("warning"),
            requested_by_user_id=str(validation.get("requested_by_user_id", requested_by_user_id)),
            requested_at=_coerce_iso_datetime(handoff.get("requested_at")),
        )
        await self._db.commit()
        return result

    async def _resume_simulation(
        self,
        *,
        simulation_id: uuid.UUID,
        correlation_id: str,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        simulation = await self._repo.get_by_id(simulation_id)
        if simulation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found.")

        if simulation.state not in {"paused", "queued"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Simulation is not resumable.",
            )

        await self._workspace_svc.get_active_workspace(simulation.workspace_id)

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

        try:
            stream_entry_id = await SimulationEventService(redis=self._redis).publish_simulation_started_handoff(
                handoff_payload=handoff,
                correlation_id=str(handoff["correlation_id"]),
            )
            queue_status = "queued"
            warning = None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "simulation_resume_queue_failed",
                simulation_id=str(simulation.simulation_id),
                correlation_id=str(handoff["correlation_id"]),
                error=str(exc),
            )
            stream_entry_id = None
            queue_status = "deferred"
            warning = "event_queue_unavailable"

        await self._repo.update_state(
            simulation,
            state="queued",
            status="queued",
            risk_gate="required",
        )
        await self._repo.update_queue_outcome(
            simulation,
            queue_status=queue_status,
            stream_entry_id=stream_entry_id,
            warning=warning,
        )
        await self._db.commit()

        return {
            "handoff": {
                **handoff,
                "resumed_from_simulation_id": str(simulation.simulation_id),
            },
            "queue_status": queue_status,
            "stream_entry_id": stream_entry_id,
            "warning": warning,
        }

    async def pause_simulation(
        self,
        *,
        simulation_id: uuid.UUID,
        correlation_id: str,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        simulation = await self._repo.get_by_id(simulation_id)
        if simulation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found.")

        if simulation.state == "paused":
            return {
                "simulation_id": str(simulation.simulation_id),
                "network_id": str(simulation.network_id),
                "scene_object_id": _DEFAULT_SIMULATION_OBJECT_ID,
                "state": "paused",
                "status": "paused",
                "risk_gate": str(simulation.risk_gate),
                "scenario_id": str(simulation.scenario_id),
                "correlation_id": correlation_id,
            }

        if simulation.state not in {"queued", "running"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Simulation is not pausable.",
            )

        await self._workspace_svc.get_active_workspace(simulation.workspace_id)

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
        }
        try:
            await publish_event(
                redis=self._redis,
                event_type="simulation.paused",
                source="simulation",
                payload=event_payload,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "simulation_pause_event_publish_failed",
                simulation_id=str(simulation.simulation_id),
                correlation_id=correlation_id,
                error=str(exc),
            )

        await self._db.commit()
        return {
            "simulation_id": str(simulation.simulation_id),
            "network_id": str(simulation.network_id),
            "scene_object_id": _DEFAULT_SIMULATION_OBJECT_ID,
            "state": "paused",
            "status": "paused",
            "risk_gate": "required",
            "scenario_id": str(simulation.scenario_id),
            "correlation_id": correlation_id,
        }

    async def branch_simulation(
        self,
        *,
        parent_simulation_id: uuid.UUID,
        scenario_name: str,
        correlation_id: str,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        parent = await self._repo.get_by_id(parent_simulation_id)
        if parent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found.")

        await self._workspace_svc.get_active_workspace(parent.workspace_id)

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

        run_output: dict[str, Any]
        if isinstance(parent.run_output, dict):
            run_output = dict(parent.run_output)
        else:
            run_output = {
                "latency_ms": 0.0,
                "loss_pct": 0.0,
                "throughput_mbps": 0.0,
            }

        model_versions = dict(parent.model_versions) if isinstance(parent.model_versions, dict) else {}
        audit_provenance = dict(parent.audit_provenance) if isinstance(parent.audit_provenance, dict) else {}
        audit_provenance["branch_from_simulation_id"] = str(parent.simulation_id)
        audit_provenance["branch_correlation_id"] = correlation_id

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
            "correlation_id": correlation_id,
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
        }

        try:
            await publish_event(
                redis=self._redis,
                event_type="simulation.branch_created",
                source="simulation",
                payload=publish_payload,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "simulation_branch_event_publish_failed",
                simulation_id=str(branch.simulation_id),
                parent_simulation_id=str(parent.simulation_id),
                correlation_id=correlation_id,
                error=str(exc),
            )

        await self._db.commit()

        return event_payload

    async def get_simulation_detail(
        self,
        *,
        simulation_id: uuid.UUID,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        _ = requested_by_user_id
        simulation = await self._repo.get_by_id(simulation_id)
        if simulation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found.")

        await self._workspace_svc.get_active_workspace(simulation.workspace_id)

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
            "scene_object_id": _DEFAULT_SIMULATION_OBJECT_ID,
            "state": str(simulation.state),
            "status": str(simulation.status),
            "risk_gate": str(simulation.risk_gate),
            "scenario_name": str(simulation.scenario_name),
            "validation": dict(simulation.validation) if isinstance(simulation.validation, dict) else {},
            "run_output": dict(simulation.run_output) if isinstance(simulation.run_output, dict) else {},
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
    ) -> dict[str, Any]:
        _ = requested_by_user_id
        simulation = await self._repo.get_by_id(simulation_id)
        if simulation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found.")

        baseline = await self._repo.get_by_id(baseline_simulation_id)
        if baseline is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline simulation not found.")

        await self._workspace_svc.get_active_workspace(simulation.workspace_id)
        await self._workspace_svc.get_active_workspace(baseline.workspace_id)

        if simulation.network_id != baseline.network_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Simulations belong to different networks.",
            )

        simulation_metrics = _extract_metrics(simulation.run_output)
        baseline_metrics = _extract_metrics(baseline.run_output)
        deltas = {
            "latency_ms": simulation_metrics["latency_ms"] - baseline_metrics["latency_ms"],
            "loss_pct": simulation_metrics["loss_pct"] - baseline_metrics["loss_pct"],
            "throughput_mbps": simulation_metrics["throughput_mbps"] - baseline_metrics["throughput_mbps"],
        }

        return {
            "simulation_id": str(simulation.simulation_id),
            "baseline_simulation_id": str(baseline.simulation_id),
            "scenario_id": str(simulation.scenario_id),
            "baseline_scenario_id": str(baseline.scenario_id),
            "network_id": str(simulation.network_id),
            "simulation_metrics": simulation_metrics,
            "baseline_metrics": baseline_metrics,
            "deltas": deltas,
        }


async def queue_scenario_validation_handoff(
    *,
    redis: aioredis.Redis,
    network_id: Any,
    scenario_name: Any,
    validation_checks: Any,
    correlation_id: Any,
    requested_by_user_id: Any,
) -> dict[str, Any]:
    """Queue a deterministic simulation validation handoff event.

    Publication failures are logged and returned as warning metadata so the caller
    can preserve fail-open behavior without crashing request flow.
    """

    handoff_service = ScenarioValidationHandoffService()
    payload = handoff_service.build_handoff_payload(
        network_id=network_id,
        scenario_name=scenario_name,
        validation_checks=validation_checks,
        correlation_id=correlation_id,
        requested_by_user_id=requested_by_user_id,
    )

    normalized_correlation_id = str(payload["correlation_id"])

    try:
        stream_entry_id = await SimulationEventService(redis=redis).publish_simulation_started_handoff(
            handoff_payload=payload,
            correlation_id=normalized_correlation_id,
        )
        logger.info(
            "simulation_validation_handoff_queued",
            simulation_id=payload["simulation_id"],
            scenario_id=payload["scenario_id"],
            network_id=payload["network_id"],
            stream_entry_id=stream_entry_id,
            correlation_id=normalized_correlation_id,
        )
        return {
            "handoff": payload,
            "queue_status": "queued",
            "stream_entry_id": stream_entry_id,
            "warning": None,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "simulation_validation_handoff_queue_failed",
            simulation_id=payload["simulation_id"],
            scenario_id=payload["scenario_id"],
            network_id=payload["network_id"],
            correlation_id=normalized_correlation_id,
            error=str(exc),
        )
        return {
            "handoff": payload,
            "queue_status": "deferred",
            "stream_entry_id": None,
            "warning": "event_queue_unavailable",
        }
