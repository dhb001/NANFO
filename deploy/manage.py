"""Explicit, project-scoped deployment lifecycle. Never upgrades existing stores.

State defaults: an existing in-repository ``deploy/state`` deployment keeps being used
(with a warning); fresh installs default to ``${XDG_STATE_HOME:-~/.local/state}/nanfo``.
Existing state is never moved. Commands: init, build, start, stop, status, config,
rotate (store/JWT credentials), autoheal (restart persistently unhealthy services)
and lab (opt-in lab; the frozen privileged image requires NANFO_LAB_FROZEN=1).
"""

import argparse
import hashlib
import ipaddress
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
import time
from pathlib import Path

try:
    from deploy.schema_contract import CURRENT_SCHEMA, require_consistent_schema
except ModuleNotFoundError:
    from schema_contract import CURRENT_SCHEMA, require_consistent_schema

ROOT = Path(__file__).resolve().parents[1]
LEGACY_STATE = ROOT / "deploy" / "state"
SERVICES = [
    "api",
    "network-outbox-worker",
    "simulation-worker",
    "report-worker",
    "alert-worker",
    "execution-worker",
    "autonomy-worker",
    "stream-retention",
    "telemetry-retention",
    "asset-gc",
    "gateway",
]
# Services that load staged credentials at start (restarted after a rotation).
APPLICATION = [name for name in SERVICES if name != "gateway"]
# Never auto-restarted: datastores (crash recovery belongs to operators) and the lab.
AUTOHEAL_SERVICES = frozenset({*SERVICES, "api2", "fleet-worker"})
STORES = ["postgres", "redis", "neo4j"]
VOLUMES = [
    "postgres_data",
    "redis_data",
    "neo4j_data",
    "reports",
    "network_assets",
    "telemetry_archive",
    "stream_archive",
    "lab_output",
    "lab_commands",
    "lab_results",
    "runtime_secrets_api",
    "runtime_secrets_worker",
    "execution_secrets",
    "lab_secrets",
    "init_secrets",
]
PASSWORD_SECRETS = [
    "postgres_admin_password",
    "postgres_owner_password",
    "postgres_runtime_password",
    "redis_password",
    "redis_admin_password",
    "neo4j_password",
    "jwt_secret",
    "bootstrap_password",
]
LAB_COMMAND_KEY = "lab_command_key"
RECEIVER_PRIVATE_KEY = "receiver_health_private_key.pem"
RECEIVER_PUBLIC_KEY = "receiver_health_public_key.pem"
# C21: the signing key lives outside secrets/ (which volume-init mounts); no service
# mounts this directory. Install the file only at the receiver, then it may be removed.
RECEIVER_DIRECTORY = "receiver"
SECRET_NAMES = [*PASSWORD_SECRETS, LAB_COMMAND_KEY, RECEIVER_PUBLIC_KEY]
# The operator may remove the bootstrap password after first login/initialization.
POST_INIT_OPTIONAL = frozenset({"bootstrap_password"})
JWT_PREVIOUS = "jwt_previous_secrets"
IMAGE_KEYS = ("NANFO_BACKEND_IMAGE", "NANFO_FRONTEND_IMAGE", "NANFO_NEO4J_IMAGE", "NANFO_REDIS_IMAGE")
REQUIRED_CONFIG = (
    "NANFO_PROJECT", "NANFO_STATE_DIR", "NANFO_HTTP_PORT", *IMAGE_KEYS,
    "NANFO_PROXY_SUBNET", "NANFO_PROXY_GATEWAY_IP", "NANFO_GATEWAY_SUBNET", "NANFO_GATEWAY_BRIDGE_IP",
)
NEO4J_TAG = "5.26.31"
REDIS_TAG = "7.4.11"
# rotate --secret NAME: (state secret file, store owning the credential)
ROTATIONS = {
    "postgres_app": ("postgres_runtime_password", "postgres"),
    "postgres_owner": ("postgres_owner_password", "postgres"),
    "neo4j": ("neo4j_password", "neo4j"),
    "redis": ("redis_password", "redis"),
    "jwt_secret": ("jwt_secret", None),
}
ROTATION_RESTARTS = {
    "postgres_app": APPLICATION,
    "postgres_owner": [],
    "neo4j": APPLICATION,
    "redis": APPLICATION,
    "jwt_secret": ["api"],
}
# One access-token lifetime (JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15) plus 30 s decode leeway.
DEFAULT_JWT_OVERLAP_SECONDS = 15 * 60 + 30
MAX_JWT_OVERLAP_SECONDS = 12 * 3600
FROZEN_LAB_WARNING = (
    "WARNING: compose.lab.frozen.yaml runs the frozen, privileged, end-of-life lab image "
    "(Debian 11 / Python 3.9). Use it only to reproduce historical results; the default "
    "lab is the least-privilege successor (compose.lab.yaml, ADR-028 C23)."
)
# Labs run only operator-verified immutable identities: a local sha256 image ID or a
# registry digest reference, never a mutable tag (C23; see deploy/README.md).
LAB_IMAGE_PIN = re.compile(r"sha256:[0-9a-f]{64}|[a-z0-9][a-z0-9._/:-]{0,254}@sha256:[0-9a-f]{64}")
# Successor lab build context: exactly `emulation/` minus the entries emulation/.dockerignore
# (and emulation/control.py's IGNORED) exclude, so this build and AI-Lab's
# `python3 emulation/control.py build` use identical sources. Historical tags are never moved.
LAB_IGNORED = frozenset({"output", "commands", "results", "frozen", ".ruff_cache", "__pycache__", ".git"})


