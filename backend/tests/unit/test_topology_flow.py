"""Unit tests for topology event flow updates in VS2 step 1.

Verifies `workspace_id` propagation from network.device.added events into Neo4j
Device node writes, per docs/features/Topology.md §6.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.events.consumers.topology_consumer import handle_topology_event
from app.modules.network.repository import NetworkRepository
from app.modules.network.topology import TopologyQueryService


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
        {"device_id": "a", "hostname": "a-host", "device_type": "router", "status": "active"},
        {"device_id": "b", "hostname": "b-host", "device_type": "switch", "status": "active"},
        {"device_id": "c", "hostname": "c-host", "device_type": "switch", "status": "active"},
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
        limit=2,
        cursor="prev-cursor",
    )

    assert [n.device_id for n in result.nodes] == ["a", "b"]
    assert len(result.edges) == 1
    assert result.edges[0].source_id == "a"
    assert result.edges[0].target_id == "b"
    assert next_cursor == "b"

    first_call = session.run.await_args_list[0]
    assert first_call.kwargs["fetch_limit"] == 3
    assert first_call.kwargs["cursor"] == "prev-cursor"


@pytest.mark.asyncio
async def test_get_graph_returns_none_next_cursor_when_last_page():
    node_rows = [
        {"device_id": "a", "hostname": "a-host", "device_type": "router", "status": "active"},
        {"device_id": "b", "hostname": "b-host", "device_type": "switch", "status": "active"},
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
        limit=2,
        cursor=None,
    )

    assert [n.device_id for n in result.nodes] == ["a", "b"]
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
    result, next_cursor = await svc.get_graph(network_id=uuid.uuid4(), limit=5)

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
        },
        "neighbours": [
            {
                "device_id": "device-3",
                "hostname": "edge-3",
                "device_type": "switch",
                "status": "active",
                "edge_type": "connected_to",
                "direction": "outbound",
            },
            {
                "device_id": "device-2",
                "hostname": "edge-2",
                "device_type": "switch",
                "status": "active",
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
    result = await svc.get_node_with_neighbours(device_id=uuid.uuid4(), depth=1)

    assert result is not None
    assert result["node"]["device_id"] == "device-1"
    assert [n["device_id"] for n in result["neighbours"]] == ["device-2", "device-3"]
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
    result = await svc.get_node_with_neighbours(device_id=uuid.uuid4(), depth=1)

    assert result is None


@pytest.mark.asyncio
async def test_get_node_with_neighbours_forces_depth_to_one():
    record = {
        "node": {
            "device_id": "device-1",
            "hostname": "core-1",
            "device_type": "router",
            "status": "active",
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
    await svc.get_node_with_neighbours(device_id=uuid.uuid4(), depth=3)

    query = session.run.await_args.args[0]
    assert "CONNECTED_TO" in query
