"""Operator baseline smoke via the same docker-exec JSON transport used by AI."""

import argparse
import json
import subprocess
import time
from pathlib import Path

from emulation.measurements import atomicJson


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--window", type=float, default=5)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--mode", choices=("sdn", "ospf"), default="sdn")
    parser.add_argument("--policy", choices=("alternate", "heuristic"), default="alternate")
    parser.add_argument("--output", type=Path, default=Path("emulation/output"))
    args = parser.parse_args()
    if not 1 <= args.episodes <= 4 or not 2 <= args.steps <= 64 or not 2 <= args.window <= 10:
        parser.error("Bounded smoke requires episodes 1..4, steps 2..64, windows 2..10")
    request = {"version": 1, "command": "reset", "episode_id": None, "step_index": None,
               "seed": args.seed, "scenario": "path0", "action": None, "mode": args.mode,
               "window_seconds": args.window, "episode_steps": args.steps}
    trace = []

    def exchange():
        result = subprocess.run(["docker", "exec", "-i", "nanfo-experiment", "python", "-m",
                                 "emulation.experiment_client"], input=json.dumps(request),
                                capture_output=True, text=True, timeout=65)
        value = json.loads(result.stdout)
        trace.append({"request": dict(request), "response": value})
        atomicJson(args.output / "experiment-smoke.json", trace)
        if not value["ok"]:
            raise RuntimeError(value["error"])
        if value["data"].get("truncated"):
            raise RuntimeError(value["data"]["evidence"]["error"])
        return value["data"]

    started = time.monotonic()
    try:
        for episode in range(args.episodes):
            request.update(command="reset", episode_id=None, step_index=None, action=None,
                           seed=args.seed + episode, scenario="path0" if episode % 2 == 0 else "path1")
            data = exchange()
            request["episode_id"] = data["episode_id"]
            request["step_index"] = 0
            for index in range(1, args.steps + 1):
                action = index % 2
                if args.policy == "heuristic":
                    observation = data["observation"]
                    pressure = [u + q / 100 for u, q in zip(observation["path_utilization"],
                                                           observation["path_queue_packets"])]
                    action = observation["previous_action"]
                    if pressure[1 - action] + 0.15 < pressure[action]:
                        action = 1 - action
                request.update(command="step", step_index=index, action=action)
                data = exchange()
        summary = {"passed": True, "episodes": args.episodes, "decision_windows": args.episodes * args.steps,
                   "initial_windows": args.episodes, "elapsed_seconds": time.monotonic() - started,
                   "policy": args.policy, "mode": args.mode}
        atomicJson(args.output / "experiment-smoke-summary.json", summary)
        print(json.dumps(summary))
    finally:
        if request["episode_id"] is not None:
            request.update(command="close", action=None)
            exchange()


if __name__ == "__main__":
    main()
