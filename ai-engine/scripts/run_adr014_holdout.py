"""Explicit test-only ADR014 continuation; frozen model package is never edited/patched."""

import argparse
import hashlib
import json
import random
import signal
import statistics
import sys
import time
import uuid
from pathlib import Path

from nanfo_routing import cli
from nanfo_routing.artifacts import atomicWrite, clientSources, inspectCheckpoint, loadCheckpoint
from nanfo_routing.contracts import Observation, jsonBytes, parseJson
from nanfo_routing.env import encode
from nanfo_routing.expanded import qualify
from nanfo_routing.extended_supervisor import releaseEvidence
from nanfo_routing.supervisor import GLOBAL_LOCK, ROOT, Supervisor, lock, outputPath, readJson

ORIGINAL = ROOT / "artifacts" / "adr014-001"
OUTPUT = ROOT / "artifacts" / "adr014-holdout-001"
SCRIPT = Path(__file__).resolve()
IMAGE = "sha256:6b4ed91c2e7be7e4fbbb536ad3a808eb0e98c9d5f8165a5008846586893016ff"
ORDER_SEED = 9142026
POLICIES = ["constant0", "constant1", "heuristic", "ospf", "ppo"]


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def choose(candidates):
    if [row["transitions"] for row in candidates] != [128, 256, 384]:
        raise ValueError("all original validation checkpoints required")
    eligible = [row for row in candidates if row["qualified"]]
    if not eligible:
        raise ValueError("no validation-qualified original checkpoint")
    return min(eligible, key=lambda row: (-row["validation_mean_reward"], row["transitions"]))


def prepare():
    original = readJson(ORIGINAL / "plan.json")
    if clientSources() != original["client_source_sha256"]:
        raise ValueError("current model package differs from original frozen source")
    for name, sha in original["client_source_sha256"].items():
        if digest(ORIGINAL / "source" / name) != sha:
            raise ValueError("original source snapshot hash differs")
    ledger = readJson(ORIGINAL / "training-plan.collection.json")
    if any(row["identity"]["split"] == "test" for row in ledger["attempts"]):
        raise ValueError("original test already attempted")
    if readJson(ORIGINAL / "status.json")["state"] not in ("stopped", "failed"):
        raise ValueError("original campaign is not terminal")
    release = releaseEvidence(ORIGINAL / "release.json", IMAGE)
    candidates = []
    for count in (2, 4, 6):
        saved = readJson(ORIGINAL / f"qualification-{count:02}.json")
        paths = saved["evidence_paths"]
        actual = qualify(
            paths["checkpoint"],
            paths["training"],
            paths["validation"],
            paths["plan"],
            paths["calibration"],
        )
        if actual != saved:
            raise ValueError("original qualification differs from reconstructed evidence")
        candidates.append(actual)
    best = choose(candidates)
    order = POLICIES.copy()
    random.Random(ORDER_SEED).shuffle(order)
    # Pin all original model/evidence/plan bytes. Locks, status and runtime logs are
    # excluded; original selection is not re-run after any holdout is opened.
    sources = [
        p
        for p in ORIGINAL.rglob("*")
        if p.is_file()
        and p.suffix in (".json", ".jsonl", ".ptz", ".py", ".toml", ".lock")
        and p.name not in ("status.json", "run.lock", "training-plan.collection.lock")
        and "lab-output" not in p.parts
    ]
    return {
        "version": "adr014-test-only-v1",
        "campaign_id": uuid.uuid4().hex,
        "output": str(OUTPUT),
        "image_id": IMAGE,
        "release": release,
        "client_source_sha256": clientSources(),
        "runtime_versions": original["runtime_versions"],
        "runner_sha256": digest(SCRIPT),
        "original_campaign": str(ORIGINAL),
        "original_plan_sha256": digest(ORIGINAL / "training-plan.json"),
        "original_evidence_sha256": {str(p.relative_to(ORIGINAL)): digest(p) for p in sources},
        "authorization": (
            "user-approved test-only continuation; original512 selection minimum waived; "
            "no training/validation/tuning"
        ),
        "selection_rule": "highest qualified validation reward; lower transitions breaks ties",
        "candidates": [
            {
                key: row[key]
                for key in ("transitions", "qualified", "validation_mean_reward", "checkpoint")
            }
            for row in candidates
        ],
        "checkpoint": best["checkpoint"],
        "checkpoint_path": best["evidence_paths"]["checkpoint"],
        "history_path": str(ORIGINAL / "validation-06" / "last-history.json"),
        "policy_order_seed": ORDER_SEED,
        "policy_order": order,
        "test_seeds": list(range(3900, 3912)),
        "scenarios": ["path0", "path1"],
        "steps": 4,
        "window_seconds": 2.0,
        "budget_seconds": 3600,
        "cleanup_reserve_seconds": 120,
        "session_budget_seconds": 600,
        "test_attempts_before_selection": 0,
        "success_rule": "all12 paired seed means: goodput95%CI lower>0 AND ICMP RTT95%CI upper<0",
        "scope": (
            "balanced stationary2/20Mbps impairment versus unchanged nominal-cost OSPF, "
            "not capacity-aware OSPF or all networks"
        ),
        "autonomous_dispatch": "blocked",
    }


