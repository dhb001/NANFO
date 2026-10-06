"""Host-side Docker controls. Never installs or runs Mininet/OVS on the host.

ADR-028 C23: the default is the unprivileged successor lab (compose.yaml). The frozen
privileged EOL image is used only with ``NANFO_LAB_FROZEN=1`` and its recorded image ID
(compose.frozen.yaml); it is never built here.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
SUCCESSOR_REPOSITORY = "nanfo-emulation"
# Commands that start a lab container (ownership preflight applies).
LAUNCHES = {"start", "reset", "verify", "verify-actions", "experiment-start"}
# Mirrors .dockerignore: never part of the image source identity.
IGNORED = {"output", "commands", "results", "frozen", ".ruff_cache", "__pycache__", ".git"}


def frozenRequested(environ):
    value = environ.get("NANFO_LAB_FROZEN", "")
    if value not in ("", "0", "1"):
        raise ValueError("NANFO_LAB_FROZEN must be 1 (frozen reproduction) or unset")
    return value == "1"


def composeFiles(directory, environ):
    """Successor by default; frozen privileged compose only with explicit acknowledgement."""
    if frozenRequested(environ):
        if not IMAGE_ID.fullmatch(environ.get("NANFO_EMULATION_IMAGE", "")):
            raise ValueError("Frozen reproduction requires NANFO_EMULATION_IMAGE=sha256:<recorded id>")
        return [directory / "compose.frozen.yaml"]
    files = [directory / "compose.yaml"]
    if environ.get("EMULATION_CONTROL_ENABLED", "false").lower() == "true":
        files.append(directory / "compose.control.yaml")
    return files


def sourceDigest(directory):
    """SHA-256 over every image source file (relative path -> file SHA-256)."""
    files = {}
    for path in sorted(Path(directory).rglob("*")):
        relative = path.relative_to(directory)
        if (
            any(part in IGNORED for part in relative.parts)
            or path.suffix == ".pyc"
            or not path.is_file()
            or path.is_symlink()
        ):
            continue
        files[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def containerProvenance(container, expected_image=None, run=subprocess.run):
    """Actual container/image identity from docker inspect, never the env we passed in."""
    fields = run(
        ["docker", "inspect", "--format", "{{json .Id}} {{json .Image}}", container],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.split()
    if len(fields) != 2:
        raise ValueError("docker inspect returned no container identity")
    identity, image = (json.loads(field) for field in fields)
    if not re.fullmatch(r"[0-9a-f]{64}", identity) or not IMAGE_ID.fullmatch(image):
        raise ValueError("docker inspect returned no immutable container/image identity")
    if expected_image is not None and image != expected_image:
        raise ValueError("Started container image differs from the pinned image")
    return {"container_id": identity, "image_id": image}


def successorPreflight(directory, environ):
    """Without DAC_OVERRIDE the lab must own output/results; commands are read by group."""
    commands = (directory / "commands").lstat()
    gid = environ.get("NANFO_LAB_READER_GID") or str(commands.st_gid)
    if not gid.isdigit():
        raise ValueError("NANFO_LAB_READER_GID must be a numeric group id")
    for name in ("output", "results"):
        info = (directory / name).lstat()
        if info.st_uid != 0 or info.st_gid != int(gid) or stat.S_IMODE(info.st_mode) & 0o027:
            raise ValueError(
                f"emulation/{name} must be root:{gid} 0750 for the unprivileged successor lab "
                f"(sudo chown root:{gid} emulation/{name} && sudo chmod 0750 emulation/{name}); "
                "or reproduce historically with NANFO_LAB_FROZEN=1"
            )
    if commands.st_mode & 0o022 or commands.st_gid != int(gid):
        raise ValueError(f"emulation/commands must belong to the writer group {gid}, mode 0750")
    if commands.st_uid == 0:
        raise ValueError("emulation/commands must be owned by the mailbox writer, not root")
    return gid


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
    environ = dict(os.environ)
    try:
        frozen = frozenRequested(environ)
        files = composeFiles(directory, environ)
        if frozen and args.command == "build":
            parser.error("The frozen image is never rebuilt; use its recorded image ID")
        if not frozen and args.command in LAUNCHES:
            environ["NANFO_LAB_READER_GID"] = successorPreflight(directory, environ)
        elif not frozen:
            environ.setdefault("NANFO_LAB_READER_GID", str((directory / "commands").lstat().st_gid))
    except ValueError as error:
        parser.error(str(error))
    docker = ["docker", "compose", "--project-directory", str(directory)]
    for path in files:
        docker += ["-f", str(path)]

    def execute(arguments):
        return subprocess.run(docker + arguments, check=True, timeout=900, env=environ).returncode

    try:
        if args.command == "build":
            if environ.get("NANFO_EMULATION_IMAGE"):
                parser.error("Build only the working tag; never rebuild a pinned/replay image")
            source = sourceDigest(directory)
            tag = f"{SUCCESSOR_REPOSITORY}:successor-{source[:12]}"
            subprocess.run(
                [
                    "docker",
                    "build",
                    "--pull",
                    "-f",
                    str(directory / "Dockerfile"),
                    "--label",
                    "org.nanfo.lab.source-sha256=" + source,
                    "-t",
                    tag,
                    "-t",
                    SUCCESSOR_REPOSITORY + ":successor",
                    str(directory),
                ],
                check=True,
                timeout=1800,
            )
            image = subprocess.run(
                ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            print(json.dumps({"tag": tag, "image_id": image, "source_sha256": source}))
            return 0
        if args.command == "experiment-start":
            running = subprocess.run(
                [*docker, "ps", "-q", "--status", "running"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
                env=environ,
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
                    environ.get("NANFO_EMULATION_IMAGE", SUCCESSOR_REPOSITORY + ":successor"),
                    "--format",
                    "{{.Id}}",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            # FRR's ospfd narrows itself to a capability set that includes NET_BIND_SERVICE.
            frr = [] if frozen or args.mode == "sdn" else ["--cap-add", "NET_BIND_SERVICE"]
            execute(
                [
                    "run",
                    "--rm",
                    "-d",
                    "--no-deps",
                    "--name",
                    "nanfo-experiment",
                    *frr,
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
            try:
                provenance = containerProvenance("nanfo-experiment", image)
            except ValueError as error:
                subprocess.run(
                    ["docker", "stop", "--time", "20", "nanfo-experiment"], check=False, timeout=30
                )
                parser.error(str(error))
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
                    print(json.dumps({"provenance": provenance}))
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
        if args.command == "start":
            execute(["up", "-d", "--wait", "--wait-timeout", "90"])
            container = subprocess.run(
                [*docker, "ps", "-q", "lab"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
                env=environ,
            ).stdout.strip()
            pinned = environ.get("NANFO_EMULATION_IMAGE", "")
            try:
                provenance = containerProvenance(
                    container, pinned if IMAGE_ID.fullmatch(pinned) else None
                )
            except ValueError as error:
                execute(["down", "--timeout", "20"])
                parser.error(str(error))
            print(json.dumps({"provenance": provenance}))
            return 0
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
                env=environ,
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
