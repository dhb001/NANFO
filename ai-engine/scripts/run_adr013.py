"""One parent-approved ADR013 campaign; frozen CLI, no retries or budget extension."""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from nanfo_routing.artifacts import atomicWrite, clientSources
from nanfo_routing.contracts import jsonBytes, parseJson
from nanfo_routing.qualification import frozenPlan

IMAGE = "sha256:72b267fdcb6f197d0ffe4960389e238ea093fac61b3f95751cf98edfefd098ad"
SPEC = "5ece436bfa8b41fd868dfc87dc5152848d038e25511c6dadee1e64a420b1cbe9"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-approved", required=True, action="store_true")
    parser.add_argument("--lab-released", required=True, action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.parent != ROOT / "artifacts" or output.exists():
        raise ValueError("new ai-engine/artifacts run directory required")
    output.mkdir(mode=0o700)
    frozen = frozenPlan()
    atomicWrite(output / "plan.json", jsonBytes(frozen))
    sourceHashes = clientSources()
    status = {
        "version": 3,
        "status": "preflight",
        "pid": os.getpid(),
        "image_id": IMAGE,
        "spec_hash": SPEC,
        "client_source_files": sourceHashes,
        "parent_authorized": True,
        "lab_released": True,
        "budget_seconds": 1200,
        "commands": [],
        "sessions": [],
        "qualifications": [],
        "test": "not_run",
        "udp_echo_rtt": "not_implemented; primary latency is measured ICMP RTT",
        "cleanup": [],
        "selection": None,
        "admission": (
            "optional pilot train estimate + max(validation estimate,210) + 30; "
            "test 5 eval estimates + 180"
        ),
    }
    owned = None
    deadline = None
    child = None

    def writeStatus():
        status["updated_unix"] = time.time()
        status["remaining_seconds"] = max(0, deadline - time.time()) if deadline else None
        atomicWrite(output / "campaign.json", jsonBytes(status))

    def command(name, argv, *, timeout=120, allowed=(0,)):
        nonlocal child
        row = {"name": name, "argv": list(map(str, argv)), "started_unix": time.time()}
        status["commands"].append(row)
        status["stage"] = name
        writeStatus()
        with (output / f"{name}.stdout.log").open("xb") as stdout:
            with (output / f"{name}.stderr.log").open("xb") as stderr:
                child = subprocess.Popen(
                    row["argv"],
                    stdout=stdout,
                    stderr=stderr,
                    cwd=ROOT.parent,
                    start_new_session=True,
                )
                try:
                    code = child.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=25)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=5)
                    raise RuntimeError(f"{name} timed out; no retries") from None
                finally:
                    row.update(finished_unix=time.time(), returncode=child.returncode)
                    child = None
                    writeStatus()
        if code not in allowed:
            raise RuntimeError(f"{name} exited {code}; inspect preserved logs")
        return code

    def docker(*argv):
        result = subprocess.run(["docker", *argv], capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[:1500])
        return result.stdout.strip()

    def cleanup():
        nonlocal owned
        if owned is None:
            return
        for _ in range(12):
            if not docker("ps", "-aq", "--no-trunc", "--filter", f"id={owned}"):
                status["cleanup"].append({"container_id": owned, "removed": True})
                owned = None
                writeStatus()
                return
            time.sleep(0.25)
        # Filter by the captured full ID, never stop a replacement by its mutable name.
        present = docker("ps", "-aq", "--no-trunc", "--filter", f"id={owned}")
        if present:
            if present != owned:
                raise RuntimeError("container identity mismatch during cleanup")
            command(
                f"cleanup-{len(status['cleanup'])}",
                ["docker", "stop", "--time", "20", owned],
                timeout=30,
            )
        for _ in range(30):
            if not docker("ps", "-aq", "--no-trunc", "--filter", f"id={owned}"):
                status["cleanup"].append({"container_id": owned, "removed": True})
                owned = None
                writeStatus()
                return
            time.sleep(0.25)
        raise RuntimeError("owned container not removed after cleanup")

    def session(name, mode, options):
        nonlocal deadline, owned
        if clientSources() != sourceHashes:
            raise RuntimeError("client source changed; freeze violated; no new collection")
        if (
            docker("image", "inspect", "nanfo-emulation:campus-small-v1", "--format", "{{.Id}}")
            != IMAGE
        ):
            raise RuntimeError("released lab image changed")
        if docker("ps", "-aq", "--filter", "name=^/nanfo-experiment$"):
            raise RuntimeError("lab slot already owned; refusing unrelated cleanup")
        if deadline is None:
            began = time.time()
            deadline = began + 1200
            status["started_unix"] = began
            status["deadline_unix"] = deadline
            # Start slightly before first measurement, counting first startup conservatively.
            atomicWrite(
                output / "plan.collection.json",
                jsonBytes(
                    {
                        "plan_sha256": hashlib.sha256(jsonBytes(frozen)).hexdigest(),
                        "started_unix": began,
                        "deadline_unix": deadline,
                        "attempts": [],
                    }
                ),
            )
        if deadline - time.time() < 230:
            raise RuntimeError("insufficient session admission/cleanup time; no new collection")
        start = time.time()
        try:
            command(
                f"start-{name}",
                [sys.executable, "emulation/control.py", "experiment-start", "--mode", mode],
                timeout=110,
            )
        finally:
            container = docker("ps", "-aq", "--no-trunc", "--filter", "name=^/nanfo-experiment$")
            if container:
                actual = parseJson(docker("inspect", container))[0]
                if (
                    actual["Image"] != IMAGE
                    or actual["Config"]["Labels"].get("com.docker.compose.project")
                    != "nanfo-emulation"
                ):
                    raise RuntimeError("started container identity mismatch; not adopting")
                owned = container
                atomicWrite(output / f"{name}.owner.json", jsonBytes(actual))
        if owned is None:
            raise RuntimeError("started experiment owner missing")
        command(
            f"session-{name}",
            [
                sys.executable,
                "-m",
                "nanfo_routing",
                *options,
                "--operator-experiment",
                "--parent-approved",
                "--lab-released",
                "--plan",
                output / "plan.json",
                "--mode",
                mode,
                "--scenarios",
                "path0,path1",
                "--steps",
                "4",
                "--window",
                "2",
                "--rollout",
                "16",
                "--budget-seconds",
                "300",
                "--output",
                output / name,
            ],
            timeout=min(460, deadline - time.time() - 25),
        )
        cleanup()
        summary = parseJson((output / name / "summary.json").read_bytes())
        if (
            summary["status"] != "completed"
            or summary["spec_hash"] != SPEC
            or summary["lab_provenance"]["lab_image_id"] != IMAGE
        ):
            raise RuntimeError("session failed completion or released provenance gate")
        status["sessions"].append(
            {
                "name": name,
                "elapsed_seconds": time.time() - start,
                "mean_episode_reward": summary["mean_episode_reward"],
            }
        )
        writeStatus()
        return output / name / "summary.json"

    def cli(name, options, allowed=(0,)):
        return command(
            name, [sys.executable, "-m", "nanfo_routing", *options], timeout=120, allowed=allowed
        )

    def interrupted(signum, frame):
        if child is not None:
            os.killpg(child.pid, signal.SIGTERM)
        raise KeyboardInterrupt("campaign interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    writeStatus()
    try:
        controls = [
            session(
                f"calibration-{policy}",
                "matched",
                [
                    "evaluate",
                    "--policy",
                    policy,
                    "--split",
                    "train",
                    "--seed",
                    "1480",
                    "--episodes",
                    "2",
                ],
            )
            for policy in ("constant0", "constant1")
        ]
        baselines = []
        candidates = []
        for index, pilot in enumerate(frozen["pilots"]):
            seed = pilot["model_seed"]
            if index:
                trainTime = (
                    next(
                        row["elapsed_seconds"]
                        for row in status["sessions"]
                        if row["name"] == "train-41"
                    )
                    * 1.15
                )
                evalTime = (
                    max(
                        row["elapsed_seconds"]
                        for row in status["sessions"]
                        if row["name"].startswith("validation-")
                    )
                    * 1.15
                )
                if deadline - time.time() < trainTime + max(evalTime, 210) + 30:
                    status["stop_reason"] = "remaining_budget_cannot_admit_complete_next_pilot"
                    break
            trained = session(
                f"train-{seed}",
                "matched",
                [
                    "train",
                    "--model-seed",
                    str(seed),
                    "--seed",
                    str(pilot["train_seeds"][0]),
                    "--episodes",
                    "8",
                    "--calibration",
                    *controls,
                ],
            )
            if not baselines:
                baselines = [
                    session(
                        f"validation-{policy}",
                        "ospf" if policy == "ospf" else "matched",
                        [
                            "evaluate",
                            "--policy",
                            policy,
                            "--split",
                            "validation",
                            "--seed",
                            "2600",
                            "--episodes",
                            "4",
                        ],
                    )
                    for policy in frozen["baselines"]
                ]
            checkpoint = trained.parent / "checkpoint.ptz"
            evaluated = session(
                f"validation-{seed}",
                "matched",
                [
                    "evaluate",
                    "--policy",
                    "ppo",
                    "--checkpoint",
                    checkpoint,
                    "--model-seed",
                    str(seed),
                    "--split",
                    "validation",
                    "--seed",
                    "2600",
                    "--episodes",
                    "4",
                ],
            )
            cli(f"report-{seed}", ["report", evaluated, *baselines])
            qualification = output / f"qualification-{seed}.json"
            code = cli(
                f"qualify-{seed}",
                [
                    "qualify",
                    "--plan",
                    output / "plan.json",
                    "--checkpoint",
                    checkpoint,
                    "--training",
                    trained,
                    "--calibration",
                    *controls,
                    "--validation",
                    evaluated,
                    *baselines,
                    "--output",
                    qualification,
                ],
                allowed=(0, 2),
            )
            candidates.append(qualification)
            result = parseJson(qualification.read_bytes())
            status["qualifications"].append(
                {
                    "model_seed": seed,
                    "qualified": result["qualified"],
                    "margins": result["margins_over_both_constants"],
                    "directional_dependence": result["directional_dependence"],
                }
            )
            cli(
                f"infer-{seed}",
                [
                    "infer",
                    "--checkpoint",
                    checkpoint,
                    "--history",
                    evaluated.parent / "last-history.json",
                ],
            )
            if code == 0:
                selection = output / "selection.json"
                cli("select", ["select", "--candidates", *candidates, "--output", selection])
                status["selection"] = str(selection)
                cli(
                    "infer-selected",
                    [
                        "infer",
                        "--checkpoint",
                        checkpoint,
                        "--selection",
                        selection,
                        "--history",
                        evaluated.parent / "last-history.json",
                    ],
                )
                evalTime = (
                    max(
                        row["elapsed_seconds"]
                        for row in status["sessions"]
                        if row["name"].startswith("validation-")
                    )
                    * 1.15
                )
                if deadline - time.time() >= 5 * evalTime + 180:
                    testPaths = []
                    for policy in [*frozen["baselines"], "ppo"]:
                        options = [
                            "evaluate",
                            "--policy",
                            policy,
                            "--split",
                            "test",
                            "--seed",
                            "3800",
                            "--episodes",
                            "4",
                            "--selection",
                            selection,
                        ]
                        if policy == "ppo":
                            options += ["--checkpoint", checkpoint, "--model-seed", str(seed)]
                        testPaths.append(
                            session(
                                f"test-{policy}", "ospf" if policy == "ospf" else "matched", options
                            )
                        )
                    cli("report-test", ["report", *testPaths])
                    status["test"] = "completed_all_five_policies"
                else:
                    status["test"] = "not_run_insufficient_original_budget_for_all_five"
                status["stop_reason"] = "qualified_selection_frozen"
                break
        status["status"] = "completed"
        status.setdefault("stop_reason", "all_frozen_pilots_evaluated_no_qualified_policy")
    except (ValueError, RuntimeError, OSError, KeyboardInterrupt) as exc:
        status.update(
            status="failed",
            failure=str(exc)[:2048],
            stop_reason="failure_preserved_no_retry_no_extension",
        )
    finally:
        try:
            cleanup()
        except (ValueError, RuntimeError, OSError) as exc:
            status.update(status="failed", cleanup_error=str(exc)[:2048])
        status["finished_unix"] = time.time()
        status["elapsed_seconds"] = time.time() - status["started_unix"] if deadline else 0
        writeStatus()
    print(
        json.dumps(
            {
                key: status.get(key)
                for key in (
                    "status",
                    "stop_reason",
                    "elapsed_seconds",
                    "test",
                    "selection",
                    "failure",
                )
            }
        ),
        flush=True,
    )
    return int(status["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
