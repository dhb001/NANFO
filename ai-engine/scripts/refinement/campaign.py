"""Single authorized ADR015 campaign. Must run within capped user systemd service."""

import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

import torch
from audit import reconstruct
from evidence import Request, Transport, phase, validate, validateSpec
from frozen import ORIGINAL, PARENT_HASH, ROOT, digest, incumbent, module
from model import load, save, warmstart
from plan import POLICIES, admission, compare, declaration

# Lifecycle reuse is independent of checkpoint loading. Its ROOT is the workspace,
# whereas the incumbent loader above imports only its original copied source.
from nanfo_routing.supervisor import GLOBAL_LOCK, Supervisor, lock

a = module("artifacts")
c = module("contracts")
env = module("env")
OUTPUT = ROOT / "artifacts/adr015-002"
FAILED_ATTEMPT = ROOT / "artifacts/adr015-001"
SCRIPT = Path(__file__).resolve()


def write(path, value):
    a.atomicWrite(path, c.jsonBytes(value))


def read(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("oversized refinement JSON")
    return c.parseJson(path.read_bytes())


def sources():
    return {p.name: digest(p) for p in sorted(SCRIPT.parent.glob("*.py"))}


def lifecycleSources():
    return {p.name: digest(p) for p in sorted((ROOT / "src/nanfo_routing").glob("*.py"))}


def priorSeeds():
    """Check attempted ledgers AND actual metadata, not unused reserved old ranges."""
    used, evidence = set(), {}
    for directory in (ROOT / "artifacts").iterdir():
        if not directory.is_dir() or directory == OUTPUT:
            continue
        paths = [
            *directory.glob("*.collection.json"),
            *directory.glob("*ledger*.json"),
            *directory.glob("**/summary.json"),
        ]
        for path in sorted(set(paths)):
            row = read(path)
            seeds = set(row.get("seeds", []))
            for attempt in row.get("attempts", []):
                identity = attempt.get("identity", attempt)
                if "seed" in identity and "episodes" in identity:
                    seeds.update(range(identity["seed"], identity["seed"] + identity["episodes"]))
                seeds.update(identity.get("seeds", []))
                # New V5 ledger reserves a whole stage but only its actual raw
                # measured seeds are consumed after a failed instrumentation run.
                if "schedule" in identity and identity.get("status") == "completed":
                    seeds.update(r["seed"] for r in identity["schedule"])
            if seeds:
                if any(type(s) is not int for s in seeds):
                    raise ValueError("malformed prior seed ledger")
                used.update(seeds)
                evidence[str(path.relative_to(ROOT))] = {
                    "sha256": digest(path),
                    "seeds": sorted(seeds),
                }
    _, metadata, _ = incumbent()
    used.update(metadata.training_seeds)
    reserved = {
        row["seed"] for split in ("training", "validation", "test") for row in declaration()[split]
    }
    if used & reserved:
        raise ValueError(f"new seeds overlap prior attempted evidence: {sorted(used & reserved)}")
    if not any("adr013-001/plan.collection.json" in p for p in evidence) or not any(
        "adr014-001/training-plan.collection.json" in p for p in evidence
    ):
        raise ValueError("required prior campaign ledgers absent")
    return evidence


def release(path):
    row = read(path)
    if row.get("released") is not True or not re.fullmatch(
        r"sha256:[a-f0-9]{64}", row.get("image_id", "")
    ):
        raise ValueError("completed lab-owner V5 release required")
    spec = row["environment_spec"]
    validateSpec(spec, spec)
    if hashlib.sha256(c.jsonBytes(spec)).hexdigest() != row["spec_hash"]:
        raise ValueError("release spec hash differs")
    for name, sha in spec["source_files"].items():
        if Path(name).name != name or digest(ROOT.parent / "emulation" / name) != sha:
            raise ValueError("lab source changed since release")
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
    if set(spec["source_files"]) != requiredSources:
        raise ValueError("incomplete released lab source inventory")
    if spec["schedule_version"] != "seeded-stationary-profiles-v5":
        raise ValueError("uninspected V5 schedule")
    return row


def prepare(releasePath):
    _, parent, _ = incumbent()
    historical = {}
    for directory in (ORIGINAL, ROOT / "artifacts/adr014-holdout-001"):
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix in (
                ".json",
                ".jsonl",
                ".ptz",
                ".py",
                ".toml",
                ".lock",
            ):
                if path.name.endswith(".lock") and path.name != "uv.lock":
                    continue
                historical[str(path.relative_to(ROOT))] = digest(path)
    failed = read(FAILED_ATTEMPT / "status.json")
    failedPlan = read(FAILED_ATTEMPT / "plan.json")
    if (
        failed["state"] != "failed"
        or failed["train_transitions"] != 0
        or failed["container_id"] is not None
        or failed["cleanup_error"] is not None
        or failed["error"] != "not a JSON type"
    ):
        raise ValueError("only zero-update serialization failure permits recorded recovery")
    failedEvidence = FAILED_ATTEMPT / "train-128/evidence.jsonl"
    with failedEvidence.open("rb") as source:
        records = [c.parseJson(line) for line in source]
    if any(r["kind"] == "ppo_update" for r in records):
        raise ValueError("failed attempt updated weights; recovery refused")
    for path in (FAILED_ATTEMPT / "lab-output").glob("experiment-*.json"):
        if (
            re.fullmatch(r"experiment-[0-9a-f-]{36}-[0-9]{2}\.json", path.name)
            and read(path).get("seed") != 1800
        ):
            raise ValueError("unexpected consumed recovery seed")
    return {
        **declaration(),
        "campaign_id": uuid.uuid4().hex,
        "output": str(OUTPUT),
        "release": release(releasePath),
        "release_path": str(releasePath.resolve()),
        "image_id": release(releasePath)["image_id"],
        "prior_seed_evidence": priorSeeds(),
        "parent_checkpoint_sha256": PARENT_HASH,
        "parent_source_sha256": parent.client_source_files,
        "parent_environment_spec": parent.environment_spec,
        "parent_preservation": historical,
        "refinement_sources": sources(),
        "runtime_versions": a.runtimeVersions(),
        "lifecycle_sources": lifecycleSources(),
        "started_unix": failedPlan["started_unix"],
        "recovery": {
            "reason": "tuple decision rejected by JSON logger; zero PPO updates",
            "failed_attempt": str(FAILED_ATTEMPT),
            "consumed_seed": 1800,
            "failed_plan_sha256": digest(FAILED_ATTEMPT / "plan.json"),
            "failed_evidence_sha256": digest(failedEvidence),
            "fresh_train_starts": 1808,
            "same_original_deadline": True,
            "validation_test_attempts": 0,
        },
    }


class Campaign(Supervisor):
    def __init__(self, output, frozen):
        super().__init__(output, frozen)
        self.hardDeadline = self.started + max(0, frozen["started_unix"] + 14400 - time.time())
        self.workDeadline = self.hardDeadline - 120
        self.status.update(
            hard_deadline_unix=frozen["started_unix"] + 14400,
            work_deadline_unix=frozen["started_unix"] + 14280,
            default_checkpoint=PARENT_HASH,
            validation_checkpoints=[],
        )
        self.secondsPerEpisode = 25.0
        self.agent = None
        self.trainSeeds = []
        self.trainHashes = []
        self.ledger = {"plan_sha256": frozen["plan_sha256"], "attempts": []}

    def checkSources(self):
        if (
            sources() != self.frozen["refinement_sources"]
            or a.runtimeVersions() != self.frozen["runtime_versions"]
            or lifecycleSources() != self.frozen["lifecycle_sources"]
        ):
            raise ValueError("refinement runtime changed during frozen campaign")
        if release(Path(self.frozen["release_path"])) != self.frozen["release"]:
            raise ValueError("lab release changed")
        if digest(self.output / "plan.json") != self.frozen["plan_sha256"]:
            raise ValueError("frozen preregistration changed")

    def preserve(self):
        for path, sha in self.frozen["parent_preservation"].items():
            if digest(ROOT / path) != sha:
                raise ValueError("incumbent frozen artifacts changed")
        return {
            "unchanged": True,
            "files": len(self.frozen["parent_preservation"]),
            "checkpoint_sha256": PARENT_HASH,
        }

    def measured(self, stage, split, rows, policy, agent=None, checkpoint=None):
        self.checkSources()
        self.check()
        if any(attempt["stage"] == stage for attempt in self.ledger["attempts"]):
            raise ValueError("attempt already consumed; no retry")
        training = split == "train"
        if training:
            start = len(self.trainSeeds)
            if rows != self.frozen["training"][start : start + 32] or policy != "candidate":
                raise ValueError("training must consume next unique frozen128-transition block")
        elif split == "validation":
            if rows != self.frozen["validation"]:
                raise ValueError("validation schedule differs")
        elif split == "test":
            selection = read(self.output / "selection.json")
            attempted = [r for r in self.ledger["attempts"] if r["split"] == "test"]
            if (
                rows != self.frozen["test"]
                or len(attempted) >= 6
                or policy != self.frozen["test_order"][len(attempted)]
                or not selection["eligible"]
                or selection["transitions"] < 256
                or (policy == "candidate" and checkpoint != selection["checkpoint_sha256"])
            ):
                raise ValueError("test selection/order/schedule differs or consumed")
        else:
            raise ValueError("invalid split")
        attempt = {
            "stage": stage,
            "split": split,
            "schedule": rows,
            "policy": policy,
            "checkpoint": checkpoint,
            "started_unix": time.time(),
            "status": "attempted",
        }
        self.ledger["attempts"].append(attempt)
        write(self.output / "ledger.json", self.ledger)
        directory = self.output / stage
        directory.mkdir(mode=0o700)
        self.status.update(stage=stage, child_progress=None)
        self.heartbeat()
        mode = "ospf" if policy == "ospf" else "matched"
        name = self.startLab(stage, mode)
        transport = Transport(name, timeout=60)
        log = a.EvidenceLog(directory / "evidence.jsonl")
        log.append({"kind": "session", "plan_sha256": self.frozen["plan_sha256"], **attempt})
        started = time.monotonic()
        stageDeadline = min(
            self.workDeadline, started + max(600, len(rows) * self.secondsPerEpisode * 1.6)
        )
        episodes, rollout = [], []
        data, request = None, None
        try:
            for row in rows:
                values = []
                for index in range(5):
                    self.check()
                    self.checkSources()
                    if time.monotonic() >= stageDeadline:
                        raise ValueError("finite measurement stage deadline exhausted")
                    before = None if index == 0 else data.observation
                    decision = None
                    if before is not None:
                        state = env.encode([before])
                        if policy in ("candidate", "incumbent"):
                            decision = agent.model.decide(state, deterministic=not training)
                            action = decision[0]
                        else:
                            action = (
                                env.heuristic(before)
                                if policy == "heuristic"
                                else int(policy == "constant1")
                            )
                    request = Request(
                        command="reset" if index == 0 else "step",
                        seed=row["seed"],
                        scenario=row["scenario"],
                        mode=mode,
                        episode_id=None if index == 0 else data.episode_id,
                        step_index=None if index == 0 else index,
                        action=None if index == 0 else action,
                        episode_steps=4,
                        window_seconds=2.0,
                    )
                    raw = transport.exchange(request)
                    log.append(
                        {
                            "kind": "measurement",
                            "request": request.model_dump(),
                            "response": raw,
                            "decision": list(decision) if decision is not None else None,
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
                    if before is not None:
                        for key in ("offered_mbps", "background_mbps", "path_capacity_mbps"):
                            if getattr(before, key) != getattr(data.observation, key):
                                raise ValueError("exogenous inputs changed within episode")
                        startAction = data.evidence["routing_health_start"]["paths"]["h1->h3"][
                            "action"
                        ]
                        if startAction != before.previous_action:
                            raise ValueError("route drift between observed state and next action")
                    if before is not None:
                        reward = env.rewardComponents(
                            data.observation,
                            before.previous_action,
                            censoredDelay=data.evidence["latency_timeout_ms"],
                        )
                        values.append(
                            {
                                "reward": reward["total"],
                                "delivery": reward["raw"]["goodput_ratio"],
                                "rtt": data.observation.latency_ms
                                if data.observation.latency_ms is not None
                                else 1000.0,
                                "changes": reward["raw"]["route_change"],
                                "outages": int(data.evidence["service_outage"]),
                            }
                        )
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
                            if len(rollout) == 16:
                                metrics = agent.update(rollout)
                                log.append(
                                    {
                                        "kind": "ppo_update",
                                        "transitions": agent.transitions,
                                        "metrics": metrics,
                                        "rollout": rollout,
                                    }
                                )
                                rollout = []
                                self.status["train_transitions"] = agent.transitions
                    self.status.update(
                        current_seed=row["seed"], current_profile=row["scenario"], step=index
                    )
                    self.heartbeat()
                episodes.append(
                    {**row, **{key: statistics.mean(v[key] for v in values) for key in values[0]}}
                )
            if rollout:
                raise ValueError("training block must end on complete on-policy update")
            close = Request(
                command="close",
                episode_id=data.episode_id,
                step_index=data.step_index,
                seed=data.seed,
                scenario=data.scenario,
                mode=mode,
                window_seconds=2.0,
                episode_steps=4,
            )
            raw = transport.exchange(close)
            log.append({"kind": "close", "request": close.model_dump(), "response": raw})
            if raw != {
                "version": 1,
                "ok": True,
                "error": None,
                "data": {"closed": True, "cleanup_verified": True, "episode_id": data.episode_id},
            }:
                raise ValueError("cleanup acknowledgement mismatch")
            attempt["status"] = "completed"
        finally:
            log.close()
            attempt["finished_unix"] = time.time()
            write(self.output / "ledger.json", self.ledger)
            self.cleanup()
        self.secondsPerEpisode = max(
            self.secondsPerEpisode, (time.monotonic() - started) / len(rows)
        )
        result = {
            "episodes": episodes,
            "policy": policy,
            "split": split,
            "evidence_sha256": digest(directory / "evidence.jsonl"),
            "checkpoint": checkpoint,
            "valid_transitions": 4 * len(rows),
            "plan_sha256": self.frozen["plan_sha256"],
            "cleanup_verified": True,
        }
        audited = reconstruct(
            directory / "evidence.jsonl", self.frozen, rows, policy, agent if not training else None
        )
        if (
            audited["episodes"] != episodes
            or audited["evidence_sha256"] != result["evidence_sha256"]
        ):
            raise ValueError("raw audit differs from session metrics")
        write(directory / "audit.json", audited)
        write(directory / "summary.json", result)
        return result

    def campaign(self):
        self.checkSources()
        self.preserve()
        self.exclusiveLab()
        if not admission(
            self.hardDeadline - time.monotonic(),
            64 + 80 + 32,
            144,
            self.secondsPerEpisode,
            starts=15,
        ):
            raise ValueError("minimum256 plus validation and final do not fit initial budget")
        self.agent, _ = warmstart()
        baseline, _, _ = incumbent()
        module("ppo").seedRuntime(self.frozen["ppo_config"]["seed"])
        # Incumbent is explicitly transferred to V5; the old image is not relabeled.
        write(
            self.output / "transfer.json",
            {
                "parent": PARENT_HASH,
                "from_spec": self.frozen["parent_environment_spec"],
                "to_spec": self.frozen["release"]["spec_hash"],
                "initialization": self.frozen["initialization"],
                "historical_observations_used": False,
            },
        )
        baselines, candidates = {}, []
        for count in self.frozen["validation_checkpoints"]:
            if count > 256 and not admission(
                self.hardDeadline - time.monotonic(), 48, 144, self.secondsPerEpisode, starts=8
            ):
                self.status["extension_stop"] = "next stage plus actual final reserve do not fit"
                break
            rows = self.frozen["training"][(count - 128) // 4 : count // 4]
            result = self.measured(f"train-{count}", "train", rows, "candidate", self.agent)
            self.trainSeeds.extend(r["seed"] for r in rows)
            self.trainHashes.append(result["evidence_sha256"])
            checkpoint = self.output / f"candidate-{count}.ptz"
            sha = save(checkpoint, self.agent, self.frozen, self.trainSeeds, self.trainHashes)
            trainingRng = torch.get_rng_state()
            evaluated, _ = load(checkpoint, sha, self.frozen)
            if not baselines:
                for policy in self.frozen["validation_order"]:
                    baselines[policy] = self.measured(
                        "validation-" + policy,
                        "validation",
                        self.frozen["validation"],
                        policy,
                        baseline if policy == "incumbent" else None,
                        PARENT_HASH if policy == "incumbent" else None,
                    )
            candidate = self.measured(
                f"validation-{count}",
                "validation",
                self.frozen["validation"],
                "candidate",
                evaluated,
                sha,
            )
            result = compare(candidate["episodes"], baselines["incumbent"]["episodes"])
            result.update(
                transitions=count,
                checkpoint=str(checkpoint),
                checkpoint_sha256=sha,
                eligible=count >= 256 and result["passed"],
                validation_reward=statistics.mean(r["reward"] for r in candidate["episodes"]),
            )
            candidates.append(result)
            write(self.output / "validation.json", {"checkpoints": candidates})
            self.status["validation_checkpoints"] = [
                {k: r[k] for k in ("transitions", "eligible", "validation_reward")}
                for r in candidates
            ]
            self.heartbeat()
            torch.set_rng_state(trainingRng)
        eligible = [r for r in candidates if r["eligible"]]
        if not eligible:
            write(
                self.output / "outcome.json",
                {
                    "status": "no_validation_quality",
                    "test_attempts": 0,
                    "default": PARENT_HASH,
                    "preservation": self.preserve(),
                    "autonomous_dispatch": "blocked",
                },
            )
            return "no_validation_quality_incumbent_retained"
        selected = min(eligible, key=lambda r: (-r["validation_reward"], r["transitions"]))
        write(self.output / "selection.json", selected)
        (self.output / "selection.json").chmod(0o400)
        if not admission(
            self.hardDeadline - time.monotonic(), 0, 144, self.secondsPerEpisode, starts=6
        ):
            return "selected_but_insufficient_final_budget_incumbent_retained"
        candidate, _ = load(
            Path(selected["checkpoint"]), selected["checkpoint_sha256"], self.frozen
        )
        tests = {}
        for policy in self.frozen["test_order"]:
            agent = (
                candidate if policy == "candidate" else baseline if policy == "incumbent" else None
            )
            sha = (
                selected["checkpoint_sha256"]
                if policy == "candidate"
                else PARENT_HASH
                if policy == "incumbent"
                else None
            )
            tests[policy] = self.measured(
                "test-" + policy, "test", self.frozen["test"], policy, agent, sha
            )
        result = compare(
            tests["candidate"]["episodes"],
            tests["incumbent"]["episodes"],
            final=True,
            endpoint=selected["endpoint"],
        )
        result.update(
            status="completed_all_six_once",
            selection=selected,
            baselines={
                p: compare(tests["candidate"]["episodes"], tests[p]["episodes"])
                for p in POLICIES
                if p != "candidate"
            },
            default=PARENT_HASH,
            preservation=self.preserve(),
            autonomous_dispatch="blocked",
            promotion="eligible_for_human_review" if result["passed"] else "research_only",
        )
        write(self.output / "outcome.json", result)
        return (
            "final_pass_incumbent_not_overwritten"
            if result["passed"]
            else "final_failed_incumbent_retained"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run", "status", "stop", "cleanup"))
    parser.add_argument("--release", type=Path, default=ROOT / "artifacts/adr015-release.json")
    parser.add_argument("--parent-approved", action="store_true")
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(read(OUTPUT / "status.json")))
        return 0
    if args.command == "stop":
        write(OUTPUT / "stop.request", {"operator_stop": True})
        return 0
    if args.command == "preflight":
        plan = prepare(args.release)
        print(
            json.dumps(
                {
                    "status": "ready",
                    "image": plan["image_id"],
                    "prior_ledgers": len(plan["prior_seed_evidence"]),
                    "parent": PARENT_HASH,
                }
            )
        )
        return 0
    if args.command == "cleanup":
        if not OUTPUT.exists():
            return 0
        with lock(OUTPUT / "run.lock"):
            plan = read(OUTPUT / "plan.json")
            plan["plan_sha256"] = digest(OUTPUT / "plan.json")
            runner = Campaign(OUTPUT, plan)
            runner.status = read(OUTPUT / "status.json")
            runner.hardDeadline = time.monotonic() + 110
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
                    state="failed",
                    stage="finished",
                    stop_reason="external_service_stop_cleanup_verified",
                )
            runner.heartbeat()
        return 0
    if not args.parent_approved or not os.environ.get("INVOCATION_ID"):
        raise ValueError("explicit parent authorization and capped systemd service required")
    properties = subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            "nanfo-adr015-refinement.service",
            "--property=RuntimeMaxUSec,Restart,TimeoutStopUSec,KillMode,ExecStopPost",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    if (
        not all(
            value in properties.splitlines()
            for value in (
                "Restart=no",
                "TimeoutStopUSec=2min",
                "KillMode=control-group",
            )
        )
        or "campaign.py cleanup" not in properties
    ):
        raise ValueError("systemd hard deadline/cleanup properties are not enforced")
    runtime = next(
        line.split("=", 1)[1]
        for line in properties.splitlines()
        if line.startswith("RuntimeMaxUSec=")
    )
    units = {"h": 3600, "min": 60, "s": 1, "ms": 0.001, "us": 0.000001}
    tokens = re.findall(r"([0-9.]+)(h|min|ms|us|s)", runtime)
    duration = sum(float(value) * units[unit] for value, unit in tokens)
    remaining = read(FAILED_ATTEMPT / "plan.json")["started_unix"] + 14400 - time.time()
    if not tokens or not 0 < duration <= 14400 or duration > remaining + 15:
        raise ValueError("systemd recovery cap exceeds original campaign deadline")
    if OUTPUT.exists():
        raise ValueError("campaign already exists; no restart, no retry")
    with lock(GLOBAL_LOCK):
        frozen = prepare(args.release)
        OUTPUT.mkdir(mode=0o700)
        (OUTPUT / "lab-output").mkdir(mode=0o700)
        (OUTPUT / "source").mkdir(mode=0o700)
        for path in SCRIPT.parent.glob("*.py"):
            a.atomicWrite(OUTPUT / "source" / path.name, path.read_bytes())
        write(OUTPUT / "plan.json", frozen)
        (OUTPUT / "plan.json").chmod(0o400)
        frozen["plan_sha256"] = digest(OUTPUT / "plan.json")
        with lock(OUTPUT / "run.lock"):
            return Campaign(OUTPUT, frozen).run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)[:2048]}), file=sys.stderr)
        sys.exit(1)
