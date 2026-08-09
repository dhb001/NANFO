"""NANFO Backend — Topology API router (/api/v1/topology/*).

Implements only GET /api/v1/topology/graph (Vertical Slice 1 scope).
C6: /neighbors, /impact, /reconcile are deferred to M4 full Topology pass.
"""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    get_current_user,
    get_request_meta,
)
from app.core.responses import ErrorDetail, ResponseMeta
from app.db.neo4j import get_neo4j_driver
from app.modules.network.schemas import TopologyGraphResponse
from app.modules.network.topology import TopologyQueryService

router = APIRouter(prefix="/api/v1/topology", tags=["Topology"])


class TopologyGraphMeta(ResponseMeta):
    next_cursor: str | None = None


class TopologyGraphAPIResponse(BaseModel):
    success: bool
    data: TopologyGraphResponse | None
    meta: TopologyGraphMeta
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

    Deferred endpoints (C6): /neighbors, /impact, /reconcile are NOT implemented here.
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
