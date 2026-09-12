"""Launch one finite systemd user service, with exact-owner ExecStopPost cleanup."""

import subprocess
import sys
import time

from frozen import ROOT


def argv(release):
    python = str(ROOT / ".venv/bin/python")
    runner = str(ROOT / "scripts/refinement/campaign.py")
    from campaign import FAILED_ATTEMPT, read

    seconds = max(1, int(read(FAILED_ATTEMPT / "plan.json")["started_unix"] + 14400 - time.time()))
    return [
        "systemd-run",
        "--user",
        "--unit=nanfo-adr015-refinement",
        "--collect",
        f"--property=RuntimeMaxSec={seconds}",
        "--property=TimeoutStopSec=120",
        "--property=KillMode=control-group",
        "--property=Restart=no",
        "--property=MemoryMax=2G",
        "--property=TasksMax=128",
        f"--property=WorkingDirectory={ROOT}",
        f"--property=ExecStopPost={python} {runner} cleanup",
        "--setenv=PYTHONUNBUFFERED=1",
        "--setenv=PYTHONDONTWRITEBYTECODE=1",
        "--setenv=OMP_NUM_THREADS=1",
        "--setenv=MKL_NUM_THREADS=1",
        python,
        runner,
        "run",
        "--parent-approved",
        "--release",
        str(release),
    ]


if __name__ == "__main__":
    release = sys.argv[1] if len(sys.argv) == 2 else str(ROOT / "artifacts/adr015-release.json")
    subprocess.run(
        [
            str(ROOT / ".venv/bin/python"),
            str(ROOT / "scripts/refinement/campaign.py"),
            "preflight",
            "--release",
            release,
        ],
        check=True,
        timeout=90,
    )
    subprocess.run(argv(release), check=True, timeout=30)
