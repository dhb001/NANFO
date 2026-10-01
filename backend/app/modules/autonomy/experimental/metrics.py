"""The ONE measured-metrics reconstruction for ADR025 raw frozen frames (ADR-028).

Import path for every consumer (verification, simulation, campaign evidence, audits):
``from app.modules.autonomy.experimental.metrics import measured_metrics``. The metric
formulas themselves are ``flow_service_metrics`` / ``probe_service_metrics`` (defined in the
dependency-free ``formulas`` module, re-exported here); ``measured_metrics`` adds the strict
raw-frame validation around them and campaign evidence calls the same functions.
"""

from __future__ import annotations

import math

from app.modules.autonomy.experimental.constants import DATAGRAM_BYTES
from app.modules.autonomy.experimental.formulas import flow_service_metrics, probe_service_metrics
from app.modules.autonomy.experimental.simulation import FrozenMeasuredFrame, number
from app.modules.simulation.evaluator import digest

__all__ = ["flow_service_metrics", "measured_metrics", "probe_service_metrics"]


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError("raw_count_missing_or_invalid")
    return value


def measured_metrics(frame):
    """Reconstruct frozen v4 service semantics; never use observation summaries.

    Goodput uses actual sender lifetime (control included), receiver totals include
    verified drain. RTT is real ICMP RTT, not evaluator residence latency.
    """
    frame = FrozenMeasuredFrame.model_validate(frame)
    evidence = frame.raw["evidence"]
    if evidence.get("measurement_complete") is not True or evidence.get("drain_status") != "verified_empty":
        raise ValueError("measurement_or_drain_incomplete")
    start, end = (number(evidence["post_control_interval"][key]) for key in ("start", "end"))
    control = number(evidence["control_start_monotonic_seconds"])
    drain_start, drain_end = (number(evidence[key]) for key in ("drain_begin", "drain_end"))
    desired = number(evidence["desired_window_seconds"], positive=True)
    measured = number(evidence["measured_window_seconds"], positive=True)
    if not control <= start < end <= drain_start < drain_end:
        raise ValueError("measurement_chronology_invalid")
    if not 2 <= desired <= 10 or not desired <= measured <= desired + 2 or not math.isclose(measured, end - start, abs_tol=.01):
        raise ValueError("measurement_interval_invalid")
    drain_limit = number(evidence["environment_spec"]["drain_max_seconds"], positive=True)
    if drain_end - drain_start > drain_limit:
        raise ValueError("measurement_drain_exceeded_frozen_spec")
    if not math.isclose((frame.observed_at - frame.window_started_at).total_seconds(), end - start, abs_tol=.01):
        raise ValueError("measurement_clock_attachment_mismatch")
    senders, receivers = evidence["udp_sent"], evidence["udp_received"]
    if len(senders) != 2 or len(receivers) != 2:
        raise ValueError("both_raw_flows_required")
    metrics = []
    for sender, receiver in zip(senders, receivers):
        sent, received = _count(sender["packets"]), _count(receiver["packets"])
        sent_bytes, received_bytes = _count(sender["bytes"]), _count(receiver["bytes"])
        duration = number(sender["duration_seconds"], positive=True)
        for worker in (sender, receiver):
            began, ended = (number(worker[key]) for key in ("started_monotonic_seconds", "finished_monotonic_seconds"))
            if (not began <= control <= start < end <= ended
                    or not math.isclose(ended - began, number(worker["duration_seconds"], positive=True), abs_tol=.01)):
                raise ValueError("worker_interval_invalid")
        if (sender["finished_monotonic_seconds"] > drain_start
                or receiver["finished_monotonic_seconds"] < drain_end
                or received > sent or received_bytes > sent_bytes
                or sent_bytes != sent * DATAGRAM_BYTES or received_bytes != received * DATAGRAM_BYTES):
            raise ValueError("raw_counter_or_drain_mismatch")
        highest = receiver["highest_sequence"]
        if (type(highest) is not int or (received == 0) != (highest == -1)
                or highest < received - 1 or sent > 0 and highest >= sent):
            raise ValueError("raw_sequence_count_mismatch")
        metrics.append(flow_service_metrics(sent, received, received_bytes, duration))
    probe = evidence["ping"]
    sent, received = _count(probe["sent"]), _count(probe["received"])
    rtt = probe["rtt_avg_ms"]
    if received > sent or number(probe["interval_seconds"]) < end - start:
        raise ValueError("raw_probe_interval_or_count_invalid")
    if (received == 0) != (rtt is None):
        raise ValueError("raw_probe_rtt_inconsistent")
    icmp = probe_service_metrics(sent, received, number(rtt) if rtt is not None else None)
    return {"goodput_mbps": metrics[0]["goodput_mbps"], "udp_loss_pct": metrics[0]["udp_loss_pct"],
            "probe_loss_pct": icmp["probe_loss_pct"], "rtt_ms": icmp["rtt_ms"],
            "probe_sent": icmp["probe_sent"], "probe_received": icmp["probe_received"],
            "traffic_bytes": senders[0]["bytes"],
            "service_outage": icmp["service_outage"],
            "service_window_seconds": end - start,
            "sender_lifetime_seconds": senders[0]["duration_seconds"],
            "raw_evidence_sha256": digest(evidence)}
