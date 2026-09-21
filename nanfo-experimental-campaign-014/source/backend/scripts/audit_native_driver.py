"""Read-only reconstruction of retained manual native-driver campaign evidence.

Does not trust result case booleans, derive calibration or contact a device.
"""

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from emulation.autonomous_frr import LinuxFRRDriver  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def logs(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    stamps = [r["monotonic_ns"] for r in rows]
    if stamps != sorted(stamps) or any(type(r["wall_ns"]) is not int or type(r["monotonic_ns"]) is not int for r in rows):
        raise ValueError("raw_integer_chronology_invalid")
    return rows


def audit(root):
    root = Path(root)
    protocol, reported = read(root / "protocol.json"), read(root / "result.json")
    if any(reported[k] is not False for k in ("autonomy_qualified", "safety_calibrated", "physical_rf_qualified", "hard_transition_deadline_proved", "receiver_journal_acceptance")):
        raise ValueError("overclaimed_native_campaign")
    for path, pin in protocol["source_sha256"].items():
        if hashlib.sha256((root / "source" / path).read_bytes()).hexdigest() != pin:
            raise ValueError("source_pin_changed")
    inspected = read(root / "container.json")[0]
    if (inspected["Image"] != protocol["image_id"] or inspected["HostConfig"]["NetworkMode"] != "none"
            or inspected["HostConfig"]["PidMode"] or inspected["HostConfig"]["IpcMode"] == "host"
            or inspected["HostConfig"]["NanoCpus"] != 2000000000
            or inspected["HostConfig"]["PidsLimit"] != 256):
        raise ValueError("container_isolation_mismatch")
    all_rows, snapshots, mutations, cases, probe_results = [], 0, 0, [], []
    for action in (0, 1):
        directory = root / f"action{action}"
        fixture_rows = logs(directory / "fixture.jsonl")
        all_rows.extend(fixture_rows)
        seal_end = next(r["monotonic_ns"] for r in fixture_rows if r["kind"] == "sealed_epoch_closed")
        cleanup = [r for r in fixture_rows if r["kind"] == "namespace_cleanup"]
        if len(cleanup) != 1 or cleanup[0]["still_present"]:
            raise ValueError("namespace_cleanup_unconfirmed")
        if len(read(directory / "namespaces.json")["namespaces"]) != 9:
            raise ValueError("namespace_scope_incomplete")
        for case_name in protocol["cases_per_action"]:
            if case_name == "exclusive-lock":
                # Driver acquisition failed on the actual same inode in harness;
                # result is scoped exception evidence, not a raw command claim.
                cases.append(dict(action=action, case=case_name, evidence="owner_exception_case"))
                continue
            case = directory / case_name
            if case_name == "binding-refusal-0":
                cases.append(dict(action=action, case=case_name, evidence="owner_exception_case"))
                continue
            prepared = read(case / "prepared.json")
            if hashlib.sha256((case / "prepared.json").read_bytes()).hexdigest() != (case / "prepared.sha256").read_text():
                raise ValueError("prepared_pin_changed")
            expected = [(r["node"], LinuxFRRDriver.command(r, k, "add")) for r in prepared["resources"] for k in ("routes", "rules")]
            if len(expected) != 12:
                raise ValueError("wrong_command_graph")
            apply_log = list(case.glob("apply-*.jsonl"))
            if len(apply_log) != 1:
                raise ValueError("ambiguous_apply_trace")
            rows = logs(apply_log[0])
            all_rows.extend(rows)
            authority = [r for r in rows if r["kind"] == "apply_authority"]
            k = int(case_name.split("-")[-1]) if case_name.startswith("STOP-") else 0 if case_name == "expired-0" else 3 if case_name in {"restart-3", "lost-receipt-3"} else 12
            if [(r["context"]["node"], r["context"]["argv"]) for r in authority] != expected[:k]:
                raise ValueError("actual_apply_authority_graph_mismatch")
            writes = [r for r in rows if r["kind"] == "native_result" and "--" in r["argv"]
                      and r["argv"][r["argv"].index("--") + 1:r["argv"].index("--") + 4] in (["ip", "route", "add"], ["ip", "rule", "add"])]
            if len(writes) != k or any(r["returncode"] for r in writes):
                raise ValueError("actual_apply_kernel_writes_mismatch")
            for check, operation in zip(authority, writes):
                if check["monotonic_ns"] >= operation["monotonic_ns"] or operation["argv"][operation["argv"].index("--") + 1:] != check["context"]["argv"]:
                    raise ValueError("actual_command_authority_mismatch")
            denied = [r for r in rows if r["kind"] in {"STOP_denied", "expiry_denied"}]
            if (case_name.startswith("STOP-") and k < 12) or case_name == "expired-0":
                if len(denied) != 1 or any(w["monotonic_ns"] > denied[0]["monotonic_ns"] for w in writes):
                    raise ValueError("post_denial_native_write")
            recovery_rows = []
            for log in case.glob("recover-*.jsonl"):
                recovery_rows.extend(logs(log))
            recovery_rows.sort(key=lambda r: r["monotonic_ns"])
            all_rows.extend(recovery_rows)
            deletes = [r for r in recovery_rows if r["kind"] == "native_result" and "--" in r["argv"]
                       and r["argv"][r["argv"].index("--") + 1:r["argv"].index("--") + 4] in (["ip", "rule", "del"], ["ip", "route", "del"])]
            if len(deletes) != k or any(r["returncode"] for r in deletes):
                raise ValueError("actual_recovery_delete_count_mismatch")
            expected_deletes = []
            for node, command in reversed(expected[:k]):
                command = [value for value in command if value != "onlink"]
                command[2] = "del"
                expected_deletes.append((node, command))
            recovery_checks = [r for r in recovery_rows if r["kind"] == "recovery_authority"]
            if [(r["context"]["node"], r["context"]["argv"]) for r in recovery_checks] != expected_deletes:
                raise ValueError("actual_reverse_compensation_graph_mismatch")
            for check, operation in zip(recovery_checks, deletes):
                if check["monotonic_ns"] >= operation["monotonic_ns"] or operation["argv"][operation["argv"].index("--") + 1:] != check["context"]["argv"]:
                    raise ValueError("actual_recovery_authority_mismatch")
            second = json.loads(read(case / "recovery-process-1.json")["stdout"])
            if second["deletes"] != 0 or not second["restoration_verified"]:
                raise ValueError("idempotent_recovery_failed")
            baseline_hash = hashlib.sha256(json.dumps(prepared["before"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if second["readback_sha256"] != baseline_hash:
                raise ValueError("baseline_not_exactly_restored")
            if case_name == "foreign-12":
                foreign = read(case / "foreign-refusal.json")
                if foreign["deletes"] or foreign["before"] != foreign["after"]:
                    raise ValueError("foreign_state_changed")
            if case_name == "normal-12":
                probes = read(case / "unsealed-verification.json")
                if probes["probe"] != {"sent": 6, "received": 6} or not probes["readback_verified"]:
                    raise ValueError("real_reachability_failed")
                probe_results.append(dict(action=action, **probes))
            mutations += len(writes) + len(deletes)
            cases.append(dict(action=action, case=case_name, native_adds=k, native_deletes=k,
                apply_elapsed_seconds=(writes[-1]["monotonic_ns"] - authority[0]["monotonic_ns"]) / 1e9 if writes else 0))
        pings = [r for r in fixture_rows if r["kind"] == "native_result" and "ping" in r["argv"]]
        if len(pings) != 2 or any(r["monotonic_ns"] <= seal_end or r["returncode"] != 0 for r in pings):
            raise ValueError("probe_executed_before_epoch_closed")
    for row in all_rows:
        if row["kind"] == "queue_snapshot":
            snapshots += 1
            if len(row["capture"]["reads"]) != 22:
                raise ValueError("incomplete_endpoint_snapshot")
            for endpoint in row["capture"]["reads"]:
                for qdisc in endpoint["qdiscs"]:
                    if qdisc["kind"] != "clsact" and any(qdisc[key] != 0 for key in ("backlog", "qlen", "bytes", "packets")):
                        raise ValueError("sealed_nonzero_queue")
    durations = [r["elapsed_ns"] / 1e9 for r in all_rows if r["kind"] in {"native_result", "command_result"}]
    if any(value >= 5 for value in durations):
        raise ValueError("native_command_timeout_bound_exceeded")
    cleanup = read(root / "cleanup.json")
    if not cleanup["removed"] or cleanup["unresolved_resources"]:
        raise ValueError("owned_container_cleanup_incomplete")
    return dict(status="passed", claim="native-driver-verified", independent_signoff=False,
        image_id=protocol["image_id"], protocol_sha256=hashlib.sha256((root / "protocol.json").read_bytes()).hexdigest(),
        cases=cases, total_cases=len(cases), native_policy_mutations=mutations, sealed_snapshots=snapshots,
        sealed_endpoint_readbacks=snapshots * 22, actual_probes=probe_results,
        native_command_count=len(durations), max_command_seconds=max(durations), median_command_seconds=statistics.median(durations),
        measured_campaign_seconds=(max(r["monotonic_ns"] for r in all_rows) - min(r["monotonic_ns"] for r in all_rows)) / 1e9,
        calibration_installed=False, autonomy_qualified=False, hard_transition_deadline_proved=False,
        caveats=["Static-FIB manual fixture, not OSPF convergence or model qualification.",
                 "Seal theorem remains conditional on reviewed kernel/enforcement premises.",
                 "Lock/binding exception cases use owner exception receipts; not native syscalls."])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.root)
    if args.output:
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
    print(json.dumps(result, indent=2, sort_keys=True))
