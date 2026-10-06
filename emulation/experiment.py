"""Opt-in, single-owner ADR-011 measured environment; no learning dependencies."""

import fcntl
import hashlib
import json
import math
import os
import select
import signal
import socket
import subprocess
import time
import uuid
from pathlib import Path

from emulation.actions import HOST_MAP, NAMES, PORTS, Actions
from emulation.experiment_client import REQUEST_LIMIT, RESPONSE_LIMIT, SOCKET, decode
from emulation.lab_contracts import ACTION_PATHS
from emulation.measurements import atomicJson, parsePing, parseQueue, utcNow
from emulation.runner import stopProcess
from emulation.topology import LINKS
from emulation.workloads import (
    MATCHED_PROFILES,
    MATCHED_SCENARIOS,
    SCENARIOS,
    SCHEDULE_VERSION,
    schedule,
)

ENVIRONMENT_SPEC = {
    "version": 4,
    "name": "nanfo-sampled-routing-pomdp",
    "observability": "sampled_pomdp; observation history does not guarantee Markov state",
    "schedule_version": "seeded-phase-per-response-v1",
    "phase_relationship": "action from observation k-1; workload advances to k before action; response and reward measure k",
    "actor_inputs": "measured observation history only; no seed, scenario, phase index or future schedule",
    "control_version": "traffic-before-break-before-make-and-end-readback-v1",
    "discovery_interval": "real cyclic SDN probes before workload counters; excluded from reward",
    "state_reward_interval": "same returned aggregate; not a separate next-phase measurement",
    "udp_interval": "each sender lifetime including control; receiver totals include drain",
    "goodput_ratio": "received foreground bytes / actual foreground sent bytes",
    "counter_interval": "per-interface before load through receiver drain and readback",
    "queue_interval": "post-control load; peak sampled leaf netem; 80ms plus collection time",
    "ping_interval": "foreground concurrent load through sender termination",
    "drain_version": "post-sender-termination-verified-leaf-queues-v4",
    "drain_max_seconds": 3.0,
    "drain_poll_interval_seconds": 0.08,
    "drain_empty_observations": 2,
    "drain_queue_scope": "all topology link endpoints, both directions, including hosts and alternate paths; single leaf netem per interface",
    "drain_completion": "all senders exited; receivers alive; two consecutive complete zero-byte/zero-packet queue sweeps separated by at least drain_poll_interval_seconds; completed within drain_max_seconds",
    "drain_timeout": "truncate with measurement_complete=false; retain final endpoint totals and partial queue evidence; no valid loss/goodput outcome",
    "late_received_packets": "unavailable (null per flow); workers publish final totals only, no drain-begin streaming counter; never inferred from queue backlog",
    "goodput_denominator": "actual foreground sender duration; delivered numerator includes service during control and verified drain",
    "latency_measurement": "foreground ICMP RTT during load; not UDP RTT",
    "ping_timeout_ms": 1000,
    "service_outage": "valid positive probe count with zero replies; RTT null; UDP counters still required",
    "window_bounds_seconds": [2, 10],
    "window_overrun_tolerance_seconds": 2,
    "generator_relative_tolerance": 0.2,
}
SOURCE_FILES = (
    "experiment.py",
    "workloads.py",
    "actions.py",
    "topology.py",
    "ospf.py",
    "matched.py",
    "measurements.py",
    "runner.py",
    "controller.py",
    "controller_main.py",
    "lab_contracts.py",
    "experiment_client.py",
    "Dockerfile",
    "debian-snapshot.sources",
    "requirements.txt",
    "requirements-build.txt",
    "compose.yaml",
)


