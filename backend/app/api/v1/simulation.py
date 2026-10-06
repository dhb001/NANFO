"""NANFO Backend — Simulation API router (/api/v1/simulations/*)."""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Any, Literal

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    enforce_workspace_scope,
    get_claim_org_scope,
    get_claim_workspace_scope,
    get_db,
    get_redis,
    get_request_meta,
    require_permissions,
)
from app.core.pagination import PageNumber
from app.core.responses import APIResponse, success_response
from app.db.postgres import AsyncSession
from app.modules.simulation.schemas import (
    ModeledOutput,
    ScenarioConfig,
    SimulationTrace,
    UnavailableOutput,
)
from app.modules.simulation.service import SimulationStartService
from app.modules.simulation.history import SimulationHistoryPage, SimulationHistoryService

router = APIRouter(prefix="/api/v1/simulations", tags=["Simulation"])


class StartSimulationRequest(BaseModel):
    network_id: uuid.UUID
    scenario_name: str = Field(min_length=1, max_length=120)
    simulation_id: uuid.UUID | None = None
    scenario_config: ScenarioConfig | None = None
    validation_checks: list[str] = Field(
        default_factory=lambda: ["simulation_before_deployment"],
        min_length=1,
    )


class PauseSimulationRequest(BaseModel):
    simulation_id: uuid.UUID


class BranchSimulationRequest(BaseModel):
    parent_simulation_id: uuid.UUID
    scenario_name: str = Field(min_length=1, max_length=120)
    scenario_config: ScenarioConfig | None = None


class ScenarioValidationState(BaseModel):
    pipeline_stage: str
    required_checks: list[str]
    policy_reference: str
    status: str
    queued_at: str
    requested_by_user_id: str
    evaluator_status: str = "unavailable"
    failure_reason: str | None = None
    source: Literal["operator_configured_model", "unavailable"] = "unavailable"
    physical_safety_authorized: Literal[False] = False


class SimulationValidationHandoffResponse(BaseModel):
    simulation_id: str
    resumed_from_simulation_id: str | None = None
    scenario_id: str
    network_id: str
    scene_object_id: str
    state: str
    status: str
    risk_gate: str
    scenario_name: str
    validation: ScenarioValidationState
    requested_at: str
    correlation_id: str
    queue_status: str
    stream_entry_id: str | None
    warning: str | None


class PauseSimulationResponse(BaseModel):
    simulation_id: str
    network_id: str
    scene_object_id: str
    state: str
    status: str
    risk_gate: str
    scenario_id: str
    correlation_id: str


class BranchSimulationResponse(BaseModel):
    simulation_id: str
    parent_simulation_id: str
    scenario_id: str
    network_id: str
    scene_object_id: str
    state: str
    status: str
    risk_gate: str
    scenario_name: str
    validation: ScenarioValidationState
    requested_at: str
    correlation_id: str


class SimulationDetailResponse(BaseModel):
    simulation_id: str
    parent_simulation_id: str | None
    scenario_id: str
    network_id: str
    workspace_id: str
    scene_object_id: str
    state: str
    status: str
    risk_gate: str
    scenario_name: str
    validation: dict[str, Any]
    run_output: ModeledOutput | UnavailableOutput
    model_versions: dict[str, Any]
    audit_provenance: dict[str, Any]
    queue_status: str
    stream_entry_id: str | None
    warning: str | None
    requested_by_user_id: str
    requested_at: str
    created_at: str
    updated_at: str
    scenario_config: ScenarioConfig | None = None
    input_sha256: str | None = None
    checkpoint_sha256: str | None = None
    revision: int = 0
    progress: dict[str, int] | None = None
    completed_at: str | None = None
    evidence_expires_at: str | None = None
    # ADR-028 C18: {policy_floors:{max_loss_pct,max_latency_ms,min_throughput_mbps},
    # limits_respect_policy:bool}; null for unconfigured runs.
    execution_policy: dict[str, Any] | None = None


class SimulationMetricsSnapshot(BaseModel):
    latency_ms: float | None
    loss_pct: float | None
    throughput_mbps: float | None


