"""NANFO Backend — Simulation API router (/api/v1/simulations/*)."""

from __future__ import annotations

import time
import uuid
from typing import Annotated

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
    validation_checks: list[str] = Field(
        default_factory=lambda: ["simulation_before_deployment"],
        min_length=1,
    )


class ScenarioValidationState(BaseModel):
    pipeline_stage: str
    required_checks: list[str]
    policy_reference: str
    status: str
    queued_at: str
    requested_by_user_id: str


class SimulationValidationHandoffResponse(BaseModel):
    simulation_id: str
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
