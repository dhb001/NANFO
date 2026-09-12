"""ADR019 Step14: operator-launched bounded campaign, never training or final-test replay."""

from __future__ import annotations

import argparse
import ast
import fcntl
import json
import os
import secrets
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from scripts.acceptance.common import (
    IMAGE,
    VERSION,
    Blocked,
    Ledger,
    encoded,
    metrics,
    read_json,
    sha,
    write_new,
)
from scripts.acceptance.runtime import PRESERVABLE_ID, baseline_safe, cleanup, execute, snapshot
from scripts.acceptance.stage import FIXTURE_TESTS

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
STAGES = ("emulation", "execution", "operator_override", "actions", "negative", "reports", "fixtures")
OPERATOR_IMAGE = "sha256:d91efe1717f29a277683b735418877d73243ae24ab80e4c2c3311f6f0343c05c"
MATRIX = {
    "low": (None, "No low-load measured verifier admitted; modeled counterpart only"),
    "ramp": (None, "No measured ramp verifier admitted; modeled counterpart only"),
    "burst": (None, "No measured burst verifier admitted; modeled counterpart only"),
    "overload": (None, "No matched measured overload verifier admitted; modeled counterpart only"),
    "multibottleneck": (None, "Multipath is not multiple independently loaded bottlenecks; modeled counterpart only"),
    "linkfail": ("negative", "Actual Mininet link-down, proposal rejection, restored probes; not convergence certification"),
    "stale": ("negative", "Actual controller SIGSTOP beyond freshness bound, proposal rejection and restored probes"),
    "disconnect": ("negative", "Actual controller termination/restart and proposal rejection; not a Redis/WebSocket outage"),
    "restart": ("execution", "Worker SIGKILL, lost result, exact command replay/readback; operator stage also restarts lab"),
    "unsafe": ("actions", "Expired dispatch, conflicting second action and uncertain rollback block real lab mutation; not DRL+safety"),
    "override": ("operator_override", "Six actual expiry/STOP/revocation/capture/restart cases"),
    "rollback": ("actions", "Actual partial mutation/crash/deadline compensation and switch readback"),
    "classes": ("execution", "Measured DSCP10 shaping, DSCP12 policing, unclassified traffic and restoration"),
    "larger_topology": (None, "Measured larger topology unsupported; separate configured 33-node fluid chain only"),
    "telemetry_pipeline": ("emulation", "Real counter/probe source -> persistence/queries/WebSocket; no artificial loss"),
    "reports": ("reports", "Actual PDF/CSV bytes, authenticated HTTP, checksum/tamper/tenant denial, worker recovery; fixture source not lab"),
    "alerts": (None, "Sustained measured lab alert/recovery verifier not installed; fixture suite is separate"),
    "alerts_fixture": ("fixtures", "Alert detector unit and disposable PostgreSQL tests with measured-typed fixtures, not live telemetry"),
    "registry": ("fixtures", "Metadata registry unit and disposable PostgreSQL transaction races only; no package execution"),
    "report_units": ("fixtures", "Pure artifact rendering/storage unit tests; no measured network claims"),
    "drl_safety": (None, "BLOCKED: installed compatible providers and calibrated safety bounds absent"),
    "power_control": (None, "BLOCKED: no installed physical power measurement/control driver"),
    "repeated_heldout": (None, "No separately predeclared repeat acceptance protocol admitted; never rerun reserved test or train/tune"),
}


def commands(python, directory, owner, image, operator_image):
    return {stage: [python, "-m", "scripts.acceptance.stage", "--live", "--stage", stage,
                    "--directory", str(directory / stage), "--owner", owner,
                    "--image", operator_image if stage == "operator_override" else image]
            for stage in STAGES}


def sources():
    paths = []
    for folder in (BACKEND / "app", BACKEND / "alembic", BACKEND / "scripts", BACKEND / "tests", ROOT / "emulation"):
        paths.extend(path for path in folder.rglob("*.py") if "__pycache__" not in path.parts
                     and "output" not in path.parts and "artifacts" not in path.parts)
    paths += [BACKEND / "pyproject.toml", BACKEND / "poetry.lock", ROOT / "emulation/compose.yaml"]
    return {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in sorted(paths)}


