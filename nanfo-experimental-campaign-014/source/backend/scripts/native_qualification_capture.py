"""Offline native-counter replay. Does not confer instrument authenticity.

Strictly validates raw JSON rather than trusting normalized measurements or flags.
Use only after running-kernel accounting/snapshot semantics have been reviewed.
The existing independent campaign validator must still validate the exported
NetworkReading and all external trust receipts.
"""

import argparse
import json
from fractions import Fraction

from scripts.native_qualification import NativeDesign
from app.modules.autonomy.artifact_io import ArtifactStore, parse_json
from emulation.native_qualification import CATEGORIES, digest, regulator_transactions, validate_rules


def _integer(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError("native_nonnegative_integer_required")
    return value


def replay_endpoint(capture, design):
    design = NativeDesign.model_validate(design)
    spec = design.model_dump(mode="json")
    if (capture.get("version") != "nanfo.native-endpoint/v1"
            or capture.get("design_sha256") != digest(spec) or capture.get("failures")
            or capture.get("measurement_complete") is not True):
        raise ValueError("native_incomplete_endpoint")
    reads = {}
    nodes = {e.node for e in design.egresses}
    expected = {(node, kind) for node in nodes for kind in ("nft", "links", "rules", "routes", "neighbors")}
    expected |= {(e.node, kind + ":" + e.egress_id) for e in design.egresses
                 for kind in ("qdisc", "filters_ingress", "filters_egress")}
    for row in capture["reads"]:
        key = row["node"], row["kind"]
        if key in reads or key not in expected or parse_json(row["raw"].encode()) != row["parsed"]:
            raise ValueError("native_raw_read_identity_mismatch")
        values = [_integer(row[k]) for k in ("start_wall_ns", "end_wall_ns", "start_monotonic_ns", "end_monotonic_ns")]
        wall, mono = values[1] - values[0], values[3] - values[2]
        if min(wall, mono) < 0 or abs(wall - mono) > Fraction(design.clock_error_seconds) * 10**9:
            raise ValueError("native_clock_discontinuity")
        reads[key] = row
    if set(reads) != expected:
        raise ValueError("native_missing_reads")
    start = min(r["start_monotonic_ns"] for r in reads.values())
    end = max(r["end_monotonic_ns"] for r in reads.values())
    wall_start = min(r["start_wall_ns"] for r in reads.values())
    wall_end = max(r["end_wall_ns"] for r in reads.values())
    if abs((wall_end - wall_start) - (end - start)) > Fraction(design.clock_error_seconds) * 10**9:
        raise ValueError("native_endpoint_clock_discontinuity")
    if end - start > Fraction(design.sensor_span_seconds) * 10**9:
        raise ValueError("native_sensor_span_exceeded")
    counters = {}
    for node, wanted in regulator_transactions(spec).items():
        raw = reads[node, "nft"]["parsed"]
        # A complete ruleset, not merely the owned table: foreign hooks can
        # duplicate/mangle/divert packets after our counter.
        validate_rules(raw, wanted)
        counters[node] = {r["counter"]["name"]: r["counter"] for r in raw["nftables"] if "counter" in r}
    queues = {}
    for e in design.egresses:
        for kind in ("filters_ingress", "filters_egress"):
            if reads[e.node, kind + ":" + e.egress_id]["parsed"] != []:
                raise ValueError("native_tc_bypass_not_allowed")
        rows = reads[e.node, "qdisc:" + e.egress_id]["parsed"]
        if len(rows) != 2 or {(r.get("kind"), r.get("handle")) for r in rows} != {("tbf", "1:"), ("bfifo", "10:")}:
            raise ValueError("native_queue_tree_mismatch")
        leaf = next(r for r in rows if r["kind"] == "bfifo")
        root = next(r for r in rows if r["kind"] == "tbf")
        if (leaf.get("parent") != "1:1" or leaf.get("options") != {"limit": e.queue_limit_bytes}
                or root.get("root") is not True or root.get("options", {}).get("rate") != e.shaper_bytes_per_second):
            raise ValueError("native_queue_configuration_mismatch")
        # TBF burst / latency / size table normalization is runtime-version
        # dependent and intentionally remains an independent-review obligation.
        q = _integer(leaf.get("backlog"))
        if q > e.queue_limit_bytes:
            raise ValueError("native_byte_limit_violated")
        queues[e.egress_id] = {"queue_bytes": q, "departures_bytes": _integer(leaf.get("bytes")),
                              "drop_packets": _integer(leaf.get("drops")),
                              "counters": {k: v for k, v in counters[e.node].items() if k.startswith(e.egress_id + "_")}}
    return {"queues": queues, "start_ns": start, "end_ns": end, "wall_end_ns": wall_end}


def replay_window(before, after, design):
    design = NativeDesign.model_validate(design)
    old, new = replay_endpoint(before, design), replay_endpoint(after, design)
    dt = Fraction(new["end_ns"] - old["end_ns"], 10**9)
    wall_dt = Fraction(new["wall_end_ns"] - old["wall_end_ns"], 10**9)
    if abs(wall_dt - dt) > Fraction(design.clock_error_seconds):
        raise ValueError("native_window_clock_discontinuity")
    if (new["start_ns"] < old["end_ns"]
            or not Fraction(design.minimum_window_seconds) <= dt <= Fraction(design.horizon_seconds)):
        raise ValueError("native_window_outside_preregistered_horizon")
    if design.prequeue_delay_upper_seconds is None and any(e.epoch_quota_bytes is None for e in design.egresses):
        raise ValueError("native_prequeue_delay_not_proved")
    report = []
    for e in design.egresses:
        a, b = old["queues"][e.egress_id], new["queues"][e.egress_id]
        deltas = {}
        for name, initial in a["counters"].items():
            deltas[name] = {}
            for unit in ("bytes", "packets"):
                value = b["counters"][name][unit] - initial[unit]
                if value < 0:
                    raise ValueError("native_counter_reset")
                deltas[name][unit] = value
        departure = b["departures_bytes"] - a["departures_bytes"]
        if departure < 0 or b["drop_packets"] != a["drop_packets"]:
            raise ValueError("native_reset_or_queue_drop_bytes_unavailable")
        if deltas[e.egress_id + "_unknown"]["packets"]:
            raise ValueError("native_unknown_offered_traffic")
        if e.epoch_quota_bytes is not None and deltas[e.egress_id + "_quota_drop"]["packets"]:
            raise ValueError("native_epoch_quota_exhausted")
        arrivals = 0
        for category in CATEGORIES:
            name = e.egress_id + "_" + category
            admitted = deltas[name + "_accepted"]["bytes"]
            arrivals += admitted
            sigma, rho = e.buckets[category].envelope()
            # nft reads are not simultaneous; interval includes both read spans.
            uncertainty = 2 * (Fraction(design.sensor_span_seconds) + Fraction(design.clock_error_seconds))
            if admitted > sigma + rho * (dt + uncertainty):
                raise ValueError("native_admitted_arrival_envelope_exceeded")
        if e.epoch_quota_bytes is not None:
            total_admitted = sum(b["counters"][e.egress_id + "_" + c + "_accepted"]["bytes"] for c in CATEGORIES)
            if total_admitted > e.epoch_quota_bytes:
                raise ValueError("native_epoch_quota_exceeded")
        residual = b["queue_bytes"] - a["queue_bytes"] - arrivals + departure
        error = Fraction(design.sensor_error_bytes) + Fraction(design.accounting_error_bytes)
        if abs(residual) > error:
            raise ValueError("native_conservation_error_exceeded")
        report.append({"egress_id": e.egress_id, "admitted_bytes": arrivals,
                       "departures_bytes": departure, "conservation_residual_bytes": residual,
                       "regulator_drops_bytes": sum(v["bytes"] for k, v in deltas.items()
                                                    if k.endswith(("_excess", "_oversize")))})
    return {"raw_replay_passed": True, "activation_ready": False, "physical_qualified": False,
            "queues": report, "limitations": ["No route or timing certificate conferred.",
                "External source, accounting, controller and instrument review still required."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    for name in ("design", "before", "after"):
        parser.add_argument("--" + name, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        store = ArtifactStore(args.root)
        values = {name: store.document(getattr(args, name), sha256=getattr(args, name + "_sha256"))
                  for name in ("design", "before", "after")}
        result = replay_window(values["before"], values["after"], values["design"])
    except (ValueError, OSError, KeyError, TypeError, OverflowError):
        print(json.dumps({"raw_replay_passed": False, "activation_ready": False,
                          "error": "native_capture_rejected"}))
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
