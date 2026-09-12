"""Explicit single24h transient user service, never unattended unlimited execution."""

import subprocess

from contract import UNIT
from history import ROOT


def command():
    python = str(ROOT / ".venv/bin/python")
    runner = str(ROOT / "scripts/refinement_long/runner.py")
    return [
        "systemd-run",
        "--user",
        f"--unit={UNIT}",
        "--collect",
        "--property=RuntimeMaxSec=86400",
        "--property=TimeoutStopSec=180",
        "--property=Restart=no",
        "--property=KillMode=control-group",
        "--property=CPUQuota=200%",
        "--property=MemoryMax=2G",
        "--property=TasksMax=128",
        f"--property=WorkingDirectory={ROOT}",
        f"--property=ExecStopPost={python} {runner} cleanup",
        "--setenv=PYTHONDONTWRITEBYTECODE=1",
        "--setenv=PYTHONUNBUFFERED=1",
        "--setenv=OMP_NUM_THREADS=1",
        "--setenv=MKL_NUM_THREADS=1",
        python,
        runner,
        "run",
        "--parent-approved",
    ]


if __name__ == "__main__":
    subprocess.run(
        [
            str(ROOT / ".venv/bin/python"),
            str(ROOT / "scripts/refinement_long/runner.py"),
            "preflight",
        ],
        check=True,
        timeout=240,
    )
    subprocess.run(command(), check=True, timeout=30)
