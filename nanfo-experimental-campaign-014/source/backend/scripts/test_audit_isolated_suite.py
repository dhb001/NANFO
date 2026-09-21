"""Isolation/evidence regressions for the owned disposable database runner."""

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from scripts import audit_isolated_suite as runner


def test_selections_reject_external_paths_options_and_privileged_suites():
    for value in ("--override-ini=addopts=", "/tmp/probe.py", "../probe.py",
                  "tests/integration/test_distributed_main_sockets.py"):
        with pytest.raises(argparse.ArgumentTypeError):
            runner.selected_test(value)
    node = "tests/integration/test_network_outbox_postgres.py::test_lost_ack_restart_replays_identical_wire_event"
    assert runner.selected_test(node) == node


def test_junit_counts_distinguish_failures_errors_and_skips(tmp_path):
    report = tmp_path / "cases.xml"
    assert runner.junit_counts(report) is None
    report.write_text('''<testsuites><testsuite>
      <testcase/><testcase classname="suite" name="failed"><failure/></testcase>
      <testcase classname="suite" name="error"><error/></testcase>
      <testcase><skipped/></testcase><testcase/>
    </testsuite></testsuites>''')
    assert runner.junit_counts(report) == {"total": 5, "passed": 2, "failed": 1, "errors": 1, "skipped": 1}
    assert runner.junit_failures(report) == ["suite::failed", "suite::error"]


def test_startup_failure_cleans_owned_tree_and_never_inherits_external_targets(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("EXPERIMENTAL_TEST_DSN", "postgresql://external.invalid/store")
    monkeypatch.setenv("AUTH_TEST_REDIS_URL", "redis://external.invalid/0")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--unsafe-option")
    monkeypatch.setenv("RUN_DISTRIBUTED_REALTIME", "1")
    monkeypatch.setattr(runner.shutil, "which", lambda *args, **kwargs: "/installed/binary")
    seen = {}

    def fail(lab):
        seen.update(runner.child_environment(lab, redis=False))
        seen["owned_root"] = lab.root
        raise RuntimeError("credential-canary")

    monkeypatch.setattr(runner.LocalLab, "start_postgres", fail)
    report = tmp_path / "result.json"
    assert runner.main(["--report", str(report)]) == 2
    result = json.loads(report.read_text())
    assert result["counts"] is None and result["pytest_exit"] is None
    assert result["cleanup"]["private_tree_removed"] and result["cleanup"]["children_reaped"]
    assert not Path(seen["owned_root"]).exists()
    assert "external.invalid" not in repr(seen)
    assert all(key not in seen for key in ("AUTH_TEST_REDIS_URL", "PYTEST_ADDOPTS", "RUN_DISTRIBUTED_REALTIME"))
    assert "credential-canary" not in report.read_text() + capsys.readouterr().out


def test_missing_approved_redis_fails_before_allocating_services(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("missing Redis must fail before allocating services")

    monkeypatch.setattr(runner.tempfile, "mkdtemp", forbidden)
    with pytest.raises(SystemExit) as error:
        runner.main(["--redis-server", str(tmp_path / "redis-server")])
    assert error.value.code == 2


@pytest.mark.parametrize("output,expected", [
    ("Redis server v=7.4.5 sha=00000000:0 malloc=jemalloc", "redis 7.4.5"),
    ("Valkey server v=8.1.3 sha=00000000:0 malloc=jemalloc", "valkey 8.1.3"),
    ("Redis server v=6.2.0", None), ("unrelated v=8.0.0", None),
])
def test_approved_redis_compatible_versions(monkeypatch, output, expected):
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 0, output))
    if expected:
        assert runner.redis_version(Path("/approved/server")) == expected
    else:
        with pytest.raises(ValueError):
            runner.redis_version(Path("/approved/server"))


def test_postgres_diagnostics_never_export_message_or_credentials(tmp_path):
    lab = runner.AuditLab(tmp_path, None)
    line = "AUDITPG 53100 PANIC: could not write secret-canary: No space left on device"
    lab.pg_log_tail.append(line)
    lab.pg_diagnostic_counts.update(runner.postgres_log_codes(line))
    result = lab.diagnostics()
    assert result["codes"] == {"sqlstate_53100": 1, "severity_panic": 1, "disk_full": 1, "write_failed": 1}
    assert "secret-canary" not in json.dumps(result)
    assert runner.postgres_log_codes("server process was terminated by signal 9: private") == ["child_sigkill"]
    assert runner.postgres_log_codes("untrusted secret message") == []


def test_postgres_spawn_keeps_durability_and_bounded_memory_log(tmp_path, monkeypatch):
    import io
    from unittest.mock import Mock

    child = Mock(pid=999)
    child.stderr = io.BytesIO(b"AUDITPG XX000 PANIC: private\n" * 200)
    spawn = Mock(return_value=child)
    monkeypatch.setattr(runner.subprocess, "Popen", spawn)
    lab = runner.AuditLab(tmp_path, None)
    assert lab.spawn(["postgres", "-h", "127.0.0.1"]) is child
    lab.pg_log_thread.join(timeout=2)
    assert not lab.pg_log_thread.is_alive()
    assert len(lab.pg_log_tail) == 128
    assert lab.pg_diagnostic_counts["severity_panic"] == 200
    args = spawn.call_args.args[0]
    assert "shared_buffers=32MB" in args and "max_wal_size=128MB" in args
    assert "fsync=off" not in args and "full_page_writes=off" not in args
    assert lab.pids == [999]
