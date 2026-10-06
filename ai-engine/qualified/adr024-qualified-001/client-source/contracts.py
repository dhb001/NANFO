"""Strict ADR011 wire schema and frozen state/reward contract."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def integerLiterals(cls, value):
        if type(value) is dict:
            for key in ("version", "action", "previous_action"):
                if key in value and value[key] is not None and type(value[key]) is not int:
                    raise ValueError(f"{key} must be an integer, not bool or float")
        return value


Nonnegative = Annotated[float, Field(ge=0, le=1e9)]
Fraction = Annotated[float, Field(ge=0, le=1)]
Identity = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
Scenario = Literal["low", "path0", "path1", "alternating", "burst", "overload"]
SCENARIOS = ("low", "path0", "path1", "alternating", "burst", "overload")
SPLITS = {"train": [1000, 1999], "validation": [2000, 2999], "test": [3000, 3999]}


def validateSeed(split: str, seed: int) -> int:
    if (
        split not in SPLITS
        or type(seed) is not int
        or not SPLITS[split][0] <= seed <= SPLITS[split][1]
    ):
        raise ValueError("seed is outside its frozen split")
    return seed


class Request(StrictModel):
    version: Literal[1] = 1
    command: Literal["reset", "step", "close"]
    episode_id: Identity | None = None
    step_index: Annotated[int, Field(ge=0, le=64)] | None = None
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] | None = None
    scenario: Scenario | None = None
    action: Literal[0, 1] | None = None
    mode: Literal["sdn", "ospf", "matched"] = "matched"
    window_seconds: Annotated[float, Field(ge=2, le=10)] = 5.0
    episode_steps: Annotated[int, Field(ge=2, le=64)] = 16

    @model_validator(mode="after")
    def commandFields(self):
        if self.command == "reset":
            if self.seed is None or self.scenario is None:
                raise ValueError("reset requires seed and scenario")
            if any(x is not None for x in (self.episode_id, self.step_index, self.action)):
                raise ValueError("reset cannot carry transition identity or action")
        elif self.command == "step":
            if self.episode_id is None or self.step_index is None or self.action is None:
                raise ValueError("step requires identity, index and action")
            if not 1 <= self.step_index <= self.episode_steps:
                raise ValueError("step index exceeds episode")
        elif self.action is not None or (self.episode_id is None) != (self.step_index is None):
            raise ValueError("close requires paired identity/index and no action")
        return self


class Observation(StrictModel):
    path_capacity_mbps: Annotated[
        list[Annotated[float, Field(gt=0, le=100)] | None], Field(min_length=2, max_length=2)
    ]
    path_utilization: Annotated[list[Nonnegative | None], Field(min_length=2, max_length=2)]
    path_queue_packets: Annotated[list[Nonnegative | None], Field(min_length=2, max_length=2)]
    latency_ms: Nonnegative | None
    loss_fraction: Fraction | None
    goodput_mbps: Nonnegative | None
    offered_mbps: Annotated[float, Field(gt=0, le=1e9)]
    actual_offered_mbps: Annotated[float, Field(gt=0, le=1e9)] | None
    background_mbps: Nonnegative
    previous_action: Literal[0, 1]
    seconds_since_change: Nonnegative

    def complete(self, *, censored=False) -> bool:
        return all(
            value is not None or (censored and index == 4)
            for index, value in enumerate(self.metrics())
        )

    def metrics(self) -> list[float | None]:
        return [
            *self.path_utilization,
            *self.path_queue_packets,
            self.latency_ms,
            self.loss_fraction,
            self.goodput_mbps,
            self.offered_mbps,
            self.background_mbps,
            self.seconds_since_change,
            self.actual_offered_mbps,
            *self.path_capacity_mbps,
        ]


class Data(StrictModel):
    episode_id: Identity
    step_index: Annotated[int, Field(ge=0, le=64)]
    mode: Literal["sdn", "ospf", "matched"]
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)]
    scenario: Scenario
    terminated: bool
    truncated: bool
    observation: Observation
    evidence: dict

    @model_validator(mode="after")
    def evidenceJson(self):
        # ADR011 leaves evidence keys extensible; bound and validate its JSON tree.
        validateJson(self.evidence)
        if not self.evidence:
            raise ValueError("measurement evidence is required")
        return self


class Response(StrictModel):
    version: Literal[1]
    ok: bool
    error: Annotated[str, Field(max_length=2048)] | None
    data: Data | None

    @model_validator(mode="after")
    def envelope(self):
        if self.ok != (self.data is not None) or self.ok != (self.error is None):
            raise ValueError("inconsistent response envelope")
        return self


def validateJson(value, depth=0):
    if depth > 16:
        raise ValueError("JSON nesting limit")
    if type(value) is dict:
        if len(value) > 2048 or any(type(key) is not str for key in value):
            raise ValueError("invalid JSON object")
        for item in value.values():
            validateJson(item, depth + 1)
    elif type(value) is list:
        if len(value) > 4096:
            raise ValueError("JSON array limit")
        for item in value:
            validateJson(item, depth + 1)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ValueError("not a JSON type")
    json.dumps(value, allow_nan=False)


NODES = ["core", "dist1", "dist2", "access1", "access2"]
ADJACENCY = [[0, 1, 1, 0, 0], [1, 0, 1, 1, 1], [1, 1, 0, 1, 1], [0, 1, 1, 0, 0], [0, 1, 1, 0, 0]]
ACTION_MAP = [["access1", "dist1", "access2"], ["access1", "dist2", "access2"]]
FEATURES = [
    "util0",
    "util1",
    "queue0",
    "queue1",
    "latency_ms",
    "loss_fraction",
    "goodput_mbps",
    "offered_mbps",
    "background_mbps",
    "seconds_since_change",
    "actual_offered_mbps",
    "capacity0_mbps",
    "capacity1_mbps",
]
SCALES = [1.0, 1.0, 100.0, 100.0, 50.0, 1.0, 20.0, 20.0, 20.0, 10.0, 20.0, 20.0, 20.0]
REWARD_WEIGHTS = {
    "goodput_ratio": 1.0,
    "delay": -0.2,
    "loss": -1.0,
    "utilization": -0.1,
    "queue": -0.1,
    "route_change": -0.05,
}
REWARD_SCALES = {"delay_ms": 50.0, "queue_packets": 100.0}
HEURISTIC_HYSTERESIS = 0.15
HISTORY_LENGTH = 1
FRAME_DIM = len(FEATURES) + 1 + 2
STATE_DIM = HISTORY_LENGTH * FRAME_DIM
CONTRACT = {
    "version": 3,
    "topology_id": "campus-small-v1",
    "nodes": NODES,
    "adjacency": ADJACENCY,
    "action_map": ACTION_MAP,
    "link_endpoints": [
        ["core", "dist1"],
        ["core", "dist2"],
        ["dist1", "dist2"],
        ["dist1", "access1"],
        ["dist2", "access1"],
        ["dist1", "access2"],
        ["dist2", "access2"],
    ],
    "link_capacity_mbps": [100, 100, 50, 20, 20, 20, 20],
    "link_delay_ms": [2, 2, 3, 5, 5, 5, 5],
    "queue_capacity_packets": 100,
    "host_attachments": {"h1": "access1", "h2": "access1", "h3": "access2", "h4": "access2"},
    "host_link_capacity_mbps": 100,
    "host_link_delay_ms": 1,
    "foreground": ["h1", "h3"],
    "background": ["h2", "h4"],
    "features": FEATURES,
    "scales": SCALES,
    "state_dim": STATE_DIM,
    "frame_dim": FRAME_DIM,
    "history_length": HISTORY_LENGTH,
    "history_padding": "repeat earliest observed frame at episode start",
    "layout": (
        "single stationary frame: log1p(features/scales),latency_available,previous_action.onehot"
    ),
    "observability": (
        "stationary exogenous inputs; no future phase/seed/scenario inputs; not a safety guarantee"
    ),
    "architecture": "separate actor/critic Linear(16,32)-Tanh heads; orthogonal actor gain 0.01",
    "reward_weights": REWARD_WEIGHTS,
    "reward_scales": REWARD_SCALES,
    "reward_goodput_ratio_cap": 1.0,
    "reward_goodput_denominator": "actual_offered_mbps from foreground sent bytes/duration",
    "censored_delay_ms": 1000.0,
    "censored_delay_semantics": (
        "penalty only for verified zero-reply outage; observed RTT stays null"
    ),
    "heuristic_hysteresis": HEURISTIC_HYSTERESIS,
    "splits": SPLITS,
    "scenarios": list(SCENARIOS),
}


def jsonBytes(value) -> bytes:
    validateJson(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def parseJson(content):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=pairs)
        validateJson(value)
        return value
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("invalid JSON encoding or nesting") from exc


CONTRACT_HASH = hashlib.sha256(jsonBytes(CONTRACT)).hexdigest()
