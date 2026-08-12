"""NANFO Backend — Simulation API router (/api/v1/simulations/*)."""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    get_current_user,
    get_db,
    get_redis,
    get_request_meta,
)
from app.core.responses import APIResponse, success_response
from app.db.postgres import AsyncSession
from app.modules.simulation.service import SimulationStartService

router = APIRouter(prefix="/api/v1/simulations", tags=["Simulation"])


class StartSimulationRequest(BaseModel):
    network_id: uuid.UUID
    scenario_name: str = Field(min_length=1, max_length=120)
    simulation_id: uuid.UUID | None = None
    validation_checks: list[str] = Field(
        default_factory=lambda: ["simulation_before_deployment"],
        min_length=1,
    )


class PauseSimulationRequest(BaseModel):
    simulation_id: uuid.UUID


class BranchSimulationRequest(BaseModel):
    parent_simulation_id: uuid.UUID
    scenario_name: str = Field(min_length=1, max_length=120)


class ScenarioValidationState(BaseModel):
    pipeline_stage: str
    required_checks: list[str]
    policy_reference: str
    status: str
    queued_at: str
    requested_by_user_id: str


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
    run_output: dict[str, Any]
    model_versions: dict[str, Any]
    audit_provenance: dict[str, Any]
    queue_status: str
    stream_entry_id: str | None
    warning: str | None
    requested_by_user_id: str
    requested_at: str
    created_at: str
    updated_at: str


class SimulationMetricsSnapshot(BaseModel):
    latency_ms: float
    loss_pct: float
    throughput_mbps: float


class SimulationCompareResponse(BaseModel):
    simulation_id: str
    baseline_simulation_id: str
    scenario_id: str
    baseline_scenario_id: str
    network_id: str
    simulation_metrics: SimulationMetricsSnapshot
    baseline_metrics: SimulationMetricsSnapshot
    deltas: SimulationMetricsSnapshot


@router.post("/start", response_model=APIResponse[SimulationValidationHandoffResponse], status_code=status.HTTP_202_ACCEPTED)
async def start_simulation(
    req: StartSimulationRequest,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    result = await SimulationStartService(db=db, redis=redis).start_simulation(
        network_id=req.network_id,
        scenario_name=req.scenario_name,
        simulation_id=req.simulation_id,
        validation_checks=req.validation_checks,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
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
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    result = await SimulationStartService(db=db, redis=redis).pause_simulation(
        simulation_id=req.simulation_id,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
    )
    payload = PauseSimulationResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.post("/branch", response_model=APIResponse[BranchSimulationResponse], status_code=status.HTTP_201_CREATED)
async def branch_simulation(
    req: BranchSimulationRequest,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    result = await SimulationStartService(db=db, redis=redis).branch_simulation(
        parent_simulation_id=req.parent_simulation_id,
        scenario_name=req.scenario_name,
        correlation_id=meta.request_id,
        requested_by_user_id=claims.user_id,
    )
    payload = BranchSimulationResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)


@router.get("/{simulation_id}", response_model=APIResponse[SimulationDetailResponse], status_code=status.HTTP_200_OK)
async def get_simulation_detail(
    simulation_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    result = await SimulationStartService(db=db, redis=redis).get_simulation_detail(
        simulation_id=simulation_id,
        requested_by_user_id=claims.user_id,
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
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    result = await SimulationStartService(db=db, redis=redis).compare_simulations(
        simulation_id=simulation_id,
        baseline_simulation_id=baseline_id,
        requested_by_user_id=claims.user_id,
    )
    payload = SimulationCompareResponse.model_validate(result)
    return success_response(payload, meta.request_id, started, meta.timestamp)
