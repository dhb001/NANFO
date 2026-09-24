"""Supervise one long-running retention loop and publish work-coupled heartbeats.

    python /opt/nanfo/deploy/supervise.py run --loop NAME -- COMMAND...
    python /opt/nanfo/deploy/supervise.py check --loop NAME

The child is the documented owner CLI, unchanged (ADR-028 C14 stream retention,
BE-Telemetry retention loop). Its output lines are relayed unchanged. Only lines that
prove a *completed* cycle refresh ``${WORKER_HEARTBEAT_PATH}.<loop>``, written in the
backend heartbeat format (child pid, kernel process start, monotonic progress), so the
probe proves progress rather than process existence. A start record is written when
the child is spawned: a first pass that never completes becomes stale after the
loop's maximum age. SIGTERM/SIGINT are forwarded to the child and its exit status is
returned; ``restart: unless-stopped`` restarts every non-zero exit (refusal exit 3,
watchdog exit 70). Output never includes environment values.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LINE_LIMIT = 65536
RECORD_LIMIT = 1024
# Event emitted by app/modules/telemetry/retention_worker.py after every completed pass.
TELEMETRY_PASS_COMPLETED = "telemetry_retention_pass_completed"


def _positive_int(environ, name, default):
    raw = environ.get(name)
    value = default if raw in (None, "") else int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _stream_progress(line):
    """scripts.stream_retention schedule prints one JSON object per cycle."""
    try:
        value = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(value, dict) and value.get("mode") == "schedule" and value.get("status") == "ok"


def _stream_max_age(environ):
    interval = _positive_int(environ, "NANFO_STREAM_RETENTION_INTERVAL_SECONDS", 300)
    jitter = _positive_int(environ, "NANFO_STREAM_RETENTION_JITTER_SECONDS", max(1, interval // 10))
    # Ten retained streams x 30 s per-stream bound, plus the sleep and scheduling slack.
    return interval + jitter + 900


def _telemetry_progress(line):
    try:
        text = line.decode("utf-8", "replace")
    except AttributeError:
        text = str(line)
    return TELEMETRY_PASS_COMPLETED in text


def _telemetry_max_age(environ):
    interval = float(environ["NANFO_TELEMETRY_RETENTION_INTERVAL_SECONDS"])
    if not 1 <= interval <= 86400:
        raise ValueError("NANFO_TELEMETRY_RETENTION_INTERVAL_SECONDS outside bounds")
    # One sleep plus a bounded pass (900 s sweep deadline + batch timeout) and slack.
    return interval + 1200


LOOPS = {
    "stream-retention": (_stream_progress, _stream_max_age),
    "telemetry-retention": (_telemetry_progress, _telemetry_max_age),
}


def heartbeat_path(loop, environ=os.environ):
    base = environ.get("WORKER_HEARTBEAT_PATH", "")
    path = Path(f"{base}.{loop}")
    if not base or not path.is_absolute() or ".." in path.parts:
        raise ValueError("WORKER_HEARTBEAT_PATH must be an absolute private path")
    return path


def process_start(pid):
    # PID namespaces reuse low PIDs after restart; the start tick binds the record.
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


def write_heartbeat(path, pid, *, clock=time.monotonic):
    record = {"pid": pid, "start": process_start(pid), "progress": clock()}
    fd, temporary = tempfile.mkstemp(prefix=".heartbeat-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as output:
            json.dump(record, output)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def run(loop, command, *, environ=os.environ, stdout=None, popen=subprocess.Popen):
    progress, max_age = LOOPS[loop]
    max_age(environ)  # Fail closed on invalid interval configuration before spawning.
    path = heartbeat_path(loop, environ)
    output = stdout or sys.stdout.buffer
    state = {"child": None, "signal": None}

    def forward(signum, _frame):
        state["signal"] = signum
        if state["child"] is not None and state["child"].poll() is None:
            state["child"].send_signal(signum)

    previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        child = popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        state["child"] = child
        if state["signal"] is not None:
            child.send_signal(state["signal"])
        write_heartbeat(path, child.pid)
        while True:
            line = child.stdout.readline(LINE_LIMIT)
            if not line:
                break
            output.write(line)
            output.flush()
            if progress(line):
                write_heartbeat(path, child.pid)
        child.stdout.close()
        code = child.wait()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 128 - code if code < 0 else code


def check(loop, *, environ=os.environ, clock=time.monotonic):
    """Backend-compatible freshness probe: live pid, same process start, bounded age."""
    status = "unavailable"
    try:
        limit = LOOPS[loop][1](environ)
        with heartbeat_path(loop, environ).open(encoding="ascii") as source:
            record = json.loads(source.read(RECORD_LIMIT))
        pid, progress = record["pid"], record["progress"]
        if type(pid) is int and pid > 1 and type(progress) in (int, float):
            age = clock() - progress
            os.kill(pid, 0)
            if 0 <= age <= limit and record["start"] == process_start(pid):
                status = "ok"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"ready": status == "ok", "checks": {"heartbeat_" + loop: status}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    runner = commands.add_parser("run")
    runner.add_argument("--loop", choices=sorted(LOOPS), required=True)
    runner.add_argument("command", nargs=argparse.REMAINDER)
    probe = commands.add_parser("check")
    probe.add_argument("--loop", choices=sorted(LOOPS), required=True)
    args = parser.parse_args(argv)
    if args.action == "check":
        result = check(args.loop)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["ready"] else 1
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("run requires -- COMMAND")
    try:
        return run(args.loop, command)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "refused", "reason": "supervisor_configuration", "error_type": type(exc).__name__}),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
