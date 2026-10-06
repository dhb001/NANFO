"""ADR-028 task 13: one experimental constants module and one measured_metrics()."""

import re
from pathlib import Path

from app.modules.autonomy.experimental import constants, metrics, simulation, verification
from app.modules.autonomy.experimental.adapter import ExperimentalLabAdapter
from emulation import lab_contracts

PACKAGE = Path(constants.__file__).parent


def test_constants_come_from_the_versioned_lab_contract():
    assert constants.ROUTE_PATHS == {"route0": ("access1", "dist1", "access2"),
                                     "route1": ("access1", "dist2", "access2")}
    assert constants.DATAGRAM_BYTES == lab_contracts.UDP_DATAGRAM_BYTES == 1200
    assert constants.FOREGROUND_KEYS == ("h1->h3", "h3->h1")
    assert ExperimentalLabAdapter.receiver_contract_hash == constants.CONTRACT_HASH
    assert constants.validate_route_readback is lab_contracts.validate_route_readback


def test_no_experimental_module_redefines_lab_constants():
    for path in PACKAGE.glob("*.py"):
        if path.name == "constants.py":
            continue
        source = path.read_text()
        assert constants.CONTRACT_HASH not in source, path
        assert not re.search(r"\*\s*1200\b|\b1200\s*\*", source), path
        assert '("access1", "dist1", "access2")' not in source, path
        assert '"route0", "route1"' not in source, path


def test_single_measured_metrics_implementation_is_shared():
    assert verification.measured_metrics is metrics.measured_metrics
    definitions = [path.name for path in PACKAGE.glob("*.py") if "def measured_metrics(" in path.read_text()]
    assert definitions == ["metrics.py"]
    assert "from .metrics import measured_metrics" in Path(simulation.__file__).read_text()


async def test_adapter_verification_requires_exact_route_nodes_not_labels_only():
    import time
    from types import SimpleNamespace
    from uuid import uuid4

    from tests.experimental_lab_support import case

    c = case()
    adapter = ExperimentalLabAdapter.__new__(ExperimentalLabAdapter)
    adapter.policy, adapter.current_authority = c.policy, None
    wanted = 1
    exact = {key: {"action": wanted, "nodes": lab_contracts.expected_nodes(wanted, *key.split("->"))}
             for key in constants.FOREGROUND_KEYS}
    labels_only = {key: {**row, "nodes": list(reversed(row["nodes"]))} for key, row in exact.items()}
    now = time.monotonic()

    def evidence(paths):
        return {"frame": {"response": {"data": {
            "observation": {"previous_action": wanted, "goodput_mbps": 5.0, "loss_fraction": 0.0,
                            "latency_ms": 3.0},
            "evidence": {"post_control_interval": {"start": now - 3, "end": now - 1},
                         "ping": {"sent": 4, "received": 4}, "udp_received": [{"bytes": 2400}]}}}},
            "clock_wall": time.time(), "clock_monotonic": now, "readback": {"paths": paths}}

    class Action:
        command = SimpleNamespace(route=SimpleNamespace(action_id="route1"), request_id=uuid4())

        def model_dump(self, mode="json"):
            return {"action": "route1"}

    for paths, verified in ((exact, True), (labels_only, False)):
        async def guarded(operation, checkpoint, paths=paths):
            return evidence(paths)

        adapter._guarded = guarded
        record = await adapter.verify(Action())
        assert record.route_verified is verified
        assert record.action_id == ("route1" if verified else None)