def verifiedPlan(output):
    plan = readJson(output / "plan.json")
    if (
        plan["output"] != str(OUTPUT)
        or output != OUTPUT
        or plan["version"] != "adr014-test-only-v1"
    ):
        raise ValueError("invalid test-only campaign identity")
    if digest(SCRIPT) != plan["runner_sha256"] or clientSources() != plan["client_source_sha256"]:
        raise ValueError("test runner or checkpoint-bound source changed")
    for name, sha in plan["original_evidence_sha256"].items():
        path = ORIGINAL / name
        if path.resolve().is_relative_to(ORIGINAL) is False or digest(path) != sha:
            raise ValueError("original frozen evidence changed")
    if inspectCheckpoint(Path(plan["checkpoint_path"])) != plan["checkpoint"]:
        raise ValueError("selected model identity changed")
    selection = readJson(output / "selection.json")
    if selection != {
        "plan_sha256": digest(output / "plan.json"),
        "checkpoint": plan["checkpoint"],
        "selection_rule": plan["selection_rule"],
        "test_only": True,
    }:
        raise ValueError("immutable test-only selection differs")
    releaseEvidence(ORIGINAL / "release.json", IMAGE)
    return plan


def session(output, policy, container):
    plan = verifiedPlan(output)
    with lock(output / "admission.lock"):
        ledger = readJson(output / "test-ledger.json")
        if ledger["plan_sha256"] != digest(output / "plan.json"):
            raise ValueError("test ledger plan mismatch")
        index = len(ledger["attempts"])
        if index >= 5 or policy != plan["policy_order"][index]:
            raise ValueError("test order consumed or differs; no retry")
        if container != "nanfo-training-" + plan["campaign_id"]:
            raise ValueError("test container is not owned")
        remaining = ledger["deadline_unix"] - time.time() - 120
        if remaining < 30:
            raise ValueError("test-only budget exhausted")
        attempt = {
            "policy": policy,
            "seeds": plan["test_seeds"],
            "split": "test",
            "checkpoint_sha256": plan["checkpoint"]["checkpoint_sha256"],
            "started_unix": time.time(),
            "status": "attempted",
        }
        ledger["attempts"].append(attempt)
        atomicWrite(output / "test-ledger.json", jsonBytes(ledger))
        args = cli.parser().parse_args(
            [
                "evaluate",
                "--operator-experiment",
                "--parent-approved",
                "--lab-released",
                "--plan",
                str(ORIGINAL / "training-plan.json"),
                "--container",
                container,
                "--output",
                str(output / ("test-" + policy)),
                "--split",
                "test",
                "--policy",
                policy,
                "--mode",
                "ospf" if policy == "ospf" else "matched",
                "--seed",
                "3900",
                "--episodes",
                "12",
                "--steps",
                "4",
                "--window",
                "2",
                "--model-seed",
                "44",
                "--rollout",
                "16",
                "--learning-rate",
                "0.003",
                "--gamma",
                "0.9",
                "--budget-seconds",
                str(min(600, remaining)),
                *(["--checkpoint", plan["checkpoint_path"]] if policy == "ppo" else []),
            ]
        )

        def interrupted(signum, frame):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            raise KeyboardInterrupt("test-only operator stop")

        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        try:
            # Explicit NEW authorization/ledger above replaces only the expired original
            # collection admission. Frozen parser/session/measurement/model code is intact;
            # original plan is read-only. This path cannot train or select after test.
            result = cli._runSession(args)
            attempt["status"] = "completed"
            return result
        finally:
            attempt["finished_unix"] = time.time()
            atomicWrite(output / "test-ledger.json", jsonBytes(ledger))


