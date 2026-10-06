"""Real Neo4j replay tests in a disposable container with no shared mounts.

NANFO_TOPOLOGY_LIVE=1 poetry run pytest tests/live/test_topology_event_revision.py -q --no-cov
Requires Docker and the existing neo4j:5.25-community image. Never touches the
configured application database, Redis streams, or another agent's containers.
"""

import asyncio
import json
import os
import secrets
import subprocess
import uuid
from unittest.mock import patch

import pytest
from neo4j import AsyncGraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from app.events.consumers.topology_consumer import handle_topology_event
from app.modules.network.synthetic_topology import EDGE_TYPE_CONNECTED_TO, PlannedEdge
from app.modules.network.topology import TopologyQueryService, ensure_graph_schema


@pytest.fixture
async def graph():
    if os.environ.get("NANFO_TOPOLOGY_LIVE") != "1":
        pytest.skip("requires explicit NANFO_TOPOLOGY_LIVE=1")
    name = f"nanfo-topology-replay-{uuid.uuid4().hex}"
    password = secrets.token_hex(20)
    driver = None
    created = False
    try:
        await asyncio.to_thread(subprocess.run, [
            "docker", "run", "--detach", "--pull=never", "--name", name,
            "--memory=1g", "--cpus=2", "--publish", "127.0.0.1::7687",
            "--env", "NEO4J_AUTH", "--env", "NEO4J_server_memory_heap_initial__size=256m",
            "--env", "NEO4J_server_memory_heap_max__size=256m",
            "--env", "NEO4J_server_memory_pagecache_size=128m", "neo4j:5.25-community",
        ], check=True, capture_output=True, timeout=30,
            env={**os.environ, "NEO4J_AUTH": f"neo4j/{password}"})
        created = True
        output = await asyncio.to_thread(subprocess.run, [
            "docker", "inspect", "--format", '{{json .NetworkSettings.Ports}}', name,
        ], check=True, capture_output=True, text=True, timeout=10)
        port = json.loads(output.stdout)["7687/tcp"][0]["HostPort"]
        driver = AsyncGraphDatabase.driver(
            f"bolt://127.0.0.1:{port}", auth=("neo4j", password), connection_timeout=2,
            max_transaction_retry_time=5,
        )
        async with asyncio.timeout(90):
            while True:
                try:
                    await driver.verify_connectivity()
                    break
                except (ServiceUnavailable, Neo4jError):
                    await asyncio.sleep(1)
        yield driver
    finally:
        if driver is not None:
            await driver.close()
        if created:
            await asyncio.to_thread(subprocess.run, ["docker", "rm", "--force", "--volumes", name],
                                    check=True, capture_output=True, timeout=30)


def device_event(action, *, device_id=None, timestamp="2026-09-09T00:00:00Z", event_id=None, changes=None):
    payload = {"device_id": device_id or str(uuid.uuid4())}
    if action == "added":
        payload.update(network_id=str(uuid.uuid4()), workspace_id=str(uuid.uuid4()),
                       hostname="replay-test", device_type="switch")
    if action == "updated":
        payload["changed_fields"] = changes or {"hostname": "new-name"}
    return {"event_type": f"network.device.{action}", "payload": payload,
            "timestamp": timestamp, "event_id": event_id or str(uuid.uuid4())}


async def state(driver, device_id):
    async with driver.session() as session:
        result = await session.run("""
            MATCH (r:DeviceEventRevision {device_id: $id})
            OPTIONAL MATCH (d:Device {device_id: $id})
            RETURN properties(r) AS revision, properties(d) AS device
        """, id=device_id)
        return await result.single()


