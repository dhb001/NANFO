"""Explicit, project-scoped deployment lifecycle. Never upgrades existing stores."""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

try:
    from deploy.schema_contract import CURRENT_SCHEMA
except ModuleNotFoundError:
    from schema_contract import CURRENT_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
SERVICES = [
    "api",
    "network-outbox-worker",
    "simulation-worker",
    "report-worker",
    "alert-worker",
    "execution-worker",
    "autonomy-worker",
    "gateway",
]
STORES = ["postgres", "redis", "neo4j"]
VOLUMES = [
    "postgres_data",
    "redis_data",
    "neo4j_data",
    "reports",
    "network_assets",
    "telemetry_archive",
    "lab_output",
    "lab_commands",
    "lab_results",
    "runtime_secrets",
    "init_secrets",
]
SECRET_NAMES = [
    "postgres_admin_password",
    "postgres_owner_password",
    "postgres_runtime_password",
    "redis_password",
    "neo4j_password",
    "jwt_secret",
    "bootstrap_password",
]


def run(command, *, capture=False):
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def compose(state, *args, capture=False):
    # No shell .env sourcing, ambient Compose project or development .env discovery.
    config = load_config(state)
    return run(
        [
            "docker",
            "compose",
            "--project-name",
            config["NANFO_PROJECT"],
            "--env-file",
            str(state / "deployment.env"),
            "-f",
            str(ROOT / "deploy/compose.yaml"),
            *args,
        ],
        capture=capture,
    )


def load_config(state):
    if state.resolve() != state or state.stat().st_mode & 0o077:
        raise ValueError("State must be a canonical private directory")
    path = state / "deployment.env"
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Unprotected deployment config")
    config = dict(line.split("=", 1) for line in path.read_text().splitlines() if line)
    for name in SECRET_NAMES:
        info = (state / "secrets" / name).lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
        ):
            raise ValueError("Source credentials must remain private regular files")
    if not re.fullmatch(
        r"nanfo-deploy-[a-z0-9][a-z0-9-]{0,40}", config["NANFO_PROJECT"]
    ):
        raise ValueError("Deployment project must use the nanfo-deploy- prefix")
    if (
        config["NANFO_STATE_DIR"] != str(state)
        or not 1024 <= int(config["NANFO_HTTP_PORT"]) <= 65535
    ):
        raise ValueError("Invalid state directory or loopback port")
    # Compose's environment precedence must not redirect this project's volumes.
    for key, value in config.items():
        if key in os.environ and os.environ[key] != value:
            raise ValueError(f"Conflicting ambient variable: {key}")
    return config


