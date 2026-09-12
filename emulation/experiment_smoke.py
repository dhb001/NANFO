"""Operator baseline smoke via the same docker-exec JSON transport used by AI."""

import argparse
import hashlib
import json
import subprocess
import time
import uuid
from pathlib import Path

from emulation.experiment import environmentSpec
from emulation.measurements import atomicJson


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--window", type=float, default=5)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--mode", choices=("sdn", "matched", "ospf"), default="sdn")
    parser.add_argument(
        "--policy",
        choices=("alternate", "heuristic", "constant0", "constant1"),
        default="alternate",
    )
    parser.add_argument(
        "--repeat-seed", action="store_true", help="Replay identical offered schedule"
    )
    parser.add_argument("--output", type=Path, default=Path("emulation/output"))
    args = parser.parse_args()
    if not 1 <= args.episodes <= 4 or not 2 <= args.steps <= 64 or not 2 <= args.window <= 10:
        parser.error("Bounded smoke requires episodes 1..4, steps 2..64, windows 2..10")
    request = {
        "version": 1,
        "command": "reset",
        "episode_id": None,
        "step_index": None,
        "seed": args.seed,
        "scenario": "path0",
        "action": None,
        "mode": args.mode,
        "window_seconds": args.window,
        "episode_steps": args.steps,
    }
    trace = []
    localSpec, localHash = environmentSpec(args.mode)
    image = subprocess.run(
        ["docker", "inspect", "nanfo-experiment", "--format", "{{.Image}}"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()

    def exchange(rejected=False):
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "nanfo-experiment",
                "python",
                "-m",
                "emulation.experiment_client",
            ],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=65,
        )
        value = json.loads(result.stdout)
        trace.append({"request": dict(request), "response": value})
        atomicJson(args.output / f"experiment-smoke-{args.mode}.json", trace)
        with (args.output / f"experiment-smoke-{args.mode}.jsonl").open("a") as stream:
            stream.write(json.dumps(trace[-1], allow_nan=False) + "\n")
        if rejected:
            if value["ok"] or value["data"] is not None:
                raise RuntimeError("Invalid/repeated request was accepted")
            return None
        if not value["ok"]:
            raise RuntimeError(value["error"])
        if "step_index" in value["data"]:
            request["episode_id"] = value["data"]["episode_id"]
            request["step_index"] = value["data"]["step_index"]
        if value["data"].get("truncated"):
            raise RuntimeError(value["data"]["evidence"]["error"])
        if "observation" in value["data"]:
            data = value["data"]
            evidence, observation = data["evidence"], data["observation"]
            spec = evidence["environment_spec"]
            digest = hashlib.sha256(
                json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
                    "ascii"
                )
            ).hexdigest()
            if not (
                spec["version"] == (4 if args.mode == "sdn" else 5)
                and spec == localSpec
                and digest == localHash
                and digest == evidence["spec_hash"]
                and evidence["measurement_complete"] is True
                and observation["actual_offered_mbps"] > 0
                and observation["actual_offered_mbps"] == evidence["actual_offered_mbps"][0]
                and evidence["provenance"]["lab_image_id"] == image
                and evidence["provenance"]["source_sha256"] == localSpec["source_sha256"]
                and evidence["phase_relationship"]["measurement_phase_index"] == data["step_index"]
            ):
                raise RuntimeError("Environment provenance or measured rate gate failed")
            empty = evidence["drain_empty_observations"]
            if not (
                evidence["drain_status"] == "verified_empty"
                and len(empty) == spec["drain_empty_observations"]
                and evidence["drain_begin"]
                < evidence["drain_end"]
                <= evidence["drain_begin"] + spec["drain_max_seconds"]
                and empty[1]["start"] - empty[0]["end"] >= spec["drain_poll_interval_seconds"]
                and all(
                    set(sweep["queues"]) == set(evidence["drain_queue_interfaces"])
                    and all(
                        q["backlog_bytes"] == q["backlog_packets"] == 0
                        for q in sweep["queues"].values()
                    )
                    for sweep in empty
                )
                and evidence["queue_end"] == empty[-1]["queues"]
                and all(
                    value is not None for key, value in observation.items() if key != "latency_ms"
                )
            ):
                raise RuntimeError("Incomplete initial/decision observation or drain evidence")
        return value["data"]

    started = time.monotonic()
    failure = None
    cleanup = False
    try:
        for episode in range(args.episodes):
            request.update(
                command="reset",
                episode_id=None,
                step_index=None,
                action=None,
                seed=args.seed if args.repeat_seed else args.seed + episode,
                scenario="path0" if args.repeat_seed or episode % 2 == 0 else "path1",
            )
            data = exchange()
            request["episode_id"] = data["episode_id"]
            request["step_index"] = 0
            valid = dict(request)
            for change in (
                {"command": "reset", "episode_id": None, "step_index": None},
                {"command": "step", "step_index": 1, "action": 1, "episode_id": str(uuid.uuid4())},
                {"command": "step", "step_index": 2, "action": 1},
                {"command": "step", "step_index": 1, "action": True},
                {"command": "step", "step_index": 1, "action": 1, "window_seconds": 11},
                {"command": "step", "step_index": 1, "action": 1, "seed": args.seed + 500},
            ):
                request = {**valid, **change}
                exchange(rejected=True)
            request = valid
            for index in range(1, args.steps + 1):
                action = index % 2
                if args.policy.startswith("constant"):
                    action = int(args.policy[-1])
                if args.policy == "heuristic":
                    observation = data["observation"]
                    pressure = [
                        u + q / 100
                        for u, q in zip(
                            observation["path_utilization"], observation["path_queue_packets"]
                        )
                    ]
                    action = observation["previous_action"]
                    if pressure[1 - action] + 0.15 < pressure[action]:
                        action = 1 - action
                    if args.mode != "sdn":
                        action = max(range(2), key=lambda p: observation["path_capacity_mbps"][p])
                request.update(command="step", step_index=index, action=action)
                data = exchange()
                # Reusing the cached request must reject, never apply or measure twice.
                exchange(rejected=True)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        failure = str(error)[:300]
    finally:
        if request["episode_id"] is not None:
            request.update(command="close", action=None)
            try:
                cleanup = exchange().get("cleanup_verified") is True
            except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
                failure = failure or str(error)[:300]
    windows = [
        row["response"]["data"]
        for row in trace
        if row["response"]["ok"] and "observation" in row["response"]["data"]
    ]
    summary = {
        "passed": failure is None and cleanup,
        "error": failure,
        "cleanup_verified": cleanup,
        "episodes": args.episodes,
        "decision_windows": sum(row["step_index"] > 0 for row in windows),
        "initial_windows": sum(row["step_index"] == 0 for row in windows),
        "protocol_rejections": sum(not row["response"]["ok"] for row in trace),
        "elapsed_seconds": time.monotonic() - started,
        "policy": args.policy,
        "mode": args.mode,
        "repeat_seed": args.repeat_seed,
        "episode_ids": list(dict.fromkeys(row["episode_id"] for row in windows)),
        "metrics": [{"step_index": row["step_index"], **row["observation"]} for row in windows],
        "environment_spec_hashes": list(
            dict.fromkeys(row["evidence"]["spec_hash"] for row in windows)
        ),
        "lab_image_ids": list(
            dict.fromkeys(row["evidence"]["provenance"]["lab_image_id"] for row in windows)
        ),
        "source_sha256": localSpec["source_sha256"],
        "executing_source_matches_workspace": failure is None,
        "drain": [
            {
                key: row["evidence"].get(key)
                for key in (
                    "drain_begin",
                    "drain_end",
                    "drain_duration_seconds",
                    "drain_status",
                    "drain_sweeps",
                    "late_received_packets",
                )
            }
            for row in windows
        ],
        "measured_windows_seconds": [
            row["evidence"].get("measured_window_seconds") for row in windows
        ],
        "control_overhead_seconds": [
            row["evidence"].get("control_overhead_seconds") for row in windows
        ],
    }
    if args.repeat_seed and failure is None:
        phases = [row["evidence"]["phase"] for row in windows]
        summary["schedule_repeat_verified"] = all(
            phases[i : i + args.steps + 1] == phases[: args.steps + 1]
            for i in range(0, len(phases), args.steps + 1)
        )
        summary["passed"] &= summary["schedule_repeat_verified"]
    atomicJson(args.output / f"experiment-smoke-{args.mode}-summary.json", summary)
    if windows:
        atomicJson(
            args.output / f"experiment-smoke-{args.mode}-{windows[0]['episode_id']}-summary.json",
            summary,
        )
    print(json.dumps(summary))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
