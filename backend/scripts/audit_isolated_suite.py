"""Bounded audit fixtures on owned loopback PostgreSQL and optional local Redis.

From backend: poetry run python -m scripts.audit_isolated_suite
Use --redis-server /absolute/installed/redis-server to authorize local Redis.
Never accepts a DSN, installs software, or invokes Docker/privileged lab tooling.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from collections import Counter, deque
from pathlib import Path

from sqlalchemy.engine import URL

from scripts.verify_measured_twin import BACKEND, LocalLab, environment

POSTGRES_SUITES = (
    "intent_execution", "report", "autonomy", "autonomy_operator", "simulation",
    "alert", "plugin", "network_outbox", "spatial", "asset", "telemetry_lifecycle",
    "retention_complete", "fleet", "autonomous_execution", "experimental_lab",
    "network_inventory", "identity_audit_repair", "alert_scope", "workflow_history",
)
EXTRA_TESTS = (
    "tests/integration/test_telemetry_history_sql.py",
    "tests/integration/test_login_rate_limit_redis.py",
    "scripts/test_audit_role_profiles.py",
    "scripts/test_audit_http_smoke.py",
)
DEFAULT_TESTS = tuple(f"tests/integration/test_{name}_postgres.py" for name in POSTGRES_SUITES) + EXTRA_TESTS
DSN_PREFIXES = (
    "INTENT", "REPORT", "AUTONOMY", "SIMULATION", "ALERT", "PLUGIN", "NETWORK_OUTBOX",
    "SPATIAL", "ASSET", "TELEMETRY", "RETENTION", "FLEET", "EXPERIMENTAL", "AUDIT", "IDENTITY",
)


class AuditLab(LocalLab):
    """Bound database lock/query waits as well as the overall pytest process."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pg_log_tail = deque(maxlen=128)
        self.pg_diagnostic_counts = Counter()
        self.pg_log_thread = None

    def spawn(self, argv: list[str]):
        if argv[0] != "postgres":
            return super().spawn(argv)
        # Small, durable test cluster on tmpfs; do not disable WAL/fsync safety.
        settings = (
            "lock_timeout=30s", "statement_timeout=120s", "shared_buffers=32MB",
            "work_mem=2MB", "maintenance_work_mem=16MB", "max_connections=40",
            "min_wal_size=32MB", "max_wal_size=128MB", "checkpoint_timeout=30s",
            "log_min_messages=log", "log_min_error_statement=panic",
            "log_statement=none", "log_error_verbosity=terse", "log_line_prefix=AUDITPG %e ",
        )
        argv = [*argv, *[part for setting in settings for part in ("-c", setting)]]
        child = subprocess.Popen(argv, cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.pids.append(child.pid)

        def drain():
            with child.stderr as stream:
                while chunk := stream.readline(4096):
                    line = chunk.decode("utf-8", errors="replace")
                    self.pg_log_tail.append(line)
                    self.pg_diagnostic_counts.update(postgres_log_codes(line))

        self.pg_log_thread = threading.Thread(target=drain, daemon=True)
        self.pg_log_thread.start()
        return child

    def diagnostics(self):
        return {"exit_code_before_cleanup": self.pg.poll() if self.pg else None,
                "codes": dict(self.pg_diagnostic_counts),
                "private_tail_bytes": sum(len(line.encode()) for line in self.pg_log_tail),
                "tmp_free_bytes": shutil.disk_usage(self.root).free}

    def cleanup(self):
        result = super().cleanup()
        if self.pg_log_thread:
            self.pg_log_thread.join(timeout=5)
            result["postgres_log_reader_reaped"] = not self.pg_log_thread.is_alive()
        self.pg_log_tail.clear()
        return result


def postgres_log_codes(line: str) -> list[str]:
    """Only code-owned classifications/SQLSTATE cross the private log boundary."""
    codes = []
    match = re.match(r"AUDITPG ([0-9A-Z]{5}) (WARNING|ERROR|FATAL|PANIC):", line)
    if match:
        codes.extend((f"sqlstate_{match[1]}", f"severity_{match[2].lower()}"))
    for needle, code in (
        ("No space left on device", "disk_full"), ("Cannot allocate memory", "memory_allocation_failed"),
        ("out of memory", "out_of_memory"), ("terminated by signal 9", "child_sigkill"),
        ("terminated by signal 11", "child_sigsegv"), ("terminated by signal 7", "child_sigbus"),
        ("database system is in recovery mode", "recovery_mode"),
        ("could not write", "write_failed"), ("could not fsync", "fsync_failed"),
        ("could not open file", "open_failed"), ("No such file or directory", "file_missing"),
        ("File size limit exceeded", "file_size_limit"),
    ):
        if needle in line:
            codes.append(code)
    return codes


def selected_test(value: str) -> str:
    """Allow node IDs and new owner-provided PostgreSQL tests, never pytest options."""
    filename = value.split("::", 1)[0]
    path = Path(filename)
    allowed = filename in EXTRA_TESTS or (
        path.parent == Path("tests/integration")
        and path.name.startswith("test_") and path.name.endswith("_postgres.py")
    )
    if not allowed or not (BACKEND / path).is_file():
        raise argparse.ArgumentTypeError("select an existing isolated PostgreSQL test or listed audit/Redis test")
    return value


def child_environment(lab: LocalLab, *, redis: bool) -> dict[str, str]:
    env = dict(lab.env)
    url = URL.create("postgresql+asyncpg", username="lab_owner",
                     password=env["POSTGRES_PASSWORD"], host="127.0.0.1",
                     port=lab.pg_port, database="postgres")
    for prefix in DSN_PREFIXES:
        env[f"{prefix}_TEST_DSN"] = url.render_as_string(hide_password=False)
    if redis:
        for index, prefix in enumerate(("INTENT", "REPORT", "AUTH", "AUDIT", "AUDIT_HTTP")):
            env[f"{prefix}_TEST_REDIS_URL"] = (
                f"redis://:{env['REDIS_PASSWORD']}@127.0.0.1:{lab.redis_port}/{index}"
            )
    env["PYTHONPATH"] = os.pathsep.join((str(BACKEND), str(BACKEND.parent)))
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def junit_counts(path: Path) -> dict[str, int] | None:
    if not path.exists():
        return None
    cases = ET.parse(path).getroot().findall(".//testcase")
    counts = {"total": len(cases), "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for case in cases:
        outcome = next((name for tag, name in (("error", "errors"), ("failure", "failed"), ("skipped", "skipped"))
                        if case.find(tag) is not None), "passed")
        counts[outcome] += 1
    return counts


def junit_failures(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [f"{case.get('classname')}::{case.get('name')}"
            for case in ET.parse(path).getroot().findall(".//testcase")
            if case.find("failure") is not None or case.find("error") is not None]


def redis_version(binary: Path) -> str:
    """Redis7+ or Valkey7+ supports the EXPIRE NX/session Lua fixture contracts."""
    result = subprocess.run([str(binary), "--version"], capture_output=True, text=True,
                            timeout=5, check=True)
    match = re.search(r"\b(Redis|Valkey) server v=(\d+)\.(\d+)\.(\d+)", result.stdout, re.IGNORECASE)
    if not match or int(match[2]) < 7:
        raise ValueError("Redis or Valkey server version7+ required")
    return f"{match[1].lower()} {match[2]}.{match[3]}.{match[4]}"


def run_pytest(argv: list[str], env: dict[str, str], root: Path, timeout: int) -> int:
    # Keep exception text/credentials private; print redacted output after the child exits.
    log = root / "pytest.log"
    with log.open("w+") as output:
        process = subprocess.Popen(argv, cwd=BACKEND, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        finally:
            # Also reap helpers left in this exact child process group on cancellation.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            output.seek(0)
            text = output.read()
            for key, value in env.items():
                if key.endswith(("_PASSWORD", "_SECRET_KEY", "_TEST_DSN", "_TEST_REDIS_URL")):
                    text = text.replace(value, "[private]")
            print(text, end="", flush=True)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="append", type=selected_test, help="repeatable file or pytest node ID")
    parser.add_argument("--redis-server", type=Path, help="approved installed Redis7+/Valkey7+ absolute binary")
    parser.add_argument("--timeout", type=int, default=600, help="pytest wall-clock seconds (1..1200)")
    parser.add_argument("--report", type=Path, help="new JSON evidence file; parent must already exist")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 1200:
        parser.error("timeout must be between 1 and 1200 seconds")
    if args.redis_server and (not args.redis_server.is_absolute() or not args.redis_server.is_file()
                             or not os.access(args.redis_server, os.X_OK)):
        parser.error("approved redis-server executable is missing; no install/container fallback")
    version = None
    if args.redis_server:
        try:
            version = redis_version(args.redis_server)
        except (OSError, ValueError, subprocess.SubprocessError):
            parser.error("approved binary must report Redis/Valkey server version7+; no fallback")
    if args.report and (args.report.exists() or not args.report.parent.is_dir()):
        parser.error("report must be a new file in an existing directory")
    # Do not inherit external DSNs, pytest options, lab opt-ins, or application settings.
    clean = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT") if key in os.environ}
    if not all(shutil.which(name, path=clean.get("PATH")) for name in ("initdb", "postgres")):
        parser.error("installed initdb/postgres must be on PATH; no install/container fallback")
    parent = Path("/tmp/opencode")
    parent.mkdir(mode=0o700, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="nanfo-audit-suite-", dir=parent))
    result = {"status": "blocked", "tests": args.test or list(DEFAULT_TESTS), "pytest_exit": None,
              "counts": None, "redis": "local" if args.redis_server else "not_requested",
              "redis_version": version,
              "blockers": [] if args.redis_server else ["real_redis_not_exercised"]}
    lab = None
    code = 2

    def interrupted(signum, _frame):
        raise InterruptedError(signum)

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        with environment(clean):
            lab = AuditLab(root, str(args.redis_server) if args.redis_server else None)
        lab.start_postgres()
        if args.redis_server:
            lab.start_redis()
        xml = root / "results.xml"
        command = [sys.executable, "-m", "pytest", "-p", "pytest_asyncio.plugin", "-p", "pytest_cov.plugin",
                   "-p", "no:cacheprovider", *result["tests"], "-v", "--no-cov", "--tb=short", "-rs",
                   f"--basetemp={root / 'pytest-tmp'}", f"--junitxml={xml}"]
        try:
            code = run_pytest(command, child_environment(lab, redis=bool(args.redis_server)), root, args.timeout)
            result["pytest_exit"] = code
        finally:
            result["counts"] = junit_counts(xml)
            result["failed_cases"] = junit_failures(xml)
        if result["counts"] is None or not result["counts"]["total"]:
            raise RuntimeError("pytest_report_missing_or_empty")
        result["status"] = "failed" if code else (
            "partial" if result["blockers"] or result["counts"]["skipped"] else "passed"
        )
    except (Exception, KeyboardInterrupt) as exc:
        result["failure"] = type(exc).__name__  # never persist raw connection/credential exceptions
        result["status"] = "incomplete"
        code = 2
    finally:
        try:
            if lab:
                result["postgres_diagnostics"] = lab.diagnostics()
                result["cleanup"] = lab.cleanup()
            else:
                shutil.rmtree(root)
                result["cleanup"] = {"private_tree_removed": not root.exists()}
            if not all(value for key, value in result["cleanup"].items() if key != "owned_pids"):
                result["status"] = "cleanup_failed"
                code = 2
        finally:
            signal.signal(signal.SIGTERM, previous)
        serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.report:
            with args.report.open("x") as output:
                output.write(serialized)
        print(serialized, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