def generate(state, project, port, email):
    if not re.fullmatch(r"nanfo-deploy-[a-z0-9][a-z0-9-]{0,40}", project):
        raise ValueError("Use a unique nanfo-deploy-* project")
    if not re.fullmatch(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", email):
        raise ValueError("An explicit operator email is required")
    if not 1024 <= port <= 65535 or not re.fullmatch(r"/[a-zA-Z0-9_./-]+", str(state)):
        raise ValueError("Invalid port or state path")
    if state.resolve() != state or state.exists() or state.is_symlink():
        raise ValueError("Refusing to overwrite an existing state directory")
    for kind in ("container", "volume", "network"):
        command = [
            "docker",
            kind,
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ]
        if kind == "container":
            command.insert(3, "-a")
        if run(command, capture=True).stdout.strip():
            raise ValueError(
                "Project already owns Docker resources; choose a fresh project"
            )
    for volume in VOLUMES:
        existing = subprocess.run(
            ["docker", "volume", "inspect", f"{project}_{volume}"],
            capture_output=True,
            check=False,
        )
        if existing.returncode == 0:
            raise ValueError("Target volume already exists")
    state.mkdir(mode=0o700)
    for name in ("secrets", "binding", "models", "model-registry"):
        (state / name).mkdir(mode=0o700)
    # Bind roots need traversal for the fixed application UID, never group writes.
    for name in ("binding", "models", "model-registry"):
        (state / name).chmod(0o755)
    for name in SECRET_NAMES:
        fd = os.open(
            state / "secrets" / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(fd, "w") as output:
            output.write(secrets.token_hex(32) + "\n")
    config = {
        "NANFO_PROJECT": project,
        "NANFO_STATE_DIR": str(state),
        "NANFO_HTTP_PORT": str(port),
        "NANFO_BOOTSTRAP_EMAIL": email,
        "NANFO_BACKEND_IMAGE": f"{project}-backend:adr020",
        "NANFO_FRONTEND_IMAGE": f"{project}-frontend:adr020",
        "NANFO_NEO4J_IMAGE": f"{project}-neo4j:5.26.12",
        "EXECUTION_MODE": "demo",
        "EMULATION_CONTROL_ENABLED": "false",
        "TELEMETRY_RUNTIME_ADAPTER_MODE": "stub",
        "API_REALTIME_DISTRIBUTED": "false",
    }
    with (state / "deployment.env").open("x") as output:
        output.write("".join(f"{key}={value}\n" for key, value in config.items()))
    (state / "deployment.env").chmod(0o600)
    return config


def build_images(state, *, service=None, with_ai=False, with_fleet=False, image_tag=None):
    """Use an allowlisted tar context, including on Docker's legacy clean builder."""
    config = load_config(state)
    if with_fleet and (with_ai or service != "backend"):
        raise ValueError("Fleet build requires only --service backend --with-fleet")
    config["NANFO_LAB_BUILD_IMAGE"] = "nanfo-emulation:operator-paths-adr020"
    if image_tag:
        repository = config["NANFO_BACKEND_IMAGE"].rsplit(":", 1)[0]
        if (
            service != "backend"
            or with_ai
            or not re.fullmatch(
                re.escape(repository) + r":[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}", image_tag
            )
            or image_tag == config["NANFO_BACKEND_IMAGE"]
        ):
            raise ValueError(
                "Explicit core build requires a distinct tag in the configured backend repository"
            )
        if (
            subprocess.run(
                ["docker", "image", "inspect", image_tag],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        ):
            raise ValueError("Refusing to overwrite an existing release tag")
    docker_root = run(
        ["docker", "info", "--format", "{{.DockerRootDir}}"], capture=True
    ).stdout.strip()
    if (
        Path(docker_root).exists()
        and shutil.disk_usage(docker_root).free < (6 if with_ai else 3) * 1024**3
    ):
        raise ValueError(
            "Docker storage lacks build headroom; free space explicitly, never prune shared data"
        )
    jobs = [
        ("backend", "NANFO_BACKEND_IMAGE", "with-ai" if with_ai else "with-fleet" if with_fleet else "runtime"),
        ("frontend", "NANFO_FRONTEND_IMAGE", None),
        ("neo4j", "NANFO_NEO4J_IMAGE", None),
    ]
    if service == "lab":
        jobs = [("lab", "NANFO_LAB_BUILD_IMAGE", None)]
    for kind, image_key, target in jobs:
        if service and service != kind:
            continue
        with tempfile.TemporaryDirectory(prefix="nanfo-deploy-build-") as directory:
            source_hashes = {}
            archive = Path(directory) / "context.tar"
            with tarfile.open(archive, "w") as context:
                for path in sorted(ROOT.rglob("*")):
                    relative = path.relative_to(ROOT)
                    parts = relative.parts
                    if path.is_symlink() or not path.is_file():
                        continue
                    if parts[0] == "deploy" and (
                        path.name.startswith("test_") or path.name == "verify.py"
                    ):
                        continue
                    if any(
                        part.startswith(".")
                        or part
                        in {
                            "node_modules",
                            "dist",
                            "artifacts",
                            "venv",
                            "test-results",
                            "playwright-report",
                            "__pycache__",
                        }
                        for part in parts
                    ) or parts[:2] == ("deploy", "state"):
                        continue
                    name = relative.as_posix()
                    allowed = name == f"deploy/Dockerfile.{kind}"
                    if kind == "backend":
                        allowed |= name in {
                            "backend/README.md",
                            "backend/pyproject.toml",
                            "backend/poetry.lock",
                            "backend/alembic/alembic.ini",
                            "ai-engine/pyproject.toml",
                            "ai-engine/uv.lock",
                            "deploy/fleet.sources",
                        }
                        allowed |= path.suffix == ".py" and (
                            name.startswith(
                                ("backend/app/", "backend/alembic/", "ai-engine/src/")
                            )
                            or len(parts) == 3
                            and parts[:2] == ("backend", "scripts")
                            or len(parts) == 2
                            and parts[0] in {"emulation", "deploy"}
                        )
                    elif kind == "frontend":
                        allowed |= parts[0] == "frontend" and (
                            path.suffix
                            in {
                                ".json",
                                ".ts",
                                ".tsx",
                                ".js",
                                ".css",
                                ".html",
                                ".svg",
                                ".png",
                                ".ico",
                                ".woff2",
                            }
                            or path.name == "package-lock.json"
                        )
                        allowed |= name in {
                            "deploy/nginx.conf", "deploy/nginx-upstream.conf"
                        }
                    else:
                        allowed |= name == "deploy/neo4j-entrypoint.sh"
                    if kind == "lab":
                        allowed = parts[0] == "emulation" and (
                            path.suffix == ".py"
                            or name
                            in {
                                "emulation/Dockerfile",
                                "emulation/apt-sources.list",
                                "emulation/requirements.txt",
                                "emulation/compose.yaml",
                            }
                        )
                    if allowed:
                        context.add(path, arcname=name, recursive=False)
                        source_hashes[name] = hashlib.sha256(
                            path.read_bytes()
                        ).hexdigest()
            tag = image_tag or config[image_key] + (
                "-ai" if kind == "backend" and with_ai else "-fleet" if kind == "backend" and with_fleet else ""
            )
            command = [
                "docker",
                "build",
                "--pull",
                "-f",
                "Dockerfile" if kind == "lab" else f"deploy/Dockerfile.{kind}",
                "-t",
                tag,
            ]
            if target:
                command += ["--target", target]
            staged = Path(directory) / "context"
            staged.mkdir()
            with tarfile.open(archive) as context:
                context.extractall(staged, filter="data")
            for path in staged.rglob("*"):
                if path.is_dir():
                    path.chmod(0o755)
            if kind == "lab":
                command[command.index("-f") + 1] = str(staged / "emulation/Dockerfile")
            subprocess.run(
                [*command, str(staged / "emulation" if kind == "lab" else staged)],
                check=True,
            )
            if source_hashes:
                image_id = run(
                    ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
                    capture=True,
                ).stdout.strip()
                runtime_hashes = {}
                for name, digest in source_hashes.items():
                    if (
                        name.startswith(
                            (
                                "backend/app/",
                                "backend/scripts/",
                                "backend/alembic/",
                                "emulation/",
                            )
                        )
                        or name.startswith("deploy/")
                        and name.endswith(".py")
                    ):
                        runtime_hashes["/opt/nanfo/" + name] = digest
                    if (
                        kind == "backend"
                        and with_ai
                        and name.startswith("ai-engine/src/")
                    ):
                        runtime_hashes["/opt/nanfo/" + name] = digest
                if kind not in {"backend", "lab"}:
                    runtime_hashes = {}
                probe = "import hashlib,json,sys; from pathlib import Path; expected=json.load(sys.stdin); bad=[p for p,h in expected.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]; print(json.dumps({'source_parity':not bad,'files':len(expected)})); sys.exit(bool(bad))"
                if runtime_hashes:
                    subprocess.run(
                        [
                            "docker",
                            "run",
                            "--rm",
                            "-i",
                            "--network",
                            "none",
                            "--read-only",
                            "--cap-drop",
                            "ALL",
                            "--security-opt",
                            "no-new-privileges:true",
                            "--entrypoint",
                            "python",
                            image_id,
                            "-c",
                            probe,
                        ],
                        input=json.dumps(runtime_hashes),
                        text=True,
                        check=True,
                    )
                if any(
                    hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest
                    for name, digest in source_hashes.items()
                ):
                    raise ValueError(
                        "Sources changed during build; release parity not established"
                    )
                record = {
                    "image": tag,
                    "image_id": image_id,
                    "target": target,
                    "source_sha256": source_hashes,
                    "runtime_parity_files": len(runtime_hashes),
                    "host_site_packages_used": False,
                    "initialized_stack_modified": False,
                }
                record_path = state / (
                    "build-" + kind + "-" + tag.rsplit(":", 1)[1] + ".json"
                )
                with record_path.open("x") as output:
                    json.dump(record, output, sort_keys=True, indent=2)
                print(f"Verified build record: {record_path}")


def adopt_restored(state, directory, key_file):
    """Authenticate source proof and reverify a stopped restored target, never migrate."""
    try:
        from deploy.backup_restore import Deployment, load_manifest, protected_file, require_current_archive_checkpoint
    except ModuleNotFoundError:
        from backup_restore import Deployment, load_manifest, protected_file, require_current_archive_checkpoint

    config = load_config(state)
    with protected_file(key_file, size=32) as source:
        key = source.read()
    manifest = load_manifest(directory, key)
    if manifest["project"] == config["NANFO_PROJECT"]:
        raise ValueError("Restore source and target must differ")
    if (state / "initialized.json").exists() or (state / "initializing").exists():
        raise ValueError(
            "Restore adoption requires a target without initialization markers"
        )
    if config.get("EMULATION_CONTROL_ENABLED", "false").lower() != "false":
        raise ValueError("Restored control must remain disabled")
    deployment = Deployment(
        config["NANFO_PROJECT"],
        [ROOT / "deploy/compose.yaml"],
        state / "deployment.env",
    )
    deployment.assert_stopped(stores_allowed=True)
    if deployment.run(
        "docker",
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.compose.project={manifest['project']}",
    ).strip():
        raise ValueError("Source owners must remain stopped")
    if (
        deployment.images() != manifest["images"]
        or deployment.mount_contract() != manifest["mount_contract"]
        or deployment.external_fingerprints(key) != manifest["external_fingerprints"]
    ):
        raise ValueError("Restored image, mount or secret proof differs")
    volumes, _ = deployment.inventory(key)
    if set(volumes) != {item["logical"] for item in manifest["volumes"]}:
        raise ValueError("Restored volume inventory differs")
    checkpoint = deployment.maintenance("checkpoint")
    expected = manifest["checkpoint"]
    # Archive authentication remains version-neutral in backup_restore.py. This
    # current composition must not resume historical images/schema as a new release.
    if expected.get("schema") != CURRENT_SCHEMA:
        raise ValueError(
            f"Current release adoption requires schema {CURRENT_SCHEMA}; use matching historical tooling"
        )
    require_current_archive_checkpoint(expected, volumes)
    require_current_archive_checkpoint(checkpoint, volumes)
    if any(
        checkpoint.get(name) != expected.get(name)
        for name in (
            "schema", "reports", "model_references", "network_assets",
            "telemetry_archive", "autonomous_execution", "experimental_lab",
        )
    ):
        raise ValueError("Restored checkpoint differs; keep writers stopped")
    verified = deployment.maintenance("restore-verify")
    if not verified.get("safe") or verified.get("schema") != CURRENT_SCHEMA:
        raise ValueError("Restore verification failed")
    images = {
        key: run(
            ["docker", "image", "inspect", config[key], "--format", "{{.Id}}"],
            capture=True,
        ).stdout.strip()
        for key in ("NANFO_BACKEND_IMAGE", "NANFO_FRONTEND_IMAGE", "NANFO_NEO4J_IMAGE")
    }
    with (state / "initialized.json").open("x") as output:
        json.dump(
            {
                "project": config["NANFO_PROJECT"],
                "images": images,
                "restored_from": manifest["project"],
                "schema": CURRENT_SCHEMA,
            },
            output,
        )
        output.flush()
        os.fsync(output.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--project", required=True)
    init.add_argument("--port", type=int, default=8787)
    init.add_argument("--email", required=True)
    init.add_argument("--build", action="store_true")
    build = commands.add_parser("build")
    build.add_argument("--service", choices=["backend", "frontend", "neo4j", "lab"])
    build.add_argument("--with-ai", action="store_true")
    build.add_argument("--with-fleet", action="store_true")
    build.add_argument(
        "--image-tag",
        help="New backend release tag; never changes the initialized stack",
    )
    start = commands.add_parser("start")
    start.add_argument("--restored", type=Path, metavar="BACKUP_DIRECTORY")
    start.add_argument("--encryption-key-file", type=Path)
    commands.add_parser("stop")
    commands.add_parser("status")
    commands.add_parser("config")
    args = parser.parse_args()
    state = args.state.absolute()
    os.umask(0o077)
    if args.command == "init":
        generate(state, args.project, args.port, args.email)
        compose(state, "config", "--quiet")
        if args.build:
            build_images(state)
        print("Private configuration generated. Run start only after images are built.")
    elif args.command == "build":
        if (
            (state / "initialized.json").exists()
            and not ((args.with_ai or args.with_fleet) and args.service == "backend")
            and not args.image_tag
        ):
            raise ValueError(
                "Do not rebuild initialized deployment tags; use an explicit release procedure"
            )
        build_images(
            state, service=args.service, with_ai=args.with_ai,
            with_fleet=args.with_fleet, image_tag=args.image_tag
        )
    elif args.command == "start":
        config = load_config(state)
        marker = state / "initialized.json"
        if bool(args.restored) != bool(args.encryption_key_file):
            raise ValueError(
                "Restored start requires both authenticated backup and key"
            )
        if args.restored:
            adopt_restored(state, args.restored, args.encryption_key_file)
        if not marker.exists():
            # A failed first initialization is intentionally not retried automatically.
            with (state / "initializing").open("x") as output:
                output.write(config["NANFO_PROJECT"])
            compose(state, "run", "--rm", "--no-deps", "volume-init")
            compose(
                state,
                "up",
                "-d",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "180",
                *STORES,
            )
            compose(state, "run", "--rm", "initialize")
            # A stale image must not receive a current-schema marker just because
            # its own initializer exited successfully. Inspect its live checkpoint.
            checkpoint = json.loads(compose(
                state, "run", "--rm", "--no-deps", "maintenance", "python",
                "/opt/nanfo/deploy/maintenance.py", "checkpoint", capture=True,
            ).stdout)
            if checkpoint.get("schema") != CURRENT_SCHEMA or checkpoint.get("safe") is not True:
                raise ValueError("Fresh initialization schema/checkpoint differs from current source")
            images = {
                key: run(
                    ["docker", "image", "inspect", config[key], "--format", "{{.Id}}"],
                    capture=True,
                ).stdout.strip()
                for key in (
                    "NANFO_BACKEND_IMAGE",
                    "NANFO_FRONTEND_IMAGE",
                    "NANFO_NEO4J_IMAGE",
                )
            }
            marker.write_text(
                json.dumps(
                    {
                        "project": config["NANFO_PROJECT"],
                        "images": images,
                        "schema": CURRENT_SCHEMA,
                    },
                    indent=2,
                )
                + "\n"
            )
        else:
            recorded = json.loads(marker.read_text())
            if recorded["project"] != config["NANFO_PROJECT"]:
                raise ValueError("Initialized project identity changed")
            if recorded.get("schema") != CURRENT_SCHEMA:
                raise ValueError(
                    f"Current release start requires schema {CURRENT_SCHEMA}; implicit upgrade forbidden"
                )
            for logical in VOLUMES:
                volume = json.loads(
                    run(
                        [
                            "docker",
                            "volume",
                            "inspect",
                            f"{config['NANFO_PROJECT']}_{logical}",
                        ],
                        capture=True,
                    ).stdout
                )[0]
                if (
                    volume.get("Labels", {}).get("com.docker.compose.project")
                    != config["NANFO_PROJECT"]
                ):
                    raise ValueError(
                        "Missing or foreign initialized volume; restore explicitly"
                    )
            for key, image_id in recorded["images"].items():
                current = run(
                    ["docker", "image", "inspect", config[key], "--format", "{{.Id}}"],
                    capture=True,
                ).stdout.strip()
                if current != image_id:
                    raise ValueError(
                        "Image changed: implicit deployment upgrade forbidden"
                    )
        compose(
            state,
            "up",
            "-d",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "180",
            *SERVICES,
        )
    elif args.command == "stop":
        compose(state, "stop", "gateway", "api")
        checkpoint = compose(
            state,
            "run",
            "--rm",
            "--no-deps",
            "maintenance",
            "python",
            "/opt/nanfo/deploy/maintenance.py",
            "checkpoint",
            capture=True,
        )
        if not json.loads(checkpoint.stdout).get("safe"):
            raise ValueError(
                "Unresolved physical recovery; workers/stores left running"
            )
        # Does not stop/restart a privileged lab or discard any durable volumes.
        compose(state, "stop", *SERVICES)
        compose(state, "stop", *STORES)
    elif args.command == "status":
        compose(state, "ps", "--all")
    else:
        compose(state, "config", "--quiet")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(
            f"Deployment operation refused ({type(error).__name__}); no automatic cleanup or retry",
            file=sys.stderr,
        )
        sys.exit(1)
