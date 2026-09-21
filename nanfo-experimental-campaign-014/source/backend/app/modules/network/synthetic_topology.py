"""NANFO Backend — Deterministic synthetic topology planner.

Purpose
-------
Demo/reference datasets (for example ``scripts/prepare_strathmore_demo.py``) create
device inventory but no ``CONNECTED_TO`` relationships, which leaves the Digital
Twin with nodes and zero edges.

This module derives a *deterministic, reproducible* layered network hierarchy from
device inventory alone:

    Perimeter firewall -> Core router -> Distribution switch -> Access switch -> Leaf

Honesty constraints (non-negotiable)
------------------------------------
* Every edge produced here is **synthetic demonstration topology**, not discovered
  infrastructure. Each edge carries ``synthetic=True`` plus generator provenance so
  downstream consumers and the UI can label it truthfully.
* No physical infrastructure is invented: the planner only connects devices that
  already exist in inventory, using their declared ``device_type`` and
  ``spatial_ref_id``.
* There is no randomness. Output depends only on the input device set, so repeated
  runs are byte-identical.

Ownership: Network module (Topology.md §4 — topology entity ownership).
This module is pure: no database, Neo4j, event bus, or network I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

__all__ = [
    "EDGE_TYPE_CONNECTED_TO",
    "SYNTHETIC_TOPOLOGY_GENERATOR",
    "PlannedDevice",
    "PlannedEdge",
    "SyntheticTopologyPlan",
    "device_tier",
    "plan_synthetic_topology",
]

SYNTHETIC_TOPOLOGY_GENERATOR = "nanfo.synthetic_topology.v1"

#: Neo4j relationship type already read by ``TopologyQueryService.get_graph``.
EDGE_TYPE_CONNECTED_TO = "connected_to"

TIER_PERIMETER = "perimeter"
TIER_CORE = "core"
TIER_DISTRIBUTION = "distribution"
TIER_ACCESS = "access"
TIER_LEAF = "leaf"

#: Ordered from upstream (closest to the WAN edge) to downstream.
TIER_ORDER: tuple[str, ...] = (
    TIER_PERIMETER,
    TIER_CORE,
    TIER_DISTRIBUTION,
    TIER_ACCESS,
    TIER_LEAF,
)

#: ``device_type`` -> logical tier.
#:
#: Values match the device types emitted by the Strathmore demo generator and the
#: generic types used elsewhere ("switch" is treated as an access switch because it
#: is the least-privileged sane default).
DEVICE_TYPE_TIERS: Mapping[str, str] = {
    "firewall": TIER_PERIMETER,
    "router": TIER_CORE,
    "core_router": TIER_CORE,
    "distribution_switch": TIER_DISTRIBUTION,
    "access_switch": TIER_ACCESS,
    "switch": TIER_ACCESS,
    "wireless_ap": TIER_LEAF,
    "server": TIER_LEAF,
    "security_gateway": TIER_LEAF,
    "ups": TIER_LEAF,
    "lab_endpoint": TIER_LEAF,
}

#: Unknown device types are attached at the least-privileged tier so that they are
#: still reachable in the scene without being promoted into the network core.
DEFAULT_TIER = TIER_LEAF


@dataclass(frozen=True)
class PlannedDevice:
    """Minimal device projection required to plan topology."""

    device_id: str
    hostname: str
    device_type: str
    spatial_ref_id: str | None = None

    @property
    def tier(self) -> str:
        return device_tier(self.device_type)

    @property
    def building_code(self) -> str | None:
        return _spatial_segment(self.spatial_ref_id, 1)

    @property
    def floor_code(self) -> str | None:
        return _spatial_segment(self.spatial_ref_id, 2)

    @property
    def campus_code(self) -> str | None:
        return _spatial_segment(self.spatial_ref_id, 0)

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """Stable ordering key. ``spatial_ref_id`` first keeps buildings grouped."""
        return (self.spatial_ref_id or "~", self.hostname or "~", self.device_id)


@dataclass(frozen=True)
class PlannedEdge:
    """A single directed, synthetic uplink: ``source_id`` is upstream of ``target_id``."""

    source_id: str
    target_id: str
    edge_type: str
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source_id, self.target_id, self.edge_type)


@dataclass(frozen=True)
class SyntheticTopologyPlan:
    """Deterministic result of planning. ``edges`` is sorted and de-duplicated."""

    edges: tuple[PlannedEdge, ...] = ()
    warnings: tuple[str, ...] = ()
    stats: Mapping[str, int] = field(default_factory=dict)

    @property
    def edge_count(self) -> int:
        return len(self.edges)


def device_tier(device_type: str | None) -> str:
    """Map a ``device_type`` to a logical network tier."""
    if not device_type:
        return DEFAULT_TIER
    return DEVICE_TYPE_TIERS.get(device_type.strip().lower(), DEFAULT_TIER)


def _spatial_segment(spatial_ref_id: str | None, index: int) -> str | None:
    """Return segment ``index`` of ``campus/building/floor/zone/device``."""
    if not spatial_ref_id:
        return None
    segments = [segment for segment in spatial_ref_id.strip().split("/") if segment.strip()]
    if index >= len(segments):
        return None
    return segments[index].strip().lower() or None


def _sorted_devices(devices: Iterable[PlannedDevice]) -> list[PlannedDevice]:
    return sorted(devices, key=lambda device: device.sort_key)


def _pick_round_robin(
    candidates: list[PlannedDevice],
    ordinal: int,
    exclude_device_id: str,
) -> PlannedDevice | None:
    """Deterministically choose one candidate, never returning ``exclude_device_id``.

    Round-robin over a stably sorted candidate list distributes children evenly
    across parents without any randomness.
    """
    usable = [candidate for candidate in candidates if candidate.device_id != exclude_device_id]
    if not usable:
        return None
    return usable[ordinal % len(usable)]


def plan_synthetic_topology(
    devices: Iterable[PlannedDevice],
    *,
    generator: str = SYNTHETIC_TOPOLOGY_GENERATOR,
    dataset_label: str | None = None,
) -> SyntheticTopologyPlan:
    """Build a deterministic layered topology from device inventory.

    Rules, applied in order:

    1. **Core backbone** — core devices are chained into a stable ring/line so the
       core is connected rather than a set of islands.
    2. **Perimeter -> core** — each firewall uplinks to a core device, preferring one
       in the same building.
    3. **Distribution -> core** — each distribution switch uplinks to a core device.
    4. **Access -> distribution** — each access switch uplinks to a distribution
       switch in the same building; annex buildings with no distribution switch home
       directly to the core (documented fallback, mirrors real small-site designs).
    5. **Leaf -> access** — access points, servers, UPS, security gateways and lab
       endpoints uplink to an access switch on the same floor, then same building,
       then any access switch, then distribution, then core.

    Returns a plan whose ``edges`` contain no duplicates and no self-links.
    """
    ordered = _sorted_devices(devices)

    by_tier: dict[str, list[PlannedDevice]] = {tier: [] for tier in TIER_ORDER}
    seen_device_ids: set[str] = set()
    warnings: list[str] = []

    for device in ordered:
        if not device.device_id:
            warnings.append(f"skipped device with empty device_id (hostname={device.hostname!r})")
            continue
        if device.device_id in seen_device_ids:
            warnings.append(f"skipped duplicate device_id {device.device_id}")
            continue
        seen_device_ids.add(device.device_id)
        by_tier[device.tier].append(device)

    core_devices = by_tier[TIER_CORE]
    distribution_devices = by_tier[TIER_DISTRIBUTION]
    access_devices = by_tier[TIER_ACCESS]

    # Grouping indexes for locality-aware parent selection.
    distribution_by_building = _group_by(distribution_devices, lambda device: device.building_code)
    access_by_building = _group_by(access_devices, lambda device: device.building_code)
    access_by_floor = _group_by(
        access_devices,
        lambda device: (device.building_code, device.floor_code),
    )

    edges: dict[tuple[str, str, str], PlannedEdge] = {}

    def add_edge(
        parent: PlannedDevice | None,
        child: PlannedDevice,
        *,
        relation: str,
        fallback: str | None = None,
    ) -> bool:
        if parent is None:
            return False
        if parent.device_id == child.device_id:
            return False

        metadata: dict[str, object] = {
            "synthetic": True,
            "generator": generator,
            "relation": relation,
            "parent_tier": parent.tier,
            "child_tier": child.tier,
        }
        if dataset_label:
            metadata["dataset"] = dataset_label
        if fallback:
            metadata["fallback"] = fallback

        edge = PlannedEdge(
            source_id=parent.device_id,
            target_id=child.device_id,
            edge_type=EDGE_TYPE_CONNECTED_TO,
            metadata=metadata,
        )
        edges.setdefault(edge.key, edge)
        return True

    # 1. Core backbone: chain sorted core devices so the core is one connected unit.
    for index in range(len(core_devices) - 1):
        add_edge(core_devices[index], core_devices[index + 1], relation="core_backbone")
    # Close the ring only when it adds a genuinely new link (3+ core devices).
    if len(core_devices) > 2:
        add_edge(core_devices[-1], core_devices[0], relation="core_backbone")

    if not core_devices:
        warnings.append("no core-tier device found; perimeter and distribution uplinks were skipped")

    # 2. Perimeter -> core.
    for ordinal, firewall in enumerate(by_tier[TIER_PERIMETER]):
        parent = _pick_local_then_global(
            preferred=_group_lookup(_group_by(core_devices, lambda d: d.building_code), firewall.building_code),
            fallback_pool=core_devices,
            ordinal=ordinal,
            exclude_device_id=firewall.device_id,
        )
        if not add_edge(parent, firewall, relation="perimeter_uplink"):
            warnings.append(f"no core uplink available for firewall {firewall.hostname or firewall.device_id}")

    # 3. Distribution -> core.
    for ordinal, distribution in enumerate(distribution_devices):
        parent = _pick_round_robin(core_devices, ordinal, distribution.device_id)
        if not add_edge(parent, distribution, relation="distribution_uplink"):
            warnings.append(
                f"no core uplink available for distribution switch "
                f"{distribution.hostname or distribution.device_id}"
            )

    # 4. Access -> distribution (same building), else core.
    for ordinal, access in enumerate(access_devices):
        building_pool = _group_lookup(distribution_by_building, access.building_code)
        parent = _pick_round_robin(building_pool, ordinal, access.device_id)
        if parent is not None:
            add_edge(parent, access, relation="access_uplink")
            continue

        # Annex buildings ship without a distribution layer; home them to the core.
        parent = _pick_round_robin(core_devices, ordinal, access.device_id)
        if add_edge(parent, access, relation="access_uplink", fallback="core_homed"):
            continue

        parent = _pick_round_robin(distribution_devices, ordinal, access.device_id)
        if not add_edge(parent, access, relation="access_uplink", fallback="remote_distribution"):
            warnings.append(
                f"no upstream available for access switch {access.hostname or access.device_id}"
            )

    # 5. Leaf -> access (same floor -> same building -> any), else distribution, else core.
    for ordinal, leaf in enumerate(by_tier[TIER_LEAF]):
        floor_pool = _group_lookup(access_by_floor, (leaf.building_code, leaf.floor_code))
        parent = _pick_round_robin(floor_pool, ordinal, leaf.device_id)
        if add_edge(parent, leaf, relation="leaf_uplink"):
            continue

        building_pool = _group_lookup(access_by_building, leaf.building_code)
        parent = _pick_round_robin(building_pool, ordinal, leaf.device_id)
        if add_edge(parent, leaf, relation="leaf_uplink", fallback="building_access"):
            continue

        parent = _pick_round_robin(access_devices, ordinal, leaf.device_id)
        if add_edge(parent, leaf, relation="leaf_uplink", fallback="campus_access"):
            continue

        building_distribution = _group_lookup(distribution_by_building, leaf.building_code)
        parent = _pick_round_robin(building_distribution or distribution_devices, ordinal, leaf.device_id)
        if add_edge(parent, leaf, relation="leaf_uplink", fallback="distribution_attached"):
            continue

        parent = _pick_round_robin(core_devices, ordinal, leaf.device_id)
        if not add_edge(parent, leaf, relation="leaf_uplink", fallback="core_attached"):
            warnings.append(f"no upstream available for leaf device {leaf.hostname or leaf.device_id}")

    sorted_edges = tuple(sorted(edges.values(), key=lambda edge: edge.key))

    stats: dict[str, int] = {
        "devices": len(seen_device_ids),
        "edges": len(sorted_edges),
        **{f"tier_{tier}": len(by_tier[tier]) for tier in TIER_ORDER},
    }
    for edge in sorted_edges:
        relation = str(edge.metadata.get("relation", "unknown"))
        stats[f"relation_{relation}"] = stats.get(f"relation_{relation}", 0) + 1

    return SyntheticTopologyPlan(
        edges=sorted_edges,
        warnings=tuple(warnings),
        stats=stats,
    )


def _group_by(devices: Iterable[PlannedDevice], key_fn) -> dict[object, list[PlannedDevice]]:
    grouped: dict[object, list[PlannedDevice]] = {}
    for device in devices:
        grouped.setdefault(key_fn(device), []).append(device)
    return grouped


def _group_lookup(grouped: Mapping[object, list[PlannedDevice]], key: object) -> list[PlannedDevice]:
    if key is None or (isinstance(key, tuple) and any(part is None for part in key)):
        return []
    return grouped.get(key, [])


def _pick_local_then_global(
    *,
    preferred: list[PlannedDevice],
    fallback_pool: list[PlannedDevice],
    ordinal: int,
    exclude_device_id: str,
) -> PlannedDevice | None:
    local = _pick_round_robin(preferred, ordinal, exclude_device_id)
    if local is not None:
        return local
    return _pick_round_robin(fallback_pool, ordinal, exclude_device_id)