def lab_build_identity(root=None):
    """(tag, source digest) of the successor lab, computed by emulation/control.py itself."""
    import importlib.util

    root = ROOT if root is None else root
    spec = importlib.util.spec_from_file_location("nanfo_emulation_control", root / "emulation" / "control.py")
    control = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(control)
    source = control.sourceDigest(root / "emulation")
    return f"{control.SUCCESSOR_REPOSITORY}:successor-{source[:12]}", source
BACKEND_EXCLUDED_SCRIPTS = re.compile(r"(test_|verify_|review_).*\.py")
# Host-only deployment tools: never staged into any image context.
HOST_ONLY_DEPLOY = frozenset({"verify.py", "manage.py", "gateway_config.py"})
BUILD_SKIPPED = frozenset({
    "node_modules", "dist", "artifacts", "venv", "test-results", "playwright-report", "__pycache__",
})


def skipped_from_context(kind, parts):
    """Never staged: host-only deploy tools and tests, private state, caches and dotfiles.

    The lab keeps dotfiles inside ``emulation/`` (e.g. its .dockerignore) so its context is
    exactly what ``docker build emulation`` would use; LAB_IGNORED still applies.
    """
    if parts[0] == "deploy" and (parts[-1].startswith("test_") or parts[-1] in HOST_ONLY_DEPLOY):
        return True
    if parts[:2] == ("deploy", "state"):
        return True
    if kind == "lab" and parts[0] == "emulation":
        return any(part in BUILD_SKIPPED for part in parts)
    return any(part.startswith(".") or part in BUILD_SKIPPED for part in parts)


def lab_source_digest(source_hashes):
    """emulation/control.py sourceDigest over the staged lab files (relative to emulation/)."""
    files = {name.removeprefix("emulation/"): digest for name, digest in source_hashes.items()}
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def run(command, *, capture=False, input=None):
    return subprocess.run(command, check=True, text=True, capture_output=capture, input=input)


def default_state(environ=os.environ, *, warn=print):
    """Keep an existing in-repository deployment; otherwise use the XDG state home.

    ``deploy/state`` counts as a deployment only when it holds ``deployment.env``; an
    evidence-only directory there is left untouched. Existing state is never moved.
    A relative ``XDG_STATE_HOME`` is ignored, as the XDG specification requires.
    """
    if (LEGACY_STATE / "deployment.env").exists():
        warn(
            f"WARNING: using existing deployment state inside the repository ({LEGACY_STATE}); "
            "keep it out of commits and backups of the checkout. It is never moved automatically.",
            file=sys.stderr,
        )
        return LEGACY_STATE
    base = environ.get("XDG_STATE_HOME", "")
    if not os.path.isabs(base):
        base = str(Path(environ.get("HOME") or Path.home()) / ".local" / "state")
    return Path(base).resolve() / "nanfo"


