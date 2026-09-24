"""NANFO Backend — Topology Query Service (Network-owned Neo4j projection).

Reads and writes the Neo4j device projection for the topology API and consumers.
Ownership: Network module (Topology.md §4: "Entity ownership: network module").

ADR-028 guarantees:

* Reads run in ``execute_read`` transactions with a server-side timeout
  (``unit_of_work``) plus a client deadline; outages/timeouts surface as
  ``DependencyUnavailableError`` (HTTP 503), never as hung requests.
* Multi-hop traversals are breadth-first with a visited set (first-reach, shortest
  hop depth); no query enumerates paths, so dense meshes cannot explode.
* Soft-deleted devices (``status = 'deleted'``) are excluded from every node
  pattern, including traversal interiors; deleting a device removes its edges.
* Graph schema (constraints/indexes) is created once by :func:`ensure_graph_schema`,
  never per event.
* Device projection revisions order by the outbox ``sequence`` (C13) when present,
  falling back to event time for events published before sequences existed.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from neo4j import READ_ACCESS, WRITE_ACCESS, AsyncDriver, unit_of_work
from neo4j.exceptions import DriverError, Neo4jError, ServiceUnavailable, SessionExpired, TransientError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DependencyUnavailableError
from app.core.logging import get_logger
from app.events.publisher import publish_event
from app.modules.network.repository import DeviceRepository, NetworkRepository
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

#: Server-side transaction timeouts (seconds); the client deadline adds a grace.
READ_TIMEOUT_SECONDS = 5.0
WRITE_TIMEOUT_SECONDS = 15.0
_CLIENT_GRACE_SECONDS = 1.0
#: Hard bounds retained from the public API (defence in depth for internal callers).
MAX_NEIGHBOUR_DEPTH = 6
MAX_IMPACT_HOPS = 8
RECONCILE_PAGE_SIZE = 500
_RECONCILE_RANK = 3
_MAX_SEQUENCE = 2**63 - 1

#: A node is visible unless explicitly tombstoned (legacy nodes may lack status).
_ACTIVE = "coalesce({alias}.status, '') <> 'deleted'"

#: (name, statement) created once at startup, idempotently.
GRAPH_SCHEMA: tuple[tuple[str, str], ...] = (
    ("device_identity",
     "CREATE CONSTRAINT device_identity IF NOT EXISTS FOR (d:Device) REQUIRE d.device_id IS UNIQUE"),
    ("device_scope",
     "CREATE INDEX device_scope IF NOT EXISTS FOR (d:Device) ON (d.workspace_id, d.network_id)"),
    ("device_event_revision_identity",
     "CREATE CONSTRAINT device_event_revision_identity IF NOT EXISTS "
     "FOR (r:DeviceEventRevision) REQUIRE r.device_id IS UNIQUE"),
)
#: Lookup index used when legacy duplicate Device nodes prevent the unique constraint.
_SCHEMA_FALLBACKS = {
    "device_identity": ("device_identity_lookup",
                        "CREATE INDEX device_identity_lookup IF NOT EXISTS FOR (d:Device) ON (d.device_id)"),
}
_schema_ready = False


async def ensure_graph_schema(driver: AsyncDriver | None = None) -> dict[str, str]:
    """Create the topology graph constraints/indexes once (startup hook).

    Idempotent (``IF NOT EXISTS``). A failing item is logged with its Neo4j error
    code and reported, never raised, so startup is not blocked by legacy data (for
    example duplicate Device nodes that must be reconciled first).
    """
    global _schema_ready
    if driver is None:
        from app.db.neo4j import get_neo4j_driver

        driver = get_neo4j_driver()
    report: dict[str, str] = {}
    async with driver.session(default_access_mode=WRITE_ACCESS) as session:
        for name, statement in GRAPH_SCHEMA:
            report[name] = await _apply_schema_item(session, name, statement)
            if report[name] == "failed" and name in _SCHEMA_FALLBACKS:
                fallback, fallback_statement = _SCHEMA_FALLBACKS[name]
                report[fallback] = await _apply_schema_item(session, fallback, fallback_statement)
    _schema_ready = all(report.get(name) == "ok" for name, _ in GRAPH_SCHEMA)
    logger.info("topology_graph_schema_ensured", ready=_schema_ready, **report)
    return report


async def _apply_schema_item(session, name: str, statement: str) -> str:
    try:
        result = await session.run(statement)
        await result.consume()
        return "ok"
    except (Neo4jError, DriverError) as exc:
        logger.error("topology_graph_schema_item_failed", item=name,
                     error_code=getattr(exc, "code", None) or type(exc).__name__)
        return "failed"


def graph_schema_ready() -> bool:
    return _schema_ready


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


def _is_unavailable(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ServiceUnavailable, SessionExpired, TransientError)):
        return True
    code = getattr(exc, "code", None) or ""
    return isinstance(exc, Neo4jError) and "TransactionTimedOut" in code


def graph_error_code(exc: BaseException) -> str:
    """Stable, non-sensitive error code for events and logs (never ``str(exc)``)."""
    if isinstance(exc, DependencyUnavailableError) or _is_unavailable(exc):
        return "GRAPH_UNAVAILABLE"
    if isinstance(exc, Neo4jError | DriverError):
        return "GRAPH_QUERY_FAILED"
    if type(exc).__module__.startswith("sqlalchemy"):
        return "INVENTORY_UNAVAILABLE"
    return "RECONCILE_FAILED"


def _epoch_us(moment: datetime) -> int:
    delta = moment.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def _edge_sort_key(metadata: object) -> str:
    if not isinstance(metadata, dict):
        return ""
    return json.dumps(metadata, sort_keys=True, separators=(",", ":"), default=str)


def _node(row: dict) -> dict:
    return {key: row.get(key) for key in ("device_id", "hostname", "device_type", "status", "spatial_ref_id")}


def _topology_node(row: dict) -> TopologyNode:
    return TopologyNode(
        device_id=row["device_id"], hostname=row["hostname"], device_type=row["device_type"],
        status=row["status"], spatial_ref_id=row.get("spatial_ref_id"),
    )


_ROOT_QUERY = f"""
MATCH (d:Device {{device_id: $device_id, network_id: $network_id, workspace_id: $workspace_id}})
WHERE {_ACTIVE.format(alias="d")}
RETURN d.device_id AS device_id,
       d.hostname AS hostname,
       d.device_type AS device_type,
       d.status AS status,
       d.spatial_ref_id AS spatial_ref_id
