#!/usr/bin/env python3
"""Explicitly opted-in, small measured training campaign against an already owned lab."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from nanfo_routing.artifacts import atomicWrite
from nanfo_routing.contracts import jsonBytes, parseJson


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator-experiment", action="store_true", required=True)
    parser.add_argument(
        "--baseline-verified",
        action="store_true",
        required=True,
        help="attest actual reset/step and FRR baseline checks passed",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, choices=(3, 4, 5), default=4)
    parser.add_argument(
        "--budget-seconds", type=int, choices=range(60, 601), default=300, metavar="60..600"
    )
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    result = {
        "version": 1,
        "status": "running",
        "source": "operator-owned-measured-lab",
        "requested_training_transitions": 6 * args.steps,
        "commands": [],
        "convergence_established": False,
        "held_out_evaluation": "not_run",
        "failure": None,
    }
    summary = args.output / "campaign.json"
    atomicWrite(summary, jsonBytes(result))
    train = args.output / "train"
    commands = [
        [
            "train",
            "--operator-experiment",
            "--output",
            str(train),
            "--episodes",
            "6",
            "--steps",
            str(args.steps),
            "--rollout",
            str(6 * args.steps),
            "--seed",
            "1000",
            "--window",
            "5",
            "--budget-seconds",
            str(args.budget_seconds),
        ],
        [
            "infer",
            "--checkpoint",
            str(train / "checkpoint.ptz"),
            "--history",
            str(train / "last-history.json"),
        ],
    ]
    try:
        for command in commands:
            argv = [sys.executable, "-m", "nanfo_routing", *command]
            result["commands"].append(argv)
            atomicWrite(summary, jsonBytes(result))
            # The session stops between requests; allow one in-flight request and close.
            with (args.output / f"{command[0]}.stdout.json").open("xb") as stdout:
                with (args.output / f"{command[0]}.stderr.log").open("xb") as stderr:
                    process = subprocess.run(
                        argv,
                        stdout=stdout,
                        stderr=stderr,
                        check=False,
                        timeout=args.budget_seconds + 200,
                    )
            if process.returncode:
                raise RuntimeError(f"{command[0]} exited {process.returncode}; inspect artifacts")
        result["status"] = "completed"
        result["training_summary"] = parseJson((train / "summary.json").read_bytes())
        result["fresh_process_inference"] = parseJson(
            (args.output / "infer.stdout.json").read_bytes()
        )
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        result.update(status="failed", failure=str(exc)[:2048] or type(exc).__name__)
        result["operator_action"] = (
            "Inspect lab ownership and experiment-stop if necessary; never replay lost steps."
        )
    finally:
        result["elapsed_seconds"] = time.monotonic() - started
        atomicWrite(summary, jsonBytes(result))
    print(json.dumps({"status": result["status"], "summary": str(summary)}))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
