"""V5 semantic adapter over unchanged, hash-verified raw telemetry checks.

No V5 response/spec/scenario is rewritten into a V4 response. The frozen validator
was monolithic: its two pure measurement blocks are compiled unchanged from the
verified source AST (capacity readback; timings/UDP/ping/queues/routes). Its V3
schedule and spec admission are NOT reused. Drain is invoked explicitly for V5.
"""

import ast
import hashlib
import random
import types
from typing import Literal

from frozen import ORIGINAL, module
from plan import PROFILES

c = module("contracts")
old = module("evidence")
Profile = Literal[
    "balanced", "moderate0", "moderate1", "severe0", "severe1", "overload", "path0", "path1"
]


class Request(c.Request):
    scenario: Profile | None = None
    mode: Literal["matched", "ospf"] = "matched"


class Data(c.Data):
    scenario: Profile
    mode: Literal["matched", "ospf"]


class Response(c.Response):
    data: Data | None


def measurementKernel():
    source = ORIGINAL / "source/evidence.py"
    if hashlib.sha256(source.read_bytes()).hexdigest() != (
        "f6ebe061a5a02bf74df6e7d1f2453664a574328d04d4e3557b679e139d8c30ff"
    ):
        raise ValueError("frozen measurement kernel source differs")
    tree = ast.parse(source.read_text())
    function = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "validateMeasurement"
    )
    original = function.body[1].body
    # These exact immutable blocks take expectedCapacity and validated V5 data.
    body = [n for n in original if 148 <= n.lineno <= 437]
    if body[0].lineno != 148 or body[-1].lineno != 437:
        raise ValueError("frozen measurement block boundaries differ")
    args = ast.arguments(
        posonlyargs=[],
        args=[ast.arg(arg=n) for n in ("data", "request", "e", "o", "phase", "expectedCapacity")],
        kwonlyargs=[],
        kw_defaults=[],
        defaults=[],
    )
    definition = ast.FunctionDef(name="rawKernel", args=args, body=body, decorator_list=[])
    namespace = vars(old).copy()
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[])),
            str(source) + ":unchanged-raw-kernel",
            "exec",
        ),
        namespace,
    )
    return namespace["rawKernel"]


KERNEL = measurementKernel()


def phase(seed, scenario, index, spec):
    if type(seed) is not int or not 0 <= seed <= 2147483647 or scenario not in PROFILES:
        raise ValueError("invalid V5 seed/profile")
    profile = spec["profiles"][scenario]
    rng = random.Random(seed)
    offered = round(rng.uniform(*profile["offered_mbps"]), 3)
    background = round(rng.uniform(*profile["background_mbps"]), 3)
    capacities = [None, None]
    for path in profile["capacity_draw_order"]:
        choices = profile["path_capacity_mbps"][path]
        capacities[path] = choices[0] if len(choices) == 1 else rng.choice(choices)
    return {
        "phase_index": index,
        "background_path": 0,
        "offered_mbps": offered,
        "background_mbps": background,
        "path_capacity_mbps": capacities,
    }


class Transport(module("transport").DockerTransport):
    # Reuse bounded argv/selector/timeout implementation, explicitly replacing ONLY
    # wire scenario typing with V5 Request. No measurement/metadata source bypass.
    original = module("transport").DockerTransport.exchange
    exchange = types.FunctionType(
        original.__code__,
        {**original.__globals__, "Request": Request},
        "v5Exchange",
        original.__defaults__,
    )


def validateSpec(spec, expected):
    if c.jsonBytes(spec) != c.jsonBytes(expected) or spec.get("version") != 5:
        raise ValueError("V5 spec differs from inspected released semantic contract")
    for key, value in module("drain").SEMANTICS.items():
        if key != "version" and spec.get(key) != value:
            raise ValueError("V5 changed verified drain semantics")
    if not set(PROFILES).issubset(spec.get("scenarios", [])):
        raise ValueError("released V5 lacks declared profiles")
    required = {
        "name": "nanfo-matched-stationary-routing",
        "schedule_version": "seeded-stationary-profiles-v5",
        "phase_relationship": (
            "episode capacities and demands fixed before reset through all decisions"
        ),
        "actor_inputs": (
            "measured observation history and actual HTB path capacities only; "
            "no seed/scenario/index"
        ),
        "control_version": "source-specific-linux-policy-routing-and-end-readback-v3",
        "modes": ["matched", "ospf"],
        "goodput_ratio": "received foreground bytes / actual foreground sent bytes",
        "ping_timeout_ms": 1000,
        "generator_relative_tolerance": 0.2,
        "window_bounds_seconds": [2, 10],
        "window_overrun_tolerance_seconds": 2,
    }
    if any(spec.get(key) != value for key, value in required.items()):
        raise ValueError("unsupported V5 measured feature/control semantics")
    sources = spec["source_files"]
    if hashlib.sha256(c.jsonBytes(sources)).hexdigest() != spec["source_sha256"]:
        raise ValueError("V5 source map digest mismatch")


