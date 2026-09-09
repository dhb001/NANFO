"""Strict event-time validation and transactional projection boundaries."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.events.consumers.topology_consumer import handle_topology_event
from app.modules.network.topology import TopologyQueryService


@pytest.mark.parametrize("timestamp", [None, "", "yesterday", "2026-09-09",
    "2026-09-09T00:00:00", "2026-02-30T00:00:00Z", "2026-09-09T00:00:00.0000001Z",
    "2026-09-09T00:00:00+00:99"])
async def test_invalid_event_timestamp_never_writes(timestamp):
    driver = MagicMock()
    with pytest.raises(ValueError):
        await TopologyQueryService(driver).apply_device_event(
            event_type="network.device.deleted", payload={"device_id": str(uuid.uuid4())},
            timestamp=timestamp, event_id=str(uuid.uuid4()),
        )
    driver.session.assert_not_called()


@pytest.mark.parametrize("missing", ["timestamp", "event_id"])
async def test_consumer_rejects_missing_envelope_instead_of_fabricating_revision(missing):
    event = {"event_type": "network.device.deleted", "payload": {"device_id": str(uuid.uuid4())},
             "timestamp": "2026-09-09T00:00:00Z", "event_id": str(uuid.uuid4())}
    del event[missing]
    with (
        patch("app.events.consumers.topology_consumer.get_neo4j_driver", return_value=MagicMock()),
        pytest.raises(KeyError),
    ):
        await handle_topology_event(event)


async def test_revision_uses_integer_utc_microseconds_and_commits_with_effect():
    driver = MagicMock()
    session = AsyncMock()
    driver.session.return_value.__aenter__.return_value = session
    tx = AsyncMock()
    tx.run.return_value.single.return_value = {"deleted": False}
    async def execute_write(callback):
        return await callback(tx)

    session.execute_write.side_effect = execute_write
    event_id = str(uuid.uuid4())
    assert await TopologyQueryService(driver).apply_device_event(
        event_type="network.device.deleted", payload={"device_id": str(uuid.uuid4())},
        timestamp="1970-01-01T01:00:00.000001+01:00", event_id=event_id,
    )
    calls = tx.run.await_args_list
    assert "SET r._lock" in calls[0].args[0]
    assert calls[1].kwargs["epoch_us"] == 1
    assert "d.status = 'deleted'" in calls[2].args[0]
    assert calls[3].kwargs["epoch_us"] == 1
    assert calls[3].kwargs["event_id"] == event_id
    assert calls[3].kwargs["deleted"] is True


@pytest.mark.parametrize("fields", [{"device_id": "other"}, {"_lock": 1},
    {"epoch_us": 1}, {"hostname = 'injected'": "x"}, {"status": {"nested": True}}])
async def test_update_cannot_inject_cypher_or_overwrite_identity(fields):
    driver = MagicMock()
    with pytest.raises(ValueError):
        await TopologyQueryService(driver).apply_device_event(
            event_type="network.device.updated", payload={"device_id": str(uuid.uuid4()), "changed_fields": fields},
            timestamp="2026-09-09T00:00:00Z", event_id=str(uuid.uuid4()),
        )
    driver.session.assert_not_called()


async def test_graph_failure_propagates_without_committing_revision():
    driver = MagicMock()
    session = AsyncMock()
    driver.session.return_value.__aenter__.return_value = session
    tx = AsyncMock()
    result = AsyncMock()
    result.single.return_value = {"deleted": False}
    tx.run.side_effect = [result, result, RuntimeError("graph write failed")]
    async def execute_write(callback):
        return await callback(tx)

    session.execute_write.side_effect = execute_write
    with pytest.raises(RuntimeError, match="graph write failed"):
        await TopologyQueryService(driver).apply_device_event(
            event_type="network.device.deleted", payload={"device_id": str(uuid.uuid4())},
            timestamp="2026-09-09T00:00:00Z", event_id=str(uuid.uuid4()),
        )
    assert tx.run.await_count == 3
