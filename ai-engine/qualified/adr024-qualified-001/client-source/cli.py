"""Operator CLI. Live commands have no synthetic transport/reward fallback."""

import argparse
import hashlib
import json
import signal
import statistics
import sys
import time
from pathlib import Path

import numpy as np

from .artifacts import (
    EvidenceLog,
    atomicWrite,
    checkDistribution,
    inspectCheckpoint,
    loadCheckpoint,
    runtimeVersions,
    saveCheckpoint,
    trainingDistribution,
)
from .contracts import (
    CONTRACT,
    CONTRACT_HASH,
    HISTORY_LENGTH,
    SPLITS,
    Observation,
    Request,
    Response,
    jsonBytes,
    parseJson,
    validateSeed,
)
from .env import InvalidMeasurement, RoutingEnv, encode, heuristic, rewardComponents
from .evidence import number, validateMeasurement
from .ppo import PPO, PPOConfig, seedRuntime
from .transport import DockerTransport


class LoggedTransport:
    def __init__(self, transport, log):
        self.transport, self.log = transport, log

    def exchange(self, request):
        started = time.monotonic()
        try:
            raw = self.transport.exchange(request)
            self.log.append(
                {
                    "kind": "ipc",
                    "request": request.model_dump(),
                    "response": raw,
                    "elapsed_seconds": time.monotonic() - started,
                }
            )
            return raw
        except (ValueError, RuntimeError) as exc:
            self.log.append(
                {
                    "kind": "ipc_failure",
                    "request": request.model_dump(),
                    "error": str(exc)[:2048],
                    "elapsed_seconds": time.monotonic() - started,
                }
            )
            raise


def runSession(args):
    if args.plan:
        from .qualification import collectionAdmission

        with collectionAdmission(args):
            return _runSession(args)
    return _runSession(args)