def validate(raw, request, release, expectedPhase):
    response = Response.model_validate(raw)
    if not response.ok:
        raise ValueError(response.error)
    data = response.data
    e, o = data.evidence, data.observation
    validateSpec(e["environment_spec"], release["environment_spec"])
    if (
        e["spec_hash"] != release["spec_hash"]
        or hashlib.sha256(c.jsonBytes(e["environment_spec"])).hexdigest() != e["spec_hash"]
        or e["provenance"]
        != {
            "source_sha256": release["environment_spec"]["source_sha256"],
            "lab_image_id": release["image_id"],
        }
    ):
        raise ValueError("V5 measurement provenance mismatch")
    if (
        data.truncated
        or e.get("error") is not None
        or e["measurement_complete"] is not True
        or e.get("cleanup_verified") is False
        or data.terminated != (data.step_index == request.episode_steps)
        or data.step_index != (request.step_index or 0)
        or (data.mode, data.seed, data.scenario) != (request.mode, request.seed, request.scenario)
        or (request.command == "step" and data.episode_id != request.episode_id)
        or (data.terminated and e.get("cleanup_verified") is not True)
    ):
        raise ValueError("invalid V5 measurement context/completion/horizon")
    if (
        c.jsonBytes(e["phase"]) != c.jsonBytes(expectedPhase)
        or o.path_capacity_mbps != expectedPhase["path_capacity_mbps"]
        or o.offered_mbps != expectedPhase["offered_mbps"]
        or o.background_mbps != expectedPhase["background_mbps"]
    ):
        raise ValueError("V5 phase differs from exact seed-derived stationary profile")
    module("drain").validateDrain(e)
    KERNEL(data, request, e, o, e["phase"], expectedPhase["path_capacity_mbps"])
    routingHealth(data)
    return data


def routingHealth(data):
    e = data.evidence
    neighbors = {
        "core": [("dist1", 1), ("dist2", 2)],
        "dist1": [("core", 1), ("dist2", 2), ("access1", 3), ("access2", 4)],
        "dist2": [("core", 1), ("dist1", 2), ("access1", 3), ("access2", 4)],
        "access1": [("dist1", 1), ("dist2", 2)],
        "access2": [("dist1", 1), ("dist2", 2)],
    }
    ids = {name: f"10.255.0.{i}" for i, name in enumerate(neighbors, 1)}
    for key in ("routing_health_start", "routing_health_end"):
        health = e[key]
        begin, end = old.number(health["start"]), old.number(health["end"])
        if set(health) != {"start", "end", "neighbors", "paths"} or begin > end:
            raise ValueError("invalid routing health envelope/timing")
        if key.endswith("start"):
            if end > min(s["started_monotonic_seconds"] for s in e["udp_sent"]):
                raise ValueError("start health not before load")
        elif begin < e["post_control_interval"]["end"] or end > min(
            s["finished_monotonic_seconds"] for s in e["udp_sent"]
        ):
            raise ValueError("end health not measured under load")
        if set(health["neighbors"]) != set(neighbors):
            raise ValueError("missing router neighbor evidence")
        for router, peers in neighbors.items():
            observed = []
            for identity, rows in health["neighbors"][router]["neighbors"].items():
                for row in rows:
                    if not row["state"].startswith("Full/"):
                        raise ValueError("non-Full adjacency")
                    observed.append((identity, row["ifaceName"].split(":")[0]))
            expected = {(ids[peer], f"{router}-eth{port}") for peer, port in peers}
            if set(observed) != expected or len(observed) != len(expected):
                raise ValueError("neighbor identities/interfaces differ")
        pairs = [("h1", "h3"), ("h3", "h1"), ("h2", "h4"), ("h4", "h2")]
        if set(health["paths"]) != {f"{s}->{d}" for s, d in pairs}:
            raise ValueError("missing bidirectional health routes")
        for source, destination in pairs:
            route = health["paths"][f"{source}->{destination}"]
            action = route["action"]
            if type(action) is not int or action not in (0, 1):
                raise ValueError("invalid health route action")
            if source in ("h2", "h4") or data.mode == "ospf":
                if action != 0:
                    raise ValueError("nominal OSPF/background path drift")
            elif key.endswith("end") and action != data.observation.previous_action:
                raise ValueError("end health foreground differs from action")
            inner = c.ACTION_MAP[action]
            nodes = [source, *(inner if source < destination else inner[::-1]), destination]
            if route["nodes"] != nodes or len(route["kernel_routes"]) != len(nodes) - 1:
                raise ValueError("health kernel path differs")
            for hop, node in zip(route["kernel_routes"], nodes[:-1], strict=True):
                if hop["node"] != node or not hop["route"].get("dev"):
                    raise ValueError("missing health kernel hop")