def _free_private_subnets(count):
    """Yield private /24s outside Docker pools and host routes, without mutation."""
    ids = run(["docker", "network", "ls", "-q"], capture=True).stdout.split()
    networks = json.loads(run(["docker", "network", "inspect", *ids], capture=True).stdout) if ids else []
    routes = json.loads(run(["ip", "-j", "-4", "route", "show", "table", "all"], capture=True).stdout)
    occupied = [
        ipaddress.ip_network(item["Subnet"], strict=False)
        for network in networks for item in (network.get("IPAM", {}).get("Config") or [])
        if item.get("Subnet")
    ]
    occupied += [ipaddress.ip_network(row["dst"], strict=False) for row in routes
                 if row.get("dst") and row["dst"] != "default"]
    pools = [ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    found = []
    for pool in pools:
        size = pool.num_addresses // 256
        start = secrets.randbelow(size)
        for offset in range(size):
            subnet = ipaddress.ip_network((int(pool.network_address) + ((start + offset) % size) * 256, 24))
            if any(subnet.version == used.version and subnet.overlaps(used) for used in occupied):
                continue
            occupied.append(subnet)
            found.append(subnet)
            if len(found) == count:
                return found
    raise ValueError("No unused private proxy subnet; review host routes and Docker pools")


def allocate_proxy_networks(count=1):
    """Select private /24s outside Docker pools and host routes, without mutation.

    Allocate source and restore together: neither network exists at selection time.
    Docker still arbitrates concurrent external allocations at network creation.
    """
    if not 1 <= count <= 16:
        raise ValueError("Proxy allocation count must be between 1 and 16")
    # APIs attach before nginx and Docker dynamically assigns from .2. The proxy
    # boundary has only nginx and one/two APIs; use its last usable address so
    # first-free allocation cannot consume nginx's IP.
    return [{"NANFO_PROXY_SUBNET": str(subnet), "NANFO_PROXY_GATEWAY_IP": str(subnet.broadcast_address - 1)}
            for subnet in _free_private_subnets(count)]


def allocate_deployment_networks(count=1):
    """Proxy boundary plus the pinned published-port bridge (R06) for each deployment."""
    if not 1 <= count <= 8:
        raise ValueError("Deployment allocation count must be between 1 and 8")
    subnets = _free_private_subnets(2 * count)
    return [
        {
            "NANFO_PROXY_SUBNET": str(proxy), "NANFO_PROXY_GATEWAY_IP": str(proxy.broadcast_address - 1),
            # Docker's bridge gateway: the source of every loopback-published connection.
            "NANFO_GATEWAY_SUBNET": str(gateway), "NANFO_GATEWAY_BRIDGE_IP": str(gateway.network_address + 1),
        }
        for proxy, gateway in zip(subnets[0::2], subnets[1::2], strict=True)
    ]


def compose(state, *args, capture=False, files=(), input=None):
    # No shell .env sourcing, ambient Compose project or development .env discovery.
    config = load_config(state)
    command = [
        "docker",
        "compose",
        "--project-name",
        config["NANFO_PROJECT"],
        "--env-file",
        str(state / "deployment.env"),
        "-f",
        str(ROOT / "deploy/compose.yaml"),
    ]
    for path in files:
        command += ["-f", str(ROOT / "deploy" / path)]
    return run([*command, *args], capture=capture, input=input)


def require_private_file(path):
    """Owner-only (no group/other bits), single-link regular file owned by this operator."""
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
        or info.st_nlink != 1
    ):
        raise ValueError("Source credentials must remain private regular files")
    return info


def _private_network(config, subnet_key, address_key, *, offset):
    subnet = ipaddress.ip_network(config[subnet_key])
    address = ipaddress.ip_address(config[address_key])
    expected = subnet.network_address + 1 if offset == 1 else subnet.broadcast_address - 1
    if subnet.version != 4 or subnet.prefixlen != 24 or not subnet.is_private or address != expected:
        raise ValueError(f"Invalid {subnet_key}/{address_key} allocation")
    return subnet


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
    missing = [key for key in REQUIRED_CONFIG if key not in config]
    if missing:
        raise ValueError("deployment.env predates this release (missing " + ", ".join(missing)
                         + "); use an explicit reviewed upgrade, never implicit regeneration")
    optional = POST_INIT_OPTIONAL if (state / "initialized.json").exists() else frozenset()
    for name in SECRET_NAMES:
        secret = state / "secrets" / name
        if name in optional and not os.path.lexists(secret):
            continue
        require_private_file(secret)
    receiver = state / RECEIVER_DIRECTORY
    if os.path.lexists(receiver):
        info = receiver.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Receiver key directory must remain private")
        if os.path.lexists(receiver / RECEIVER_PRIVATE_KEY):
            require_private_file(receiver / RECEIVER_PRIVATE_KEY)
    if not re.fullmatch(
        r"nanfo-deploy-[a-z0-9][a-z0-9-]{0,40}", config["NANFO_PROJECT"]
    ):
        raise ValueError("Deployment project must use the nanfo-deploy- prefix")
    if (
        config["NANFO_STATE_DIR"] != str(state)
        or not 1024 <= int(config["NANFO_HTTP_PORT"]) <= 65535
    ):
        raise ValueError("Invalid state directory or loopback port")
    proxy = _private_network(config, "NANFO_PROXY_SUBNET", "NANFO_PROXY_GATEWAY_IP", offset=-2)
    gateway = _private_network(config, "NANFO_GATEWAY_SUBNET", "NANFO_GATEWAY_BRIDGE_IP", offset=1)
    if proxy.overlaps(gateway):
        raise ValueError("Proxy and gateway networks must not overlap")
    # Compose's environment precedence must not redirect this project's volumes.
    for key, value in config.items():
        if key in os.environ and os.environ[key] != value:
            raise ValueError(f"Conflicting ambient variable: {key}")
    return config


