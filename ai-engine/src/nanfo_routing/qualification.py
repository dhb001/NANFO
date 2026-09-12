"""Offline evidence qualification, never authorization or a model self-attestation."""

import fcntl
import hashlib
import statistics
import time
from contextlib import contextmanager
from pathlib import Path

from .artifacts import atomicWrite, inspectCheckpoint, loadCheckpoint
from .contracts import CONTRACT_HASH, Observation, jsonBytes, parseJson
from .env import encode
from .ppo import PPOConfig

MARGIN = 0.02


def pairedComparison(policy, baseline):
    """Pair episode means by seed; windows within an episode are not independent runs."""
    metrics = {
        "reward": lambda row: row["reward"]["total"],
        "goodput_mbps": lambda row: row["goodput_mbps"],
        "loss_fraction": lambda row: row["loss_fraction"],
        "icmp_rtt_ms": lambda row: row["observed_latency_ms"],
    }
    result = {}
    for name, metric in metrics.items():
        pairs = []
        for seed in policy["seeds"]:
            left = [metric(row) for row in policy["reconstructed_steps"] if row["seed"] == seed]
            right = [metric(row) for row in baseline["reconstructed_steps"] if row["seed"] == seed]
            if not left or not right or None in left or None in right:
                continue
            pairs.append(
                {
                    "seed": seed,
                    "policy": statistics.mean(left),
                    "baseline": statistics.mean(right),
                    "delta": statistics.mean(left) - statistics.mean(right),
                }
            )
        deltas = [row["delta"] for row in pairs]
        n = len(deltas)
        mean = statistics.mean(deltas) if n else None
        # Exact two-sided Student-t .975 critical values, df=1..30. For larger n,
        # df=30 is conservative; no optional SciPy/Docker dependency in inference.
        critical = [
            12.7062,
            4.3027,
            3.1825,
            2.7764,
            2.5706,
            2.4469,
            2.3646,
            2.3061,
            2.2622,
            2.2282,
            2.2010,
            2.1789,
            2.1604,
            2.1448,
            2.1315,
            2.1199,
            2.1098,
            2.1009,
            2.0930,
            2.0860,
            2.0796,
            2.0739,
            2.0687,
            2.0639,
            2.0596,
            2.0555,
            2.0518,
            2.0485,
            2.0453,
            2.0423,
        ]
        half = critical[min(n - 2, 29)] * statistics.stdev(deltas) / n**0.5 if n > 1 else None
        result[name] = {
            "pairs": pairs,
            "paired_seed_count": n,
            "mean_delta": mean,
            "ci95": [mean - half, mean + half] if half is not None else None,
            "method": "paired seed-mean Student-t interval; normality assumption",
            "limitation": "Few seeds; exploratory uncertainty, not proof of superiority",
        }
    return result


def frozenPlan():
    return {
        "version": 3,
        "contract_hash": CONTRACT_HASH,
        "collection_budget_seconds": 1200,
        "approval": "parent must approve measurements after lab release; this file is not approval",
        "scenarios": ["path0", "path1"],
        "steps": 4,
        "window_seconds": 2.0,
        "rollout": 16,
        "ppo_config": PPOConfig().model_dump(exclude={"seed"}),
        "validation_margin_strictly_greater_than": MARGIN,
        "calibration_seeds": [1480, 1481],
        "pilots": [
            {"model_seed": seed, "train_seeds": list(range(first, first + 8))}
            for seed, first in ((41, 1500), (42, 1520), (43, 1540))
        ],
        "pilot_admission": (
            "41 first; 42 then 43 only if parent confirms time remaining; no retuning"
        ),
        "validation_seeds": [2600, 2601, 2602, 2603],
        "test_seeds": [3800, 3801, 3802, 3803],
        "baselines": ["constant0", "constant1", "heuristic", "ospf"],
        "selection": (
            "highest validation mean reward among eligible pilots; lower model seed breaks ties"
        ),
        "test": "once after selection is frozen; never tune on test; omit if budget exhausted",
        "stop": (
            "no new measurement after 1200 seconds aggregate collection; keep failures, no retries"
        ),
    }


def readPlan(path):
    with Path(path).open("rb") as source:
        content = source.read(65537)
    if len(content) > 65536:
        raise ValueError("plan exceeds bound")
    plan = parseJson(content)
    if plan.get("version") == 4:
        from .expanded import frozenPlan as expandedPlan

        if plan != expandedPlan():
            raise ValueError("plan differs from frozen ADR014 budget/seeds/gates")
        return plan, hashlib.sha256(jsonBytes(plan)).hexdigest()
    if plan != frozenPlan():
        raise ValueError("plan differs from frozen ADR013 budget/seeds/gates")
    return plan, hashlib.sha256(jsonBytes(plan)).hexdigest()


