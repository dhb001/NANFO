"""NANFO Backend — Topology API router (/api/v1/topology/*).

Implements only GET /api/v1/topology/graph (Vertical Slice 1 scope).
C6: /neighbors, /impact, /reconcile are deferred to M4 full Topology pass.
"""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    RequestMeta,
    TokenClaims,
    get_current_user,
    get_db,
    get_redis,
    get_request_meta,
)
from app.core.responses import APIResponse, success_response
from app.db.neo4j import get_neo4j_driver
from app.modules.network.schemas import TopologyGraphResponse
from app.modules.network.topology import TopologyQueryService

router = APIRouter(prefix="/api/v1/topology", tags=["Topology"])


@router.get("/graph", response_model=APIResponse[TopologyGraphResponse], status_code=status.HTTP_200_OK)
async def get_topology_graph(
    network_id: uuid.UUID,
    claims: Annotated[TokenClaims, Depends(get_current_user)],
    meta: Annotated[RequestMeta, Depends(get_request_meta)],
    depth: int = 2,
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
    result = await svc.get_graph(network_id=network_id, depth=depth)
    return success_response(result, meta.request_id, started, meta.timestamp)