def write_private(path, data, *, replace=False):
    """0600 owner-only file; replacement is atomic (temporary + fsync + rename)."""
    data = data.encode() if isinstance(data, str) else data
    target = path
    if replace:
        path = path.with_name(f".{path.name}.tmp-{secrets.token_hex(8)}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if replace:
            os.replace(path, target)
    except BaseException:
        if replace:
            path.unlink(missing_ok=True)
        raise
    sync_directory(target.parent)


def sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def receiver_keypair():
    """C21 Ed25519 receiver-health keypair (PKCS#8 private, SubjectPublicKeyInfo public)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, public


def generate(state, project, port, email):
    if not re.fullmatch(r"nanfo-deploy-[a-z0-9][a-z0-9-]{0,40}", project):
        raise ValueError("Use a unique nanfo-deploy-* project")
    if not re.fullmatch(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", email):
        raise ValueError("An explicit operator email is required")
    if not 1024 <= port <= 65535 or not re.fullmatch(r"/[a-zA-Z0-9_./-]+", str(state)):
        raise ValueError("Invalid port or state path")
    if state.resolve() != state or state.exists() or state.is_symlink():
        raise ValueError("Refusing to overwrite an existing state directory")
    require_consistent_schema()
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
    networks = allocate_deployment_networks()[0]
    private_key, public_key = receiver_keypair()
    state.mkdir(mode=0o700)
    for name in ("secrets", RECEIVER_DIRECTORY, "binding", "models", "model-registry"):
        (state / name).mkdir(mode=0o700)
    # Bind roots need traversal for the fixed application UID, never group writes.
    for name in ("binding", "models", "model-registry"):
        (state / name).chmod(0o755)
    for name in PASSWORD_SECRETS:
        write_private(state / "secrets" / name, secrets.token_hex(32) + "\n")
    # C15 mailbox HMAC key: 32 random bytes as 64 hex characters, no trailing newline.
    write_private(state / "secrets" / LAB_COMMAND_KEY, secrets.token_hex(32))
    # C21: verifiers get the public key (staged by volume-init); the signing key stays
    # in receiver/, which no Compose service or volume-init mounts.
    write_private(state / RECEIVER_DIRECTORY / RECEIVER_PRIVATE_KEY, private_key)
    write_private(state / "secrets" / RECEIVER_PUBLIC_KEY, public_key)
    config = {
        **networks,
        "NANFO_PROJECT": project,
        "NANFO_STATE_DIR": str(state),
        "NANFO_HTTP_PORT": str(port),
        "NANFO_BOOTSTRAP_EMAIL": email,
        "NANFO_BACKEND_IMAGE": f"{project}-backend:adr020",
        "NANFO_FRONTEND_IMAGE": f"{project}-frontend:adr020",
        "NANFO_NEO4J_IMAGE": f"{project}-neo4j:{NEO4J_TAG}",
        "NANFO_REDIS_IMAGE": f"{project}-redis:{REDIS_TAG}",
        "EXECUTION_MODE": "demo",
        "EMULATION_CONTROL_ENABLED": "false",
        "TELEMETRY_RUNTIME_ADAPTER_MODE": "stub",
        "API_REALTIME_DISTRIBUTED": "false",
    }
    with (state / "deployment.env").open("x") as output:
        output.write("".join(f"{key}={value}\n" for key, value in config.items()))
    (state / "deployment.env").chmod(0o600)
    return config


def context_allowed(kind, name, parts, suffix):
    """Allowlisted build-context members per image (mirrors Dockerfile.*.dockerignore)."""
    if kind == "lab":
        # The whole successor source tree except runtime mailboxes, results, frozen history
        # and caches (mirrors emulation/.dockerignore; the image build runs emulation/tests).
        return parts[0] == "emulation" and len(parts) > 1 and not LAB_IGNORED & set(parts[1:]) and suffix != ".pyc"
    if name == f"deploy/Dockerfile.{kind}":
        return True
    if kind == "backend":
        if name in {
            "backend/README.md",
            "backend/pyproject.toml",
            "backend/poetry.lock",
            "backend/alembic/alembic.ini",
            "ai-engine/pyproject.toml",
            "ai-engine/uv.lock",
            "deploy/fleet.sources",
        }:
            return True
        # Runtime data packaged with the application (ADR-028 embedded PDF font + licence).
        if name.startswith("backend/app/") and (suffix == ".ttf" or parts[-1] == "LICENSE"):
            return True
        if suffix != ".py":
            return False
        if name.startswith(("backend/app/", "backend/alembic/", "ai-engine/src/")):
            return True
        if len(parts) == 3 and parts[:2] == ("backend", "scripts"):
            # Operator verifiers/reviews and tests never enter the runtime image.
            return not BACKEND_EXCLUDED_SCRIPTS.fullmatch(parts[2])
        return len(parts) == 2 and parts[0] in {"emulation", "deploy"}
    if kind == "frontend":
        if parts[0] == "frontend":
            return suffix in {
                ".json", ".ts", ".tsx", ".js", ".css", ".html", ".svg", ".png", ".ico", ".woff2",
            } or parts[-1] == "package-lock.json"
        return name in {
            "deploy/nginx.conf",
            "deploy/nginx-security-headers.conf",
            "deploy/nginx-proxy.conf",
            "deploy/nginx-upstream.conf",
            "deploy/nginx-upstream-single.conf",
            "deploy/nginx-distributed-upstream.conf",
            "deploy/gateway-entrypoint.sh",
        }
    if kind == "neo4j":
        return name == "deploy/neo4j-entrypoint.sh"
    if kind == "redis":
        return name == "deploy/redis-entrypoint.sh"
    return False


def build_images(state, *, service=None, with_ai=False, with_fleet=False, image_tag=None):
    """Use an allowlisted tar context, including on Docker's legacy clean builder."""
    config = load_config(state)
    if with_fleet and (with_ai or service != "backend"):
        raise ValueError("Fleet build requires only --service backend --with-fleet")
    lab_source = None
    if service == "lab":
        # AI-Lab's convention (emulation/control.py build): nanfo-emulation:successor-<src12>.
        config["NANFO_LAB_BUILD_IMAGE"], lab_source = lab_build_identity()
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
        ("redis", "NANFO_REDIS_IMAGE", None),
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
                    if path.is_symlink() or not path.is_file() or skipped_from_context(kind, parts):
                        continue
                    name = relative.as_posix()
                    if context_allowed(kind, name, parts, path.suffix):
                        context.add(path, arcname=name, recursive=False)
                        source_hashes[name] = hashlib.sha256(
                            path.read_bytes()
                        ).hexdigest()
            if kind == "lab" and lab_source_digest(source_hashes) != lab_source:
                raise ValueError("Lab build context differs from the emulation/control.py source identity")
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
            if kind == "lab":
                command += ["--label", "org.nanfo.lab.source-sha256=" + lab_source]
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


def image_ids(config):
    return {
        key: run(["docker", "image", "inspect", config[key], "--format", "{{.Id}}"], capture=True).stdout.strip()
        for key in IMAGE_KEYS
    }


def adopt_restored(state, directory, key_file):
    """Authenticate source proof and reverify a stopped restored target, never migrate."""
    try:
        from deploy.backup_restore import (
            Deployment, backup_keys, load_manifest, protected_file, require_current_archive_checkpoint,
        )
    except ModuleNotFoundError:
        from backup_restore import (
            Deployment, backup_keys, load_manifest, protected_file, require_current_archive_checkpoint,
        )

    config = load_config(state)
    with protected_file(key_file, size=32) as source:
        key = source.read()
    manifest = load_manifest(directory, key)
    keys = backup_keys(key, manifest.get("format", 1))
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
        or deployment.external_fingerprints(keys.fingerprint) != manifest["external_fingerprints"]
    ):
        raise ValueError("Restored image, mount or secret proof differs")
    volumes, _ = deployment.inventory(keys.fingerprint)
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
    images = image_ids(config)
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


