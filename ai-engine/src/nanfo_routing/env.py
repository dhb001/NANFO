"""Gym state/reward adapter. Invalid windows are never training transitions."""

import gymnasium as gym
import numpy as np

from .contracts import (
    ADJACENCY, REWARD_WEIGHTS, SCALES, STATE_DIM, Observation, Request, Response, validateSeed,
)
from .transport import Transport, TransportError


class InvalidMeasurement(RuntimeError):
    pass


def encode(observation: Observation) -> np.ndarray:
    metrics = observation.metrics()
    mask = [float(value is not None) for value in metrics]
    values = [0.0 if value is None else value / scale
              for value, scale in zip(metrics, SCALES, strict=True)]
    return np.asarray([*np.asarray(ADJACENCY).flatten(), *values, *mask,
                       float(observation.previous_action == 0),
                       float(observation.previous_action == 1)], dtype=np.float32)


def rewardComponents(observation: Observation, previous: int) -> dict:
    if not observation.complete():
        raise InvalidMeasurement("reward requires complete measured window")
    raw = {
        "goodput_ratio": min(observation.goodput_mbps / observation.offered_mbps, 1.0),
        "delay": observation.latency_ms / 50.0,
        "loss": observation.loss_fraction,
        "utilization": max(observation.path_utilization),
        "queue": max(observation.path_queue_packets) / 100.0,
        "route_change": float(observation.previous_action != previous),
    }
    contributions = {key: value * REWARD_WEIGHTS[key] for key, value in raw.items()}
    return {"version": 1, "raw": raw, "contributions": contributions,
            "total": sum(contributions.values())}


def heuristic(observation: Observation, hysteresis: float = 0.1) -> int:
    if not observation.complete() or not 0 <= hysteresis <= 1:
        raise InvalidMeasurement("heuristic requires valid measured pressure")
    pressure = [util + queue / 100.0 for util, queue in
                zip(observation.path_utilization, observation.path_queue_packets, strict=True)]
    current = observation.previous_action
    return 1 - current if pressure[current] - pressure[1 - current] > hysteresis else current


class RoutingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, transport: Transport, *, split="train", scenario="low", mode="sdn",
                 window_seconds=5.0, episode_steps=16):
        self.transport = transport
        self.split = split
        validateSeed(split, {"train": 1000, "validation": 2000, "test": 3000}.get(split, -1))
        self.template = Request(command="reset", scenario=scenario, mode=mode,
                                window_seconds=window_seconds, episode_steps=episode_steps)
        self.action_space = gym.spaces.Discrete(2)
        self.observation_space = gym.spaces.Box(0.0, np.inf, shape=(STATE_DIM,), dtype=np.float32)
        self.data = None
        self.active = False
        self.lastResponse = None

    def _exchange(self, request):
        self.lastResponse = None
        raw = self.transport.exchange(request)
        self.lastResponse = raw
        response = Response.model_validate(raw)
        if not response.ok:
            raise InvalidMeasurement(response.error)
        data = response.data
        if (data.mode, data.seed, data.scenario) != (request.mode, request.seed, request.scenario):
            raise InvalidMeasurement("measurement context mismatch")
        if request.command == "step" and (data.episode_id, data.step_index) != (
                request.episode_id, request.step_index):
            raise InvalidMeasurement("stale or out-of-order measurement")
        if request.command == "reset" and data.step_index != 0:
            raise InvalidMeasurement("reset must return step zero")
        return data

    def reset(self, *, seed=None, options=None):
        if self.active:
            raise InvalidMeasurement("close active episode before reset")
        if options:
            raise ValueError("reset options unsupported; configure the environment explicitly")
        validateSeed(self.split, seed)
        super().reset(seed=seed)
        request = self.template.model_copy(update={"seed": seed})
        data = self._exchange(request)
        self.data = data
        if data.terminated or data.truncated or not data.observation.complete():
            raise InvalidMeasurement("invalid initial measured window")
        self.active = True
        return encode(data.observation), self._info(True)

    def _info(self, valid, **extra):
        return {"valid_transition": valid, "raw_response": self.lastResponse, **extra}

    def step(self, action):
        if not self.active:
            raise InvalidMeasurement("reset required before step")
        if not self.action_space.contains(action) or isinstance(action, bool):
            raise ValueError("action must be 0 or 1")
        previous = self.data.observation.previous_action
        request = self.template.model_copy(update={
            "command": "step", "episode_id": self.data.episode_id,
            "step_index": self.data.step_index + 1, "seed": self.data.seed, "action": int(action),
        })
        try:
            data = self._exchange(request)
            if not data.observation.complete():
                raise InvalidMeasurement("incomplete measured window")
            if self.template.mode == "sdn" and data.observation.previous_action != int(action):
                raise InvalidMeasurement("measured route differs from requested action")
            # A complete horizon observation bootstraps; other truncations are invalid windows.
            horizon = data.step_index == self.template.episode_steps
            if data.truncated and not horizon:
                raise InvalidMeasurement("lab truncated measurement before time limit")
            self.data = data
            components = rewardComponents(data.observation, previous)
            terminated, truncated = data.terminated, data.truncated or horizon
            self.active = not (terminated or truncated)
            return (encode(data.observation), components["total"], terminated, truncated,
                    self._info(True, reward=components, time_limit=horizon))
        except (ValueError, InvalidMeasurement, TransportError) as exc:
            self.active = False
            # NaN is a deliberate non-reward sentinel, never a fabricated zero reward.
            return (encode(self.data.observation), float("nan"), False, True,
                    self._info(False, reward=None, error=str(exc)[:2048], time_limit=False))

    def close(self):
        if self.data is not None:
            request = self.template.model_copy(update={
                "command": "close", "episode_id": self.data.episode_id,
                "step_index": self.data.step_index, "seed": self.data.seed,
            })
            raw = self.transport.exchange(request)
            # Close has no measurement data; validate its exact wire envelope separately.
            if (type(raw) is not dict or set(raw) != {"version", "ok", "error", "data"}
                    or type(raw["version"]) is not int or raw["version"] != 1
                    or raw["ok"] is not True or raw["error"] is not None
                    or (raw["data"] is not None and type(raw["data"]) is not dict)):
                raise TransportError("experiment cleanup not acknowledged; inspect lab ownership")
            self.data = None
        self.active = False
