"""ADR-028 task 13: campaign evidence and experimental measured_metrics share one semantics."""

import copy
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.modules.autonomy.campaign_evidence import UDPWorker, service_metrics
from app.modules.autonomy.experimental.metrics import measured_metrics
from app.modules.simulation.evaluator import digest

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
IDENTITY = UUID("00000000-0000-0000-0000-000000000002")


def worker(packets, start, end):
    return {"packets": packets, "bytes": packets * 1200, "highest_sequence": packets - 1,
            "duration_seconds": end - start, "started_monotonic_seconds": start,
            "finished_monotonic_seconds": end}


def frame(received=1900, probes_received=18):
    raw = {"episode_id": str(IDENTITY), "seed": 7, "scenario": "path0", "mode": "matched",
           "terminated": False, "truncated": False, "step_index": 1,
           "observation": {"previous_action": 1},
           "evidence": {"measurement_complete": True, "error": None,
                        "udp_sent": [worker(2000, 9, 13), worker(400, 9, 13)],
                        "udp_received": [worker(received, 8, 14), worker(400, 8, 14)],
                        "post_control_interval": {"start": 10, "end": 12},
                        "control_start_monotonic_seconds": 9.5, "drain_begin": 13, "drain_end": 13.5,
                        "drain_status": "verified_empty", "desired_window_seconds": 2,
                        "measured_window_seconds": 2,
                        "ping": {"sent": 20, "received": probes_received,
                                 "rtt_avg_ms": 12.5 if probes_received else None, "interval_seconds": 4},
                        "environment_spec": {"version": 5, "drain_max_seconds": 3}}}
    return {"network_id": IDENTITY, "workspace_id": IDENTITY, "runtime_sha256": "d" * 64,
            "window_started_at": NOW - timedelta(seconds=3), "observed_at": NOW - timedelta(seconds=1),
            "raw_sha256": digest(raw), "raw": raw}


@pytest.mark.parametrize("received,probes", [(2000, 20), (1900, 18), (1, 0)])
def test_campaign_service_metrics_equal_the_single_measured_metrics(received, probes):
    value = frame(received, probes)
    evidence = copy.deepcopy(value["raw"]["evidence"])
    measured = measured_metrics(value)
    local = service_metrics([UDPWorker.model_validate(row) for row in evidence["udp_sent"]],
                            [UDPWorker.model_validate(row) for row in evidence["udp_received"]],
                            evidence["ping"])
    assert local["goodput_mbps"] == measured["goodput_mbps"]
    assert local["loss_fraction"] * 100 == pytest.approx(measured["udp_loss_pct"], abs=1e-12)
    assert local["icmp_rtt_ms"] == measured["rtt_ms"]


def test_one_formula_implementation_is_shared_by_both_consumers():
    """ADR-028: campaign evidence calls the same formula functions measured_metrics is built from."""
    import inspect

    from app.modules.autonomy import campaign_evidence
    from app.modules.autonomy.experimental import formulas, metrics

    assert metrics.flow_service_metrics is formulas.flow_service_metrics
    assert metrics.probe_service_metrics is formulas.probe_service_metrics
    assert {"flow_service_metrics", "probe_service_metrics", "measured_metrics"} <= set(metrics.__all__)
    for source in (inspect.getsource(campaign_evidence.service_metrics), inspect.getsource(metrics.measured_metrics)):
        assert "* 8 /" not in source and "1 - received" not in source and "100 * (sent" not in source
    value = frame()
    evidence = value["raw"]["evidence"]
    sender, receiver = evidence["udp_sent"][0], evidence["udp_received"][0]
    flow = formulas.flow_service_metrics(sender["packets"], receiver["packets"], receiver["bytes"],
                                         float(sender["duration_seconds"]))
    icmp = formulas.probe_service_metrics(20, 18, 12.5)
    local = service_metrics([UDPWorker.model_validate(row) for row in evidence["udp_sent"]],
                            [UDPWorker.model_validate(row) for row in evidence["udp_received"]], evidence["ping"])
    assert local == {"goodput_mbps": flow["goodput_mbps"], "loss_fraction": flow["loss_fraction"],
                     "icmp_rtt_ms": icmp["rtt_ms"]}
    measured = measured_metrics(value)
    assert (measured["goodput_mbps"], measured["udp_loss_pct"]) == (flow["goodput_mbps"], flow["udp_loss_pct"])
    assert (measured["probe_loss_pct"], measured["rtt_ms"], measured["service_outage"]) == (
        icmp["probe_loss_pct"], icmp["rtt_ms"], icmp["service_outage"])


