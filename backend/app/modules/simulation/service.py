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
    """Start simulation handoff flow with C5-safe validation and persistence."""

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
        validation_checks: list[str],
        correlation_id: str,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
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
