"""Read-only compact status/results for the bounded ADR013 campaign."""

import argparse
import json
import statistics
from pathlib import Path

from nanfo_routing.contracts import parseJson


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    status = parseJson((args.output / "campaign.json").read_bytes())
    result = {
        key: status.get(key)
        for key in (
            "status",
            "stage",
            "started_unix",
            "deadline_unix",
            "remaining_seconds",
            "stop_reason",
            "failure",
            "cleanup_error",
            "elapsed_seconds",
            "qualifications",
            "test",
            "selection",
            "cleanup",
        )
    }
    result["sessions"] = []
    for path in sorted(args.output.glob("*/summary.json")):
        value = parseJson(path.read_bytes())
        row = {
            key: value.get(key)
            for key in (
                "status",
                "policy",
                "split",
                "mode",
                "valid_transitions",
                "invalid_windows",
                "updates",
                "transitions",
                "elapsed_seconds",
                "action_counts",
                "failure",
                "cleanup_error",
                "spec_hash",
            )
        }
        row["name"] = path.parent.name
        episodes = value.get("episodes", [])
        row["episode_means"] = [
            {
                "seed": episode["seed"],
                "scenario": episode["scenario"],
                "reward": episode["reward"] / episode["windows"],
            }
            for episode in episodes
            if episode["windows"]
        ]
        row["mean_reward"] = (
            statistics.mean(item["reward"] for item in row["episode_means"])
            if row["episode_means"]
            else None
        )
        progress = path.parent / "progress.json"
        if progress.exists():
            row["progress"] = parseJson(progress.read_bytes())
        result["sessions"].append(row)
    result["reports"] = []
    for path in sorted(args.output.glob("report-*.stdout.log")):
        if not path.stat().st_size:
            continue
        report = parseJson(path.read_bytes())
        result["reports"].append(
            {
                "file": path.name,
                "comparable": report["comparable_held_out_schedules"],
                "metrics": [
                    {"policy": row["policy"], **row["derived_metrics"]}
                    for row in report["sessions"]
                ],
                "paired_comparisons": report["paired_seed_comparisons"],
            }
        )
    if args.compact:
        result["cleanup_count"] = len(result.pop("cleanup") or [])
        for row in result["sessions"]:
            row.pop("episode_means", None)
            row.pop("spec_hash", None)
        for report in result["reports"]:
            for row in report["metrics"]:
                rtt = [value for value in row.pop("observed_rtt_ms") if value is not None]
                row["mean_icmp_rtt_ms"] = statistics.mean(rtt) if rtt else None
                row.pop("udp_rtt")
            for comparison in report["paired_comparisons"]:
                for metric in comparison["metrics"].values():
                    metric.pop("pairs")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
