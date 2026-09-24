"""Network-owned trusted inventory binding and observed discovery (ADR-009).

The discovery service depends only on narrow structural contracts (profile lookup,
network authority + owner device reads, and observed-edge writing), never on
concrete repositories. :func:`build_emulation_discovery` is the single public
composition for one fresh database session. The binding wire primitives
(DPID/Name/strict schema/bounded trusted file read) remain the shared emulation
snapshot format published by Telemetry; no other Telemetry internals are used.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol, Self

from fastapi import HTTPException
from pydantic import Field, model_validator

from app.modules.network.synthetic_topology import PlannedEdge
from app.modules.telemetry.emulation import (
    DPID,
    Name,
    StrictSchema,
    read_bounded_file,
    validate_json,
)

if TYPE_CHECKING:
    from app.modules.telemetry.emulation import EmulationSnapshot


class ProfileLookup(Protocol):
    async def get_profile(self, user_id: str) -> Any: ...


class NetworkAuthority(Protocol):
    """``NetworkService`` subset: write authority plus the public owner device read."""

    async def assert_network_workspace_access(
        self, *, network_id: uuid.UUID, requested_workspace_id: uuid.UUID | None, actor_user_id: str,
        require_write: bool = False,
    ) -> Any: ...

    async def get_devices_for_owner(
        self, *, network_id: uuid.UUID, device_ids: Sequence[uuid.UUID], actor_user_id: str,
        requested_workspace_id: uuid.UUID | None = None,
    ) -> Mapping[uuid.UUID, Any]: ...


class DeviceLookup(Protocol):
    """Deprecated compatibility shape (repository-style lookup); prefer the network read."""

    async def get_by_id(self, device_id: uuid.UUID) -> Any: ...


class ObservedEdgeWriter(Protocol):
    async def replace_observed_device_edges(
        self, *, network_id: str, workspace_id: str, owner_id: str, edges: Sequence[PlannedEdge],
    ) -> int: ...


class EmulationBinding(StrictSchema):
    version: Literal[1]
    topology_id: Literal["campus-small-v1"]
    network_id: uuid.UUID
    workspace_id: uuid.UUID
    actor_user_id: uuid.UUID
    switches: Annotated[dict[DPID, uuid.UUID], Field(min_length=1, max_length=64)]
    hosts: Annotated[dict[Name, uuid.UUID], Field(max_length=256)]
    port_capacities_mbps: Annotated[
        dict[Annotated[str, Field(pattern=r"^[0-9a-f]{16}:[1-9][0-9]{0,9}$")],
             Annotated[float, Field(gt=0, le=1e9, allow_inf_nan=False)]],
        Field(max_length=16384),
    ]

    @model_validator(mode="after")
    def unique_devices(self) -> Self:
        devices = [*self.switches.values(), *self.hosts.values()]
        if len(devices) != len(set(devices)):
            raise ValueError("binding device identities must be unique")
        for key in self.port_capacities_mbps:
            dpid, port = key.split(":")
            if dpid not in self.switches or int(port) > 2**32 - 1:
                raise ValueError("capacity references unknown switch or invalid port")
        return self

    @property
    def owner_id(self) -> str:
        # Stable across runs and mapping repairs, scoped by tenant and topology.
        return str(uuid.uuid5(self.network_id, f"{self.workspace_id}:{self.topology_id}"))


async def load_binding(path: Path, *, snapshot_path: Path) -> EmulationBinding:
    if path.resolve() == snapshot_path.resolve() or path.resolve().is_relative_to(snapshot_path.parent.resolve()):
        raise ValueError("binding must be outside the producer output directory")
    try:
        data = await asyncio.to_thread(read_bounded_file, path, 131072, trusted=True)
        return validate_json(EmulationBinding, data)
    except (OSError, ValueError) as exc:
        raise ValueError("trusted emulation binding unavailable or invalid") from exc


class EmulationDiscoveryService:
    """Public composition contract; call on every poll with a fresh DB session.

    Build it with :func:`build_emulation_discovery`. ``devices`` is a deprecated
    compatibility argument for compositions that still inject a repository-style
    ``get_by_id``; when omitted, devices are read through the Network service's
    public ``get_devices_for_owner`` (one authorized batch read). ``release`` ends
    the caller's database transaction after validation and before any graph write,
    so no PostgreSQL lock or snapshot is held across Neo4j I/O.
    """

    def __init__(self, *, identity: ProfileLookup, network: NetworkAuthority,
                 topology: ObservedEdgeWriter | None = None, expected_topology: dict,
                 devices: DeviceLookup | None = None,
                 release: Callable[[], Awaitable[None]] | None = None):
        self.identity = identity
        self.network = network
        self.devices = devices
        self.topology = topology
        self.expected_topology = expected_topology
        self.release = release

    async def _bound_devices(self, binding: EmulationBinding) -> dict[uuid.UUID, Any]:
        device_ids = [*binding.switches.values(), *binding.hosts.values()]
        if self.devices is None:
            return dict(await self.network.get_devices_for_owner(
                network_id=binding.network_id, device_ids=device_ids,
                actor_user_id=str(binding.actor_user_id), requested_workspace_id=binding.workspace_id,
            ))
        found = {}
        for device_id in device_ids:
            device = await self.devices.get_by_id(device_id)
            if device is not None:
                found[device_id] = device
        return found

    async def validate_binding(self, binding: EmulationBinding) -> dict[str, object]:
        expected = self.expected_topology
        if (binding.topology_id != expected["topology_id"]
                or set(binding.switches) != {s["dpid"] for s in expected["switches"]}
                or set(binding.hosts) != {h["name"] for h in expected["hosts"]}
                or binding.port_capacities_mbps != expected["port_capacities_mbps"]):
            raise ValueError("binding differs from trusted topology configuration")
        profile = await self.identity.get_profile(str(binding.actor_user_id))
        if not {"write:config", "read:topology"}.issubset(profile.permissions):
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        await self.network.assert_network_workspace_access(
            network_id=binding.network_id, requested_workspace_id=binding.workspace_id,
            actor_user_id=str(binding.actor_user_id), require_write=True,
        )
        found = await self._bound_devices(binding)
        inventory = {}
        for identity, device_id in {**binding.switches, **binding.hosts}.items():
            device = found.get(device_id)
            if (device is None or device.network_id != binding.network_id
                    or device.status != "active" or getattr(device, "deleted_at", None) is not None):
                raise ValueError("binding references unavailable or out-of-scope inventory")
            inventory[identity] = device
        return inventory

    async def apply_snapshot(self, binding: EmulationBinding, snapshot: EmulationSnapshot) -> dict:
        inventory = await self.validate_binding(binding)
        switch_names = {s["dpid"]: s["name"] for s in self.expected_topology["switches"]}
        expected_hosts = {h["name"]: h for h in self.expected_topology["hosts"]}
        if binding.topology_id != snapshot.topology_id:
            raise ValueError("snapshot topology does not match binding")
        for switch in snapshot.switches:
            device = inventory.get(switch.dpid)
            if device is None or device.hostname != switch.name or switch_names[switch.dpid] != switch.name:
                raise ValueError("unexpected switch identity")
            for port in switch.ports:
                # Controller local/reserved ports have no trusted capacity and no
                # utilization; physical topology ports must be bound by the operator.
                if port.port_no < 0xffffff00 and f"{switch.dpid}:{port.port_no}" not in binding.port_capacities_mbps:
                    raise ValueError("unexpected switch port")
        for host in snapshot.hosts:
            device = inventory.get(host.name)
            expected_host = expected_hosts.get(host.name)
            if (device is None or device.hostname != host.name
                    or str(device.ip_address) != str(host.ipv4)
                    or host.model_dump(mode="json") != expected_host):
                raise ValueError("unexpected host identity")
        for probe in snapshot.probes:
            if probe.src_host not in binding.hosts or probe.dst_host not in binding.hosts:
                raise ValueError("unexpected probe endpoint")

        def port_bound(dpid: str, port: int) -> None:
            if dpid not in binding.switches or f"{dpid}:{port}" not in binding.port_capacities_mbps:
                raise ValueError("discovery references an unbound port")

        metadata = {"synthetic": False, "execution_mode": "emulation",
                    "topology_id": snapshot.topology_id, "run_id": str(snapshot.run_id),
                    "sequence": snapshot.sequence, "observed_at": snapshot.observed_at.isoformat(),
                    "quality": "measured", "freshness": "fresh"}
        edges = {}
        names = {s["name"]: s["dpid"] for s in self.expected_topology["switches"]}
        expected_links = {
            tuple(sorted(((names[link["a"][0]], link["a"][1]),
                          (names[link["b"][0]], link["b"][1]))))
            for link in self.expected_topology["links"]
            if link["a"][0] in names and link["b"][0] in names
        }
        for link in snapshot.links:
            port_bound(link.src_dpid, link.src_port)
            port_bound(link.dst_dpid, link.dst_port)
            endpoints = sorted([(link.src_dpid, link.src_port), (link.dst_dpid, link.dst_port)])
            if tuple(endpoints) not in expected_links:
                raise ValueError("unexpected discovered link endpoints")
            (src, src_port), (dst, dst_port) = endpoints
            key = f"switch:{src}:{src_port}:{dst}:{dst_port}"
            edges[key] = PlannedEdge(
                source_id=str(binding.switches[src]), target_id=str(binding.switches[dst]),
                edge_type="connected_to", metadata={**metadata, "edge_key": key,
                    "source_port": src_port, "target_port": dst_port,
                    "measurement_method": "lldp_discovery"},
            )
        for host in snapshot.hosts:
            port_bound(host.dpid, host.port_no)
            key = f"host:{host.dpid}:{host.port_no}:{host.name}"
            edges[key] = PlannedEdge(
                source_id=str(binding.switches[host.dpid]), target_id=str(binding.hosts[host.name]),
                edge_type="connected_to", metadata={**metadata, "edge_key": key,
                    "source_port": host.port_no, "target_port": 0, "mac": host.mac,
                    "measurement_method": "host_attachment"},
            )
        for queue in snapshot.queues:
            port_bound(queue.dpid, queue.port_no)
        if self.topology is None:
            raise ValueError("observed topology writer is not configured")
        if self.release is not None:
            # Validation is complete: end the PostgreSQL transaction (and its org/
            # network fences) before graph I/O. The graph writer serializes against
            # device deletion with per-device revision locks.
            await self.release()
        await self.topology.replace_observed_device_edges(
            network_id=str(binding.network_id), workspace_id=str(binding.workspace_id),
            owner_id=binding.owner_id, edges=list(edges.values()),
        )
        return binding.model_dump(mode="json")


def build_emulation_discovery(
    db, redis, *, expected_topology: dict, topology: ObservedEdgeWriter | None = None,
) -> EmulationDiscoveryService:
    """The single public composition of :class:`EmulationDiscoveryService` for ONE session.

    Uses only public owner services (Identity profile lookup, Network authority and
    owner device reads); no repository is constructed by the caller. ``topology`` is
    required only for :meth:`EmulationDiscoveryService.apply_snapshot`; read paths
    that only call ``validate_binding`` omit it. The session's transaction is
    released after validation and before any graph write.
    """
    from app.modules.identity.service import AuthService
    from app.modules.network.service import NetworkService

    return EmulationDiscoveryService(
        identity=AuthService(db, redis), network=NetworkService(db, redis), topology=topology,
        expected_topology=expected_topology, release=db.rollback,
    )
