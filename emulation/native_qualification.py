"""Native kernel regulator compiler and read-only acquisition (ADR024).

No lab creation, rule installation, dispatch, attestation or calibration. The
parent owns serialized provisioning. Generated transactions use exclusive create
and must be reviewed against the *running* kernel before qualification.
"""

import copy
import hashlib
import json
import time

TABLE = "nanfo_native_qualification"
CATEGORIES = ("h1_h3", "h3_h1", "h2_h4", "h4_h2", "arp", "ospf")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _match(left, right, op="=="):
    return {"match": {"op": op, "left": left, "right": right}}


def regulator_transactions(spec):
    """Compile a validated NativeDesign's JSON; unknown/oversize/excess DROP.

    Every class has its own packet token bucket, including ARP and OSPF. Counting
    accepted bytes happens AFTER policing and BEFORE qdisc. No protocol has an
    unpoliced exemption. All IPv4 traffic between a host pair (ACKs/probes too)
    shares its class. Fragmentation does not bypass the IP address classifiers.
    """
    output = {}
    for e in spec["egresses"]:
        node, key = e["node"], e["egress_id"]
        if node not in output:
            output[node] = [{"create": {"table": {"family": "netdev", "name": TABLE}}}]
        commands = output[node]
        base = {"family": "netdev", "table": TABLE}
        commands.append({"create": {"chain": {**base, "name": key, "type": "filter",
            "hook": "egress", "dev": e["interface"], "prio": -500, "policy": "drop"}}})

        def counter(name, commands=commands, base=base):
            commands.append({"create": {"counter": {**base, "name": name}}})

        def rule(chain, expressions, commands=commands, base=base):
            commands.append({"add": {"rule": {**base, "chain": chain, "expr": expressions}}})

        counter(key + "_offered")
        rule(key, [{"counter": key + "_offered"}])
        if e.get("epoch_quota_bytes") is not None:
            # Atomic lifetime quota closes arbitrary hook->enqueue delay for a
            # finite campaign epoch. Never reset/replenish during that epoch.
            commands.append({"create": {"quota": {**base, "name": key + "_quota",
                "bytes": e["epoch_quota_bytes"], "inv": True}}})
            counter(key + "_quota_drop")
            rule(key, [{"quota": key + "_quota"}, {"counter": key + "_quota_drop"}, {"drop": None}])
        for category in CATEGORIES:
            name = key + "_" + category
            bucket = e["buckets"][category]
            commands.append({"create": {"chain": {**base, "name": name}}})
            for suffix in ("offered", "oversize", "excess", "accepted"):
                counter(name + "_" + suffix)
            if category == "arp":
                selector = [_match({"meta": {"key": "protocol"}}, "arp")]
            else:
                selector = [_match({"meta": {"key": "protocol"}}, "ip")]
                if category == "ospf":
                    selector.append(_match({"payload": {"protocol": "ip", "field": "protocol"}}, 89))
                else:
                    source, destination = category.split("_")
                    selector.extend(_match({"payload": {"protocol": "ip", "field": field}},
                                           spec["host_addresses"][host])
                                    for field, host in (("saddr", source), ("daddr", destination)))
            rule(key, [*selector, {"goto": {"target": name}}])
            rule(name, [{"counter": name + "_offered"}])
            rule(name, [_match({"meta": {"key": "length"}}, bucket["max_skb_bytes"], ">"),
                        {"counter": name + "_oversize"}, {"drop": None}])
            rule(name, [{"limit": {"rate": bucket["packets_per_second"], "per": "second",
                                   "burst": bucket["burst_packets"], "inv": True}},
                        {"counter": name + "_excess"}, {"drop": None}])
            rule(name, [{"counter": name + "_accepted"}, {"accept": None}])
        counter(key + "_unknown")
        rule(key, [{"counter": key + "_unknown"}, {"drop": None}])
    return {node: {"nftables": rows} for node, rows in output.items()}


