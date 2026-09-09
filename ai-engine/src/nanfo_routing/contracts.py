"""Strict ADR011 wire schema and frozen state/reward contract."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)


Nonnegative = Annotated[float, Field(ge=0, le=1e9)]
Fraction = Annotated[float, Field(ge=0, le=1)]
Identity = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
Scenario = Literal["low", "path0", "path1", "alternating", "burst", "overload"]
SCENARIOS = ("low", "path0", "path1", "alternating", "burst", "overload")
SPLITS = {"train": [1000, 1999], "validation": [2000, 2999], "test": [3000, 3999]}


def validateSeed(split: str, seed: int) -> int:
    if split not in SPLITS or type(seed) is not int or not SPLITS[split][0] <= seed <= SPLITS[split][1]:
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
    mode: Literal["sdn", "ospf"] = "sdn"
    window_seconds: Annotated[float, Field(ge=2, le=10)] = 5.0
    episode_steps: Annotated[int, Field(ge=2, le=64)] = 16


class Observation(StrictModel):
    path_utilization: Annotated[list[Nonnegative | None], Field(min_length=2, max_length=2)]
    path_queue_packets: Annotated[list[Nonnegative | None], Field(min_length=2, max_length=2)]
    latency_ms: Nonnegative | None
    loss_fraction: Fraction | None
    goodput_mbps: Nonnegative | None
    offered_mbps: Annotated[float, Field(gt=0, le=1e9)]
    background_mbps: Nonnegative
    previous_action: Literal[0, 1]
    seconds_since_change: Nonnegative

    def complete(self) -> bool:
        return all(value is not None for value in self.metrics())

    def metrics(self) -> list[float | None]:
        return [*self.path_utilization, *self.path_queue_packets, self.latency_ms,
                self.loss_fraction, self.goodput_mbps, self.offered_mbps,
                self.background_mbps, self.seconds_since_change]


class Data(StrictModel):
    episode_id: Identity
    step_index: Annotated[int, Field(ge=0, le=64)]
    mode: Literal["sdn", "ospf"]
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
ADJACENCY = [[0, 1, 1, 0, 0], [1, 0, 1, 1, 1], [1, 1, 0, 1, 1],
             [0, 1, 1, 0, 0], [0, 1, 1, 0, 0]]
ACTION_MAP = [["access1", "dist1", "access2"], ["access1", "dist2", "access2"]]
FEATURES = ["util0", "util1", "queue0", "queue1", "latency_ms", "loss_fraction",
            "goodput_mbps", "offered_mbps", "background_mbps", "seconds_since_change"]
SCALES = [1.0, 1.0, 100.0, 100.0, 50.0, 1.0, 20.0, 20.0, 20.0, 10.0]
REWARD_WEIGHTS = {"goodput_ratio": 1.0, "delay": -0.2, "loss": -1.0,
                  "utilization": -0.1, "queue": -0.1, "route_change": -0.05}
STATE_DIM = 25 + len(FEATURES) * 2 + 2
CONTRACT = {
    "version": 1, "topology_id": "campus-small-v1", "nodes": NODES,
    "adjacency": ADJACENCY, "action_map": ACTION_MAP,
    "link_capacity_mbps": [100, 100, 50, 20, 20, 20, 20],
    "link_delay_ms": [2, 2, 3, 5, 5, 5, 5], "queue_capacity_packets": 100,
    "features": FEATURES, "scales": SCALES, "state_dim": STATE_DIM,
    "layout": "adjacency.rowmajor,features,finiteness_masks,previous_action.onehot",
    "reward_weights": REWARD_WEIGHTS, "reward_goodput_ratio_cap": 1.0,
    "splits": SPLITS, "scenarios": list(SCENARIOS),
}


def jsonBytes(value) -> bytes:
    validateJson(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


CONTRACT_HASH = hashlib.sha256(jsonBytes(CONTRACT)).hexdigest()
