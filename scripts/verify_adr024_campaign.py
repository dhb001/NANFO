#!/usr/bin/env python3
"""Read-only independent reconstruction and private installation check of ADR024 results."""

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import adr024_campaign as campaign
import recover_qualified_runtime as recovery


def independent_metrics(output, plan, report):
    """Rebuild paired CIs directly from raw measurement frames, not saved comparisons."""
    rows = {}
    for policy in plan["policy_order"]:
        seeds = {}
        before = None
        for line in (output / f"test-{policy}/evidence.jsonl").read_bytes().splitlines():
            row = json.loads(line)
            if row.get("kind") != "ipc" or row["request"]["command"] == "close":
                continue
            data = row["response"]["data"]
            obs, evidence = data["observation"], data["evidence"]
            if row["request"]["command"] == "reset":
                before = obs
                continue
            # Independent arithmetic; exact coefficients come from frozen contract.
            contract = plan["checkpoint"]["manifest"]["contract"]
            scales, weights = contract["reward_scales"], contract["reward_weights"]
            reward = dict(goodput_ratio=min(obs["goodput_mbps"] / obs["actual_offered_mbps"], 1.0),
                delay=(obs["latency_ms"] if obs["latency_ms"] is not None else evidence["latency_timeout_ms"]) / scales["delay_ms"],
                loss=obs["loss_fraction"], utilization=max(obs["path_utilization"]),
                queue=max(obs["path_queue_packets"]) / scales["queue_packets"],
                route_change=float(obs["previous_action"] != before["previous_action"]))
            values = dict(reward=sum(reward[key] * weights[key] for key in reward),
                          goodput_mbps=obs["goodput_mbps"], icmp_rtt_ms=obs["latency_ms"],
                          loss_fraction=obs["loss_fraction"])
            seeds.setdefault(data["seed"], []).append(values)
            before = obs
        recovery.require(set(seeds) == set(plan["test_seeds"]) and all(len(v) == 4 for v in seeds.values()), "independent raw window count")
        rows[policy] = seeds
    comparisons = {}
    for saved in report["paired_seed_comparisons"]:
        baseline = saved["baseline"]
        comparisons[baseline] = {}
        for metric in ("reward", "goodput_mbps", "icmp_rtt_ms", "loss_fraction"):
            deltas = [statistics.mean(row[metric] for row in rows["ppo"][seed])
                      - statistics.mean(row[metric] for row in rows[baseline][seed]) for seed in plan["test_seeds"]]
            mean = statistics.mean(deltas)
            half = 2.2010 * statistics.stdev(deltas) / math.sqrt(12)
            interval = [mean - half, mean + half]
            actual = saved["metrics"][metric]
            recovery.require(actual["paired_seed_count"] == 12 and math.isclose(actual["mean_delta"], mean, abs_tol=1e-12)
                and all(math.isclose(a, b, abs_tol=1e-12) for a, b in zip(actual["ci95"], interval, strict=True)),
                "independent CI mismatch")
            comparisons[baseline][metric] = dict(mean_delta=mean, ci95=interval, paired_seed_count=12)
    return comparisons


