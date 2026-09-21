"""Unit tests for the deterministic synthetic topology planner (Digital Twin Phase 1).

Covers the Phase 1 acceptance criteria:
- edge count > 0
- core/distribution/access relationships exist
- deterministic (reproducible) output
- no duplicate edges
- valid source/target devices
- no self-links
- input devices are never mutated
"""

from __future__ import annotations

import pytest

from app.modules.network.synthetic_topology import (
    EDGE_TYPE_CONNECTED_TO,
    SYNTHETIC_TOPOLOGY_GENERATOR,
    TIER_ACCESS,
    TIER_CORE,
    TIER_DISTRIBUTION,
    TIER_LEAF,
    TIER_PERIMETER,
    PlannedDevice,
    device_tier,
    plan_synthetic_topology,
)

# --------------------------------------------------------------------------------------
# Fixtures mirroring the shape of the Strathmore demo dataset
# --------------------------------------------------------------------------------------

CAMPUS = "strathmore"


def _device(
    device_id: str,
    hostname: str,
    device_type: str,
    building: str | None = None,
    floor: str | None = None,
    zone: str = "core",
) -> PlannedDevice:
    spatial_ref_id = None
    if building and floor:
        spatial_ref_id = f"{CAMPUS}/{building}/{floor}/{zone}/{hostname}"
    return PlannedDevice(
        device_id=device_id,
        hostname=hostname,
        device_type=device_type,
        spatial_ref_id=spatial_ref_id,
    )


def _mini_campus() -> list[PlannedDevice]:
    """Two buildings with a full tier stack, plus one annex with no distribution layer."""
    devices: list[PlannedDevice] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"dev-{counter:04d}"

    for building in ("sbs", "lib"):
        devices.append(_device(next_id(), f"rtr-{building}-f01-01", "router", building, "f01", "core"))
        devices.append(_device(next_id(), f"fw-{building}-f01-01", "firewall", building, "f01", "security"))
        for floor in ("f01", "f02"):
            devices.append(
                _device(next_id(), f"sw-dist-{building}-{floor}-01", "distribution_switch", building, floor, "distribution")
            )
            for ordinal in (1, 2):
                devices.append(
                    _device(
                        next_id(),
                        f"sw-acc-{building}-{floor}-{ordinal:02d}",
                        "access_switch",
                        building,
                        floor,
                        "distribution",
                    )
                )
            for ordinal in (1, 2, 3):
                devices.append(
                    _device(next_id(), f"ap-{building}-{floor}-{ordinal:02d}", "wireless_ap", building, floor, "wireless")
                )
            devices.append(_device(next_id(), f"srv-{building}-{floor}-01", "server", building, floor, "services"))
            devices.append(_device(next_id(), f"ups-{building}-{floor}-01", "ups", building, floor, "core"))

    # Annex building: access switch + leaves, deliberately no distribution switch.
    for floor in ("f01", "f02"):
        devices.append(_device(next_id(), f"sw-acc-bld-e-{floor}-01", "access_switch", "bld-e", floor, "distribution"))
        for ordinal in (1, 2, 3):
            devices.append(
                _device(next_id(), f"ap-bld-e-{floor}-{ordinal:02d}", "wireless_ap", "bld-e", floor, "wireless")
            )
        devices.append(_device(next_id(), f"end-bld-e-{floor}-01", "lab_endpoint", "bld-e", floor, "lab"))

    return devices


# --------------------------------------------------------------------------------------
# Tier mapping
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("device_type", "expected_tier"),
    [
        ("firewall", TIER_PERIMETER),
        ("router", TIER_CORE),
        ("core_router", TIER_CORE),
        ("distribution_switch", TIER_DISTRIBUTION),
        ("access_switch", TIER_ACCESS),
        ("switch", TIER_ACCESS),
        ("wireless_ap", TIER_LEAF),
        ("server", TIER_LEAF),
        ("security_gateway", TIER_LEAF),
        ("ups", TIER_LEAF),
        ("lab_endpoint", TIER_LEAF),
    ],
)
def test_device_tier_maps_every_demo_device_type(device_type: str, expected_tier: str):
    assert device_tier(device_type) == expected_tier


def test_device_tier_is_case_insensitive_and_defaults_to_leaf():
    assert device_tier("ROUTER") == TIER_CORE
    assert device_tier("  Firewall  ") == TIER_PERIMETER
    # Unknown types must never be promoted into the core.
    assert device_tier("smart_fridge") == TIER_LEAF
    assert device_tier(None) == TIER_LEAF
    assert device_tier("") == TIER_LEAF


# --------------------------------------------------------------------------------------
# Core Phase 1 acceptance criteria
# --------------------------------------------------------------------------------------


def test_plan_produces_edges_for_a_realistic_campus():
    plan = plan_synthetic_topology(_mini_campus())
    assert plan.edge_count > 0


def test_plan_covers_core_distribution_and_access_relationships():
    plan = plan_synthetic_topology(_mini_campus())
    relations = {str(edge.metadata["relation"]) for edge in plan.edges}

    assert "core_backbone" in relations
    assert "perimeter_uplink" in relations
    assert "distribution_uplink" in relations
    assert "access_uplink" in relations
    assert "leaf_uplink" in relations


