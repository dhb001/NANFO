"""Versioned integer-clock acquisition for existing HTB/netem causal instruments.

Retains v1 queue reconstruction with explicit physical-capacity/shaper separation.
No burst guarantee is inferred from the nominal rate readback.
No provisioning, lab creation, probes, clock rewriting or calibration. v2 is an
explicit new acquisition format; old artifacts keep their original identities.
"""

import copy
import json
import time
from fractions import Fraction

from emulation.autonomous_causal import TABLE, validate_capture, validate_instrument_tables


def capture_endpoint(network, config, *, clock=time):
    start_wall, start_mono = clock.time_ns(), clock.monotonic_ns()
    tables = {node: json.loads(network.command(node, ["nft", "-j", "list", "table", "netdev", TABLE]))
              for node in sorted({e["node"] for e in config["egresses"]})}
    validate_instrument_tables(tables, config)
    rows = []
    for e in config["egresses"]:
        wall, mono = clock.time_ns(), clock.monotonic_ns()
        qdiscs = json.loads(network.command(e["node"], ["tc", "-j", "-s", "qdisc", "show", "dev", e["interface"]]))
        classes = json.loads(network.command(e["node"], ["tc", "-j", "-s", "class", "show", "dev", e["interface"]]))
        leaves = [q for q in qdiscs if q.get("kind") == "netem" and q.get("handle") == e["leaf_handle"]]
        if len(leaves) != 1:
            raise ValueError("causal_leaf_queue_missing_or_ambiguous")
        leaf = leaves[0]
        counters = {v["counter"]["name"]: v["counter"]["bytes"] for v in tables[e["node"]]["nftables"] if "counter" in v}
        demands = {name: counters[e["egress_id"] + "_" + name]
                   for name in [d["demand_id"] for d in config["demands"]] + ["unknown"]}
        end_mono, end_wall = clock.monotonic_ns(), clock.time_ns()
        rows.append({"egress_id": e["egress_id"], "read_started": wall / 10**9, "read_finished": end_wall / 10**9,
            "read_started_wall_ns": wall, "read_finished_wall_ns": end_wall,
            "read_started_monotonic_ns": mono, "read_finished_monotonic_ns": end_mono,
            "queue_bytes": leaf["backlog"], "departures_bytes": leaf["bytes"], "drop_packets": leaf["drops"],
            "demand_arrivals_bytes": demands, "raw_qdiscs": qdiscs, "raw_classes": classes,
            "capacity_bytes_per_second": e["capacity_bytes_per_second"],
            "shaper_nominal_bytes_per_second": e.get("shaper_nominal_bytes_per_second") or e["capacity_bytes_per_second"]})
    end_mono, end_wall = clock.monotonic_ns(), clock.time_ns()
    return {"started_wall_ns": start_wall, "finished_wall_ns": end_wall,
            "started_monotonic_ns": start_mono, "finished_monotonic_ns": end_mono,
            "started_unix": start_wall / 10**9, "finished_unix": end_wall / 10**9,
            "started_monotonic": start_mono / 10**9, "finished_monotonic": end_mono / 10**9,
            "queues": rows, "raw_nftables": tables}


def validate_ns_capture(capture, config):
    if capture.get("version") != "nanfo.frr-causal-capture/v2":
        raise ValueError("native_causal_v2_required")
    tolerance = Fraction(config["clock_error_seconds"]) * 10**9
    span = Fraction(config["max_read_span_seconds"]) * 10**9
    for ep in (capture["before"], capture["after"]):
        for prefix, ns_prefix in (("started_unix", "started_wall_ns"), ("finished_unix", "finished_wall_ns"),
                                  ("started_monotonic", "started_monotonic_ns"), ("finished_monotonic", "finished_monotonic_ns")):
            ns = ep[ns_prefix]
            if type(ns) is not int or not 0 <= ns < 2**63 or ep[prefix] != ns / 10**9:
                raise ValueError("native_causal_clock_projection_mismatch")
        wall = ep["finished_wall_ns"] - ep["started_wall_ns"]
        mono = ep["finished_monotonic_ns"] - ep["started_monotonic_ns"]
        if not 0 <= mono <= span or wall < 0 or abs(wall - mono) > tolerance:
            raise ValueError("native_causal_clock_span_invalid")
        for row in ep["queues"]:
            for axis in ("wall", "monotonic"):
                start, end = row[f"read_started_{axis}_ns"], row[f"read_finished_{axis}_ns"]
                if (type(start) is not int or type(end) is not int
                        or not ep[f"started_{axis}_ns"] <= start <= end <= ep[f"finished_{axis}_ns"]):
                    raise ValueError("native_causal_read_clock_invalid")
            if (row["read_started"] != row["read_started_wall_ns"] / 10**9
                    or row["read_finished"] != row["read_finished_wall_ns"] / 10**9):
                raise ValueError("native_causal_read_projection_mismatch")
    a, b = capture["before"], capture["after"]
    dt = b["finished_wall_ns"] - a["finished_wall_ns"]
    mono = b["finished_monotonic_ns"] - a["finished_monotonic_ns"]
    if (mono <= 0 or abs(dt - mono) > tolerance
            or b["started_monotonic_ns"] < a["finished_monotonic_ns"]):
        raise ValueError("native_causal_window_clock_invalid")
    validate_native_counters(capture, config)


def validate_native_counters(capture, config):
    """Reuse v1 counter replay with an explicit *validation-only* shaper view.

    Raw classes/rates/capacity are never rewritten. v1 calls its HTB-rate field
    capacity. In this detached local adapter ONLY, that field carries HTB nominal
    rate to reuse the tree check. Actual physical capacity stays in the v2 capture
    and safety observation, and is separately bound to the reviewed config.
    """
    projected, legacy_config = copy.deepcopy(capture), copy.deepcopy(config)
    for e in legacy_config["egresses"]:
        nominal = e.get("shaper_nominal_bytes_per_second") or e["capacity_bytes_per_second"]
        for endpoint in (projected["before"], projected["after"]):
            rows = [q for q in endpoint["queues"] if q["egress_id"] == e["egress_id"]]
            if (len(rows) != 1 or rows[0]["capacity_bytes_per_second"] != e["capacity_bytes_per_second"]
                    or rows[0].get("shaper_nominal_bytes_per_second") != nominal):
                raise ValueError("native_causal_physical_or_shaper_mismatch")
            rows[0]["capacity_bytes_per_second"] = nominal
        e["capacity_bytes_per_second"] = nominal
    validate_capture(projected, legacy_config)


def acquire_window(network, config, *, clock=time, sleep=time.sleep):
    pairs = (("h1", "h3"), ("h3", "h1"), ("h2", "h4"), ("h4", "h2"))
    paths = {f"{s}->{d}": network.routePath(s, d) for s, d in pairs}
    before = capture_endpoint(network, config, clock=clock)
    sleep(config["window_seconds"])
    after = capture_endpoint(network, config, clock=clock)
    result = {"version": "nanfo.frr-causal-capture/v2", "before": before, "after": after,
              "paths_before": paths, "paths_after": {f"{s}->{d}": network.routePath(s, d) for s, d in pairs},
              "failures": [], "measurement_complete": False, "guaranteed_bounds": False}
    try:
        validate_ns_capture(result, config)
        result["measurement_complete"] = True
    except ValueError as exc:
        result["failures"] = [str(exc)]
    return result
