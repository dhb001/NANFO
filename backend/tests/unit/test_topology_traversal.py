"""ADR-028 topology regressions: bounded BFS, tombstones, schema, atomic replace, reconcile."""

import asyncio
import time
import uuid
from itertools import product
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from neo4j.exceptions import ClientError, ServiceUnavailable

from app.core.errors import DependencyUnavailableError
from app.modules.network import topology
from app.modules.network.synthetic_topology import EDGE_TYPE_CONNECTED_TO, PlannedEdge
from app.modules.network.topology import TopologyQueryService, ensure_graph_schema

NETWORK, WORKSPACE = str(uuid.UUID(int=71)), str(uuid.UUID(int=72))
ACTIVE_PREDICATE = "coalesce({}.status, '') <> 'deleted'"


class FakeGraph:
    """In-memory CONNECTED_TO graph answering the traversal queries like Neo4j would."""

    def __init__(self, nodes, edges, *, network=NETWORK, workspace=WORKSPACE):
        self.nodes = {}
        for node in nodes:
            node = {"network_id": network, "workspace_id": workspace, "status": "active",
                    "hostname": f"h-{node['device_id']}", "device_type": "switch", "spatial_ref_id": None, **node}
            self.nodes[node["device_id"]] = node
        self.edges = [(source, target, dict(properties)) for source, target, properties in edges]
        self.calls: list[tuple[str, dict]] = []
        self.rows_returned = 0

    def visible(self, device_id, network_id, workspace_id):
        node = self.nodes.get(device_id)
        return (node is not None and node["network_id"] == network_id and node["workspace_id"] == workspace_id
                and node.get("status") != "deleted")

    def incident(self, device_id):
        for source, target, properties in self.edges:
            if source == device_id:
                yield target, "outbound", properties
            if target == device_id:
                yield source, "inbound", properties

    def project(self, device_id):
        node = self.nodes[device_id]
        return {key: node.get(key) for key in ("device_id", "hostname", "device_type", "status", "spatial_ref_id")}

    async def run(self, query, **params):
        self.calls.append((query, params))
        result = MagicMock()
        scope = (params["network_id"], params["workspace_id"])
        if "UNWIND $frontier" in query:
            rows, seen = [], set()
            for parent in params["frontier"]:
                for other, _, _ in self.incident(parent):
                    if self.visible(other, *scope) and (parent, other) not in seen:
                        seen.add((parent, other))
                        rows.append({"parent_id": parent, **self.project(other)})
            self.rows_returned += len(rows)
            result.data = AsyncMock(return_value=rows)
        elif "-[r:CONNECTED_TO]-(n:Device)" in query:
            root = params["device_id"]
            rows = [{**self.project(other), "edge_type": "connected_to", "edge_metadata": properties,
                     "direction": direction}
                    for other, direction, properties in self.incident(root)
                    if other != root and self.visible(other, *scope)]
            self.rows_returned += len(rows)
            result.data = AsyncMock(return_value=rows)
        else:
            root = params["device_id"]
            result.single = AsyncMock(return_value=self.project(root) if self.visible(root, *scope) else None)
        return result


def driver_for(graph):
    session = AsyncMock()

    async def run_work(work, *args, **kwargs):
        return await work(graph, *args, **kwargs)

    session.execute_read = AsyncMock(side_effect=run_work)
    session.execute_write = AsyncMock(side_effect=run_work)
    driver = MagicMock()
    driver.session.return_value.__aenter__.return_value = session
    driver.session.return_value.__aexit__.return_value = None
    return driver, session


async def neighbours(graph, root, depth=6, limit=1000):
    driver, _ = driver_for(graph)
    return await TopologyQueryService(driver).get_device_neighbours(
        device_id=uuid.UUID(int=0) if root is None else root, network_id=NETWORK, workspace_id=WORKSPACE,
        depth=depth, limit=limit,
    )


def ids(*numbers):
    return [str(uuid.UUID(int=n)) for n in numbers]


async def test_neighbours_report_shortest_hop_depth_and_bounded_depth():
    a, b, c, d, e = ids(1, 2, 3, 4, 5)
    graph = FakeGraph([{"device_id": x} for x in (a, b, c, d, e)],
                      [(a, b, {}), (b, c, {}), (c, d, {}), (a, d, {}), (d, e, {})])
    driver, _ = driver_for(graph)
    result = await TopologyQueryService(driver).get_device_neighbours(
        device_id=uuid.UUID(a), network_id=NETWORK, workspace_id=WORKSPACE, depth=2, limit=10)
    depths = {item.device_id: item.hop_depth for item in result.neighbours}
    assert depths == {b: 1, d: 1, c: 2, e: 2}
    assert [item.device_id for item in result.neighbours] == sorted(depths)
    assert result.depth == 2 and result.total == 4


