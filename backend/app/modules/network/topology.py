"""NANFO Backend — Topology Query Service.

Reads Neo4j device nodes and edges to serve GET /api/v1/topology/graph.
Ownership: Network module (Topology.md §4: "Entity ownership: network module").

C6 constraint: /neighbors, /impact, /reconcile endpoints are deferred to M4 full pass.
Only GET /api/v1/topology/graph is implemented in Vertical Slice 1.
"""

from __future__ import annotations

import uuid

from neo4j import AsyncDriver

from app.core.logging import get_logger
from app.modules.network.schemas import TopologyEdge, TopologyGraphResponse, TopologyNode

logger = get_logger(__name__)


class TopologyQueryService:

    def __init__(self, driver: AsyncDriver):
        self._driver = driver

    async def get_graph(self, network_id: uuid.UUID, depth: int = 2) -> TopologyGraphResponse:
        """Return all device nodes and edges for the given network.

        Deferred edges (DEPENDS_ON, LOCATED_IN, POWERED_BY) are returned when present
        but are not created in Slice 1 (no device-link endpoint yet).
        Only CONNECTED_TO edges are wired in this slice (Topology.md §4).
        """
        query = """
        MATCH (d:Device {network_id: $network_id})
        OPTIONAL MATCH (d)-[e:CONNECTED_TO]->(t:Device {network_id: $network_id})
        RETURN
            collect(DISTINCT {
                device_id: d.device_id,
                hostname: d.hostname,
                device_type: d.device_type,
                status: d.status
            }) AS nodes,
            collect(DISTINCT CASE WHEN e IS NOT NULL THEN {
                source_id: d.device_id,
                target_id: t.device_id,
                edge_type: 'connected_to',
                metadata: {}
            } END) AS edges
        """
        async with self._driver.session() as session:
            result = await session.run(query, network_id=str(network_id))
            record = await result.single()

        if record is None:
            return TopologyGraphResponse(nodes=[], edges=[])

        raw_nodes = record["nodes"] or []
        raw_edges = [e for e in (record["edges"] or []) if e is not None]

        nodes = [
            TopologyNode(
                device_id=n["device_id"],
                hostname=n["hostname"],
                device_type=n["device_type"],
                status=n["status"],
            )
            for n in raw_nodes
        ]
        edges = [
            TopologyEdge(
                source_id=e["source_id"],
                target_id=e["target_id"],
                edge_type=e["edge_type"],
                metadata=e["metadata"],
            )
            for e in raw_edges
        ]
        return TopologyGraphResponse(nodes=nodes, edges=edges)

    async def create_device_node(self, device_id: str, network_id: str, hostname: str, device_type: str, status: str = "active") -> None:
        """Create or merge a Device node in Neo4j. Called by TopologyConsumer on network.device.added."""
        query = """
        MERGE (d:Device {device_id: $device_id})
        SET d.network_id = $network_id,
            d.hostname = $hostname,
            d.device_type = $device_type,
            d.status = $status
        """
        async with self._driver.session() as session:
            await session.run(
                query,
                device_id=device_id,
                network_id=network_id,
                hostname=hostname,
                device_type=device_type,
                status=status,
            )
        logger.info("topology_node_created", device_id=device_id, network_id=network_id)
