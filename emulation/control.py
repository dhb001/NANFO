"""Host-side Docker controls. Never installs or runs Mininet/OVS on the host."""

import argparse
import subprocess
import sys
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
            "verify",
            "verify-actions",
            "experiment-start",
            "experiment-stop",
        ),
    )
    parser.add_argument("--mode", choices=("sdn", "ospf"), default="sdn")
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
        return subprocess.run(docker + arguments, check=True).returncode

    try:
        if args.command == "experiment-start":
            running = subprocess.run(
                [*docker, "ps", "-q", "--status", "running"], check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            if running:
                parser.error("Another lab owns the slot; stop it explicitly first")
            if (directory / "results" / ".journal.json").exists() or (directory / "results" / ".journal.json").is_symlink():
                parser.error("Manual journal exists; reconcile it through manual control, never delete it")
            return execute(["run", "--rm", "-d", "--no-deps", "--name", "nanfo-experiment",
                            "-e", "EMULATION_CONTROL_ENABLED=false", "lab",
                            "--experiment", "--mode", args.mode, "--output", "/output"])
        if args.command == "experiment-stop":
            return subprocess.run(["docker", "stop", "--time", "20", "nanfo-experiment"], check=True).returncode
        if args.command == "build":
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


if __name__ == "__main__":
    sys.exit(main())
