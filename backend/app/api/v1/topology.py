"""NANFO Backend — Topology API router (/api/v1/topology/*).

Implements:
- GET /api/v1/topology/graph
- GET /api/v1/topology/nodes/{device_id}
- GET /api/v1/topology/device/{device_id}/neighbors
- GET /api/v1/topology/impact/{device_id}
- POST /api/v1/topology/reconcile
"""

import time
import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    get_current_user,
    get_db,
    get_redis,
    get_request_meta,
)
from app.core.responses import ErrorDetail, ResponseMeta
from app.db.neo4j import get_neo4j_driver
from app.modules.network.schemas import (
    TopologyDeviceNeighboursResponse,
    TopologyGraphResponse,
    TopologyImpactResponse,
)
from app.modules.network.topology import TopologyQueryService

router = APIRouter(prefix="/api/v1/topology", tags=["Topology"])


class TopologyGraphMeta(ResponseMeta):
    next_cursor: str | None = None


class TopologyGraphAPIResponse(BaseModel):
    success: bool
    data: TopologyGraphResponse | None
    meta: TopologyGraphMeta
    errors: ErrorDetail | None


class TopologyNeighbourNode(BaseModel):
    device_id: str
    hostname: str
    device_type: str
    status: str
    spatial_ref_id: str | None = None
    edge_type: str
    direction: str


class TopologyPrimaryNode(BaseModel):
    device_id: str
    hostname: str
    device_type: str
    status: str
    spatial_ref_id: str | None = None


class TopologyNodeWithNeighbours(BaseModel):
    node: TopologyPrimaryNode
    neighbours: list[TopologyNeighbourNode]


class TopologyNodeAPIResponse(BaseModel):
    success: bool
    data: TopologyNodeWithNeighbours | None
    meta: ResponseMeta
    errors: ErrorDetail | None


class TopologyNeighboursAPIResponse(BaseModel):
    success: bool
    data: TopologyDeviceNeighboursResponse | None
    meta: ResponseMeta
    errors: ErrorDetail | None


class TopologyImpactAPIResponse(BaseModel):
    success: bool
    data: TopologyImpactResponse | None
    meta: ResponseMeta
    errors: ErrorDetail | None


class TopologyReconcileRequest(BaseModel):
    network_id: uuid.UUID


class TopologyReconcileResult(BaseModel):
    reconcile_id: str
    network_id: str
    status: str
    checked_nodes: int
    checked_edges: int
    missing_workspace_nodes: int
    workspace_backfilled_nodes: int
    warning: str | None = None


class TopologyReconcileAPIResponse(BaseModel):
    success: bool
    data: TopologyReconcileResult | None
    meta: ResponseMeta
    errors: ErrorDetail | None


@router.get("/graph", response_model=TopologyGraphAPIResponse, status_code=status.HTTP_200_OK)
async def get_topology_graph(
    network_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    depth: int = 2,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
):
    """Return device nodes and edges for the given network from Neo4j.

    Eventual consistency note: Neo4j state is updated asynchronously after
    POST /api/v1/networks/{id}/devices via the topology consumer.
    A brief lag is expected and is documented behaviour (design_package risk R5).

    """
    started = time.monotonic()
    driver = get_neo4j_driver()
    svc = TopologyQueryService(driver=driver)
    result, next_cursor = await svc.get_graph(
        network_id=network_id,
        depth=depth,
        limit=limit,
        cursor=cursor,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return TopologyGraphAPIResponse(
        success=True,
        data=result,
        meta=TopologyGraphMeta(
            request_id=meta.request_id,
            timestamp=meta.timestamp,
            execution_time_ms=elapsed_ms,
            next_cursor=next_cursor,
        ),
        errors=None,
    )


@router.get("/nodes/{device_id}", response_model=TopologyNodeAPIResponse, status_code=status.HTTP_200_OK)
async def get_topology_node_with_neighbours(
    device_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    depth: int = Query(default=1, ge=1),
):
    started = time.monotonic()
    driver = get_neo4j_driver()
    svc = TopologyQueryService(driver=driver)
    result = await svc.get_node_with_neighbours(device_id=device_id, depth=depth)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology node not found.")

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return TopologyNodeAPIResponse(
        success=True,
        data=TopologyNodeWithNeighbours.model_validate(result),
        meta=ResponseMeta(
            request_id=meta.request_id,
            timestamp=meta.timestamp,
            execution_time_ms=elapsed_ms,
        ),
        errors=None,
    )


@router.get("/device/{device_id}/neighbors", response_model=TopologyNeighboursAPIResponse, status_code=status.HTTP_200_OK)
async def get_topology_device_neighbours(
    device_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    depth: int = Query(default=1, ge=1, le=6),
    limit: int = Query(default=200, ge=1, le=1000),
):
    started = time.monotonic()
    driver = get_neo4j_driver()
    svc = TopologyQueryService(driver=driver)
    result = await svc.get_device_neighbours(device_id=device_id, depth=depth, limit=limit)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology node not found.")

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return TopologyNeighboursAPIResponse(
        success=True,
        data=result,
        meta=ResponseMeta(
            request_id=meta.request_id,
            timestamp=meta.timestamp,
            execution_time_ms=elapsed_ms,
        ),
        errors=None,
    )


@router.get("/impact/{device_id}", response_model=TopologyImpactAPIResponse, status_code=status.HTTP_200_OK)
async def get_topology_impact(
    device_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    max_hops: int = Query(default=3, ge=1, le=8),
    limit: int = Query(default=500, ge=1, le=2000),
):
    started = time.monotonic()
    driver = get_neo4j_driver()
    svc = TopologyQueryService(driver=driver)
    result = await svc.get_impact_analysis(device_id=device_id, max_hops=max_hops, limit=limit)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topology node not found.")

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return TopologyImpactAPIResponse(
        success=True,
        data=result,
        meta=ResponseMeta(
            request_id=meta.request_id,
            timestamp=meta.timestamp,
            execution_time_ms=elapsed_ms,
        ),
        errors=None,
    )


@router.post("/reconcile", response_model=TopologyReconcileAPIResponse, status_code=status.HTTP_200_OK)
async def reconcile_topology(
    req: TopologyReconcileRequest,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    started = time.monotonic()
    driver = get_neo4j_driver()
    svc = TopologyQueryService(driver=driver)
    result = await svc.reconcile_network(
        network_id=req.network_id,
        db=db,
        redis=redis,
        actor_id=claims.user_id,
        correlation_id=meta.request_id,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found.")

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return TopologyReconcileAPIResponse(
        success=True,
        data=TopologyReconcileResult.model_validate(result),
        meta=ResponseMeta(
            request_id=meta.request_id,
            timestamp=meta.timestamp,
            execution_time_ms=elapsed_ms,
        ),
        errors=None,
    )
