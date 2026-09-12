"""ADR016 finite, balanced on-policy collection and seven-method paired evaluation."""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import torch
from checkpoint import load, modelHash, save, warmstart
from contract import METHODS, UNIT, budget, qualify
from history import INCUMBENT_HASH, OLD, PARENT_HASH, ROOT, a, digest, env, parent, ppo, read, write
from preflight import OUTPUT, SCRIPT_DIR, prepare, sources
from protocol import PROFILES, Request, Transport, phase, validate, validateSchedule

Supervisor = OLD["campaign"].Supervisor
lock = OLD["campaign"].lock
GLOBAL_LOCK = OLD["campaign"].GLOBAL_LOCK


class LongCampaign(Supervisor):
    def __init__(self, output, plan):
        super().__init__(output, plan)
        self.started = time.monotonic() - max(0, time.time() - plan["started_unix"])
        self.hardDeadline = self.started + 86400
        self.workDeadline = self.hardDeadline - 180
        self.status.update(
            hard_deadline_unix=plan["started_unix"] + 86400,
            work_deadline_unix=plan["started_unix"] + 86220,
            started_unix=plan["started_unix"],
            completed_rounds=0,
            completed_sessions=0,
            train_updates=0,
            measured_decisions=0,
            default_checkpoint=INCUMBENT_HASH,
            parent_checkpoint=PARENT_HASH,
            validation_checkpoints=[],
            last_update=None,
        )
        self.secondsPerEpisode = 25.0
        self.startupSeconds = 30.0
        self.trainSeeds, self.trainHashes = [], []
        self.ledger = {"plan_sha256": plan["plan_sha256"], "attempts": []}

    def heartbeat(self):
        # Post-stop cleanup preserves terminal duration and model/session counters.
        now = time.time()
        self.status.update(heartbeat_unix=now, child_pid=self.process.pid if self.process else None)
        end = self.status.get("finished_unix", now)
        self.status["elapsed_seconds"] = max(0, end - self.frozen["started_unix"])
        write(self.output / "status.json", self.status)

    def checkSources(self):
        if (
            sources() != self.frozen["sources"]
            or a.runtimeVersions() != self.frozen["runtime_versions"]
            or digest(self.output / "plan.json") != self.frozen["plan_sha256"]
        ):
            raise ValueError("frozen ADR016 source/runtime/plan changed")
        if (
            OLD["campaign"].release(ROOT / "artifacts/adr015-release.json")
            != self.frozen["release"]
        ):
            raise ValueError("pinned V5 release changed")

    def preserve(self):
        count = 0
        for chunk in self.frozen["preservation"]:
            for name, sha in chunk.items():
                if digest(ROOT / name) != sha:
                    raise ValueError("historical incumbent/ADR015 artifact changed")
                count += 1
        return {"unchanged": True, "files": count}

    def diskUsage(self):
        total, count = 0, 0
        for path in self.output.rglob("*"):
            try:
                if path.is_symlink():
                    raise ValueError("symlink in campaign output")
                if path.is_file():
                    total += path.stat().st_size
                    count += 1
            except FileNotFoundError:
                continue  # atomic rename by the owned producer
        self.status["disk_bytes"] = total
        if (
            total >= self.frozen["disk_limit_bytes"] - self.frozen["disk_headroom_bytes"]
            or count > 50000
        ):
            raise ValueError("ADR016 monitored4GiB disk bound exhausted")

    def admit(self, session, checkpoint):
        split, rows, policy = session["split"], session["rows"], session["policy"]
        validateSchedule(split, rows)
        if any(r["stage"] == session["stage"] for r in self.ledger["attempts"]):
            raise ValueError("session attempted already; no retry")
        if split == "train":
            if (
                rows != self.frozen["training"][len(self.trainSeeds) : len(self.trainSeeds) + 32]
                or policy != "candidate"
            ):
                raise ValueError("training must consume next frozen128-transition block")
        else:
            if split == "test":
                selection = read(self.output / "selection.json")
                if (
                    not selection["qualified"]
                    or self.status["train_transitions"] != 2048
                    or (policy == "candidate" and checkpoint != selection["checkpoint_sha256"])
                ):
                    raise ValueError("test requires locked qualified2048-campaign selection")
                expected = self.frozen["test_sessions"]
            else:
                expected = self.frozen["validation_sessions"][str(self.status["train_transitions"])]
            preceding = [
                r for r in self.ledger["attempts"] if r["stage"] in {s["stage"] for s in expected}
            ]
            if len(preceding) >= len(expected) or session != expected[len(preceding)]:
                raise ValueError("counterbalanced session order differs or exhausted")

    def measured(self, session, agent=None, checkpoint=None):
        self.checkSources()
        self.check()
        self.diskUsage()
        self.admit(session, checkpoint)
        stage, rows, policy, split = (session[k] for k in ("stage", "rows", "policy", "split"))
        training = split == "train"
        attempt = {
            **session,
            "checkpoint": checkpoint,
            "started_unix": time.time(),
            "status": "attempted",
        }
        self.ledger["attempts"].append(attempt)
        write(self.output / "ledger.json", self.ledger)
        directory = self.output / stage
        directory.mkdir(mode=0o700)
        self.status.update(stage=stage, session_policy=policy, session_split=split)
        self.heartbeat()
        mode = "ospf" if policy == "ospf" else "matched"
        log = a.EvidenceLog(directory / "evidence.jsonl")
        log.append(
            {
                "kind": "session",
                "plan_sha256": self.frozen["plan_sha256"],
                "schedule": rows,
                **attempt,
            }
        )
        started = time.monotonic()
        deadline = min(
            self.workDeadline, started + max(600, len(rows) * self.secondsPerEpisode * 1.6 + 90)
        )
        episodes, rollout, rolloutProfiles = [], [], []
        data = None
        closed = False
        try:
            name = self.startLab(stage, mode)
            collectionStart = time.monotonic()
            transport = Transport(name, timeout=60)
            for row in rows:
                values = []
                for index in range(5):
                    self.check()
                    self.checkSources()
                    if time.monotonic() >= deadline:
                        raise ValueError("finite session deadline exhausted")
                    before = data.observation if index else None
                    decision = None
                    if index:
                        state = env.encode([before])
                        if policy in ("candidate", "incumbent", "candidate512"):
                            decision = agent.model.decide(state, deterministic=not training)
                            action = decision[0]
                        else:
                            action = (
                                env.heuristic(before)
                                if policy == "heuristic"
                                else int(policy == "constant1")
                            )
                    request = Request(
                        command="step" if index else "reset",
                        seed=row["seed"],
                        scenario=row["scenario"],
                        mode=mode,
                        episode_steps=4,
                        window_seconds=2.0,
                        episode_id=data.episode_id if index else None,
                        step_index=index if index else None,
                        action=action if index else None,
                    )
                    raw = transport.exchange(request)
                    log.append(
                        {
                            "kind": "measurement",
                            "request": request.model_dump(),
                            "response": raw,
                            "decision": list(decision) if decision else None,
                            "wall_unix": time.time(),
                        }
                    )
                    data = validate(
                        raw,
                        request,
                        self.frozen["release"],
                        phase(
                            row["seed"],
                            row["scenario"],
                            index,
                            self.frozen["release"]["environment_spec"],
                        ),
                    )
                    if index:
                        startAction = data.evidence["routing_health_start"]["paths"]["h1->h3"][
                            "action"
                        ]
                        if startAction != before.previous_action or any(
                            getattr(before, k) != getattr(data.observation, k)
                            for k in ("offered_mbps", "background_mbps", "path_capacity_mbps")
                        ):
                            raise ValueError("stationary observation/route drift")
                        reward = env.rewardComponents(
                            data.observation,
                            before.previous_action,
                            censoredDelay=data.evidence["latency_timeout_ms"],
                        )
                        values.append(
                            {
                                "reward": reward["total"],
                                "delivery": reward["raw"]["goodput_ratio"],
                                "changes": reward["raw"]["route_change"],
                                "rtt": data.observation.latency_ms
                                if data.observation.latency_ms is not None
                                else 1000.0,
                                "outages": int(data.evidence["service_outage"]),
                            }
                        )
                        self.status["measured_decisions"] += 1
                        if training:
                            nextValue = agent.model.decide(
                                env.encode([data.observation]), deterministic=True
                            )[2]
                            rollout.append(
                                {
                                    "state": state.tolist(),
                                    "action": action,
                                    "log_prob": decision[1],
                                    "value": decision[2],
                                    "next_value": nextValue,
                                    "reward": reward["total"],
                                    "terminated": False,
                                    "truncated": index == 4,
                                    "valid_transition": True,
                                }
                            )
                            rolloutProfiles.append(row["scenario"])
                            if len(rollout) == 32:
                                if rolloutProfiles != [p for p in PROFILES for _ in range(4)]:
                                    raise ValueError(
                                        "update does not contain all eight profiles exactly"
                                    )
                                beforeHash = modelHash(agent)
                                metrics = agent.update(rollout)
                                afterHash = modelHash(agent)
                                if beforeHash == afterHash or metrics["preclip_grad_norm"] <= 0:
                                    raise ValueError(
                                        "PPO update produced no measured gradient/weight movement"
                                    )
                                update = {
                                    "kind": "ppo_update",
                                    "transitions": agent.transitions,
                                    "updates": agent.updates,
                                    "profiles": rolloutProfiles,
                                    "model_before": beforeHash,
                                    "model_after": afterHash,
                                    "metrics": metrics,
                                    "rollout": rollout,
                                }
                                log.append(update)
                                self.status.update(
                                    train_transitions=agent.transitions,
                                    train_updates=agent.updates,
                                    last_update={k: v for k, v in update.items() if k != "rollout"},
                                )
                                rollout, rolloutProfiles = [], []
                    self.status.update(
                        current_seed=row["seed"], current_profile=row["scenario"], step=index
                    )
                    self.heartbeat()
                episodes.append(
                    {**row, **{k: statistics.mean(v[k] for v in values) for k in values[0]}}
                )
                self.diskUsage()
            if rollout:
                raise ValueError("partial PPO update at session end")
            request = Request(
                command="close",
                episode_id=data.episode_id,
                step_index=4,
                seed=data.seed,
                scenario=data.scenario,
                mode=mode,
                window_seconds=2.0,
                episode_steps=4,
            )
            raw = transport.exchange(request)
            log.append({"kind": "close", "request": request.model_dump(), "response": raw})
            if raw != {
                "version": 1,
                "ok": True,
                "error": None,
                "data": {"closed": True, "cleanup_verified": True, "episode_id": data.episode_id},
            }:
                raise ValueError("protocol cleanup not acknowledged")
            closed = True
            collectionEnd = time.monotonic()
        finally:
            log.close()
            attempt.update(finished_unix=time.time(), protocol_cleanup_verified=closed)
            write(self.output / "ledger.json", self.ledger)
            self.cleanup()
        audited = OLD["audit"].reconstruct(
            directory / "evidence.jsonl", self.frozen, rows, policy, agent if not training else None
        )
        if audited["episodes"] != episodes:
            raise ValueError("independent raw reconstruction differs")
        write(directory / "audit.json", audited)
        result = {
            "episodes": episodes,
            "evidence_sha256": audited["evidence_sha256"],
            "valid_transitions": len(rows) * 4,
            "cleanup_verified": True,
            "policy": policy,
            "split": split,
            "checkpoint": checkpoint,
        }
        write(directory / "summary.json", result)
        attempt.update(status="completed", finished_unix=time.time(), cleanup_verified=True)
        write(self.output / "ledger.json", self.ledger)
        self.secondsPerEpisode = max(
            self.secondsPerEpisode, (collectionEnd - collectionStart) / len(rows)
        )
        overhead = (time.monotonic() - started) - (collectionEnd - collectionStart)
        self.startupSeconds = max(self.startupSeconds, overhead * 1.25)
        self.status["completed_sessions"] += 1
        self.heartbeat()
        return result

    def evaluation(self, sessions, agents, hashes):
        results = {p: [] for p in METHODS}
        for session in sessions:
            p = session["policy"]
            result = self.measured(session, agents.get(p), hashes.get(p))
            results[p].extend(result["episodes"])
        return results

    def campaign(self):
        self.checkSources()
        self.exclusiveLab()
        write(self.output / "preservation-start.json", self.preserve())
        agent, _ = warmstart()
        baseline, _, _ = OLD["frozen"].incumbent()
        parentAgent, _ = parent()
        ppo.seedRuntime(self.frozen["ppo_config"]["seed"])
        write(
            self.output / "initialization.json",
            {
                "parent": PARENT_HASH,
                "initial_model_sha256": modelHash(agent),
                "parent_model_sha256": modelHash(parentAgent),
                "optimizer_state_entries": len(agent.optimizer.state),
                "fresh_updates": agent.updates,
                "fresh_transitions": agent.transitions,
                "initialization": self.frozen["initialization"],
                "historical_samples_used": False,
            },
        )
        candidates = []
        for block in range(16):
            remainingValidation = (2 - len(candidates)) * 448
            remainingValidationSessions = (2 - len(candidates)) * 56
            admission = budget(
                self.hardDeadline - time.monotonic(),
                (16 - block) * 32 + remainingValidation,
                16 - block + remainingValidationSessions,
                self.secondsPerEpisode,
                startup=self.startupSeconds,
            )
            self.status["budget_admission"] = admission
            if not admission["admitted"]:
                return "insufficient_budget_for_remaining_training_validation_final"
            count = (block + 1) * 128
            rows = self.frozen["training"][block * 32 : (block + 1) * 32]
            result = self.measured(
                {
                    "stage": f"train-{count:04}",
                    "split": "train",
                    "policy": "candidate",
                    "rows": rows,
                },
                agent,
            )
            self.trainSeeds.extend(r["seed"] for r in rows)
            self.trainHashes.append(result["evidence_sha256"])
            path = self.output / f"candidate-{count:04}.ptz"
            sha = save(path, agent, self.frozen, self.trainSeeds, self.trainHashes)
            self.status.update(
                completed_rounds=block + 1,
                latest_checkpoint=str(path),
                latest_checkpoint_sha256=sha,
            )
            self.heartbeat()
            if count not in self.frozen["validation_checkpoints"]:
                continue
            rng = torch.get_rng_state()
            evaluated, _ = load(path, sha, self.frozen)
            values = self.evaluation(
                self.frozen["validation_sessions"][str(count)],
                {"candidate": evaluated, "candidate512": parentAgent, "incumbent": baseline},
                {"candidate": sha, "candidate512": PARENT_HASH, "incumbent": INCUMBENT_HASH},
            )
            gates = qualify(values["candidate"], values["incumbent"], values["candidate512"])
            gates.update(
                transitions=count,
                checkpoint=str(path),
                checkpoint_sha256=sha,
                validation_reward=statistics.mean(r["reward"] for r in values["candidate"]),
            )
            candidates.append(gates)
            write(
                self.output / f"validation-{count}.json",
                {"policies": values, "qualification": gates},
            )
            write(self.output / "candidates.json", {"checkpoints": candidates})
            self.status["validation_checkpoints"] = [
                {k: r[k] for k in ("transitions", "qualified", "validation_reward")}
                for r in candidates
            ]
            self.heartbeat()
            torch.set_rng_state(rng)
        eligible = [r for r in candidates if r["qualified"]]
        if not eligible:
            return "no_qualified_candidate_final_unopened"
        selected = min(eligible, key=lambda r: (-r["validation_reward"], r["transitions"]))
        write(self.output / "selection.json", selected)
        (self.output / "selection.json").chmod(0o400)
        admission = budget(
            self.hardDeadline - time.monotonic(),
            896,
            112,
            self.secondsPerEpisode,
            finalReserve=False,
            startup=self.startupSeconds,
        )
        self.status["budget_admission"] = admission
        if not admission["admitted"]:
            return "qualified_but_insufficient_final_budget"
        candidate, _ = load(
            Path(selected["checkpoint"]), selected["checkpoint_sha256"], self.frozen
        )
        values = self.evaluation(
            self.frozen["test_sessions"],
            {"candidate": candidate, "candidate512": parentAgent, "incumbent": baseline},
            {
                "candidate": selected["checkpoint_sha256"],
                "candidate512": PARENT_HASH,
                "incumbent": INCUMBENT_HASH,
            },
        )
        gates = qualify(
            values["candidate"],
            values["incumbent"],
            values["candidate512"],
            final=True,
            endpoints=selected["endpoints"],
        )
        write(
            self.output / "final.json",
            {
                "policies": values,
                "qualification": gates,
                "promotion": "human_review_only" if gates["qualified"] else "research_only",
            },
        )
        return (
            "final_pass_no_automatic_promotion"
            if gates["qualified"]
            else "final_failed_default_retained"
        )

    def run(self):
        code = super().run()
        self.status["finished_unix"] = time.time()
        self.heartbeat()
        write(
            self.output / "outcome.json",
            {
                "state": self.status["state"],
                "reason": self.status["stop_reason"],
                "transitions": self.status["train_transitions"],
                "updates": self.status["train_updates"],
                "test_attempts": sum(r["split"] == "test" for r in self.ledger["attempts"]),
                "default": INCUMBENT_HASH,
                "autonomous_dispatch": "blocked",
                "preservation": self.preserve(),
                "cleanup_error": self.status["cleanup_error"],
            },
        )
        return code


