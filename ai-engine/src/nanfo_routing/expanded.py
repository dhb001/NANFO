"""ADR014 plan and measured qualification V4. No training from archived observations."""

import statistics
from pathlib import Path

from .artifacts import (
    inspectCheckpoint,
    loadCheckpoint,
    loadCheckpointIdentity,
    trainingDistribution,
)
from .contracts import CONTRACT_HASH, Observation, parseJson
from .env import encode
from .ppo import PPOConfig
from .qualification import MARGIN, actionEffectChecks, pairedComparison, readPlan


def frozenPlan():
    return {
        "version": 4,
        "adr": "ADR-014",
        "contract_hash": CONTRACT_HASH,
        "collection_budget_seconds": 7200,
        "cleanup_reserve_seconds": 120,
        "test_reserve_seconds": 1800,
        "scenarios": ["path0", "path1"],
        "steps": 4,
        "window_seconds": 2.0,
        "rollout": 16,
        "model_seed": 44,
        "ppo_config": PPOConfig(seed=44, learning_rate=0.003, gamma=0.9).model_dump(),
        "hyperparameter_rationale": (
            "Fixed before collection: .003 candidate for measurable on-policy movement; "
            "gamma .9 discounts noisy distant value in a four-decision stationary episode. "
            "GAE lambda .95, four epochs, separate 32-unit actor/critic unchanged. "
            "No validation/test hyperparameter search or prior-data warmstart."
        ),
        "calibration_seeds": [1580, 1581],
        "train_seeds": list(range(1600, 1856)),
        "validation_seeds": list(range(2700, 2708)),
        "test_seeds": list(range(3900, 3912)),
        "checkpoint_transitions": list(range(64, 1025, 64)),
        "validation_transitions": list(range(128, 1025, 128)),
        "minimum_quality_stop_transitions": 512,
        "maximum_transitions": 1024,
        "baseline_order": ["constant0", "constant1", "heuristic", "ospf"],
        "baselines": ["constant0", "constant1", "heuristic", "ospf"],
        "test_order": ["ospf", "constant1", "ppo", "constant0", "heuristic"],
        "validation_margin_strictly_greater_than": MARGIN,
        "qualification": (
            "actual majority correct route in BOTH directions AND >.02 over BOTH constants"
        ),
        "pressure_swap": "diagnostic only; inconsistent synthetic observations cannot veto",
        "selection": "highest eligible validation mean; earliest tie; minimum512",
        "extension": (
            "after512 continue if reward OR minimum directional probability "
            "improved >.02 over previous256"
        ),
        "test": "all five policies once on12 paired seeds, no retries/tuning; CI uses seed means",
        "success": "OSPF paired12-seed goodput CI lower>0 AND ICMP RTT CI upper<0",
        "baseline_repeatability": (
            "single pass per policy; no repeatability established; fixed order timing reported"
        ),
        "autonomous_dispatch": "blocked",
    }


def checkTrainingBlock(plan, seeds, config, resume):
    if config.model_dump() != plan["ppo_config"]:
        raise ValueError("hyperparameters differ from frozen ADR014 plan")
    preceding = []
    if resume:
        _, parent = loadCheckpoint(resume, resume=True)
        preceding = parent.training_seeds
        if (
            parent.config != config
            or parent.transitions != len(preceding) * plan["steps"]
            or parent.updates != parent.transitions // plan["rollout"]
            or parent.environment_spec.get("version") != 4
        ):
            raise ValueError("resume must be exact V4 measured on-policy lineage")
    if (
        len(seeds) != 16
        or len(preceding) % 16
        or preceding != plan["train_seeds"][: len(preceding)]
        or seeds != plan["train_seeds"][len(preceding) : len(preceding) + 16]
    ):
        raise ValueError("training must consume next unique frozen64-transition block")