def start(state, *, restored=None, key_file=None):
    config = load_config(state)
    marker = state / "initialized.json"
    if bool(restored) != bool(key_file):
        raise ValueError(
            "Restored start requires both authenticated backup and key"
        )
    if restored:
        adopt_restored(state, restored, key_file)
    if not marker.exists():
        # Never initialize below the migration head the shipped code requires.
        require_consistent_schema()
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
        marker.write_text(
            json.dumps(
                {
                    "project": config["NANFO_PROJECT"],
                    "images": image_ids(config),
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
        if set(recorded["images"]) != set(IMAGE_KEYS):
            raise ValueError("Initialized image inventory differs; implicit deployment upgrade forbidden")
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


def stop(state):
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


def read_state_secret(path):
    require_private_file(path)
    value = path.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_:,-]{16,4096}", value):
        raise ValueError("Invalid source credential content")
    return value


def previous_entries(path):
    if not path.exists():
        return []
    entries = []
    for entry in read_state_secret(path).split(","):
        not_after, _, key = entry.partition(":")
        if not not_after.isdigit() or not key:
            raise ValueError("Invalid previous signing-key record")
        entries.append((int(not_after), key))
    return entries


def rotate(state, secret, *, resume=False, finalize=False, overlap_seconds=DEFAULT_JWT_OVERLAP_SECONDS,
           now=time.time):
    """Rotate one credential without ever placing plaintext in argv or SQL.

    Store credentials: the new value is journaled (0600 pending file), applied to the
    store by the in-container helper (SCRAM verifier / Redis ACL / Neo4j ALTER USER),
    atomically published, restaged into every volume holding it, and dependent
    services are restarted. A crash leaves the pending value for ``--resume``.
    """
    load_config(state)
    if not (state / "initialized.json").exists():
        raise ValueError("Rotation requires an initialized deployment")
    if secret == "jwt_secret":
        return rotate_jwt(state, finalize=finalize, resume=resume, overlap_seconds=overlap_seconds, now=now)
    if finalize:
        raise ValueError("--finalize applies to jwt_secret only")
    name, _store = ROTATIONS[secret]
    directory = state / "secrets"
    current = directory / name
    pending = directory / f".{name}.pending"
    if os.path.lexists(pending):
        if not resume:
            raise ValueError("An interrupted rotation is pending; rerun with --resume")
        value = read_state_secret(pending)
    elif resume:
        value = read_state_secret(current)  # Published already: finish restage/restart.
    else:
        value = secrets.token_hex(32)
        write_private(pending, value + "\n")
    payload = json.dumps({"password": value})
    helper = ("run", "--rm", "--no-deps", "-T", "secret-rotation", "python", "/opt/nanfo/deploy/secret_rotation.py")
    compose(state, *helper, "apply", secret, input=payload, capture=True)
    if os.path.lexists(pending):
        os.replace(pending, current)
        sync_directory(directory)
    compose(state, "run", "--rm", "--no-deps", "volume-init", "restage", name)
    restarts = ROTATION_RESTARTS[secret]
    if restarts:
        compose(state, "restart", *restarts)
    if secret == "redis":
        # Clients now hold the new password: drop every other `nanfo` password.
        compose(state, *helper, "finalize", secret, input=payload, capture=True)
    return {"rotated": secret, "restarted": list(restarts)}


def publish_jwt(state):
    """Restage the verify-only previous keys and the signing key, then restart the API."""
    compose(state, "run", "--rm", "--no-deps", "volume-init", "restage", JWT_PREVIOUS)
    compose(state, "run", "--rm", "--no-deps", "volume-init", "restage", "jwt_secret")
    compose(state, "restart", *ROTATION_RESTARTS["jwt_secret"])


def rotate_jwt(state, *, finalize, overlap_seconds, now, resume=False):
    """C19: sign with a new key; verify the previous one only for the overlap window.

    ``resume`` republishes the recorded keys after an interrupted restage/restart;
    ``finalize`` (after the window) drops the expired previous key from the API.
    """
    directory = state / "secrets"
    previous = directory / JWT_PREVIOUS
    moment = int(now())
    entries = previous_entries(previous)
    if resume and finalize:
        raise ValueError("Use either --resume or --finalize")
    if resume:
        publish_jwt(state)
        return {"rotated": "jwt_secret", "resumed": True,
                "previous_valid_until": max((not_after for not_after, _ in entries), default=None)}
    if finalize:
        if not entries:
            return {"rotated": "jwt_secret", "finalized": True, "previous_keys": 0}
        if any(not_after > moment for not_after, _ in entries):
            raise ValueError("Previous signing key is still inside its overlap window")
        previous.unlink()
        sync_directory(directory)
        publish_jwt(state)
        return {"rotated": "jwt_secret", "finalized": True, "previous_keys": 0}
    if not 0 <= overlap_seconds <= MAX_JWT_OVERLAP_SECONDS:
        raise ValueError("Overlap must be between 0 and 43200 seconds")
    current = read_state_secret(directory / "jwt_secret")
    # An entry equal to the current key is an interrupted run of this procedure.
    if any(not_after > moment and key != current for not_after, key in entries):
        raise ValueError("A previous rotation is still inside its overlap window; "
                         "--finalize it after expiry, or --resume an interrupted run")
    if overlap_seconds:
        # Verify-only: tokens are always signed with JWT_SECRET_KEY (C19).
        write_private(previous, f"{moment + overlap_seconds}:{current}\n", replace=True)
    elif previous.exists():
        previous.unlink()
        sync_directory(directory)
    write_private(directory / "jwt_secret", secrets.token_hex(32) + "\n", replace=True)
    publish_jwt(state)
    return {"rotated": "jwt_secret", "previous_valid_until": moment + overlap_seconds if overlap_seconds else None}


def autoheal(state, *, once=False, interval=30, threshold=3, sleep=time.sleep, emit=print):
    """Restart project containers reported unhealthy on more than ``threshold`` checks.

    Docker restart policies only react to exits (including the watchdog's exit 70);
    this closes the unhealthy-but-running gap for the application services.
    Datastores and the lab are never restarted here, and restarts are deferred while
    any datastore is not healthy (dependent services cannot recover by restarting).
    With ``--once`` (systemd timer) consecutive counts persist in ``autoheal.json``.
    """
    if not 1 <= threshold <= 100 or not 5 <= interval <= 3600:
        raise ValueError("Autoheal threshold 1..100 and interval 5..3600 seconds")
    config = load_config(state)
    project = f"label=com.docker.compose.project={config['NANFO_PROJECT']}"
    ledger = state / "autoheal.json"
    counts = json.loads(ledger.read_text()) if once and ledger.exists() else {}
    if not isinstance(counts, dict):
        raise ValueError("Invalid autoheal ledger")

    def listed(health, template):
        return run(["docker", "ps", "--filter", project, "--filter", f"health={health}", "--format", template],
                   capture=True).stdout.splitlines()

    while True:
        unhealthy = {}
        for line in listed("unhealthy", '{{.ID}} {{.Label "com.docker.compose.service"}}'):
            identity, _, service = line.strip().partition(" ")
            if re.fullmatch(r"[0-9a-f]{12,64}", identity) and service in AUTOHEAL_SERVICES:
                unhealthy[identity] = service
        counts = {identity: int(counts.get(identity, 0)) + 1 for identity in unhealthy}
        due = {identity: count for identity, count in counts.items() if count > threshold}
        if due:
            stores = {line.strip() for line in listed("healthy", '{{.Label "com.docker.compose.service"}}')}
            if not set(STORES) <= stores:
                emit(json.dumps({"autoheal": "deferred", "reason": "datastore_not_healthy",
                                 "services": sorted(unhealthy[identity] for identity in due)}))
                due = {}
        for identity, count in sorted(due.items()):
            run(["docker", "restart", "-t", "45", identity])
            emit(json.dumps({"autoheal": "restarted", "service": unhealthy[identity], "checks": count}))
            counts[identity] = 0
        if once:
            write_private(ledger, json.dumps(counts, sort_keys=True), replace=True)
            return counts
        sleep(interval)


def lab(state, action, *, frozen=False, environ=os.environ, warn=print):
    """Opt-in lab lifecycle; the frozen privileged EOL image needs NANFO_LAB_FROZEN=1.

    Only an operator-pinned immutable image (``NANFO_LAB_IMAGE`` for the C23 successor,
    ``NANFO_LAB_FROZEN_IMAGE`` for historical reproduction) is accepted, and ``start``
    requires an initialized deployment so the lab volumes carry the volume-init layout
    and the staged C15 command key instead of Docker-created empty volumes.
    """
    if frozen:
        acknowledged = environ.get("NANFO_LAB_FROZEN") == "1"
        warn(FROZEN_LAB_WARNING + ("" if acknowledged else " Refused: set NANFO_LAB_FROZEN=1 to acknowledge."),
             file=sys.stderr)
        if not acknowledged:
            raise ValueError("Frozen lab refused without NANFO_LAB_FROZEN=1")
    config = load_config(state)
    key = "NANFO_LAB_FROZEN_IMAGE" if frozen else "NANFO_LAB_IMAGE"
    if not LAB_IMAGE_PIN.fullmatch(config.get(key) or environ.get(key, "")):
        raise ValueError(f"{key} must be an operator-verified sha256 image ID or @sha256 digest reference")
    files = ["compose.lab.frozen.yaml" if frozen else "compose.lab.yaml"]
    if action == "start":
        if not (state / "initialized.json").exists():
            raise ValueError("Lab start requires an initialized deployment (lab volumes and C15 key staged)")
        return compose(state, "--profile", "lab", "up", "-d", "--no-build", "--no-deps", "lab", files=files)
    if action == "stop":
        return compose(state, "stop", "--timeout", "30", "lab", files=files)
    return compose(state, "--profile", "lab", "ps", "--all", "lab", files=files)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, help="Deployment state directory (see module docstring)")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--project", required=True)
    init.add_argument("--port", type=int, default=8787)
    init.add_argument("--email", required=True)
    init.add_argument("--build", action="store_true")
    build = commands.add_parser("build")
    build.add_argument("--service", choices=["backend", "frontend", "neo4j", "redis", "lab"])
    build.add_argument("--with-ai", action="store_true")
    build.add_argument("--with-fleet", action="store_true")
    build.add_argument(
        "--image-tag",
        help="New backend release tag; never changes the initialized stack",
    )
    starting = commands.add_parser("start")
    starting.add_argument("--restored", type=Path, metavar="BACKUP_DIRECTORY")
    starting.add_argument("--encryption-key-file", type=Path)
    commands.add_parser("stop")
    commands.add_parser("status")
    commands.add_parser("config")
    rotation = commands.add_parser("rotate", help="Rotate one credential (see deploy/OPERATIONS.md)")
    rotation.add_argument("--secret", required=True, choices=sorted(ROTATIONS))
    rotation.add_argument("--resume", action="store_true", help="Finish an interrupted rotation")
    rotation.add_argument("--finalize", action="store_true", help="jwt_secret: drop the expired previous key")
    rotation.add_argument("--overlap-seconds", type=int, default=DEFAULT_JWT_OVERLAP_SECONDS,
                          help="jwt_secret: previous-key verification window (0 revokes immediately)")
    healing = commands.add_parser("autoheal", help="Restart persistently unhealthy application containers")
    healing.add_argument("--once", action="store_true", help="One observation (systemd timer)")
    healing.add_argument("--interval", type=int, default=30, help="Seconds between observations")
    healing.add_argument("--threshold", type=int, default=3, help="Restart after more than N unhealthy checks")
    laboratory = commands.add_parser("lab", help="Opt-in lab lifecycle (never started implicitly)")
    laboratory.add_argument("action", choices=["start", "stop", "status"])
    laboratory.add_argument("--frozen", action="store_true", help="Frozen privileged EOL image (historical only)")
    args = parser.parse_args(argv)
    state = args.state.absolute() if args.state else default_state()
    os.umask(0o077)
    if args.command == "init":
        if args.state is None and not state.parent.exists():
            state.parent.mkdir(mode=0o700, parents=True)
        generate(state, args.project, args.port, args.email)
        compose(state, "config", "--quiet")
        if args.build:
            build_images(state)
        print("Private configuration generated. Run start only after images are built.")
    elif args.command == "build":
        # The opt-in lab image is pinned separately (NANFO_LAB_IMAGE), never in initialized.json.
        if (
            (state / "initialized.json").exists()
            and args.service != "lab"
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
        start(state, restored=args.restored, key_file=args.encryption_key_file)
    elif args.command == "stop":
        stop(state)
    elif args.command == "status":
        compose(state, "ps", "--all")
    elif args.command == "rotate":
        print(json.dumps(rotate(state, args.secret, resume=args.resume, finalize=args.finalize,
                                overlap_seconds=args.overlap_seconds), sort_keys=True))
    elif args.command == "autoheal":
        autoheal(state, once=args.once, interval=args.interval, threshold=args.threshold)
    elif args.command == "lab":
        lab(state, args.action, frozen=args.frozen)
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