"""

# First hop keeps every relationship (direction/type/metadata) so the chosen first
# edge is deterministic; deeper hops inherit it from their BFS parent.
_FIRST_HOP_QUERY = f"""
MATCH (d:Device {{device_id: $device_id}})-[r:CONNECTED_TO]-(n:Device)
WHERE n.network_id = $network_id AND n.workspace_id = $workspace_id
  AND {_ACTIVE.format(alias="n")} AND n.device_id <> $device_id
RETURN n.device_id AS device_id,
       n.hostname AS hostname,
       n.device_type AS device_type,
       n.status AS status,
       n.spatial_ref_id AS spatial_ref_id,
       toLower(type(r)) AS edge_type,
       properties(r) AS edge_metadata,
       CASE WHEN startNode(r) = d THEN 'outbound' ELSE 'inbound' END AS direction
"""

# One hop of the frontier. Visited filtering happens client-side, so the per-level
# cost is bounded by the frontier's incident edges (no path enumeration).
_EXPAND_QUERY = f"""
UNWIND $frontier AS parent_id
MATCH (p:Device {{device_id: parent_id}})-[:CONNECTED_TO]-(n:Device)
WHERE n.network_id = $network_id AND n.workspace_id = $workspace_id
  AND {_ACTIVE.format(alias="n")}
RETURN DISTINCT parent_id,
       n.device_id AS device_id,
       n.hostname AS hostname,
       n.device_type AS device_type,
       n.status AS status,
       n.spatial_ref_id AS spatial_ref_id
