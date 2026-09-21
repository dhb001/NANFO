"""Native read-only causal acquisition, independent of frozen model observations.

Uses explicitly provisioned nft netdev-egress counters BEFORE qdisc and leaf netem
byte backlog/departure counters. Drops lacking byte counters are a blocker, never
silently converted from packet counts. Counter hook semantics require independent
kernel/instrument review in the runtime binding. This module does not fit bounds.
"""

import json
import time

TABLE = "nanfo_autonomous_causal"


def provision_rules(config):
    """Return per-node nft JSON transactions for explicit operator installation.

    No flush/delete, no changing qdisc; existing table collisions fail atomically.
    Every classifier has a counter then return; unmatched bytes get their own
    counter. The caller must attest that protocol/address selectors partition all
    demands and that each counter observes the queue's exact input bytes.
    """
    output = {}
    for egress in config["egresses"]:
        node, interface, key = egress["node"], egress["interface"], egress["egress_id"]
        if node not in output:
            output[node] = [{"add": {"table": {"family": "netdev", "name": TABLE}}}]
        commands = output[node]
        commands.append({"add": {"chain": {"family": "netdev", "table": TABLE, "name": key,
            "type": "filter", "hook": "egress", "dev": interface, "prio": -500, "policy": "accept"}}})
        for demand in config["demands"]:
            name = key + "_" + demand["demand_id"]
            commands.append({"add": {"counter": {"family": "netdev", "table": TABLE, "name": name}}})
            expressions = [{"match": {"op": "==", "left": {"meta": {"key": "protocol"}}, "right": "ip"}}]
            for field, value in (("saddr", demand["source_ipv4"]), ("daddr", demand["destination_ipv4"]),
                                 ("protocol", demand["ip_protocol"])):
                expressions.append({"match": {"op": "==", "left": {"payload": {"protocol": "ip", "field": field}}, "right": value}})
            expressions.extend([{"counter": name}, {"return": None}])
            commands.append({"add": {"rule": {"family": "netdev", "table": TABLE, "chain": key, "expr": expressions}}})
        name = key + "_unknown"
        commands.extend([{"add": {"counter": {"family": "netdev", "table": TABLE, "name": name}}},
            {"add": {"rule": {"family": "netdev", "table": TABLE, "chain": key, "expr": [{"counter": name}]}}}])
    return {node: {"nftables": commands} for node, commands in output.items()}


def capture_endpoint(network, config):
    """Read every required native counter and queue; preserve real read spans."""
    started, monotonic = time.time(), time.monotonic()
    tables = {node: json.loads(network.command(node, ["nft", "-j", "list", "table", "netdev", TABLE]))
              for node in sorted({e["node"] for e in config["egresses"]})}
    validate_instrument_tables(tables, config)
    rows = []
    for egress in config["egresses"]:
        before = time.time()
        raw = json.loads(network.command(egress["node"], ["tc", "-j", "-s", "qdisc", "show", "dev", egress["interface"]]))
        leaves = [q for q in raw if q.get("kind") == "netem" and q.get("handle") == egress["leaf_handle"]]
        if len(leaves) != 1:
            raise ValueError("causal_leaf_queue_missing_or_ambiguous")
        q = leaves[0]
        classes = json.loads(network.command(egress["node"], ["tc", "-j", "-s", "class", "show", "dev", egress["interface"]]))
        shaped = [c for c in classes if c.get("kind") == "htb" and c.get("handle") == q.get("parent")]
        if (len(shaped) != 1 or shaped[0].get("options", {}).get("rate") != egress["capacity_bytes_per_second"]):
            raise ValueError("causal_capacity_readback_mismatch")
        counters = {v["counter"]["name"]: v["counter"] for v in tables[egress["node"]]["nftables"] if "counter" in v}
        names = [d["demand_id"] for d in config["demands"]] + ["unknown"]
        demands = {}
        for name in names:
            value = counters.get(egress["egress_id"] + "_" + name)
            if value is None or type(value.get("bytes")) is not int or value["bytes"] < 0:
                raise ValueError("causal_prequeue_counter_missing")
            demands[name] = value["bytes"]
        if any(type(q.get(k)) is not int or q[k] < 0 for k in ("backlog", "bytes", "drops")):
            raise ValueError("causal_queue_byte_counters_missing")
        rows.append({"egress_id": egress["egress_id"], "read_started": before, "read_finished": time.time(),
            "queue_bytes": q["backlog"], "departures_bytes": q["bytes"], "drop_packets": q["drops"],
            "demand_arrivals_bytes": demands, "raw_qdiscs": raw, "raw_classes": classes,
            "capacity_bytes_per_second": shaped[0]["options"]["rate"]})
    return {"started_unix": started, "finished_unix": time.time(), "started_monotonic": monotonic,
            "finished_monotonic": time.monotonic(), "queues": rows, "raw_nftables": tables}