@contextmanager
def collectionAdmission(args):
    """One bounded campaign ledger, including failed/ambiguous attempts; never retry seeds."""
    plan, planHash = readPlan(args.plan)
    if not args.parent_approved or not args.lab_released:
        raise ValueError("measurements require explicit parent approval and released lab")
    if args.command == "train":
        if not args.calibration:
            raise ValueError("training requires completed train-only action-effect evidence")
        actionEffectChecks(args.calibration, plan)
    elif args.policy == "ppo":
        _, manifest = loadCheckpoint(args.checkpoint)
        if args.model_seed != manifest.config.seed:
            raise ValueError("evaluation model seed must identify its frozen pilot")
    if args.command == "evaluate" and args.split == "test":
        if not args.selection:
            raise ValueError("test requires frozen evidence-validated selection")
        selected = validateSelection(args.selection)
        if selected["plan_sha256"] != planHash:
            raise ValueError("selection plan differs")
        if args.policy == "ppo" and inspectCheckpoint(args.checkpoint) != selected["checkpoint"]:
            raise ValueError("test must use the frozen selected checkpoint")
    lockPath = args.plan.with_suffix(".collection.lock")
    ledgerPath = args.plan.with_suffix(".collection.json")
    with lockPath.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another campaign session owns collection") from exc
        now = time.time()
        ledger = (
            parseJson(ledgerPath.read_bytes())
            if ledgerPath.exists()
            else {
                "plan_sha256": planHash,
                "started_unix": now,
                "deadline_unix": now + plan["collection_budget_seconds"],
                "attempts": [],
            }
        )
        if ledger["plan_sha256"] != planHash:
            raise ValueError("collection ledger plan mismatch")
        remaining = ledger["deadline_unix"] - now
        if remaining < 210:
            raise ValueError("collection budget exhausted; cleanup reserve retained")
        split = "train" if args.command == "train" else args.split
        identity = {
            "kind": args.command,
            "split": split,
            "policy": "ppo" if args.command == "train" else args.policy,
            "model_seed": args.model_seed
            if (args.command == "train" or args.policy == "ppo") and split != "test"
            else None,
            "seed": args.seed,
            "episodes": args.episodes,
        }
        if plan["version"] == 4 and args.command == "evaluate" and args.policy == "ppo":
            identity["checkpoint_sha256"] = inspectCheckpoint(args.checkpoint)["checkpoint_sha256"]
        if any(row["identity"] == identity for row in ledger["attempts"]):
            raise ValueError("collection attempt already consumed; failed attempts cannot replay")
        if split != "test" and any(
            row["identity"]["split"] == "test" for row in ledger["attempts"]
        ):
            raise ValueError("test opened; further training/validation tuning blocked")
        args.budget_seconds = min(args.budget_seconds, remaining - 180)
        attempt = {
            "identity": identity,
            "output": str(args.output.resolve()),
            "started_unix": now,
            "status": "attempted",
        }
        ledger["attempts"].append(attempt)
        atomicWrite(ledgerPath, jsonBytes(ledger))
        try:
            yield
        finally:
            attempt["finished_unix"] = time.time()
            atomicWrite(ledgerPath, jsonBytes(ledger))


def actionEffectChecks(calibration, plan):
    from .cli import report

    calibrationResult = report(calibration)
    controls = calibrationResult["sessions"]
    if (
        len(controls) != 2
        or {row["policy"] for row in controls} != {"constant0", "constant1"}
        or not calibrationResult["matched_offered_schedules"]
        or any(
            row["split"] != "train"
            or row["seeds"] != plan["calibration_seeds"]
            or row["mode"] != "matched"
            for row in controls
        )
    ):
        raise ValueError("qualification requires matched train-only action-effect checks")
    actionEffects = {}
    for scenario, preferred in (("path0", "constant1"), ("path1", "constant0")):
        means = {
            row["policy"]: statistics.mean(
                step["reward"]["total"]
                for step in row["reconstructed_steps"]
                if step["scenario"] == scenario
            )
            for row in controls
        }
        other = "constant0" if preferred == "constant1" else "constant1"
        actionEffects[scenario] = means[preferred] - means[other]
    if any(delta <= MARGIN for delta in actionEffects.values()):
        raise ValueError("train-only directional action-effect gate did not pass")
    return controls, actionEffects


