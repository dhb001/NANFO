"""NANFO Backend — Topology Query Service.

Reads Neo4j device nodes and edges to serve GET /api/v1/topology/graph.
Ownership: Network module (Topology.md §4: "Entity ownership: network module").

VS10 extends this service with:
- /topology/device/{id}/neighbors deterministic neighbour queries
- /topology/impact/{id} reachable dependency analysis
- /topology/reconcile audit-event-backed reconciliation baseline
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
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
from app.modules.network.synthetic_topology import PlannedEdge

logger = get_logger(__name__)


def _record_int(record: object, key: str, default: int = 0) -> int:
    """Read an integer column from a Neo4j record safely.

    Why this exists: ``neo4j.Record`` subclasses ``tuple``, so ``"key" in record``
    tests membership against the record's *values*, not its keys, and is therefore
    almost always ``False``. Using that idiom silently produced zeroed counters.
    Indexing by key works on both ``neo4j.Record`` and plain dicts.
    """
    if record is None:
        return default
    try:
        value = record[key]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return default
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class TopologyQueryService:

    def __init__(self, driver: AsyncDriver):
        self._driver = driver

    async def get_graph(
        self,
        network_id: uuid.UUID,
        workspace_id: uuid.UUID,
        depth: int = 2,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[TopologyGraphResponse, str | None]:
        """Return a deterministic, paginated topology graph page.

        Pagination is node-based and ordered by `device_id` ascending.
        `next_cursor` is the last device_id in the current page when more rows exist.
        """
        node_query = """
        MATCH (d:Device {network_id: $network_id, workspace_id: $workspace_id})
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
        MATCH (s:Device {network_id: $network_id, workspace_id: $workspace_id})-[e:CONNECTED_TO]->(t:Device {network_id: $network_id, workspace_id: $workspace_id})
        WHERE s.device_id IN $device_ids
        RETURN DISTINCT
            s.device_id AS source_id,
            t.device_id AS target_id,
            properties(e) AS edge_properties
        ORDER BY source_id ASC, target_id ASC
        """

        fetch_limit = limit + 1
        async with self._driver.session() as session:
            node_result = await session.run(
                node_query,
                network_id=str(network_id),
                workspace_id=str(workspace_id),
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
                workspace_id=str(workspace_id),
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
        # Assign each edge to its source's page so cross-page links are not lost.
        edges: list[TopologyEdge] = []
        seen_edge_keys: set[tuple] = set()
        for e in raw_edges:
            raw_properties = e.get("edge_properties")
            metadata = dict(raw_properties) if isinstance(raw_properties, dict) else {}
            edge_key = (e["source_id"], e["target_id"], metadata.get("observation_owner"), metadata.get("synthetic_owner"),
                        metadata.get("edge_key"), metadata.get("source_port"), metadata.get("target_port"))
            if edge_key in seen_edge_keys:
                continue
            seen_edge_keys.add(edge_key)

            edges.append(
                TopologyEdge(
                    source_id=e["source_id"],
                    target_id=e["target_id"],
                    edge_type="connected_to",
                    metadata=metadata,
                )
            )
        return TopologyGraphResponse(nodes=nodes, edges=edges), next_cursor

    async def get_node_with_neighbours(
        self,
        device_id: uuid.UUID,
        network_id: uuid.UUID,
        workspace_id: uuid.UUID,
        depth: int = 1,
    ) -> dict | None:
        """Return one device node with deterministic direct neighbours.

        VS2 scope is direct (1-hop) neighbours with edge metadata.
        """
        if depth != 1:
            depth = 1

        query = """
        MATCH (d:Device {device_id: $device_id, network_id: $network_id, workspace_id: $workspace_id})
        OPTIONAL MATCH (d)-[:CONNECTED_TO]->(n_out:Device {network_id: $network_id, workspace_id: $workspace_id})
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
        OPTIONAL MATCH (n_in:Device {network_id: $network_id, workspace_id: $workspace_id})-[:CONNECTED_TO]->(d)
        WHERE n_in.device_id <> d.device_id
        WITH d, outbound, collect(DISTINCT {
            device_id: n_in.device_id,
            hostname: n_in.hostname,
            device_type: n_in.device_type,
            status: n_in.status,
            spatial_ref_id: n_in.spatial_ref_id,
            edge_type: 'connected_to',
            direction: 'inbound'
        }) AS inbound
        WITH d, outbound + inbound AS neighbours
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
            result = await session.run(
                query,
                device_id=str(device_id),
                network_id=str(network_id),
                workspace_id=str(workspace_id),
            )
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
        workspace_id: uuid.UUID,
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
        expected_workspace_id = workspace_map.get(str(network_id))
        if expected_workspace_id is None:
            return None
        if expected_workspace_id != str(workspace_id):
            return None

        reconcile_id = str(uuid.uuid4())
        warning: str | None = None
        requested_payload = {
            "reconcile_id": reconcile_id,
            "network_id": str(network_id),
            "workspace_id": str(workspace_id),
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
                node_result = await session.run(
                    node_count_query,
                    network_id=str(network_id),
                )
                node_record = await node_result.single()
                edge_result = await session.run(
                    edge_count_query,
                    network_id=str(network_id),
                )
                edge_record = await edge_result.single()
                missing_result = await session.run(
                    missing_workspace_count_query,
                    network_id=str(network_id),
                )
                missing_record = await missing_result.single()
                backfill_result = await session.run(
                    backfill_workspace_query,
                    network_id=str(network_id),
                    workspace_id=str(workspace_id),
                )
                backfill_record = await backfill_result.single()
        except Exception as exc:
            failed_payload = {
                "reconcile_id": reconcile_id,
                "network_id": str(network_id),
                "workspace_id": str(workspace_id),
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

        node_count = _record_int(node_record, "node_count")
        edge_count = _record_int(edge_record, "edge_count")
        missing_workspace_nodes = _record_int(missing_record, "missing_workspace_nodes")
        workspace_backfilled_nodes = _record_int(backfill_record, "workspace_backfilled_nodes")

        completed_payload = {
            "reconcile_id": reconcile_id,
            "network_id": str(network_id),
            "workspace_id": str(workspace_id),
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
        network_id: uuid.UUID,
        workspace_id: uuid.UUID,
        depth: int = 1,
        limit: int = 200,
    ) -> TopologyDeviceNeighboursResponse | None:
        """Return deterministic neighbours for /topology/device/{id}/neighbors.

        Includes relationship metadata and hop depth for each neighbour.
        """
        bounded_depth = max(1, min(depth, 6))

        root_query = """
        MATCH (d:Device {device_id: $device_id, network_id: $network_id, workspace_id: $workspace_id})
        RETURN d.device_id AS device_id,
               d.hostname AS hostname,
               d.device_type AS device_type,
               d.status AS status,
               d.spatial_ref_id AS spatial_ref_id
        """

        neighbours_query = """
        MATCH (d:Device {device_id: $device_id, network_id: $network_id, workspace_id: $workspace_id})
        CALL {
            WITH d
            MATCH path = (d)-[r:CONNECTED_TO*1..__DEPTH__]-(n:Device {network_id: $network_id, workspace_id: $workspace_id})
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
            root_result = await session.run(
                root_query,
                device_id=str(device_id),
                network_id=str(network_id),
                workspace_id=str(workspace_id),
            )
            root_record = await root_result.single()
            if root_record is None:
                return None

            neighbours_result = await session.run(
                neighbours_query,
                device_id=str(device_id),
                network_id=str(network_id),
                workspace_id=str(workspace_id),
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
        network_id: uuid.UUID,
        workspace_id: uuid.UUID,
        max_hops: int = 3,
        limit: int = 500,
    ) -> TopologyImpactResponse | None:
        """Return reachable dependency set with hop depth.

        Used by /topology/impact/{id} for VS10 scope.
        """
        bounded_hops = max(1, min(max_hops, 8))

        root_query = """
        MATCH (d:Device {device_id: $device_id, network_id: $network_id, workspace_id: $workspace_id})
        RETURN d.device_id AS device_id,
               d.hostname AS hostname,
               d.device_type AS device_type,
               d.status AS status,
               d.spatial_ref_id AS spatial_ref_id
        """

        impact_query = """
        MATCH (d:Device {device_id: $device_id, network_id: $network_id, workspace_id: $workspace_id})
        MATCH path = (d)-[:CONNECTED_TO*1..__MAX_HOPS__]-(n:Device {network_id: $network_id, workspace_id: $workspace_id})
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
            root_result = await session.run(
                root_query,
                device_id=str(device_id),
                network_id=str(network_id),
                workspace_id=str(workspace_id),
            )
            root_record = await root_result.single()
            if root_record is None:
                return None

            impact_result = await session.run(
                impact_query,
                device_id=str(device_id),
                network_id=str(network_id),
                workspace_id=str(workspace_id),
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

    async def apply_device_event(
        self, *, event_type: str, payload: dict, timestamp: str, event_id: str,
    ) -> bool:
        """Apply a strictly newer event and its durable revision in one transaction.

        Separate revision nodes retain missing-device delete tombstones without
        fabricating incomplete Device nodes. Direct discovery/seed helpers remain
        unversioned and retain their existing semantics.
        """
        precedence = {"network.device.added": 0, "network.device.updated": 1, "network.device.deleted": 2}
        rank = precedence[event_type]
        if not isinstance(timestamp, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", timestamp,
        ):
            raise ValueError("Device event requires an offset-aware ISO timestamp with microsecond precision")
        occurred = datetime.fromisoformat(timestamp).astimezone(UTC)
        delta = occurred - datetime(1970, 1, 1, tzinfo=UTC)
        epoch_us = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
        identity = str(uuid.UUID(event_id))
        device_id = str(uuid.UUID(payload["device_id"]))
        properties = {}
        if rank == 0:
            properties = {
                "network_id": str(uuid.UUID(payload["network_id"])),
                "workspace_id": str(uuid.UUID(payload["workspace_id"])),
                "hostname": payload["hostname"], "device_type": payload["device_type"],
                "spatial_ref_id": payload.get("spatial_ref_id"), "status": "active",
            }
        elif rank == 1:
            properties = payload["changed_fields"]
            allowed = {"hostname", "device_type", "spatial_ref_id", "status"}
            if not isinstance(properties, dict) or properties.keys() - allowed:
                raise ValueError("Unsupported device projection fields")
        if any(value is not None and not isinstance(value, str) for value in properties.values()):
            raise ValueError("Device projection properties must be strings or null")

        async def apply(tx):
            # The uniqueness constraint serializes concurrent first deliveries.
            # Explicit write lock precedes the revision read (Neo4j read-committed).
            locked = await tx.run("""
                MERGE (r:DeviceEventRevision {device_id: $device_id})
                SET r._lock = coalesce(r._lock, 0) + 1
            """, device_id=device_id)
            await locked.consume()
            result = await tx.run("""
                MATCH (r:DeviceEventRevision {device_id: $device_id})
                WHERE r.epoch_us IS NULL OR r.epoch_us < $epoch_us
                    OR (r.epoch_us = $epoch_us AND r.rank < $rank)
                    OR (r.epoch_us = $epoch_us AND r.rank = $rank AND r.event_id < $event_id)
                RETURN r.deleted AS deleted
            """, device_id=device_id, epoch_us=epoch_us, rank=rank, event_id=identity)
            revision = await result.single()
            if revision is None:
                return False
            if rank == 0:
                result = await tx.run("""
                    MERGE (d:Device {device_id: $device_id}) SET d += $properties
                """, device_id=device_id, properties=properties)
            elif rank == 2:
                result = await tx.run("""
                    MATCH (d:Device {device_id: $device_id}) SET d.status = 'deleted'
                """, device_id=device_id)
            elif revision["deleted"]:
                # Updates cannot undo a tombstone; only a newer explicit add can.
                return False
            else:
                result = await tx.run("""
                    MATCH (d:Device {device_id: $device_id})
                    SET d += $properties RETURN count(d) AS matched
                """, device_id=device_id, properties=properties)
                if _record_int(await result.single(), "matched") == 0:
                    raise ValueError("Device update arrived before its add projection")
            await result.consume()
            result = await tx.run("""
                MATCH (r:DeviceEventRevision {device_id: $device_id})
                SET r.epoch_us = $epoch_us, r.rank = $rank, r.event_id = $event_id,
                    r.deleted = $deleted
            """, device_id=device_id, epoch_us=epoch_us, rank=rank,
                event_id=identity, deleted=rank == 2 or properties.get("status") == "deleted")
            await result.consume()
            return True

        async with self._driver.session() as session:
            result = await session.run("""
                CREATE CONSTRAINT device_event_revision_identity IF NOT EXISTS
                FOR (r:DeviceEventRevision) REQUIRE r.device_id IS UNIQUE
            """)
            await result.consume()
            return await session.execute_write(apply)

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

    async def merge_device_edges(
        self,
        *,
        network_id: str,
        workspace_id: str,
        edges: Sequence[PlannedEdge],
    ) -> int:
        """Create or merge synthetic ``CONNECTED_TO`` relationships between Device nodes.

        Counterpart to :meth:`create_device_node`, which only ever wrote nodes. Without
        this, ``get_graph`` can never return edges.

        Contract:
        - Idempotent. ``MERGE`` on the relationship pattern means replaying the same
          plan does not create duplicates.
        - Scoped. Both endpoints must already exist inside ``network_id`` /
          ``workspace_id``; unmatched pairs are silently skipped rather than
          fabricating nodes.
        - Self-links are rejected.
        - Synthetic generator and edge identity never match observed relationships.
        - Relationship properties are flat primitives only (Neo4j constraint).

        Returns the number of relationships written.
        """
        payload: list[dict[str, object]] = []
        for edge in edges:
            if not edge.source_id or not edge.target_id:
                continue
            if edge.source_id == edge.target_id:
                continue
            properties = {
                key: value
                for key, value in (edge.metadata or {}).items()
                if isinstance(value, (str, int, float, bool))
            }
            if properties.get("synthetic") is not True or not properties.get("generator"):
                raise ValueError("planned edges require synthetic provenance and a stable generator")
            properties.pop("observation_owner", None)
            properties["synthetic_owner"] = str(properties["generator"])
            properties["edge_key"] = str(properties.get("edge_key") or uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{network_id}:{workspace_id}:{edge.source_id}:{edge.target_id}:"
                f"{properties.get('source_port', '')}:{properties.get('target_port', '')}",
            ))
            properties["execution_mode"] = "demo"
            payload.append(
                {
                    "source_id": edge.source_id,
                    "target_id": edge.target_id,
                    "properties": properties,
                }
            )

        if not payload:
            logger.info(
                "topology_edges_merge_skipped",
                network_id=network_id,
                reason="empty_payload",
            )
            return 0

        query = """
        UNWIND $edges AS edge
        MATCH (s:Device {device_id: edge.source_id, network_id: $network_id, workspace_id: $workspace_id})
        MATCH (t:Device {device_id: edge.target_id, network_id: $network_id, workspace_id: $workspace_id})
        WHERE s.device_id <> t.device_id
        MERGE (s)-[r:CONNECTED_TO {synthetic_owner: edge.properties.synthetic_owner, edge_key: edge.properties.edge_key}]->(t)
        SET r += edge.properties
        RETURN count(r) AS written
        """

        async with self._driver.session() as session:
            result = await session.run(
                query,
                edges=payload,
                network_id=network_id,
                workspace_id=workspace_id,
            )
            record = await result.single()

        written = _record_int(record, "written")
        logger.info(
            "topology_edges_merged",
            network_id=network_id,
            requested_edges=len(payload),
            written_edges=written,
        )
        return written

    async def replace_observed_device_edges(
        self, *, network_id: str, workspace_id: str, owner_id: str,
        edges: Sequence[PlannedEdge],
    ) -> int:
        """Atomically replace only this binding's observed links, preserving parallels.

        Missing graph projections abort the transaction, retaining the previous set
        for a later retry. No undocumented link event is published (ADR-009).
        """
        payload = []
        for edge in edges:
            properties = dict(edge.metadata or {})
            key = properties.get("edge_key")
            if not key or edge.source_id == edge.target_id or properties.get("synthetic") is not False:
                raise ValueError("invalid observed edge")
            if any(not isinstance(value, (str, int, float, bool)) for value in properties.values()):
                raise ValueError("observed edge properties must be flat primitives")
            properties["observation_owner"] = owner_id
            properties["execution_mode"] = "emulation"
            payload.append({"source_id": edge.source_id, "target_id": edge.target_id,
                            "key": key, "properties": properties})
        if not owner_id or len({edge["key"] for edge in payload}) != len(payload):
            raise ValueError("invalid observed edge ownership or duplicate key")

        async def replace(tx):
            params = {"network_id": network_id, "workspace_id": workspace_id,
                      "owner_id": owner_id, "edges": payload}
            result = await tx.run("""
                UNWIND $edges AS edge
                MATCH (s:Device {device_id: edge.source_id, network_id: $network_id, workspace_id: $workspace_id})
                MATCH (t:Device {device_id: edge.target_id, network_id: $network_id, workspace_id: $workspace_id})
                RETURN count(*) AS matched
            """, **params)
            if _record_int(await result.single(), "matched") != len(payload):
                raise ValueError("observed topology inventory projection incomplete")
            result = await tx.run("""
                MATCH (:Device {network_id: $network_id, workspace_id: $workspace_id})
                    -[r:CONNECTED_TO]->(:Device {network_id: $network_id, workspace_id: $workspace_id})
                WHERE r.observation_owner = $owner_id AND r.synthetic = false
                    AND r.execution_mode = 'emulation'
                DELETE r
            """, **params)
            await result.consume()
            result = await tx.run("""
                UNWIND $edges AS edge
                MATCH (s:Device {device_id: edge.source_id, network_id: $network_id, workspace_id: $workspace_id})
                MATCH (t:Device {device_id: edge.target_id, network_id: $network_id, workspace_id: $workspace_id})
                MERGE (s)-[r:CONNECTED_TO {observation_owner: $owner_id, edge_key: edge.key}]->(t)
                SET r += edge.properties
                RETURN count(r) AS written
            """, **params)
            return _record_int(await result.single(), "written")

        async with self._driver.session() as session:
            return await session.execute_write(replace)

    async def prune_synthetic_device_edges(
        self,
        *,
        network_id: str,
        workspace_id: str,
        generator: str,
    ) -> int:
        """Delete previously generated synthetic edges for one network.

        Only relationships explicitly tagged ``synthetic = true`` **and** matching
        ``generator`` are removed, so discovered/real topology is never touched.

        This exists because a regenerated plan is not necessarily a superset of the
        previous one: if the device set differs (for example because Neo4j projection
        was still catching up), parent selection legitimately changes and a plain
        ``MERGE`` would leave stale uplinks behind, inflating the edge count.
        """
        query = """
        MATCH (s:Device {network_id: $network_id, workspace_id: $workspace_id})
              -[r:CONNECTED_TO]->
              (t:Device {network_id: $network_id, workspace_id: $workspace_id})
        WHERE r.synthetic = true AND r.generator = $generator
        DELETE r
        RETURN count(r) AS deleted
        """
        async with self._driver.session() as session:
            result = await session.run(
                query,
                network_id=network_id,
                workspace_id=workspace_id,
                generator=generator,
            )
            record = await result.single()

        deleted = _record_int(record, "deleted")
        logger.info(
            "topology_synthetic_edges_pruned",
            network_id=network_id,
            generator=generator,
            deleted_edges=deleted,
        )
        return deleted

    async def replace_synthetic_device_edges(
        self,
        *,
        network_id: str,
        workspace_id: str,
        edges: Sequence[PlannedEdge],
        generator: str,
    ) -> tuple[int, int]:
        """Make the synthetic edge set for a network exactly match ``edges``.

        Returns ``(deleted, written)``. Safe to re-run: the result depends only on the
        supplied plan, not on how many times seeding has happened before.
        """
        if any((edge.metadata or {}).get("synthetic") is not True
               or (edge.metadata or {}).get("generator") != generator for edge in edges):
            raise ValueError("replacement edges must belong to the synthetic generator")
        deleted = await self.prune_synthetic_device_edges(
            network_id=network_id,
            workspace_id=workspace_id,
            generator=generator,
        )
        written = await self.merge_device_edges(
            network_id=network_id,
            workspace_id=workspace_id,
            edges=edges,
        )
        return deleted, written

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
                updated = _record_int(record, "updated")
                updated_total += updated

        logger.info(
            "topology_workspace_backfill_complete",
            correlation_id=correlation_id,
            missing_networks=len(network_ids),
            mapped_networks=len(workspace_by_network),
            updated_nodes=updated_total,
        )
        return updated_total
