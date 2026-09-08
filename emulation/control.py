"""Host-side Docker controls. Never installs or runs Mininet/OVS on the host."""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("build", "start", "stop", "reset", "status", "smoke", "traffic", "verify"),
    )
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    output = directory / "output"
    if output.is_symlink() or not output.is_dir():
        parser.error("emulation/output must exist as a dedicated real directory, not a symlink")
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
        if args.command == "build":
            return execute(["build", "--pull"])
        if args.command == "start":
            return execute(["up", "-d", "--wait", "--wait-timeout", "90"])
        if args.command == "stop":
            return execute(["down", "--timeout", "20"])
        if args.command == "reset":
            execute(["down", "--timeout", "20"])
            return execute(["up", "-d", "--wait", "--wait-timeout", "90", "--force-recreate"])
        if args.command == "verify":
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
            return execute(["run", "--rm", "--no-deps", "lab", "--verify", "--output", "/output"])
        return execute(
            ["exec", "-T", "lab", "python", "-m", "emulation.runner", "--request", args.command]
        )
    except subprocess.CalledProcessError as error:
        return error.returncode


if __name__ == "__main__":
    sys.exit(main())