def directionalDependence(agent, learned, plan):
    result = {}
    for scenario, desired in (("path0", 1), ("path1", 0)):
        steps = [row for row in learned["reconstructed_steps"] if row["scenario"] == scenario]
        if len(steps) != len(plan["validation_seeds"]) // 2 * plan["steps"]:
            raise ValueError("validation directions must be balanced")
        correct, probabilities, swappedCorrect = [], [], []
        for row in steps:
            observation = Observation.model_validate(row["input"])
            decision = agent.model.decide(encode([observation]), deterministic=True)
            if row["action"] != decision[0]:
                raise ValueError("actual path differs from deterministic checkpoint replay")
            correct.append(row["action"] == desired)
            probabilities.append(decision[3][desired])
            swapped = observation.model_copy(
                update={
                    key: list(reversed(getattr(observation, key)))
                    for key in ("path_capacity_mbps", "path_utilization", "path_queue_packets")
                }
            )
            swappedCorrect.append(
                agent.model.decide(encode([swapped]), deterministic=True)[0] == 1 - desired
            )
        result[scenario] = {
            "desired_route_fraction": statistics.mean(correct),
            "mean_desired_probability": statistics.mean(probabilities),
            "pressure_swap_desired_route_fraction": statistics.mean(swappedCorrect),
            "swap_is_diagnostic_not_measured_reward": True,
        }
    return result


