"""Post-campaign read-only replay and append-only audit artifacts; never collects data."""

import argparse
import hashlib
import json
import statistics
from pathlib import Path

import torch

from nanfo_routing.artifacts import clientSources, inspectCheckpoint, loadCheckpoint
from nanfo_routing.cli import report
from nanfo_routing.contracts import jsonBytes, parseJson
from nanfo_routing.ppo import PPO
from nanfo_routing.qualification import qualify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    campaign = parseJson((root / "campaign.json").read_bytes())
    if campaign["status"] != "completed" or campaign["client_source_files"] != clientSources():
        raise ValueError("campaign unfinished or source changed")
    summaries = list(sorted(root.glob("*/summary.json")))
    controls = [root / f"calibration-constant{i}" / "summary.json" for i in (0, 1)]
    baselines = [
        root / f"validation-{name}" / "summary.json"
        for name in ("constant0", "constant1", "heuristic", "ospf")
    ]
    result = {
        "version": 3,
        "elapsed_seconds": campaign["elapsed_seconds"],
        "deadline_respected": campaign["elapsed_seconds"] <= 1200,
        "all_sessions_reparsed": True,
        "valid_decisions": 0,
        "measured_windows": 0,
        "invalid_windows": 0,
        "pilots": [],
        "validation_metrics": {},
        "primary_latency": "ICMP RTT",
        "udp_echo_rtt": None,
        "test": "not_run_no_qualified_policy; reserved seeds untouched",
        "backend_assessment": "not_invoked_no_qualified_policy",
        "backend_format_gap": [
            "ProducerQualification lacks train_only_action_effects, "
            "calibration_evidence_sha256 and evidence_paths",
            "CheckpointManifest lacks client_source_files",
        ],
        "autonomous_dispatch": "disabled; never requested",
    }
    for path in summaries:
        parsed = report([path])["sessions"][0]
        value = parseJson(path.read_bytes())
        result["valid_decisions"] += parsed["derived_metrics"]["valid_decisions"]
        result["measured_windows"] += len(parsed["reconstructed_phases"])
        result["invalid_windows"] += value["invalid_windows"]
        if value["split"] == "test":
            raise ValueError("unexpected test access")
    for seed in (41, 42):
        checkpoint = root / f"train-{seed}" / "checkpoint.ptz"
        validation = root / f"validation-{seed}" / "summary.json"
        actual = qualify(
            checkpoint,
            checkpoint.parent / "summary.json",
            [validation, *baselines],
            root / "plan.json",
            controls,
        )
        if actual != parseJson((root / f"qualification-{seed}.json").read_bytes()):
            raise ValueError("qualification replay differs")
        agent, manifest = loadCheckpoint(checkpoint)
        initial = PPO(manifest.config)
        changed = {
            name: float((tensor - initial.model.state_dict()[name]).abs().max())
            for name, tensor in agent.model.state_dict().items()
        }
        if not all(torch.isfinite(value).all() for value in agent.model.parameters()):
            raise ValueError("nonfinite checkpoint")
        parsed = report([validation, *baselines], checkpoint=checkpoint)
        for row in parsed["sessions"]:
            metrics = row["derived_metrics"]
            name = f"ppo{seed}" if row["policy"] == "ppo" else row["policy"]
            result["validation_metrics"][name] = {
                "mean_reward": metrics["mean_reward"],
                "mean_goodput_mbps": metrics["mean_goodput_mbps"],
                "mean_loss_fraction": metrics["mean_loss_fraction"],
                "mean_icmp_rtt_ms": statistics.mean(metrics["observed_rtt_ms"]),
                "actual_route_counts": metrics["actual_route_counts"],
                "timings": metrics["timings"],
            }
        result["pilots"].append(
            {
                "seed": seed,
                "checkpoint_sha256": inspectCheckpoint(checkpoint)["checkpoint_sha256"],
                "weights_sha256": manifest.weights_sha256,
                "updates": manifest.updates,
                "transitions": manifest.transitions,
                "parameter_max_abs_changes": changed,
                "qualified": actual["qualified"],
                "margins": actual["margins_over_both_constants"],
                "directional_dependence": actual["directional_dependence"],
                "ospf_paired": actual["comparisons"]["ospf"],
                "fresh_process_inference": parseJson(
                    (root / f"infer-{seed}.stdout.log").read_bytes()
                ),
            }
        )
    # Snapshot exact runtime source before any future fix can invalidate these checkpoints.
    sourceDirectory = Path(__file__).resolve().parents[1] / "src" / "nanfo_routing"
    snapshot = root / "frozen-client-source"
    snapshot.mkdir()
    for name, digest in campaign["client_source_files"].items():
        content = (sourceDirectory / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("source changed during snapshot")
        with (snapshot / name).open("xb") as output:
            output.write(content)
    with (root / "final-audit.json").open("xb") as output:
        output.write(jsonBytes(result))
    hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    with (root / "artifact-hashes.json").open("xb") as output:
        output.write(jsonBytes(hashes))
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "deadline_respected",
                    "valid_decisions",
                    "measured_windows",
                    "invalid_windows",
                    "test",
                    "backend_assessment",
                )
            },
            indent=2,
        )
    )
    print(
        json.dumps(
            {
                "checkpoints": [
                    {
                        key: row[key]
                        for key in (
                            "seed",
                            "checkpoint_sha256",
                            "weights_sha256",
                            "parameter_max_abs_changes",
                        )
                    }
                    for row in result["pilots"]
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