def failures_for(before, after, config):
    failures = []
    dt = after["finished_unix"] - before["finished_unix"]
    mono = after["finished_monotonic"] - before["finished_monotonic"]
    if dt <= 0 or abs(dt - mono) > config["clock_error_seconds"]:
        failures.append("causal_clock_discontinuity")
    if dt > config["window_seconds"] + config["max_read_span_seconds"] + config["clock_error_seconds"]:
        failures.append("causal_window_overrun")
    for endpoint in (before, after):
        if endpoint["finished_unix"] - endpoint["started_unix"] > config["max_read_span_seconds"]:
            failures.append("causal_read_skew_exceeded")
    for old, new in zip(before["queues"], after["queues"]):
        deltas = {k: new["demand_arrivals_bytes"][k] - old["demand_arrivals_bytes"][k] for k in old["demand_arrivals_bytes"]}
        departure = new["departures_bytes"] - old["departures_bytes"]
        if min([departure, *deltas.values()]) < 0 or new["drop_packets"] < old["drop_packets"]:
            failures.append("causal_counter_reset")
        if new["drop_packets"] != old["drop_packets"]:
            failures.append("causal_drop_bytes_unavailable")
        if deltas["unknown"]:
            failures.append("causal_unknown_demand")
        error = next(e["measurement_error_bytes"] for e in config["egresses"] if e["egress_id"] == old["egress_id"])
        if abs(new["queue_bytes"] - (old["queue_bytes"] + sum(deltas.values()) - departure)) > error:
            failures.append("causal_conservation_failed")
    return sorted(set(failures))


def validate_instrument_tables(tables, config):
    expected = provision_rules(config)
    if set(tables) != set(expected):
        raise ValueError("causal_instrument_node_scope_mismatch")
    def normalized(rows):
        result = []
        for entry in rows:
            if "metainfo" in entry:
                continue
            if len(entry) != 1:
                raise ValueError("invalid_nft_instrument")
            kind, value = next(iter(entry.items()))
            value = dict(value)
            value.pop("handle", None)
            if kind == "counter":
                value.pop("packets", None)
                value.pop("bytes", None)
            result.append({kind: value})
        return result
    for node in tables:
        wanted = normalized([row["add"] for row in expected[node]["nftables"]])
        actual = normalized(tables[node]["nftables"])
        # nft lists objects grouped by kind, but rule ordering in each chain matters.
        def grouped(items):
            return {kind: [row[kind] for row in items if kind in row] for kind in ("table", "counter", "chain", "rule")}
        if grouped(wanted) != grouped(actual):
            raise ValueError("causal_instrument_rules_changed")


def validate_capture(capture, config):
    """Reconstruct normalized rows from retained native counters; distrust flags."""
    expected_paths = {"h1->h3", "h3->h1", "h2->h4", "h4->h2"}
    if (set(capture.get("paths_before", {})) != expected_paths or set(capture.get("paths_after", {})) != expected_paths
            or any(capture["paths_before"][key]["nodes"] != capture["paths_after"][key]["nodes"] for key in expected_paths)):
        raise ValueError("causal_route_window_unstable")
    for endpoint in (capture["before"], capture["after"]):
        validate_instrument_tables(endpoint["raw_nftables"], config)
        if [q["egress_id"] for q in endpoint["queues"]] != [e["egress_id"] for e in config["egresses"]]:
            raise ValueError("causal_egress_scope_mismatch")
        for egress, row in zip(config["egresses"], endpoint["queues"]):
            leaves = [q for q in row["raw_qdiscs"] if q.get("kind") == "netem" and q.get("handle") == egress["leaf_handle"]]
            if len(leaves) != 1:
                raise ValueError("causal_native_leaf_missing")
            leaf = leaves[0]
            classes = [c for c in row["raw_classes"] if c.get("kind") == "htb" and c.get("handle") == leaf.get("parent")]
            if (len(classes) != 1 or classes[0].get("options", {}).get("rate") != egress["capacity_bytes_per_second"]
                    or row["capacity_bytes_per_second"] != egress["capacity_bytes_per_second"]):
                raise ValueError("causal_capacity_readback_mismatch")
            counters = {v["counter"]["name"]: v["counter"]["bytes"]
                        for v in endpoint["raw_nftables"][egress["node"]]["nftables"] if "counter" in v}
            expected = {d: counters[egress["egress_id"] + "_" + d]
                        for d in [d["demand_id"] for d in config["demands"]] + ["unknown"]}
            values = [*expected.values(), leaf.get("backlog"), leaf.get("bytes"), leaf.get("drops")]
            if (any(type(v) is not int or v < 0 for v in values)
                    or row["demand_arrivals_bytes"] != expected
                    or row["queue_bytes"] != leaf["backlog"] or row["departures_bytes"] != leaf["bytes"]
                    or row["drop_packets"] != leaf["drops"]
                    or not endpoint["started_unix"] <= row["read_started"] <= row["read_finished"] <= endpoint["finished_unix"]):
                raise ValueError("causal_native_normalized_mismatch")
    failures = failures_for(capture["before"], capture["after"], config)
    if failures:
        raise ValueError("causal_capture_rejected:" + ",".join(failures))


def acquire_window(network, config, *, sleep=time.sleep):
    pairs = (("h1", "h3"), ("h3", "h1"), ("h2", "h4"), ("h4", "h2"))
    paths_before = {f"{s}->{d}": network.routePath(s, d) for s, d in pairs}
    before = capture_endpoint(network, config)
    sleep(config["window_seconds"])
    after = capture_endpoint(network, config)
    paths_after = {f"{s}->{d}": network.routePath(s, d) for s, d in pairs}
    failures = failures_for(before, after, config)
    if any(paths_before[key]["nodes"] != paths_after[key]["nodes"] for key in paths_before):
        failures.append("causal_route_changed_during_window")
    return {"version": "nanfo.frr-causal-capture/v1", "before": before, "after": after,
            "paths_before": paths_before, "paths_after": paths_after,
            "failures": sorted(set(failures)), "measurement_complete": not failures,
            "guaranteed_bounds": False}