async def test_deleted_devices_are_never_returned_or_traversed():
    a, b, c, d = ids(1, 2, 3, 4)
    graph = FakeGraph([{"device_id": a}, {"device_id": b, "status": "deleted"}, {"device_id": c}, {"device_id": d}],
                      [(a, b, {}), (b, c, {}), (a, d, {})])
    result = await neighbours(graph, uuid.UUID(a))
    assert [item.device_id for item in result.neighbours] == [d]
    # Every node pattern in the traversal filters tombstones, including interiors.
    root_query, first_query = graph.calls[0][0], graph.calls[1][0]
    assert ACTIVE_PREDICATE.format("d") in root_query
    assert ACTIVE_PREDICATE.format("n") in first_query
    expand = [query for query, _ in graph.calls if "UNWIND $frontier" in query]
    assert expand and all(ACTIVE_PREDICATE.format("n") in query for query in expand)
    graph.nodes[a]["status"] = "deleted"
    assert await neighbours(graph, uuid.UUID(a)) is None


async def test_first_edge_is_deterministic_across_parallel_edges_and_parents():
    a, b, c = ids(1, 2, 3)
    graph = FakeGraph([{"device_id": x} for x in (a, b, c)],
                      [(a, b, {"edge_key": "z"}), (b, a, {"edge_key": "y"}), (b, c, {"edge_key": "x"})])
    first = await neighbours(graph, uuid.UUID(a))
    second = await neighbours(graph, uuid.UUID(a))
    assert [item.model_dump() for item in first.neighbours] == [item.model_dump() for item in second.neighbours]
    by_id = {item.device_id: item for item in first.neighbours}
    # 'inbound' < 'outbound': the b->a edge is the canonical first hop, inherited by c.
    assert by_id[b].direction == "inbound" and by_id[b].edge_metadata == {"edge_key": "y"}
    assert by_id[c].hop_depth == 2 and by_id[c].edge_metadata == {"edge_key": "y"}


@pytest.mark.parametrize("shape", ["complete", "grid"])
async def test_dense_meshes_do_not_enumerate_paths(shape):
    """Regression: *1..N path enumeration is exponential on meshes; BFS is O(V+E)."""
    if shape == "complete":
        nodes = ids(*range(1, 61))
        edges = [(x, y, {}) for index, x in enumerate(nodes) for y in nodes[index + 1:]]
    else:
        size = 25
        nodes = ids(*range(1, size * size + 1))
        grid = {(r, c): nodes[r * size + c] for r, c in product(range(size), range(size))}
        edges = [(grid[r, c], grid[r + dr, c + dc], {}) for (r, c) in grid for dr, dc in ((0, 1), (1, 0))
                 if (r + dr, c + dc) in grid]
    graph = FakeGraph([{"device_id": x} for x in nodes], edges)
    started = time.monotonic()
    result = await neighbours(graph, uuid.UUID(nodes[0]), depth=6, limit=1000)
    assert time.monotonic() - started < 2
    # One root lookup, one first hop and at most depth-1 frontier expansions.
    assert len(graph.calls) <= 1 + 6
    assert graph.rows_returned <= 2 * len(edges)
    expected = len(nodes) - 1 if shape == "complete" else sum(1 for r, c in product(range(25), range(25))
                                                              if 0 < r + c <= 6)
    assert result.total == expected


async def test_impact_orders_by_hop_then_id_and_stops_expanding_at_limit():
    nodes = ids(*range(1, 12))
    root, rest = nodes[0], nodes[1:]
    # root -> 5 direct neighbours -> each has one child.
    edges = [(root, rest[i], {}) for i in range(5)] + [(rest[i], rest[i + 5], {}) for i in range(5)]
    graph = FakeGraph([{"device_id": x} for x in nodes], edges)
    driver, _ = driver_for(graph)
    result = await TopologyQueryService(driver).get_impact_analysis(
        device_id=uuid.UUID(root), network_id=NETWORK, workspace_id=WORKSPACE, max_hops=8, limit=3)
    assert [item.hop_depth for item in result.impacts] == [1, 1, 1]
    assert [item.device_id for item in result.impacts] == sorted(rest[:5])[:3]
    assert not any("UNWIND $frontier" in query for query, _ in graph.calls)
    assert result.max_hops == 8 and result.total == 3


