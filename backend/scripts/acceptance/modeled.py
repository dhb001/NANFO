"""Generated configured-fluid fixtures, not network-fidelity or live-policy tests."""

import math

from app.modules.simulation.evaluator import (
    MODEL_VERSION,
    advance,
    canonical_config,
    initial_checkpoint,
    output,
)
from app.modules.simulation.schemas import ScenarioConfig

from scripts.acceptance.common import Blocked, encoded, sha


def fixtures():
    cases = {}
    for name, demand, length in (
        ("low", [0.2], 1), ("ramp", [index / 10 for index in range(40)], 1),
        ("burst", [0.2] * 10 + [8.0] * 10 + [0.2] * 20, 1),
        ("overload", [8.0], 1), ("multibottleneck", [8.0], 3),
        ("classes", [2.0], 2), ("larger_topology", [2.0], 32),
    ):
        links = [{"link_id": f"l{i}", "source": f"n{i}", "target": f"n{i + 1}",
                  "capacity_mbps": 1.0 if i % 2 == 0 else 0.5,
                  "buffer_bytes": 25000.0, "delay_ms": 0.0, "initial_queue_bytes": 0.0}
                 for i in range(length)]
        flows = [{"flow_id": "foreground", "source": "n0", "target": f"n{length}",
                  "path": [link["link_id"] for link in links], "demand_mbps": demand}]
        if name == "classes":
            flows.append({**flows[0], "flow_id": "background", "demand_mbps": [0.5]})
        cases[name] = ScenarioConfig.model_validate({
            "version": 1, "seed": 14, "tick_ms": 100, "duration_ticks": 40,
            "links": links, "flows": flows, "action_binding": None,
            "limits": {"max_loss_pct": 100.0, "max_latency_ms": 10000.0, "min_throughput_mbps": 0.0},
        })
    return cases


def run_models():
    results = {}
    for name, config in fixtures().items():
        checkpoint = initial_checkpoint(config)
        while checkpoint["state"]["tick"] < config.duration_ticks:
            checkpoint = advance(config, checkpoint, ticks=8)
            for flow in checkpoint["state"]["flows"].values():
                accounted = sum(flow[key] for key in (
                    "delivered_bytes", "dropped_bytes", "queued_bytes", "inflight_bytes"))
                if not math.isclose(flow["offered_bytes"], accounted, rel_tol=1e-9, abs_tol=1e-5):
                    raise Blocked("independent_mass_conservation_failed")
        fixture = canonical_config(config)
        results[name] = {"version": MODEL_VERSION, "input_fixture": fixture,
                         "input_fixture_sha256": sha(encoded(fixture)), "result": output(config, checkpoint),
                         "mass_conservation_checked": True,
                         "scope": "Configured fluid arithmetic only; no packet/network fidelity, DSCP priority, RTT or live acceptance"}
    return results
