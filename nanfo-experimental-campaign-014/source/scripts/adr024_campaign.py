#!/usr/bin/env python3
"""Bounded ADR024 provenance rebinding and fresh five-policy evaluation; no training."""

import argparse
import fcntl
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import random
import signal
import statistics
import subprocess
import sys
import time
import uuid

import recover_qualified_runtime as recovery

ROOT = recovery.ROOT
IMAGE = "sha256:954462c0f00d5bbaa72ea144f6064936b399c430e6ab94bffcf1c00d134ea0d7"
VERSION = "adr024-rebuilt-evaluation-v1"
SCRIPT = Path(__file__).resolve()
GATES = {"constant_reward_margin_strict_gt": .02, "constant_reward_ci_lower_strict_gt": 0,
         "ospf_goodput_ci_lower_strict_gt": 0, "ospf_rtt_ci_upper_strict_lt": 0,
         "direction_correct_fraction_strict_gt": .5, "paired_seeds": 12}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    recovery.write_json(Path(path), value)


def frozen():
    name = "_adr024_frozen"
    if name not in sys.modules:
        source = recovery.TRAIN / "source"
        spec = importlib.util.spec_from_file_location(name, source / "__init__.py", submodule_search_locations=[str(source)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[name] = package
        spec.loader.exec_module(package)
    return {key: importlib.import_module(name + "." + key)
            for key in ("artifacts", "cli", "contracts", "env", "qualification", "transport")}


def seed_values(value, key=""):
    result = set()
    if isinstance(value, dict):
        for name, child in value.items():
            result.update(seed_values(child, name))
    elif isinstance(value, list):
        for child in value:
            result.update(seed_values(child, key))
    elif type(value) is int and "seed" in key.lower() and 0 <= value <= 2147483647:
        result.add(value)
    return result


def audit_seeds():
    """Conservative union of actual/reserved seed fields, including failed campaigns."""
    reserved, documents = set(), []
    for root in (recovery.AI / "artifacts", ROOT / "emulation/output"):
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in (".json", ".jsonl"):
                continue
            found = set()
            with path.open("rb") as stream:
                if path.suffix == ".jsonl":
                    hasher = hashlib.sha256()
                    for line in stream:
                        hasher.update(line)
                        if line.strip():
                            found.update(seed_values(json.loads(line)))
                    hashed = hasher.hexdigest()
                else:
                    content = stream.read()
                    hashed = hashlib.sha256(content).hexdigest()
                    found.update(seed_values(json.loads(content)))
            reserved.update(found)
            documents.append(dict(path=str(path.relative_to(ROOT)), sha256=hashed, seeds=sorted(found)))
    candidates = next((list(range(first, first + 12)) for first in range(3000, 3989)
                       if not reserved.intersection(range(first, first + 12))), None)
    recovery.require(candidates is not None, "no unused contiguous twelve-seed test block")
    return dict(version=1, roots=["ai-engine/artifacts", "emulation/output"],
                reserved_seeds=sorted(reserved), selected_seeds=candidates, documents=documents)


def derive(output):
    manifest, _, _ = recovery.audit()
    modules = frozen()
    artifacts = modules["artifacts"]
    agent, parent = artifacts.loadCheckpoint(recovery.CHECKPOINT, resume=True)
    target = output / "checkpoint.ptz"
    artifacts.saveCheckpoint(target, agent, provenance=parent.provenance,
        trainingSeeds=parent.training_seeds, episodes=parent.episodes, evidenceHash=parent.evidence_sha256,
        environmentSpec=parent.environment_spec, distribution=parent.training_distribution,
        labProvenance={**parent.lab_provenance, "lab_image_id": IMAGE})
    actual, tensors = artifacts.readBundle(target)
    _, original = artifacts.readBundle(recovery.CHECKPOINT)
    recovery.require(tensors == original, "original writer did not preserve exact tensor payload")
    expected = {**manifest, "lab_provenance": {**manifest["lab_provenance"], "lab_image_id": IMAGE}}
    recovery.require(actual.model_dump() == expected, "unexpected derived manifest change")
    artifacts.loadCheckpoint(target)
    lineage = dict(version=VERSION, operation="provenance-rebinding-only-no-training",
        parent_checkpoint_sha256=recovery.CHECKPOINT_HASH, derived_checkpoint_sha256=digest(target),
        parent_manifest_sha256=recovery.sha(recovery.canonical(manifest)),
        derived_manifest_sha256=recovery.sha(recovery.canonical(expected)),
        tensor_payload_sha256=recovery.sha(tensors), exact_tensor_bytes_equal=True,
        parent_image_id=parent.lab_provenance["lab_image_id"], image_id=IMAGE,
        source_sha256=parent.environment_spec["source_sha256"], client_source_sha256=parent.client_source_files,
        changed_manifest_fields=["lab_provenance.lab_image_id"], qualified=False)
    save(output / "lineage.json", lineage)
    return artifacts.inspectCheckpoint(target)


def prepare(output):
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    identity = derive(output)
    audit = audit_seeds()
    save(output / "seed-audit.json", audit)
    order = ["ppo", "constant0", "constant1", "heuristic", "ospf"]
    random.Random(9242026).shuffle(order)
    plan = dict(version=VERSION, campaign_id=uuid.uuid4().hex, created_unix=time.time(),
        authorization="ADR024 amended; user serialized exclusive evaluation authorization; no training",
        checkpoint=identity, image_id=IMAGE, parent_checkpoint_sha256=recovery.CHECKPOINT_HASH,
        lineage_sha256=digest(output / "lineage.json"), seed_audit_sha256=digest(output / "seed-audit.json"),
        runner_sha256=digest(SCRIPT), recovery_script_sha256=digest(Path(recovery.__file__)),
        client_source_sha256=identity["manifest"]["client_source_files"],
        runtime_versions=identity["manifest"]["versions"], test_seeds=audit["selected_seeds"],
        policy_order=order, policy_order_seed=9242026, scenarios=["path0", "path1"],
        steps=4, window_seconds=2.0, budget_seconds=1800, cleanup_reserve_seconds=120,
        session_budget_seconds=600, qualification=GATES, test_attempts_before_selection=0,
        selection_rule="fixed ADR014 incumbent; tensor-identical deployment rebind; no selection on new tests",
        retry_rule="no completed unfavorable campaign retry; preserve invalid attempts; no tuning",
        scope="stationary-campus-small-v4-scoped-benchmark", autonomous_dispatch=False)
    save(output / "plan.json", plan)
    save(output / "selection.json", dict(plan_sha256=digest(output / "plan.json"), checkpoint=identity,
         selection_rule=plan["selection_rule"], test_only=True))
    return dict(output=str(output), plan_sha256=digest(output / "plan.json"),
                seeds=plan["test_seeds"], order=order, checkpoint_sha256=identity["checkpoint_sha256"])


def verify_plan(output):
    plan = read(output / "plan.json")
    recovery.require(plan["version"] == VERSION and plan["qualification"] == GATES, "protocol/gates changed")
    recovery.require(digest(SCRIPT) == plan["runner_sha256"], "runner changed after preregistration")
    recovery.require(digest(Path(recovery.__file__)) == plan["recovery_script_sha256"], "recovery script changed")
    recovery.audit()
    recovery.require(frozen()["artifacts"].inspectCheckpoint(output / "checkpoint.ptz") == plan["checkpoint"], "model changed")
    for name in ("lineage", "seed-audit"):
        recovery.require(digest(output / (name + ".json")) == plan[name.replace("-", "_") + "_sha256"], "lineage/audit changed")
    audit = read(output / "seed-audit.json")
    recovery.require(len(plan["test_seeds"]) == 12 and len(set(plan["test_seeds"])) == 12
                     and all(3000 <= seed <= 3999 for seed in plan["test_seeds"])
                     and not set(plan["test_seeds"]) & set(audit["reserved_seeds"]), "reserved seeds used")
    return plan


def command(output, label, argv, timeout=30, check=True):
    return recovery.command(output, label, argv, timeout=timeout, check=check)


def start_lab(output, plan, policy):
    name = "nanfo-training-" + uuid.uuid4().hex
    owner = dict(name=name, campaign_id=plan["campaign_id"], policy=policy, image_id=IMAGE)
    save(output / (policy + "-owner.json"), owner)
    result = command(output, policy + "-create", ["docker", "create", "--pull=never", "--name", name,
        "--cidfile", str(output / (policy + ".cid")), "--label", "nanfo.adr024.campaign=" + plan["campaign_id"],
        "--network", "none", "--privileged", "--cpus", "2", "--memory", "768m", "--memory-swap", "768m",
        "--pids-limit", "256", "--tmpfs", "/run:exec,size=64m", "--tmpfs", "/tmp:exec,size=64m",
        "--log-driver", "json-file", "--log-opt", "max-size=2m", "--log-opt", "max-file=2",
        "--env", "EMULATION_CONTROL_ENABLED=false", "--env", "NANFO_LAB_IMAGE_ID=" + IMAGE,
        IMAGE, "--experiment", "--mode", "ospf" if policy == "ospf" else "matched", "--output", "/output"])
    cid = result.stdout.decode().strip()
    recovery.require(cid == (output / (policy + ".cid")).read_text().strip(), "container ID mismatch")
    details = json.loads(command(output, policy + "-inspect", ["docker", "inspect", cid]).stdout)[0]
    recovery.require(details["Image"] == IMAGE and details["HostConfig"]["NetworkMode"] == "none"
                     and not details["Mounts"] and not details["HostConfig"].get("PidMode")
                     and not details["HostConfig"].get("Binds"), "lab isolation mismatch")
    command(output, policy + "-start", ["docker", "start", cid])
    code = ("from pathlib import Path; import time,sys; end=time.monotonic()+75; "
            "exec(\"while time.monotonic()<end and not Path('/run/nanfo/experiment.sock').is_socket(): time.sleep(.25)\"); "
            "sys.exit(not Path('/run/nanfo/experiment.sock').is_socket())")
    command(output, policy + "-ready", ["docker", "exec", cid, "python", "-c", code], timeout=80)
    return name


def cleanup(output, plan, policy):
    cidpath = output / (policy + ".cid")
    if not cidpath.exists():
        return
    cid = cidpath.read_text().strip()
    owner = read(output / (policy + "-owner.json"))
    info = json.loads(command(output, policy + "-cleanup-inspect", ["docker", "inspect", cid]).stdout)[0]
    recovery.require(info["Id"] == cid and info["Image"] == IMAGE and info["Name"] == "/" + owner["name"]
                     and info["Config"]["Labels"]["nanfo.adr024.campaign"] == plan["campaign_id"], "cleanup ownership mismatch")
    command(output, policy + "-stop", ["docker", "stop", "--time", "20", cid], timeout=30)
    command(output, policy + "-logs", ["docker", "logs", cid], check=False)
    # Copy from the stopped owned container; never bind host paths into privileged labs.
    command(output, policy + "-raw-output", ["docker", "cp", cid + ":/output", str(output / (policy + "-lab-output"))])
    command(output, policy + "-remove", ["docker", "rm", cid])
    remaining = command(output, policy + "-absent", ["docker", "ps", "-a", "--no-trunc", "--filter", "id=" + cid, "--format", "{{.ID}}"])
    recovery.require(not remaining.stdout.strip(), "owned container still present")
    save(output / (policy + "-cleanup.json"), dict(container_id=cid, removed=True, at_unix=time.time()))


def collect(output, policy, container, budget):
    """New admission/orchestration only; frozen transport, env, policy and raw validator."""
    plan = verify_plan(output)
    m = frozen()
    a, cli, c, envmod = (m[k] for k in ("artifacts", "cli", "contracts", "env"))
    checkpoint = output / "checkpoint.ptz"
    agent, manifest = a.loadCheckpoint(checkpoint)
    directory = output / ("test-" + policy)
    directory.mkdir(mode=0o700)
    mode = "ospf" if policy == "ospf" else "matched"
    log = a.EvidenceLog(directory / "evidence.jsonl")
    env = envmod.RoutingEnv(cli.LoggedTransport(m["transport"].DockerTransport(container, 90), log),
                           split="test", mode=mode, window_seconds=2.0, episode_steps=4,
                           expectedSpec=manifest.environment_spec)
    summary = dict(version=3, kind="evaluation", provenance="measured-lab", contract_hash=c.CONTRACT_HASH,
        contract=c.CONTRACT, versions=a.runtimeVersions(), plan_sha256=digest(output / "plan.json"), split="test",
        evaluation_role="held-out", seeds=plan["test_seeds"], scenarios=plan["scenarios"], policy=policy, mode=mode,
        window_seconds=2.0, episode_steps=4, budget_seconds=budget, config=agent.config.model_dump() if policy == "ppo" else None,
        generalization=False, model_seed=44, episodes=[], invalid_windows=0, valid_transitions=0,
        action_counts=[0, 0], route_changes=0, checkpoint=None, status="running", limitations=[
            "Scoped isolated rebuilt v4 evaluation; not physical safety or autonomous authorization."],
        safety_confidence=None)
    a.atomicWrite(directory / "summary.json", c.jsonBytes(summary))
    log.append(dict(kind="session", summary=summary, parent_checkpoint=manifest.model_dump() if policy == "ppo" else None))
    # Record attachment before reset: no old records or re-timestamped measurements.
    save(directory / "feed-attachment.json", dict(session_sha256=digest(directory / "evidence.jsonl"),
         feed_offset=(directory / "evidence.jsonl").stat().st_size, attached_monotonic=time.monotonic(),
         attached_unix=time.time(), purpose="qualification raw feed; not a qualified live snapshot"))
    started = time.monotonic()
    failure, close_error = None, None
    try:
        for index, seed in enumerate(plan["test_seeds"]):
            if time.monotonic() - started >= budget:
                raise RuntimeError("session deadline exhausted")
            scenario = plan["scenarios"][index % 2]
            env.template = env.template.model_copy(update={"scenario": scenario})
            began = time.monotonic()
            state, _ = env.reset(seed=seed)
            recovery.require(env.labProvenance == manifest.lab_provenance, "actual image differs from deployment artifact")
            rewards = []
            for _ in range(4):
                if time.monotonic() - started >= budget:
                    raise RuntimeError("session deadline exhausted")
                t = time.perf_counter()
                if policy == "ppo":
                    action, _, value, probabilities = agent.model.decide(state, deterministic=True)
                else:
                    action = (int(policy[-1]) if policy.startswith("constant") else
                              envmod.heuristic(env.data.observation) if policy == "heuristic" else env.data.observation.previous_action)
                    value, probabilities = None, None
                inference = time.perf_counter() - t
                input_hash = hashlib.sha256(c.jsonBytes(env.data.observation.model_dump())).hexdigest()
                state, _, terminated, truncated, info = env.step(action)
                valid = info["valid_transition"]
                log.append(dict(kind="decision", episode_id=env.data.episode_id, step_index=env.data.step_index,
                    action=action, input_sha256=input_hash, inference_seconds=inference, probabilities=probabilities,
                    value=value, reward=info["reward"], valid_transition=valid, terminated=terminated,
                    truncated=truncated, error=info.get("error")))
                if not valid:
                    summary["invalid_windows"] += 1
                    raise RuntimeError(info.get("error") or "invalid transition")
                rewards.append(info["reward"])
                summary["valid_transitions"] += 1
                summary["action_counts"][action] += 1
                summary["route_changes"] += int(info["reward"]["raw"]["route_change"])
            summary["episodes"].append(dict(seed=seed, scenario=scenario, reward=sum(r["total"] for r in rewards),
                windows=4, rewards=rewards, wall_seconds=time.monotonic() - began))
            print(json.dumps(dict(policy=policy, seed=seed, complete_episodes=len(summary["episodes"]))), flush=True)
    except (ValueError, RuntimeError, OSError, KeyboardInterrupt) as exc:
        failure = str(exc)
    finally:
        try:
            env.close()
        except (ValueError, RuntimeError, OSError) as exc:
            close_error = str(exc)
        log.close()
        summary.update(status="failed" if failure or close_error else "completed", failure=failure,
            cleanup_error=close_error, elapsed_seconds=time.monotonic() - started,
            evidence_sha256=log.digest.hexdigest(), evidence_bytes=log.size,
            mean_episode_reward=statistics.mean(row["reward"] for row in summary["episodes"]) if summary["episodes"] else None,
            environment_spec=env.environmentSpec, lab_provenance=env.labProvenance,
            spec_hash=manifest.spec_hash, checkpoint=a.inspectCheckpoint(checkpoint) if policy == "ppo" else None)
        a.atomicWrite(directory / "summary.json", c.jsonBytes(summary))
    recovery.require(not failure and not close_error, "session failed: " + str(failure or close_error))


def assess(report):
    checks = {"matched_schedules": report["comparable_held_out_schedules"]}
    comparisons = {row["baseline"]: row["metrics"] for row in report["paired_seed_comparisons"]}
    for policy in ("constant0", "constant1"):
        reward = comparisons[policy]["reward"]
        checks[policy] = reward["paired_seed_count"] == 12 and reward["mean_delta"] > .02 and reward["ci95"] is not None and reward["ci95"][0] > 0
    goodput, rtt = (comparisons["ospf"][key] for key in ("goodput_mbps", "icmp_rtt_ms"))
    checks["ospf_goodput"] = goodput["paired_seed_count"] == 12 and goodput["ci95"] is not None and goodput["ci95"][0] > 0
    checks["ospf_rtt"] = rtt["paired_seed_count"] == 12 and rtt["ci95"] is not None and rtt["ci95"][1] < 0
    learned = next(row for row in report["sessions"] if row["policy"] == "ppo")
    for scenario, desired in (("path0", 1), ("path1", 0)):
        rows = [row for row in learned["reconstructed_steps"] if row["scenario"] == scenario]
        checks[scenario] = len(rows) == 24 and sum(row["action"] == desired for row in rows) > 12
    return dict(qualified=all(checks.values()), checks=checks, comparisons=comparisons,
                safety_calibrated=False, autonomous_activation=False)


def finalize(output):
    plan = verify_plan(output)
    paths = [output / ("test-" + p) / "summary.json" for p in plan["policy_order"]]
    for policy, path in zip(plan["policy_order"], paths, strict=True):
        summary = read(path)
        recovery.require(summary["status"] == "completed" and summary["seeds"] == plan["test_seeds"]
            and summary["valid_transitions"] == 48 and summary["invalid_windows"] == 0
            and summary["lab_provenance"] == plan["checkpoint"]["manifest"]["lab_provenance"]
            and summary["plan_sha256"] == digest(output / "plan.json") and summary["policy"] == policy,
            "incomplete or incompatible campaign")
    report = frozen()["cli"].report(paths, checkpoint=output / "checkpoint.ptz")
    save(output / "test-report.json", report)
    result = assess(report)
    save(output / "qualification.json", result)
    def ref(path):
        return dict(path=str(path.relative_to(output)), sha256=digest(path), size_bytes=path.stat().st_size)
    registry = dict(protocol=VERSION, checkpoint=ref(output / "checkpoint.ptz"),
        parent_checkpoint_sha256=recovery.CHECKPOINT_HASH, lineage=ref(output / "lineage.json"),
        plan=ref(output / "plan.json"), selection=ref(output / "selection.json"),
        seed_audit=ref(output / "seed-audit.json"), report=ref(output / "test-report.json"),
        qualification=ref(output / "qualification.json"), image_id=IMAGE,
        source_directory="source", source_sha256=plan["client_source_sha256"],
        runtime_versions=plan["runtime_versions"], sessions=[dict(summary=ref(path), evidence=ref(path.parent / "evidence.jsonl")) for path in paths],
        action_ids=["route0", "route1"], runtime_action="linux-frr-host-route",
        observation_contract="nanfo.passive-measured-v4.v1", qualified=result["qualified"],
        qualification_claim="must be independently reconstructed; this flag grants no authority")
    source = output / "source"
    source.mkdir(mode=0o700)
    for name in plan["client_source_sha256"]:
        recovery.write(source / name, (recovery.TRAIN / "source" / name).read_bytes())
    save(output / "deployment-registry.json", registry)
    return result


def run(output):
    plan = verify_plan(output)
    with (output / "campaign.lock").open("xb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        save(output / "started.json", dict(plan_sha256=digest(output / "plan.json"), at_unix=time.time()))
        start = time.monotonic()
        failure = None
        for policy in plan["policy_order"]:
            try:
                remaining = plan["budget_seconds"] - (time.monotonic() - start) - plan["cleanup_reserve_seconds"]
                recovery.require(remaining >= 60, "campaign budget exhausted")
                name = start_lab(output, plan, policy)
                remaining = plan["budget_seconds"] - (time.monotonic() - start) - plan["cleanup_reserve_seconds"]
                recovery.require(remaining >= 30, "campaign budget exhausted during startup")
                command(output, policy + "-session", [sys.executable, "-B", str(SCRIPT), "session", "--output", str(output),
                    "--policy", policy, "--container", name, "--budget", str(min(600, remaining))],
                    timeout=min(690, remaining + 90))
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                failure = str(exc)
            finally:
                cleanup(output, plan, policy)
            if failure:
                break
        if failure:
            result = dict(qualified=False, status="invalid-incomplete", failure=failure, training=False,
                          elapsed_seconds=time.monotonic() - start)
        else:
            result = finalize(output)
            result.update(status="passed" if result["qualified"] else "failed-valid-complete",
                          elapsed_seconds=time.monotonic() - start)
        save(output / "outcome.json", result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "run", "session", "finalize"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy", choices=("ppo", "constant0", "constant1", "heuristic", "ospf"))
    parser.add_argument("--container")
    parser.add_argument("--budget", type=float, default=600)
    args = parser.parse_args()
    os.umask(0o077)
    if args.operation == "session":
        def stop(signum, frame):
            raise KeyboardInterrupt("operator stopped campaign session")
        signal.signal(signal.SIGTERM, stop)
        collect(args.output, args.policy, args.container, args.budget)
    else:
        print(json.dumps(globals()[args.operation](args.output), indent=2), flush=True)


if __name__ == "__main__":
    main()