def qualify(checkpoint, training, validation, planPath, calibration):
    from .cli import report

    plan, planHash = readPlan(planPath)
    if plan["version"] == 4:
        from .expanded import qualify as expandedQualify

        return expandedQualify(checkpoint, training, validation, planPath, calibration)
    controls, actionEffects = actionEffectChecks(calibration, plan)
    agent, manifest = loadCheckpoint(checkpoint)
    identity = inspectCheckpoint(checkpoint)
    if manifest.training_distribution != {
        "mode": "matched",
        "window_seconds": plan["window_seconds"],
        "episode_steps": plan["steps"],
        "scenario_selection": "episode index modulo explicit balanced stationary curriculum",
        "scenarios": plan["scenarios"],
        "training_split": [1000, 1999],
    }:
        raise ValueError("checkpoint differs from frozen training distribution")
    pilot = next((row for row in plan["pilots"] if row["model_seed"] == manifest.config.seed), None)
    if pilot is None or pilot["train_seeds"] != manifest.training_seeds:
        raise ValueError("training seeds/model seed differ from predeclared pilot")
    if manifest.config.model_dump(exclude={"seed"}) != plan["ppo_config"]:
        raise ValueError("checkpoint hyperparameters differ from frozen pilot")
    if manifest.transitions != 32 or manifest.updates != 2:
        raise ValueError("pilot did not complete its frozen on-policy training budget")
    train = report([training], checkpoint=checkpoint)["sessions"][0]
    if (
        train["kind"] != "train"
        or train["status"] != "completed"
        or train["evidence_sha256"] != manifest.evidence_sha256
        or train["checkpoint"] != identity
        or train["seeds"] != manifest.training_seeds
    ):
        raise ValueError("checkpoint not bound to parsed completed training evidence")
    result = report(validation, checkpoint=checkpoint)
    sessions = result["sessions"]
    if not result["comparable_held_out_schedules"]:
        raise ValueError("validation is not matched complete held-out evidence")
    if sorted(row["policy"] for row in sessions) != sorted(["ppo", *plan["baselines"]]):
        raise ValueError("qualification requires PPO, BOTH constants, pressure heuristic and OSPF")
    for row, path in zip(
        [train, *sessions, *controls], [training, *validation, *calibration], strict=True
    ):
        if row["generalization"] or row["lab_provenance"] != manifest.lab_provenance:
            raise ValueError("qualification cannot use generalized or different-image evidence")
        if row["environment_spec"] != manifest.environment_spec:
            raise ValueError("calibration/training/validation specs differ")
        if not row["lab_provenance"].get("lab_image_id") or any(
            "fixture" in name.lower() for name in row["environment_spec"]["source_files"]
        ):
            raise ValueError("offline fixtures cannot qualify a policy")
        requiredSources = {
            "experiment.py",
            "workloads.py",
            "actions.py",
            "topology.py",
            "ospf.py",
            "matched.py",
            "measurements.py",
            "runner.py",
            "controller.py",
            "experiment_client.py",
            "Dockerfile",
            "requirements.txt",
            "compose.yaml",
        }
        if not requiredSources <= row["environment_spec"]["source_files"].keys():
            raise ValueError("qualification requires complete lab source provenance")
        # The plan is recorded before the first measurement, not supplied after seeing results.
        with (Path(path).parent / "evidence.jsonl").open("rb") as source:
            initial = parseJson(source.readline(2 * 1024 * 1024))
        if initial.get("kind") != "session" or initial["summary"].get("plan_sha256") != planHash:
            raise ValueError("measured session did not predeclare this plan")
    for row in sessions:
        if row["split"] != "validation" or row["seeds"] != plan["validation_seeds"]:
            raise ValueError("selection requires reserved balanced validation, never test")
        if row["policy"] == "ppo" and row["checkpoint"] != identity:
            raise ValueError("validation checkpoint identity differs")
    learned = next(row for row in sessions if row["policy"] == "ppo")
    comparisons = {
        row["policy"]: pairedComparison(learned, row) for row in sessions if row["policy"] != "ppo"
    }
    dependence = {}
    for scenario, desired in (("path0", 1), ("path1", 0)):
        steps = [row for row in learned["reconstructed_steps"] if row["scenario"] == scenario]
        if len(steps) != len(plan["validation_seeds"]) // 2 * plan["steps"]:
            raise ValueError("validation pressure scenarios are not balanced")
        correct, swappedCorrect = [], []
        for row in steps:
            observation = Observation.model_validate(row["input"])
            decision = agent.model.decide(encode([observation]), deterministic=True)
            swapped = observation.model_copy(
                update={
                    key: list(reversed(getattr(observation, key)))
                    for key in ("path_capacity_mbps", "path_utilization", "path_queue_packets")
                }
            )
            counterfactual = agent.model.decide(encode([swapped]), deterministic=True)
            correct.append(decision[0] == desired)
            swappedCorrect.append(counterfactual[0] == 1 - desired)
        dependence[scenario] = {
            "desired_route_fraction": statistics.mean(correct),
            "pressure_swap_desired_route_fraction": statistics.mean(swappedCorrect),
            "swap_is_diagnostic_not_measured_reward": True,
        }
    margins = {
        name: comparisons[name]["reward"]["mean_delta"] for name in ("constant0", "constant1")
    }
    passed = all(value > MARGIN for value in margins.values()) and all(
        row["desired_route_fraction"] > 0.5 and row["pressure_swap_desired_route_fraction"] > 0.5
        for row in dependence.values()
    )
    return {
        "version": 3,
        "qualified": passed,
        "scope": "useful adaptation on validation only",
        "checkpoint": identity,
        "plan_sha256": planHash,
        "training_evidence_sha256": train["evidence_sha256"],
        "train_only_action_effects": actionEffects,
        "calibration_evidence_sha256": {row["policy"]: row["evidence_sha256"] for row in controls},
        "validation_evidence_sha256": {row["policy"]: row["evidence_sha256"] for row in sessions},
        "minimum_margin_exclusive": MARGIN,
        "margins_over_both_constants": margins,
        "directional_dependence": dependence,
        "comparisons": comparisons,
        "validation_mean_reward": learned["derived_metrics"]["mean_reward"],
        "test_status": "not assessed; freeze selection before fresh holdout",
        "autonomous_dispatch": "blocked",
        "safety_guarantee": False,
        "limitation": "Local artifact consistency is not remote attestation or production safety",
        "evidence_paths": {
            "checkpoint": str(Path(checkpoint).resolve()),
            "training": str(Path(training).resolve()),
            "validation": [str(Path(path).resolve()) for path in validation],
            "plan": str(Path(planPath).resolve()),
            "calibration": [str(Path(path).resolve()) for path in calibration],
        },
    }


