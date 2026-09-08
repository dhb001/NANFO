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
