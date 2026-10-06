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


async def test_inventory_patch_fields_reach_graph_and_ws_unchanged():
    from app.events.consumers.ws_push_consumer import handle_ws_push_event

    changes = {"hostname": "new-router", "device_type": "router", "ip_address": "2001:db8::1",
               "vendor": None, "model": "model", "location_hint": None, "spatial_ref_id": None}
    device_id, network_id = str(uuid.uuid4()), str(uuid.uuid4())
    event = {"event_id": str(uuid.uuid4()), "event_type": "network.device.updated",
             "timestamp": "2026-09-20T00:00:00Z", "payload": {
                 "device_id": device_id, "network_id": network_id, "changed_fields": changes,
             }}
    driver, session, tx = MagicMock(), AsyncMock(), AsyncMock()
    driver.session.return_value.__aenter__.return_value = session
    tx.run.return_value.single.return_value = {"deleted": False, "matched": 1}

    async def execute(callback):
        return await callback(tx)

    session.execute_write.side_effect = execute
    assert await TopologyQueryService(driver).apply_device_event(
        event_type=event["event_type"], payload=event["payload"], timestamp=event["timestamp"], event_id=event["event_id"],
    )
    assert tx.run.await_args_list[2].kwargs["properties"] == changes
    with patch("app.events.consumers.ws_push_consumer.push_realtime_delta", new_callable=AsyncMock) as push:
        await handle_ws_push_event(event)
        assert push.call_args.kwargs["node"] == {"device_id": device_id, **changes}


@pytest.mark.parametrize("sequence", [0, -1, True, "7", 1.5, 2**63])
async def test_invalid_sequence_is_rejected_before_any_graph_write(sequence):
    driver = MagicMock()
    with pytest.raises(ValueError, match="sequence"):
        await TopologyQueryService(driver).apply_device_event(
            event_type="network.device.deleted", payload={"device_id": str(uuid.uuid4()), "sequence": sequence},
            timestamp="2026-09-09T00:00:00Z", event_id=str(uuid.uuid4()),
        )
    driver.session.assert_not_called()


@pytest.mark.parametrize("sequence", [None, 7])
async def test_revision_orders_by_outbox_sequence_with_timestamp_fallback(sequence):
    """C13: (network_id, sequence) ordering when present; epoch for pre-sequence events."""
    driver = MagicMock()
    session = AsyncMock()
    driver.session.return_value.__aenter__.return_value = session
    tx = AsyncMock()
    tx.run.return_value.single.return_value = {"deleted": False}

    async def execute_write(callback):
        assert callback.timeout > 0  # bounded unit of work
        return await callback(tx)

    session.execute_write.side_effect = execute_write
    payload = {"device_id": str(uuid.uuid4())}
    if sequence is not None:
        payload["sequence"] = sequence
    assert await TopologyQueryService(driver).apply_device_event(
        event_type="network.device.deleted", payload=payload,
        timestamp="2026-09-09T00:00:00Z", event_id=str(uuid.uuid4()),
    )
    select, advance = tx.run.await_args_list[1], tx.run.await_args_list[3]
    assert select.kwargs["sequence"] == sequence and advance.kwargs["sequence"] == sequence
    assert "$sequence > r.sequence" in select.args[0]
    assert "($sequence IS NULL OR r.sequence IS NULL)" in select.args[0]
    # The stored sequence only advances; the clock triple never moves backwards.
    assert "r.sequence = coalesce($sequence, r.sequence)" in advance.args[0]
    assert "CASE WHEN advances THEN $epoch_us ELSE r.epoch_us END" in advance.args[0]


async def test_consumer_passes_sequence_through_payload():
    payload = {"device_id": str(uuid.uuid4()), "network_id": str(uuid.uuid4()), "sequence": 9}
    event = {"event_type": "network.device.deleted", "payload": payload,
             "timestamp": "2026-09-09T00:00:00Z", "event_id": str(uuid.uuid4())}
    svc = MagicMock()
    svc.apply_device_event = AsyncMock(return_value=True)
    with (
        patch("app.events.consumers.topology_consumer.get_neo4j_driver", return_value=MagicMock()),
        patch("app.events.consumers.topology_consumer.TopologyQueryService", return_value=svc),
    ):
        await handle_topology_event(event)
    assert svc.apply_device_event.await_args.kwargs["payload"]["sequence"] == 9