def infer(output):
    plan = verifiedPlan(output)
    checkpoint = Path(plan["checkpoint_path"])
    started = time.perf_counter()
    agent, _ = loadCheckpoint(checkpoint)
    loadSeconds = time.perf_counter() - started
    history = readJson(Path(plan["history_path"]))
    observation = Observation.model_validate(
        history["frames"][-1]["response"]["data"]["observation"]
    )
    state = encode([observation])
    decisions, timings = [], []
    for _ in range(101):
        start = time.perf_counter()
        decisions.append(agent.model.decide(state, deterministic=True))
        timings.append(time.perf_counter() - start)
    if any(row != decisions[0] for row in decisions):
        raise ValueError("warm deterministic inference not reproducible")
    return {
        "decision": decisions[0],
        "model_load_seconds": loadSeconds,
        "cold_inference_seconds": timings[0],
        "warm_inference_mean_seconds": statistics.mean(timings[1:]),
        "warm_inference_max_seconds": max(timings[1:]),
        "warm_repeats": 100,
        "history_sha256": digest(Path(plan["history_path"])),
        "checkpoint_sha256": plan["checkpoint"]["checkpoint_sha256"],
    }


class Holdout(Supervisor):
    def __init__(self, output, frozen, started=None):
        super().__init__(output, frozen, started)
        self.hardDeadline = self.started + 3600
        self.workDeadline = self.hardDeadline - 120
        self.status.update(
            hard_deadline_unix=time.time() + self.hardDeadline - time.monotonic(),
            work_deadline_unix=time.time() + self.workDeadline - time.monotonic(),
            test_only=True,
            selected_checkpoint=frozen["checkpoint"],
            completed_policies=[],
        )

    def campaign(self):
        verifiedPlan(self.output)
        self.checkSources()
        self.exclusiveLab()
        image = self.command(
            ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], 10
        ).strip()
        if image != IMAGE:
            raise ValueError("pinned local image unavailable")
        cold = []
        for _ in range(2):
            start = time.perf_counter()
            result = parseJson(
                self.command(
                    [sys.executable, str(SCRIPT), "infer", "--output", str(self.output)], 60
                )
            )
            result["fresh_process_wall_seconds"] = time.perf_counter() - start
            cold.append(result)
        if cold[0]["decision"] != cold[1]["decision"]:
            raise ValueError("fresh-process probability/value/action mismatch")
        # Original CLI independently validates exact history/spec and its input hash.
        checked = parseJson(
            self.command(
                [
                    sys.executable,
                    "-m",
                    "nanfo_routing",
                    "infer",
                    "--checkpoint",
                    self.frozen["checkpoint_path"],
                    "--history",
                    self.frozen["history_path"],
                ],
                60,
            )
        )
        if (
            checked["action"] != cold[0]["decision"][0]
            or checked["probabilities"] != cold[0]["decision"][3]
            or checked["value"] != cold[0]["decision"][2]
        ):
            raise ValueError("frozen CLI history inference differs")
        atomicWrite(
            self.output / "inference-reproducibility.json",
            jsonBytes({"fresh_processes": cold, "frozen_cli": checked}),
        )
        paths = []
        for policy in self.frozen["policy_order"]:
            self.check()
            verifiedPlan(self.output)
            self.checkSources()
            self.status.update(stage="test-" + policy, child_progress=None)
            self.sessionOutput = self.output / ("test-" + policy)
            name = self.startLab("test-" + policy, "ospf" if policy == "ospf" else "matched")
            self.command(
                [
                    sys.executable,
                    str(SCRIPT),
                    "session",
                    "--output",
                    str(self.output),
                    "--policy",
                    policy,
                    "--container",
                    name,
                ],
                660,
                session=True,
            )
            self.cleanup()
            path = self.sessionOutput / "summary.json"
            row = readJson(path)
            if (
                row["status"] != "completed"
                or row["invalid_windows"] != 0
                or row["valid_transitions"] != 48
                or row["seeds"] != self.frozen["test_seeds"]
                or row["spec_hash"] != self.frozen["release"]["spec_hash"]
                or row["lab_provenance"]["lab_image_id"] != IMAGE
            ):
                raise ValueError("incomplete or non-pinned test measurement; no retry")
            paths.append(path)
            self.status["completed_policies"].append(policy)
            self.heartbeat()
        result = cli.report(paths, checkpoint=Path(self.frozen["checkpoint_path"]))
        if not result["comparable_held_out_schedules"]:
            raise ValueError("test inputs/dataplane not comparable")
        ospf = next(
            row["metrics"] for row in result["paired_seed_comparisons"] if row["baseline"] == "ospf"
        )
        goodput, rtt = ospf["goodput_mbps"], ospf["icmp_rtt_ms"]
        success = (
            goodput["paired_seed_count"] == rtt["paired_seed_count"] == 12
            and goodput["ci95"] is not None
            and rtt["ci95"] is not None
            and goodput["ci95"][0] > 0
            and rtt["ci95"][1] < 0
        )
        result.update(
            test_only=True,
            selection=readJson(self.output / "selection.json"),
            scope=self.frozen["scope"],
            measured_ospf_improvement=success,
            policy_order=self.frozen["policy_order"],
            autonomous_dispatch="blocked",
        )
        atomicWrite(self.output / "test-report.json", jsonBytes(result))
        verifiedPlan(self.output)
        self.status["measured_ospf_improvement"] = success
        return "completed_all_five_once"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "session", "infer", "status", "stop", "cleanup"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--parent-approved-test-only", action="store_true")
    parser.add_argument("--policy", choices=POLICIES)
    parser.add_argument("--container")
    args = parser.parse_args(argv)
    try:
        output = outputPath(args.output, existing=args.command != "run")
        if output != OUTPUT:
            raise ValueError("one authorized test-only output; no second ledger/retry")
        if args.command == "run":
            if not args.parent_approved_test_only or output.exists():
                raise ValueError("explicit authorization and new test ledger required")
            with lock(GLOBAL_LOCK), lock(ORIGINAL / "run.lock"):
                frozen = prepare()
                output.mkdir(mode=0o700)
                (output / "lab-output").mkdir(mode=0o700)
                atomicWrite(output / "plan.json", jsonBytes(frozen))
                atomicWrite(output / "runner.py", SCRIPT.read_bytes())
                atomicWrite(
                    output / "selection.json",
                    jsonBytes(
                        {
                            "plan_sha256": digest(output / "plan.json"),
                            "checkpoint": frozen["checkpoint"],
                            "selection_rule": frozen["selection_rule"],
                            "test_only": True,
                        }
                    ),
                )
                for name in ("plan.json", "selection.json", "runner.py"):
                    (output / name).chmod(0o400)
                started = time.monotonic()
                now = time.time()
                atomicWrite(
                    output / "test-ledger.json",
                    jsonBytes(
                        {
                            "plan_sha256": digest(output / "plan.json"),
                            "started_unix": now,
                            "deadline_unix": now + 3600,
                            "attempts": [],
                        }
                    ),
                )
                with lock(output / "run.lock"):
                    return Holdout(output, frozen, started).run()
        elif args.command == "session":
            result = session(output, args.policy, args.container)
        elif args.command == "infer":
            result = infer(output)
        elif args.command == "status":
            result = readJson(output / "status.json")
            result["heartbeat_stale"] = time.time() - result["heartbeat_unix"] > 10
        elif args.command == "stop":
            atomicWrite(output / "stop.request", jsonBytes({"operator_stop": True}))
            result = {"status": "stop_requested"}
        else:
            with lock(output / "run.lock"):
                frozen = readJson(output / "plan.json")
                runner = Holdout(output, frozen)
                runner.commandIndex = max(
                    [
                        900,
                        *[
                            int(p.name.split(".")[0].split("-")[1])
                            for p in output.glob("command-*.stdout.log")
                        ],
                    ]
                )
                runner.status = readJson(output / "status.json")
                runner.started -= runner.status["elapsed_seconds"]
                runner.hardDeadline = time.monotonic() + 110
                runner.status.update(stage="poststop_cleanup", child_pid=None)
                try:
                    runner.cleanup()
                    runner.status.update(stage="finished", cleanup_error=None)
                except (ValueError, RuntimeError, OSError) as exc:
                    runner.status.update(state="failed", cleanup_error=str(exc))
                    raise
                finally:
                    runner.heartbeat()
            result = {"status": "owned_cleanup_verified"}
        print(json.dumps(result))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)[:2048]}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
