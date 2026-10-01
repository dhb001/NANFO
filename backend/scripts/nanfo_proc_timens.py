#!/usr/bin/python3 -I
"""Root helper for the passive observer (ADR-028): one PID on stdin, fixed reads only.

Install root-owned and unwritable by anyone else, then add the EXACT sudoers entry
(no wildcards; ``""`` forbids every command-line argument, the PID arrives on stdin):

    install -o root -g root -m 0755 backend/scripts/nanfo_proc_timens.py \
        /usr/local/libexec/nanfo-proc-timens
    visudo -f /etc/sudoers.d/nanfo-passive-observer
        nanfo-operator ALL=(root) NOPASSWD: /usr/local/libexec/nanfo-proc-timens ""

It prints ``{"pid", "time_namespace", "timens_offsets"}`` for that PID and nothing else:
no shell, no caller-supplied path, no signals, no writes. Stdlib only, isolated mode.
"""

import json
import os
import re
import sys

MAX_PID = 4194304


def read_pid(stream):
    raw = stream.read(24)
    if not re.fullmatch(r"[1-9][0-9]{0,6}\n?", raw) or int(raw) > MAX_PID:
        raise ValueError("pid")
    return int(raw)


def proc_timens(pid, proc="/proc"):
    namespace = os.readlink(f"{proc}/{pid}/ns/time")
    if not re.fullmatch(r"time:\[[0-9]+\]", namespace):
        raise ValueError("namespace")
    with open(f"{proc}/{pid}/timens_offsets", encoding="ascii") as stream:
        content = stream.read(4097)
    if len(content) > 4096:
        raise ValueError("offsets")
    offsets = {}
    for line in content.splitlines():
        name, seconds, nanos = line.split()
        if name not in ("monotonic", "boottime") or name in offsets:
            raise ValueError("offsets")
        offsets[name] = [int(seconds), int(nanos)]
    return {"pid": pid, "time_namespace": namespace, "timens_offsets": offsets}


def main(argv=None, stdin=None, stdout=None):
    argv = sys.argv[1:] if argv is None else argv
    stdout = sys.stdout if stdout is None else stdout
    if argv:
        stdout.write('{"error":"arguments_forbidden"}\n')
        return 2
    try:
        value = proc_timens(read_pid(sys.stdin if stdin is None else stdin))
    except (OSError, ValueError):
        stdout.write('{"error":"unavailable"}\n')
        return 1
    stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