def migration_head():
    revisions, parents = set(), set()
    for path in (BACKEND / "alembic/versions").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_bytes())):
            if isinstance(node, ast.Assign):
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id]
            else:
                continue
            if "revision" in names:
                revisions.add(ast.literal_eval(node.value))
            if "down_revision" in names:
                value = ast.literal_eval(node.value)
                parents.update(value if isinstance(value, tuple) else [value])
    if revisions - parents != {"0019"} or not {"0017", "0018", "0019"} <= revisions:
        raise Blocked("migration_head_not_single_0019")
    return "0019"


def case(name, kind, state="blocked", reason="pending_operator_run", *, fixture=None, references=None):
    return {"case": name, "state": state, "evidence_kind": kind, "version": VERSION,
            "input_fixture_sha256": fixture, "metrics": metrics(), "evidence": references or [],
            "reason": reason, "comparator_scope": "No policy superiority or production autonomy claim"}


def summary(cases):
    counts = {state: sum(row["state"] == state for row in cases) for state in ("passed", "failed", "blocked")}
    return {"version": VERSION, "overall": "partial" if counts["blocked"] else "failed" if counts["failed"] else "passed",
            "counts": counts, "all_network_acceptance_complete": False, "cases": cases}


def artifact_passed(stage, result):
    if result.get("passed") is not True:
        return False
    checks = result.get("checks", {})
    if stage in ("reports", "fixtures"):
        tests = result.get("test_counts", {})
        if not tests.get("tests") or any(tests.get(key, 0) for key in ("skipped", "failures", "errors")):
            return False
        if stage == "reports":
            return all(item in checks for item in ("CSV actual parsed cells", "PDF parsed text", "SHA256 and Content-Length",
                                                   "same-size tamper denial", "foreign tenant download denial"))
        return True
    required = {
        "execution": ("worker_kill_lost_result", "shape", "police", "deadline_compensation"),
        "actions": ("expired_publication_no_mutation", "uncertainty_blocks", "executor_process_death", "mid_action_deadline"),
        "operator_override": ("final", "baseline_capture", "final_capture"),
    }.get(stage, ())
    if not all(key in checks for key in required):
        return False
    if stage == "operator_override":
        if set(result.get("cases", {})) != {"expiry_restart", "stop_during_restoration", "expiry_during_capture",
                                             "stop_during_capture", "lab_restart_holding", "actor_revocation"}:
            return False
        if result.get("cleanup", {}).get("passed") is not True:
            return False
    if stage == "execution" and result.get("cleanup", {}).get("passed") is not True:
        return False
    if stage == "negative":
        return all(result.get("cases", {}).get(name, {}).get("fault_injected") is True
                   and result["cases"][name].get("proposal_rejected") is True
                   and len(result["cases"][name].get("probes", [])) == 4
                   and all(probe["sent"] > 0 and probe["sent"] == probe["received"]
                           for probe in result["cases"][name]["probes"])
                   and bool(result["cases"][name].get("no_mutation_readback"))
                   for name in ("linkfail", "stale", "disconnect"))
    return True


def preflight(expected_sources, *, timeout=10, preserve_stopped=()):
    migration_head()
    if sources() != expected_sources:
        raise Blocked("source_or_migrations_changed_wait_for_agents")
    services = []
    for scope in ([], ["--user"]):
        result = execute(["systemctl", *scope, "list-units", "--type=service", "--state=active,activating",
                          "--no-pager", "--no-legend", "--plain"], timeout=timeout)
        if result["returncode"] or result["timed_out"] or result["bytes"]["stdout"] > 1024 * 1024:
            raise Blocked("training_service_detection_unavailable")
        services.append(result["stdout"].decode(errors="replace"))
    result = execute(["ps", "-eo", "args="], timeout=timeout)
    if result["returncode"] or result["timed_out"] or result["bytes"]["stdout"] > 1024 * 1024:
        raise Blocked("process_detection_unavailable")
    rows = snapshot()
    baseline_safe(rows, "\n".join(services), result["stdout"].decode(errors="replace"), preserve_stopped)
    return rows


