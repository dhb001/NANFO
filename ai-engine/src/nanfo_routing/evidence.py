"""Validate producer evidence, not just the presence of aggregate metric values."""

import hashlib
import math
import random

from .contracts import ACTION_MAP, CONTRACT, Data, Request, jsonBytes

PATH_PORTS = [
    ["access1-eth1", "dist1-eth3", "dist1-eth4", "access2-eth1"],
    ["access1-eth2", "dist2-eth3", "dist2-eth4", "access2-eth2"],
]


def number(value, *, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError("invalid finite evidence number")
    return value


def same(actual, expected, *, tolerance=1e-6):
    if not math.isclose(number(actual), number(expected), rel_tol=1e-6, abs_tol=tolerance):
        raise ValueError("derived measurement disagrees with evidence")


def validateSpec(spec, digest):
    if type(spec) is not dict or hashlib.sha256(jsonBytes(spec)).hexdigest() != digest:
        raise ValueError("lab spec hash mismatch")
    required = {
        "version": 3,
        "name": "nanfo-matched-stationary-routing",
        "phase_relationship": (
            "episode capacities and demands fixed before reset through all decisions"
        ),
        "actor_inputs": (
            "measured observation history and actual HTB path capacities only; "
            "no seed/scenario/index"
        ),
        "control_version": "source-specific-linux-policy-routing-and-end-readback-v3",
        "drain_version": "post-sender-termination-250ms-v1",
        "drain_seconds": 0.25,
        "schedule_version": "seeded-stationary-capacity-v3",
        "modes": ["matched", "ospf"],
        "scenarios": ["low", "path0", "path1"],
        "capacity_policy": (
            "path0=[2,20], path1=[20,2], low=[20,20] Mbps; "
            "both directions on both inter-router links"
        ),
        "demand_policy": (
            "seeded foreground uniform(5.8,6.2), background uniform(1.8,2.2) Mbps; "
            "constant per episode"
        ),
        "background_policy": "actual FRR OSPF h2->h4 and return; no pinning in either mode",
        "ospf_cost_policy": (
            "nominal manifest bandwidth costs frozen before impairment; single next hop "
            "prefers dist1; not capacity-aware OSPF"
        ),
        "capacity_observation": (
            "path_capacity_mbps from verified HTB rate/ceil; "
            "utilization divided by actual shaped capacity"
        ),
        "route_policy": (
            "matched overrides exact h1/h3 source+destination /32 both directions at every "
            "router on route0/1; ospf ignores action"
        ),
        "goodput_ratio": "received foreground bytes / actual foreground sent bytes",
        "ping_timeout_ms": 1000,
        "window_bounds_seconds": [2, 10],
        "window_overrun_tolerance_seconds": 2,
        "generator_relative_tolerance": 0.2,
    }
    if spec.get("version") == 4:
        from .drain import SEMANTICS

        required.pop("drain_seconds")
        required.update(SEMANTICS)
    if any(jsonBytes(spec.get(key)) != jsonBytes(value) for key, value in required.items()):
        raise ValueError("unsupported lab measurement semantics")
    sources = spec.get("source_files")
    if (
        type(sources) is not dict
        or not sources
        or any(
            type(value) is not str
            or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
            for value in sources.values()
        )
        or hashlib.sha256(jsonBytes(sources)).hexdigest() != spec.get("source_sha256")
    ):
        raise ValueError("invalid lab source fingerprint")


def validateMeasurement(data: Data, request: Request):
    """Raises on incomplete telemetry; an evidenced no-reply outage is still measured."""
    try:
        e, o = data.evidence, data.observation
        validateSpec(e["environment_spec"], e["spec_hash"])
        provenance = e["provenance"]
        if provenance["source_sha256"] != e["environment_spec"]["source_sha256"]:
            raise ValueError("lab provenance differs from spec")
        image = provenance["lab_image_id"]
        if image is not None and (
            type(image) is not str
            or not image.startswith("sha256:")
            or len(image) != 71
            or any(char not in "0123456789abcdef" for char in image[7:])
        ):
            raise ValueError("invalid lab image identity")
        if (
            data.truncated
            or e.get("error") is not None
            or e["measurement_complete"] is not True
            or e.get("cleanup_verified") is False
            or data.terminated != (data.step_index == request.episode_steps)
            or data.step_index != (request.step_index or 0)
            or (data.mode, data.seed, data.scenario)
            != (request.mode, request.seed, request.scenario)
            or (request.command == "step" and data.episode_id != request.episode_id)
            or (data.terminated and e.get("cleanup_verified") is not True)
        ):
            raise ValueError("invalid measurement context, completion or horizon")
        phase = e["phase"]
        if data.mode not in ("matched", "ospf") or data.scenario not in ("low", "path0", "path1"):
            raise ValueError("v3 requires stationary routed measurements")
        expectedCapacity = {"low": [20, 20], "path0": [2, 20], "path1": [20, 2]}[data.scenario]
        if (
            o.path_capacity_mbps != expectedCapacity
            or phase["path_capacity_mbps"] != expectedCapacity
        ):
            raise ValueError("capacity differs from frozen exogenous scenario")
        # Independently reconstruct seeded-stationary-capacity-v3, not just agreement
        # between attacker-relabelable fields. Draw order and rounding are semantic.
        rng = random.Random(data.seed)
        expectedPhase = {
            "phase_index": data.step_index,
            "background_path": 0,
            "offered_mbps": round(rng.uniform(5.8, 6.2), 3),
            "background_mbps": round(rng.uniform(1.8, 2.2), 3),
            "path_capacity_mbps": expectedCapacity,
        }
        if (
            phase != expectedPhase
            or o.offered_mbps != expectedPhase["offered_mbps"]
            or o.background_mbps != expectedPhase["background_mbps"]
        ):
            raise ValueError("workload differs from reconstructed seeded stationary v3 schedule")
        for key in ("capacity_readback", "capacity_readback_end"):
            rows = e[key]
            if len(rows) != 8 or {row["interface"] for row in rows} != {
                port for path in PATH_PORTS for port in path
            }:
                raise ValueError("missing capacity readback")
            for row in rows:
                capacity = expectedCapacity[
                    next(i for i, ports in enumerate(PATH_PORTS) if row["interface"] in ports)
                ]
                same(row["capacity_mbps"], capacity)
                owned = [
                    item
                    for item in row["classes"]
                    if item.get("kind") == "htb" and item.get("handle") == "5:1"
                ]
                if len(owned) != 1:
                    raise ValueError("missing owned HTB class")
                for rate in ("rate", "ceil"):
                    same(owned[0]["options"][rate], capacity * 1e6 / 8)
        if (
            type(phase["phase_index"]) is not int
            or phase["phase_index"] != data.step_index
            or type(phase["background_path"]) is not int
            or phase["background_path"] not in (0, 1)
        ):
            raise ValueError("invalid observed phase")
        same(phase["offered_mbps"], o.offered_mbps)
        same(phase["background_mbps"], o.background_mbps)
        relationship = {
            "action_observation_phase_index": data.step_index - 1 if data.step_index else None,
            "measurement_phase_index": data.step_index,
            "workload_advanced_before_action": False,
            "state_and_reward_share_measurement": True,
        }
        if jsonBytes(e["phase_relationship"]) != jsonBytes(relationship):
            raise ValueError("phase timing contract mismatch")
        if e["transition_traffic_included"] is not True or e["initial_window"] != (
            data.step_index == 0
        ):
            raise ValueError("invalid measurement interval flags")
        if type(e["decision_windows"]) is not int or e["decision_windows"] != data.step_index:
            raise ValueError("invalid decision window index")
        start, end = (number(e["post_control_interval"][key]) for key in ("start", "end"))
        control = number(e["control_start_monotonic_seconds"])
        duration = number(e["measured_window_seconds"])
        same(e["desired_window_seconds"], request.window_seconds)
        if not (
            control <= start < end
            and request.window_seconds <= duration <= request.window_seconds + 2
        ):
            raise ValueError("incomplete positive post-control interval")
        same(end - start, duration, tolerance=0.01)
        same(start - control, e["control_overhead_seconds"], tolerance=0.01)
        sent, received = e["udp_sent"], e["udp_received"]
        if len(sent) != 2 or len(received) != 2:
            raise ValueError("both UDP flows required")
        if e["environment_spec"]["version"] == 4:
            from .drain import validateDrain

            validateDrain(e)
        actual = []
        for s, r, target in zip(sent, received, (o.offered_mbps, o.background_mbps), strict=True):
            for worker in (s, r):
                if any(
                    type(worker[key]) is not int for key in ("packets", "bytes", "highest_sequence")
                ):
                    raise ValueError("invalid UDP count types")
                began, ended = (
                    number(worker[key])
                    for key in ("started_monotonic_seconds", "finished_monotonic_seconds")
                )
                length = number(worker["duration_seconds"], minimum=1e-9)
                if not began <= control <= start < end <= ended:
                    raise ValueError("UDP window does not cover control and measurement")
                same(ended - began, length, tolerance=0.01)
            if (
                s["packets"] <= 0
                or not 0 <= r["packets"] <= s["packets"]
                or s["bytes"] != s["packets"] * 1200
                or r["bytes"] != r["packets"] * 1200
                or not -1 <= r["highest_sequence"] < s["packets"]
                or (r["packets"] == 0) != (r["highest_sequence"] == -1)
                or r["highest_sequence"] < r["packets"] - 1
            ):
                raise ValueError("inconsistent UDP sender/receiver counts")
            rate = s["bytes"] * 8 / s["duration_seconds"] / 1e6
            if target <= 0 or abs(rate / target - 1) > 0.2:
                raise ValueError("generator missed target rate")
            actual.append(rate)
        if len(e["actual_offered_mbps"]) != 2:
            raise ValueError("missing actual sender rates")
        for actualRate, reportedRate in zip(actual, e["actual_offered_mbps"], strict=True):
            same(reportedRate, actualRate)
        same(o.actual_offered_mbps, actual[0])
        same(o.goodput_mbps, received[0]["bytes"] * 8 / sent[0]["duration_seconds"] / 1e6)
        same(o.loss_fraction, 1 - received[0]["packets"] / sent[0]["packets"])
        probe = e["ping"]
        if (
            type(probe["sent"]) is not int
            or type(probe["received"]) is not int
            or not 0 <= probe["received"] <= probe["sent"] <= 100
            or probe["sent"] <= 0
            or (probe["src_host"], probe["dst_host"]) != ("h1", "h3")
            or number(probe["interval_seconds"]) < request.window_seconds
        ):
            raise ValueError("invalid foreground ping evidence")
        same(probe["interval_seconds"], e["load_interval_seconds"])
        outage = probe["received"] == 0
        if (
            e["service_outage"] is not outage
            or e["latency_censored"] is not outage
            or (probe["rtt_avg_ms"] is None) != outage
            or (o.latency_ms is None) != outage
            or e["latency_timeout_ms"] != (CONTRACT["censored_delay_ms"] if outage else None)
        ):
            raise ValueError("missing RTT is not a verified censored service outage")
        if not outage:
            same(o.latency_ms, probe["rtt_avg_ms"])
        ports = {port for path in PATH_PORTS for port in path}
        if set(e["counter_windows"]) != ports or set(e["queue_peaks"]) != ports:
            raise ValueError("incomplete path counter/queue evidence")
        for index, path in enumerate(PATH_PORTS):
            rates, queues = [], []
            if type(e["queue_samples"][index]) is not int or e["queue_samples"][index] < 4:
                raise ValueError("missing queue samples")
            for port in path:
                row = e["counter_windows"][port]
                a, b = row["before"], row["after"]
                interval = number(row["duration_seconds"], minimum=1e-9)
                same(b["monotonic_seconds"] - a["monotonic_seconds"], interval)
                if not a["monotonic_seconds"] <= control <= start < end <= b["monotonic_seconds"]:
                    raise ValueError("counter window does not cover measurement")
                for key in ("tx_bytes", "rx_bytes"):
                    if (
                        type(a[key]) is not int
                        or type(b[key]) is not int
                        or not 0 <= a[key] <= b[key]
                    ):
                        raise ValueError("counter reset or invalid counter")
                rates.append(
                    (b["tx_bytes"] - a["tx_bytes"])
                    * 8
                    / interval
                    / (o.path_capacity_mbps[index] * 1e6)
                )
                queue = e["queue_peaks"][port]
                if not start <= number(queue["monotonic_seconds"]) <= end:
                    raise ValueError("queue sample outside post-control window")
                qdiscs = queue["raw_leaf_qdiscs"]
                leaves = [
                    row
                    for row in qdiscs
                    if row.get("kind") == "netem"
                    and not any(
                        child.get("parent", "").split(":")[0] == row.get("handle", "").split(":")[0]
                        for child in qdiscs
                        if child is not row
                    )
                ]
                if len(leaves) != 1:
                    raise ValueError("missing raw queue readback")
                same(leaves[0]["qlen"], queue["backlog_packets"])
                same(leaves[0]["backlog"], queue["backlog_bytes"])
                queues.append(number(queue["backlog_packets"]))
            same(o.path_utilization[index], max(rates))
            same(o.path_queue_packets[index], max(queues))
        for key in ("route", "route_end"):
            route = e[key]
            if type(route["changed"]) is not bool or route["path"] != ACTION_MAP[o.previous_action]:
                raise ValueError("route readback disagrees with observation")
            readback = route["readback"]
            if data.mode == "sdn":
                if set(readback) != set(CONTRACT["nodes"]) or any(
                    type(rows) is not list
                    or (len(rows) < 2 if node in route["path"] else bool(rows))
                    or any(
                        type(line) is not str
                        or "cookie=0x4e414e4600000001" not in line
                        or "actions=output:" not in line
                        for line in rows
                    )
                    for node, rows in readback.items()
                ):
                    raise ValueError("missing verified SDN flow readback")
                pathPort = o.previous_action + 1
                for source, target, outputs in (
                    ("10.77.0.1", "10.77.0.3", [pathPort, 4, 3]),
                    ("10.77.0.3", "10.77.0.1", [3, 3, pathPort]),
                ):
                    for node, output in zip(route["path"], outputs, strict=True):
                        if not any(
                            all(
                                token in line.replace(" ", ",").split(",")
                                for token in (
                                    "table=0",
                                    "priority=30000",
                                    f"nw_src={source}",
                                    f"nw_dst={target}",
                                )
                            )
                            and line.split(" actions=")[-1] == f"output:{output}"
                            for line in readback[node]
                        ):
                            raise ValueError("foreground forwarding readback differs from route")
            elif data.mode == "ospf" and (
                readback["action"] != o.previous_action
                or readback["nodes"][1:-1] != route["path"]
                or not route["background_readback"]
                or not route["policy"]
                or len(readback["kernel_routes"]) != len(readback["nodes"]) - 1
                or any(not hop["route"].get("dev") for hop in readback["kernel_routes"])
            ):
                raise ValueError("missing FRR route readback")
            if data.mode in ("matched", "ospf"):
                paths = (
                    readback["paths"]
                    if data.mode == "matched"
                    else {"h1->h3": readback, "h2->h4": route["background_readback"]}
                )
                endpointsList = [("h1", "h3"), ("h2", "h4")]
                if data.mode == "matched":
                    endpointsList += [("h3", "h1"), ("h4", "h2")]
                    owned = readback["owned"]
                    if set(owned) != {
                        f"{node}:{table}" for node in route["path"] for table in (19110, 19111)
                    }:
                        raise ValueError("missing exact matched route ownership")
                    for identity, ruleset in owned.items():
                        table = int(identity.split(":")[1])
                        source, destination = (
                            ("10.78.8.2", "10.78.10.2")
                            if table == 19110
                            else ("10.78.10.2", "10.78.8.2")
                        )
                        if len(ruleset["rules"]) != 1 or len(ruleset["routes"]) != 1:
                            raise ValueError("ambiguous matched route ownership")
                        rule, kernel = ruleset["rules"][0], ruleset["routes"][0]
                        if (
                            rule.get("priority") != table
                            or str(rule.get("table")) != str(table)
                            or rule.get("src") not in (source, source + "/32")
                            or rule.get("dst") not in (destination, destination + "/32")
                            or kernel.get("dst") not in (destination, destination + "/32")
                            or not kernel.get("dev")
                            or not kernel.get("gateway")
                            or kernel.get("protocol") != "static"
                        ):
                            raise ValueError("matched override is not exact foreground-only rule")
                for endpoints in endpointsList:
                    actual = paths["->".join(endpoints)]
                    if (actual["nodes"][0], actual["nodes"][-1]) != endpoints:
                        raise ValueError("FRR route endpoint mismatch")
                    if len(actual["kernel_routes"]) != len(actual["nodes"]) - 1 or any(
                        hop["node"] != node or not hop["route"].get("dev")
                        for hop, node in zip(
                            actual["kernel_routes"], actual["nodes"][:-1], strict=True
                        )
                    ):
                        raise ValueError("incomplete FRR kernel hop evidence")
                    if endpoints in (("h1", "h3"), ("h3", "h1")):
                        expected = route["path"] if endpoints[0] == "h1" else route["path"][::-1]
                        if actual["nodes"][1:-1] != expected:
                            raise ValueError("matched foreground path mismatch")
                if not route["policy"]:
                    raise ValueError("missing FRR policy")
        if e["route_end"]["changed"] is not False:
            raise ValueError("route changed within the measurement")
        if data.mode == "matched":
            beforePaths = e["route"]["readback"]["paths"]
            endPaths = e["route_end"]["readback"]["paths"]
            if any(
                beforePaths[key]["nodes"] != endPaths[key]["nodes"]
                for key in ("h1->h3", "h3->h1", "h2->h4", "h4->h2")
            ):
                raise ValueError("foreground/background path changed within window")
        elif (
            e["route"]["background_readback"]["nodes"]
            != (e["route_end"]["background_readback"]["nodes"])
        ):
            raise ValueError("OSPF background changed within window")
        if (
            data.mode != "ospf"
            and request.command == "step"
            and o.previous_action != request.action
        ):
            raise ValueError("requested route did not take effect")
        if not o.complete(censored=outage):
            raise ValueError("incomplete measured observation")
        return e["environment_spec"]
    except (KeyError, TypeError, IndexError, ZeroDivisionError, AttributeError) as exc:
        raise ValueError("missing or malformed measured evidence") from exc
