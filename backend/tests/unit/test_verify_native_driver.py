"""Manual verifier graph/authority tests only; no lab setup or subprocesses."""

import json
import os
import time
from types import SimpleNamespace

import pytest

from scripts.verify_native_driver import Authority, Evidence, digest, shortest, write
from emulation.ospf import PATHS, linkPlan
from tests.autonomous_frr_support import FakeFRRNetwork
from tests.unit.test_autonomous_frr import driver, plan


def test_static_nominal_baseline_has_exact_original_foreground_paths():
    graph = linkPlan()
    assert shortest(graph, "h1", "h3") == ["h1", *PATHS[0], "h3"]
    assert shortest(graph, "h3", "h1") == ["h3", *reversed(PATHS[0]), "h1"]
    assert len([e for link in graph for e in link["endpoints"]]) == 22


@pytest.mark.parametrize("stop", range(13))
async def test_manual_verifier_checkpoint_denies_exact_prefix(tmp_path, stop):
    device = driver(FakeFRRNetwork())
    prepared = await device.prepare(plan())
    network = device.network
    network.binding = SimpleNamespace(resource_id="unit", run_id="run")
    network.ownership = lambda *_: True
    protocol = {"authority_kind": "scoped-manual-driver-campaign"}
    write(tmp_path / "protocol.json", protocol)
    evidence = Evidence(tmp_path, "events.jsonl")
    authority = Authority(network, evidence, dict(protocol_path=str(tmp_path / "protocol.json"),
        protocol_digest=digest(protocol), expires_monotonic_ns=time.monotonic_ns() + 10**9), prepared,
        stop=stop, sealed=False)
    try:
        if stop < 12:
            with pytest.raises(ValueError, match="manual_STOP"):
                await device.apply(prepared, authority.checkpoint)
        else:
            await device.apply(prepared, authority.checkpoint)
        assert len(network.writes) == stop
        events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
        assert sum(e["kind"] == "mutation_ack" for e in events) == stop
    finally:
        authority.close()
        evidence.stream.close()


@pytest.mark.skipif(not os.environ.get("NANFO_NATIVE_DRIVER_EVIDENCE"), reason="explicit retained native evidence required")
def test_retained_actual_campaign_readonly_reconstruction():
    from scripts.audit_native_driver import audit
    result = audit(os.environ["NANFO_NATIVE_DRIVER_EVIDENCE"])
    assert result["status"] == "passed" and result["total_cases"] == 42
    assert result["native_policy_mutations"] == 480
    assert result["sealed_endpoint_readbacks"] >= 10000
    assert [r["probe"]["received"] for r in result["actual_probes"]] == [6, 6]
    assert not result["autonomy_qualified"] and not result["calibration_installed"]