def qualify(checkpoint, training, validation, planPath, calibration):
    from .cli import report

    checkpoint, training, planPath = map(Path, (checkpoint, training, planPath))
    validation, calibration = [list(map(Path, paths)) for paths in (validation, calibration)]
    plan, planHash = readPlan(planPath)
    controls, effects = actionEffectChecks(calibration, plan)
    agent, manifest, identity = loadCheckpointIdentity(checkpoint)
    if (
        manifest.config.model_dump() != plan["ppo_config"]
        or manifest.environment_spec.get("version") != 4
        or manifest.training_distribution != trainingDistribution(2.0, 4)
        or manifest.transitions not in plan["checkpoint_transitions"]
        or manifest.updates != manifest.transitions // 16
        or manifest.training_seeds != plan["train_seeds"][: manifest.transitions // 4]
    ):
        raise ValueError("checkpoint differs from frozen V4 on-policy budget/spec/config")
    # Walk every saved parent, not just the final64 transitions. Each block binds its
    # raw session parent manifest to the preceding actual checkpoint and seed prefix.
    trainPaths, trains = [], []
    path = Path(training)
    expected = identity
    while True:
        train = report([path])["sessions"][0]
        with (path.parent / "evidence.jsonl").open("rb") as source:
            initial = parseJson(source.readline(2 * 1024 * 1024))
        m = expected["manifest"]
        count = m["transitions"] // 4
        if (
            train["kind"] != "train"
            or train["split"] != "train"
            or train["status"] != "completed"
            or train["checkpoint"] != expected
            or train["evidence_sha256"] != m["evidence_sha256"]
            or train["seeds"] != plan["train_seeds"][count - 16 : count]
            or m["training_seeds"] != plan["train_seeds"][:count]
            or m["config"] != plan["ppo_config"]
            or m["updates"] != count // 4
            or initial["summary"]["config"] != plan["ppo_config"]
            or initial["summary"]["model_seed"] != plan["model_seed"]
        ):
            raise ValueError("incomplete or mismatched measured training lineage")
        trainPaths.append(path)
        trains.append(train)
        parent = initial["parent_checkpoint"]
        if count == 16:
            if parent is not None:
                raise ValueError("fresh V4 model cannot warmstart")
            break
        if count < 16 or len(trains) > 16:
            raise ValueError("invalid training lineage length")
        path = path.parent.parent / f"train-{count // 16 - 1:02}" / "summary.json"
        expected = inspectCheckpoint(path.parent / "checkpoint.ptz")
        if parent != expected["manifest"] or parent["transitions"] != (count - 16) * 4:
            raise ValueError("parent checkpoint not bound to preceding measured block")
    result = report(validation, checkpoint=checkpoint)
    sessions = result["sessions"]
    if not result["comparable_held_out_schedules"] or sorted(
        row["policy"] for row in sessions
    ) != sorted(["ppo", *plan["baselines"]]):
        raise ValueError("qualification requires matched PPO, BOTH constants, heuristic and OSPF")
    for row, path in zip(
        [*trains, *sessions, *controls], [*trainPaths, *validation, *calibration], strict=True
    ):
        if (
            row["generalization"]
            or row["environment_spec"] != manifest.environment_spec
            or row["lab_provenance"] != manifest.lab_provenance
            or not row["lab_provenance"].get("lab_image_id")
            or any("fixture" in name.lower() for name in row["environment_spec"]["source_files"])
        ):
            raise ValueError("V4 qualification requires identical actual released lab provenance")
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
        if set(row["environment_spec"]["source_files"]) != requiredSources:
            raise ValueError("qualification requires complete released source provenance")
        with (Path(path).parent / "evidence.jsonl").open("rb") as source:
            initial = parseJson(source.readline(2 * 1024 * 1024))
        if initial["summary"].get("plan_sha256") != planHash:
            raise ValueError("evidence did not predeclare V4 plan")
    for row in sessions:
        if row["split"] != "validation" or row["seeds"] != plan["validation_seeds"]:
            raise ValueError("qualification requires frozen validation, never test")
        if row["policy"] == "ppo" and row["checkpoint"] != identity:
            raise ValueError("validation checkpoint identity differs")
    learned = next(row for row in sessions if row["policy"] == "ppo")
    comparisons = {
        row["policy"]: pairedComparison(learned, row) for row in sessions if row["policy"] != "ppo"
    }
    dependence = directionalDependence(agent, learned, plan)
    margins = {key: comparisons[key]["reward"]["mean_delta"] for key in ("constant0", "constant1")}
    return {
        "version": 4,
        "qualified": all(value > MARGIN for value in margins.values())
        and all(row["desired_route_fraction"] > 0.5 for row in dependence.values()),
        "checkpoint": identity,
        "plan_sha256": planHash,
        "training_evidence_sha256": [row["evidence_sha256"] for row in reversed(trains)],
        "train_only_action_effects": effects,
        "directional_dependence": dependence,
        "margins_over_both_constants": margins,
        "comparisons": comparisons,
        "validation_mean_reward": learned["derived_metrics"]["mean_reward"],
        "transitions": manifest.transitions,
        "updates": manifest.updates,
        "autonomous_dispatch": "blocked",
        "safety_guarantee": False,
        "test_status": "not assessed",
        "evidence_paths": {
            "checkpoint": str(Path(checkpoint).resolve()),
            "training": str(Path(training).resolve()),
            "validation": [str(Path(p).resolve()) for p in validation],
            "calibration": [str(Path(p).resolve()) for p in calibration],
            "plan": str(Path(planPath).resolve()),
        },
    }


def selectPolicy(candidates):
    if not 1 <= len(candidates) <= 16:
        raise ValueError("V4 selection requires bounded checkpoint candidates")
    verified = []
    for path in candidates:
        saved = parseJson(Path(path).read_bytes())
        p = saved["evidence_paths"]
        actual = qualify(
            p["checkpoint"], p["training"], p["validation"], p["plan"], p["calibration"]
        )
        if actual != saved:
            raise ValueError("qualification self-attestation refused")
        verified.append(actual)
    first = verified[0]
    plan, planHash = readPlan(first["evidence_paths"]["plan"])
    counts = [row["transitions"] for row in verified]
    if counts != plan["validation_transitions"][: len(counts)] or any(
        row["plan_sha256"] != planHash for row in verified
    ):
        raise ValueError("selection must account for every ordered V4 checkpoint")
    ledger = parseJson(
        Path(first["evidence_paths"]["plan"]).with_suffix(".collection.json").read_bytes()
    )
    trained = [row for row in ledger["attempts"] if row["identity"]["kind"] == "train"]
    if ledger["plan_sha256"] != planHash or len(trained) != len(counts) * 2:
        raise ValueError("selection must account for every admitted training block")
    eligible = [row for row in verified if row["qualified"] and row["transitions"] >= 512]
    if not eligible:
        raise ValueError("no V4 checkpoint qualifies after minimum512 transitions")
    best = sorted(eligible, key=lambda row: (-row["validation_mean_reward"], row["transitions"]))[0]
    return {
        "version": 4,
        "plan_sha256": planHash,
        "checkpoint": best["checkpoint"],
        "candidates": [str(Path(p).resolve()) for p in candidates],
        "validation_only": True,
        "autonomous_dispatch": "blocked",
    }
