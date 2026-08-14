"""NANFO Backend — Topology Query Service.

Reads Neo4j device nodes and edges to serve GET /api/v1/topology/graph.
Ownership: Network module (Topology.md §4: "Entity ownership: network module").

VS10 extends this service with:
- /topology/device/{id}/neighbors deterministic neighbour queries
- /topology/impact/{id} reachable dependency analysis
- /topology/reconcile audit-event-backed reconciliation baseline
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis
from neo4j import AsyncDriver
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.network.repository import NetworkRepository
from app.modules.network.schemas import (
    TopologyDeviceNeighboursResponse,
    TopologyEdge,
    TopologyGraphResponse,
    TopologyImpactNode,
    TopologyImpactResponse,
    TopologyNeighbourEdge,
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

    async def reconcile_network(
        self,
        *,
        network_id: uuid.UUID,
        db: AsyncSession,
        redis: aioredis.Redis,
        actor_id: str,
        correlation_id: str,
    ) -> dict | None:
        """Run deterministic topology reconciliation for one network.

        Baseline behavior:
        - validates network ownership context exists,
        - counts nodes/edges for the target network,
        - backfills missing workspace_id properties where possible,
        - emits auditable lifecycle events.
        """
        network_repo = NetworkRepository(db)
        workspace_map = await network_repo.get_workspace_ids_for_network_ids([str(network_id)])
        workspace_id = workspace_map.get(str(network_id))
        if workspace_id is None:
            return None

        reconcile_id = str(uuid.uuid4())
        warning: str | None = None
        requested_payload = {
            "reconcile_id": reconcile_id,
            "network_id": str(network_id),
            "workspace_id": workspace_id,
            "status": "requested",
            "actor_id": actor_id,
            "requested_at": datetime.now(UTC).isoformat(),
        }

        try:
            await publish_event(
                redis=redis,
                event_type="network.topology.reconcile_requested",
                source="network",
                payload=requested_payload,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            warning = "event_queue_unavailable"
            logger.warning(
                "topology_reconcile_requested_event_publish_failed",
                correlation_id=correlation_id,
                reconcile_id=reconcile_id,
                network_id=str(network_id),
                error=str(exc),
            )

        node_count_query = """
        MATCH (d:Device {network_id: $network_id})
        RETURN count(d) AS node_count
        """
        edge_count_query = """
        MATCH (:Device {network_id: $network_id})-[e:CONNECTED_TO]->(:Device {network_id: $network_id})
        RETURN count(e) AS edge_count
        """
        missing_workspace_count_query = """
        MATCH (d:Device {network_id: $network_id})
        WHERE d.workspace_id IS NULL OR d.workspace_id = ''
        RETURN count(d) AS missing_workspace_nodes
        """
        backfill_workspace_query = """
        MATCH (d:Device {network_id: $network_id})
        WHERE d.workspace_id IS NULL OR d.workspace_id = ''
        SET d.workspace_id = $workspace_id
        RETURN count(d) AS workspace_backfilled_nodes
        """

        try:
            async with self._driver.session() as session:
                node_result = await session.run(node_count_query, network_id=str(network_id))
                node_record = await node_result.single()
                edge_result = await session.run(edge_count_query, network_id=str(network_id))
                edge_record = await edge_result.single()
                missing_result = await session.run(
                    missing_workspace_count_query,
                    network_id=str(network_id),
                )
                missing_record = await missing_result.single()
                backfill_result = await session.run(
                    backfill_workspace_query,
                    network_id=str(network_id),
                    workspace_id=workspace_id,
                )
                backfill_record = await backfill_result.single()
        except Exception as exc:
            failed_payload = {
                "reconcile_id": reconcile_id,
                "network_id": str(network_id),
                "workspace_id": workspace_id,
                "status": "failed",
                "actor_id": actor_id,
                "error": str(exc),
                "failed_at": datetime.now(UTC).isoformat(),
            }
            try:
                await publish_event(
                    redis=redis,
                    event_type="network.topology.reconcile_failed",
                    source="network",
                    payload=failed_payload,
                    correlation_id=correlation_id,
                )
            except Exception as failed_exc:  # noqa: BLE001
                logger.warning(
                    "topology_reconcile_failed_event_publish_failed",
                    correlation_id=correlation_id,
                    reconcile_id=reconcile_id,
                    network_id=str(network_id),
                    error=str(failed_exc),
                )
            raise

        node_count = int(node_record["node_count"]) if node_record and "node_count" in node_record else 0
        edge_count = int(edge_record["edge_count"]) if edge_record and "edge_count" in edge_record else 0
        missing_workspace_nodes = (
            int(missing_record["missing_workspace_nodes"])
            if missing_record and "missing_workspace_nodes" in missing_record
            else 0
        )
        workspace_backfilled_nodes = (
            int(backfill_record["workspace_backfilled_nodes"])
            if backfill_record and "workspace_backfilled_nodes" in backfill_record
            else 0
        )

        completed_payload = {
            "reconcile_id": reconcile_id,
            "network_id": str(network_id),
            "workspace_id": workspace_id,
            "status": "completed",
            "actor_id": actor_id,
            "checked_nodes": node_count,
            "checked_edges": edge_count,
            "missing_workspace_nodes": missing_workspace_nodes,
            "workspace_backfilled_nodes": workspace_backfilled_nodes,
            "warning": warning,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        try:
            await publish_event(
                redis=redis,
                event_type="network.topology.reconcile_completed",
                source="network",
                payload=completed_payload,
                correlation_id=correlation_id,
            )
        except Exception as exc:  # noqa: BLE001
            warning = "event_queue_unavailable"
            logger.warning(
                "topology_reconcile_completed_event_publish_failed",
                correlation_id=correlation_id,
                reconcile_id=reconcile_id,
                network_id=str(network_id),
                error=str(exc),
            )

        return {
            "reconcile_id": reconcile_id,
            "network_id": str(network_id),
            "status": "completed",
            "checked_nodes": node_count,
            "checked_edges": edge_count,
            "missing_workspace_nodes": missing_workspace_nodes,
            "workspace_backfilled_nodes": workspace_backfilled_nodes,
            "warning": warning,
        }

    async def get_device_neighbours(
        self,
        *,
        device_id: uuid.UUID,
        depth: int = 1,
        limit: int = 200,
    ) -> TopologyDeviceNeighboursResponse | None:
        """Return deterministic neighbours for /topology/device/{id}/neighbors.

        Includes relationship metadata and hop depth for each neighbour.
        """
        bounded_depth = max(1, min(depth, 6))

        root_query = """
        MATCH (d:Device {device_id: $device_id})
        RETURN d.device_id AS device_id,
               d.hostname AS hostname,
               d.device_type AS device_type,
               d.status AS status,
               d.spatial_ref_id AS spatial_ref_id
        """

        neighbours_query = """
        MATCH (d:Device {device_id: $device_id})
        CALL {
            WITH d
            MATCH path = (d)-[r:CONNECTED_TO*1..__DEPTH__]-(n:Device)
            WHERE n.device_id <> d.device_id
            WITH n,
                 d,
                 length(path) AS hop_depth,
                 head(relationships(path)) AS first_edge
            RETURN {
                device_id: n.device_id,
                hostname: n.hostname,
                device_type: n.device_type,
                status: n.status,
                spatial_ref_id: n.spatial_ref_id,
                edge_type: toLower(type(first_edge)),
                edge_metadata: properties(first_edge),
                direction: CASE
                    WHEN startNode(first_edge).device_id = d.device_id THEN 'outbound'
                    ELSE 'inbound'
                END,
                hop_depth: hop_depth
            } AS candidate
        }
        WITH candidate.device_id AS device_id, collect(candidate) AS candidates
        WITH device_id, reduce(best = null, item IN candidates |
            CASE
                WHEN best IS NULL THEN item
                WHEN item.hop_depth < best.hop_depth THEN item
                WHEN item.hop_depth = best.hop_depth AND item.direction < best.direction THEN item
                WHEN item.hop_depth = best.hop_depth
                     AND item.direction = best.direction
                     AND item.edge_type < best.edge_type THEN item
                ELSE best
            END
        ) AS selected
        RETURN selected
        ORDER BY selected.device_id ASC,
                 selected.hop_depth ASC,
                 selected.direction ASC,
                 selected.edge_type ASC
        LIMIT $limit
        """
        neighbours_query = neighbours_query.replace("__DEPTH__", str(bounded_depth))

        async with self._driver.session() as session:
            root_result = await session.run(root_query, device_id=str(device_id))
            root_record = await root_result.single()
            if root_record is None:
                return None

            neighbours_result = await session.run(
                neighbours_query,
                device_id=str(device_id),
                limit=limit,
            )
            neighbour_rows = await neighbours_result.data()

        root_node = TopologyNode(
            device_id=root_record["device_id"],
            hostname=root_record["hostname"],
            device_type=root_record["device_type"],
            status=root_record["status"],
            spatial_ref_id=root_record.get("spatial_ref_id"),
        )
        neighbours: list[TopologyNeighbourEdge] = []
        for row in neighbour_rows:
            selected = row.get("selected") if isinstance(row, dict) else None
            if not isinstance(selected, dict):
                continue
            neighbours.append(
                TopologyNeighbourEdge(
                    device_id=str(selected.get("device_id", "")),
                    hostname=str(selected.get("hostname", "")),
                    device_type=str(selected.get("device_type", "")),
                    status=str(selected.get("status", "")),
                    spatial_ref_id=selected.get("spatial_ref_id"),
                    edge_type=str(selected.get("edge_type", "connected_to")) or "connected_to",
                    edge_metadata=selected.get("edge_metadata") if isinstance(selected.get("edge_metadata"), dict) else {},
                    direction=str(selected.get("direction", "outbound")) or "outbound",
                    hop_depth=int(selected.get("hop_depth", 1)),
                )
            )

        return TopologyDeviceNeighboursResponse(
            device=root_node,
            neighbours=neighbours,
            depth=bounded_depth,
            total=len(neighbours),
        )

    async def get_impact_analysis(
        self,
        *,
        device_id: uuid.UUID,
        max_hops: int = 3,
        limit: int = 500,
    ) -> TopologyImpactResponse | None:
        """Return reachable dependency set with hop depth.

        Used by /topology/impact/{id} for VS10 scope.
        """
        bounded_hops = max(1, min(max_hops, 8))

        root_query = """
        MATCH (d:Device {device_id: $device_id})
        RETURN d.device_id AS device_id,
               d.hostname AS hostname,
               d.device_type AS device_type,
               d.status AS status,
               d.spatial_ref_id AS spatial_ref_id
        """

        impact_query = """
        MATCH (d:Device {device_id: $device_id})
        MATCH path = (d)-[:CONNECTED_TO*1..__MAX_HOPS__]-(n:Device)
        WHERE n.device_id <> d.device_id
        WITH n.device_id AS device_id,
             min(length(path)) AS hop_depth,
             collect(n)[0] AS node
        RETURN {
            device_id: device_id,
            hostname: node.hostname,
            device_type: node.device_type,
            status: node.status,
            spatial_ref_id: node.spatial_ref_id,
            hop_depth: hop_depth
        } AS impact
        ORDER BY impact.hop_depth ASC,
                 impact.device_id ASC
        LIMIT $limit
        """
        impact_query = impact_query.replace("__MAX_HOPS__", str(bounded_hops))

        async with self._driver.session() as session:
            root_result = await session.run(root_query, device_id=str(device_id))
            root_record = await root_result.single()
            if root_record is None:
                return None

            impact_result = await session.run(
                impact_query,
                device_id=str(device_id),
                limit=limit,
            )
            impact_rows = await impact_result.data()

        root_node = TopologyNode(
            device_id=root_record["device_id"],
            hostname=root_record["hostname"],
            device_type=root_record["device_type"],
            status=root_record["status"],
            spatial_ref_id=root_record.get("spatial_ref_id"),
        )
        impacts: list[TopologyImpactNode] = []
        for row in impact_rows:
            impact = row.get("impact") if isinstance(row, dict) else None
            if not isinstance(impact, dict):
                continue
            impacts.append(
                TopologyImpactNode(
                    device_id=str(impact.get("device_id", "")),
                    hostname=str(impact.get("hostname", "")),
                    device_type=str(impact.get("device_type", "")),
                    status=str(impact.get("status", "")),
                    spatial_ref_id=impact.get("spatial_ref_id"),
                    hop_depth=int(impact.get("hop_depth", 1)),
                )
            )

        return TopologyImpactResponse(
            device=root_node,
            impacts=impacts,
            max_hops=bounded_hops,
            total=len(impacts),
        )

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
