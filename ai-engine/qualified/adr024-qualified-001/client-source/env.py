"""Gym state/reward adapter. Invalid windows are never training transitions."""

import gymnasium as gym
import numpy as np

from .contracts import (
    CONTRACT,
    HEURISTIC_HYSTERESIS,
    HISTORY_LENGTH,
    REWARD_SCALES,
    REWARD_WEIGHTS,
    SCALES,
    STATE_DIM,
    Observation,
    Request,
    Response,
    validateSeed,
)
from .evidence import validateMeasurement
from .transport import Transport, TransportError


class InvalidMeasurement(RuntimeError):
    pass


def encode(history: list[Observation]) -> np.ndarray:
    if not 1 <= len(history) <= HISTORY_LENGTH:
        raise ValueError("state requires exactly one stationary observed frame")
    frames = []
    for observation in [history[0]] * (HISTORY_LENGTH - len(history)) + history:
        metrics = observation.metrics()
        values = [
            0.0 if value is None else np.log1p(value / scale)
            for value, scale in zip(metrics, SCALES, strict=True)
        ]
        frames.extend(
            [
                *values,
                float(observation.latency_ms is not None),
                float(observation.previous_action == 0),
                float(observation.previous_action == 1),
            ]
        )
    return np.asarray(frames, dtype=np.float32)


def rewardComponents(observation: Observation, previous: int, *, censoredDelay=None) -> dict:
    if censoredDelay is not None and (
        censoredDelay != CONTRACT["censored_delay_ms"] or observation.latency_ms is not None
    ):
        raise InvalidMeasurement("invalid censored delay penalty")
    if not observation.complete(censored=censoredDelay is not None):
        raise InvalidMeasurement("reward requires complete measured window")
    raw = {
        "goodput_ratio": min(observation.goodput_mbps / observation.actual_offered_mbps, 1.0),
        "delay": (censoredDelay if censoredDelay is not None else observation.latency_ms)
        / REWARD_SCALES["delay_ms"],
        "loss": observation.loss_fraction,
        "utilization": max(observation.path_utilization),
        "queue": max(observation.path_queue_packets) / REWARD_SCALES["queue_packets"],
        "route_change": float(observation.previous_action != previous),
    }
    contributions = {key: value * REWARD_WEIGHTS[key] for key, value in raw.items()}
    return {
        "version": 3,
        "delay_censored": censoredDelay is not None,
        "observed_latency_ms": observation.latency_ms,
        "censored_delay_penalty_ms": censoredDelay,
        "raw": raw,
        "contributions": contributions,
        "total": sum(contributions.values()),
    }


def heuristic(observation: Observation, hysteresis: float = HEURISTIC_HYSTERESIS) -> int:
    if not observation.complete(censored=True) or not 0 <= hysteresis <= 1:
        raise InvalidMeasurement("heuristic requires valid measured pressure")
    pressure = [
        util + queue / 100.0
        for util, queue in zip(
            observation.path_utilization, observation.path_queue_packets, strict=True
        )
    ]
    current = observation.previous_action
    return 1 - current if pressure[current] - pressure[1 - current] > hysteresis else current


class RoutingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        transport: Transport,
        *,
        split="train",
        scenario="path0",
        mode="matched",
        window_seconds=5.0,
        episode_steps=16,
        expectedSpec=None,
    ):
        self.transport = transport
        self.split = split
        validateSeed(split, {"train": 1000, "validation": 2000, "test": 3000}.get(split, -1))
        self.template = Request(
            command="reset",
            seed={"train": 1000, "validation": 2000, "test": 3000}[split],
            scenario=scenario,
            mode=mode,
            window_seconds=window_seconds,
            episode_steps=episode_steps,
        )
        self.action_space = gym.spaces.Discrete(2)
        self.observation_space = gym.spaces.Box(0.0, np.inf, shape=(STATE_DIM,), dtype=np.float32)
        self.data = None
        self.active = False
        self.lastResponse = None
        self.contacted = False
        self.failed = False
        self.history = []
        self.historyEvidence = []
        self.environmentSpec = expectedSpec
        self.labProvenance = None

    def _exchange(self, request):
        self.lastResponse = None
        self.contacted = True
        raw = self.transport.exchange(request)
        self.lastResponse = raw
        response = Response.model_validate(raw)
        if not response.ok:
            raise InvalidMeasurement(response.error)
        data = response.data
        if (data.mode, data.seed, data.scenario) != (request.mode, request.seed, request.scenario):
            raise InvalidMeasurement("measurement context mismatch")
        if request.command == "step" and (data.episode_id, data.step_index) != (
            request.episode_id,
            request.step_index,
        ):
            raise InvalidMeasurement("stale or out-of-order measurement")
        if request.command == "reset" and data.step_index != 0:
            raise InvalidMeasurement("reset must return step zero")
        return data

    def reset(self, *, seed=None, options=None):
        if self.failed:
            raise InvalidMeasurement("failed session cannot reset; close and inspect lab ownership")
        if self.active:
            raise InvalidMeasurement("close active episode before reset")
        if options:
            raise ValueError("reset options unsupported; configure the environment explicitly")
        validateSeed(self.split, seed)
        super().reset(seed=seed)
        request = self.template.model_copy(update={"seed": seed})
        try:
            data = self._exchange(request)
        except (ValueError, RuntimeError):
            self.failed = True
            raise
        self.data = data
        try:
            spec = validateMeasurement(data, request)
            if self.environmentSpec is not None and spec != self.environmentSpec:
                raise InvalidMeasurement("lab spec changed or differs from checkpoint")
            self.environmentSpec = spec
            self.labProvenance = data.evidence["provenance"]
        except ValueError as exc:
            self.failed = True
            raise InvalidMeasurement(str(exc)) from exc
        if (
            data.terminated
            or data.truncated
            or not data.observation.complete(censored=data.evidence["service_outage"])
            or data.evidence.get("error")
            or data.evidence.get("cleanup_verified") is False
        ):
            self.failed = True
            raise InvalidMeasurement("invalid initial measured window")
        self.active = True
        self.history = [data.observation]
        self.historyEvidence = [{"request": request.model_dump(), "response": self.lastResponse}]
        return encode(self.history), self._info(True)

    def _info(self, valid, **extra):
        return {"valid_transition": valid, "raw_response": self.lastResponse, **extra}

    def step(self, action):
        if not self.active:
            raise InvalidMeasurement("reset required before step")
        if not self.action_space.contains(action) or isinstance(action, bool):
            raise ValueError("action must be 0 or 1")
        previous = self.data.observation.previous_action
        request = self.template.model_copy(
            update={
                "command": "step",
                "episode_id": self.data.episode_id,
                "step_index": self.data.step_index + 1,
                "seed": self.data.seed,
                "action": int(action),
            }
        )
        try:
            data = self._exchange(request)
            self.data = data
            spec = validateMeasurement(data, request)
            if spec != self.environmentSpec:
                raise InvalidMeasurement("lab spec changed within session")
            if data.evidence["provenance"] != self.labProvenance:
                raise InvalidMeasurement("lab provenance changed within session")
            if any(
                getattr(data.observation, key) != getattr(self.history[-1], key)
                for key in ("offered_mbps", "background_mbps", "path_capacity_mbps")
            ):
                raise InvalidMeasurement("exogenous inputs changed within stationary episode")
            if self.template.mode != "ospf" and data.observation.previous_action != int(action):
                raise InvalidMeasurement("measured route differs from requested action")
            # The lab marks its fixed schedule end terminated. It is a Gym time limit,
            # not an absorbing network state. Lab truncations always mean invalid windows.
            horizon = data.step_index == self.template.episode_steps
            if data.terminated != horizon:
                raise InvalidMeasurement("termination must match the fixed episode horizon")
            if (
                data.truncated
                or data.evidence.get("error")
                or data.evidence.get("cleanup_verified") is False
            ):
                raise InvalidMeasurement("lab truncated or failed measured window")
            components = rewardComponents(
                data.observation, previous, censoredDelay=data.evidence["latency_timeout_ms"]
            )
            terminated, truncated = data.terminated and not horizon, horizon
            self.active = not (terminated or truncated)
            self.history = [*self.history, data.observation][-HISTORY_LENGTH:]
            self.historyEvidence = [
                *self.historyEvidence,
                {
                    "request": request.model_dump(),
                    "response": self.lastResponse,
                },
            ][-HISTORY_LENGTH:]
            return (
                encode(self.history),
                components["total"],
                terminated,
                truncated,
                self._info(True, reward=components, time_limit=horizon),
            )
        except (ValueError, InvalidMeasurement, TransportError) as exc:
            self.active = False
            self.failed = True
            # NaN is a deliberate non-reward sentinel, never a fabricated zero reward.
            return (
                encode(self.history),
                float("nan"),
                False,
                True,
                self._info(False, reward=None, error=str(exc)[:2048], time_limit=False),
            )

    def close(self):
        if self.contacted:
            request = self.template.model_copy(
                update={
                    "command": "close",
                    "episode_id": self.data.episode_id if self.data else None,
                    "step_index": self.data.step_index if self.data else None,
                    "seed": self.data.seed if self.data else None,
                    "scenario": self.data.scenario if self.data else None,
                }
            )
            raw = self.transport.exchange(request)
            # Close has no measurement data; validate its exact wire envelope separately.
            if (
                type(raw) is not dict
                or set(raw) != {"version", "ok", "error", "data"}
                or type(raw["version"]) is not int
                or raw["version"] != 1
                or raw["ok"] is not True
                or raw["error"] is not None
                or type(raw["data"]) is not dict
                or raw["data"].get("closed") is not True
                or raw["data"].get("cleanup_verified") is not True
                or set(raw["data"]) != {"closed", "cleanup_verified", "episode_id"}
                or raw["data"].get("episode_id") != (self.data.episode_id if self.data else None)
            ):
                raise TransportError("experiment cleanup not acknowledged; inspect lab ownership")
            self.data = None
            self.contacted = False
        self.active = False