def _runSession(args):
    training = args.command == "train"
    split = "train" if training else args.split
    if split == "test" and not args.plan:
        raise ValueError("fresh test access requires a frozen plan and validated selection")
    startSeed = args.seed if args.seed is not None else SPLITS[split][0]
    if not 1 <= args.episodes <= 1000:
        raise ValueError("episodes must be 1..1000")
    if not 30 <= args.budget_seconds <= 600:
        raise ValueError("session budget must be 30..600 seconds")
    seeds = [validateSeed(split, startSeed + index) for index in range(args.episodes)]
    scenarios = args.scenarios.split(",")
    trainingDistribution(args.window, args.steps, scenarios)
    config = PPOConfig(
        seed=args.model_seed,
        rollout=args.rollout,
        learning_rate=args.learning_rate,
        gamma=args.gamma,
        gae_lambda=args.gae_lambda,
        epochs=args.epochs,
        entropy=args.entropy,
        minibatch=args.minibatch,
    )
    planHash = None
    if args.plan:
        from .qualification import readPlan

        plan, planHash = readPlan(args.plan)
        if (
            scenarios != plan["scenarios"]
            or args.steps != plan["steps"]
            or args.window != plan["window_seconds"]
            or args.rollout != plan["rollout"]
        ):
            raise ValueError("session configuration differs from frozen plan")
        if training:
            if plan["version"] == 4:
                from .expanded import checkTrainingBlock

                checkTrainingBlock(plan, seeds, config, args.resume)
            else:
                pilot = next(
                    (row for row in plan["pilots"] if row["model_seed"] == args.model_seed), None
                )
                if args.resume or pilot is None or seeds != pilot["train_seeds"]:
                    raise ValueError("training differs from predeclared fresh pilot")
                if config.model_dump(exclude={"seed"}) != plan["ppo_config"]:
                    raise ValueError("hyperparameters differ from frozen pilot")
        elif seeds != plan[f"{split if split != 'train' else 'calibration'}_seeds"]:
            raise ValueError("evaluation seeds differ from frozen plan")
    if args.episodes % 2 or not 4 <= args.steps <= 8 or args.rollout not in (16, 32):
        raise ValueError("v3 requires balanced even episodes, 4..8 steps and rollout 16 or 32")
    if training and args.mode != "matched":
        raise ValueError("v3 training requires matched Linux/FRR mode")
    agent, parent = None, None
    if training:
        if args.resume:
            agent, parent = loadCheckpoint(args.resume, resume=True)
            if config != parent.config:
                raise ValueError("resume hyperparameters/model seed differ from checkpoint")
            checkDistribution(parent, args.window, args.steps, scenarios=scenarios)
            if set(seeds) & set(parent.training_seeds):
                raise ValueError("resume seeds overlap previous training episodes")
            if len(seeds) + parent.episodes > 1000:
                raise ValueError("resumed episode count exceeds bound")
        else:
            agent = PPO(config)
    elif args.policy == "ppo":
        if args.checkpoint is None or args.mode != "matched":
            raise ValueError("PPO evaluation requires a measured checkpoint and matched mode")
        agent, parent = loadCheckpoint(args.checkpoint)
        checkDistribution(
            parent, args.window, args.steps, generalization=args.generalization, scenarios=scenarios
        )
        seedRuntime(args.model_seed)
    elif args.checkpoint:
        raise ValueError("only PPO evaluation accepts a checkpoint")
    if not training and (args.mode == "ospf") != (args.policy == "ospf"):
        raise ValueError("OSPF baseline requires mode=ospf and policy=ospf")
    # Validate all configuration before allocating artifacts or contacting Docker.
    transport = DockerTransport(args.container, args.timeout)
    env = RoutingEnv(
        transport,
        split=split,
        mode=args.mode,
        window_seconds=args.window,
        episode_steps=args.steps,
        expectedSpec=parent.environment_spec if parent else None,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    log = EvidenceLog(args.output / "evidence.jsonl")
    env.transport = LoggedTransport(transport, log)
    started = time.monotonic()
    rows, episodes, usedSeeds = [], [], []
    failure, cleanupError = None, None
    summary = {
        "version": 3,
        "kind": "train" if training else "evaluation",
        "provenance": "measured-lab",
        "contract_hash": CONTRACT_HASH,
        "plan_sha256": planHash,
        "contract": CONTRACT,
        "versions": runtimeVersions(),
        "split": split,
        "evaluation_role": "calibration-not-held-out"
        if not training and split == "train"
        else "held-out"
        if not training
        else "training",
        "seeds": seeds,
        "scenarios": scenarios,
        "policy": "ppo" if training else args.policy,
        "mode": args.mode,
        "window_seconds": args.window,
        "episode_steps": args.steps,
        "budget_seconds": args.budget_seconds,
        "config": agent.config.model_dump() if agent else None,
        "generalization": bool(not training and args.generalization),
        "model_seed": agent.config.seed if training else args.model_seed,
        "episodes": episodes,
        "invalid_windows": 0,
        "valid_transitions": 0,
        "action_counts": [0, 0],
        "route_changes": 0,
        "constraint_violations": {"utilization_above_capacity": 0, "queue_above_capacity": 0},
        "status": "running",
        "checkpoint": None,
        "route_efficacy": [] if training else None,
        "safety_confidence": None,
        "limitations": [
            "Short runs do not establish superiority or convergence.",
            "Probabilities are not safety confidence.",
            "Comparability requires identical Linux/FRR background routing and exogenous inputs.",
            "Capacity exceedance counters are diagnostics, not the Step 9 safety filter.",
        ],
    }
    atomicWrite(args.output / "summary.json", jsonBytes(summary))
    try:
        log.append(
            {
                "kind": "session",
                "summary": summary,
                "parent_checkpoint": parent.model_dump() if parent else None,
            }
        )
        for episodeIndex, seed in enumerate(seeds):
            if time.monotonic() - started >= args.budget_seconds:
                raise InvalidMeasurement("session wall-time budget exhausted")
            scenario = scenarios[episodeIndex % len(scenarios)]
            env.template = env.template.model_copy(update={"scenario": scenario})
            episodeStart = time.monotonic()
            try:
                state, _ = env.reset(seed=seed)
            except (ValueError, RuntimeError):
                summary["invalid_windows"] += 1
                raise
            total = 0.0
            episodeRewards = []
            for _ in range(args.steps):
                if time.monotonic() - started >= args.budget_seconds:
                    raise InvalidMeasurement("session wall-time budget exhausted")
                inferenceStart = time.perf_counter_ns()
                if agent:
                    action, logProb, value, probabilities = agent.model.decide(
                        state, deterministic=not training
                    )
                else:
                    if args.policy in ("constant0", "constant1"):
                        action = int(args.policy[-1])
                    elif args.policy == "heuristic":
                        action = heuristic(env.data.observation)
                    else:
                        action = env.data.observation.previous_action
                    logProb, value, probabilities = None, None, None
                inferenceSeconds = (time.perf_counter_ns() - inferenceStart) / 1e9
                previousObservation = env.data.observation
                inputHash = hashlib.sha256(jsonBytes(previousObservation.model_dump())).hexdigest()
                nextState, reward, terminated, truncated, info = env.step(action)
                valid = info["valid_transition"]
                log.append(
                    {
                        "kind": "decision",
                        "episode_id": env.data.episode_id,
                        "step_index": env.data.step_index,
                        "action": action,
                        "input_sha256": inputHash,
                        "inference_seconds": inferenceSeconds,
                        "probabilities": probabilities,
                        "value": value,
                        "reward": info["reward"],
                        "valid_transition": valid,
                        "terminated": terminated,
                        "truncated": truncated,
                        "error": info.get("error"),
                    }
                )
                if not valid:
                    summary["invalid_windows"] += 1
                    # Abort the session and discard pending rollout, never bridge an invalid gap.
                    rows.clear()
                    raise InvalidMeasurement(info["error"])
                total += reward
                summary["valid_transitions"] += 1
                summary["action_counts"][action] += 1
                summary["route_changes"] += int(info["reward"]["raw"]["route_change"])
                if training and info["reward"]["raw"]["route_change"]:
                    summary["route_efficacy"].append(
                        {
                            "seed": seed,
                            "step_index": env.data.step_index,
                            "requested_action": action,
                            "actual_action": env.data.observation.previous_action,
                            "readback_verified": True,
                            "goodput_delta_mbps": env.data.observation.goodput_mbps
                            - previousObservation.goodput_mbps,
                            "loss_delta": env.data.observation.loss_fraction
                            - previousObservation.loss_fraction,
                            "latency_delta_ms": (
                                env.data.observation.latency_ms - previousObservation.latency_ms
                                if env.data.observation.latency_ms is not None
                                and previousObservation.latency_ms is not None
                                else None
                            ),
                            "causal_improvement_established": False,
                            "limitation": (
                                "stationary inputs; before/after still has measurement noise"
                            ),
                        }
                    )
                violations = summary["constraint_violations"]
                violations["utilization_above_capacity"] += int(
                    max(env.data.observation.path_utilization) > 1
                )
                violations["queue_above_capacity"] += int(
                    max(env.data.observation.path_queue_packets)
                    > CONTRACT["queue_capacity_packets"]
                )
                atomicWrite(
                    args.output / "last-history.json",
                    jsonBytes({"version": 3, "frames": env.historyEvidence}),
                )
                episodeRewards.append(info["reward"])
                atomicWrite(
                    args.output / "progress.json",
                    jsonBytes(
                        {
                            "seed": seed,
                            "scenario": scenario,
                            "step_index": env.data.step_index,
                            "valid_transitions": summary["valid_transitions"],
                            "evidence_bytes": log.size,
                            "last_reward": reward,
                        }
                    ),
                )
                if training:
                    nextValue = agent.model.decide(nextState, deterministic=True)[2]
                    rows.append(
                        {
                            "state": state,
                            "action": action,
                            "log_prob": logProb,
                            "value": value,
                            "next_value": nextValue,
                            "reward": reward,
                            "terminated": terminated,
                            "truncated": truncated,
                            "valid_transition": True,
                        }
                    )
                    if len(rows) == agent.config.rollout:
                        log.append(
                            {
                                "kind": "ppo_update",
                                "metrics": agent.update(rows),
                                "updates": agent.updates,
                                "transitions": agent.transitions,
                            }
                        )
                        rows.clear()
                state = nextState
                if terminated or truncated:
                    break
            usedSeeds.append(seed)
            episodes.append(
                {
                    "seed": seed,
                    "scenario": scenario,
                    "reward": total,
                    "windows": len(episodeRewards),
                    "rewards": episodeRewards,
                    "wall_seconds": time.monotonic() - episodeStart,
                }
            )
        if training and len(rows) >= 2:
            log.append(
                {
                    "kind": "ppo_update",
                    "metrics": agent.update(rows),
                    "updates": agent.updates,
                    "transitions": agent.transitions,
                }
            )
            rows.clear()
        summary["unused_valid_tail_transitions"] = len(rows)
        if training and agent.updates == 0:
            raise InvalidMeasurement("no PPO update completed")
    except (ValueError, RuntimeError, OSError, KeyboardInterrupt) as exc:
        failure = str(exc)[:2048] or type(exc).__name__
    finally:
        try:
            env.close()
        except (ValueError, RuntimeError, OSError) as exc:
            cleanupError = str(exc)[:2048]
        try:
            log.close()
        except OSError as exc:
            failure = failure or f"evidence durability failed: {str(exc)[:1800]}"
        summary.update(
            status="failed" if failure or cleanupError else "completed",
            failure=failure,
            cleanup_error=cleanupError,
            elapsed_seconds=time.monotonic() - started,
            evidence_sha256=log.digest.hexdigest(),
            evidence_bytes=log.size,
            mean_episode_reward=float(np.mean([row["reward"] for row in episodes]))
            if episodes
            else None,
        )
        if training:
            summary.update(updates=agent.updates, transitions=agent.transitions)
        summary["environment_spec"] = env.environmentSpec
        summary["lab_provenance"] = env.labProvenance
        summary["spec_hash"] = (
            hashlib.sha256(jsonBytes(env.environmentSpec)).hexdigest()
            if env.environmentSpec
            else None
        )
        if not failure and not cleanupError:
            try:
                if training:
                    path = args.output / "checkpoint.ptz"
                    allSeeds = (parent.training_seeds if parent else []) + usedSeeds
                    saveCheckpoint(
                        path,
                        agent,
                        provenance="measured-lab",
                        trainingSeeds=allSeeds,
                        episodes=len(allSeeds),
                        evidenceHash=log.digest.hexdigest(),
                        environmentSpec=env.environmentSpec,
                        distribution=trainingDistribution(args.window, args.steps, scenarios),
                        labProvenance=env.labProvenance,
                    )
                    summary["checkpoint"] = inspectCheckpoint(path)
                elif args.checkpoint:
                    summary["checkpoint"] = inspectCheckpoint(args.checkpoint)
            except (ValueError, RuntimeError, OSError) as exc:
                failure = str(exc)[:2048]
                summary.update(status="failed", failure=failure)
        atomicWrite(args.output / "summary.json", jsonBytes(summary))
    if failure or cleanupError:
        raise InvalidMeasurement(f"session failed; inspect {args.output / 'summary.json'}")
    return {
        "status": summary["status"],
        "output": str(args.output),
        "elapsed_seconds": summary["elapsed_seconds"],
        "mean_episode_reward": summary["mean_episode_reward"],
    }


def report(paths, *, checkpoint=None):
    if not 1 <= len(paths) <= 32:
        raise ValueError("report requires 1..32 session summaries")
    summaries = []
    replayAgent, replayManifest = loadCheckpoint(checkpoint) if checkpoint else (None, None)
    for path in paths:
        with path.open("rb") as source:
            content = source.read(8 * 1024 * 1024 + 1)
        if len(content) > 8 * 1024 * 1024:
            raise ValueError("summary exceeds bound")
        value = parseJson(content)
        jsonBytes(value)
        if (
            type(value) is not dict
            or value.get("contract_hash") != CONTRACT_HASH
            or value.get("provenance") != "measured-lab"
            or value.get("contract") != CONTRACT
        ):
            raise ValueError("incompatible report evidence")
        required = {
            "kind",
            "policy",
            "mode",
            "split",
            "seeds",
            "status",
            "failure",
            "invalid_windows",
            "elapsed_seconds",
            "mean_episode_reward",
            "evidence_sha256",
            "checkpoint",
            "limitations",
            "window_seconds",
            "episode_steps",
            "scenarios",
            "episodes",
        }
        if (
            not required <= value.keys()
            or value["status"] not in ("completed", "failed")
            or value["kind"] not in ("train", "evaluation")
            or value["split"] not in SPLITS
            or type(value["seeds"]) is not list
            or not 1 <= len(value["seeds"]) <= 1000
            or len(value["seeds"]) != len(set(value["seeds"]))
            or type(value["episodes"]) is not list
            or any(
                type(row) is not dict or not {"seed", "scenario"} <= row.keys()
                for row in value["episodes"]
            )
        ):
            raise ValueError("invalid session summary")
        for seed in value["seeds"]:
            validateSeed(value["split"], seed)
        if value["policy"] not in ("ppo", "heuristic", "ospf", "constant0", "constant1"):
            raise ValueError("invalid policy in summary")
        if (value["mode"] == "ospf") != (value["policy"] == "ospf"):
            raise ValueError("reported policy/dataplane mismatch")
        trainingDistribution(value["window_seconds"], value["episode_steps"], value["scenarios"])
        if value["kind"] == "evaluation" and value["split"] == "train":
            if value.get("evaluation_role") != "calibration-not-held-out":
                raise ValueError("training-split evaluation must be labeled calibration")
        digest = hashlib.sha256()
        size = 0
        measurements, decisions, failures = [], [], []
        updates = []
        previous = None
        closeVerified = False
        labSpec = None
        labProvenance = None
        sessionCount = 0
        episodeSeeds = []
        with (path.parent / "evidence.jsonl").open("rb") as evidence:
            while chunk := evidence.readline(2 * 1024 * 1024 + 1):
                size += len(chunk)
                if size > 64 * 1024 * 1024 or len(chunk) > 2 * 1024 * 1024:
                    raise ValueError("evidence exceeds bound")
                digest.update(chunk)
                row = parseJson(chunk)
                if row["kind"] == "session":
                    sessionCount += 1
                    if sessionCount != 1 or measurements or decisions:
                        raise ValueError("session predeclaration must be first and unique")
                    if any(
                        row["summary"][key] != value[key]
                        for key in (
                            "kind",
                            "policy",
                            "mode",
                            "split",
                            "seeds",
                            "window_seconds",
                            "episode_steps",
                            "scenarios",
                            "plan_sha256",
                            "generalization",
                            "config",
                            "model_seed",
                        )
                    ):
                        raise ValueError("summary labels differ from recorded session")
                elif row["kind"] == "decision":
                    decisions.append(row)
                elif row["kind"] == "ppo_update":
                    updates.append(row)
                elif row["kind"] == "ipc_failure":
                    failures.append(row)
                elif row["kind"] == "ipc":
                    request = Request.model_validate(row["request"])
                    if (
                        request.mode != value["mode"]
                        or request.window_seconds != value["window_seconds"]
                        or request.episode_steps != value["episode_steps"]
                    ):
                        raise ValueError("summary configuration differs from wire evidence")
                    if request.command == "close":
                        raw = row["response"]
                        closeVerified = (
                            raw.get("ok") is True
                            and raw.get("error") is None
                            and raw.get("data", {}).get("closed") is True
                            and raw["data"].get("cleanup_verified") is True
                            and previous is not None
                            and raw["data"].get("episode_id") == previous.episode_id
                        )
                        continue
                    response = Response.model_validate(row["response"])
                    if not response.ok or response.data.truncated:
                        failures.append(row)
                        continue
                    data = response.data
                    spec = validateMeasurement(data, request)
                    if not sessionCount:
                        raise ValueError("missing session predeclaration")
                    if labProvenance is not None and data.evidence["provenance"] != labProvenance:
                        raise ValueError("lab provenance changed in trace")
                    labProvenance = data.evidence["provenance"]
                    if labSpec is not None and spec != labSpec:
                        raise ValueError("lab spec changed in trace")
                    labSpec = spec
                    validateSeed(value["split"], data.seed)
                    if request.command == "reset":
                        if previous is not None and not previous.terminated:
                            raise ValueError("trace reset before completed horizon")
                        episodeSeeds.append(data.seed)
                        expectedScenario = value["scenarios"][(len(episodeSeeds) - 1) % 2]
                        if data.scenario != expectedScenario:
                            raise ValueError("wire scenario differs from frozen selection")
                    elif (
                        previous is None
                        or previous.terminated
                        or data.episode_id != previous.episode_id
                        or data.step_index != previous.step_index + 1
                        or data.seed != previous.seed
                        or data.scenario != previous.scenario
                        or any(
                            getattr(data.observation, key) != getattr(previous.observation, key)
                            for key in ("offered_mbps", "background_mbps", "path_capacity_mbps")
                        )
                    ):
                        raise ValueError("out-of-order measured trace")
                    observation = data.observation
                    measurements.append(
                        {
                            "seed": data.seed,
                            "scenario": data.scenario,
                            "step_index": data.step_index,
                            "episode_id": data.episode_id,
                            "phase": data.evidence["phase"],
                            "actual_offered_mbps": data.evidence["actual_offered_mbps"],
                            "goodput_mbps": observation.goodput_mbps,
                            "loss_fraction": observation.loss_fraction,
                            "observed_latency_ms": observation.latency_ms,
                            "service_outage": data.evidence["service_outage"],
                            "action": observation.previous_action,
                            "requested_action": request.action,
                            "input": previous.observation.model_dump()
                            if request.command == "step"
                            else None,
                            "control_seconds": data.evidence["control_overhead_seconds"],
                            "ipc_seconds": row["elapsed_seconds"],
                            "background_route": (
                                data.evidence["route"]["readback"]["paths"]["h2->h4"]
                                if data.mode == "matched"
                                else data.evidence["route"].get("background_readback")
                            ),
                            "routing_policy": data.evidence["route"].get("policy"),
                            "udp_rtt": data.evidence.get("udp_rtt"),
                            **(
                                {
                                    "drain": {
                                        key: data.evidence[key]
                                        for key in (
                                            "drain_status",
                                            "drain_begin",
                                            "drain_end",
                                            "drain_duration_seconds",
                                            "late_received_packets",
                                            "udp_sent",
                                            "udp_received",
                                        )
                                    }
                                }
                                if labSpec["version"] == 4
                                else {}
                            ),
                            "reward": rewardComponents(
                                observation,
                                previous.observation.previous_action,
                                censoredDelay=data.evidence["latency_timeout_ms"],
                            )
                            if request.command == "step"
                            else None,
                        }
                    )
                    previous = data
        if digest.hexdigest() != value["evidence_sha256"]:
            raise ValueError("raw evidence digest mismatch")
        steps = [row for row in measurements if row["step_index"] > 0]
        if episodeSeeds != value["seeds"][: len(episodeSeeds)]:
            raise ValueError("summary seeds differ from wire evidence")
        if value["status"] == "completed" and (
            failures
            or not closeVerified
            or episodeSeeds != value["seeds"]
            or previous is None
            or not previous.terminated
            or len(steps) != len(value["seeds"]) * value["episode_steps"]
        ):
            raise ValueError("completed summary lacks complete measured evidence")
        validDecisions = [row for row in decisions if row.get("valid_transition") is True]
        if len(validDecisions) != len(steps):
            raise ValueError("decision trace disagrees with measured windows")
        for measured, decision in zip(steps, validDecisions, strict=True):
            if (measured["episode_id"], measured["step_index"]) != (
                decision["episode_id"],
                decision["step_index"],
            ):
                raise ValueError("decision identity differs from measurement")
            if measured["reward"] != decision["reward"]:
                raise ValueError("logged reward differs from derived reward")
            if decision["input_sha256"] != hashlib.sha256(jsonBytes(measured["input"])).hexdigest():
                raise ValueError("decision input differs from preceding measurement")
            if measured["requested_action"] != decision["action"]:
                raise ValueError("decision differs from wire action")
            if value["mode"] != "ospf" and measured["action"] != decision["action"]:
                raise ValueError("decision differs from actual route")
            if value["policy"] == "heuristic" and decision["action"] != heuristic(
                Observation.model_validate(measured["input"])
            ):
                raise ValueError("heuristic decision differs from observed pressure")
            if replayAgent and value["policy"] == "ppo" and value["kind"] == "evaluation":
                replay = replayAgent.model.decide(
                    encode([Observation.model_validate(measured["input"])]), deterministic=True
                )
                if decision["action"] != replay[0] or decision["probabilities"] != replay[3]:
                    raise ValueError("checkpoint does not reproduce measured decisions")
            if value["policy"] in ("constant0", "constant1") and (
                decision["action"] != int(value["policy"][-1])
                or measured["action"] != int(value["policy"][-1])
            ):
                raise ValueError("constant policy differs from measured action")
        if value["valid_transitions"] != len(steps) or value["invalid_windows"] != len(failures):
            raise ValueError("summary valid/invalid counts differ from trace")
        if value.get("environment_spec") != labSpec:
            raise ValueError("summary lab spec differs from trace")
        if value.get("lab_provenance") != labProvenance:
            raise ValueError("summary provenance differs from trace")
        if value["kind"] == "train" and value["status"] == "completed":
            if (
                not updates
                or updates[-1]["updates"] != value["updates"]
                or updates[-1]["transitions"] != value["transitions"]
                or value["checkpoint"]["manifest"]["updates"] != value["updates"]
                or value["checkpoint"]["manifest"]["transitions"] != value["transitions"]
            ):
                raise ValueError("training update trace differs from checkpoint counters")
        if replayManifest and labSpec != replayManifest.environment_spec:
            raise ValueError("qualification checkpoint spec differs from measured evidence")
        completedEpisodes = [
            row for row in measurements if row["step_index"] == value["episode_steps"]
        ]
        if [(row["seed"], row["scenario"]) for row in completedEpisodes] != [
            (row["seed"], row["scenario"]) for row in value["episodes"]
        ]:
            raise ValueError("episode summary differs from measured phases")
        for episode in value["episodes"]:
            rewards = [row["reward"] for row in steps if row["seed"] == episode["seed"]]
            if (
                episode["windows"] != len(rewards)
                or episode["rewards"] != rewards
                or not np.isclose(episode["reward"], sum(row["total"] for row in rewards))
            ):
                raise ValueError("episode rewards differ from measured evidence")
        if steps and value["status"] == "completed":
            reconstructedMean = sum(row["reward"]["total"] for row in steps) / len(
                completedEpisodes
            )
            if not np.isclose(value["mean_episode_reward"], reconstructedMean):
                raise ValueError("summary mean reward differs from measurements")
        value["reconstructed_phases"] = [
            {key: row[key] for key in ("seed", "scenario", "step_index", "phase")}
            for row in measurements
        ]
        value["measured_rates"] = [
            {key: row[key] for key in ("seed", "step_index", "actual_offered_mbps", "goodput_mbps")}
            for row in measurements
        ]
        value["derived_metrics"] = {
            "valid_decisions": len(steps),
            "mean_reward": statistics.mean(row["reward"]["total"] for row in steps)
            if steps
            else None,
            "mean_goodput_mbps": statistics.mean(row["goodput_mbps"] for row in steps)
            if steps
            else None,
            "mean_loss_fraction": statistics.mean(row["loss_fraction"] for row in steps)
            if steps
            else None,
            "service_outages": sum(row["service_outage"] for row in steps),
            "observed_rtt_ms": [row["observed_latency_ms"] for row in steps],
            "actual_route_counts": [
                sum(row["action"] == action for row in steps) for action in (0, 1)
            ],
            "route_changes": sum(row["reward"]["raw"]["route_change"] for row in steps),
            "timings": {
                name: {
                    "p50": float(np.percentile(samples, 50)),
                    "p95": float(np.percentile(samples, 95)),
                    "p99": float(np.percentile(samples, 99)),
                }
                if samples
                else None
                for name, samples in (
                    (
                        "inference_seconds",
                        [number(row["inference_seconds"]) for row in validDecisions],
                    ),
                    ("control_readback_seconds", [row["control_seconds"] for row in steps]),
                    ("observation_control_ipc_seconds", [row["ipc_seconds"] for row in steps]),
                )
            },
            "udp_rtt": [row["udp_rtt"] for row in steps],
        }
        value["reconstructed_steps"] = steps
        # Display clarification only: preserve stored rewards, counters and dossier schema.
        value["limitations"] = [
            *value["limitations"],
            (
                "V4 delivered totals include verified queue drain; late delivery counts remain "
                "unavailable, not inferred. Goodput uses actual sender duration including control; "
                "latency remains ICMP RTT, not UDP RTT."
                if labSpec["version"] == 4
                else "UDP loss_fraction is delivery deficit at bounded receiver cutoff, "
                "not eventual "
                "packet loss. The 250ms post-sender drain can leave queued packets uncounted "
                "(100 x 1200-byte packets take about 480ms at 2Mbps, before overhead). "
                "Goodput and reward use the same cutoff; late versus dropped is not distinguished."
            ),
        ]
        summaries.append(value)
    evaluations = [value for value in summaries if value["kind"] == "evaluation"]
    matched = len(evaluations) >= 2 and all(
        (
            value["split"],
            value["seeds"],
            value["window_seconds"],
            value["episode_steps"],
            value["reconstructed_phases"],
        )
        == (
            evaluations[0]["split"],
            evaluations[0]["seeds"],
            evaluations[0]["window_seconds"],
            evaluations[0]["episode_steps"],
            evaluations[0]["reconstructed_phases"],
        )
        and value["status"] == "completed"
        and value["invalid_windows"] == 0
        for value in evaluations
    )
    sameDataplane = all(row["mode"] in ("matched", "ospf") for row in evaluations)
    sameBackground = all(
        [(step["background_route"], step["routing_policy"]) for step in row["reconstructed_steps"]]
        == [
            (step["background_route"], step["routing_policy"])
            for step in evaluations[0]["reconstructed_steps"]
        ]
        for row in evaluations
    )
    sameSpec = all(
        row["environment_spec"] == evaluations[0]["environment_spec"]
        and row["lab_provenance"] == evaluations[0]["lab_provenance"]
        for row in evaluations
    )
    from .qualification import pairedComparison

    learned = [row for row in evaluations if row["policy"] == "ppo"]
    comparisons = (
        [
            {
                "policy_evidence_sha256": left["evidence_sha256"],
                "baseline": right["policy"],
                "baseline_evidence_sha256": right["evidence_sha256"],
                "metrics": pairedComparison(left, right),
            }
            for left in learned
            for right in evaluations
            if right["policy"] != "ppo"
        ]
        if matched and sameDataplane and sameBackground and sameSpec
        else []
    )
    return {
        "version": 3,
        "matched_offered_schedules": matched,
        "comparable_held_out_schedules": matched
        and sameDataplane
        and sameBackground
        and sameSpec
        and all(row["split"] != "train" for row in evaluations),
        "comparison_limit": (
            "OSPF L3 and OSPF-selected background placement differ from SDN; not comparable"
            if not sameDataplane or not sameBackground
            else "matched inputs do not establish policy superiority"
        ),
        "statistical_superiority_established": False,
        "paired_seed_comparisons": comparisons,
        "sessions": [
            {
                key: value[key]
                for key in (
                    "kind",
                    "policy",
                    "mode",
                    "split",
                    "seeds",
                    "status",
                    "failure",
                    "invalid_windows",
                    "elapsed_seconds",
                    "mean_episode_reward",
                    "evidence_sha256",
                    "checkpoint",
                    "limitations",
                    "derived_metrics",
                    "reconstructed_phases",
                    "measured_rates",
                    "reconstructed_steps",
                    "environment_spec",
                    "lab_provenance",
                    "generalization",
                )
            }
            for value in summaries
        ],
    }


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for command in ("train", "evaluate"):
        sub = commands.add_parser(command)
        sub.add_argument("--operator-experiment", action="store_true", required=True)
        sub.add_argument("--container", default="nanfo-experiment")
        sub.add_argument("--timeout", type=float, default=90.0)
        sub.add_argument("--budget-seconds", type=float, default=600.0)
        sub.add_argument("--output", type=Path, required=True)
        sub.add_argument("--plan", type=Path)
        sub.add_argument("--parent-approved", action="store_true")
        sub.add_argument("--lab-released", action="store_true")
        sub.add_argument("--selection", type=Path)
        sub.add_argument("--episodes", type=int, default=6)
        sub.add_argument("--steps", type=int, default=4)
        sub.add_argument("--window", type=float, default=5.0)
        sub.add_argument("--seed", type=int)
        sub.add_argument("--model-seed", type=int, default=42)
        sub.add_argument("--rollout", type=int, choices=(16, 32), default=16)
        sub.add_argument("--learning-rate", type=float, default=0.0003)
        sub.add_argument("--gamma", type=float, default=0.99)
        sub.add_argument("--gae-lambda", type=float, default=0.95)
        sub.add_argument("--epochs", type=int, default=4)
        sub.add_argument("--entropy", type=float, default=0.01)
        sub.add_argument("--minibatch", type=int, default=32)
        sub.add_argument("--scenarios", default="path0,path1")
        sub.add_argument("--mode", choices=("matched", "ospf", "sdn"), default="matched")
        if command == "train":
            sub.add_argument("--resume", type=Path)
            sub.add_argument("--calibration", type=Path, nargs=2)
        else:
            sub.add_argument(
                "--generalization",
                action="store_true",
                help="explicitly evaluate a different window or horizon; never resume",
            )
            sub.add_argument(
                "--split",
                choices=("train", "validation", "test"),
                default="test",
                help="train is calibration, never held-out evaluation",
            )
            sub.add_argument(
                "--policy",
                choices=("ppo", "heuristic", "ospf", "constant0", "constant1"),
                default="ppo",
            )
            sub.add_argument("--checkpoint", type=Path)
    sub = commands.add_parser("infer")
    sub.add_argument("--checkpoint", type=Path, required=True)
    sub.add_argument(
        "--history",
        type=Path,
        required=True,
        help="versioned one-to-three measured request/response frames",
    )
    sub.add_argument("--seed", type=int, default=42)
    sub.add_argument("--sample", action="store_true")
    sub.add_argument("--generalization", action="store_true")
    sub.add_argument("--selection", type=Path)
    sub = commands.add_parser("inspect")
    sub.add_argument("--checkpoint", type=Path, required=True)
    sub = commands.add_parser("report")
    sub.add_argument("summaries", type=Path, nargs="+")
    sub = commands.add_parser("plan")
    sub.add_argument("--output", type=Path, required=True)
    sub = commands.add_parser("qualify")
    sub.add_argument("--checkpoint", type=Path, required=True)
    sub.add_argument("--training", type=Path, required=True)
    sub.add_argument("--validation", type=Path, nargs=5, required=True)
    sub.add_argument("--calibration", type=Path, nargs=2, required=True)
    sub.add_argument("--plan", type=Path, required=True)
    sub.add_argument("--output", type=Path, required=True)
    sub = commands.add_parser("select")
    sub.add_argument("--candidates", type=Path, nargs="+", required=True)
    sub.add_argument("--output", type=Path, required=True)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    previousSignals = {}
    if args.command in ("train", "evaluate"):

        def interrupted(signum, frame):
            # Ignore further signals while runSession attempts the protocol close.
            for item in (signal.SIGTERM, signal.SIGINT):
                signal.signal(item, signal.SIG_IGN)
            raise KeyboardInterrupt("operator termination requested")

        for item in (signal.SIGTERM, signal.SIGINT):
            previousSignals[item] = signal.signal(item, interrupted)
    try:
        commandStart = time.perf_counter_ns()
        if args.command in ("train", "evaluate"):
            result = runSession(args)
        elif args.command == "inspect":
            result = inspectCheckpoint(args.checkpoint)
        elif args.command == "infer":
            agent, manifest = loadCheckpoint(args.checkpoint)
            if args.selection:
                from .qualification import validateSelection

                selection = validateSelection(args.selection)
                if (
                    args.sample
                    or args.generalization
                    or (selection["checkpoint"] != inspectCheckpoint(args.checkpoint))
                ):
                    raise ValueError(
                        "qualified inference requires exact selected deterministic policy"
                    )
            seedRuntime(args.seed)
            if str(args.history) == "-":
                content = sys.stdin.buffer.read(4 * 1024 * 1024 + 1)
            else:
                with args.history.open("rb") as source:
                    content = source.read(4 * 1024 * 1024 + 1)
            if len(content) > 4 * 1024 * 1024:
                raise ValueError("history too large")
            history = parseJson(content)
            if (
                type(history) is not dict
                or set(history) != {"version", "frames"}
                or type(history["version"]) is not int
                or history["version"] != 3
                or type(history["frames"]) is not list
                or not 1 <= len(history["frames"]) <= HISTORY_LENGTH
            ):
                raise ValueError("invalid measured history")
            observations, previous, previousRequest = [], None, None
            for frame in history["frames"]:
                request = Request.model_validate(frame["request"])
                response = Response.model_validate(frame["response"])
                if not response.ok or request.command not in ("reset", "step"):
                    raise ValueError("history requires measured reset/step frames")
                data = response.data
                if validateMeasurement(data, request) != manifest.environment_spec:
                    raise ValueError("inference lab spec differs from checkpoint")
                if data.evidence["provenance"] != manifest.lab_provenance:
                    raise ValueError("inference image/source provenance differs from checkpoint")
                checkDistribution(
                    manifest,
                    request.window_seconds,
                    request.episode_steps,
                    generalization=args.generalization,
                )
                if previous and (
                    previous.terminated
                    or data.episode_id != previous.episode_id
                    or data.seed != previous.seed
                    or data.scenario != previous.scenario
                    or data.mode != previous.mode
                    or data.step_index != previous.step_index + 1
                    or request.window_seconds != previousRequest.window_seconds
                    or request.episode_steps != previousRequest.episode_steps
                ):
                    raise ValueError("history crosses reset or skips measurements")
                if request.mode != manifest.training_distribution["mode"]:
                    raise ValueError("inference dataplane differs from training")
                observations.append(data.observation)
                previous = data
                previousRequest = request
            state = encode(observations)
            inferenceStart = time.perf_counter_ns()
            action, _, value, probabilities = agent.model.decide(
                state, deterministic=not args.sample
            )
            inferenceSeconds = (time.perf_counter_ns() - inferenceStart) / 1e9
            result = {
                "action": action,
                "probabilities": probabilities,
                "value": value,
                "input_sha256": hashlib.sha256(
                    jsonBytes(observations[-1].model_dump())
                ).hexdigest(),
                "policy_sha256": inspectCheckpoint(args.checkpoint)["checkpoint_sha256"],
                "inference_seconds": inferenceSeconds,
                "execution": "not_applied",
                "qualification_checked": args.selection is not None,
                "evidence": [observation.model_dump() for observation in observations],
                "spec_hash": manifest.spec_hash,
                "generalization": args.generalization,
                "contract_hash": CONTRACT_HASH,
                "checkpoint_weights_sha256": manifest.weights_sha256,
                "checkpoint_provenance": manifest.provenance,
            }
        elif args.command == "report":
            result = report(args.summaries)
        elif args.command == "plan":
            from .qualification import frozenPlan

            result = frozenPlan()
            with args.output.open("xb") as output:
                output.write(jsonBytes(result))
        elif args.command == "qualify":
            from .qualification import qualify

            result = qualify(
                args.checkpoint, args.training, args.validation, args.plan, args.calibration
            )
            with args.output.open("xb") as output:
                output.write(jsonBytes(result))
        elif args.command == "select":
            from .qualification import selectPolicy

            result = selectPolicy(args.candidates)
            with args.output.open("xb") as output:
                output.write(jsonBytes(result))
        if args.command == "infer":
            result["artifact_validation_and_inference_seconds"] = (
                time.perf_counter_ns() - commandStart
            ) / 1e9
        print(json.dumps(result, allow_nan=False))
        return 2 if args.command == "qualify" and not result["qualified"] else 0
    except (ValueError, RuntimeError, OSError, TypeError, KeyError, KeyboardInterrupt) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)[:2048]}), file=sys.stderr)
        return 1
    finally:
        for item, handler in previousSignals.items():
            signal.signal(item, handler)


if __name__ == "__main__":
    sys.exit(main())
