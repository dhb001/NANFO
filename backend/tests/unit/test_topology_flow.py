"""Unit tests for topology event flow updates in VS2 step 1.

Verifies `workspace_id` propagation from network.device.added events into Neo4j
Device node writes, per docs/features/Topology.md §6.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from neo4j import Record

from app.events.consumers.topology_consumer import handle_topology_event
from app.modules.network.repository import NetworkRepository
from app.modules.network.synthetic_topology import EDGE_TYPE_CONNECTED_TO, PlannedEdge
from app.modules.network.topology import TopologyQueryService, _record_int


@pytest.mark.asyncio
async def test_topology_consumer_passes_workspace_id_on_device_added():
    payload = {
        "device_id": str(uuid.uuid4()),
        "network_id": str(uuid.uuid4()),
        "workspace_id": str(uuid.uuid4()),
        "hostname": "edge-router-01",
        "device_type": "router",
        "spatial_ref_id": "campus-a/building-1/floor-2/room-204/rack-3/device-edge-router-01",
    }
    event = {"event_type": "network.device.added", "payload": payload}

    svc = MagicMock()
    svc.create_device_node = AsyncMock()

    with (
        patch("app.events.consumers.topology_consumer.get_neo4j_driver", return_value=MagicMock()),
        patch("app.events.consumers.topology_consumer.TopologyQueryService", return_value=svc),
    ):
        await handle_topology_event(event)

    svc.create_device_node.assert_awaited_once_with(
        device_id=payload["device_id"],
        network_id=payload["network_id"],
        workspace_id=payload["workspace_id"],
        hostname=payload["hostname"],
        device_type=payload["device_type"],
        spatial_ref_id=payload["spatial_ref_id"],
        status="active",
    )


@pytest.mark.asyncio
async def test_topology_consumer_updates_spatial_ref_id_on_device_updated_event():
    payload = {
        "device_id": str(uuid.uuid4()),
        "changed_fields": {
            "spatial_ref_id": "campus-a/building-1/floor-2/room-204/rack-3/device-edge-router-01",
        },
    }
    event = {"event_type": "network.device.updated", "payload": payload}

    session = AsyncMock()
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    with patch("app.events.consumers.topology_consumer.get_neo4j_driver", return_value=driver):
        await handle_topology_event(event)

    session.run.assert_awaited_once()
    query = session.run.await_args.args[0]
    params = session.run.await_args.kwargs
    assert "SET d.spatial_ref_id = $spatial_ref_id" in query
    assert params["device_id"] == payload["device_id"]
    assert params["spatial_ref_id"] == payload["changed_fields"]["spatial_ref_id"]


@pytest.mark.asyncio
async def test_create_device_node_sets_workspace_id_property():
    session = AsyncMock()
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    await svc.create_device_node(
        device_id=str(uuid.uuid4()),
        network_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        hostname="core-switch-01",
        device_type="switch",
        spatial_ref_id="campus-a/device-core-switch-01",
    )

    session.run.assert_awaited_once()
    query = session.run.await_args.args[0]
    params = session.run.await_args.kwargs

    assert "d.workspace_id = $workspace_id" in query
    assert "d.spatial_ref_id = $spatial_ref_id" in query
    assert params["workspace_id"]
    assert params["spatial_ref_id"] == "campus-a/device-core-switch-01"


@pytest.mark.asyncio
async def test_backfill_missing_workspace_ids_updates_only_missing_nodes():
    first_result = MagicMock()
    first_result.data = AsyncMock(return_value=[
        {"network_id": str(uuid.uuid4())},
        {"network_id": str(uuid.uuid4())},
    ])

    update_result_1 = MagicMock()
    update_result_1.single = AsyncMock(return_value={"updated": 2})
    update_result_2 = MagicMock()
    update_result_2.single = AsyncMock(return_value={"updated": 0})

    session = AsyncMock()
    session.run = AsyncMock(side_effect=[first_result, update_result_1, update_result_2])
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    db = AsyncMock()

    network_ids = [
        first_result.data.return_value[0]["network_id"],
        first_result.data.return_value[1]["network_id"],
    ]
    workspace_map = {
        network_ids[0]: str(uuid.uuid4()),
        network_ids[1]: str(uuid.uuid4()),
    }

    with patch.object(
        NetworkRepository,
        "get_workspace_ids_for_network_ids",
        new=AsyncMock(return_value=workspace_map),
    ) as workspace_lookup:
        updated = await TopologyQueryService(driver=driver).backfill_missing_workspace_ids(
            db=db,
            correlation_id="corr-1",
        )

    assert updated == 2
    workspace_lookup.assert_awaited_once_with(network_ids)
    assert session.run.await_count == 3
    assert "WHERE d.workspace_id IS NULL OR d.workspace_id = ''" in session.run.await_args_list[1].args[0]


@pytest.mark.asyncio
async def test_backfill_missing_workspace_ids_is_noop_when_nothing_missing():
    first_result = MagicMock()
    first_result.data = AsyncMock(return_value=[])

    session = AsyncMock()
    session.run = AsyncMock(return_value=first_result)
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    db = AsyncMock()

    with patch.object(
        NetworkRepository,
        "get_workspace_ids_for_network_ids",
        new=AsyncMock(),
    ) as workspace_lookup:
        updated = await TopologyQueryService(driver=driver).backfill_missing_workspace_ids(
            db=db,
            correlation_id="corr-2",
        )

    assert updated == 0
    workspace_lookup.assert_not_awaited()
    session.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_network_repository_get_workspace_ids_for_network_ids_ignores_invalid_ids(mock_db):
    valid_network_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    result = MagicMock()
    result.all.return_value = [(valid_network_id, workspace_id)]
    mock_db.execute = AsyncMock(return_value=result)

    repo = NetworkRepository(mock_db)
    mapping = await repo.get_workspace_ids_for_network_ids([
        str(valid_network_id),
        "not-a-uuid",
        "",
    ])

    assert mapping == {str(valid_network_id): str(workspace_id)}
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_network_repository_get_workspace_ids_for_network_ids_returns_empty_without_valid_ids(mock_db):
    repo = NetworkRepository(mock_db)
    mapping = await repo.get_workspace_ids_for_network_ids(["invalid", "also-invalid"])

    assert mapping == {}
    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_graph_paginates_and_returns_next_cursor_with_stable_order():
    node_rows = [
        {
            "device_id": "a",
            "hostname": "a-host",
            "device_type": "router",
            "status": "active",
            "spatial_ref_id": "campus-a/device-a",
        },
        {
            "device_id": "b",
            "hostname": "b-host",
            "device_type": "switch",
            "status": "active",
            "spatial_ref_id": None,
        },
        {
            "device_id": "c",
            "hostname": "c-host",
            "device_type": "switch",
            "status": "active",
            "spatial_ref_id": None,
        },
    ]
    edge_rows = [{"source_id": "a", "target_id": "b"}]

    node_result = MagicMock()
    node_result.data = AsyncMock(return_value=node_rows)
    edge_result = MagicMock()
    edge_result.data = AsyncMock(return_value=edge_rows)

    session = AsyncMock()
    session.run = AsyncMock(side_effect=[node_result, edge_result])
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result, next_cursor = await svc.get_graph(
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        limit=2,
        cursor="prev-cursor",
    )

    assert [n.device_id for n in result.nodes] == ["a", "b"]
    assert len(result.edges) == 1
    assert result.edges[0].source_id == "a"
    assert result.edges[0].target_id == "b"
    assert result.nodes[0].spatial_ref_id == "campus-a/device-a"
    assert result.nodes[1].spatial_ref_id is None
    assert next_cursor == "b"

    first_call = session.run.await_args_list[0]
    assert first_call.kwargs["fetch_limit"] == 3
    assert first_call.kwargs["cursor"] == "prev-cursor"
    assert first_call.kwargs["workspace_id"]

    second_call = session.run.await_args_list[1]
    assert second_call.kwargs["workspace_id"]


@pytest.mark.asyncio
async def test_get_graph_returns_none_next_cursor_when_last_page():
    node_rows = [
        {
            "device_id": "a",
            "hostname": "a-host",
            "device_type": "router",
            "status": "active",
            "spatial_ref_id": "campus-a/device-a",
        },
        {
            "device_id": "b",
            "hostname": "b-host",
            "device_type": "switch",
            "status": "active",
            "spatial_ref_id": "campus-a/device-b",
        },
    ]
    edge_rows = []

    node_result = MagicMock()
    node_result.data = AsyncMock(return_value=node_rows)
    edge_result = MagicMock()
    edge_result.data = AsyncMock(return_value=edge_rows)

    session = AsyncMock()
    session.run = AsyncMock(side_effect=[node_result, edge_result])
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result, next_cursor = await svc.get_graph(
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        limit=2,
        cursor=None,
    )

    assert [n.device_id for n in result.nodes] == ["a", "b"]
    assert result.nodes[0].spatial_ref_id == "campus-a/device-a"
    assert result.nodes[1].spatial_ref_id == "campus-a/device-b"
    assert result.edges == []
    assert next_cursor is None


@pytest.mark.asyncio
async def test_get_graph_returns_empty_page_without_edge_query_when_no_nodes():
    node_result = MagicMock()
    node_result.data = AsyncMock(return_value=[])

    session = AsyncMock()
    session.run = AsyncMock(return_value=node_result)
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result, next_cursor = await svc.get_graph(network_id=uuid.uuid4(), workspace_id=uuid.uuid4(), limit=5)

    assert result.nodes == []
    assert result.edges == []
    assert next_cursor is None
    session.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_node_with_neighbours_returns_node_and_sorted_neighbours():
    record = {
        "node": {
            "device_id": "device-1",
            "hostname": "core-1",
            "device_type": "router",
            "status": "active",
            "spatial_ref_id": "campus-a/core-1",
        },
        "neighbours": [
            {
                "device_id": "device-3",
                "hostname": "edge-3",
                "device_type": "switch",
                "status": "active",
                "spatial_ref_id": None,
                "edge_type": "connected_to",
                "direction": "outbound",
            },
            {
                "device_id": "device-2",
                "hostname": "edge-2",
                "device_type": "switch",
                "status": "active",
                "spatial_ref_id": "campus-a/edge-2",
                "edge_type": "connected_to",
                "direction": "inbound",
            },
        ],
    }
    result_obj = MagicMock()
    result_obj.single = AsyncMock(return_value=record)

    session = AsyncMock()
    session.run = AsyncMock(return_value=result_obj)
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result = await svc.get_node_with_neighbours(
        device_id=uuid.uuid4(),
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        depth=1,
    )

    assert result is not None
    assert result["node"]["device_id"] == "device-1"
    assert result["node"]["spatial_ref_id"] == "campus-a/core-1"
    assert [n["device_id"] for n in result["neighbours"]] == ["device-2", "device-3"]
    assert result["neighbours"][0]["spatial_ref_id"] == "campus-a/edge-2"
    assert result["neighbours"][1]["spatial_ref_id"] is None
    assert result["neighbours"][0]["edge_type"] == "connected_to"
    assert result["neighbours"][0]["direction"] == "inbound"


@pytest.mark.asyncio
async def test_get_node_with_neighbours_returns_none_when_missing():
    result_obj = MagicMock()
    result_obj.single = AsyncMock(return_value=None)

    session = AsyncMock()
    session.run = AsyncMock(return_value=result_obj)
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result = await svc.get_node_with_neighbours(
        device_id=uuid.uuid4(),
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        depth=1,
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_node_with_neighbours_forces_depth_to_one():
    record = {
        "node": {
            "device_id": "device-1",
            "hostname": "core-1",
            "device_type": "router",
            "status": "active",
            "spatial_ref_id": None,
        },
        "neighbours": [],
    }
    result_obj = MagicMock()
    result_obj.single = AsyncMock(return_value=record)

    session = AsyncMock()
    session.run = AsyncMock(return_value=result_obj)
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    await svc.get_node_with_neighbours(
        device_id=uuid.uuid4(),
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        depth=3,
    )

    query = session.run.await_args.args[0]
    assert "CONNECTED_TO" in query
    assert "WITH d, outbound, collect" in query
    assert "workspace_id" in query


@pytest.mark.asyncio
async def test_get_device_neighbours_returns_deterministic_rows_with_metadata_and_depth():
    root_record = {
        "device_id": "device-1",
        "hostname": "core-1",
        "device_type": "router",
        "status": "active",
        "spatial_ref_id": "campus-a/core-1",
    }
    root_result = MagicMock()
    root_result.single = AsyncMock(return_value=root_record)

    neighbours_result = MagicMock()
    neighbours_result.data = AsyncMock(
        return_value=[
            {
                "selected": {
                    "device_id": "device-2",
                    "hostname": "edge-2",
                    "device_type": "switch",
                    "status": "active",
                    "spatial_ref_id": "campus-a/edge-2",
                    "edge_type": "connected_to",
                    "edge_metadata": {"link_quality": "good"},
                    "direction": "inbound",
                    "hop_depth": 2,
                }
            },
            {
                "selected": {
                    "device_id": "device-3",
                    "hostname": "edge-3",
                    "device_type": "switch",
                    "status": "active",
                    "spatial_ref_id": None,
                    "edge_type": "connected_to",
                    "edge_metadata": {},
                    "direction": "outbound",
                    "hop_depth": 1,
                }
            },
        ]
    )

    session = AsyncMock()
    session.run = AsyncMock(side_effect=[root_result, neighbours_result])
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result = await svc.get_device_neighbours(
        device_id=uuid.uuid4(),
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        depth=10,
        limit=5,
    )

    assert result is not None
    assert result.device.device_id == "device-1"
    assert result.depth == 6
    assert result.total == 2
    assert result.neighbours[0].edge_metadata == {"link_quality": "good"}
    assert result.neighbours[0].hop_depth == 2
    assert result.neighbours[1].hop_depth == 1

    neighbours_call = session.run.await_args_list[1]
    assert neighbours_call.kwargs["limit"] == 5
    assert neighbours_call.kwargs["workspace_id"]
    assert "1..6" in neighbours_call.args[0]
    assert "workspace_id" in neighbours_call.args[0]


@pytest.mark.asyncio
async def test_get_device_neighbours_returns_none_when_root_missing():
    root_result = MagicMock()
    root_result.single = AsyncMock(return_value=None)

    session = AsyncMock()
    session.run = AsyncMock(return_value=root_result)
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result = await svc.get_device_neighbours(
        device_id=uuid.uuid4(),
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        depth=1,
        limit=20,
    )

    assert result is None
    session.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_impact_analysis_returns_ordered_reachable_set():
    root_record = {
        "device_id": "device-1",
        "hostname": "core-1",
        "device_type": "router",
        "status": "active",
        "spatial_ref_id": "campus-a/core-1",
    }
    root_result = MagicMock()
    root_result.single = AsyncMock(return_value=root_record)

    impact_result = MagicMock()
    impact_result.data = AsyncMock(
        return_value=[
            {
                "impact": {
                    "device_id": "device-2",
                    "hostname": "dist-2",
                    "device_type": "switch",
                    "status": "active",
                    "spatial_ref_id": "campus-a/dist-2",
                    "hop_depth": 1,
                }
            },
            {
                "impact": {
                    "device_id": "device-3",
                    "hostname": "edge-3",
                    "device_type": "switch",
                    "status": "active",
                    "spatial_ref_id": None,
                    "hop_depth": 2,
                }
            },
        ]
    )

    session = AsyncMock()
    session.run = AsyncMock(side_effect=[root_result, impact_result])
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result = await svc.get_impact_analysis(
        device_id=uuid.uuid4(),
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        max_hops=20,
        limit=9,
    )

    assert result is not None
    assert result.device.device_id == "device-1"
    assert result.max_hops == 8
    assert result.total == 2
    assert result.impacts[0].device_id == "device-2"
    assert result.impacts[0].hop_depth == 1
    assert result.impacts[1].device_id == "device-3"
    assert result.impacts[1].hop_depth == 2

    impact_call = session.run.await_args_list[1]
    assert impact_call.kwargs["limit"] == 9
    assert impact_call.kwargs["workspace_id"]
    assert "1..8" in impact_call.args[0]
    assert "workspace_id" in impact_call.args[0]


@pytest.mark.asyncio
async def test_get_impact_analysis_returns_none_when_root_missing():
    root_result = MagicMock()
    root_result.single = AsyncMock(return_value=None)

    session = AsyncMock()
    session.run = AsyncMock(return_value=root_result)
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result = await svc.get_impact_analysis(
        device_id=uuid.uuid4(),
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        max_hops=2,
        limit=200,
    )

    assert result is None
    session.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_network_returns_none_when_network_not_found():
    network_id = uuid.uuid4()

    session = AsyncMock()
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None
    driver = MagicMock()
    driver.session.return_value = session_cm

    with patch.object(
        NetworkRepository,
        "get_workspace_ids_for_network_ids",
        new=AsyncMock(return_value={}),
    ) as workspace_lookup, patch("app.modules.network.topology.publish_event", new_callable=AsyncMock) as publish_event:
        result = await TopologyQueryService(driver=driver).reconcile_network(
            network_id=network_id,
            workspace_id=uuid.uuid4(),
            db=AsyncMock(),
            redis=AsyncMock(),
            actor_id=str(uuid.uuid4()),
            correlation_id="corr-1",
        )

    assert result is None
    workspace_lookup.assert_awaited_once_with([str(network_id)])
    publish_event.assert_not_awaited()
    session.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_network_returns_counts_and_emits_requested_and_completed_events():
    network_id = uuid.uuid4()
    workspace_id = str(uuid.uuid4())

    node_result = MagicMock()
    node_result.single = AsyncMock(return_value={"node_count": 7})
    edge_result = MagicMock()
    edge_result.single = AsyncMock(return_value={"edge_count": 6})
    missing_result = MagicMock()
    missing_result.single = AsyncMock(return_value={"missing_workspace_nodes": 2})
    backfill_result = MagicMock()
    backfill_result.single = AsyncMock(return_value={"workspace_backfilled_nodes": 2})

    session = AsyncMock()
    session.run = AsyncMock(side_effect=[node_result, edge_result, missing_result, backfill_result])
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None
    driver = MagicMock()
    driver.session.return_value = session_cm

    with patch.object(
        NetworkRepository,
        "get_workspace_ids_for_network_ids",
        new=AsyncMock(return_value={str(network_id): workspace_id}),
    ), patch("app.modules.network.topology.publish_event", new_callable=AsyncMock) as publish_event:
        result = await TopologyQueryService(driver=driver).reconcile_network(
            network_id=network_id,
            workspace_id=uuid.UUID(workspace_id),
            db=AsyncMock(),
            redis=AsyncMock(),
            actor_id=str(uuid.uuid4()),
            correlation_id="corr-2",
        )

    assert result is not None
    assert result["network_id"] == str(network_id)
    assert result["status"] == "completed"
    assert result["checked_nodes"] == 7
    assert result["checked_edges"] == 6
    assert result["missing_workspace_nodes"] == 2
    assert result["workspace_backfilled_nodes"] == 2
    assert result["warning"] is None

    assert publish_event.await_count == 2
    first_event_kwargs = publish_event.await_args_list[0].kwargs
    second_event_kwargs = publish_event.await_args_list[1].kwargs
    assert first_event_kwargs["event_type"] == "network.topology.reconcile_requested"
    assert second_event_kwargs["event_type"] == "network.topology.reconcile_completed"


@pytest.mark.asyncio
async def test_reconcile_network_returns_none_when_workspace_mismatch_detected():
    network_id = uuid.uuid4()
    resolved_workspace_id = uuid.uuid4()
    mismatched_workspace_id = uuid.uuid4()

    session = AsyncMock()
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None
    driver = MagicMock()
    driver.session.return_value = session_cm

    with patch.object(
        NetworkRepository,
        "get_workspace_ids_for_network_ids",
        new=AsyncMock(return_value={str(network_id): str(resolved_workspace_id)}),
    ) as workspace_lookup, patch("app.modules.network.topology.publish_event", new_callable=AsyncMock) as publish_event:
        result = await TopologyQueryService(driver=driver).reconcile_network(
            network_id=network_id,
            workspace_id=mismatched_workspace_id,
            db=AsyncMock(),
            redis=AsyncMock(),
            actor_id=str(uuid.uuid4()),
            correlation_id="corr-workspace-mismatch",
        )

    assert result is None
    workspace_lookup.assert_awaited_once_with([str(network_id)])
    publish_event.assert_not_awaited()
    session.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_network_emits_failed_event_and_raises_on_neo4j_error():
    network_id = uuid.uuid4()
    workspace_id = str(uuid.uuid4())

    session = AsyncMock()
    session.run = AsyncMock(side_effect=RuntimeError("neo4j unavailable"))
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None
    driver = MagicMock()
    driver.session.return_value = session_cm

    with (
        patch.object(
            NetworkRepository,
            "get_workspace_ids_for_network_ids",
            new=AsyncMock(return_value={str(network_id): workspace_id}),
        ),
        patch("app.modules.network.topology.publish_event", new_callable=AsyncMock) as publish_event,
        pytest.raises(RuntimeError, match="neo4j unavailable"),
    ):
        await TopologyQueryService(driver=driver).reconcile_network(
            network_id=network_id,
            workspace_id=uuid.UUID(workspace_id),
            db=AsyncMock(),
            redis=AsyncMock(),
            actor_id=str(uuid.uuid4()),
            correlation_id="corr-3",
        )

    assert publish_event.await_count == 2
    assert publish_event.await_args_list[0].kwargs["event_type"] == "network.topology.reconcile_requested"
    assert publish_event.await_args_list[1].kwargs["event_type"] == "network.topology.reconcile_failed"


# ======================================================================================
# Digital Twin Phase 1 — CONNECTED_TO edge writer + edge metadata read-through
# ======================================================================================


def _edge_write_session(written: int = 0):
    """Build a mocked Neo4j session returning ``written`` from the merge query."""
    record = {"written": written}
    result = MagicMock()
    result.single = AsyncMock(return_value=record)

    session = AsyncMock()
    session.run = AsyncMock(return_value=result)
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm
    return driver, session


@pytest.mark.asyncio
async def test_merge_device_edges_writes_scoped_idempotent_relationships():
    network_id = str(uuid.uuid4())
    workspace_id = str(uuid.uuid4())
    driver, session = _edge_write_session(written=2)

    svc = TopologyQueryService(driver=driver)
    written = await svc.merge_device_edges(
        network_id=network_id,
        workspace_id=workspace_id,
        edges=[
            PlannedEdge("a", "b", EDGE_TYPE_CONNECTED_TO, {"synthetic": True, "relation": "core_backbone"}),
            PlannedEdge("b", "c", EDGE_TYPE_CONNECTED_TO, {"synthetic": True, "relation": "access_uplink"}),
        ],
    )

    assert written == 2
    query = session.run.await_args.args[0]
    # Idempotency + scoping + self-link rejection must all be enforced in Cypher.
    assert "MERGE (s)-[r:CONNECTED_TO]->(t)" in query
    assert "network_id: $network_id" in query
    assert "workspace_id: $workspace_id" in query
    assert "s.device_id <> t.device_id" in query

    kwargs = session.run.await_args.kwargs
    assert kwargs["network_id"] == network_id
    assert kwargs["workspace_id"] == workspace_id
    assert [edge["source_id"] for edge in kwargs["edges"]] == ["a", "b"]
    assert kwargs["edges"][0]["properties"]["relation"] == "core_backbone"
    assert kwargs["edges"][0]["properties"]["synthetic"] is True


@pytest.mark.asyncio
async def test_merge_device_edges_drops_self_links_and_blank_endpoints():
    driver, session = _edge_write_session(written=1)

    svc = TopologyQueryService(driver=driver)
    written = await svc.merge_device_edges(
        network_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        edges=[
            PlannedEdge("a", "a", EDGE_TYPE_CONNECTED_TO, {}),
            PlannedEdge("", "b", EDGE_TYPE_CONNECTED_TO, {}),
            PlannedEdge("c", "", EDGE_TYPE_CONNECTED_TO, {}),
            PlannedEdge("c", "d", EDGE_TYPE_CONNECTED_TO, {}),
        ],
    )

    assert written == 1
    payload = session.run.await_args.kwargs["edges"]
    assert [(edge["source_id"], edge["target_id"]) for edge in payload] == [("c", "d")]


@pytest.mark.asyncio
async def test_merge_device_edges_strips_non_primitive_properties_for_neo4j():
    driver, session = _edge_write_session(written=1)

    svc = TopologyQueryService(driver=driver)
    await svc.merge_device_edges(
        network_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        edges=[
            PlannedEdge(
                "a",
                "b",
                EDGE_TYPE_CONNECTED_TO,
                {
                    "synthetic": True,
                    "relation": "leaf_uplink",
                    "hops": 2,
                    "weight": 1.5,
                    "nested": {"not": "allowed"},
                    "listy": ["also", "dropped"],
                },
            )
        ],
    )

    properties = session.run.await_args.kwargs["edges"][0]["properties"]
    assert properties == {
        "synthetic": True,
        "relation": "leaf_uplink",
        "hops": 2,
        "weight": 1.5,
    }


@pytest.mark.asyncio
async def test_merge_device_edges_skips_query_entirely_for_empty_payload():
    driver, session = _edge_write_session(written=0)

    svc = TopologyQueryService(driver=driver)
    written = await svc.merge_device_edges(
        network_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        edges=[],
    )

    assert written == 0
    session.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_graph_surfaces_synthetic_edge_metadata():
    node_rows = [
        {
            "device_id": "a",
            "hostname": "a-host",
            "device_type": "router",
            "status": "active",
            "spatial_ref_id": "strathmore/sbs/f01/core/rtr-sbs-f01-01",
        },
        {
            "device_id": "b",
            "hostname": "b-host",
            "device_type": "access_switch",
            "status": "active",
            "spatial_ref_id": "strathmore/sbs/f01/distribution/sw-acc-sbs-f01-01",
        },
    ]
    edge_rows = [
        {
            "source_id": "a",
            "target_id": "b",
            "edge_properties": {
                "synthetic": True,
                "generator": "nanfo.synthetic_topology.v1",
                "relation": "access_uplink",
            },
        }
    ]

    node_result = MagicMock()
    node_result.data = AsyncMock(return_value=node_rows)
    edge_result = MagicMock()
    edge_result.data = AsyncMock(return_value=edge_rows)

    session = AsyncMock()
    session.run = AsyncMock(side_effect=[node_result, edge_result])
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result, _ = await svc.get_graph(
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        limit=10,
    )

    assert len(result.edges) == 1
    edge = result.edges[0]
    assert edge.edge_type == "connected_to"
    assert edge.metadata["synthetic"] is True
    assert edge.metadata["relation"] == "access_uplink"
    assert edge.metadata["generator"] == "nanfo.synthetic_topology.v1"


@pytest.mark.asyncio
async def test_get_graph_defaults_edge_metadata_when_properties_absent():
    """Legacy edges without properties must still deserialise (backward compatibility)."""
    node_rows = [
        {"device_id": "a", "hostname": "a", "device_type": "router", "status": "active", "spatial_ref_id": None},
        {"device_id": "b", "hostname": "b", "device_type": "switch", "status": "active", "spatial_ref_id": None},
    ]
    edge_rows = [{"source_id": "a", "target_id": "b"}]

    node_result = MagicMock()
    node_result.data = AsyncMock(return_value=node_rows)
    edge_result = MagicMock()
    edge_result.data = AsyncMock(return_value=edge_rows)

    session = AsyncMock()
    session.run = AsyncMock(side_effect=[node_result, edge_result])
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result, _ = await svc.get_graph(network_id=uuid.uuid4(), workspace_id=uuid.uuid4(), limit=10)

    assert result.edges[0].metadata == {}


@pytest.mark.asyncio
async def test_get_graph_deduplicates_repeated_edge_rows():
    node_rows = [
        {"device_id": "a", "hostname": "a", "device_type": "router", "status": "active", "spatial_ref_id": None},
        {"device_id": "b", "hostname": "b", "device_type": "switch", "status": "active", "spatial_ref_id": None},
    ]
    edge_rows = [
        {"source_id": "a", "target_id": "b", "edge_properties": {"relation": "access_uplink"}},
        {"source_id": "a", "target_id": "b", "edge_properties": {"relation": "duplicate_ignored"}},
    ]

    node_result = MagicMock()
    node_result.data = AsyncMock(return_value=node_rows)
    edge_result = MagicMock()
    edge_result.data = AsyncMock(return_value=edge_rows)

    session = AsyncMock()
    session.run = AsyncMock(side_effect=[node_result, edge_result])
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    result, _ = await svc.get_graph(network_id=uuid.uuid4(), workspace_id=uuid.uuid4(), limit=10)

    assert len(result.edges) == 1
    assert result.edges[0].metadata["relation"] == "access_uplink"


# ======================================================================================
# Regression: neo4j.Record subclasses tuple, so `"key" in record` tests VALUES not keys
# ======================================================================================


def test_record_int_reads_real_neo4j_record_by_key():
    """Guards against the zeroed-counter bug that dict-based mocks could not catch."""
    record = Record(zip(["written"], [323]))

    # Documents the trap: the `in` idiom is False even though the key exists.
    assert "written" not in record
    assert record["written"] == 323

    assert _record_int(record, "written") == 323


def test_record_int_still_supports_plain_dict_records():
    assert _record_int({"written": 7}, "written") == 7


@pytest.mark.parametrize(
    "record",
    [None, Record(zip(["other"], [1])), {}, {"written": None}],
)
def test_record_int_falls_back_to_default_for_missing_or_null(record):
    assert _record_int(record, "written") == 0
    assert _record_int(record, "written", default=-1) == -1


def test_record_int_defaults_when_value_is_not_numeric():
    assert _record_int(Record(zip(["written"], ["not-a-number"])), "written") == 0


def test_record_int_coerces_numeric_strings_and_floats():
    assert _record_int(Record(zip(["written"], ["12"])), "written") == 12
    assert _record_int(Record(zip(["written"], [4.9])), "written") == 4


@pytest.mark.asyncio
async def test_merge_device_edges_returns_real_count_from_neo4j_record():
    """End-to-end guard: the writer must report what Neo4j actually returned."""
    record = Record(zip(["written"], [323]))
    result = MagicMock()
    result.single = AsyncMock(return_value=record)

    session = AsyncMock()
    session.run = AsyncMock(return_value=result)
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    svc = TopologyQueryService(driver=driver)
    written = await svc.merge_device_edges(
        network_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        edges=[PlannedEdge("a", "b", EDGE_TYPE_CONNECTED_TO, {"synthetic": True})],
    )

    assert written == 323


@pytest.mark.asyncio
async def test_reconcile_network_reports_real_counts_from_neo4j_records():
    """Pre-existing defect: reconcile always reported zeros against a real driver."""
    network_id = uuid.uuid4()
    workspace_id = uuid.uuid4()

    def _result(record):
        res = MagicMock()
        res.single = AsyncMock(return_value=record)
        return res

    session = AsyncMock()
    session.run = AsyncMock(
        side_effect=[
            _result(Record(zip(["node_count"], [339]))),
            _result(Record(zip(["edge_count"], [338]))),
            _result(Record(zip(["missing_workspace_nodes"], [5]))),
            _result(Record(zip(["workspace_backfilled_nodes"], [5]))),
        ]
    )
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    driver = MagicMock()
    driver.session.return_value = session_cm

    repo_result = {str(network_id): str(workspace_id)}

    with (
        patch.object(
            NetworkRepository,
            "get_workspace_ids_for_network_ids",
            new=AsyncMock(return_value=repo_result),
        ),
        patch("app.modules.network.topology.publish_event", new=AsyncMock()),
    ):
        svc = TopologyQueryService(driver=driver)
        outcome = await svc.reconcile_network(
            network_id=network_id,
            workspace_id=workspace_id,
            db=AsyncMock(),
            redis=MagicMock(),
            actor_id="actor-1",
            correlation_id="corr-1",
        )

    assert outcome is not None
    assert outcome["checked_nodes"] == 339
    assert outcome["checked_edges"] == 338
    assert outcome["missing_workspace_nodes"] == 5
    assert outcome["workspace_backfilled_nodes"] == 5


# ======================================================================================
# Replace semantics: re-seeding must converge, not accumulate stale synthetic uplinks
# ======================================================================================


@pytest.mark.asyncio
async def test_prune_synthetic_device_edges_only_targets_tagged_generated_edges():
    driver, session = _edge_write_session(written=0)
    record = Record(zip(["deleted"], [323]))
    session.run.return_value.single = AsyncMock(return_value=record)

    svc = TopologyQueryService(driver=driver)
    deleted = await svc.prune_synthetic_device_edges(
        network_id="net-1",
        workspace_id="ws-1",
        generator="nanfo.synthetic_topology.v1",
    )

    assert deleted == 323
    query = session.run.await_args.args[0]
    # Must never delete discovered/real topology.
    assert "r.synthetic = true" in query
    assert "r.generator = $generator" in query
    assert "DELETE r" in query
    assert "network_id: $network_id" in query
    assert "workspace_id: $workspace_id" in query

    kwargs = session.run.await_args.kwargs
    assert kwargs["generator"] == "nanfo.synthetic_topology.v1"


@pytest.mark.asyncio
async def test_replace_synthetic_device_edges_prunes_before_writing():
    """Regression for observed accumulation: 323 stale + 338 new produced 614 edges."""
    svc = TopologyQueryService(driver=MagicMock())

    call_order: list[str] = []

    async def fake_prune(_self, **kwargs):
        call_order.append("prune")
        return 323

    async def fake_merge(_self, **kwargs):
        call_order.append("merge")
        return 338

    with (
        patch.object(TopologyQueryService, "prune_synthetic_device_edges", new=fake_prune),
        patch.object(TopologyQueryService, "merge_device_edges", new=fake_merge),
    ):
        deleted, written = await svc.replace_synthetic_device_edges(
            network_id="net-1",
            workspace_id="ws-1",
            edges=[PlannedEdge("a", "b", EDGE_TYPE_CONNECTED_TO, {"synthetic": True})],
            generator="nanfo.synthetic_topology.v1",
        )

    assert (deleted, written) == (323, 338)
    assert call_order == ["prune", "merge"], "stale edges must be removed before writing"


@pytest.mark.asyncio
async def test_replace_synthetic_device_edges_is_convergent_across_reruns():
    """Two runs with the same plan must leave the same edge count, not double it."""
    svc = TopologyQueryService(driver=MagicMock())
    graph_edges: set[tuple[str, str]] = set()
    plan = [
        PlannedEdge("a", "b", EDGE_TYPE_CONNECTED_TO, {"synthetic": True}),
        PlannedEdge("b", "c", EDGE_TYPE_CONNECTED_TO, {"synthetic": True}),
    ]

    async def fake_prune(_self, **kwargs):
        removed = len(graph_edges)
        graph_edges.clear()
        return removed

    async def fake_merge(_self, **kwargs):
        for edge in kwargs["edges"]:
            graph_edges.add((edge.source_id, edge.target_id))
        return len(kwargs["edges"])

    with (
        patch.object(TopologyQueryService, "prune_synthetic_device_edges", new=fake_prune),
        patch.object(TopologyQueryService, "merge_device_edges", new=fake_merge),
    ):
        await svc.replace_synthetic_device_edges(
            network_id="n", workspace_id="w", edges=plan, generator="g"
        )
        assert len(graph_edges) == 2

        await svc.replace_synthetic_device_edges(
            network_id="n", workspace_id="w", edges=plan, generator="g"
        )
        assert len(graph_edges) == 2, "re-running must converge, not accumulate"


@pytest.mark.asyncio
async def test_replace_converges_when_a_rerun_plan_picks_different_parents():
    """The real failure mode: a different device set yields different valid parents."""
    svc = TopologyQueryService(driver=MagicMock())
    graph_edges: set[tuple[str, str]] = set()

    async def fake_prune(_self, **kwargs):
        removed = len(graph_edges)
        graph_edges.clear()
        return removed

    async def fake_merge(_self, **kwargs):
        for edge in kwargs["edges"]:
            graph_edges.add((edge.source_id, edge.target_id))
        return len(kwargs["edges"])

    partial_plan = [PlannedEdge("core-1", "ap-1", EDGE_TYPE_CONNECTED_TO, {"synthetic": True})]
    full_plan = [PlannedEdge("core-2", "ap-1", EDGE_TYPE_CONNECTED_TO, {"synthetic": True})]

    with (
        patch.object(TopologyQueryService, "prune_synthetic_device_edges", new=fake_prune),
        patch.object(TopologyQueryService, "merge_device_edges", new=fake_merge),
    ):
        await svc.replace_synthetic_device_edges(
            network_id="n", workspace_id="w", edges=partial_plan, generator="g"
        )
        await svc.replace_synthetic_device_edges(
            network_id="n", workspace_id="w", edges=full_plan, generator="g"
        )

    # ap-1 must end up with exactly one uplink, from the newer plan.
    assert graph_edges == {("core-2", "ap-1")}