def verify(output):
    plan = campaign.verify_plan(output)
    modules = campaign.frozen()
    report = modules["cli"].report([output / f"test-{p}/summary.json" for p in plan["policy_order"]],
                                    checkpoint=output / "checkpoint.ptz")
    recovery.require(report == campaign.read(output / "test-report.json"), "raw report differs")
    comparisons = independent_metrics(output, plan, report)
    recovery.require(campaign.assess(report)["qualified"], "campaign gates failed")
    # Additional portable lineage bytes and acquisition references; original outputs stay intact.
    recovery.write(output / "parent-checkpoint.ptz", recovery.CHECKPOINT.read_bytes())
    recovery.write(output / "campaign-runner.py", campaign.SCRIPT.read_bytes())
    recovery.write(output / "recovery-runner.py", Path(recovery.__file__).read_bytes())
    histories = {}
    for line in (output / "test-ppo/evidence.jsonl").read_bytes().splitlines():
        row = json.loads(line)
        if row.get("kind") == "ipc" and row["request"]["command"] == "reset":
            scenario = row["request"]["scenario"]
            if scenario not in histories:
                name = f"recorded-history-{scenario}.json"
                recovery.write_json(output / name, dict(version=3, frames=[dict(request=row["request"], response=row["response"])]))
                histories[scenario] = name
    def ref(name):
        path = output / name
        return dict(path=name, sha256=campaign.digest(path), size_bytes=path.stat().st_size)
    now = datetime.now(timezone.utc)
    private = Path(tempfile.mkdtemp(prefix="nanfo-adr024-installation-check-", dir=recovery.scratch_root()))
    (private / "observations").mkdir(mode=0o700)
    manifest = plan["checkpoint"]["manifest"]
    registry = dict(version=1, model_id="adr024-rebuilt-v4", checkpoint=ref("checkpoint.ptz"),
        qualification_protocol=campaign.VERSION, parent_checkpoint=ref("parent-checkpoint.ptz"),
        lineage=ref("lineage.json"), seed_audit=ref("seed-audit.json"), source_directory="source",
        source_sha256=manifest["client_source_files"], contract_sha256=manifest["contract_hash"], spec_sha256=manifest["spec_hash"],
        runtime_versions=manifest["versions"], observation_contract="nanfo.passive-measured-v4.v1", runtime_action="linux-frr-host-route",
        action_ids=["route0", "route1"], scopes=[dict(network_id=str(uuid.uuid4()), workspace_id=str(uuid.uuid4()), snapshot_path="snapshot.json")],
        installed_at=now.isoformat(), expires_at=(now + timedelta(hours=2)).isoformat(), max_observation_age_seconds=30,
        plan=ref("plan.json"), selection=ref("selection.json"), report=ref("test-report.json"),
        sessions=[dict(summary=ref(f"test-{p}/summary.json"), evidence=ref(f"test-{p}/evidence.jsonl"),
                       attachment=ref(f"test-{p}/feed-attachment.json")) for p in plan["policy_order"]])
    recovery.write_json(private / "registry.json", registry)
    template = json.loads(json.dumps(registry))
    template["installed_at"], template["expires_at"] = "REPLACE_AWARE_INSTALL_TIME", "REPLACE_AWARE_EXPIRY"
    template["scopes"] = [dict(network_id="REPLACE_NETWORK_UUID", workspace_id="REPLACE_WORKSPACE_UUID", snapshot_path="snapshot.json")]
    recovery.write_json(output / "live-registry.template.json", template)
    env = {"PATH": os.environ["PATH"], "HOME": str(private), "TMPDIR": str(private),
        "NANFO_LIVE_MODEL_REGISTRY": str(private / "registry.json"),
        "NANFO_LIVE_MODEL_REGISTRY_SHA256": campaign.digest(private / "registry.json"),
        "NANFO_MODEL_ROOT": str(output), "NANFO_MODEL_PYTHON": str(recovery.AI / ".venv/bin/python"),
        "NANFO_LIVE_OBSERVATION_ROOT": str(private / "observations"),
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    recovery.write_json(private / "environment.json", env)
    results = {}
    for operation, extra in (("qualify", []), ("replay-path0", ["--replay-history", histories["path0"]]),
                             ("replay-path1", ["--replay-history", histories["path1"]])):
        argv = [str(recovery.AI / ".venv/bin/python"), "-I", "-B", str(recovery.ROOT / "backend/scripts/frozen_live_inference.py"),
                "qualify" if operation == "qualify" else "replay", *extra]
        result = subprocess.run(argv, cwd=private, env=env, capture_output=True, timeout=120)
        recovery.write(private / (operation + ".stdout"), result.stdout)
        recovery.write(private / (operation + ".stderr"), result.stderr)
        recovery.require(result.returncode == 0, "confined qualification/replay failed; evidence at " + str(private))
        results[operation] = json.loads(result.stdout)
    evidence = dict(version=campaign.VERSION, raw_report_exact=True, independent_raw_metrics=comparisons,
        confined_results=results, installation_check_directory=str(private),
        installation_scope="disposable offline qualification/replay only; no current live snapshot",
        plan_sha256=campaign.digest(output / "plan.json"), report_sha256=campaign.digest(output / "test-report.json"),
        derived_checkpoint_sha256=campaign.digest(output / "checkpoint.ptz"),
        original_checkpoint_unchanged=campaign.digest(recovery.CHECKPOINT) == recovery.CHECKPOINT_HASH,
        reviewer_script_sha256=campaign.digest(Path(__file__)), source_runner_sha256=campaign.digest(campaign.SCRIPT))
    recovery.write_json(output / "independent-verification.json", evidence)
    return dict(verified=True, installation_check_directory=str(private),
                verification_sha256=campaign.digest(output / "independent-verification.json"),
                live_registry_template_sha256=campaign.digest(output / "live-registry.template.json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(verify(args.output), indent=2))
