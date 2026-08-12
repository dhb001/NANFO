"""NANFO Backend — Topology Query Service.

Reads Neo4j device nodes and edges to serve GET /api/v1/topology/graph.
Ownership: Network module (Topology.md §4: "Entity ownership: network module").

C6 constraint: /neighbors, /impact, /reconcile endpoints are deferred to M4 full pass.
Only GET /api/v1/topology/graph is implemented in Vertical Slice 1.
"""

from __future__ import annotations

import uuid

from neo4j import AsyncDriver
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.network.repository import NetworkRepository
from app.modules.network.schemas import (
    TopologyEdge,
    TopologyGraphResponse,
    TopologyNode,
)

logger = get_logger(__name__)


class TopologyQueryService:

    def __init__(self, driver: AsyncDriver):
        self._driver = driver

    async def get_graph(
        self,
        network_id: uuid.UUID,
        depth: int = 2,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[TopologyGraphResponse, str | None]:
        """Return a deterministic, paginated topology graph page.

        Pagination is node-based and ordered by `device_id` ascending.
        `next_cursor` is the last device_id in the current page when more rows exist.
        """
        node_query = """
        MATCH (d:Device {network_id: $network_id})
        WHERE $cursor IS NULL OR d.device_id > $cursor
        RETURN d.device_id AS device_id,
               d.hostname AS hostname,
               d.device_type AS device_type,
               d.status AS status,
               d.spatial_ref_id AS spatial_ref_id
        ORDER BY d.device_id ASC
        LIMIT $fetch_limit
        """

        edge_query = """
        MATCH (s:Device {network_id: $network_id})-[e:CONNECTED_TO]->(t:Device {network_id: $network_id})
        WHERE s.device_id IN $device_ids AND t.device_id IN $device_ids
        RETURN DISTINCT
            s.device_id AS source_id,
            t.device_id AS target_id
        ORDER BY source_id ASC, target_id ASC
        """

        fetch_limit = limit + 1
        async with self._driver.session() as session:
            node_result = await session.run(
                node_query,
                network_id=str(network_id),
                cursor=cursor,
                fetch_limit=fetch_limit,
            )
            raw_nodes = await node_result.data()

            page_rows = raw_nodes[:limit]
            has_more = len(raw_nodes) > limit
            next_cursor = page_rows[-1]["device_id"] if has_more and page_rows else None

            if not page_rows:
                return TopologyGraphResponse(nodes=[], edges=[]), None

            device_ids = [row["device_id"] for row in page_rows]
            edge_result = await session.run(
                edge_query,
                network_id=str(network_id),
                device_ids=device_ids,
            )
            raw_edges = await edge_result.data()

        nodes = [
            TopologyNode(
                device_id=n["device_id"],
                hostname=n["hostname"],
                device_type=n["device_type"],
                status=n["status"],
                spatial_ref_id=n.get("spatial_ref_id"),
            )
            for n in page_rows
        ]
        edges = [
            TopologyEdge(
                source_id=e["source_id"],
                target_id=e["target_id"],
                edge_type="connected_to",
                metadata={},
            )
            for e in raw_edges
        ]
        return TopologyGraphResponse(nodes=nodes, edges=edges), next_cursor

    async def get_node_with_neighbours(
        self,
        device_id: uuid.UUID,
        depth: int = 1,
    ) -> dict | None:
        """Return one device node with deterministic direct neighbours.

        VS2 scope is direct (1-hop) neighbours with edge metadata.
        """
        if depth != 1:
            depth = 1

        query = """
        MATCH (d:Device {device_id: $device_id})
        OPTIONAL MATCH (d)-[:CONNECTED_TO]->(n_out:Device)
        WHERE n_out.device_id <> d.device_id
        WITH d, collect(DISTINCT {
            device_id: n_out.device_id,
            hostname: n_out.hostname,
            device_type: n_out.device_type,
            status: n_out.status,
            spatial_ref_id: n_out.spatial_ref_id,
            edge_type: 'connected_to',
            direction: 'outbound'
        }) AS outbound
        OPTIONAL MATCH (n_in:Device)-[:CONNECTED_TO]->(d)
        WHERE n_in.device_id <> d.device_id
        WITH d, outbound + collect(DISTINCT {
            device_id: n_in.device_id,
            hostname: n_in.hostname,
            device_type: n_in.device_type,
            status: n_in.status,
            spatial_ref_id: n_in.spatial_ref_id,
            edge_type: 'connected_to',
            direction: 'inbound'
        }) AS neighbours
        RETURN {
            device_id: d.device_id,
            hostname: d.hostname,
            device_type: d.device_type,
            status: d.status,
            spatial_ref_id: d.spatial_ref_id
        } AS node,
        [n IN neighbours WHERE n.device_id IS NOT NULL] AS neighbours
        """

        async with self._driver.session() as session:
            result = await session.run(query, device_id=str(device_id))
            record = await result.single()

        if record is None or record["node"] is None:
            return None

        raw_neighbours = record["neighbours"] or []
        ordered_neighbours = sorted(
            raw_neighbours,
            key=lambda item: (item["device_id"], item["direction"], item["edge_type"]),
        )
        return {
            "node": record["node"],
            "neighbours": ordered_neighbours,
        }

    async def create_device_node(
        self,
        device_id: str,
        network_id: str,
        workspace_id: str,
        hostname: str,
        device_type: str,
        spatial_ref_id: str | None = None,
        status: str = "active",
    ) -> None:
        """Create or merge a Device node in Neo4j.

        Topology.md §6 requires `workspace_id` on all Device nodes.
        """
        query = """
        MERGE (d:Device {device_id: $device_id})
        SET d.network_id = $network_id,
            d.workspace_id = $workspace_id,
            d.hostname = $hostname,
            d.device_type = $device_type,
            d.spatial_ref_id = $spatial_ref_id,
            d.status = $status
        """
        async with self._driver.session() as session:
            await session.run(
                query,
                device_id=device_id,
                network_id=network_id,
                workspace_id=workspace_id,
                hostname=hostname,
                device_type=device_type,
                spatial_ref_id=spatial_ref_id,
                status=status,
            )
        logger.info("topology_node_created", device_id=device_id, network_id=network_id)

    async def backfill_missing_workspace_ids(self, db: AsyncSession, correlation_id: str = "") -> int:
        """Fill missing Device.workspace_id in Neo4j using Network module ownership data.

        Idempotent by design: only nodes with missing/empty workspace_id are updated.
        Safe to rerun: nodes already carrying workspace_id are untouched.
        """
        missing_query = """
        MATCH (d:Device)
        WHERE d.workspace_id IS NULL OR d.workspace_id = ''
        RETURN DISTINCT d.network_id AS network_id
        """
        async with self._driver.session() as session:
            result = await session.run(missing_query)
            records = await result.data()

        network_ids = [record.get("network_id") for record in records if record.get("network_id")]
        if not network_ids:
            logger.info(
                "topology_workspace_backfill_complete",
                correlation_id=correlation_id,
                missing_networks=0,
                updated_nodes=0,
            )
            return 0

        workspace_by_network = await NetworkRepository(db).get_workspace_ids_for_network_ids(network_ids)
        if not workspace_by_network:
            logger.warning(
                "topology_workspace_backfill_no_workspace_mapping",
                correlation_id=correlation_id,
                missing_networks=len(network_ids),
            )
            return 0

        updated_total = 0
        update_query = """
        MATCH (d:Device {network_id: $network_id})
        WHERE d.workspace_id IS NULL OR d.workspace_id = ''
        SET d.workspace_id = $workspace_id
        RETURN count(d) AS updated
        """
        async with self._driver.session() as session:
            for network_id, workspace_id in workspace_by_network.items():
                update_result = await session.run(
                    update_query,
                    network_id=network_id,
                    workspace_id=workspace_id,
                )
                record = await update_result.single()
                updated = int(record["updated"]) if record and "updated" in record else 0
                updated_total += updated

        logger.info(
            "topology_workspace_backfill_complete",
            correlation_id=correlation_id,
            missing_networks=len(network_ids),
            mapped_networks=len(workspace_by_network),
            updated_nodes=updated_total,
        )
        return updated_total
