"""Explicit ADR014 campaign, sharing the bounded ID/label-owning supervisor runtime."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .artifacts import atomicWrite, clientSources, runtimeVersions
from .cli import report
from .contracts import jsonBytes, parseJson
from .expanded import frozenPlan, qualify, selectPolicy
from .qualification import actionEffectChecks
from .supervisor import (
    GLOBAL_LOCK,
    IMAGE_PATTERN,
    ROOT,
    Supervisor,
    labProfile,
    lock,
    outputPath,
    readJson,
)


def releaseEvidence(path, image):
    """The lab owner supplies this handoff after live drain verification and cleanup."""
    release = readJson(path)
    if (
        release.get("released") is not True
        or release.get("image_id") != image
        or not re.fullmatch(IMAGE_PATTERN, image)
        or release.get("environment_spec", {}).get("version") != 4
    ):
        raise ValueError("complete V4 lab-owner release with exact image/spec required")
    from .evidence import validateSpec

    spec = release["environment_spec"]
    validateSpec(spec, release["spec_hash"])
    for name, digest in spec["source_files"].items():
        if (
            Path(name).name != name
            or hashlib.sha256((ROOT.parent / "emulation" / name).read_bytes()).hexdigest() != digest
        ):
            raise ValueError("released lab source changed; wait for new completed handoff")
    return release


def learning(curves):
    """Validation-only probability movement can justify extension despite fixed argmax."""
    if len(curves) < 4:
        return True
    recent, previous = curves[-2:], curves[-4:-2]
    reward = (
        max(row["validation_mean_reward"] for row in recent)
        > max(row["validation_mean_reward"] for row in previous) + 0.02
    )

    def probability(row):
        return min(d["mean_desired_probability"] for d in row["directional_dependence"].values())

    return reward or max(map(probability, recent)) > max(map(probability, previous)) + 0.02


class ExtendedSupervisor(Supervisor):
    def checkSources(self):
        super().checkSources()
        releaseEvidence(self.output / "release.json", self.frozen["image_id"])

    def measured(
        self,
        stage,
        split,
        first,
        count,
        policy="ppo",
        checkpoint=None,
        calibration=None,
        selection=None,
    ):
        self.checkSources()
        self.status.update(stage=stage, child_progress=None)
        self.sessionOutput = self.output / stage
        self.heartbeat()
        mode = "ospf" if policy == "ospf" else "matched"
        name = self.startLab(stage, mode)
        training = stage.startswith("train-")
        argv = [
            sys.executable,
            "-m",
            "nanfo_routing",
            "train" if training else "evaluate",
            "--operator-experiment",
            "--parent-approved",
            "--lab-released",
            "--plan",
            str(self.output / "training-plan.json"),
            "--container",
            name,
            "--budget-seconds",
            "600",
            "--mode",
            mode,
            "--scenarios",
            "path0,path1",
            "--seed",
            str(first),
            "--episodes",
            str(count),
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
            "--output",
            str(self.sessionOutput),
        ]
        if training:
            argv += ["--calibration", *map(str, calibration)]
        else:
            argv += ["--policy", policy, "--split", split]
        if checkpoint:
            argv += ["--resume" if training else "--checkpoint", str(checkpoint)]
        if selection:
            argv += ["--selection", str(selection)]
        self.command(argv, 660, session=True)
        self.cleanup()
        path = self.sessionOutput / "summary.json"
        summary = readJson(path)
        if (
            summary["status"] != "completed"
            or summary["invalid_windows"] != 0
            or summary["valid_transitions"] != count * 4
            or summary["lab_provenance"]["lab_image_id"] != self.frozen["image_id"]
            or summary["spec_hash"] != self.frozen["release"]["spec_hash"]
        ):
            raise ValueError("incomplete or non-released measurement; no retry")
        audited = report([path], checkpoint=checkpoint if not training else None)
        atomicWrite(self.sessionOutput / "audit.json", jsonBytes(audited))
        self.check()
        return path

    def offline(self, name, options):
        self.status["stage"] = name
        self.checkSources()
        self.command([sys.executable, "-m", "nanfo_routing", *map(str, options)], 180)

    def campaign(self):
        plan = frozenPlan()
        self.checkSources()
        self.exclusiveLab()
        if (
            self.command(
                ["docker", "image", "inspect", self.frozen["image_id"], "--format", "{{.Id}}"], 10
            ).strip()
            != self.frozen["image_id"]
        ):
            raise ValueError("released image unavailable locally; no pull/build")
        controls = [
            self.measured("calibration-" + p, "train", 1580, 2, p)
            for p in ("constant0", "constant1")
        ]
        _, self.status["learnability_margins"] = actionEffectChecks(controls, plan)
        firstBlock = self.measured("train-01", "train", 1600, 16, calibration=controls)
        with (firstBlock.parent / "evidence.jsonl").open("rb") as source:
            updates = [row for line in source if (row := parseJson(line))["kind"] == "ppo_update"]
        if len(updates) != 4:
            raise ValueError("first fresh block did not complete four on-policy updates")
        atomicWrite(
            self.output / "train-only-diagnostics.json",
            jsonBytes(
                {
                    "label": "FRESH ONPOLICY TRAIN-ONLY DIAGNOSTICS",
                    "updates": updates,
                    "hyperparameters": plan["ppo_config"],
                    "hyperparameters_changed": False,
                    "validation_or_test_seen": False,
                }
            ),
        )
        baselines = [
            self.measured("baseline-" + p, "validation", 2700, 8, p) for p in plan["baseline_order"]
        ]
        baselineReport = report(baselines)
        if not baselineReport["comparable_held_out_schedules"]:
            raise ValueError("baselines are not matched held-out measurements")
        atomicWrite(self.output / "baseline-report.json", jsonBytes(baselineReport))
        curves, candidates, previous = [], [], None
        reason = "maximum1024_transitions"
        for index in range(16):
            # Fixed admission reserve covers five12-seed tests, selection and cleanup.
            # Work commands still have independent hard deadlines; no optimistic retry.
            if (
                index % 2 == 0
                and self.workDeadline - time.monotonic() < 1200 + plan["test_reserve_seconds"]
            ):
                reason = "budget_reserved_for_selection_and_test"
                break
            trained = (
                firstBlock
                if index == 0
                else self.measured(
                    f"train-{index + 1:02}",
                    "train",
                    1600 + index * 16,
                    16,
                    checkpoint=previous,
                    calibration=controls,
                )
            )
            checkpoint = trained.parent / "checkpoint.ptz"
            previous = checkpoint
            self.status.update(completed_rounds=index + 1, train_transitions=(index + 1) * 64)
            self.heartbeat()
            if (index + 1) * 64 not in plan["validation_transitions"]:
                continue
            evaluated = self.measured(
                f"validation-{index + 1:02}", "validation", 2700, 8, checkpoint=checkpoint
            )
            result = qualify(
                checkpoint,
                trained,
                [evaluated, *baselines],
                self.output / "training-plan.json",
                controls,
            )
            candidate = self.output / f"qualification-{index + 1:02}.json"
            atomicWrite(candidate, jsonBytes(result))
            candidates.append(candidate)
            curves.append(result)
            atomicWrite(
                self.output / "curves.json", jsonBytes({"version": 4, "checkpoints": curves})
            )
            self.offline(
                f"fresh-infer-{index + 1:02}",
                [
                    "infer",
                    "--checkpoint",
                    checkpoint,
                    "--history",
                    evaluated.parent / "last-history.json",
                ],
            )
            previous = checkpoint
            self.status.update(
                completed_rounds=index + 1,
                train_transitions=(index + 1) * 64,
                last_reward=result["validation_mean_reward"],
                directional_dependence=result["directional_dependence"],
                qualified=result["qualified"],
            )
            self.heartbeat()
            if (index + 1) * 64 >= 512:
                if any(row["qualified"] and row["transitions"] >= 512 for row in curves):
                    reason = "qualified_after_minimum512"
                    break
                if not learning(curves):
                    reason = "no_quality_or_probability_learning_after_minimum512"
                    break
        if not any(row["qualified"] and row["transitions"] >= 512 for row in curves):
            self.status["test"] = "not_run_no_qualified_policy"
            return reason
        selection = selectPolicy(candidates)
        selectedPath = self.output / "selection.json"
        atomicWrite(selectedPath, jsonBytes(selection))
        checkpoint = next(
            Path(row["evidence_paths"]["checkpoint"])
            for row in curves
            if row["checkpoint"] == selection["checkpoint"]
        )
        self.status["best_checkpoint"] = selection["checkpoint"]
        if self.workDeadline - time.monotonic() < plan["test_reserve_seconds"]:
            self.status["test"] = "not_run_insufficient_reserved_budget"
            return reason
        # Ledger closes all training/validation after the first test attempt. Invalid
        # or unfavorable tests consume their identity and are never re-collected.
        tests = [
            self.measured(
                "test-" + p,
                "test",
                3900,
                12,
                p,
                checkpoint=checkpoint if p == "ppo" else None,
                selection=selectedPath,
            )
            for p in plan["test_order"]
        ]
        final = report(tests, checkpoint=checkpoint)
        if not final["comparable_held_out_schedules"]:
            raise ValueError("test schedules are not comparable")
        comparison = next(
            row["metrics"] for row in final["paired_seed_comparisons"] if row["baseline"] == "ospf"
        )
        goodput, rtt = comparison["goodput_mbps"], comparison["icmp_rtt_ms"]
        success = (
            goodput["paired_seed_count"] == rtt["paired_seed_count"] == 12
            and goodput["ci95"] is not None
            and rtt["ci95"] is not None
            and goodput["ci95"][0] > 0
            and rtt["ci95"][1] < 0
        )
        final.update(
            version=4,
            measured_ospf_improvement=success,
            scope=(
                "balanced stationary2/20Mbps degradation versus unchanged nominal-cost OSPF; "
                "ICMP RTT"
            ),
            autonomous_dispatch="blocked",
        )
        atomicWrite(self.output / "test-report.json", jsonBytes(final))
        self.status.update(
            test="completed_once_all_five_policies", measured_ospf_improvement=success
        )
        return reason


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--operator-experiment", required=True, action="store_true")
    run.add_argument("--image-id", required=True)
    run.add_argument("--release", required=True, type=Path)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--output", type=Path, required=True)
    for name in ("status", "stop", "cleanup"):
        sub = commands.add_parser(name)
        sub.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        output = outputPath(args.output, existing=args.command != "run")
        if args.command == "run":
            if output.exists():
                raise ValueError("new campaign directory required; restart/resume disabled")
            release = releaseEvidence(args.release, args.image_id)
            frozen = {
                "version": 4,
                "plan": frozenPlan(),
                "image_id": args.image_id,
                "lab_profile": labProfile(),
                "release": release,
                "client_source_sha256": clientSources(),
                "runtime_versions": runtimeVersions(),
                "output": str(output),
            }
            if args.dry_run:
                print(json.dumps(frozen, indent=2))
                return 0
            with lock(GLOBAL_LOCK):
                output.mkdir(mode=0o700)
                (output / "lab-output").mkdir(mode=0o700)
                snapshot = output / "source"
                snapshot.mkdir(mode=0o700)
                for source in sorted(Path(__file__).parent.glob("*.py")):
                    atomicWrite(snapshot / source.name, source.read_bytes())
                for name in ("pyproject.toml", "uv.lock"):
                    atomicWrite(snapshot / name, (ROOT / name).read_bytes())
                frozen["campaign_id"] = uuid.uuid4().hex
                atomicWrite(output / "plan.json", jsonBytes(frozen))
                atomicWrite(output / "release.json", jsonBytes(release))
                atomicWrite(output / "training-plan.json", jsonBytes(frozenPlan()))
                now = time.time()
                atomicWrite(
                    output / "training-plan.collection.json",
                    jsonBytes(
                        {
                            "plan_sha256": hashlib.sha256(jsonBytes(frozenPlan())).hexdigest(),
                            "started_unix": now,
                            "deadline_unix": now + 7200 - (time.monotonic() - started),
                            "attempts": [],
                        }
                    ),
                )
                with lock(output / "run.lock"):
                    return ExtendedSupervisor(output, frozen, started).run()
        frozen = readJson(output / "plan.json")
        if (
            frozen.get("version") != 4
            or frozen.get("output") != str(output)
            or not re.fullmatch(r"[a-f0-9]{32}", frozen.get("campaign_id", ""))
            or not re.fullmatch(IMAGE_PATTERN, frozen.get("image_id", ""))
        ):
            raise ValueError("invalid V4 supervisor identity")
        if args.command == "status":
            status = readJson(output / "status.json")
            status["heartbeat_stale"] = time.time() - status["heartbeat_unix"] > 10
            print(json.dumps(status, indent=2))
        elif args.command == "stop":
            atomicWrite(output / "stop.request", jsonBytes({"campaign_id": frozen["campaign_id"]}))
            print(json.dumps({"status": "stop_requested", "signals_sent": False}))
        else:
            with lock(output / "run.lock"):
                supervisor = ExtendedSupervisor(output, frozen)
                supervisor.commandIndex = max(
                    [
                        900,
                        *[
                            int(p.name.split(".")[0].split("-")[1])
                            for p in output.glob("command-*.stdout.log")
                        ],
                    ]
                )
                supervisor.hardDeadline = time.monotonic() + 110
                supervisor.status = readJson(output / "status.json")
                supervisor.status.update(stage="poststop_cleanup", child_pid=None)
                try:
                    supervisor.cleanup()
                    supervisor.status.update(stage="finished", cleanup_error=None)
                    if supervisor.status["state"] == "running":
                        supervisor.status.update(state="stopped", stop_reason="poststop_cleanup")
                except (ValueError, RuntimeError, OSError) as exc:
                    supervisor.status.update(state="failed", cleanup_error=str(exc)[:2048])
                    raise
                finally:
                    supervisor.heartbeat()
            print(json.dumps({"status": "owned_cleanup_verified"}))
        return 0
    except (
        ValueError,
        RuntimeError,
        OSError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            json.dumps({"status": "blocked_or_failed", "error": str(exc)[:2048]}), file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