def run_stage(stage, argv, directory, owner, baseline, timeout, ledger):
    ledger.append("stage_started", {"stage": stage, "argv": argv, "timeout_seconds": timeout,
                                     "baseline_ids": list(baseline)})
    result = None
    artifact = None
    state = "failed"
    reason = "stage_failed"
    clean = {"passed": False}
    interrupted = False
    try:
        result = execute(argv, timeout=timeout, cwd=BACKEND,
                         env={key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "LANG")}
                         | {"PYTHONPATH": f"{BACKEND}:{ROOT}", "PYTHONDONTWRITEBYTECODE": "1"})
        # Raw output is bounded in memory and discarded. Logs are structured,
        # allowlisted facts so a server stack/secret cannot escape by regex evasion.
        write_new(directory / "process-log.json", {"returncode": result["returncode"], "timed_out": result["timed_out"],
                  "captured_bytes": result["bytes"], "stdout": "withheld", "stderr": "withheld"})
        if result["timed_out"]:
            reason = "stage_timeout"
        elif (directory / "result.json").exists():
            artifact, digest = read_json(directory / "result.json")
            if result["returncode"] == 0 and artifact_passed(stage, artifact):
                state, reason = "passed", "verifier_assertions_and_artifact_checked"
                write_new(directory / "validated.json", {"result_sha256": digest, "state": state})
            elif result["returncode"] == 0:
                reason = "artifact_missing_required_assertions"
    except InterruptedError:
        interrupted = True
        reason = "operator_signal_or_overall_deadline"
    except Exception:
        reason = "stage_or_evidence_validation_failed"
    finally:
        try:
            clean = cleanup(directory, owner, stage, baseline)
        except Exception:
            clean = {"passed": False, "reason": "cleanup_inspection_failed_unknown_resources_preserved"}
        write_new(directory / "cleanup.json", clean)
        if not clean["passed"]:
            state, reason = "blocked", "cleanup_uncertain_later_live_stages_blocked"
        if interrupted:
            state, reason = "blocked", "operator_signal_or_overall_deadline"
        ledger.append("stage_finished", {"stage": stage, "state": state, "reason": reason,
                                          "cleanup": clean, "result": str(directory / "result.json") if artifact else None})
    return state, reason, clean["passed"] and not interrupted, artifact


def measured_metrics(row, stage, artifact, reference):
    if row["state"] != "passed" or not artifact:
        return
    def assign(name, value, count, pointer):
        if value is not None:
            row["metrics"][name].update(value=value, count=count, raw_reference=f"{reference}#{pointer}")
    if stage == "emulation":
        maxima = artifact.get("maxima", {})
        for name, source in (("goodput", "throughput_mbps"), ("rtt", "latency_ms"),
                             ("probe_loss", "packet_loss_percent"), ("queue_backlog", "queue_backlog_bytes")):
            # Port counter throughput is not end-to-end application goodput.
            if name != "goodput":
                assign(name, maxima.get(source), None, f"/maxima/{source}")
        assign("delivered", artifact.get("workload", {}).get("delivered_bytes"), 1, "/workload/delivered_bytes")
    if stage == "negative":
        actual = artifact.get("cases", {}).get(row["case"], {})
        assign("recovery", actual.get("recovery_seconds"), 1, f"/cases/{row['case']}/recovery_seconds")
    if stage == "execution" and row["case"] == "classes":
        # Preserve all classified/unclassified/restored observations, not a misleading average.
        row["measurements"] = {key: artifact["checks"][key] for key in ("shape", "police")}
    if stage == "operator_override":
        row["measurements"] = {name: {"recovery_seconds": value.get("trigger_to_verified_seconds"),
                                       "probes": value.get("after", {}).get("ping")}
                               for name, value in artifact["cases"].items()}