def queue_commands(spec):
    """Commands only, for clean disposable interfaces; parent must fence owner.

    TBF is a ceiling, not a service guarantee. Its bfifo child is the measured
    byte queue. Replacing the automatically created child is deliberate. Existing
    netem/HTB roots must cause the initial `add root` to fail, never be overwritten.
    """
    return [{"node": e["node"], "egress_id": e["egress_id"], "commands": [
        ["tc", "qdisc", "add", "dev", e["interface"], "root", "handle", "1:", "tbf",
         "rate", str(e["shaper_bytes_per_second"]) + "bps", "burst", str(e["shaper_burst_bytes"]),
         "limit", str(e["queue_limit_bytes"])],
        ["tc", "qdisc", "replace", "dev", e["interface"], "parent", "1:1", "handle", "10:",
         "bfifo", "limit", str(e["queue_limit_bytes"])],
    ]} for e in spec["egresses"]]


def validate_rules(actual, expected):
    """Reject altered rules/order/options; ignore only handles/live counter values.

    nft versions that normalize expressions differently require a reviewed adapter;
    don't silently weaken comparison to accept them.
    """
    def grouped(document, transaction=False):
        groups = {k: [] for k in ("table", "chain", "counter", "quota", "rule")}
        for entry in document["nftables"]:
            if "metainfo" in entry:
                continue
            if transaction:
                entry = next(iter(entry.values()))
            if len(entry) != 1 or next(iter(entry)) not in groups:
                raise ValueError("native_unexpected_nft_object")
            kind, row = next(iter(entry.items()))
            row = copy.deepcopy(row)
            row.pop("handle", None)
            if kind == "counter":
                for key in ("packets", "bytes"):
                    if not transaction and (type(row.get(key)) is not int or not 0 <= row[key] < 2**63):
                        raise ValueError("native_counter_invalid")
                    row.pop(key, None)
            if kind == "quota":
                if not transaction and (type(row.get("used")) is not int or not 0 <= row["used"] <= row["bytes"]):
                    raise ValueError("native_quota_usage_invalid")
                row.pop("used", None)
            groups[kind].append(row)
        return groups
    if grouped(actual) != grouped(expected, transaction=True):
        raise ValueError("native_regulator_readback_mismatch")


def capture_endpoint(network, spec, *, clock=time):
    """Read actual nft/tc/ip JSON, preserving individual monotonic/wall spans.

    The network must already be an exclusively handed-off AttachedFRRNetwork.
    Captures are raw evidence, NOT NetworkReading or a provider frame. No route
    probes are emitted. A failed command is retained as an incomplete capture.
    """
    result = {"version": "nanfo.native-endpoint/v1", "design_sha256": digest(spec),
              "reads": [], "failures": [], "measurement_complete": False,
              "physical_qualified": False}
    queries = []
    for node in sorted({e["node"] for e in spec["egresses"]}):
        queries.extend((node, kind, args) for kind, args in (
            ("nft", ["nft", "-j", "list", "ruleset"]),
            ("links", ["ip", "-j", "-d", "link", "show"]),
            ("rules", ["ip", "-j", "rule", "show"]),
            ("routes", ["ip", "-j", "route", "show", "table", "all"]),
            ("neighbors", ["ip", "-j", "neigh", "show"])))
    for e in spec["egresses"]:
        for kind, args in (("qdisc", ["tc", "-j", "-s", "-d", "qdisc", "show", "dev", e["interface"]]),
                           ("filters_ingress", ["tc", "-j", "filter", "show", "dev", e["interface"], "ingress"]),
                           ("filters_egress", ["tc", "-j", "filter", "show", "dev", e["interface"], "egress"])):
            queries.append((e["node"], kind + ":" + e["egress_id"], args))
    for node, kind, args in queries:
        row = {"node": node, "kind": kind, "argv": args,
               "start_wall_ns": clock.time_ns(), "start_monotonic_ns": clock.monotonic_ns()}
        try:
            row["raw"] = network.command(node, args)
            row["parsed"] = json.loads(row["raw"])
        except (ValueError, OSError, RuntimeError):
            result["failures"].append("native_read_failed:" + node + ":" + kind)
        finally:
            row.update(end_monotonic_ns=clock.monotonic_ns(), end_wall_ns=clock.time_ns())
            result["reads"].append(row)
    result["measurement_complete"] = not result["failures"]
    return result


def observation_envelope(raw_capture):
    """Detached canonical clock for a passive native feed; raw bytes stay intact.

    Host-only (backend interpreter): the clock moved to the backend (ADR-028).
    """
    from emulation.native_qualification_clock import endpoint_clock_binding
    return {"raw_capture": raw_capture, "clock_binding": endpoint_clock_binding(raw_capture)}