async def test_real_neo4j_replay_tombstones_updates_and_atomic_concurrency(graph):
    # Schema is created once at startup, never per event (ADR-028).
    assert set((await ensure_graph_schema(graph)).values()) == {"ok"}
    # Use the actual consumer: timestamp/id must survive its boundary unchanged.
    with patch("app.events.consumers.topology_consumer.get_neo4j_driver", return_value=graph):
        add = device_event("added")
        device_id = add["payload"]["device_id"]
        delete = device_event("deleted", device_id=device_id, timestamp="2026-09-09T00:00:02Z")
        await handle_topology_event(add)
        await handle_topology_event(delete)
        await handle_topology_event(add)  # Redis completion marker absent/expired.
        row = await state(graph, device_id)
        assert row["device"]["status"] == "deleted"
        assert row["revision"]["event_id"] == delete["event_id"]
        assert row["revision"]["deleted"] is True
        await handle_topology_event(device_event(
            "updated", device_id=device_id, timestamp="2026-09-09T00:00:03Z", changes={"status": "active"},
        ))
        assert (await state(graph, device_id))["device"]["status"] == "deleted"
        assert (await state(graph, device_id))["revision"]["event_id"] == delete["event_id"]

        # Delete-before-add retains an independent tombstone, not a bogus Device.
        missing_add = device_event("added")
        missing_id = missing_add["payload"]["device_id"]
        missing_delete = device_event("deleted", device_id=missing_id, timestamp="2026-09-09T00:00:02Z")
        await handle_topology_event(missing_delete)
        await handle_topology_event(missing_add)
        row = await state(graph, missing_id)
        assert row["device"] is None
        assert row["revision"]["event_id"] == missing_delete["event_id"]
        # A genuinely newer add may recreate the device; replay still cannot.
        new_add = {**missing_add, "timestamp": "2026-09-09T00:00:04Z", "event_id": str(uuid.uuid4())}
        await handle_topology_event(new_add)
        await handle_topology_event(missing_delete)
        row = await state(graph, missing_id)
        assert row["device"]["status"] == "active"
        assert row["revision"]["event_id"] == new_add["event_id"]

        updated_add = device_event("added")
        updated_id = updated_add["payload"]["device_id"]
        old_update = device_event("updated", device_id=updated_id, timestamp="2026-09-09T00:00:01Z",
                                  changes={"hostname": "old"})
        update = device_event("updated", device_id=updated_id, timestamp="2026-09-09T00:00:02.000001Z")
        await handle_topology_event(updated_add)
        await handle_topology_event(update)
        await handle_topology_event(update)
        await handle_topology_event(old_update)
        row = await state(graph, updated_id)
        assert row["device"]["hostname"] == "new-name"
        assert row["revision"]["event_id"] == update["event_id"]

        # Same instant expressed with another offset: delete wins regardless of UUID.
        for reversed_order in (False, True):
            tie_add = device_event("added", event_id=str(uuid.UUID(int=999)))
            tie_id = tie_add["payload"]["device_id"]
            tie_delete = device_event("deleted", device_id=tie_id, event_id=str(uuid.UUID(int=1)),
                                      timestamp="2026-09-09T01:00:00+01:00")
            events = [tie_add, tie_delete]
            for event in reversed(events) if reversed_order else events:
                await handle_topology_event(event)
            row = await state(graph, tie_id)
            assert row["revision"]["event_id"] == tie_delete["event_id"]
            assert row["device"] is None or row["device"]["status"] == "deleted"

        # Concurrent first arrivals must share one revision/lock, not duplicate it.
        concurrent_add = device_event("added")
        concurrent_id = concurrent_add["payload"]["device_id"]
        concurrent_delete = device_event("deleted", device_id=concurrent_id,
                                         timestamp="2026-09-09T00:00:03Z")
        await asyncio.wait_for(asyncio.gather(*[
            handle_topology_event(event) for event in [concurrent_add, concurrent_delete] * 4
        ]), 30)
        row = await state(graph, concurrent_id)
        assert row["revision"]["event_id"] == concurrent_delete["event_id"]
        assert row["device"] is None or row["device"]["status"] == "deleted"
        async with graph.session() as session:
            result = await session.run("MATCH (r:DeviceEventRevision {device_id: $id}) RETURN count(r) AS n",
                                       id=concurrent_id)
            assert (await result.single())["n"] == 1

        # Equal timestamp updates converge on UUID order even when delivery reverses.
        high = device_event("updated", device_id=updated_id, timestamp="2026-09-09T00:00:03Z",
                            event_id=str(uuid.UUID(int=999)), changes={"hostname": "winner"})
        low = device_event("updated", device_id=updated_id, timestamp=high["timestamp"],
                           event_id=str(uuid.UUID(int=1)), changes={"hostname": "loser"})
        await asyncio.gather(handle_topology_event(high), handle_topology_event(low))
        assert (await state(graph, updated_id))["device"]["hostname"] == "winner"

        # Missing update rolls back its revision so an older add can subsequently apply.
        late_add = device_event("added")
        late_id = late_add["payload"]["device_id"]
        early_update = device_event("updated", device_id=late_id, timestamp="2026-09-09T00:00:01Z")
        with pytest.raises(ValueError, match="before its add"):
            await handle_topology_event(early_update)
        assert await state(graph, late_id) is None
        await handle_topology_event(late_add)
        await handle_topology_event(early_update)
        assert (await state(graph, late_id))["device"]["hostname"] == "new-name"

        # C13: outbox sequence order wins over skewed producer timestamps; a replayed
        # (not newer) sequence never applies, even with a later timestamp.
        seq_add = device_event("added", timestamp="2026-09-09T00:00:09Z")
        seq_add["payload"]["sequence"] = 10
        seq_id = seq_add["payload"]["device_id"]
        skewed = device_event("updated", device_id=seq_id, timestamp="2026-09-09T00:00:01Z",
                              changes={"hostname": "sequenced"})
        skewed["payload"]["sequence"] = 11
        replayed = device_event("updated", device_id=seq_id, timestamp="2026-09-09T00:00:30Z",
                                changes={"hostname": "stale"})
        replayed["payload"]["sequence"] = 11
        for event in (seq_add, skewed, replayed):
            await handle_topology_event(event)
        row = await state(graph, seq_id)
        assert row["device"]["hostname"] == "sequenced" and row["revision"]["sequence"] == 11
        legacy = device_event("updated", device_id=seq_id, timestamp="2026-09-09T00:00:05Z",
                              changes={"hostname": "legacy-older"})
        await handle_topology_event(legacy)  # pre-sequence event: timestamp fallback, older -> ignored
        assert (await state(graph, seq_id))["device"]["hostname"] == "sequenced"

        # Deleting a device removes its relationships; traversals never cross it.
        scope = {"network_id": str(uuid.uuid4()), "workspace_id": str(uuid.uuid4())}
        chain = [device_event("added") for _ in range(3)]
        for event in chain:
            event["payload"].update(scope)
            await handle_topology_event(event)
        a, b, c = (event["payload"]["device_id"] for event in chain)
        svc = TopologyQueryService(graph)
        plan = [PlannedEdge(a, b, EDGE_TYPE_CONNECTED_TO, {"synthetic": True, "generator": "live"}),
                PlannedEdge(b, c, EDGE_TYPE_CONNECTED_TO, {"synthetic": True, "generator": "live"})]
        assert await svc.replace_synthetic_device_edges(**scope, edges=plan, generator="live") == (0, 2)
        root = uuid.UUID(a)
        found = await svc.get_device_neighbours(device_id=root, network_id=scope["network_id"],
                                                workspace_id=scope["workspace_id"], depth=6)
        assert {item.device_id: item.hop_depth for item in found.neighbours} == {b: 1, c: 2}
        await handle_topology_event(device_event("deleted", device_id=b, timestamp="2026-09-10T00:00:00Z"))
        found = await svc.get_device_neighbours(device_id=root, network_id=scope["network_id"],
                                                workspace_id=scope["workspace_id"], depth=6)
        assert found.neighbours == []
        async with graph.session() as session:
            result = await session.run("MATCH (d:Device {device_id: $id})-[e]-() RETURN count(e) AS n", id=b)
            assert (await result.single())["n"] == 0

        # ADR-028 fix 7: seed/discovery edge MERGEs take the endpoint revision locks,
        # so a concurrent delete can never leave an edge attached to a tombstone.
        racers = [device_event("added") for _ in range(2)]
        for event in racers:
            event["payload"].update(scope)
            await handle_topology_event(event)
        x, y = (event["payload"]["device_id"] for event in racers)
        edge = [PlannedEdge(x, y, EDGE_TYPE_CONNECTED_TO, {"synthetic": True, "generator": "race"})]
        await asyncio.wait_for(asyncio.gather(
            *[svc.replace_synthetic_device_edges(**scope, edges=edge, generator="race") for _ in range(4)],
            handle_topology_event(device_event("deleted", device_id=y, timestamp="2026-09-11T00:00:00Z")),
        ), 30)
        async with graph.session() as session:
            result = await session.run("MATCH (d:Device {device_id: $id})-[e]-() RETURN count(e) AS n", id=y)
            assert (await result.single())["n"] == 0
        # Replaying the seed after the delete still cannot attach to the tombstone.
        assert await svc.replace_synthetic_device_edges(**scope, edges=edge, generator="race") == (0, 0)
