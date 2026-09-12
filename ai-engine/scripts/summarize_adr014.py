"""Read-only reconstruction of ADR014-001; no collection, selection or test access."""

from pathlib import Path

from nanfo_routing.artifacts import atomicWrite
from nanfo_routing.contracts import jsonBytes, parseJson
from nanfo_routing.expanded import qualify


def main():
    output = Path(__file__).resolve().parents[1] / "artifacts" / "adr014-001"
    ledger = parseJson((output / "training-plan.collection.json").read_bytes())
    status = parseJson((output / "status.json").read_bytes())
    rows = []
    for path in sorted(output.glob("qualification-*.json")):
        saved = parseJson(path.read_bytes())
        p = saved["evidence_paths"]
        actual = qualify(
            p["checkpoint"], p["training"], p["validation"], p["plan"], p["calibration"]
        )
        if saved != actual:
            raise ValueError("qualification reconstruction mismatch")
        rows.append(
            {
                key: actual[key]
                for key in (
                    "transitions",
                    "updates",
                    "qualified",
                    "validation_mean_reward",
                    "margins_over_both_constants",
                    "directional_dependence",
                )
            }
        )
    summaries = [
        parseJson((Path(row["output"]) / "summary.json").read_bytes()) for row in ledger["attempts"]
    ]
    result = {
        "version": 4,
        "status": "incomplete_requested_training_budget",
        "actual_train_transitions": sum(
            row["valid_transitions"] for row in summaries if row["kind"] == "train"
        ),
        "actual_measured_decisions_all_policies": sum(
            row["valid_transitions"] for row in summaries
        ),
        "actual_measured_reset_windows": sum(len(row["episodes"]) for row in summaries),
        "completed_sessions": len(summaries),
        "first_collection_unix": ledger["started_unix"],
        "last_collection_finished_unix": max(row["finished_unix"] for row in ledger["attempts"]),
        "collection_elapsed_seconds": max(row["finished_unix"] for row in ledger["attempts"])
        - ledger["started_unix"],
        "unused_seconds_at_last_collection": ledger["deadline_unix"]
        - max(row["finished_unix"] for row in ledger["attempts"]),
        "stop_reason": status["stop_reason"],
        "validation_checkpoints": rows,
        "reserved_test_attempts": sum(
            row["identity"]["split"] == "test" for row in ledger["attempts"]
        ),
        "selected_checkpoint": None,
        "ospf_test_superiority_established": False,
        "autonomous_dispatch": "blocked",
        "known_supervisor_defects": [
            "1200-second next-pair plus1800-second test reserve blocked final pair before512.",
            (
                "poststop cleanup overwrote status elapsed_seconds with cleanup duration; "
                "use ledger timing."
            ),
            (
                "not_run_no_qualified_policy means no selection-eligible >=512 model, "
                "not failed validation gate."
            ),
        ],
    }
    path = output / "outcome.json"
    if path.exists():
        raise ValueError("outcome exists; no overwrite")
    atomicWrite(path, jsonBytes(result))
    print(jsonBytes(result).decode())


if __name__ == "__main__":
    main()
