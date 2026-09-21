"""Unit tests for Strathmore demo preparation helper script."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.network.synthetic_topology import SYNTHETIC_TOPOLOGY_GENERATOR
from scripts.prepare_strathmore_demo import (
    SYNTHETIC_DATASET_LABEL,
    _await_topology_projection,
    _build_parser,
    build_dataset_summary,
    build_group_scope_intent_request,
    build_planned_devices_from_graph,
    build_strathmore_device_payloads,
    build_synthetic_topology_plan,
    materialize_synthetic_topology_edges,
)


def test_build_strathmore_device_payloads_matches_phase1_targets():
    payloads = build_strathmore_device_payloads()
    summary = build_dataset_summary(payloads)

    assert summary["total_devices"] == 339
    assert summary["devices_by_building"] == {
        "bld-e": 12,
        "bld-f": 12,
        "bld-g": 12,
        "lib": 86,
        "msb": 71,
        "sbs": 86,
        "ssc": 60,
    }
    assert summary["devices_by_type"] == {
        "access_switch": 64,
        "distribution_switch": 23,
        "firewall": 2,
        "lab_endpoint": 35,
        "router": 2,
        "security_gateway": 29,
        "server": 25,
        "ups": 29,
        "wireless_ap": 130,
    }
    assert summary["floors_by_building"] == {
        "bld-e": 2,
        "bld-f": 2,
        "bld-g": 2,
        "lib": 6,
        "msb": 5,
        "sbs": 6,
        "ssc": 4,
    }


def test_build_strathmore_device_payloads_respects_cap():
    payloads = build_strathmore_device_payloads(max_devices=5)

    assert len(payloads) == 5
    assert payloads[0]["hostname"] == "rtr-sbs-f01-01"
    assert payloads[0]["spatial_ref_id"] == "strathmore/sbs/f01/core/rtr-sbs-f01-01"


def test_build_group_scope_intent_request_uses_contract_safe_shape():
    payload = build_group_scope_intent_request(
        workspace_id="11111111-1111-1111-1111-111111111111",
        network_id="22222222-2222-2222-2222-222222222222",
    )

    assert payload["workspace_id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["network_id"] == "22222222-2222-2222-2222-222222222222"
    assert payload["intent"]["action"] == "optimize_wireless_capacity"
    assert payload["intent"]["scope"]["target"] == "group"
    assert payload["intent"]["scope"]["site_prefix"] == "strathmore/ssc/f02"
    assert payload["intent"]["constraints"]["simulation_required"] is True


# ======================================================================================
# Digital Twin Phase 1 — synthetic topology materialisation for the demo dataset
# ======================================================================================


def _graph_nodes_from_payloads(payloads: list[dict]) -> list[dict]:
    """Mimic GET /api/v1/topology/graph node rows for the seeded device payloads."""
    return [
        {
            "device_id": f"device-{index:04d}",
            "hostname": payload["hostname"],
            "device_type": payload["device_type"],
            "status": "active",
            "spatial_ref_id": payload["spatial_ref_id"],
        }
        for index, payload in enumerate(build_strathmore_device_payloads(), start=1)
    ]


def test_build_planned_devices_from_graph_projects_all_rows():
    payloads = build_strathmore_device_payloads()
    nodes = _graph_nodes_from_payloads(payloads)

    planned = build_planned_devices_from_graph(nodes)

    assert len(planned) == 339
    assert planned[0].hostname == "rtr-sbs-f01-01"
    assert planned[0].device_type == "router"
    assert planned[0].spatial_ref_id == "strathmore/sbs/f01/core/rtr-sbs-f01-01"


def test_build_planned_devices_from_graph_drops_rows_without_device_id():
    nodes = [
        {"device_id": "d1", "hostname": "a", "device_type": "router", "spatial_ref_id": "c/b/f/z/a"},
        {"device_id": "", "hostname": "b", "device_type": "router", "spatial_ref_id": None},
        {"hostname": "c", "device_type": "router"},
        "not-a-dict",
    ]

    planned = build_planned_devices_from_graph(nodes)

    assert [device.device_id for device in planned] == ["d1"]


def test_build_planned_devices_from_graph_normalises_blank_spatial_ref():
    nodes = [{"device_id": "d1", "hostname": "a", "device_type": "router", "spatial_ref_id": "   "}]

    planned = build_planned_devices_from_graph(nodes)

    assert planned[0].spatial_ref_id is None


def test_strathmore_synthetic_plan_connects_the_whole_339_device_dataset():
    """The headline Phase 1 fix: 339 nodes must no longer yield 0 edges."""
    nodes = _graph_nodes_from_payloads(build_strathmore_device_payloads())

    plan = build_synthetic_topology_plan(nodes)

    # 339 devices, 2 core routers -> every other device gains exactly one uplink,
    # plus one core backbone link between the two routers.
    assert plan.edge_count == 338
    assert plan.stats["devices"] == 339
    assert plan.stats["tier_core"] == 2
    assert plan.stats["tier_perimeter"] == 2
    assert plan.stats["tier_distribution"] == 23
    assert plan.stats["tier_access"] == 64
    assert plan.stats["tier_leaf"] == 248


def test_strathmore_synthetic_plan_has_no_duplicates_or_self_links():
    nodes = _graph_nodes_from_payloads(build_strathmore_device_payloads())
    plan = build_synthetic_topology_plan(nodes)

    keys = [edge.key for edge in plan.edges]
    assert len(keys) == len(set(keys))
    assert all(edge.source_id != edge.target_id for edge in plan.edges)


def test_strathmore_synthetic_plan_references_only_seeded_devices():
    nodes = _graph_nodes_from_payloads(build_strathmore_device_payloads())
    known = {node["device_id"] for node in nodes}

    plan = build_synthetic_topology_plan(nodes)

    for edge in plan.edges:
        assert edge.source_id in known
        assert edge.target_id in known


def test_strathmore_synthetic_plan_is_reproducible():
    nodes = _graph_nodes_from_payloads(build_strathmore_device_payloads())

    first = build_synthetic_topology_plan(nodes)
    second = build_synthetic_topology_plan(nodes)

    assert [edge.key for edge in first.edges] == [edge.key for edge in second.edges]
    assert first.stats == second.stats


def test_strathmore_synthetic_plan_labels_every_edge_as_demo_data():
    """Honesty requirement: nothing here may look like discovered infrastructure."""
    nodes = _graph_nodes_from_payloads(build_strathmore_device_payloads())
    plan = build_synthetic_topology_plan(nodes)

    assert plan.edges
    for edge in plan.edges:
        assert edge.metadata["synthetic"] is True
        assert edge.metadata["dataset"] == SYNTHETIC_DATASET_LABEL
        assert edge.metadata["generator"]


def test_strathmore_synthetic_plan_reaches_every_building():
    nodes = _graph_nodes_from_payloads(build_strathmore_device_payloads())
    by_id = {node["device_id"]: node for node in nodes}
    plan = build_synthetic_topology_plan(nodes)

    connected_buildings = set()
    for edge in plan.edges:
        for endpoint in (edge.source_id, edge.target_id):
            spatial_ref = by_id[endpoint]["spatial_ref_id"]
            connected_buildings.add(spatial_ref.split("/")[1])

    assert connected_buildings == {"sbs", "lib", "msb", "ssc", "bld-e", "bld-f", "bld-g"}


def test_strathmore_annex_buildings_home_directly_to_core():
    """bld-e/f/g have no distribution switch; the documented fallback must apply."""
    nodes = _graph_nodes_from_payloads(build_strathmore_device_payloads())
    by_id = {node["device_id"]: node for node in nodes}
    plan = build_synthetic_topology_plan(nodes)

    annex_access_edges = [
        edge
        for edge in plan.edges
        if edge.metadata.get("relation") == "access_uplink"
        and by_id[edge.target_id]["spatial_ref_id"].split("/")[1] in {"bld-e", "bld-f", "bld-g"}
    ]

    assert len(annex_access_edges) == 6
    for edge in annex_access_edges:
        assert edge.metadata["fallback"] == "core_homed"
        assert by_id[edge.source_id]["device_type"] == "router"


def test_materialize_synthetic_topology_edges_is_noop_for_empty_plan():
    empty_plan = build_synthetic_topology_plan([])

    result = materialize_synthetic_topology_edges(
        network_id="11111111-1111-1111-1111-111111111111",
        workspace_id="22222222-2222-2222-2222-222222222222",
        plan=empty_plan,
    )

    assert result == (0, 0)


def test_materialize_synthetic_topology_edges_delegates_to_network_topology_writer():
    nodes = _graph_nodes_from_payloads(build_strathmore_device_payloads())
    plan = build_synthetic_topology_plan(nodes)

    service = MagicMock()
    service.replace_synthetic_device_edges = AsyncMock(return_value=(12, plan.edge_count))

    with (
        patch("scripts.prepare_strathmore_demo.init_neo4j", new=AsyncMock()) as init_mock,
        patch("scripts.prepare_strathmore_demo.close_neo4j", new=AsyncMock()) as close_mock,
        patch("scripts.prepare_strathmore_demo.get_neo4j_driver", return_value=MagicMock()),
        patch("scripts.prepare_strathmore_demo.TopologyQueryService", return_value=service),
    ):
        deleted, written = materialize_synthetic_topology_edges(
            network_id="11111111-1111-1111-1111-111111111111",
            workspace_id="22222222-2222-2222-2222-222222222222",
            plan=plan,
        )

    assert (deleted, written) == (12, plan.edge_count)
    init_mock.assert_awaited_once()
    close_mock.assert_awaited_once()
    # Replace semantics are required so re-seeding cannot accumulate stale uplinks.
    service.replace_synthetic_device_edges.assert_awaited_once_with(
        network_id="11111111-1111-1111-1111-111111111111",
        workspace_id="22222222-2222-2222-2222-222222222222",
        edges=plan.edges,
        generator=SYNTHETIC_TOPOLOGY_GENERATOR,
    )


def test_materialize_closes_neo4j_even_when_the_write_fails():
    nodes = _graph_nodes_from_payloads(build_strathmore_device_payloads())
    plan = build_synthetic_topology_plan(nodes)

    service = MagicMock()
    service.replace_synthetic_device_edges = AsyncMock(side_effect=RuntimeError("neo4j down"))

    with (
        patch("scripts.prepare_strathmore_demo.init_neo4j", new=AsyncMock()),
        patch("scripts.prepare_strathmore_demo.close_neo4j", new=AsyncMock()) as close_mock,
        patch("scripts.prepare_strathmore_demo.get_neo4j_driver", return_value=MagicMock()),
        patch("scripts.prepare_strathmore_demo.TopologyQueryService", return_value=service),
        pytest.raises(RuntimeError, match="neo4j down"),
    ):
        materialize_synthetic_topology_edges(
            network_id="11111111-1111-1111-1111-111111111111",
            workspace_id="22222222-2222-2222-2222-222222222222",
            plan=plan,
        )

    close_mock.assert_awaited_once()


def test_seed_topology_edges_flag_defaults_on_and_can_be_disabled():
    parser = _build_parser()

    assert parser.parse_args([]).seed_topology_edges is True
    assert parser.parse_args(["--no-seed-topology-edges"]).seed_topology_edges is False
    assert parser.parse_args(["--seed-topology-edges"]).seed_topology_edges is True


# ======================================================================================
# Eventual-consistency guard: never plan topology from a partially-projected graph
# ======================================================================================


def _graph_response(node_count: int, edge_count: int = 0) -> dict:
    return {
        "nodes": [
            {
                "device_id": f"device-{index:04d}",
                "hostname": f"host-{index}",
                "device_type": "wireless_ap",
                "status": "active",
                "spatial_ref_id": f"strathmore/sbs/f01/wireless/host-{index}",
            }
            for index in range(node_count)
        ],
        "edges": [{"source_id": "a", "target_id": "b"} for _ in range(edge_count)],
    }


def test_await_topology_projection_returns_immediately_when_already_complete():
    api = MagicMock()
    api.get_topology_graph = MagicMock(return_value=_graph_response(339))

    nodes, edges = _await_topology_projection(
        api=api,
        network_id="net-1",
        expected_nodes=339,
        graph_limit=339,
        timeout_seconds=30,
        poll_interval_seconds=0,
    )

    assert len(nodes) == 339
    assert edges == []
    api.get_topology_graph.assert_called_once()


def test_await_topology_projection_polls_until_neo4j_catches_up():
    """Reproduces the observed race: 324 of 339 devices projected on first read."""
    api = MagicMock()
    api.get_topology_graph = MagicMock(
        side_effect=[
            _graph_response(324),
            _graph_response(331),
            _graph_response(339),
        ]
    )

    nodes, _ = _await_topology_projection(
        api=api,
        network_id="net-1",
        expected_nodes=339,
        graph_limit=339,
        timeout_seconds=30,
        poll_interval_seconds=0,
    )

    assert len(nodes) == 339
    assert api.get_topology_graph.call_count == 3


def test_await_topology_projection_gives_up_after_timeout_and_warns(capsys):
    api = MagicMock()
    api.get_topology_graph = MagicMock(return_value=_graph_response(324))

    nodes, _ = _await_topology_projection(
        api=api,
        network_id="net-1",
        expected_nodes=339,
        graph_limit=339,
        timeout_seconds=0,
        poll_interval_seconds=0,
    )

    assert len(nodes) == 324
    output = capsys.readouterr().out
    assert "WARNING" in output
    assert "will not receive an uplink" in output


def test_await_topology_projection_tolerates_more_nodes_than_expected():
    api = MagicMock()
    api.get_topology_graph = MagicMock(return_value=_graph_response(400))

    nodes, _ = _await_topology_projection(
        api=api,
        network_id="net-1",
        expected_nodes=339,
        graph_limit=500,
        timeout_seconds=30,
        poll_interval_seconds=0,
    )

    assert len(nodes) == 400


def test_topology_sync_timeout_flag_has_a_sane_default():
    parser = _build_parser()
    assert parser.parse_args([]).topology_sync_timeout_seconds == 90.0
    assert parser.parse_args(["--topology-sync-timeout-seconds", "5"]).topology_sync_timeout_seconds == 5.0
