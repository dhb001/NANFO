"""NANFO Backend — Topology event consumer.

Consumes network.device.* events and writes/updates/removes Device nodes in Neo4j.
One of the three consumers of network.device.added (EventAPI.md §5).
Idempotency: MERGE on device_id prevents duplicate nodes on replay.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.neo4j import get_neo4j_driver
from app.modules.network.topology import TopologyQueryService

logger = get_logger(__name__)


async def handle_topology_event(event: dict) -> None:
    """Write topology changes to Neo4j based on network.device.* events."""
    event_type = event.get("event_type", "")
    payload = event.get("payload", {})
    driver = get_neo4j_driver()
    svc = TopologyQueryService(driver)

    if event_type == "network.device.added":
        await svc.create_device_node(
            device_id=payload["device_id"],
            network_id=payload["network_id"],
            workspace_id=payload["workspace_id"],
            hostname=payload["hostname"],
            device_type=payload["device_type"],
            status="active",
        )
        logger.info("topology_node_added", device_id=payload["device_id"])

    elif event_type == "network.device.updated":
        changed = payload.get("changed_fields", {})
        if changed:
            # Build SET clause from changed_fields
            set_parts = ", ".join(f"d.{k} = ${k}" for k in changed)
            query = f"MATCH (d:Device {{device_id: $device_id}}) SET {set_parts}"
            async with driver.session() as session:
                await session.run(query, device_id=payload["device_id"], **changed)
            logger.info("topology_node_updated", device_id=payload["device_id"])

    elif event_type == "network.device.deleted":
        query = "MATCH (d:Device {device_id: $device_id}) SET d.status = 'deleted'"
        async with driver.session() as session:
            await session.run(query, device_id=payload["device_id"])
        logger.info("topology_node_soft_deleted", device_id=payload["device_id"])


TOPOLOGY_HANDLERS: dict[str, object] = {
    "network.device.added": handle_topology_event,
    "network.device.updated": handle_topology_event,
    "network.device.deleted": handle_topology_event,
}
