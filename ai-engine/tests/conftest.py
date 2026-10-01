"""Synthetic contract fixtures for unit verification ONLY, never a training source."""

import hashlib
import json
import runpy
import sys
import tarfile
from copy import deepcopy
from pathlib import Path

import pytest

from nanfo_routing.contracts import ACTION_MAP, CONTRACT, jsonBytes
from nanfo_routing.evidence import PATH_PORTS

REPO = Path(__file__).resolve().parents[2]
FROZEN_LAB = REPO / "emulation/frozen/adr015-prechange-v4-source.tar.gz"
SPEC_FIXTURE = Path(__file__).resolve().parent / "fixtures/adr014-environment-spec.json"
# spec_hash recorded in the ADR014 release and in the qualified checkpoint manifest.
SPEC_FIXTURE_SHA256 = "bb15142a19ed3ee87a6aec2c6f9109d789d9736a5e6afda826ad898ef5fe7200"


def loadSpecFixture(path=SPEC_FIXTURE):
    spec = json.loads(Path(path).read_bytes())
    if hashlib.sha256(jsonBytes(spec)).hexdigest() != SPEC_FIXTURE_SHA256:
        raise ValueError("ADR014 environment spec fixture differs from its pinned spec_hash")
    return spec


def frozenLabModule(name):
    """A V4 producer module from the tracked frozen archive, pinned by the fixture spec."""
    with tarfile.open(FROZEN_LAB) as archive:
        source = archive.extractfile("emulation/" + name).read()
    if hashlib.sha256(source).hexdigest() != loadSpecFixture()["source_files"][name]:
        raise ValueError(f"frozen V4 {name} differs from the pinned lab source")
    namespace = {"__name__": "_frozen_v4_" + name.removesuffix(".py")}
    exec(compile(source, f"frozen-v4/emulation/{name}", "exec"), namespace)
    return namespace


def successorLabModule(name):
    """The evolving lab module (V5 refinement tests); it imports the emulation package."""
    saved = list(sys.path)
    sys.path.insert(0, str(REPO))
    try:
        return runpy.run_path(str(REPO / "emulation" / name))
    finally:
        sys.path[:] = saved


# Historical V4 client tests must not silently consume the evolving successor lab.
producerSchedule = frozenLabModule("workloads.py")["schedule"]


def producerSpec():
    # Refinement tests independently validate V5; production artifacts stay read-only.
    return loadSpecFixture()


