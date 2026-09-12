"""Independent ADR014 queue-drain evidence checks, never inferred packet delivery."""

import math

INTERFACES = {
    *[
        f"{node}-eth{port}"
        for node in ("dist1", "dist2", "access1", "access2")
        for port in range(1, 5)
    ],
    "core-eth1",
    "core-eth2",
    *[f"h{i}-eth0" for i in range(1, 5)],
}

SEMANTICS = {
    "version": 4,
    "drain_version": "post-sender-termination-verified-leaf-queues-v4",
    "drain_max_seconds": 3.0,
    "drain_poll_interval_seconds": 0.08,
    "drain_empty_observations": 2,
    "drain_queue_scope": (
        "all topology link endpoints, both directions, including hosts and alternate paths; "
        "single leaf netem per interface"
    ),
    "drain_completion": (
        "all senders exited; receivers alive; two consecutive complete zero-byte/zero-packet "
        "queue sweeps separated by at least drain_poll_interval_seconds; completed within "
        "drain_max_seconds"
    ),
    "drain_timeout": (
        "truncate with measurement_complete=false; retain final endpoint totals and partial "
        "queue evidence; no valid loss/goodput outcome"
    ),
    "late_received_packets": (
        "unavailable (null per flow); workers publish final totals only, no drain-begin "
        "streaming counter; never inferred from queue backlog"
    ),
    "goodput_denominator": (
        "actual foreground sender duration; delivered numerator includes service during "
        "control and verified drain"
    ),
    "latency_measurement": "foreground ICMP RTT during load; not UDP RTT",
}


def validateDrain(evidence):
    from .evidence import number, same

    e = evidence
    begin, end = number(e["drain_begin"]), number(e["drain_end"])
    sent, received = e["udp_sent"], e["udp_received"]
    stopped = number(e["senders_stopped_monotonic_seconds"])
    if (
        e["drain_status"] != "verified_empty"
        or e["drain_error"] is not None
        or not max(number(s["finished_monotonic_seconds"]) for s in sent) <= stopped <= begin < end
        or end > min(number(r["finished_monotonic_seconds"]) for r in received)
        or end - begin > 3.0
        or set(e["drain_queue_interfaces"]) != INTERFACES
        or len(e["drain_queue_interfaces"]) != len(INTERFACES)
        or type(e["drain_sweeps"]) is not int
        or not 2 <= e["drain_sweeps"] <= 100
        or e["late_received_packets"] != [None, None]
        or e["late_received_unavailable_reason"]
        != "workers publish final totals only; no drain-begin counter"
    ):
        raise ValueError("invalid verified-drain interval/coverage/endpoint evidence")
    same(e["drain_duration_seconds"], end - begin)
    sweeps = e["drain_empty_observations"]
    if len(sweeps) != 2 or e["queue_end"] != sweeps[-1]["queues"]:
        raise ValueError("two final empty drain observations required")
    last = None
    rows = [(e["queue_begin"], begin, end, False)]
    for sweep in sweeps:
        a, b = number(sweep["start"]), number(sweep["end"])
        if not begin <= a <= b <= end or (last is not None and a - last < 0.08 - 1e-8):
            raise ValueError("invalid drain sweep chronology")
        rows.append((sweep["queues"], a, b, True))
        last = b
    for queues, a, b, empty in rows:
        if set(queues) != INTERFACES:
            raise ValueError("drain must cover all actual topology endpoints")
        for row in queues.values():
            if not a <= number(row["monotonic_seconds"]) <= b:
                raise ValueError("queue timestamp outside drain sweep")
            raw = row["raw_leaf_qdiscs"]
            leaves = [
                q
                for q in raw
                if q.get("kind") == "netem"
                and not any(
                    child.get("parent", "").split(":")[0] == q.get("handle", "").split(":")[0]
                    for child in raw
                    if child is not q
                )
            ]
            if len(leaves) != 1:
                raise ValueError("missing actual drain leaf netem")
            for key, rawKey in (("backlog_bytes", "backlog"), ("backlog_packets", "qlen")):
                value = number(row[key])
                if not math.isfinite(value) or value != int(value) or (empty and value != 0):
                    raise ValueError("drain final queues are not empty")
                same(leaves[0][rawKey], value)