def test_plan_is_deterministic_across_repeated_runs():
    devices = _mini_campus()
    first = plan_synthetic_topology(devices)
    second = plan_synthetic_topology(devices)

    assert [edge.key for edge in first.edges] == [edge.key for edge in second.edges]
    assert [edge.metadata for edge in first.edges] == [edge.metadata for edge in second.edges]
    assert first.stats == second.stats


def test_plan_is_independent_of_input_ordering():
    devices = _mini_campus()
    shuffled = list(reversed(devices))

    baseline = plan_synthetic_topology(devices)
    reordered = plan_synthetic_topology(shuffled)

    assert [edge.key for edge in baseline.edges] == [edge.key for edge in reordered.edges]


def test_plan_contains_no_duplicate_edges():
    plan = plan_synthetic_topology(_mini_campus())
    keys = [edge.key for edge in plan.edges]
    assert len(keys) == len(set(keys))


def test_plan_contains_no_self_links():
    plan = plan_synthetic_topology(_mini_campus())
    assert all(edge.source_id != edge.target_id for edge in plan.edges)


def test_plan_only_references_known_devices():
    devices = _mini_campus()
    known_ids = {device.device_id for device in devices}
    plan = plan_synthetic_topology(devices)

    for edge in plan.edges:
        assert edge.source_id in known_ids
        assert edge.target_id in known_ids


def test_plan_does_not_mutate_input_devices():
    devices = _mini_campus()
    snapshot = [
        (device.device_id, device.hostname, device.device_type, device.spatial_ref_id)
        for device in devices
    ]

    plan_synthetic_topology(devices)

    assert [
        (device.device_id, device.hostname, device.device_type, device.spatial_ref_id)
        for device in devices
    ] == snapshot


def test_every_non_core_device_receives_an_uplink():
    devices = _mini_campus()
    plan = plan_synthetic_topology(devices)

    devices_with_parent = {edge.target_id for edge in plan.edges}
    core_ids = {device.device_id for device in devices if device.tier == TIER_CORE}

    for device in devices:
        if device.device_id in core_ids:
            continue
        assert device.device_id in devices_with_parent, (
            f"{device.hostname} ({device.device_type}) has no upstream uplink"
        )


def test_edges_use_the_relationship_type_the_graph_query_reads():
    plan = plan_synthetic_topology(_mini_campus())
    assert {edge.edge_type for edge in plan.edges} == {EDGE_TYPE_CONNECTED_TO}


# --------------------------------------------------------------------------------------
# Honesty / provenance requirements
# --------------------------------------------------------------------------------------


def test_every_edge_is_labelled_synthetic_with_generator_provenance():
    plan = plan_synthetic_topology(_mini_campus())

    assert plan.edges
    for edge in plan.edges:
        assert edge.metadata["synthetic"] is True
        assert edge.metadata["generator"] == SYNTHETIC_TOPOLOGY_GENERATOR


def test_dataset_label_is_recorded_when_supplied():
    plan = plan_synthetic_topology(_mini_campus(), dataset_label="strathmore-demo")
    assert plan.edges
    assert all(edge.metadata["dataset"] == "strathmore-demo" for edge in plan.edges)


def test_edge_metadata_is_flat_primitives_only_for_neo4j():
    plan = plan_synthetic_topology(_mini_campus(), dataset_label="strathmore-demo")
    for edge in plan.edges:
        for key, value in edge.metadata.items():
            assert isinstance(key, str)
            assert isinstance(value, (str, int, float, bool)), f"{key} is not a Neo4j primitive"


# --------------------------------------------------------------------------------------
# Locality and fallback behaviour
# --------------------------------------------------------------------------------------


def test_access_switches_prefer_a_distribution_switch_in_their_own_building():
    devices = _mini_campus()
    by_id = {device.device_id: device for device in devices}
    plan = plan_synthetic_topology(devices)

    checked = 0
    for edge in plan.edges:
        if edge.metadata.get("relation") != "access_uplink":
            continue
        child = by_id[edge.target_id]
        parent = by_id[edge.source_id]
        if child.building_code == "bld-e":
            # Annex has no distribution layer; documented core-homed fallback.
            assert edge.metadata.get("fallback") == "core_homed"
            assert parent.tier == TIER_CORE
        else:
            assert parent.tier == TIER_DISTRIBUTION
            assert parent.building_code == child.building_code
            checked += 1

    assert checked > 0


def test_leaf_devices_attach_to_an_access_switch_on_the_same_floor():
    devices = _mini_campus()
    by_id = {device.device_id: device for device in devices}
    plan = plan_synthetic_topology(devices)

    checked = 0
    for edge in plan.edges:
        if edge.metadata.get("relation") != "leaf_uplink":
            continue
        parent = by_id[edge.source_id]
        child = by_id[edge.target_id]
        assert parent.tier == TIER_ACCESS
        assert parent.building_code == child.building_code
        assert parent.floor_code == child.floor_code
        checked += 1

    assert checked > 0