def cleanup():
    if not OUTPUT.exists():
        return
    with lock(OUTPUT / "run.lock"):
        plan = read(OUTPUT / "plan.json")
        plan["plan_sha256"] = digest(OUTPUT / "plan.json")
        runner = LongCampaign(OUTPUT, plan)
        runner.status = read(OUTPUT / "status.json")
        runner.hardDeadline = time.monotonic() + 170
        runner.commandIndex = max(
            [
                9000,
                *[
                    int(p.name.split(".")[0].split("-")[1])
                    for p in OUTPUT.glob("command-*.stdout.log")
                ],
            ]
        )
        runner.cleanup()
        if runner.status["state"] == "running":
            runner.status.update(
                state="stopped",
                stage="finished",
                finished_unix=time.time(),
                stop_reason="external_stop_owned_cleanup_verified",
            )
        runner.heartbeat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run", "status", "stop", "cleanup"))
    parser.add_argument("--parent-approved", action="store_true")
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(read(OUTPUT / "status.json")))
        return 0
    if args.command == "stop":
        write(OUTPUT / "stop.request", {"operator_stop": True, "time": time.time()})
        return 0
    if args.command == "cleanup":
        cleanup()
        return 0
    if args.command == "preflight":
        plan = prepare()
        print(
            json.dumps(
                {
                    "ready": True,
                    "preserved_files": sum(map(len, plan["preservation"])),
                    "audited_seed_files": sum(map(len, plan["prior_seed_audit"]["sources"])),
                    "parent": PARENT_HASH,
                    "image": plan["image_id"],
                }
            )
        )
        return 0
    if not args.parent_approved or not os.environ.get("INVOCATION_ID"):
        raise ValueError("parent approval and capped systemd user invocation required")
    properties = subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            UNIT,
            "--property=RuntimeMaxUSec,TimeoutStopUSec,Restart,KillMode,ExecStopPost,CPUQuotaPerSecUSec",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    if (
        not all(
            r in properties.splitlines()
            for r in (
                "RuntimeMaxUSec=1d",
                "TimeoutStopUSec=3min",
                "Restart=no",
                "KillMode=control-group",
                "CPUQuotaPerSecUSec=2s",
            )
        )
        or "runner.py cleanup" not in properties
    ):
        raise ValueError("actual systemd cap/resources/cleanup not enforced")
    if OUTPUT.exists():
        raise ValueError("output exists; no restart/replay")
    with lock(GLOBAL_LOCK):
        plan = prepare()
        OUTPUT.mkdir(mode=0o700)
        (OUTPUT / "lab-output").mkdir(mode=0o700)
        (OUTPUT / "source").mkdir(mode=0o700)
        for path in SCRIPT_DIR.glob("*.py"):
            a.atomicWrite(OUTPUT / "source" / path.name, path.read_bytes())
        write(OUTPUT / "plan.json", plan)
        (OUTPUT / "plan.json").chmod(0o400)
        plan["plan_sha256"] = digest(OUTPUT / "plan.json")
        with lock(OUTPUT / "run.lock"):
            return LongCampaign(OUTPUT, plan).run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (
        ValueError,
        RuntimeError,
        OSError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({"state": "failed", "error": str(exc)[:2048]}), file=sys.stderr)
        sys.exit(1)