"""


async def _breadth_first(tx, *, device_id: str, network_id: str, workspace_id: str, max_depth: int,
                         stop_after: int | None = None) -> tuple[dict | None, list[dict]]:
    """First-reach BFS from ``device_id``; returns (root, reached nodes with hop_depth).

    Each reached node carries the deterministic first edge from the root on one of
    its shortest paths: minimal (direction, edge_type, metadata) at hop 1, then the
    minimal (inherited edge, parent id) among same-level parents.
    """
    scope = {"network_id": network_id, "workspace_id": workspace_id}
    root = await (await tx.run(_ROOT_QUERY, device_id=device_id, **scope)).single()
    if root is None:
        return None, []
    root = dict(root)
    reached: dict[str, dict] = {}
    for row in await (await tx.run(_FIRST_HOP_QUERY, device_id=device_id, **scope)).data():
        rank = (str(row.get("direction") or "outbound"), str(row.get("edge_type") or "connected_to"),
                _edge_sort_key(row.get("edge_metadata")))
        current = reached.get(row["device_id"])
        if current is None or rank < current["_rank"]:
            metadata = row.get("edge_metadata")
            reached[row["device_id"]] = {
                **_node(row), "hop_depth": 1, "direction": rank[0], "edge_type": rank[1],
                "edge_metadata": dict(metadata) if isinstance(metadata, dict) else {}, "_rank": rank,
            }
    visited = {device_id, *reached}
    frontier = sorted(reached)
    depth = 1
    while frontier and depth < max_depth and (stop_after is None or len(reached) < stop_after):
        depth += 1
        level: dict[str, dict] = {}
        for row in await (await tx.run(_EXPAND_QUERY, frontier=frontier, **scope)).data():
            candidate = row["device_id"]
            parent = reached.get(row["parent_id"])
            if candidate in visited or parent is None:
                continue
            rank = (parent["_rank"], row["parent_id"])
            current = level.get(candidate)
            if current is None or rank < current["_parent_rank"]:
                level[candidate] = {
                    **_node(row), "hop_depth": depth, "direction": parent["direction"],
                    "edge_type": parent["edge_type"], "edge_metadata": parent["edge_metadata"],
                    "_rank": parent["_rank"], "_parent_rank": rank,
                }
        visited.update(level)
        reached.update(level)
        frontier = sorted(level)
    return root, [{key: value for key, value in item.items() if not key.startswith("_")}
                  for item in reached.values()]


class TopologyQueryService:

    def __init__(self, driver: AsyncDriver):
        self._driver = driver

    async def _read(self, work, **kwargs):
        """Run ``work(tx, **kwargs)`` in one bounded read transaction."""
        @unit_of_work(timeout=READ_TIMEOUT_SECONDS)
        async def transaction(tx):
            return await work(tx, **kwargs)

        try:
            async with asyncio.timeout(READ_TIMEOUT_SECONDS + _CLIENT_GRACE_SECONDS):
                async with self._driver.session(default_access_mode=READ_ACCESS) as session:
                    return await session.execute_read(transaction)
        except (Neo4jError, DriverError, TimeoutError) as exc:
            if _is_unavailable(exc):
                raise DependencyUnavailableError("neo4j") from exc
            raise

    async def _write(self, work, *, timeout: float = WRITE_TIMEOUT_SECONDS, **kwargs):
        """Run ``work(tx, **kwargs)`` in one bounded (retried) write transaction."""
        @unit_of_work(timeout=timeout)
        async def transaction(tx):
            return await work(tx, **kwargs)

        try:
            async with asyncio.timeout(timeout + _CLIENT_GRACE_SECONDS):
                async with self._driver.session(default_access_mode=WRITE_ACCESS) as session:
                    return await session.execute_write(transaction)
        except (Neo4jError, DriverError, TimeoutError) as exc:
            if _is_unavailable(exc):
                raise DependencyUnavailableError("neo4j") from exc
            raise

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
        Tombstoned devices and their edges are never returned.
        """
        node_query = f"""
        MATCH (d:Device {{network_id: $network_id, workspace_id: $workspace_id}})
        WHERE ($cursor IS NULL OR d.device_id > $cursor) AND {_ACTIVE.format(alias="d")}
        RETURN d.device_id AS device_id,
               d.hostname AS hostname,
               d.device_type AS device_type,
               d.status AS status,
               d.spatial_ref_id AS spatial_ref_id
        ORDER BY d.device_id ASC
        LIMIT $fetch_limit
        """

        edge_query = f"""
        MATCH (s:Device {{network_id: $network_id, workspace_id: $workspace_id}})-[e:CONNECTED_TO]->(t:Device {{network_id: $network_id, workspace_id: $workspace_id}})
        WHERE s.device_id IN $device_ids AND {_ACTIVE.format(alias="s")} AND {_ACTIVE.format(alias="t")}
        RETURN DISTINCT
            s.device_id AS source_id,
            t.device_id AS target_id,
            properties(e) AS edge_properties
        ORDER BY source_id ASC, target_id ASC
        """
        scope = {"network_id": str(network_id), "workspace_id": str(workspace_id)}

        async def work(tx):
            raw_nodes = await (await tx.run(node_query, **scope, cursor=cursor, fetch_limit=limit + 1)).data()
            page = raw_nodes[:limit]
            if not page:
                return raw_nodes, []
            ids = [row["device_id"] for row in page]
            return raw_nodes, await (await tx.run(edge_query, **scope, device_ids=ids)).data()

        raw_nodes, raw_edges = await self._read(work)
        page_rows = raw_nodes[:limit]
        if not page_rows:
            return TopologyGraphResponse(nodes=[], edges=[]), None
        next_cursor = page_rows[-1]["device_id"] if len(raw_nodes) > limit else None

        nodes = [_topology_node(n) for n in page_rows]
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
            edges.append(TopologyEdge(source_id=e["source_id"], target_id=e["target_id"],
                                      edge_type="connected_to", metadata=metadata))
        return TopologyGraphResponse(nodes=nodes, edges=edges), next_cursor

    async def get_node_with_neighbours(
        self,
        device_id: uuid.UUID,
        network_id: uuid.UUID,
        workspace_id: uuid.UUID,
        depth: int = 1,
    ) -> dict | None:
        """Return one device node with deterministic direct (1-hop) neighbours."""
        query = f"""
        MATCH (d:Device {{device_id: $device_id, network_id: $network_id, workspace_id: $workspace_id}})
        WHERE {_ACTIVE.format(alias="d")}
        OPTIONAL MATCH (d)-[:CONNECTED_TO]->(n_out:Device {{network_id: $network_id, workspace_id: $workspace_id}})
        WHERE n_out.device_id <> d.device_id AND {_ACTIVE.format(alias="n_out")}
        WITH d, collect(DISTINCT {{
            device_id: n_out.device_id,
            hostname: n_out.hostname,
            device_type: n_out.device_type,
            status: n_out.status,
            spatial_ref_id: n_out.spatial_ref_id,
            edge_type: 'connected_to',
            direction: 'outbound'
        }}) AS outbound
        OPTIONAL MATCH (n_in:Device {{network_id: $network_id, workspace_id: $workspace_id}})-[:CONNECTED_TO]->(d)
        WHERE n_in.device_id <> d.device_id AND {_ACTIVE.format(alias="n_in")}
        WITH d, outbound, collect(DISTINCT {{
            device_id: n_in.device_id,
            hostname: n_in.hostname,
            device_type: n_in.device_type,
            status: n_in.status,
            spatial_ref_id: n_in.spatial_ref_id,
            edge_type: 'connected_to',
            direction: 'inbound'
        }}) AS inbound
        WITH d, outbound + inbound AS neighbours
        RETURN {{
            device_id: d.device_id,
            hostname: d.hostname,
            device_type: d.device_type,
            status: d.status,
            spatial_ref_id: d.spatial_ref_id
        }} AS node,
        [n IN neighbours WHERE n.device_id IS NOT NULL] AS neighbours
        """

        async def work(tx):
            record = await (await tx.run(
                query, device_id=str(device_id), network_id=str(network_id), workspace_id=str(workspace_id),
            )).single()
            return None if record is None else {"node": record["node"], "neighbours": record["neighbours"]}

        record = await self._read(work)
        if record is None or record["node"] is None:
            return None
        ordered_neighbours = sorted(
            record["neighbours"] or [],
            key=lambda item: (item["device_id"], item["direction"], item["edge_type"]),
        )
        return {"node": record["node"], "neighbours": ordered_neighbours}

    async def get_device_neighbours(
        self,
        *,
        device_id: uuid.UUID,
        network_id: uuid.UUID,
        workspace_id: uuid.UUID,
        depth: int = 1,
        limit: int = 200,
    ) -> TopologyDeviceNeighboursResponse | None:
        """Deterministic neighbours within ``depth`` hops (shortest hop depth each).

        Ordered by device_id; each neighbour carries the deterministic first edge
        (type, metadata, direction) of a shortest path from the device.
        """
        bounded_depth = max(1, min(depth, MAX_NEIGHBOUR_DEPTH))
        root, reached = await self._read(
            _breadth_first, device_id=str(device_id), network_id=str(network_id),
            workspace_id=str(workspace_id), max_depth=bounded_depth,
        )
        if root is None:
            return None
        selected = sorted(reached, key=lambda item: (item["device_id"], item["hop_depth"],
                                                    item["direction"], item["edge_type"]))[:max(0, limit)]
        neighbours = [
            TopologyNeighbourEdge(
                device_id=str(item.get("device_id", "")),
                hostname=str(item.get("hostname", "")),
                device_type=str(item.get("device_type", "")),
                status=str(item.get("status", "")),
                spatial_ref_id=item.get("spatial_ref_id"),
                edge_type=str(item.get("edge_type") or "connected_to"),
                edge_metadata=item.get("edge_metadata") if isinstance(item.get("edge_metadata"), dict) else {},
                direction=str(item.get("direction") or "outbound"),
                hop_depth=int(item["hop_depth"]),
            )
            for item in selected
        ]
        return TopologyDeviceNeighboursResponse(
            device=_topology_node(root), neighbours=neighbours, depth=bounded_depth, total=len(neighbours),
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
        """Reachable dependency set with shortest hop depth (hop, device_id order).

        BFS stops expanding once ``limit`` nodes are reached at a completed level.
        """
        bounded_hops = max(1, min(max_hops, MAX_IMPACT_HOPS))
        root, reached = await self._read(
            _breadth_first, device_id=str(device_id), network_id=str(network_id),
            workspace_id=str(workspace_id), max_depth=bounded_hops, stop_after=max(1, limit),
        )
        if root is None:
            return None
        selected = sorted(reached, key=lambda item: (item["hop_depth"], item["device_id"]))[:max(0, limit)]
        impacts = [
            TopologyImpactNode(
                device_id=str(item.get("device_id", "")),
                hostname=str(item.get("hostname", "")),
                device_type=str(item.get("device_type", "")),
                status=str(item.get("status", "")),
                spatial_ref_id=item.get("spatial_ref_id"),
                hop_depth=int(item["hop_depth"]),
            )
            for item in selected
        ]
        return TopologyImpactResponse(
            device=_topology_node(root), impacts=impacts, max_hops=bounded_hops, total=len(impacts),
        )

    # ------------------------------------------------------------------ reconcile

    async def reconcile_network(
        self,
        *,
        network_id: uuid.UUID,
        workspace_id: uuid.UUID,
        watermark: int,
        db: AsyncSession,
        redis: aioredis.Redis,
        actor_id: str,
        correlation_id: str,
        page_size: int = RECONCILE_PAGE_SIZE,
    ) -> dict:
        """Converge the network's Device projection to PostgreSQL inventory.

        The caller authorized and read ``watermark`` under the inventory lock, then
        released it. Active devices are read in keyset pages (the PostgreSQL
        transaction ends before each graph write) and upserted under their
        revision lock; projected devices absent from inventory are tombstoned and
        lose their edges. A revision that already applied a newer sequence than
        ``watermark`` is never overwritten.
        """
        if type(watermark) is not int or not 0 <= watermark <= _MAX_SEQUENCE:
            raise ValueError("Reconcile watermark must be a non-negative 64-bit integer")
        reconcile_id = str(uuid.uuid4())
        network, workspace = str(network_id), str(workspace_id)
        base = {"reconcile_id": reconcile_id, "network_id": network, "workspace_id": workspace,
                "actor_id": actor_id}
        warning = None
        if not await self._publish(redis, "network.topology.reconcile_requested", {
            **base, "status": "requested", "requested_at": datetime.now(UTC).isoformat(),
        }, correlation_id):
            warning = "event_queue_unavailable"
        revision = {"network_id": network, "workspace_id": workspace, "watermark": watermark,
                    "epoch_us": _epoch_us(datetime.now(UTC)), "reconcile_id": reconcile_id}
        counts = {"active_devices": 0, "upserted_nodes": 0, "tombstoned_nodes": 0, "skipped_newer_nodes": 0}
        try:
            missing_before = await self._read(_count_missing_workspace, network_id=network)
            devices = DeviceRepository(db)
            seen: set[str] = set()
            after: uuid.UUID | None = None
            while True:
                page = await devices.list_projection_page(network_id, after=after, limit=page_size)
                # Never hold a PostgreSQL transaction (or snapshot) across graph I/O.
                await db.rollback()
                if not page:
                    break
                batch = [_device_projection(row) for row in page]
                seen.update(item["device_id"] for item in batch)
                upserted = await self._write(_reconcile_upsert, devices=batch, **revision)
                counts["active_devices"] += len(batch)
                counts["upserted_nodes"] += upserted
                counts["skipped_newer_nodes"] += len(batch) - upserted
                if len(page) < page_size:
                    break
                after = page[-1]["device_id"]
            projected = await self._read(_projected_device_ids, network_id=network)
            stale = sorted(set(projected) - seen)
            for start in range(0, len(stale), page_size):
                chunk = stale[start:start + page_size]
                tombstoned = await self._write(_reconcile_tombstone, device_ids=chunk, **revision)
                counts["tombstoned_nodes"] += tombstoned
                counts["skipped_newer_nodes"] += len(chunk) - tombstoned
            totals = await self._read(_network_totals, network_id=network)
        except Exception as exc:
            code = graph_error_code(exc)
            logger.warning("topology_reconcile_failed", correlation_id=correlation_id, reconcile_id=reconcile_id,
                           network_id=network, error_code=code, error_type=type(exc).__name__)
            await self._publish(redis, "network.topology.reconcile_failed", {
                **base, "status": "failed", "error": code, "failed_at": datetime.now(UTC).isoformat(),
            }, correlation_id)
            raise

        result = {
            "reconcile_id": reconcile_id, "network_id": network, "status": "completed",
            "checked_nodes": _record_int(totals, "nodes"), "checked_edges": _record_int(totals, "edges"),
            "missing_workspace_nodes": missing_before,
            "workspace_backfilled_nodes": max(0, missing_before - _record_int(totals, "missing_workspace")),
            "watermark_sequence": watermark, **counts,
        }
        if not await self._publish(redis, "network.topology.reconcile_completed", {
            **base, **{key: value for key, value in result.items() if key not in base},
            "warning": warning, "completed_at": datetime.now(UTC).isoformat(),
        }, correlation_id):
            warning = "event_queue_unavailable"
        return {**result, "warning": warning}

    async def _publish(self, redis, event_type: str, payload: dict, correlation_id: str) -> bool:
        try:
            await publish_event(redis=redis, event_type=event_type, source="network",
                                payload=payload, correlation_id=correlation_id)
            return True
        except Exception as exc:  # noqa: BLE001 - lifecycle events are best effort
            logger.warning("topology_reconcile_event_publish_failed", event_type=event_type,
                           correlation_id=correlation_id, error_type=type(exc).__name__)
            return False

    # ------------------------------------------------------------ event projection

    async def apply_device_event(
        self, *, event_type: str, payload: dict, timestamp: str, event_id: str,
    ) -> bool:
        """Apply a strictly newer event and its durable revision in one transaction.

        Order: the per-network outbox ``sequence`` (C13) when both the event and the
        stored revision carry one; otherwise event time, precedence and event id
        (events published before sequences existed). Separate revision nodes retain
        missing-device delete tombstones without fabricating incomplete Device nodes.
        """
        precedence = {"network.device.added": 0, "network.device.updated": 1, "network.device.deleted": 2}
        rank = precedence[event_type]
        if not isinstance(timestamp, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", timestamp,
        ):
            raise ValueError("Device event requires an offset-aware ISO timestamp with microsecond precision")
        epoch_us = _epoch_us(datetime.fromisoformat(timestamp))
        identity = str(uuid.UUID(event_id))
        device_id = str(uuid.UUID(payload["device_id"]))
        sequence = payload.get("sequence")
        if sequence is not None and (type(sequence) is not int or not 1 <= sequence <= _MAX_SEQUENCE):
            raise ValueError("Device event sequence must be a positive 64-bit integer")
        properties = {}
        if rank == 0:
            properties = {
                "network_id": str(uuid.UUID(payload["network_id"])),
                "workspace_id": str(uuid.UUID(payload["workspace_id"])),
                "hostname": payload["hostname"], "device_type": payload["device_type"],
                "ip_address": payload.get("ip_address"),
                "spatial_ref_id": payload.get("spatial_ref_id"), "status": "active",
            }
        elif rank == 1:
            properties = payload["changed_fields"]
            allowed = {"hostname", "device_type", "ip_address", "vendor", "model",
                       "location_hint", "spatial_ref_id", "status"}
            if not isinstance(properties, dict) or properties.keys() - allowed:
                raise ValueError("Unsupported device projection fields")
        if any(value is not None and not isinstance(value, str) for value in properties.values()):
            raise ValueError("Device projection properties must be strings or null")
        order = {"device_id": device_id, "epoch_us": epoch_us, "rank": rank, "event_id": identity,
                 "sequence": sequence}

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
                WHERE (r.epoch_us IS NULL AND r.sequence IS NULL)
                    OR ($sequence IS NOT NULL AND r.sequence IS NOT NULL AND $sequence > r.sequence)
                    OR (($sequence IS NULL OR r.sequence IS NULL) AND (
                        r.epoch_us IS NULL OR r.epoch_us < $epoch_us
                        OR (r.epoch_us = $epoch_us AND r.rank < $rank)
                        OR (r.epoch_us = $epoch_us AND r.rank = $rank AND r.event_id < $event_id)))
                RETURN r.deleted AS deleted
            """, **order)
            revision = await result.single()
            if revision is None:
                return False
            if rank == 0:
                result = await tx.run("""
                    MERGE (d:Device {device_id: $device_id}) SET d += $properties
                """, device_id=device_id, properties=properties)
            elif rank == 2:
                # A tombstoned device keeps its node but loses every relationship,
                # so traversals and edge reads can never route through it.
                result = await tx.run("""
                    MATCH (d:Device {device_id: $device_id}) SET d.status = 'deleted'
                    WITH d
                    OPTIONAL MATCH (d)-[e:CONNECTED_TO]-()
                    DELETE e
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
            # Revision clock triple only moves forward, so pre-sequence events can
            # never overtake a newer sequenced event even under producer clock skew.
            result = await tx.run("""
                MATCH (r:DeviceEventRevision {device_id: $device_id})
                WITH r, (r.epoch_us IS NULL OR $epoch_us > r.epoch_us
                    OR ($epoch_us = r.epoch_us AND ($rank > r.rank
                        OR ($rank = r.rank AND $event_id > r.event_id)))) AS advances
                SET r.epoch_us = CASE WHEN advances THEN $epoch_us ELSE r.epoch_us END,
                    r.rank = CASE WHEN advances THEN $rank ELSE r.rank END,
                    r.event_id = CASE WHEN advances THEN $event_id ELSE r.event_id END,
                    r.sequence = coalesce($sequence, r.sequence),
                    r.deleted = $deleted
            """, **order, deleted=rank == 2 or properties.get("status") == "deleted")
            await result.consume()
            return True

        # Bounded like every other graph write; an outage surfaces as a transient
        # DependencyUnavailableError (redelivered), never as a poison event.
        return await self._write(apply)

    # ------------------------------------------------------------ edge writers
    #
    # Every relationship MERGE first takes the per-device revision locks of its
    # endpoints (sorted; the same lock the event projector and reconcile take
    # before touching a Device), then re-checks both endpoints are active. A
    # concurrent delete therefore either commits first (the writer then skips the
    # tombstoned endpoint) or waits and removes the new relationship afterwards:
    # no edge to a deleted device can survive a seed/discovery race.

    async def merge_device_edges(
        self,
        *,
        network_id: str,
        workspace_id: str,
        edges: Sequence[PlannedEdge],
    ) -> int:
        """Create or merge synthetic ``CONNECTED_TO`` relationships between Device nodes.

        Contract:
        - Idempotent. ``MERGE`` on the relationship pattern means replaying the same
          plan does not create duplicates.
        - Scoped. Both endpoints must already exist, active, inside ``network_id`` /
          ``workspace_id``; unmatched pairs are silently skipped rather than
          fabricating nodes.
        - Self-links are rejected.
        - Synthetic generator and edge identity never match observed relationships.
        - Relationship properties are flat primitives only (Neo4j constraint).

        Returns the number of relationships written.
        """
        payload = _synthetic_edge_payload(network_id=network_id, workspace_id=workspace_id, edges=edges)
        if not payload:
            logger.info("topology_edges_merge_skipped", network_id=network_id, reason="empty_payload")
            return 0
        written = await self._write(_merge_edges, edges=payload, network_id=network_id, workspace_id=workspace_id)
        logger.info("topology_edges_merged", network_id=network_id, requested_edges=len(payload),
                    written_edges=written)
        return written

    async def replace_observed_device_edges(
        self, *, network_id: str, workspace_id: str, owner_id: str,
        edges: Sequence[PlannedEdge],
    ) -> int:
        """Atomically replace only this binding's observed links, preserving parallels.

        Missing (or tombstoned) graph projections abort the transaction, retaining
        the previous set for a later retry. No undocumented link event is published.
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

        endpoints = f"""
                MATCH (s:Device {{device_id: edge.source_id, network_id: $network_id, workspace_id: $workspace_id}})
                MATCH (t:Device {{device_id: edge.target_id, network_id: $network_id, workspace_id: $workspace_id}})
                WHERE {_ACTIVE.format(alias="s")} AND {_ACTIVE.format(alias="t")}"""

        async def replace(tx):
            params = {"network_id": network_id, "workspace_id": workspace_id,
                      "owner_id": owner_id, "edges": payload}
            # Endpoint revision locks precede the activity check they protect.
            await _lock_revisions(tx, _endpoint_ids(payload))
            result = await tx.run(f"""
                UNWIND $edges AS edge{endpoints}
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
            result = await tx.run(f"""
                UNWIND $edges AS edge{endpoints}
                MERGE (s)-[r:CONNECTED_TO {{observation_owner: $owner_id, edge_key: edge.key}}]->(t)
                SET r += edge.properties
                RETURN count(r) AS written
            """, **params)
            return _record_int(await result.single(), "written")

        return await self._write(replace)

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
        """
        deleted = await self._write(_prune_synthetic, network_id=network_id, workspace_id=workspace_id,
                                    generator=generator)
        logger.info("topology_synthetic_edges_pruned", network_id=network_id, generator=generator,
                    deleted_edges=deleted)
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

        Prune and merge run in ONE write transaction: readers never observe the
        network without its synthetic edges, and a failure keeps the previous set.
        Returns ``(deleted, written)``; re-running with the same plan converges.
        """
        if any((edge.metadata or {}).get("synthetic") is not True
               or (edge.metadata or {}).get("generator") != generator for edge in edges):
            raise ValueError("replacement edges must belong to the synthetic generator")
        payload = _synthetic_edge_payload(network_id=network_id, workspace_id=workspace_id, edges=edges)

        async def replace(tx):
            # Lock the plan's endpoints before the prune, keeping the revision-then-
            # node lock order shared with the event projector.
            await _lock_revisions(tx, _endpoint_ids(payload))
            deleted = await _prune_synthetic(tx, network_id=network_id, workspace_id=workspace_id,
                                             generator=generator)
            written = await _merge_edges(tx, edges=payload, network_id=network_id,
                                         workspace_id=workspace_id, locked=True) if payload else 0
            return deleted, written

        deleted, written = await self._write(replace)
        logger.info("topology_synthetic_edges_replaced", network_id=network_id, generator=generator,
                    deleted_edges=deleted, written_edges=written)
        return deleted, written

    async def backfill_missing_workspace_ids(self, db: AsyncSession, correlation_id: str = "") -> int:
        """Fill missing Device.workspace_id in Neo4j using Network module ownership data.

        Idempotent by design: only nodes with missing/empty workspace_id are updated.
        Safe to rerun: nodes already carrying workspace_id are untouched. Every graph
        statement runs in a bounded transaction and the PostgreSQL read ends before
        any graph write.
        """
        missing_query = """
        MATCH (d:Device)
        WHERE d.workspace_id IS NULL OR d.workspace_id = ''
        RETURN DISTINCT d.network_id AS network_id
        """

        async def missing(tx):
            return await (await tx.run(missing_query)).data()

        records = await self._read(missing)

        network_ids = [record.get("network_id") for record in records if record.get("network_id")]
        if not network_ids:
            logger.info(
                "topology_workspace_backfill_complete",
                correlation_id=correlation_id,
                missing_networks=0,
                updated_nodes=0,
            )
            return 0

        try:
            workspace_by_network = await NetworkRepository(db).get_workspace_ids_for_network_ids(network_ids)
        finally:
            await db.rollback()
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

        async def fill(tx, *, network_id: str, workspace_id: str) -> int:
            result = await tx.run(update_query, network_id=network_id, workspace_id=workspace_id)
            return _record_int(await result.single(), "updated")

        for network_id, workspace_id in workspace_by_network.items():
            updated_total += await self._write(fill, network_id=network_id, workspace_id=workspace_id)

        logger.info(
            "topology_workspace_backfill_complete",
            correlation_id=correlation_id,
            missing_networks=len(network_ids),
            mapped_networks=len(workspace_by_network),
            updated_nodes=updated_total,
        )
        return updated_total


# ---------------------------------------------------------------- tx functions


def _synthetic_edge_payload(*, network_id: str, workspace_id: str, edges: Sequence[PlannedEdge]) -> list[dict]:
    payload: list[dict[str, Any]] = []
    for edge in edges:
        if not edge.source_id or not edge.target_id or edge.source_id == edge.target_id:
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
        payload.append({"source_id": edge.source_id, "target_id": edge.target_id, "properties": properties})
    return payload


_MERGE_EDGES_QUERY = f"""
UNWIND $edges AS edge
MATCH (s:Device {{device_id: edge.source_id, network_id: $network_id, workspace_id: $workspace_id}})
MATCH (t:Device {{device_id: edge.target_id, network_id: $network_id, workspace_id: $workspace_id}})
WHERE s.device_id <> t.device_id AND {_ACTIVE.format(alias="s")} AND {_ACTIVE.format(alias="t")}
MERGE (s)-[r:CONNECTED_TO {{synthetic_owner: edge.properties.synthetic_owner, edge_key: edge.properties.edge_key}}]->(t)
SET r += edge.properties
RETURN count(r) AS written
"""

_PRUNE_SYNTHETIC_QUERY = """
MATCH (s:Device {network_id: $network_id, workspace_id: $workspace_id})
      -[r:CONNECTED_TO]->
      (t:Device {network_id: $network_id, workspace_id: $workspace_id})
WHERE r.synthetic = true AND r.generator = $generator
DELETE r
RETURN count(r) AS deleted
"""


async def _merge_edges(tx, *, edges: list[dict], network_id: str, workspace_id: str, locked: bool = False) -> int:
    if not locked:
        await _lock_revisions(tx, _endpoint_ids(edges))
    result = await tx.run(_MERGE_EDGES_QUERY, edges=edges, network_id=network_id, workspace_id=workspace_id)
    return _record_int(await result.single(), "written")


async def _prune_synthetic(tx, *, network_id: str, workspace_id: str, generator: str) -> int:
    result = await tx.run(_PRUNE_SYNTHETIC_QUERY, network_id=network_id, workspace_id=workspace_id,
                          generator=generator)
    return _record_int(await result.single(), "deleted")


def _device_projection(row: dict) -> dict:
    ip_address = row.get("ip_address")
    return {"device_id": str(row["device_id"]), "properties": {
        "hostname": row["hostname"], "device_type": row["device_type"],
        "ip_address": str(ip_address) if ip_address is not None else None,
        "vendor": row.get("vendor"), "model": row.get("model"), "location_hint": row.get("location_hint"),
        "spatial_ref_id": row.get("spatial_ref_id"),
    }}


_LOCK_REVISIONS_QUERY = """
UNWIND $device_ids AS device_id
MERGE (r:DeviceEventRevision {device_id: device_id})
SET r._lock = coalesce(r._lock, 0) + 1
"""

# Revision advance shared by reconcile writers: sequence moves to the watermark and
# the clock triple only moves forward (see apply_device_event).
_ADVANCE_REVISION = f"""
SET r.sequence = CASE WHEN r.sequence IS NULL OR r.sequence < $watermark THEN $watermark ELSE r.sequence END,
    r.rank = CASE WHEN r.epoch_us IS NULL OR r.epoch_us < $epoch_us THEN {_RECONCILE_RANK} ELSE r.rank END,
    r.event_id = CASE WHEN r.epoch_us IS NULL OR r.epoch_us < $epoch_us THEN $reconcile_id ELSE r.event_id END,
    r.epoch_us = CASE WHEN r.epoch_us IS NULL OR r.epoch_us < $epoch_us THEN $epoch_us ELSE r.epoch_us END
"""

_RECONCILE_UPSERT_QUERY = f"""
UNWIND $devices AS device
MATCH (r:DeviceEventRevision {{device_id: device.device_id}})
WHERE r.sequence IS NULL OR r.sequence <= $watermark
MERGE (d:Device {{device_id: device.device_id}})
SET d += device.properties, d.network_id = $network_id, d.workspace_id = $workspace_id, d.status = 'active',
    r.deleted = false
{_ADVANCE_REVISION}
RETURN count(d) AS upserted
"""

_RECONCILE_TOMBSTONE_QUERY = f"""
UNWIND $device_ids AS device_id
MATCH (r:DeviceEventRevision {{device_id: device_id}})
WHERE r.sequence IS NULL OR r.sequence <= $watermark
MATCH (d:Device {{device_id: device_id, network_id: $network_id}})
SET d.status = 'deleted', d.workspace_id = coalesce(d.workspace_id, $workspace_id), r.deleted = true
{_ADVANCE_REVISION}
WITH d
OPTIONAL MATCH (d)-[e:CONNECTED_TO]-()
DELETE e
RETURN count(DISTINCT d) AS tombstoned
"""


async def _lock_revisions(tx, device_ids: Sequence[str]) -> None:
    # Sorted, de-duplicated lock order keeps concurrent batch writers deadlock-free.
    ordered = sorted({str(device_id) for device_id in device_ids if device_id})
    if not ordered:
        return
    result = await tx.run(_LOCK_REVISIONS_QUERY, device_ids=ordered)
    await result.consume()


def _endpoint_ids(edges: Sequence[dict]) -> list[str]:
    """Every source/target device id of an edge payload (lock set of a writer)."""
    return sorted({device_id for edge in edges for device_id in (edge["source_id"], edge["target_id"])})


async def _reconcile_upsert(tx, *, devices: list[dict], network_id: str, workspace_id: str, watermark: int,
                            epoch_us: int, reconcile_id: str) -> int:
    await _lock_revisions(tx, [device["device_id"] for device in devices])
    result = await tx.run(_RECONCILE_UPSERT_QUERY, devices=devices, network_id=network_id,
                          workspace_id=workspace_id, watermark=watermark, epoch_us=epoch_us,
                          reconcile_id=reconcile_id)
    return _record_int(await result.single(), "upserted")


async def _reconcile_tombstone(tx, *, device_ids: list[str], network_id: str, workspace_id: str, watermark: int,
                               epoch_us: int, reconcile_id: str) -> int:
    await _lock_revisions(tx, device_ids)
    result = await tx.run(_RECONCILE_TOMBSTONE_QUERY, device_ids=device_ids, network_id=network_id,
                          workspace_id=workspace_id, watermark=watermark, epoch_us=epoch_us,
                          reconcile_id=reconcile_id)
    return _record_int(await result.single(), "tombstoned")


async def _projected_device_ids(tx, *, network_id: str) -> list[str]:
    result = await tx.run(f"""
        MATCH (d:Device {{network_id: $network_id}})
        WHERE {_ACTIVE.format(alias="d")}
        RETURN d.device_id AS device_id
    """, network_id=network_id)
    return [row["device_id"] for row in await result.data() if row.get("device_id")]


async def _count_missing_workspace(tx, *, network_id: str) -> int:
    result = await tx.run("""
        MATCH (d:Device {network_id: $network_id})
        WHERE d.workspace_id IS NULL OR d.workspace_id = ''
        RETURN count(d) AS missing
    """, network_id=network_id)
    return _record_int(await result.single(), "missing")


async def _network_totals(tx, *, network_id: str) -> dict:
    result = await tx.run("""
        MATCH (d:Device {network_id: $network_id})
        WITH count(d) AS nodes,
             sum(CASE WHEN d.workspace_id IS NULL OR d.workspace_id = '' THEN 1 ELSE 0 END) AS missing_workspace
        OPTIONAL MATCH (:Device {network_id: $network_id})-[e:CONNECTED_TO]->(:Device {network_id: $network_id})
        RETURN nodes, missing_workspace, count(e) AS edges
    """, network_id=network_id)
    record = await result.single()
    return {"nodes": _record_int(record, "nodes"), "edges": _record_int(record, "edges"),
            "missing_workspace": _record_int(record, "missing_workspace")}
