"""Host-side Docker controls. Never installs or runs Mininet/OVS on the host."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "build",
            "start",
            "stop",
            "reset",
            "status",
            "smoke",
            "traffic",
            "paths",
            "verify",
            "verify-actions",
            "experiment-start",
            "experiment-stop",
        ),
    )
    parser.add_argument("--mode", choices=("sdn", "matched", "ospf"), default="sdn")
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    output = directory / "output"
    if output.is_symlink() or not output.is_dir():
        parser.error("emulation/output must exist as a dedicated real directory, not a symlink")
    for name in ("commands", "results"):
        path = directory / name
        if path.is_symlink() or not path.is_dir():
            parser.error(f"emulation/{name} must be a dedicated real directory")
    docker = [
        "docker",
        "compose",
        "--project-directory",
        str(directory),
        "-f",
        str(directory / "compose.yaml"),
    ]

    def execute(arguments):
        return subprocess.run(docker + arguments, check=True, timeout=900).returncode

    try:
        if args.command == "experiment-start":
            running = subprocess.run(
                [*docker, "ps", "-q", "--status", "running"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            if running:
                parser.error("Another lab owns the slot; stop it explicitly first")
            if (directory / "results" / ".journal.json").exists() or (
                directory / "results" / ".journal.json"
            ).is_symlink():
                parser.error(
                    "Manual journal exists; reconcile it through manual control, never delete it"
                )
            image = subprocess.run(
                [
                    "docker",
                    "image",
                    "inspect",
                    os.environ.get("NANFO_EMULATION_IMAGE", "nanfo-emulation:campus-small-v1"),
                    "--format",
                    "{{.Id}}",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            execute(
                [
                    "run",
                    "--rm",
                    "-d",
                    "--no-deps",
                    "--name",
                    "nanfo-experiment",
                    "-e",
                    "EMULATION_CONTROL_ENABLED=false",
                    "-e",
                    "NANFO_LAB_IMAGE_ID=" + image,
                    "lab",
                    "--experiment",
                    "--mode",
                    args.mode,
                    "--output",
                    "/output",
                ]
            )
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                ready = subprocess.run(
                    [
                        "docker",
                        "exec",
                        "nanfo-experiment",
                        "python",
                        "-c",
                        "from pathlib import Path; import sys; sys.exit(not Path('/run/nanfo/experiment.sock').is_socket())",
                    ],
                    capture_output=True,
                    timeout=5,
                )
                if ready.returncode == 0:
                    return 0
                time.sleep(0.5)
            subprocess.run(
                ["docker", "stop", "--time", "20", "nanfo-experiment"], check=False, timeout=30
            )
            parser.error(
                "Experiment failed readiness within 90 seconds; inspect container diagnostics"
            )
        if args.command == "experiment-stop":
            return subprocess.run(
                ["docker", "stop", "--time", "20", "nanfo-experiment"], check=True, timeout=30
            ).returncode
        if args.command == "build":
            if os.environ.get("NANFO_EMULATION_IMAGE"):
                parser.error("Build only the working tag; never rebuild a pinned/replay image")
            return execute(["build", "--pull"])
        if args.command == "start":
            return execute(["up", "-d", "--wait", "--wait-timeout", "90"])
        if args.command == "stop":
            return execute(["down", "--timeout", "20"])
        if args.command == "reset":
            execute(["down", "--timeout", "20"])
            return execute(["up", "-d", "--wait", "--wait-timeout", "90", "--force-recreate"])
        if args.command in ("verify", "verify-actions"):
            running = subprocess.run(
                [*docker, "ps", "-q", "--status", "running"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            if running:
                parser.error(
                    "Stop the active lab before one-shot verify (one output producer only)"
                )
            return execute(
                [
                    "run",
                    "--rm",
                    "--no-deps",
                    "-e",
                    "EMULATION_CONTROL_ENABLED=false",
                    "lab",
                    "--" + args.command,
                    "--output",
                    "/output",
                ]
            )
        return execute(
            ["exec", "-T", "lab", "python", "-m", "emulation.runner", "--request", args.command]
        )
    except subprocess.CalledProcessError as error:
        return error.returncode
    except subprocess.TimeoutExpired:
        print("Docker command timed out; inspect and stop only the owned lab", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
