"""Independent live-verifier calculations reject altered evidence."""

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.telemetry.emulation import EmulationSnapshot
from scripts.verify_emulation import verify_measurements


@pytest.mark.parametrize("fault", [None, "value", "time", "device", "synthetic"])
def test_independent_queue_evidence_validation(fault):
    dpid, device_id = "0000000000000001", uuid.uuid4()
    run_id, observed = str(uuid.uuid4()), datetime.now(UTC).isoformat()
    snapshot = EmulationSnapshot.model_validate_json(json.dumps({
        "version": 1, "topology_id": "campus-small-v1", "run_id": run_id,
        "sequence": 0, "observed_at": observed, "switches": [], "links": [],
        "hosts": [], "probes": [], "queues": [{"dpid": dpid, "port_no": 1,
            "observed_at": observed, "backlog_bytes": 321, "backlog_packets": 2}],
    }))
    sample = {"device_id": str(device_id), "metric": "queue_backlog_bytes", "value": 321,
        "observed_at": observed, "tags": {"dpid": dpid, "port_no": 1, "run_id": run_id,
            "sequence": 0, "synthetic": False, "quality": "measured",
            "execution_mode": "emulation", "freshness": "fresh"}}
    if fault == "value":
        sample["value"] = 0
    elif fault == "time":
        sample["observed_at"] = "2020-01-01T00:00:00+00:00"
    elif fault == "device":
        sample["device_id"] = str(uuid.uuid4())
    elif fault == "synthetic":
        sample["tags"]["synthetic"] = True
    binding = SimpleNamespace(switches={dpid: device_id}, hosts={})
    if fault is None:
        verify_measurements(snapshot, None, binding, [sample])
    else:
        with pytest.raises(ValueError):
            verify_measurements(snapshot, None, binding, [sample])
async def test_batch_backpressure_waits_for_both_lag_and_pending(monkeypatch):
    from unittest.mock import AsyncMock
    from scripts.verify_emulation import drain_owned_batch

    redis = AsyncMock()
    redis.xinfo_groups.side_effect = [
        [{"name": "owned", "lag": 10, "pending": 0}],
        [{"name": "owned", "lag": 0, "pending": 3}],
        [{"name": "other", "lag": 0, "pending": 0}, {"name": "owned", "lag": 0, "pending": 0}],
    ]
    monkeypatch.setattr("scripts.verify_emulation.asyncio.sleep", AsyncMock())
    await drain_owned_batch(redis, "owned", [])
    assert redis.xinfo_groups.await_count == 3


async def test_batch_backpressure_does_not_hide_stalled_or_failed_consumer(monkeypatch):
    from unittest.mock import AsyncMock
    import pytest
    from scripts.verify_emulation import drain_owned_batch

    redis = AsyncMock()
    redis.xinfo_groups.return_value = [{"name": "owned", "lag": 1, "pending": 0}]
    monkeypatch.setattr("scripts.verify_emulation.asyncio.sleep", AsyncMock())
    with pytest.raises(ValueError, match="40 seconds"):
        await drain_owned_batch(redis, "owned", [])
    assert redis.xinfo_groups.await_count == 200
    with pytest.raises(ValueError, match="consumer failed"):
        await drain_owned_batch(redis, "owned", ["TypeError"])