def test_leaf_uplinks_are_distributed_across_available_access_switches():
    """Round-robin must spread children instead of piling them on one parent."""
    devices = _mini_campus()
    by_id = {device.device_id: device for device in devices}
    plan = plan_synthetic_topology(devices)

    parents_for_sbs_f01 = {
        edge.source_id
        for edge in plan.edges
        if edge.metadata.get("relation") == "leaf_uplink"
        and by_id[edge.target_id].building_code == "sbs"
        and by_id[edge.target_id].floor_code == "f01"
    }
    # sbs/f01 has two access switches; both should carry leaf traffic.
    assert len(parents_for_sbs_f01) == 2


def test_core_devices_are_chained_into_a_connected_backbone():
    devices = _mini_campus()
    plan = plan_synthetic_topology(devices)

    backbone = [edge for edge in plan.edges if edge.metadata.get("relation") == "core_backbone"]
    # Two core routers -> exactly one backbone link, and no ring duplicate.
    assert len(backbone) == 1


def test_three_core_devices_close_the_backbone_ring():
    devices = [
        _device("c1", "rtr-a", "router", "sbs", "f01"),
        _device("c2", "rtr-b", "router", "lib", "f01"),
        _device("c3", "rtr-c", "router", "msb", "f01"),
    ]
    plan = plan_synthetic_topology(devices)

    backbone = [edge for edge in plan.edges if edge.metadata.get("relation") == "core_backbone"]
    assert len(backbone) == 3
    assert all(edge.source_id != edge.target_id for edge in backbone)


# --------------------------------------------------------------------------------------
# Degenerate and hostile inputs
# --------------------------------------------------------------------------------------


def test_empty_input_yields_empty_plan():
    plan = plan_synthetic_topology([])
    assert plan.edges == ()
    assert plan.stats["devices"] == 0
    assert plan.stats["edges"] == 0


def test_single_device_yields_no_edges():
    plan = plan_synthetic_topology([_device("d1", "rtr-1", "router", "sbs", "f01")])
    assert plan.edges == ()


def test_duplicate_device_ids_are_skipped_with_a_warning():
    duplicate = _device("dup", "ap-1", "wireless_ap", "sbs", "f01", "wireless")
    devices = [
        _device("core", "rtr-1", "router", "sbs", "f01"),
        _device("acc", "sw-acc-1", "access_switch", "sbs", "f01", "distribution"),
        duplicate,
        duplicate,
    ]

    plan = plan_synthetic_topology(devices)

    assert plan.stats["devices"] == 3
    assert any("duplicate device_id" in warning for warning in plan.warnings)


def test_device_without_device_id_is_skipped_with_a_warning():
    devices = [
        _device("core", "rtr-1", "router", "sbs", "f01"),
        PlannedDevice(device_id="", hostname="ghost", device_type="wireless_ap"),
    ]

    plan = plan_synthetic_topology(devices)

    assert plan.stats["devices"] == 1
    assert any("empty device_id" in warning for warning in plan.warnings)


def test_devices_without_spatial_ref_still_receive_an_uplink():
    devices = [
        _device("core", "rtr-1", "router", "sbs", "f01"),
        _device("acc", "sw-acc-1", "access_switch", "sbs", "f01", "distribution"),
        PlannedDevice(device_id="floating", hostname="ap-floating", device_type="wireless_ap"),
    ]

    plan = plan_synthetic_topology(devices)

    targets = {edge.target_id for edge in plan.edges}
    assert "floating" in targets


def test_missing_core_tier_is_reported_and_does_not_crash():
    devices = [
        _device("dist", "sw-dist-1", "distribution_switch", "sbs", "f01", "distribution"),
        _device("acc", "sw-acc-1", "access_switch", "sbs", "f01", "distribution"),
        _device("ap", "ap-1", "wireless_ap", "sbs", "f01", "wireless"),
    ]

    plan = plan_synthetic_topology(devices)

    assert any("no core-tier device" in warning for warning in plan.warnings)
    # Access and leaf layers still wire up beneath the distribution switch.
    targets = {edge.target_id for edge in plan.edges}
    assert {"acc", "ap"} <= targets


def test_leaf_only_input_produces_no_edges_but_no_crash():
    devices = [
        _device("ap1", "ap-1", "wireless_ap", "sbs", "f01", "wireless"),
        _device("ap2", "ap-2", "wireless_ap", "sbs", "f01", "wireless"),
    ]

    plan = plan_synthetic_topology(devices)

    assert plan.edges == ()
    assert plan.warnings


def test_stats_report_tier_counts_and_relation_breakdown():
    plan = plan_synthetic_topology(_mini_campus())

    assert plan.stats["tier_core"] == 2
    assert plan.stats["tier_perimeter"] == 2
    assert plan.stats["edges"] == plan.edge_count
    assert plan.stats["relation_core_backbone"] == 1
    assert sum(
        count for key, count in plan.stats.items() if key.startswith("relation_")
    ) == plan.edge_count
