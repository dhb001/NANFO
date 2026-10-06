"""NANFO Backend — Topology event consumer.

Consumes network.device.* events and writes/updates/removes Device nodes in Neo4j.
One of the three consumers of network.device.added (EventAPI.md §5).
Replay ordering and tombstones are persisted atomically by Network in Neo4j: events
order per network by the outbox ``sequence`` in the payload (C13), falling back to
the envelope timestamp for events published before sequences existed.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.neo4j import get_neo4j_driver
from app.modules.network.topology import TopologyQueryService

logger = get_logger(__name__)


async def handle_topology_event(event: dict) -> None:
    """Write topology changes to Neo4j based on network.device.* events."""
    event_type = event.get("event_type", "")
    if event_type not in TOPOLOGY_HANDLERS:
        return
    payload = event["payload"]
    driver = get_neo4j_driver()
    svc = TopologyQueryService(driver)

    applied = await svc.apply_device_event(
        event_type=event_type, payload=payload,
        timestamp=event["timestamp"], event_id=event["event_id"],
    )
    logger.info("topology_event_projected", device_id=payload["device_id"],
                network_id=payload.get("network_id"), sequence=payload.get("sequence"), applied=applied)


TOPOLOGY_HANDLERS: dict[str, object] = {
    "network.device.added": handle_topology_event,
    "network.device.updated": handle_topology_event,
    "network.device.deleted": handle_topology_event,
}