def test_measured_metrics_result_is_unchanged_by_the_extraction():
    """Same keys, same order and the historical expressions, bit for bit."""
    value = frame(1900, 18)
    evidence = value["raw"]["evidence"]
    measured = measured_metrics(value)
    assert list(measured) == ["goodput_mbps", "udp_loss_pct", "probe_loss_pct", "rtt_ms", "probe_sent",
                              "probe_received", "traffic_bytes", "service_outage", "service_window_seconds",
                              "sender_lifetime_seconds", "raw_evidence_sha256"]
    sender, receiver, ping = evidence["udp_sent"][0], evidence["udp_received"][0], evidence["ping"]
    assert measured["goodput_mbps"] == receiver["bytes"] * 8 / float(sender["duration_seconds"]) / 1e6
    assert measured["udp_loss_pct"] == 100 * (sender["packets"] - receiver["packets"]) / sender["packets"]
    assert measured["probe_loss_pct"] == 100 * (ping["sent"] - ping["received"]) / ping["sent"]
    assert measured["rtt_ms"] == 12.5 and measured["service_outage"] is False
    outage = measured_metrics(frame(1900, 0))
    assert outage["rtt_ms"] is None and outage["service_outage"] is True and outage["probe_loss_pct"] == 100


@pytest.mark.parametrize("change", ["ospf", "pre_drain"])
def test_campaign_keeps_accepting_records_measured_metrics_rejects(change):
    value = frame()
    raw = value["raw"]
    if change == "ospf":
        raw["mode"] = "ospf"
    else:
        raw["evidence"]["drain_status"] = "not_measured"
        for key in ("drain_begin", "drain_end"):
            raw["evidence"].pop(key)
    value["raw_sha256"] = digest(raw)
    with pytest.raises(ValueError):
        measured_metrics(value)
    evidence = raw["evidence"]
    local = service_metrics([UDPWorker.model_validate(row) for row in evidence["udp_sent"]],
                            [UDPWorker.model_validate(row) for row in evidence["udp_received"]], evidence["ping"])
    assert local["goodput_mbps"] == 1900 * 1200 * 8 / 4.0 / 1e6
    assert local["loss_fraction"] == 1 - 1900 / 2000 and local["icmp_rtt_ms"] == 12.5
    # The caller validates probe counts after this call; a missing or malformed `sent` must
    # therefore neither raise here nor change the service values (unchanged error order).
    for ping in ({key: value for key, value in evidence["ping"].items() if key != "sent"},
                 {**evidence["ping"], "sent": "20"}):
        assert service_metrics([UDPWorker.model_validate(row) for row in evidence["udp_sent"]],
                               [UDPWorker.model_validate(row) for row in evidence["udp_received"]], ping) == local


def test_formal_imports_never_load_experimental_code_and_calls_load_only_the_pure_formulas():
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    code = """
import json, sys
import app.modules.autonomy.campaign_evidence as campaign
import app.modules.autonomy.qualification  # noqa: F401
before = sorted(k for k in sys.modules if k.startswith(("app.modules.autonomy.experimental", "emulation")))
worker = campaign.UDPWorker.model_validate
row = {"packets": 10, "bytes": 12000, "highest_sequence": 9, "duration_seconds": 2.0,
       "started_monotonic_seconds": 1.0, "finished_monotonic_seconds": 3.0}
campaign.service_metrics([worker(row)], [worker(row)], {"sent": 3, "received": 3, "rtt_avg_ms": 1.0})
after = sorted(k for k in sys.modules if k.startswith(("app.modules.autonomy.experimental", "emulation")))
print(json.dumps([before, after]))
"""
    env = {**os.environ, "PYTHONPATH": str(backend) + os.pathsep + str(backend.parent), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("NANFO_EXPERIMENTAL_LAB_ENABLED", None)
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True,
                            cwd=backend, env=env)
    before, after = json.loads(result.stdout)
    assert before == []
    assert after == ["app.modules.autonomy.experimental", "app.modules.autonomy.experimental.formulas"]
