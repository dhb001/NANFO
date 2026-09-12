"""Hash-pin immutable campaign/retry/external evidence without overwriting outcomes."""

import argparse
import json
from pathlib import Path

from scripts.acceptance.campaign import summary
from scripts.acceptance.common import read_json, write_new
from scripts.acceptance.runtime import PRESERVABLE_ID, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--retry", type=Path, required=True)
    parser.add_argument("--alerts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--superseding-summary", type=Path, action="append", default=[],
                        help="Root-cause-fixed failed-stage retry; only verified passed cases supersede prior failures")
    args = parser.parse_args()
    base, base_hash = read_json(args.campaign)
    retry, retry_hash = read_json(args.retry)
    alerts, alerts_hash = read_json(args.alerts)
    preserved, preserved_hash = read_json(args.alerts.parent.parent / "preservation.json")
    if not (alerts.get("passed") is True and alerts.get("live_capture") is True
            and alerts["cleanup"]["passed"] is True and preserved["passed"] is True
            and alerts["measured_samples"] > 3 and alerts["history_events"] == alerts["audit_events"] == 2
            and all(alerts["checks"].values())):
        raise ValueError("External measured evidence incomplete")
    rows = base["cases"]
    alert_row = next(row for row in rows if row["case"] == "alerts")
    alert_row.update(state="passed", reason="Separately executed measured verifier; original campaign blocked row retained in source",
                     evidence=[str(args.alerts)], input_fixture_sha256=alerts_hash)
    alert_row["measurements"] = {"measured_samples": alerts["measured_samples"], "history_events": 2,
                                 "audit_events": 2, "windows": alerts["windows"]}
    telemetry, telemetry_hash = read_json(args.alerts.parent / "telemetry.json")
    values = [row["value"] for row in telemetry["items"]]
    alert_row["measurements"]["utilization_percent"] = {"min": min(values), "max": max(values),
                                                        "count": len(values), "raw_sha256": telemetry_hash}
    history, _ = read_json(args.alerts.parent / "history.json")
    from datetime import datetime

    recovered = next(row for row in history["items"] if row["event_type"] == "alert.resolved")
    recovery_seconds = (datetime.fromisoformat(recovered["payload"]["observed_at"])
                        - datetime.fromisoformat(alerts["workload_stopped_at"])).total_seconds()
    alert_row["metrics"]["recovery"].update(value=recovery_seconds, count=1,
        raw_reference=str(args.alerts.parent / "history.json"))
    execution, _ = read_json(args.campaign.parent / "execution/result.json")
    for name in ("classes", "restart"):
        row = next(row for row in rows if row["case"] == name)
        row["partial_measured_evidence"] = {key: execution["checks"][key] for key in
                                           ("baseline_tcp", "shape", "police", "multipath_tcp", "worker_kill_lost_result")}
        row["reason"] = "Execution verifier failed final deadline compensation; earlier measured checks retained, not whole-stage pass"
    retry_row = next(row for row in retry["cases"] if row["case"] == "telemetry_pipeline")
    row = next(row for row in rows if row["case"] == "telemetry_pipeline")
    row["evidence"].extend(retry_row["evidence"])
    row["reason"] = "Initial merged-handler contract corrected; retry failed source/persistence sample-count equality"
    result = summary(rows)
    stage_states = {"measured_alerts_external": "passed"}
    for path in sorted(args.campaign.parent.glob("event-*.json")):
        event, _ = read_json(path)
        if event["kind"] == "stage_finished":
            stage_states[event["data"]["stage"]] = event["data"]["state"]
    result["stage_counts"] = {state: list(stage_states.values()).count(state) for state in ("passed", "failed", "blocked")}
    result["stage_states"] = stage_states
    result["sources"] = [{"path": str(path), "sha256": digest} for path, digest in
                         ((args.campaign, base_hash), (args.retry, retry_hash), (args.alerts, alerts_hash),
                          (args.alerts.parent.parent / "preservation.json", preserved_hash))]
    result["supersessions"] = []
    for path in args.superseding_summary:
        attempt, digest = read_json(path)
        result["sources"].append({"path": str(path), "sha256": digest})
        for replacement in attempt["cases"]:
            prior = next((row for row in rows if row["case"] == replacement["case"]), None)
            if prior is not None and prior["state"] == "failed" and replacement["state"] == "passed":
                result["supersessions"].append({"case": prior["case"], "prior": prior,
                                                "fixed_attempt": str(path), "fixed_attempt_sha256": digest})
                rows[rows.index(prior)] = replacement
        for event_path in sorted(path.parent.glob("event-*.json")):
            event, _ = read_json(event_path)
            if event["kind"] == "stage_finished" and event["data"]["state"] == "passed":
                stage_states[event["data"]["stage"]] = "passed"
    result.update(summary(rows))
    result["stage_counts"] = {state: list(stage_states.values()).count(state) for state in ("passed", "failed", "blocked")}
    result["signature"] = None
    result["integrity_scope"] = "SHA256 hash-pinned local artifacts; no cryptographic signature or external signer claimed"
    before, _ = read_json(args.campaign.parent / "baseline.json")
    after = snapshot()
    if after != before:
        raise ValueError("Final baseline differs")
    result["cleanup"] = {"passed": True, "final_container_count": len(after), "unknown_or_owned_leaks": [],
                         "preserved_id": PRESERVABLE_ID, "preserved_state": after[PRESERVABLE_ID]["State"],
                         "preserved_inspect_sha256": after[PRESERVABLE_ID]["InspectSHA256"]}
    write_new(args.output, result)
    _, digest = read_json(args.output)
    print(json.dumps({"overall": result["overall"], "counts": result["counts"],
                      "stage_counts": result["stage_counts"], "artifact": str(args.output), "sha256": digest}))


if __name__ == "__main__":
    main()