class SimulationCompareResponse(BaseModel):
    simulation_id: str
    baseline_simulation_id: str
    scenario_id: str
    baseline_scenario_id: str
    network_id: str
    simulation_metrics: SimulationMetricsSnapshot
    baseline_metrics: SimulationMetricsSnapshot
    deltas: SimulationMetricsSnapshot
    compatible: bool = False
    comparison_reason: str | None = None
    simulation_trace: list[SimulationTrace] | None = None
    baseline_trace: list[SimulationTrace] | None = None


@router.post("/start", response_model=APIResponse[SimulationValidationHandoffResponse], status_code=status.HTTP_202_ACCEPTED)
async def start_simulation(
    req: StartSimulationRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = get_claim_workspace_scope(claims=claims)
    claim_org_id = get_claim_org_scope(claims=claims)
    result = await SimulationStartService(db=db, redis=redis).start_simulation(
        network_id=req.network_id,
        scenario_name=req.scenario_name,
        simulation_id=req.simulation_id,
        scenario_config=req.scenario_config,
        validation_checks=req.validation_checks,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=claim_org_id,
    )

    handoff_data = {
        **result["handoff"],
        "queue_status": result["queue_status"],
        "stream_entry_id": result["stream_entry_id"],
        "warning": result["warning"],
    }
    payload = SimulationValidationHandoffResponse.model_validate(handoff_data)
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.post("/pause", response_model=APIResponse[PauseSimulationResponse], status_code=status.HTTP_200_OK)
async def pause_simulation(
    req: PauseSimulationRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = get_claim_workspace_scope(claims=claims)
    claim_org_id = get_claim_org_scope(claims=claims)
    result = await SimulationStartService(db=db, redis=redis).pause_simulation(
        simulation_id=req.simulation_id,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=claim_org_id,
    )
    payload = PauseSimulationResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.post("/branch", response_model=APIResponse[BranchSimulationResponse], status_code=status.HTTP_201_CREATED)
async def branch_simulation(
    req: BranchSimulationRequest,
    claims: Annotated[TokenClaims, Depends(require_permissions("write:config"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = get_claim_workspace_scope(claims=claims)
    claim_org_id = get_claim_org_scope(claims=claims)
    result = await SimulationStartService(db=db, redis=redis).branch_simulation(
        parent_simulation_id=req.parent_simulation_id,
        scenario_config=req.scenario_config,
        scenario_name=req.scenario_name,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=claim_org_id,
    )
    payload = BranchSimulationResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.get("", response_model=APIResponse[SimulationHistoryPage])
async def list_simulations(
    workspace_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
    network_id: uuid.UUID | None = None,
    page: PageNumber = 1,
    page_size: int = Query(20, ge=1, le=200),
):
    started = time.monotonic()
    workspace_id = enforce_workspace_scope(claims=claims, workspace_id=workspace_id)
    result = await SimulationHistoryService(db=db, redis=redis).list_page(
        workspace_id=workspace_id, network_id=network_id, user_id=claims.user_id,
        claim_org_id=get_claim_org_scope(claims=claims), page=page, page_size=page_size,
    )
    return success_response(result, meta.request_id, started, meta.timestamp)


@router.get("/{simulation_id}", response_model=APIResponse[SimulationDetailResponse], status_code=status.HTTP_200_OK)
async def get_simulation_detail(
    simulation_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = get_claim_workspace_scope(claims=claims)
    claim_org_id = get_claim_org_scope(claims=claims)
    result = await SimulationStartService(db=db, redis=redis).get_simulation_detail(
        simulation_id=simulation_id,
        requested_by_user_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=claim_org_id,
    )
    payload = SimulationDetailResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.get(
    "/{simulation_id}/compare/{baseline_id}",
    response_model=APIResponse[SimulationCompareResponse],
    status_code=status.HTTP_200_OK,
)
async def compare_simulations(
    simulation_id: uuid.UUID,
    baseline_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(require_permissions("read:topology"))],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    requested_workspace_id = get_claim_workspace_scope(claims=claims)
    claim_org_id = get_claim_org_scope(claims=claims)
    result = await SimulationStartService(db=db, redis=redis).compare_simulations(
        simulation_id=simulation_id,
        baseline_simulation_id=baseline_id,
        requested_by_user_id=claims.user_id,
        requested_workspace_id=requested_workspace_id,
        claim_org_id=claim_org_id,
    )
    payload = SimulationCompareResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)