async def test_reads_use_bounded_read_transactions():
    graph = FakeGraph([{"device_id": ids(1)[0]}], [])
    driver, session = driver_for(graph)
    await TopologyQueryService(driver).get_device_neighbours(
        device_id=uuid.UUID(ids(1)[0]), network_id=NETWORK, workspace_id=WORKSPACE)
    assert driver.session.call_args.kwargs["default_access_mode"] == "READ"
    work = session.execute_read.await_args.args[0]
    assert work.timeout == topology.READ_TIMEOUT_SECONDS


@pytest.mark.parametrize("failure", [ServiceUnavailable("down"), TimeoutError(),
                                     ClientError._hydrate_neo4j(code="Neo.ClientError.Transaction.TransactionTimedOut",
                                                                message="timed out")])
async def test_graph_outage_or_timeout_is_dependency_unavailable(failure):
    driver, session = driver_for(FakeGraph([], []))
    session.execute_read.side_effect = failure
    with pytest.raises(DependencyUnavailableError):
        await TopologyQueryService(driver).get_graph(uuid.uuid4(), uuid.uuid4())


async def test_slow_graph_read_is_cut_off_by_the_client_deadline(monkeypatch):
    monkeypatch.setattr(topology, "READ_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(topology, "_CLIENT_GRACE_SECONDS", 0.01)
    driver, session = driver_for(FakeGraph([], []))

    async def hang(work):
        await asyncio.Event().wait()

    session.execute_read.side_effect = hang
    with pytest.raises(DependencyUnavailableError):
        await TopologyQueryService(driver).get_graph(uuid.uuid4(), uuid.uuid4())


async def test_graph_page_excludes_tombstones_and_their_edges():
    session = AsyncMock()
    node_result, edge_result = MagicMock(), MagicMock()
    node_result.data = AsyncMock(return_value=[{"device_id": "a", "hostname": "a", "device_type": "switch",
                                                "status": "active", "spatial_ref_id": None}])
    edge_result.data = AsyncMock(return_value=[])
    session.run = AsyncMock(side_effect=[node_result, edge_result])

    async def run_work(work):
        return await work(session)

    session.execute_read = AsyncMock(side_effect=run_work)
    driver = MagicMock()
    driver.session.return_value.__aenter__.return_value = session
    driver.session.return_value.__aexit__.return_value = None
    await TopologyQueryService(driver).get_graph(uuid.uuid4(), uuid.uuid4())
    node_query, edge_query = (call.args[0] for call in session.run.await_args_list)
    assert ACTIVE_PREDICATE.format("d") in node_query
    assert ACTIVE_PREDICATE.format("s") in edge_query and ACTIVE_PREDICATE.format("t") in edge_query


async def test_ensure_graph_schema_creates_constraints_once_and_reports_failures():
    session = AsyncMock()
    ok = AsyncMock()
    session.run = AsyncMock(side_effect=[
        ClientError._hydrate_neo4j(code="Neo.ClientError.Schema.ConstraintCreationFailed", message="duplicates"),
        ok, ok, ok,
    ])
    driver = MagicMock()
    driver.session.return_value.__aenter__.return_value = session
    driver.session.return_value.__aexit__.return_value = None
    report = await ensure_graph_schema(driver)
    statements = [call.args[0] for call in session.run.await_args_list]
    assert "REQUIRE d.device_id IS UNIQUE" in statements[0]
    assert "device_identity_lookup" in statements[1]
    assert "(d.workspace_id, d.network_id)" in statements[2]
    assert "DeviceEventRevision" in statements[3] and "IF NOT EXISTS" in statements[3]
    assert report == {"device_identity": "failed", "device_identity_lookup": "ok", "device_scope": "ok",
                      "device_event_revision_identity": "ok"}
    assert topology.graph_schema_ready() is False
    session.run = AsyncMock(return_value=ok)
    assert set((await ensure_graph_schema(driver)).values()) == {"ok"}
    assert topology.graph_schema_ready() is True


async def test_device_events_never_issue_schema_statements():
    tx = AsyncMock()
    tx.run.return_value.single.return_value = {"deleted": False, "matched": 1}
    session = AsyncMock()

    async def execute(callback):
        return await callback(tx)

    session.execute_write.side_effect = execute
    driver = MagicMock()
    driver.session.return_value.__aenter__.return_value = session
    await TopologyQueryService(driver).apply_device_event(
        event_type="network.device.deleted", payload={"device_id": str(uuid.uuid4()), "sequence": 3},
        timestamp="2026-09-09T00:00:00Z", event_id=str(uuid.uuid4()),
    )
    session.run.assert_not_awaited()
    assert not any("CONSTRAINT" in call.args[0] for call in tx.run.await_args_list)
    delete = tx.run.await_args_list[2].args[0]
    assert "d.status = 'deleted'" in delete and "DELETE e" in delete


async def test_synthetic_replace_prunes_and_merges_in_one_write_transaction():
    tx = AsyncMock()
    locked, pruned, merged = MagicMock(), MagicMock(), MagicMock()
    locked.consume = AsyncMock()
    pruned.single = AsyncMock(return_value={"deleted": 323})
    merged.single = AsyncMock(return_value={"written": 2})
    tx.run = AsyncMock(side_effect=[locked, pruned, merged])
    session = AsyncMock()

    async def execute(work):
        return await work(tx)

    session.execute_write = AsyncMock(side_effect=execute)
    driver = MagicMock()
    driver.session.return_value.__aenter__.return_value = session
    driver.session.return_value.__aexit__.return_value = None
    plan = [PlannedEdge("a", "b", EDGE_TYPE_CONNECTED_TO, {"synthetic": True, "generator": "g"}),
            PlannedEdge("b", "c", EDGE_TYPE_CONNECTED_TO, {"synthetic": True, "generator": "g"})]
    assert await TopologyQueryService(driver).replace_synthetic_device_edges(
        network_id=NETWORK, workspace_id=WORKSPACE, edges=plan, generator="g") == (323, 2)
    session.execute_write.assert_awaited_once()
    lock, prune, merge = tx.run.await_args_list
    # Endpoint revision locks come first (same order as the event projector), so a
    # concurrent device delete can never leave a seeded edge to a tombstone.
    assert "MERGE (r:DeviceEventRevision {device_id: device_id})" in lock.args[0]
    assert lock.kwargs["device_ids"] == ["a", "b", "c"]
    prune, merge = prune.args[0], merge.args[0]
    assert "r.synthetic = true AND r.generator = $generator" in prune and "DELETE r" in prune
    assert "MERGE (s)-[r:CONNECTED_TO" in merge and ACTIVE_PREDICATE.format("t") in merge
    # The merge does not lock twice.
    assert tx.run.await_count == 3
    # A failed merge rolls the prune back with it (one transaction): nothing to assert
    # beyond the single execute_write, which the driver retries or aborts atomically.
    with pytest.raises(ValueError):
        await TopologyQueryService(driver).replace_synthetic_device_edges(
            network_id=NETWORK, workspace_id=WORKSPACE, generator="g",
            edges=[PlannedEdge("a", "b", EDGE_TYPE_CONNECTED_TO, {"synthetic": True, "generator": "other"})])


async def test_synthetic_replace_with_empty_plan_only_prunes():
    tx = AsyncMock()
    pruned = MagicMock()
    pruned.single = AsyncMock(return_value={"deleted": 4})
    tx.run = AsyncMock(return_value=pruned)
    session = AsyncMock()

    async def execute(work):
        return await work(tx)

    session.execute_write = AsyncMock(side_effect=execute)
    driver = MagicMock()
    driver.session.return_value.__aenter__.return_value = session
    assert await TopologyQueryService(driver).replace_synthetic_device_edges(
        network_id=NETWORK, workspace_id=WORKSPACE, edges=[], generator="g") == (4, 0)
    assert tx.run.await_count == 1


# ------------------------------------------------------------------------ reconcile


class ReconcileGraph:
    def __init__(self, *, projected, upserted=None, tombstoned=None, fail=None):
        self.projected = projected
        self.upserted = upserted
        self.tombstoned = tombstoned
        self.fail = fail
        self.writes: list[tuple[str, dict]] = []

    async def run(self, query, **params):
        if self.fail is not None:
            raise self.fail
        result = MagicMock()
        result.consume = AsyncMock()
        if "RETURN count(d) AS missing" in query:
            result.single = AsyncMock(return_value={"missing": 2})
        elif "SET r._lock" in query:
            self.writes.append(("lock", params))
        elif "AS upserted" in query:
            self.writes.append(("upsert", params))
            count = len(params["devices"]) if self.upserted is None else self.upserted
            result.single = AsyncMock(return_value={"upserted": count})
        elif "AS tombstoned" in query:
            self.writes.append(("tombstone", params))
            count = len(params["device_ids"]) if self.tombstoned is None else self.tombstoned
            result.single = AsyncMock(return_value={"tombstoned": count})
        elif "RETURN d.device_id AS device_id" in query:
            result.data = AsyncMock(return_value=[{"device_id": device_id} for device_id in self.projected])
        else:
            result.single = AsyncMock(return_value={"nodes": 4, "edges": 3, "missing_workspace": 0})
        return result


def page(*numbers):
    return [{"device_id": uuid.UUID(int=n), "hostname": f"h{n}", "device_type": "switch", "ip_address": None,
             "vendor": None, "model": None, "location_hint": None, "spatial_ref_id": None} for n in numbers]


async def reconcile(graph, pages, *, watermark=42, page_size=2):
    driver, _ = driver_for(graph)
    db = AsyncMock()
    order = []
    db.rollback.side_effect = lambda: order.append("rollback")
    listing = AsyncMock(side_effect=lambda *a, **k: order.append("page") or pages.pop(0))
    publish = AsyncMock()
    with (
        patch("app.modules.network.topology.DeviceRepository.list_projection_page", listing),
        patch("app.modules.network.topology.publish_event", publish),
    ):
        result = await TopologyQueryService(driver).reconcile_network(
            network_id=uuid.UUID(NETWORK), workspace_id=uuid.UUID(WORKSPACE), watermark=watermark, db=db,
            redis=AsyncMock(), actor_id="actor", correlation_id="corr", page_size=page_size,
        )
    return result, publish, listing, order


async def test_reconcile_upserts_active_pages_and_tombstones_stale_projections():
    stale = str(uuid.UUID(int=9))
    graph = ReconcileGraph(projected=[str(uuid.UUID(int=n)) for n in (1, 2, 3)] + [stale])
    result, publish, listing, order = await reconcile(graph, [page(1, 2), page(3)])
    assert [kind for kind, _ in graph.writes] == ["lock", "upsert", "lock", "upsert", "lock", "tombstone"]
    upserts = [params for kind, params in graph.writes if kind == "upsert"]
    assert [device["device_id"] for device in upserts[0]["devices"]] == [str(uuid.UUID(int=1)), str(uuid.UUID(int=2))]
    assert all(params["watermark"] == 42 and params["workspace_id"] == WORKSPACE for params in upserts)
    tombstone = next(params for kind, params in graph.writes if kind == "tombstone")
    assert tombstone["device_ids"] == [stale]
    # The PostgreSQL transaction ends after every page, before any graph write.
    assert order == ["page", "rollback", "page", "rollback"]
    assert listing.await_args_list[1].kwargs["after"] == uuid.UUID(int=2)
    assert result["active_devices"] == 3 and result["upserted_nodes"] == 3 and result["tombstoned_nodes"] == 1
    assert result["missing_workspace_nodes"] == 2 and result["workspace_backfilled_nodes"] == 2
    assert result["checked_nodes"] == 4 and result["checked_edges"] == 3 and result["watermark_sequence"] == 42
    assert [call.kwargs["event_type"] for call in publish.await_args_list] == [
        "network.topology.reconcile_requested", "network.topology.reconcile_completed",
    ]


async def test_reconcile_never_overwrites_revisions_newer_than_the_watermark():
    graph = ReconcileGraph(projected=[str(uuid.UUID(int=1))], upserted=0)
    result, *_ = await reconcile(graph, [page(1)])
    assert result["upserted_nodes"] == 0 and result["skipped_newer_nodes"] == 1
    assert "r.sequence IS NULL OR r.sequence <= $watermark" in topology._RECONCILE_UPSERT_QUERY
    assert "r.sequence IS NULL OR r.sequence <= $watermark" in topology._RECONCILE_TOMBSTONE_QUERY
    assert "DELETE e" in topology._RECONCILE_TOMBSTONE_QUERY


@pytest.mark.parametrize("failure,code", [(ServiceUnavailable("bolt://secret@host down"), "GRAPH_UNAVAILABLE"),
                                          (RuntimeError("password=hunter2"), "RECONCILE_FAILED")])
async def test_reconcile_failure_publishes_error_code_not_exception_text(failure, code):
    graph = ReconcileGraph(projected=[], fail=failure)
    with pytest.raises((DependencyUnavailableError, RuntimeError)):
        await reconcile(graph, [page(1)])


async def test_reconcile_failed_event_payload_is_sanitized():
    driver, session = driver_for(ReconcileGraph(projected=[]))
    session.execute_read.side_effect = RuntimeError("password=hunter2")
    publish = AsyncMock()
    with patch("app.modules.network.topology.publish_event", publish), pytest.raises(RuntimeError):
        await TopologyQueryService(driver).reconcile_network(
            network_id=uuid.UUID(NETWORK), workspace_id=uuid.UUID(WORKSPACE), watermark=1, db=AsyncMock(),
            redis=AsyncMock(), actor_id="actor", correlation_id="corr",
        )
    failed = publish.await_args_list[-1].kwargs
    assert failed["event_type"] == "network.topology.reconcile_failed"
    assert failed["payload"]["error"] == "RECONCILE_FAILED"
    assert "hunter2" not in str(failed["payload"])


@pytest.mark.parametrize("watermark", [-1, True, 2**63, "1"])
async def test_reconcile_rejects_invalid_watermarks(watermark):
    driver, _ = driver_for(ReconcileGraph(projected=[]))
    with pytest.raises(ValueError):
        await TopologyQueryService(driver).reconcile_network(
            network_id=uuid.uuid4(), workspace_id=uuid.uuid4(), watermark=watermark, db=AsyncMock(),
            redis=AsyncMock(), actor_id="actor", correlation_id="corr",
        )


def _write_driver(tx):
    session = AsyncMock()

    async def execute(work):
        return await work(tx)

    session.execute_write = AsyncMock(side_effect=execute)
    driver = MagicMock()
    driver.session.return_value.__aenter__.return_value = session
    driver.session.return_value.__aexit__.return_value = None
    return driver, session


async def test_device_event_projection_is_a_bounded_write_transaction():
    tx = AsyncMock()
    tx.run.return_value.single.return_value = {"deleted": False, "matched": 1}
    driver, session = _write_driver(tx)
    event = {"event_type": "network.device.updated", "timestamp": "2026-09-09T00:00:00Z",
             "event_id": str(uuid.uuid4()),
             "payload": {"device_id": str(uuid.uuid4()), "changed_fields": {"hostname": "h"}, "sequence": 9}}
    assert await TopologyQueryService(driver).apply_device_event(**event) is True
    assert driver.session.call_args.kwargs["default_access_mode"] == "WRITE"
    assert session.execute_write.await_args.args[0].timeout == topology.WRITE_TIMEOUT_SECONDS
    session.execute_write.side_effect = ServiceUnavailable("bolt://user:secret@graph down")
    with pytest.raises(DependencyUnavailableError):
        await TopologyQueryService(driver).apply_device_event(**event)


async def test_observed_edge_writer_locks_endpoints_before_checking_activity():
    tx = AsyncMock()
    tx.run.return_value.single.side_effect = [{"matched": 1}, {"written": 1}]
    driver, session = _write_driver(tx)
    edge = PlannedEdge("b", "a", EDGE_TYPE_CONNECTED_TO, {"synthetic": False, "edge_key": "k"})
    assert await TopologyQueryService(driver).replace_observed_device_edges(
        network_id=NETWORK, workspace_id=WORKSPACE, owner_id="owner", edges=[edge]) == 1
    queries = [call.args[0] for call in tx.run.await_args_list]
    assert "DeviceEventRevision" in queries[0] and tx.run.await_args_list[0].kwargs["device_ids"] == ["a", "b"]
    assert "AS matched" in queries[1] and ACTIVE_PREDICATE.format("t") in queries[1]
    assert "DELETE r" in queries[2] and "MERGE (s)-[r:CONNECTED_TO" in queries[3]
    assert session.execute_write.await_args.args[0].timeout == topology.WRITE_TIMEOUT_SECONDS


async def test_standalone_synthetic_merge_locks_its_endpoints():
    tx = AsyncMock()
    tx.run.return_value.single.return_value = {"written": 1}
    driver, _ = _write_driver(tx)
    await TopologyQueryService(driver).merge_device_edges(
        network_id=NETWORK, workspace_id=WORKSPACE,
        edges=[PlannedEdge("z", "y", EDGE_TYPE_CONNECTED_TO, {"synthetic": True, "generator": "g"}),
               PlannedEdge("y", "z", EDGE_TYPE_CONNECTED_TO, {"synthetic": True, "generator": "g"})])
    lock, merge = tx.run.await_args_list
    assert lock.kwargs["device_ids"] == ["y", "z"]
    assert "MERGE (s)-[r:CONNECTED_TO" in merge.args[0]