def evidenceFixture(observation, request):
    sources = {"offline-fixture-only": "0" * 64}
    spec = {
        "version": 2,
        "name": "nanfo-sampled-routing-pomdp",
        "phase_relationship": (
            "action from observation k-1; workload advances to k before action; "
            "response and reward measure k"
        ),
        "actor_inputs": (
            "measured observation history only; no seed, scenario, phase index or future schedule"
        ),
        "control_version": "traffic-before-break-before-make-and-end-readback-v1",
        "drain_version": "post-sender-termination-250ms-v1",
        "drain_seconds": 0.25,
        "schedule_version": "seeded-phase-per-response-v1",
        "goodput_ratio": "received foreground bytes / actual foreground sent bytes",
        "ping_timeout_ms": 1000,
        "window_bounds_seconds": [2, 10],
        "window_overrun_tolerance_seconds": 2,
        "generator_relative_tolerance": 0.2,
        "source_files": sources,
        "source_sha256": hashlib.sha256(jsonBytes(sources)).hexdigest(),
    }
    spec = {
        **producerSpec(),
        "source_files": sources,
        "source_sha256": hashlib.sha256(jsonBytes(sources)).hexdigest(),
    }
    index = request.step_index or 0
    start, end = 101.0, 101.0 + request.window_seconds
    duration = request.window_seconds + 2
    sent, received = [], []
    for target, ratio in [
        (observation["actual_offered_mbps"], 0.9),
        (observation["background_mbps"], 1.0),
    ]:
        packets = round(target * 1e6 * duration / 9600)
        worker = {
            "packets": packets,
            "bytes": packets * 1200,
            "highest_sequence": -1,
            "duration_seconds": duration,
            "started_monotonic_seconds": 100.0,
            "finished_monotonic_seconds": 100.0 + duration,
        }
        sent.append(worker)
        receivedPackets = round(packets * ratio)
        received.append(
            {
                **worker,
                "packets": receivedPackets,
                "bytes": receivedPackets * 1200,
                "highest_sequence": receivedPackets - 1,
            }
        )
    rates = [row["bytes"] * 8 / duration / 1e6 for row in sent]
    for worker in received:
        worker["finished_monotonic_seconds"] += 0.5
        worker["duration_seconds"] += 0.5
    observation.update(
        actual_offered_mbps=rates[0],
        goodput_mbps=received[0]["bytes"] * 8 / duration / 1e6,
        loss_fraction=1 - received[0]["packets"] / sent[0]["packets"],
    )
    counters, queues = {}, {}
    for indexPath, ports in enumerate(PATH_PORTS):
        for port in ports:
            counters[port] = {
                "before": {"tx_bytes": 0, "rx_bytes": 0, "monotonic_seconds": 100.0},
                "after": {
                    "tx_bytes": round(
                        observation["path_utilization"][indexPath]
                        * observation["path_capacity_mbps"][indexPath]
                        * 1e6
                        * duration
                        / 8
                    ),
                    "rx_bytes": 0,
                    "monotonic_seconds": 100.0 + duration,
                },
                "duration_seconds": duration,
            }
            queues[port] = {
                "backlog_packets": observation["path_queue_packets"][indexPath],
                "backlog_bytes": observation["path_queue_packets"][indexPath] * 1200,
                "monotonic_seconds": start + 1,
                "raw_leaf_qdiscs": [
                    {
                        "kind": "netem",
                        "handle": "10:",
                        "backlog": observation["path_queue_packets"][indexPath] * 1200,
                        "qlen": observation["path_queue_packets"][indexPath],
                    }
                ],
            }
    path = ACTION_MAP[observation["previous_action"]]
    route = {
        "changed": False,
        "path": path,
        "readback": {
            node: ["cookie=0x4e414e4600000001 actions=output:1"] * 2 if node in path else []
            for node in CONTRACT["nodes"]
        },
    }
    for indexNode, node in enumerate(path):
        route["readback"][node] = [
            f"cookie=0x4e414e4600000001, table=0, priority=30000,nw_src={source},"
            f"nw_dst={target} actions=output:{outputs[indexNode]}"
            for source, target, outputs in (
                ("10.77.0.1", "10.77.0.3", [observation["previous_action"] + 1, 4, 3]),
                ("10.77.0.3", "10.77.0.1", [3, 3, observation["previous_action"] + 1]),
            )
        ]
    if request.mode in ("matched", "ospf"):
        nodes = ["h1", *path, "h3"]
        readback = {
            "nodes": nodes,
            "action": observation["previous_action"],
            "kernel_routes": [
                {"node": node, "route": {"dev": "fixture-eth0"}} for node in nodes[:-1]
            ],
        }
        route = {
            "changed": False,
            "path": path,
            "readback": readback,
            "background_readback": {**readback, "nodes": ["h2", *path, "h4"]},
            "policy": {"source": "offline fixture only"},
            "actual_action": observation["previous_action"],
            "requested_action_ignored": request.action,
        }
        route["background_readback"]["kernel_routes"] = [
            {"node": node, "route": {"dev": "fixture-eth0"}}
            for node in route["background_readback"]["nodes"][:-1]
        ]
        if request.mode == "matched":
            paths = {}
            for source, destination in (("h1", "h3"), ("h3", "h1"), ("h2", "h4"), ("h4", "h2")):
                inner = path if source in ("h1", "h3") else ACTION_MAP[0]
                inner = inner[::-1] if source in ("h3", "h4") else inner
                nodes = [source, *inner, destination]
                paths[f"{source}->{destination}"] = {
                    "nodes": nodes,
                    "action": observation["previous_action"],
                    "kernel_routes": [
                        {"node": node, "route": {"dev": "fixture-eth0"}} for node in nodes[:-1]
                    ],
                }
            paths["h2->h4"]["action"] = 0
            owned = {}
            for node in path:
                for table, source, destination in (
                    (19110, "10.78.8.2", "10.78.10.2"),
                    (19111, "10.78.10.2", "10.78.8.2"),
                ):
                    owned[f"{node}:{table}"] = {
                        "rules": [
                            {"priority": table, "table": table, "src": source, "dst": destination}
                        ],
                        "routes": [
                            {
                                "dst": destination,
                                "dev": "fixture-eth0",
                                "gateway": "10.78.1.1",
                                "protocol": "static",
                            }
                        ],
                    }
            route["readback"] = {"owned": owned, "paths": paths}
            route.pop("background_readback")
    capacityReadback = [
        {
            "interface": port,
            "capacity_mbps": observation["path_capacity_mbps"][i],
            "classes": [
                {
                    "kind": "htb",
                    "handle": "5:1",
                    "options": {
                        "rate": observation["path_capacity_mbps"][i] * 1e6 / 8,
                        "ceil": observation["path_capacity_mbps"][i] * 1e6 / 8,
                    },
                }
            ],
        }
        for i, ports in enumerate(PATH_PORTS)
        for port in ports
    ]
    drain = {}
    if spec["version"] == 4:
        from nanfo_routing.drain import INTERFACES

        begin = 100.0 + duration
        sweeps = []
        for offset in (0.05, 0.2):
            queuesDrain = {
                port: {
                    "backlog_packets": 0,
                    "backlog_bytes": 0,
                    "monotonic_seconds": begin + offset,
                    "raw_leaf_qdiscs": [
                        {"kind": "netem", "handle": "10:", "qlen": 0, "backlog": 0}
                    ],
                }
                for port in INTERFACES
            }
            sweeps.append(
                {"start": begin + offset, "end": begin + offset + 0.01, "queues": queuesDrain}
            )
        drain = {
            "drain_begin": begin,
            "drain_end": begin + 0.3,
            "drain_duration_seconds": 0.3,
            "drain_status": "verified_empty",
            "drain_error": None,
            "drain_queue_interfaces": sorted(INTERFACES),
            "drain_sweeps": 2,
            "drain_empty_observations": sweeps,
            "queue_begin": deepcopy(sweeps[0]["queues"]),
            "queue_end": deepcopy(sweeps[1]["queues"]),
            "late_received_packets": [None, None],
            "late_received_unavailable_reason": (
                "workers publish final totals only; no drain-begin counter"
            ),
            "senders_stopped_monotonic_seconds": begin,
        }
    return {
        **drain,
        "source": "OFFLINE UNIT FIXTURE ONLY",
        "provenance": {"source_sha256": spec["source_sha256"], "lab_image_id": None},
        "environment_spec": spec,
        "spec_hash": hashlib.sha256(jsonBytes(spec)).hexdigest(),
        "phase": {
            "phase_index": index,
            "background_path": 0,
            "path_capacity_mbps": observation["path_capacity_mbps"],
            "offered_mbps": observation["offered_mbps"],
            "background_mbps": observation["background_mbps"],
        },
        "phase_relationship": {
            "action_observation_phase_index": index - 1 if index else None,
            "measurement_phase_index": index,
            "workload_advanced_before_action": False,
            "state_and_reward_share_measurement": True,
        },
        "measurement_complete": True,
        "capacity_readback": capacityReadback,
        "capacity_readback_end": deepcopy(capacityReadback),
        "service_outage": False,
        "latency_censored": False,
        "latency_timeout_ms": None,
        "error": None,
        "cleanup_verified": True,
        "desired_window_seconds": request.window_seconds,
        "measured_window_seconds": request.window_seconds,
        "post_control_interval": {"start": start, "end": end},
        "control_start_monotonic_seconds": 100.5,
        "control_overhead_seconds": 0.5,
        "initial_window": index == 0,
        "decision_windows": index,
        "transition_traffic_included": True,
        "udp_sent": sent,
        "udp_received": received,
        "actual_offered_mbps": rates,
        "load_interval_seconds": duration,
        "ping": {
            "sent": 30,
            "received": 30,
            "interval_seconds": duration,
            "rtt_avg_ms": observation["latency_ms"],
            "src_host": "h1",
            "dst_host": "h3",
        },
        "counter_windows": counters,
        "queue_peaks": queues,
        "queue_samples": [4, 4],
        "route": route,
        "route_end": deepcopy(route),
    }