def selectPolicy(candidates):
    if candidates and parseJson(Path(candidates[0]).read_bytes()).get("version") == 4:
        from .expanded import selectPolicy as expandedSelect

        return expandedSelect(candidates)
    if not 1 <= len(candidates) <= 3:
        raise ValueError("selection requires one to three frozen pilot qualifications")
    verified = []
    for path in candidates:
        with Path(path).open("rb") as source:
            content = source.read(8 * 1024 * 1024 + 1)
        if len(content) > 8 * 1024 * 1024:
            raise ValueError("qualification artifact too large")
        saved = parseJson(content)
        paths = saved["evidence_paths"]
        actual = qualify(
            Path(paths["checkpoint"]),
            Path(paths["training"]),
            [Path(item) for item in paths["validation"]],
            Path(paths["plan"]),
            [Path(item) for item in paths["calibration"]],
        )
        if saved != actual:
            raise ValueError("qualification differs from parsed evidence; self-attestation refused")
        verified.append(actual)
    if len({row["plan_sha256"] for row in verified}) != 1:
        raise ValueError("pilot plans differ")
    seeds = [row["checkpoint"]["manifest"]["config"]["seed"] for row in verified]
    if len(seeds) != len(set(seeds)):
        raise ValueError("duplicate pilot qualification")
    planPath = Path(verified[0]["evidence_paths"]["plan"])
    ledgerPath = planPath.with_suffix(".collection.json")
    with ledgerPath.open("rb") as source:
        ledger = parseJson(source.read(128 * 1024))
    admitted = {
        row["identity"]["model_seed"]
        for row in ledger["attempts"]
        if row["identity"]["kind"] == "train"
    }
    if ledger["plan_sha256"] != verified[0]["plan_sha256"] or admitted != set(seeds):
        raise ValueError("selection must account for every admitted training pilot")
    eligible = [row for row in verified if row["qualified"]]
    if not eligible:
        raise ValueError("no pilot meets unchanged qualification gate")
    best = sorted(
        eligible,
        key=lambda row: (
            -row["validation_mean_reward"],
            row["checkpoint"]["manifest"]["config"]["seed"],
        ),
    )[0]
    return {
        "version": 3,
        "plan_sha256": best["plan_sha256"],
        "checkpoint": best["checkpoint"],
        "candidates": [str(Path(path).resolve()) for path in candidates],
        "validation_only": True,
        "autonomous_dispatch": "blocked",
    }


def validateSelection(path):
    with Path(path).open("rb") as source:
        saved = parseJson(source.read(128 * 1024))
    actual = selectPolicy(saved["candidates"])
    if saved != actual:
        raise ValueError("selection differs from evidence-validated pilot selection")
    return actual