def run(args):
    parent = args.output_parent
    if not parent.is_dir() or parent.is_symlink() or parent.resolve() != parent.absolute():
        raise Blocked("output_parent_must_be_existing_real_directory")
    owner = secrets.token_hex(16)
    directory = parent / ("step14-" + owner)
    directory.mkdir(mode=0o700)
    ledger = Ledger(directory)
    started = time.monotonic()
    deadline = started + args.overall_seconds
    frozen = sources()
    command_map = commands(sys.executable, directory, owner, args.image, args.operator_image)
    manifest = {"version": VERSION, "owner": owner, "started_at": datetime.now(UTC).isoformat(),
                "preserve_stopped_container": args.preserve_stopped_container,
                "selected_stages": args.stages, "retry_of": str(args.retry_of) if args.retry_of else None,
                "overall_cap_seconds": args.overall_seconds, "stage_timeout_seconds": args.stage_seconds,
                "source_hashes": frozen, "commands": command_map,
                "verifier_contracts": {
                    "emulation": {"source": "scripts/verify_emulation.py --live --timeout-seconds 600", "trigger": "traffic; source calculations/persistence/WebSocket"},
                    "execution": {"source": "scripts/verify_execution.py --live", "trigger": "SIGKILL/lost receipt/deadline/DSCP workloads", "migration_adapter": "0012 -> 0019"},
                    "operator_override": {"source": "scripts/verify_operator_override.py --live", "trigger": "six built-in CASES including actual lab restart", "migration_adapter": "0016 -> 0019"},
                    "actions": {"source": "container python -m emulation.runner --verify-actions", "trigger": "existing local fault hooks/expired dispatch/uncertain rollback"},
                    "negative": {"source": "container python /acceptance_negative.py", "trigger": "Mininet link down; controller SIGSTOP 8s; SIGTERM/restart"},
                    "reports": {"source": "python -m scripts.verify_reports --live", "migration_adapter": "0017 -> 0019", "tests": "tests/integration/test_report_postgres.py -q --no-cov", "environment": ["REPORT_TEST_DSN", "REPORT_TEST_REDIS_URL"]},
                    "fixtures": {"source": "python -m pytest", "tests": list(FIXTURE_TESTS), "environment": ["ALERT_TEST_DSN", "PLUGIN_TEST_DSN"], "skip_policy": "any skip blocks acceptance"},
                },
                "environment": {"PYTHONPATH": f"{BACKEND}:{ROOT}", "APP_ENV": "verification",
                                "POSTGRES_DB": "owned disposable only", "migration_head_required": "0019",
                                "credentials": "fresh random private environment; never serialized",
                                "training": "never launched", "deployment_configuration": "unchanged"},
                "matrix": {name: {"stage": stage, "scope": reason} for name, (stage, reason) in MATRIX.items()}}
    write_new(directory / "manifest.json", manifest)
    rows = [case(name, "unit" if stage == "fixtures" else "measured", reason=reason, fixture=sha(encoded({"stage": stage, "scope": reason, "sources": frozen})))
            for name, (stage, reason) in MATRIX.items()]
    ledger.append("campaign_created", {"manifest": str(directory / "manifest.json"), "cases": rows})
    historical_row = case("drl_alone", "historical", reason="Historical heldout artifact not yet verified")
    rows.append(historical_row)
    ledger.append("case_finished", historical_row)
    try:
        from scripts.acceptance.modeled import run_models

        for name, value in run_models().items():
            path = directory / f"modeled-{name}.json"
            write_new(path, value)
            row = case("modeled_" + name, "modeled", "passed", value["scope"],
                       fixture=value["input_fixture_sha256"], references=[str(path)])
            row["version"] = value["version"]
            row["metrics"]["delivered"].update(value=value["result"]["delivered_bytes"], count=40,
                                               raw_reference=f"{path}#/result/delivered_bytes")
            row["modeled_metrics"] = {key: value["result"][key] for key in
                                      ("offered_bytes", "delivered_bytes", "dropped_bytes", "queued_bytes", "inflight_bytes", "throughput_mbps", "latency_ms")}
            rows.append(row)
            ledger.append("case_finished", row)
        if args.historical_json:
            historical, digest = read_json(args.historical_json)
            if digest != args.historical_sha256 or historical.get("comparable_held_out_schedules") is not True:
                raise Blocked("historical_heldout_hash_or_contract_mismatch")
            row = case("drl_alone", "historical", "passed", "Historical heldout artifact integrity only; no rerun, model inference or new measured claim",
                       fixture=digest, references=[str(args.historical_json.resolve())])
            row["comparator_scope"] = "Historical matched heldout comparison only; raw artifact retained at reference"
        else:
            row = case("drl_alone", "historical", reason="Operator must supply historical heldout JSON plus expected SHA256")
        rows[rows.index(historical_row)] = row
        ledger.append("case_finished", row)
        if not args.live:
            raise Blocked("live_not_authorized_plan_and_models_only")
        # All accepting campaign processes share this inode; never unlink a flock file.
        lockpath = Path("/tmp/opencode/nanfo-step14-lab.lock")
        fd = os.open(lockpath, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if time.monotonic() + args.quiet_seconds + 180 >= deadline:
                raise Blocked("overall_budget_before_quiescence")
            time.sleep(args.quiet_seconds)
            baseline = preflight(frozen, preserve_stopped=args.preserve_stopped_container)
            write_new(directory / "baseline.json", baseline)
            safe = True
            for stage in STAGES:
                if stage not in args.stages:
                    continue
                targets = [row for row in rows if MATRIX.get(row["case"], (None,))[0] == stage]
                if not safe:
                    for row in targets:
                        row["reason"] = "previous_cleanup_or_baseline_unsafe"
                    continue
                remaining = deadline - time.monotonic() - 180
                if remaining < 60:
                    for row in targets:
                        row["reason"] = "finite_overall_budget_exhausted"
                    continue
                try:
                    current = preflight(frozen, preserve_stopped=args.preserve_stopped_container)
                    if current != baseline:
                        raise Blocked("baseline_drift_before_stage")
                except Exception as error:
                    ledger.append("stage_admission_rejected", {"stage": stage,
                                  "reason": str(error) if isinstance(error, Blocked) else type(error).__name__})
                    safe = False
                    for row in targets:
                        row["reason"] = "source_service_or_baseline_changed"
                    continue
                remaining = deadline - time.monotonic() - 180
                if remaining < 60:
                    for row in targets:
                        row["reason"] = "finite_overall_budget_exhausted"
                    continue
                stage_dir = directory / stage
                stage_dir.mkdir(mode=0o700)
                write_new(stage_dir / "baseline-before.json", current)
                image = args.operator_image if stage == "operator_override" else args.image
                write_new(stage_dir / "admission.json", {"owner": owner, "stage": stage, "image": image})
                state, reason, safe, artifact = run_stage(stage, command_map[stage], stage_dir, owner, baseline,
                                                         min(args.stage_seconds, remaining), ledger)
                for row in targets:
                    row.update(state=state, reason=reason, evidence=[str(stage_dir)])
                    measured_metrics(row, stage, artifact, stage_dir / "result.json")
                    ledger.append("case_finished", row)
        finally:
            os.close(fd)
    except Blocked as error:
        ledger.append("campaign_blocked", {"reason": str(error)})
    except BaseException:
        ledger.append("campaign_blocked", {"reason": "unexpected_failure_diagnostics_withheld"})
    for row in rows:
        ledger.append("case_finished", row)
    result = summary(rows)
    result.update(elapsed_seconds=time.monotonic() - started, manifest=str(directory / "manifest.json"),
                  ledger_directory=str(directory), live_authorized=args.live)
    write_new(directory / "summary.json", result)
    ledger.append("campaign_finished", {"overall": result["overall"], "summary": str(directory / "summary.json")})
    print(json.dumps({"overall": result["overall"], "summary": str(directory / "summary.json"), "counts": result["counts"]}))
    return 0 if args.plan else 2 if result["overall"] == "partial" else 1 if result["overall"] == "failed" else 0


def status(directory):
    ledger = Ledger(directory)  # Validates full durable chain before trusting status.
    rows = {}
    stages = {}
    for path in sorted(directory.glob("event-*.json")):
        event, _ = read_json(path)
        if event["kind"] == "campaign_created":
            rows.update({row["case"]: row for row in event["data"]["cases"]})
        elif event["kind"] == "case_finished":
            rows[event["data"]["case"]] = event["data"]
        elif event["kind"] == "stage_started":
            stages[event["data"]["stage"]] = "interrupted_or_running"
        elif event["kind"] == "stage_finished":
            stages[event["data"]["stage"]] = event["data"]["state"]
    return {**summary(list(rows.values())), "ledger_events": ledger.sequence, "stages": stages,
            "resume_policy": "Read-only status recovery; a new explicit --live attempt uses a new directory and fresh baseline, never overwrites or blindly replays"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--plan", action="store_true", help="Generate modeled evidence and command manifest only; no service/Docker calls")
    mode.add_argument("--status", type=Path, help="Recover read-only durable status after interruption")
    parser.add_argument("--agents-idle", action="store_true", help="Operator confirms other agents/migrations are finished; mandatory with --live")
    parser.add_argument("--output-parent", type=Path, default=Path("/tmp/opencode"))
    parser.add_argument("--image", default=OPERATOR_IMAGE, help="Immutable manual campus image; do not retag defaults")
    parser.add_argument("--operator-image", default=OPERATOR_IMAGE, help="Immutable capture-capable ADR018 image")
    parser.add_argument("--overall-seconds", type=int, default=7200)
    parser.add_argument("--stage-seconds", type=int, default=1000)
    parser.add_argument("--quiet-seconds", type=int, default=30)
    parser.add_argument("--historical-json", type=Path)
    parser.add_argument("--historical-sha256")
    parser.add_argument("--stages", nargs="+", choices=STAGES, default=list(STAGES), help="Explicit stage selection for infrastructure-only retries")
    parser.add_argument("--retry-of", type=Path, help="Prior immutable campaign summary retained alongside this retry")
    parser.add_argument("--preserve-stopped-container", action="append", default=[], choices=[PRESERVABLE_ID],
                        help="Explicit approved full-ID preserve-only exception; exited state and full inspect hash must remain unchanged")
    args = parser.parse_args(argv)
    if args.live and not args.agents_idle:
        parser.error("--live requires --agents-idle after parent/operator authorization; no resources created")
    if not (300 <= args.overall_seconds <= 7200 and 60 <= args.stage_seconds <= 1200 and 10 <= args.quiet_seconds <= 120):
        parser.error("Finite bounds required: overall 300..7200, stage 60..1200, quiet 10..120 seconds")
    if not IMAGE.fullmatch(args.image) or not IMAGE.fullmatch(args.operator_image):
        parser.error("Use immutable sha256 image IDs; deployment image aliases are never changed")
    if bool(args.historical_json) != bool(args.historical_sha256):
        parser.error("Historical JSON requires its independently supplied SHA256")
    try:
        if args.status:
            print(json.dumps(status(args.status)))
            return 0
        def interrupted(signum, frame):
            raise InterruptedError("operator_signal")
        previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM)}
        try:
            # Independent overall watchdog reserves 120 seconds for bounded owned
            # cleanup and durable finalization, including preflight/model work.
            signal.setitimer(signal.ITIMER_REAL, args.overall_seconds - 120)
            return run(args)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    except BaseException:
        print(json.dumps({"overall": "partial", "reason": "campaign_failed_closed_diagnostics_withheld"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
