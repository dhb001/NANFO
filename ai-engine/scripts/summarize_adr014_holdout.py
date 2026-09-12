"""Read-only holdout reconstruction and seed-level results; no collection or selection."""

import statistics
from copy import deepcopy

from run_adr014_holdout import OUTPUT, digest, verifiedPlan

from nanfo_routing.cli import report
from nanfo_routing.contracts import jsonBytes, parseJson
from nanfo_routing.qualification import pairedComparison
from nanfo_routing.supervisor import readJson


def main():
    plan = verifiedPlan(OUTPUT)
    ledger = readJson(OUTPUT / "test-ledger.json")
    if [row["policy"] for row in ledger["attempts"]] != plan["policy_order"] or any(
        row["status"] != "completed" for row in ledger["attempts"]
    ):
        raise ValueError("five complete once-only test sessions required")
    checkpoint = OUTPUT.parent / "adr014-001" / "train-06" / "checkpoint.ptz"
    paths = [OUTPUT / ("test-" + policy) / "summary.json" for policy in plan["policy_order"]]
    rebuilt = report(paths, checkpoint=checkpoint)
    saved = readJson(OUTPUT / "test-report.json")
    if any(saved[key] != value for key, value in rebuilt.items()):
        raise ValueError("saved report differs from independently replayed raw test evidence")
    sessions = {row["policy"]: row for row in rebuilt["sessions"]}
    metrics = {}
    for policy, row in sessions.items():
        steps = row["reconstructed_steps"]
        rtts = [step["observed_latency_ms"] for step in steps]
        sent = sum(step["drain"]["udp_sent"][0]["packets"] for step in steps)
        received = sum(step["drain"]["udp_received"][0]["packets"] for step in steps)
        metrics[policy] = {
            "seed_count": len(row["seeds"]),
            "decision_windows": len(steps),
            "mean_goodput_mbps": row["derived_metrics"]["mean_goodput_mbps"],
            "mean_icmp_rtt_ms": statistics.mean(rtts) if None not in rtts else None,
            "mean_verified_drain_loss_fraction": row["derived_metrics"]["mean_loss_fraction"],
            "aggregate_foreground_sent_packets": sent,
            "aggregate_foreground_received_packets": received,
            "aggregate_packet_weighted_loss_fraction": 1 - received / sent,
            "mean_reward": row["derived_metrics"]["mean_reward"],
            "route_changes": row["derived_metrics"]["route_changes"],
            "actual_route_counts": row["derived_metrics"]["actual_route_counts"],
            "service_outages": row["derived_metrics"]["service_outages"],
            "mean_drain_seconds": statistics.mean(
                step["drain"]["drain_duration_seconds"] for step in steps
            ),
            "timings": row["derived_metrics"]["timings"],
            "session_elapsed_seconds": row["elapsed_seconds"],
            "evidence_sha256": row["evidence_sha256"],
        }
    directional = {}
    for scenario in ("path0", "path1"):
        pair = []
        for policy in ("ppo", "ospf"):
            row = deepcopy(sessions[policy])
            row["reconstructed_steps"] = [
                s for s in row["reconstructed_steps"] if s["scenario"] == scenario
            ]
            row["seeds"] = sorted({s["seed"] for s in row["reconstructed_steps"]})
            pair.append(row)
        directional[scenario] = pairedComparison(*pair)
    # Same seed-mean CI implementation, with additional operational metric series.
    changed = []
    for policy in ("ppo", "ospf"):
        row = deepcopy(sessions[policy])
        for step in row["reconstructed_steps"]:
            step["reward"]["total"] = float(step["reward"]["raw"]["route_change"])
        changed.append(row)
    inference = readJson(OUTPUT / "inference-reproducibility.json")
    result = {
        "version": "adr014-holdout-results-v1",
        "selected_checkpoint_sha256": plan["checkpoint"]["checkpoint_sha256"],
        "checkpoint_weights_sha256": plan["checkpoint"]["manifest"]["weights_sha256"],
        "original_plan_sha256": plan["original_plan_sha256"],
        "test_plan_sha256": digest(OUTPUT / "plan.json"),
        "selection_sha256": digest(OUTPUT / "selection.json"),
        "original_test_attempts_before_selection": 0,
        "completed_test_attempts": 5,
        "train_or_validation_collection_attempts": 0,
        "policy_order": plan["policy_order"],
        "policy_order_seed": plan["policy_order_seed"],
        "metrics": metrics,
        "paired_seed_comparisons": rebuilt["paired_seed_comparisons"],
        "ppo_vs_ospf_by_scenario": directional,
        "ppo_vs_ospf_route_changes_per_decision": pairedComparison(*changed)["reward"],
        "fresh_process_inference": inference["fresh_processes"],
        "exact_raw_ppo_replay": True,
        "test_elapsed_seconds": readJson(OUTPUT / "status.json")["elapsed_seconds"],
        "collection_elapsed_seconds": max(row["finished_unix"] for row in ledger["attempts"])
        - ledger["started_unix"],
        "measured_ospf_improvement": saved["measured_ospf_improvement"],
        "scope": plan["scope"],
        "autonomous_dispatch": "blocked",
        "limitations": [
            "ICMP RTT, not UDP echo; late delivery counts unavailable, not inferred.",
            "Student-t seed-mean intervals assume approximately normal independent seed deltas.",
            (
                "One shuffled policy order, not counterbalanced/repeated sessions; "
                "time drift may confound."
            ),
            "Simultaneous coverage of multiple reported95% intervals is not guaranteed.",
            (
                "Goodput includes control/drain service and uses sender duration; "
                "reset windows excluded."
            ),
        ],
    }
    path = OUTPUT / "outcome.json"
    if path.exists():
        if parseJson(path.read_bytes()) != result:
            raise ValueError("existing outcome differs; never overwrite")
    else:
        with path.open("xb") as target:
            target.write(jsonBytes(result))
    print(jsonBytes(result).decode())


if __name__ == "__main__":
    main()