@pytest.fixture
def observation():
    return {
        "path_utilization": [0.8, 0.2],
        "path_queue_packets": [20.0, 0.0],
        "latency_ms": 25.0,
        "loss_fraction": 0.1,
        "goodput_mbps": 5.4,
        "offered_mbps": 6.0,
        "actual_offered_mbps": 6.0,
        "background_mbps": 2.0,
        "path_capacity_mbps": [2.0, 20.0],
        "previous_action": 0,
        "seconds_since_change": 5.0,
    }


class FixtureTransport:
    """Unit-only fake lab, deliberately not shipped in the runtime package."""

    def __init__(self, observation):
        self.observation = deepcopy(observation)
        self.requests = []
        self.mutate = None
        self.counter = 0

    def exchange(self, request):
        self.requests.append(request.model_dump())
        if request.command == "close":
            return {
                "version": 1,
                "ok": True,
                "error": None,
                "data": {
                    "closed": True,
                    "cleanup_verified": True,
                    "episode_id": request.episode_id,
                },
            }
        if request.command == "reset":
            self.counter += 1
        observation = deepcopy(self.observation)
        phase = producerSchedule(
            request.seed, request.scenario, request.episode_steps, mode=request.mode
        )[request.step_index or 0]
        observation.update(
            offered_mbps=phase["offered_mbps"],
            background_mbps=phase["background_mbps"],
            actual_offered_mbps=phase["offered_mbps"],
        )
        observation["previous_action"] = (request.action or 0) if request.mode != "ospf" else 0
        observation["path_capacity_mbps"] = {
            "low": [20.0, 20.0],
            "path0": [2.0, 20.0],
            "path1": [20.0, 2.0],
        }[request.scenario]
        evidence = evidenceFixture(observation, request)
        data = {
            "episode_id": f"00000000-0000-4000-8000-{self.counter:012d}",
            "step_index": request.step_index or 0,
            "mode": request.mode,
            "seed": request.seed,
            "scenario": request.scenario,
            "terminated": request.step_index == request.episode_steps,
            "truncated": False,
            "observation": observation,
            "evidence": evidence,
        }
        raw = {"version": 1, "ok": True, "error": None, "data": data}
        if self.mutate:
            self.mutate(raw)
        return raw


@pytest.fixture
def transport(observation):
    return FixtureTransport(observation)