def environmentSpec(mode="sdn"):
    sources = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in SOURCE_FILES
    }
    sourceDigest = hashlib.sha256(
        json.dumps(sources, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    spec = {**ENVIRONMENT_SPEC, "source_sha256": sourceDigest, "source_files": sources}
    if mode in ("matched", "ospf"):
        spec.update(
            version=5,
            name="nanfo-matched-stationary-routing",
            observability="stationary exogenous capacities and demands observed; sampled queues/history not a proven Markov state",
            schedule_version=SCHEDULE_VERSION,
            phase_relationship="episode capacities and demands fixed before reset through all decisions",
            actor_inputs="measured observation history and actual HTB path capacities only; no seed/scenario/index",
            control_version="source-specific-linux-policy-routing-and-end-readback-v3",
            discovery_interval="FRR readiness and all-pairs probes before episode; no SDN discovery",
            modes=["matched", "ospf"],
            scenarios=list(MATCHED_SCENARIOS),
            profiles=json.loads(json.dumps(MATCHED_PROFILES)),
            schedule_draws="random.Random(integer seed); first foreground uniform(*offered_mbps), then background uniform(*background_mbps), each round(value,3); then capacity_draw_order with random.choice of listed path_capacity_mbps arrays, singleton arrays consume no draw; repeat unchanged for indices 0..episode_steps inclusive",
            capacity_policy="profile integer Mbps; identical rate/ceil on both directions of both inter-router links; repeated serial service is not summed capacity",
            demand_policy="profile foreground/background Mbps ranges; constant per episode; low/path0/path1 preserve v4 draws",
            flow_order=["h1->h3", "h2->h4"],
            actual_offered_policy="per-flow actual_offered_mbps[i]=udp_sent[i].bytes*8/udp_sent[i].duration_seconds/1e6; each within 20 percent of its phase target; 1200-byte payloads; receiver bytes=packets*1200; 0<=received<=sent; not a delivered-rate guarantee",
            routing_health_policy="fresh Full neighbor identities/interfaces and exact bidirectional kernel paths before load and at end under load; background path0 both modes, foreground requested path in matched and path0 in ospf; mismatch truncates, no reconvergence retry or timer/cost retuning; sampled health is not a convergence SLA",
            background_policy="actual FRR OSPF h2->h4 and return; no pinning in either mode",
            ospf_cost_policy="nominal manifest bandwidth costs frozen before impairment; single next hop prefers dist1; not capacity-aware OSPF",
            capacity_observation="path_capacity_mbps from verified HTB rate/ceil; utilization divided by actual shaped capacity",
            route_policy="matched overrides exact h1/h3 source+destination /32 both directions at every router on route0/1; ospf ignores action",
        )
    elif mode != "sdn":
        raise ValueError("Unknown environment mode")
    digest = hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    ).hexdigest()
    return spec, digest


ROUTES = ACTION_PATHS
FIXTURE_COOKIE = "0x4e414e4600000007"
FIELDS = {
    "version",
    "command",
    "episode_id",
    "step_index",
    "seed",
    "scenario",
    "action",
    "mode",
    "window_seconds",
    "episode_steps",
}


def validate(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("Exact ADR-011 request fields required")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported version")
    if value["command"] not in ("reset", "step", "close") or value["mode"] not in (
        "sdn",
        "matched",
        "ospf",
    ):
        raise ValueError("Invalid command or mode")
    window = value["window_seconds"]
    if type(window) not in (int, float) or not math.isfinite(window) or not 2 <= window <= 10:
        raise ValueError("window_seconds must be finite in 2..10")
    if type(value["episode_steps"]) is not int or not 2 <= value["episode_steps"] <= 64:
        raise ValueError("episode_steps must be an integer in 2..64")
    if value["seed"] is not None and (
        type(value["seed"]) is not int or not 0 <= value["seed"] <= 2147483647
    ):
        raise ValueError("Invalid seed")
    scenarios = SCENARIOS if value["mode"] == "sdn" else MATCHED_SCENARIOS
    if value["scenario"] is not None and value["scenario"] not in scenarios:
        raise ValueError("Invalid scenario")
    if value["episode_id"] is not None and (
        not isinstance(value["episode_id"], str)
        or str(uuid.UUID(value["episode_id"])) != value["episode_id"]
    ):
        raise ValueError("episode_id must be a canonical UUID")
    if value["step_index"] is not None and (
        type(value["step_index"]) is not int or not 0 <= value["step_index"] <= 64
    ):
        raise ValueError("Invalid step_index")
    if value["action"] is not None and (
        type(value["action"]) is not int or value["action"] not in (0, 1)
    ):
        raise ValueError("Invalid action")
    if value["command"] == "reset":
        if any(value[k] is not None for k in ("episode_id", "step_index", "action")):
            raise ValueError("reset requires null identity, index and action")
        if value["seed"] is None or value["scenario"] is None:
            raise ValueError("reset requires seed and scenario")
    elif value["command"] == "step":
        if any(value[k] is None for k in ("episode_id", "step_index", "action")):
            raise ValueError("step requires identity, index and action")
    elif value["action"] is not None:
        raise ValueError("close requires null action")
    return value


def pathPorts():
    return [
        [
            (node, PORTS[node, peer][0])
            for node, peer in (
                (route[0], route[1]),
                (route[1], route[0]),
                (route[1], route[2]),
                (route[2], route[1]),
            )
        ]
        for route in ROUTES
    ]


class SdnRouting:
    def __init__(self, lab):
        self.lab = lab
        self.driver = Actions(lab)
        self.prepared = None
        self.action = None
        self.fixturePath = None

    def readback(self):
        actual = self.driver.verify(self.prepared)
        return {
            node: [
                line.strip()
                for line in row["flows"].splitlines()
                if "cookie=0x4e414e4600000001" in line
            ]
            for node, row in actual["switches"].items()
        }

    def change(self, action):
        if self.action == action:
            return {"changed": False, "path": list(ROUTES[action]), "readback": self.readback()}
        if self.prepared is not None:
            self.driver.rollback(self.prepared)
            self.prepared = None
        plan = {
            "operation": "reroute",
            "source_host": "h1",
            "destination_host": "h3",
            "paths": [list(ROUTES[action])],
            "weights": [1],
            "dscp": None,
            "rate_mbps": None,
        }
        self.prepared = self.driver.prepare(plan)
        self.driver.apply(self.prepared, self.lab.checkController)
        readback = self.readback()
        self.action = action
        return {
            "changed": True,
            "path": list(ROUTES[action]),
            "readback": readback,
            "strategy": "break-before-make; baseline forwarding may carry traffic in gap",
        }

    def fixture(self, path):
        # Owned forwarding bypasses PacketIn. Refresh real attachment observations
        # on the unowned cyclic probe pairs, outside the measured traffic window.
        self.lab.probe()
        deadline = time.monotonic() + 3
        while not self.lab.ready(self.lab.controllerState()):
            self.lab.checkController()
            if time.monotonic() >= deadline:
                raise RuntimeError("Fresh observed topology and host attachments required")
            time.sleep(0.1)
        if self.fixturePath == path:
            return
        self.clearFixture()
        route = ROUTES[path]
        for src, dst, nodes in (
            (HOST_MAP["h2"], HOST_MAP["h4"], route),
            (HOST_MAP["h4"], HOST_MAP["h2"], tuple(reversed(route))),
        ):
            for index, node in enumerate(nodes):
                ingress = src["port_no"] if index == 0 else PORTS[node, nodes[index - 1]][0]
                egress = dst["port_no"] if index == 2 else PORTS[node, nodes[index + 1]][0]
                flow = (
                    f"cookie={FIXTURE_COOKIE},table=1,priority=25000,in_port={ingress},"
                    f"ip,dl_src={src['mac']},dl_dst={dst['mac']},nw_src={src['ipv4']},"
                    f"nw_dst={dst['ipv4']},actions=output:{egress}"
                )
                self.driver.of("add-flow", node, flow)
                rows = self.driver.of("dump-flows", node, f"cookie={FIXTURE_COOKIE}/-1,table=1")
                if not any(
                    all(
                        token in line.replace(" ", ",").split(",")
                        for token in flow.split(",actions=")[0].split(",")
                    )
                    and line.split(" actions=")[-1] == f"output:{egress}"
                    for line in rows.splitlines()
                ):
                    raise RuntimeError("Fixture flow readback failed")
        self.fixturePath = path

    def clearFixture(self):
        for node in NAMES.values():
            self.driver.of("del-flows", node, f"cookie={FIXTURE_COOKIE}/-1,table=1")
            if FIXTURE_COOKIE in self.driver.of("dump-flows", node, "table=1"):
                raise RuntimeError("Fixture cleanup failed")
        self.fixturePath = None

    def close(self):
        try:
            if self.prepared is not None:
                self.driver.rollback(self.prepared)
                self.prepared = None
            self.driver.reconcile()
        finally:
            self.clearFixture()
        self.action = None


class OspfLab:
    """Lifecycle adapter: FRR owns namespaces; workload children remain separate."""

    def __init__(self, output):
        from emulation.ospf import OSPFNetwork

        self.network = OSPFNetwork()
        self.output = output
        self.outputLock = None
        self.processes = []
        self.stopping = False

    def start(self):
        self.outputLock = os.open(
            str(self.output / ".producer.lock"), os.O_CREAT | os.O_RDWR, 0o644
        )
        fcntl.flock(self.outputLock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.network.start()
        self.net = self.network.net
        self.hostAddresses = self.network.hostAddresses
        atomicJson(self.output / "experiment-ospf-readiness.json", self.network.verify())

    def checkController(self):
        if self.stopping:
            raise RuntimeError("Lab stopping")
        self.network.checkProcesses()

    def close(self):
        try:
            for process in self.processes:
                stopProcess(process)
            self.network.close()
        finally:
            if self.outputLock is not None:
                os.close(self.outputLock)
                self.outputLock = None


class OspfRouting:
    def __init__(self, lab):
        self.lab = lab
        self.action = None

    def fixture(self, path):
        self.lab.checkController()  # OSPF determines both flows; no fixture route installation.

    def change(self, action):
        foreground = self.lab.network.routePath("h1", "h3")
        background = self.lab.network.routePath("h2", "h4")
        if foreground["action"] not in (0, 1):
            raise RuntimeError("OSPF foreground route is outside two-path observation contract")
        changed = self.action != foreground["action"]
        self.action = foreground["action"]
        return {
            "changed": changed,
            "path": foreground["nodes"][1:-1],
            "actual_action": foreground["action"],
            "requested_action_ignored": action,
            "readback": foreground,
            "background_readback": background,
            "policy": self.lab.network.policy,
        }

    def close(self):
        # There are no experiment-owned OSPF mutations to undo. The lab owner
        # terminates all FRR processes and namespaces when the server closes.
        if not self.lab.stopping:
            self.lab.checkController()


def counters(lab):
    result = {}
    for ports in pathPorts():
        for node, port in ports:
            interface = f"{node}-eth{port}"
            # Kernel link counters are local, synchronous and independently timed.
            process = lab.net[node].popen(
                ["ip", "-s", "-j", "link", "show", "dev", interface],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                text, _ = process.communicate(timeout=2)
            finally:
                stopProcess(process)
            if process.returncode:
                raise RuntimeError("Link counter read failed")
            row = json.loads(text)[0]
            stats = row.get("stats64", row.get("stats"))
            result[interface] = {
                "tx_bytes": stats["tx"]["bytes"],
                "rx_bytes": stats["rx"]["bytes"],
                "monotonic_seconds": time.monotonic(),
            }
    return result


def utilization(before, after, capacities=(20, 20)):
    values, windows = [], {}
    for ports, capacity in zip(pathPorts(), capacities):
        rates = []
        for node, port in ports:
            key = f"{node}-eth{port}"
            if key not in before or key not in after:
                continue
            a, b = before[key], after[key]
            duration = b["monotonic_seconds"] - a["monotonic_seconds"]
            delta = b["tx_bytes"] - a["tx_bytes"]
            windows[key] = {"before": a, "after": b, "duration_seconds": duration}
            if duration > 0 and delta >= 0:
                rates.append(delta * 8 / duration / (capacity * 1e6))
        values.append(max(rates) if len(rates) == 4 else None)
    return values, windows


def drainQueues(lab, receivers, evidence):
    """Bound queue verification, not a fixed sleep or inferred endpoint delivery."""
    began = time.monotonic()
    spec = evidence["environment_spec"]
    deadline = began + spec["drain_max_seconds"]
    interfaces = {
        f"{node}-eth{port}": node for link in LINKS for node, port in (link["a"], link["b"])
    }
    evidence.update(
        drain_begin=began,
        drain_end=None,
        drain_status="unverified",
        drain_error=None,
        drain_queue_interfaces=list(interfaces),
        drain_sweeps=0,
        drain_empty_observations=[],
        queue_begin={},
        queue_end={},
        late_received_packets=[None, None],
        late_received_unavailable_reason="workers publish final totals only; no drain-begin counter",
    )
    try:
        while time.monotonic() < deadline:
            lab.checkController()
            if any(p.poll() is not None for p in receivers):
                raise RuntimeError("Receiver exited before verified drainage")
            sweep = {"start": time.monotonic(), "end": None, "queues": {}}
            evidence["queue_end"] = sweep["queues"]
            if evidence["drain_sweeps"] == 0:
                evidence["queue_begin"] = sweep["queues"]
            for interface, node in interfaces.items():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                process = lab.net[node].popen(
                    ["tc", "-s", "-j", "qdisc", "show", "dev", interface],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                try:
                    text, _ = process.communicate(timeout=min(2, remaining))
                except subprocess.TimeoutExpired:
                    # Do not spend the generic three-second graceful-stop budget on tc.
                    process.kill()
                    process.wait(timeout=0.2)
                    raise
                finally:
                    stopProcess(process)
                queue = parseQueue(text)
                if process.returncode != 0 or queue is None:
                    raise RuntimeError(f"Missing or invalid drain leaf queue: {interface}")
                sweep["queues"][interface] = {
                    **queue,
                    "monotonic_seconds": time.monotonic(),
                    "raw_leaf_qdiscs": json.loads(text),
                }
            sweep["end"] = time.monotonic()
            evidence["drain_sweeps"] += 1
            if any(p.poll() is not None for p in receivers):
                raise RuntimeError("Receiver exited during queue drainage")
            if sweep["end"] > deadline or len(sweep["queues"]) != len(interfaces):
                break
            empty = all(
                row["backlog_bytes"] == row["backlog_packets"] == 0
                for row in sweep["queues"].values()
            )
            if empty:
                evidence["drain_empty_observations"].append(sweep)
                if len(evidence["drain_empty_observations"]) == spec["drain_empty_observations"]:
                    evidence["drain_status"] = "verified_empty"
                    break
            else:
                evidence["drain_empty_observations"].clear()
            time.sleep(
                min(spec["drain_poll_interval_seconds"], max(0, deadline - time.monotonic()))
            )
        if evidence["drain_status"] != "verified_empty":
            evidence["drain_status"] = "timeout"
            evidence["drain_error"] = "Queue drainage not established within 3-second cap"
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        evidence["drain_status"] = "timeout" if time.monotonic() >= deadline else "unverified"
        evidence["drain_error"] = str(error)[:200]
    finally:
        evidence["drain_end"] = time.monotonic()
        evidence["drain_duration_seconds"] = evidence["drain_end"] - began
        if evidence["drain_end"] > deadline:
            evidence["drain_status"] = "timeout"
            evidence["drain_error"] = "Queue drainage exceeded 3-second cap"


def measurementOutcome(observation, evidence, controlStart):
    """Validate measured evidence before deriving rates or declaring a service outage."""
    sent, received = evidence["udp_sent"], evidence["udp_received"]
    start, end = (evidence["post_control_interval"][k] for k in ("start", "end"))
    desired, measured = evidence["desired_window_seconds"], evidence["measured_window_seconds"]
    if not (
        all(
            type(v) in (int, float) and math.isfinite(v)
            for v in (start, end, desired, measured, controlStart)
        )
        and 2 <= desired <= 10
        and controlStart <= start < end
        and desired <= measured <= desired + 2
        and abs(end - start - measured) < 0.01
    ):
        raise RuntimeError("Invalid or incomplete positive measurement interval")
    if len(sent) != 2 or len(received) != 2:
        raise RuntimeError("Both UDP flows require sender and receiver counters")
    if evidence["drain_status"] != "verified_empty":
        raise RuntimeError(evidence["drain_error"] or "Queue drainage unverified")
    if not (
        max(s["finished_monotonic_seconds"] for s in sent)
        <= evidence["drain_begin"]
        < evidence["drain_end"]
        <= min(r["finished_monotonic_seconds"] for r in received)
        and evidence["drain_end"] - evidence["drain_begin"] <= ENVIRONMENT_SPEC["drain_max_seconds"]
    ):
        raise RuntimeError("Invalid receiver drain interval")
    for s, r in zip(sent, received):
        for worker in (s, r):
            if any(type(worker[k]) is not int for k in ("packets", "bytes", "highest_sequence")):
                raise RuntimeError("Invalid UDP counter types")
            duration, began, ended = (
                worker[k]
                for k in (
                    "duration_seconds",
                    "started_monotonic_seconds",
                    "finished_monotonic_seconds",
                )
            )
            if not (
                all(type(v) in (int, float) and math.isfinite(v) for v in (duration, began, ended))
                and duration > 0
                and began <= controlStart <= start < end <= ended
                and abs(ended - began - duration) < 0.01
            ):
                raise RuntimeError("UDP worker did not cover the complete concurrent window")
        if (
            s["packets"] <= 0
            or not 0 <= r["packets"] <= s["packets"]
            or s["bytes"] != s["packets"] * 1200
            or r["bytes"] != r["packets"] * 1200
            or not -1 <= r["highest_sequence"] < s["packets"]
            or (r["packets"] == 0) != (r["highest_sequence"] == -1)
            or r["highest_sequence"] < r["packets"] - 1
        ):
            raise RuntimeError("Invalid UDP sender/receiver counts")
    actual = [s["bytes"] * 8 / s["duration_seconds"] / 1e6 for s in sent]
    evidence["actual_offered_mbps"] = actual
    if any(
        abs(rate / observation[key] - 1) > 0.2
        for rate, key in zip(actual, ("offered_mbps", "background_mbps"))
    ):
        raise RuntimeError("UDP generator missed offered rate by more than 20 percent")
    probe = evidence["ping"]
    if (
        not isinstance(probe, dict)
        or type(probe.get("sent")) is not int
        or type(probe.get("received")) is not int
        or not 0 <= probe["received"] <= probe["sent"]
        or probe["sent"] <= 0
        or not math.isfinite(probe["interval_seconds"])
        or probe["interval_seconds"] < desired
        or (probe["received"] == 0) != (probe["rtt_avg_ms"] is None)
    ):
        raise RuntimeError("Missing or inconsistent foreground probe evidence")
    if probe["rtt_avg_ms"] is not None and (
        not math.isfinite(probe["rtt_avg_ms"]) or probe["rtt_avg_ms"] < 0
    ):
        raise RuntimeError("Invalid measured probe RTT")
    if (
        any(
            v is None or not math.isfinite(v) or v < 0
            for v in observation["path_utilization"] + observation["path_queue_packets"]
        )
        or len(evidence["queue_peaks"]) != 8
        or len(evidence["counter_windows"]) != 8
        or any(row["duration_seconds"] <= 0 for row in evidence["counter_windows"].values())
    ):
        raise RuntimeError("Incomplete counter or queue evidence")
    observation.update(
        actual_offered_mbps=actual[0],
        latency_ms=probe["rtt_avg_ms"],
        loss_fraction=1 - received[0]["packets"] / sent[0]["packets"],
        goodput_mbps=received[0]["bytes"] * 8 / sent[0]["duration_seconds"] / 1e6,
    )
    evidence["service_outage"] = probe["received"] == 0
    evidence["latency_censored"] = evidence["service_outage"]
    evidence["latency_timeout_ms"] = (
        ENVIRONMENT_SPEC["ping_timeout_ms"] if evidence["service_outage"] else None
    )


class Experiment:
    def __init__(self, lab, mode="sdn", routing=None):
        from emulation.matched import MatchedRouting

        self.lab, self.mode = lab, mode
        self.routing = (
            routing
            if routing is not None
            else (
                SdnRouting(lab)
                if mode == "sdn"
                else MatchedRouting(lab)
                if mode == "matched"
                else OspfRouting(lab)
            )
        )
        self.episode = None
        self.index = 0
        self.done = True
        self.closed = False
        self.changedAt = time.monotonic()
        self.lastRequest = time.monotonic()
        self.environmentSpec, self.specHash = environmentSpec(mode)

    def handle(self, request):
        try:
            value = validate(request)
            if self.closed or value["mode"] != self.mode:
                raise ValueError("Server closed or mode mismatch")
            if value["command"] == "reset":
                if not self.done:
                    raise ValueError("Active episode must finish or close before reset")
                self.routing.close()
                self.episode = str(uuid.uuid4())
                self.config = dict(value)
                self.phases = schedule(
                    value["seed"], value["scenario"], value["episode_steps"], self.mode
                )
                self.index, self.done = 0, False
                self.started = time.monotonic()
                atomicJson(
                    self.lab.output / f"experiment-{self.episode}-schedule.json", self.phases
                )
                data = self.measure(0)
            else:
                expectedIndex = (
                    None if self.episode is None else self.index + (value["command"] == "step")
                )
                if value["episode_id"] != self.episode or value["step_index"] != expectedIndex:
                    raise ValueError("Wrong episode or repeated/out-of-order step")
                if self.episode is not None and any(
                    value[k] != self.config[k] for k in ("window_seconds", "episode_steps")
                ):
                    raise ValueError("Episode configuration is frozen")
                if self.episode is not None and any(
                    value[k] is not None and value[k] != self.config[k]
                    for k in ("seed", "scenario")
                ):
                    raise ValueError("Episode workload is frozen")
                if value["command"] == "close":
                    self.routing.close()
                    self.closed = True
                    data = {"closed": True, "cleanup_verified": True, "episode_id": self.episode}
                else:
                    if self.done:
                        raise ValueError("Episode already finished")
                    self.index += 1
                    data = self.measure(value["action"])
            return {"version": 1, "ok": True, "error": None, "data": data}
        except (ValueError, TypeError, AttributeError) as error:
            return {"version": 1, "ok": False, "error": str(error)[:200], "data": None}
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            self.lab.stopping = True
            return {"version": 1, "ok": False, "error": str(error)[:200], "data": None}

    def measure(self, action):
        phase = self.phases[self.index]
        window = self.config["window_seconds"]
        observation = {
            "path_utilization": [None, None],
            "path_queue_packets": [None, None],
            "latency_ms": None,
            "loss_fraction": None,
            "goodput_mbps": None,
            "offered_mbps": phase["offered_mbps"],
            "actual_offered_mbps": None,
            "background_mbps": phase["background_mbps"],
            "previous_action": action,
            "seconds_since_change": 0.0,
        }
        if self.mode != "sdn":
            observation["path_capacity_mbps"] = [None, None]
        evidence = {
            "environment_spec": self.environmentSpec,
            "spec_hash": self.specHash,
            "provenance": {
                "source_sha256": self.environmentSpec["source_sha256"],
                "lab_image_id": os.environ.get("NANFO_LAB_IMAGE_ID"),
            },
            "phase": phase,
            "phase_relationship": {
                "action_observation_phase_index": self.index - 1 if self.index else None,
                "measurement_phase_index": self.index,
                "workload_advanced_before_action": self.index > 0 and self.mode == "sdn",
                "state_and_reward_share_measurement": True,
            },
            "measurement_complete": False,
            "service_outage": None,
            "latency_censored": None,
            "latency_timeout_ms": None,
            "desired_window_seconds": window,
            "initial_window": self.index == 0,
            "decision_windows": self.index,
            "measurement_source": "real namespace UDP, ping, kernel link counters, leaf netem",
            "transition_traffic_included": True,
        }
        processes = []
        began = time.monotonic()
        error = None
        addresses = getattr(
            self.lab, "hostAddresses", {name: row["ipv4"] for name, row in HOST_MAP.items()}
        )

        def spawn(host, args):
            process = self.lab.net[host].popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "LC_ALL": "C"},
            )
            processes.append(process)
            self.lab.processes.append(process)
            return process

        def ready(process):
            if not select.select([process.stdout], [], [], 2)[0] or decode(
                process.stdout.readline()
            ) != {"ready": True}:
                raise RuntimeError("UDP worker did not become ready")

        try:
            if self.mode != "sdn":
                evidence["capacity_readback"] = self.lab.network.shape(
                    phase["path_capacity_mbps"] if self.index == 0 else None
                )
                observation["path_capacity_mbps"] = list(self.lab.network.capacities)
            self.routing.fixture(phase["background_path"])
            if self.index == 0:
                evidence["initial_route"] = self.routing.change(action)
                self.changedAt = time.monotonic()
            if self.mode != "sdn":
                evidence["routing_health_start"] = self.lab.network.stationaryReadback(
                    self.routing.action if self.mode == "matched" else 0
                )
            receivers = [
                spawn(host, ["python", "-m", "emulation.workloads", "receive"])
                for host in ("h3", "h4")
            ]
            for process in receivers:
                ready(process)
            before = counters(self.lab)
            loadStart = time.monotonic()
            senders = [
                spawn(
                    host,
                    [
                        "python",
                        "-m",
                        "emulation.workloads",
                        "send",
                        "--target",
                        target,
                        "--mbps",
                        str(phase[rate]),
                    ],
                )
                for host, target, rate in (
                    ("h1", addresses["h3"], "offered_mbps"),
                    ("h2", addresses["h4"], "background_mbps"),
                )
            ]
            for process in senders:
                ready(process)
            ping = spawn("h1", ["ping", "-n", "-i", "0.2", "-W", "1", addresses["h3"]])
            # Traffic is already running when break-before-make begins.
            time.sleep(0.1)
            controlStart = time.monotonic()
            evidence["route"] = self.routing.change(action)
            observation["previous_action"] = evidence["route"].get("actual_action", action)
            if evidence["route"]["changed"]:
                self.changedAt = time.monotonic()
            evidence["control_overhead_seconds"] = time.monotonic() - controlStart
            measuredStart = time.monotonic()
            peaks, samples, queueEvidence = [None, None], [0, 0], {}
            while time.monotonic() - measuredStart < window:
                self.lab.checkController()
                if any(p.poll() is not None for p in receivers + senders + [ping]):
                    raise RuntimeError("Measurement worker exited before window end")
                for path, ports in enumerate(pathPorts()):
                    for node, port in ports:
                        process = self.lab.net[node].popen(
                            ["tc", "-s", "-j", "qdisc", "show", "dev", f"{node}-eth{port}"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                        try:
                            text, _ = process.communicate(timeout=2)
                        finally:
                            stopProcess(process)
                        queue = parseQueue(text)
                        if process.returncode == 0 and queue is not None:
                            samples[path] += 1
                            peaks[path] = max(peaks[path] or 0, queue["backlog_packets"])
                            key = f"{node}-eth{port}"
                            previous = queueEvidence.get(key)
                            if (
                                previous is None
                                or queue["backlog_packets"] > previous["backlog_packets"]
                            ):
                                queueEvidence[key] = {
                                    **queue,
                                    "monotonic_seconds": time.monotonic(),
                                    "raw_leaf_qdiscs": json.loads(text),
                                }
                time.sleep(0.08)
            evidence["measured_window_seconds"] = time.monotonic() - measuredStart
            measuredEnd = time.monotonic()
            evidence["route_end"] = self.routing.change(action)
            if self.mode != "sdn":
                evidence["capacity_readback_end"] = self.lab.network.shape()
                evidence["routing_health_end"] = self.lab.network.stationaryReadback(
                    observation["previous_action"] if self.mode == "matched" else 0
                )
            if (
                evidence["route_end"]["changed"]
                or evidence["route_end"]["path"] != evidence["route"]["path"]
            ):
                raise RuntimeError("Route changed during measurement window")
            for process in senders:
                process.send_signal(signal.SIGTERM)
            sent = [decode(p.communicate(timeout=2)[0]) for p in senders]
            if any(p.returncode != 0 for p in senders):
                raise RuntimeError("UDP sender exit failed")
            loadEnd = time.monotonic()
            evidence["senders_stopped_monotonic_seconds"] = loadEnd
            evidence["udp_sent"] = sent
            ping.send_signal(signal.SIGINT)
            drainQueues(self.lab, receivers, evidence)
            for process in receivers:
                process.send_signal(signal.SIGTERM)
            received = [decode(p.communicate(timeout=2)[0]) for p in receivers]
            evidence["udp_received"] = received
            if any(p.returncode != 0 for p in receivers):
                raise RuntimeError("UDP receiver exit failed")
            pingText = ping.communicate(timeout=2)[0].decode("ascii", errors="replace")
            after = counters(self.lab)
            rates, raw = utilization(before, after, observation.get("path_capacity_mbps", (20, 20)))
            probe = parsePing(pingText, "h1", "h3", loadEnd - loadStart, utcNow())
            evidence.update(
                {
                    "counter_windows": raw,
                    "queue_samples": samples,
                    "queue_peaks": queueEvidence,
                    "udp_sent": sent,
                    "udp_received": received,
                    "ping": probe,
                    "load_interval_seconds": loadEnd - loadStart,
                    "post_control_interval": {"start": measuredStart, "end": measuredEnd},
                    "control_start_monotonic_seconds": controlStart,
                    "queue_sampling": "peak sampled during post-control load, 80ms plus collection time",
                }
            )
            observation.update(
                {
                    "path_utilization": rates,
                    "path_queue_packets": peaks,
                    "seconds_since_change": time.monotonic() - self.changedAt,
                }
            )
            measurementOutcome(observation, evidence, controlStart)
        except (
            RuntimeError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            subprocess.SubprocessError,
        ) as failure:
            error = str(failure)[:200]
            self.done = True
        finally:
            for process in processes:
                stopProcess(process)
                self.lab.processes.remove(process)
        self.done = self.done or self.index >= self.config["episode_steps"]
        if self.done:
            try:
                self.routing.close()
                evidence["cleanup_verified"] = True
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
                error = "Routing cleanup uncertain; lab shutting down"
                evidence["cleanup_verified"] = False
                self.lab.stopping = True
        evidence.update(
            {
                "error": error,
                "measurement_complete": error is None,
                "transition_wall_seconds": time.monotonic() - began,
                "episode_wall_seconds": time.monotonic() - self.started,
            }
        )
        data = {
            "episode_id": self.episode,
            "step_index": self.index,
            "mode": self.mode,
            "seed": self.config["seed"],
            "scenario": self.config["scenario"],
            "terminated": self.done and error is None,
            "truncated": error is not None,
            "observation": observation,
            "evidence": evidence,
        }
        atomicJson(self.lab.output / f"experiment-{self.episode}-{self.index:02}.json", data)
        return data

    def serve(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(SOCKET)
            os.chmod(SOCKET, 0o600)
            server.listen(1)
            server.settimeout(1)
            try:
                while not self.closed and not self.lab.stopping:
                    if time.monotonic() - self.lastRequest > 300:
                        raise RuntimeError("Experiment idle watchdog expired")
                    try:
                        connection, _ = server.accept()
                    except socket.timeout:
                        continue
                    with connection:
                        connection.settimeout(2)
                        try:

                            def expired(signum, frame):
                                self.lab.stopping = True
                                raise RuntimeError(
                                    "Experiment request watchdog exceeded 45 seconds"
                                )

                            signal.signal(signal.SIGALRM, expired)
                            signal.alarm(45)
                            raw = bytearray()
                            while len(raw) <= REQUEST_LIMIT:
                                part = connection.recv(REQUEST_LIMIT + 1 - len(raw))
                                if not part:
                                    break
                                raw.extend(part)
                            if len(raw) > REQUEST_LIMIT:
                                raise ValueError("Request exceeds 4096 bytes")
                            self.lastRequest = time.monotonic()
                            result = self.handle(decode(raw))
                        except (
                            OSError,
                            ValueError,
                            RuntimeError,
                            subprocess.SubprocessError,
                        ) as failure:
                            result = {
                                "version": 1,
                                "ok": False,
                                "error": str(failure)[:200],
                                "data": None,
                            }
                        finally:
                            signal.alarm(0)
                        payload = json.dumps(result, allow_nan=False).encode("ascii")
                        if len(payload) > RESPONSE_LIMIT:
                            raise RuntimeError("Response bound exceeded")
                        try:
                            connection.sendall(payload)
                        except OSError:
                            # A lost response cannot safely be replayed. Close the owner.
                            self.closed = True
            finally:
                self.routing.close()
                Path(SOCKET).unlink(missing_ok=True)
