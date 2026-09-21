"""ADR020 cold-volume operations. Run with --help; failures never resume writers.

Host requirements: Python 3.12+, cryptography and Docker Compose v2. Keep the
32-byte encryption key separately, mode 0600; the tool never generates/logs it.
Restore is same OS/architecture/image IDs only, not a portable database export.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

MAGIC = b"NANFO-GCM-1\0"
CHUNK = 1024 * 1024
PROJECT = re.compile(r"nanfo-deploy-[a-z0-9][a-z0-9-]{0,47}\Z")
SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
STORES = {"postgres", "redis", "neo4j"}
STAGES = frozenset(
    {
        "arguments",
        "key",
        "configuration",
        "archive_validation",
        "backup_inventory",
        "backup_quiesce",
        "backup_checkpoint",
        "backup_stop_stores",
        "backup_archive",
        "restore_validate",
        "restore_extract",
        "restore_start_stores",
        "restore_checkpoint",
        "restore_sessions",
    }
)


class OperationError(Exception):
    """Safe, operator-facing failure; never include subprocess output."""


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def protected_file(path, *, size=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
        or info.st_nlink != 1
        or (size is not None and info.st_size != size)
    ):
        os.close(fd)
        raise OperationError(
            "File must be regular, owned, single-link and mode 0600 (key: exactly 32 raw bytes)."
        )
    return os.fdopen(fd, "rb")


def private_directory(path):
    path = Path(path).absolute()
    if path.resolve() != path:
        raise OperationError(
            "Protected directory must not contain symlinks or traversal."
        )
    info = path.stat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
    ):
        raise OperationError("Use an operator-owned directory with mode 0700.")
    return path


def file_hash(path):
    result = hashlib.sha256()
    with protected_file(path) as source:
        while data := source.read(CHUNK):
            result.update(data)
    return result.hexdigest()


def encrypt_stream(source, target, key, aad, *, max_bytes):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    target.write(MAGIC + nonce)
    total = 0
    while block := source.read(CHUNK):
        total += len(block)
        if total > max_bytes:
            raise OperationError("Archive byte cap exceeded; backup incomplete.")
        target.write(encryptor.update(block))
    target.write(encryptor.finalize())
    target.write(encryptor.tag)
    return total


def decrypt_stream(source, target, key, aad, *, max_bytes):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if source.read(len(MAGIC)) != MAGIC:
        raise OperationError("Unsupported encrypted archive.")
    nonce = source.read(12)
    begin = source.tell()
    source.seek(0, 2)
    end = source.tell() - 16
    if end < begin or end - begin > max_bytes:
        raise OperationError("Encrypted archive exceeds byte cap or is truncated.")
    source.seek(end)
    tag = source.read(16)
    source.seek(begin)
    decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
    decryptor.authenticate_additional_data(aad)
    try:
        remaining = end - begin
        while remaining:
            block = source.read(min(CHUNK, remaining))
            if not block:
                raise OperationError("Truncated archive.")
            remaining -= len(block)
            target.write(decryptor.update(block))
        target.write(decryptor.finalize())
    except InvalidTag:
        raise OperationError(
            "Archive authentication failed; nothing extracted."
        ) from None
    target.flush()
    target.seek(0)


def validate_tar(source, *, max_bytes, max_entries=1_000_000):
    """Validate the entire authenticated tar before starting any extraction.

    Internal links are allowed, but may never be traversal parents or leave root.
    Devices, sockets, FIFOs, sparse files and duplicate entries are refused.
    """
    entries, total = {}, 0
    source.seek(0)
    with tarfile.open(fileobj=source, mode="r:") as archive:
        for member in archive:
            name = member.name
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in name
                or len(name) > 4096
                or "\x00" in name
            ):
                raise OperationError("Unsafe archive path.")
            name = str(path)
            if name in entries or len(entries) >= max_entries:
                raise OperationError("Duplicate entry or archive entry cap exceeded.")
            if (
                not (
                    member.isfile()
                    or member.isdir()
                    or member.issym()
                    or member.islnk()
                )
                or member.sparse
            ):
                raise OperationError("Unsupported archive entry type.")
            if member.mode & 0o7000:
                raise OperationError("Special permission bits are not restorable.")
            if member.size < 0:
                raise OperationError("Invalid archive entry size.")
            total += member.size
            if total > max_bytes:
                raise OperationError("Expanded archive byte cap exceeded.")
            if member.issym() or member.islnk():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or "\\" in member.linkname or ".." in link.parts:
                    raise OperationError("Unsafe archive link.")
            entries[name] = member
    for name, member in entries.items():
        if any(
            str(parent) in entries and not entries[str(parent)].isdir()
            for parent in PurePosixPath(name).parents
        ):
            raise OperationError("Archive entry descends through a non-directory.")
        if member.islnk():
            target = entries.get(str(PurePosixPath(member.linkname)))
            if target is None or not target.isfile():
                raise OperationError(
                    "Hardlink must reference a regular archive member."
                )
    source.seek(0)
    return {"entries": len(entries), "bytes": total}


class Deployment:
    def __init__(self, project, compose_files, env_file, *, runner=subprocess.run):
        if not PROJECT.fullmatch(project):
            raise OperationError(
                "Explicit --project must match nanfo-deploy-<scope>; existing nanfo_* is forbidden."
            )
        self.project, self.runner = project, runner
        self.base = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--env-file",
            str(Path(env_file).resolve()),
        ]
        for file in compose_files:
            self.base += ["-f", str(Path(file).resolve())]
        # Inspect every declared profile, including the persisted init_secrets
        # volume. This does not activate profiles on any lifecycle command.
        self.config = self.json(
            *self.base, "--profile", "*", "config", "--format", "json"
        )
        for spec in self.config.get("networks", {}).values():
            if spec.get("external") or not spec.get("name", "").startswith(
                project + "_"
            ):
                raise OperationError("Only project-owned networks are supported.")
        if (
            not STORES.issubset(self.config["services"])
            or "api" not in self.config["services"]
        ):
            raise OperationError(
                "Compose must define api, postgres, redis and neo4j services."
            )
        for service in self.config["services"].values():
            if service.get("network_mode") not in (None, "none"):
                raise OperationError(
                    "Shared/host service network namespaces are forbidden."
                )
            environment = service.get("environment", {})
            if (
                environment.get("POSTGRES_HOST", "postgres") != "postgres"
                or environment.get("REDIS_HOST", "redis") != "redis"
                or environment.get("NEO4J_URI", "bolt://neo4j:7687")
                != "bolt://neo4j:7687"
            ):
                raise OperationError(
                    "Operations require project-local stores, never external/shared database endpoints."
                )

    def run(self, *args, **kwargs):
        allow_failure = kwargs.pop("allow_failure", False)
        result = self.runner(
            list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=kwargs.pop("timeout", 180),
            **kwargs,
        )
        dependency_pending = False
        if result.returncode and allow_failure:
            try:
                value = json.loads(result.stdout)
                dependency_pending = (
                    isinstance(value, dict)
                    and set(value) == {"safe", "dependencies"}
                    and value["safe"] is False
                    and isinstance(value["dependencies"], dict)
                    and set(value["dependencies"]).issubset(
                        {"postgres", "schema", "redis", "neo4j"}
                    )
                    and set(value["dependencies"].values()).issubset(
                        {"ok", "unavailable"}
                    )
                    and "unavailable" in value["dependencies"].values()
                )
            except (ValueError, TypeError):
                pass
        if result.returncode and not dependency_pending:
            diagnostic_dir = getattr(self, "diagnostic_dir", None)
            if diagnostic_dir is not None:
                # Private bounded diagnostics are outside export/backup manifests.
                with tempfile.NamedTemporaryFile(
                    prefix="docker-", suffix=".private.log", dir=diagnostic_dir
                ) as diagnostic:
                    diagnostic.write(result.stderr[:65536])
                    diagnostic.write(b"\nPRIVATE STDOUT\n" + result.stdout[:65536])
                    diagnostic.flush()
                    # Keep only this explicit private failure record for diagnosis.
                    os.link(diagnostic.name, diagnostic.name + ".retained")
            raise OperationError(
                "Docker operation failed; inspect scoped services locally (output suppressed for secrets)."
            )
        return result.stdout

    def json(self, *args):
        return json.loads(self.run(*args))

    def compose(self, *args, **kwargs):
        return self.run(*self.base, *args, timeout=kwargs.pop("timeout", 600), **kwargs)

    def containers(self):
        ids = (
            self.run(
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label=com.docker.compose.project={self.project}",
            )
            .decode()
            .split()
        )
        return self.json("docker", "inspect", *ids) if ids else []

    def volumes(self):
        ids = (
            self.run(
                "docker",
                "volume",
                "ls",
                "-q",
                "--filter",
                f"label=com.docker.compose.project={self.project}",
            )
            .decode()
            .split()
        )
        return self.json("docker", "volume", "inspect", *ids) if ids else []

    def volume_name(self, logical):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", logical):
            raise OperationError("Invalid logical volume identity.")
        spec = self.config.get("volumes", {}).get(logical)
        expected = f"{self.project}_{logical}"
        if (
            spec is None
            or spec.get("external")
            or spec.get("driver_opts")
            or spec.get("name", expected) != expected
        ):
            raise OperationError(
                "Only project-prefixed, non-external named volumes are supported."
            )
        return expected

    def images(self):
        result = {}
        for name, spec in self.config["services"].items():
            if not spec.get("image"):
                raise OperationError("Build/tag all Compose images before operations.")
            image = self.json("docker", "image", "inspect", spec["image"])[0]
            result[name] = {
                "id": image["Id"],
                "os": image["Os"],
                "architecture": image["Architecture"],
            }
        return result

    def mount_contract(self):
        return {
            name: sorted(
                [
                    {
                        "type": mount["type"],
                        "target": mount["target"],
                        "source": mount.get("source")
                        if mount["type"] == "volume"
                        else "operator-bind",
                        "read_only": mount.get("read_only", False),
                    }
                    for mount in spec.get("volumes", [])
                ],
                key=lambda mount: mount["target"],
            )
            for name, spec in self.config["services"].items()
        }

    def external_fingerprints(self, key):
        result = {}
        for name, service in self.config["services"].items():
            for category, root in (("secrets", "/run/secrets/"), ("configs", "/")):
                for mount in service.get(category, []):
                    spec = self.config.get(category, {}).get(mount["source"], {})
                    if "file" not in spec:
                        raise OperationError(
                            "External secret/config provider cannot be verified."
                        )
                    source = Path(spec["file"])
                    if source.is_symlink() or not source.is_file():
                        raise OperationError(
                            "Secret/config must be an explicit regular file."
                        )
                    with open(source, "rb") as stream:
                        data = stream.read(CHUNK + 1)
                    if len(data) > CHUNK:
                        raise OperationError("External configuration exceeds cap.")
                    target = mount.get("target", mount["source"])
                    if not target.startswith("/"):
                        target = root + target
                    result[f"{name}:{target}"] = hmac.new(
                        key, data, hashlib.sha256
                    ).hexdigest()
            for mount in service.get("volumes", []):
                if mount.get("type") == "bind":
                    source = Path(mount["source"])
                    if name == "volume-init" and mount["target"] == "/source-secrets":
                        continue  # Runtime/init secret volumes are included in full.
                    if not mount.get("read_only") or source.is_symlink():
                        raise OperationError(
                            "External binds must be read-only, non-symlink operator inputs."
                        )
                    if source.is_file():
                        if mount["target"] != "/deploy/redis-entrypoint.sh":
                            raise OperationError(
                                "Unbacked regular bind; use a backed directory or Compose secret."
                            )
                        with open(source, "rb") as stream:
                            data = stream.read(CHUNK + 1)
                        if len(data) > CHUNK:
                            raise OperationError("External script exceeds cap.")
                        result[f"{name}:{mount['target']}"] = hmac.new(
                            key, data, hashlib.sha256
                        ).hexdigest()
                    elif not source.is_dir():
                        raise OperationError(
                            "External bind source must exist before backup/restore."
                        )
                if mount.get("type") == "volume":
                    self.volume_name(mount.get("source", ""))
        return result

    def binds(self):
        groups = {}
        for name, service in sorted(self.config["services"].items()):
            for mount in service.get("volumes", []):
                if mount.get("type") != "bind" or (
                    name == "volume-init" and mount["target"] == "/source-secrets"
                ):
                    continue
                source = Path(mount["source"])
                if source.is_dir():
                    if not mount.get("read_only") or source.resolve() != source:
                        raise OperationError(
                            "Backed bind directories must be read-only and canonical."
                        )
                    groups.setdefault(str(source), []).append(
                        f"{name}:{mount['target']}"
                    )
        return {
            "bind-" + hashlib.sha256(canonical(sorted(refs))).hexdigest()[:16]: {
                "source": source,
                "references": sorted(refs),
            }
            for source, refs in groups.items()
        }

    def inventory(self, key):
        declared = {
            self.volume_name(name): name for name in self.config.get("volumes", {})
        }
        for service, spec in self.config["services"].items():
            named = [
                mount for mount in spec.get("volumes", []) if mount["type"] == "volume"
            ]
            if service in STORES and not named:
                raise OperationError(
                    "Every datastore must declare a backed named volume."
                )
            for mount in named:
                self.volume_name(mount.get("source", ""))
        volumes = self.volumes()
        for volume in volumes:
            if (
                volume["Name"] not in declared
                or volume.get("Driver") != "local"
                or volume.get("Options")
                or volume.get("Labels", {}).get("com.docker.compose.volume")
                != declared[volume["Name"]]
            ):
                raise OperationError(
                    "Unrecognized/external volume; cannot prove complete backup."
                )
        existing = {v["Name"] for v in volumes}
        if existing != set(declared):
            raise OperationError(
                "Declared volume is missing; refusing incomplete backup before any service mutation."
            )
        containers = self.containers()
        services_present = set()
        for container in containers:
            service = (
                container.get("Config", {})
                .get("Labels", {})
                .get("com.docker.compose.service")
            )
            if service not in self.config["services"]:
                raise OperationError(
                    "Unknown project container; cannot validate mount layout."
                )
            services_present.add(service)
            spec = self.config["services"][service]
            expected = {}
            for mount in spec.get("volumes", []):
                if mount["type"] not in {"volume", "bind"}:
                    continue
                source = (
                    self.volume_name(mount.get("source", ""))
                    if mount["type"] == "volume"
                    else str(Path(mount["source"]).resolve())
                )
                target = mount["target"]
                if target in expected:
                    raise OperationError(
                        "Duplicate declared persistent mount destination."
                    )
                expected[target] = (
                    mount["type"],
                    source,
                    not mount.get("read_only", False),
                )
                if mount.get("volume", {}).get("subpath"):
                    raise OperationError(
                        "Volume subpath mounts are not supported by cold backup."
                    )
            for category, root in (("secrets", "/run/secrets/"), ("configs", "/")):
                for mount in spec.get(category, []):
                    source = (
                        self.config.get(category, {})
                        .get(mount["source"], {})
                        .get("file")
                    )
                    if not source:
                        raise OperationError(
                            "Unverifiable external secret/config mount."
                        )
                    target = mount.get("target", mount["source"])
                    target = target if target.startswith("/") else root + target
                    if target in expected:
                        raise OperationError(
                            "Duplicate declared persistent mount destination."
                        )
                    expected[target] = ("bind", str(Path(source).resolve()), False)
            actual = {}
            for mount in container.get("Mounts", []):
                if mount["Type"] not in {"volume", "bind"}:
                    continue
                target = mount["Destination"]
                if target in actual:
                    raise OperationError(
                        "Duplicate actual persistent mount destination."
                    )
                source = (
                    mount.get("Name")
                    if mount["Type"] == "volume"
                    else str(Path(mount["Source"]).resolve())
                )
                actual[target] = (mount["Type"], source, mount.get("RW"))
            if actual != expected:
                raise OperationError(
                    "Actual service persistent mounts differ from resolved Compose declaration."
                )
        if not STORES.issubset(services_present):
            raise OperationError(
                "Missing datastore container; cannot establish backed mount identity."
            )
        secret_sources = {
            str(Path(v["file"]).resolve())
            for v in self.config.get("secrets", {}).values()
            if "file" in v
        }
        config_sources = {
            str(Path(v["file"]).resolve())
            for v in self.config.get("configs", {}).values()
            if "file" in v
        }
        external = self.external_fingerprints(key)
        binds = {value["source"] for value in self.binds().values()}
        for container in containers:
            service = (
                container.get("Config", {})
                .get("Labels", {})
                .get("com.docker.compose.service")
            )
            if service not in self.config["services"]:
                raise OperationError(
                    "Unknown project container; stop and reconcile manually."
                )
            for mount in container.get("Mounts", []):
                if mount["Type"] == "volume" and mount.get("Name") not in existing:
                    raise OperationError(
                        "Anonymous or foreign mounted volume is not backed up."
                    )
                if mount["Type"] == "bind":
                    source = str(Path(mount["Source"]).resolve())
                    if (
                        service == "volume-init"
                        and mount["Destination"] == "/source-secrets"
                        and not mount.get("RW")
                    ):
                        continue
                    if source in binds and not mount.get("RW"):
                        continue
                    script = mount["Destination"] == "/deploy/redis-entrypoint.sh"
                    if (
                        source not in secret_sources | config_sources and not script
                    ) or mount.get("RW"):
                        raise OperationError(
                            "Unbacked external bind mount. Move model/lab/report data to an owned named volume."
                        )
                    with open(source, "rb") as stream:
                        data = stream.read(CHUNK + 1)
                    if len(data) > CHUNK:
                        raise OperationError("External configuration exceeds cap.")
                    # Keyed fingerprints do not provide an offline password oracle.
                    identity = f"{service}:{mount['Destination']}"
                    if (
                        external.get(identity)
                        != hmac.new(key, data, hashlib.sha256).hexdigest()
                    ):
                        raise OperationError(
                            "Actual external mount differs from Compose declaration."
                        )
        return {declared[v["Name"]]: v["Name"] for v in volumes}, external

    def assert_stopped(self, *, stores_allowed=False):
        for container in self.containers():
            service = container["Config"]["Labels"].get("com.docker.compose.service")
            if container["State"].get("Running") and not (
                stores_allowed and service in STORES
            ):
                raise OperationError(
                    "All application/lab owners must be stopped; no live-volume operation permitted."
                )
            if (
                not stores_allowed
                and service in STORES
                and container["State"].get("ExitCode") != 0
            ):
                raise OperationError(
                    "Store did not shut down cleanly; cold backup refused."
                )

    def assert_exclusive(self, volumes):
        for name in volumes:
            ids = (
                self.run("docker", "ps", "-q", "--filter", f"volume={name}")
                .decode()
                .split()
            )
            if ids:
                raise OperationError(
                    "A running container still mounts a backup volume."
                )
        for value in self.binds().values():
            if self.run(
                "docker", "ps", "-q", "--filter", f"volume={value['source']}"
            ).strip():
                raise OperationError(
                    "A running container still mounts a backed external directory."
                )

    def maintenance(self, action, *, wait_dependencies=False):
        deadline = time.monotonic() + 120
        while True:
            result = self._maintenance_result(action)
            if result.get("safe") is True:
                return result
            dependencies = result.get("dependencies")
            if not (
                wait_dependencies
                and isinstance(dependencies, dict)
                and set(result) == {"safe", "dependencies"}
                and set(dependencies).issubset({"postgres", "schema", "redis", "neo4j"})
                and "unavailable" in dependencies.values()
                and time.monotonic() < deadline
            ):
                raise OperationError(
                    "Maintenance checkpoint refused: resolve physical execution/overrides with their owner services."
                )
            time.sleep(2)

    def _maintenance_result(self, action):
        output = self.compose(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "maintenance" if "maintenance" in self.config["services"] else "api",
            "python",
            "/opt/nanfo/deploy/maintenance.py",
            action,
            allow_failure=True,
            timeout=130,
        )
        try:
            result = json.loads(output)
        except (ValueError, TypeError):
            raise OperationError(
                "Maintenance CLI did not return a valid checkpoint."
            ) from None
        if not isinstance(result, dict):
            raise OperationError("Maintenance CLI did not return a valid checkpoint.")
        return result

    def helper_args(self, image, volume, *, readonly, bind=False):
        if not SHA.fullmatch(image):
            raise OperationError("Helper requires an exact local image ID.")
        args = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--read-only",
            "--user",
            "0:0",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "DAC_OVERRIDE",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            "256m",
            "--label",
            f"com.docker.compose.project={self.project}",
            "--label",
            "com.docker.compose.service=operations-helper",
        ]
        if not readonly:
            args += ["--cap-add", "CHOWN", "--cap-add", "FOWNER"]
        if "," in volume:
            raise OperationError("Mount source contains an unsupported delimiter.")
        args += [
            "--mount",
            f"type={'bind' if bind else 'volume'},src={volume},dst=/volume"
            + (",readonly" if readonly else ""),
            "--entrypoint",
            "tar",
            image,
        ]
        return args + (
            ["-c", "-f", "-", "-C", "/volume", "."]
            if readonly
            else ["-x", "-p", "--numeric-owner", "-f", "-", "-C", "/volume"]
        )


def write_json(path, value):
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def load_manifest(directory, key):
    directory = private_directory(directory)
    with protected_file(directory / "manifest.json") as stream:
        raw = stream.read(CHUNK + 1)
    if len(raw) > CHUNK:
        raise OperationError("Manifest exceeds cap.")
    with protected_file(directory / "manifest.hmac") as stream:
        signature = stream.read(65).decode("ascii")
    if not hmac.compare_digest(
        signature, hmac.new(key, raw, hashlib.sha256).hexdigest()
    ):
        raise OperationError("Manifest authentication failed.")
    manifest = json.loads(raw)
    if manifest.get("format") != 1 or manifest.get("complete") is not True:
        raise OperationError("Incomplete/unsupported backup manifest.")
    if not PROJECT.fullmatch(manifest.get("project", "")):
        raise OperationError("Invalid source project.")
    files = set()
    for item in manifest["volumes"] + manifest.get("binds", []):
        filename = item["file"]
        if (
            not re.fullmatch(r"volume-[0-9]{4}\.tar\.gcm", filename)
            or filename in files
        ):
            raise OperationError("Unsafe/duplicate manifest archive filename.")
        files.add(filename)
        if file_hash(directory / filename) != item["sha256"]:
            raise OperationError("Encrypted archive checksum mismatch.")
    return manifest


def backup(deployment, directory, key, *, max_bytes):
    deployment.stage = "backup_inventory"
    directory = private_directory(directory)
    if any(directory.iterdir()):
        raise OperationError("Backup destination must be empty.")
    images = deployment.images()
    volumes, external = deployment.inventory(key)
    binds = deployment.binds()
    if not volumes or not deployment.containers():
        raise OperationError("No initialized deployment to back up.")
    for container in deployment.containers():
        service = container["Config"]["Labels"].get("com.docker.compose.service")
        if container["Image"] != images[service]["id"]:
            raise OperationError(
                "Running deployment image differs from Compose image; exact restore cannot be guaranteed."
            )
    # Stop admissions first; recovery workers remain alive until owner services
    # prove there is no unresolved physical work. Refusal never kills recovery.
    deployment.stage = "backup_quiesce"
    admissions = ["gateway", "api"]
    if "api2" in deployment.config["services"]:
        admissions.append("api2")
    deployment.compose("stop", "--timeout", "120", *admissions)
    checkpoint = deployment.maintenance("quiesce")
    references = checkpoint.get("model_references", {})
    if any(references.values()):
        service = deployment.config["services"]["api"]
        environment = service.get("environment", {})
        live_registry = environment.get("NANFO_LIVE_MODEL_REGISTRY")
        roots = [environment.get("NANFO_MODEL_ROOT")]
        if references.get("diagnostic_records"):
            roots.append(environment.get("NANFO_MODEL_REGISTRY"))
        if references.get("checkpoint_decisions") and live_registry:
            roots.extend([live_registry, environment.get("NANFO_LIVE_OBSERVATION_ROOT")])
        elif references.get("checkpoint_decisions"):
            roots.extend([
                environment.get("NANFO_MODEL_REGISTRY"),
                environment.get("NANFO_AUTONOMY_ARTIFACT_ROOT"),
            ])
        targets = [
            mount["target"]
            for mount in service.get("volumes", [])
            if mount.get("type") in {"bind", "volume"}
        ]
        if any(
            not root
            or not any(PurePosixPath(root).is_relative_to(target) for target in targets)
            for root in roots
        ):
            raise OperationError(
                "Persisted model references require mounted/backed model, registry and evidence roots."
            )
    writers = sorted(set(deployment.config["services"]) - STORES)
    deployment.compose("stop", "--timeout", "120", *writers)
    deployment.assert_stopped(stores_allowed=True)
    deployment.stage = "backup_checkpoint"
    checkpoint = deployment.maintenance("checkpoint")
    require_current_archive_checkpoint(checkpoint, volumes)
    if not isinstance(checkpoint.get("neo4j_graph"), dict):
        raise OperationError(
            "Maintenance image lacks the required Neo4j graph checkpoint."
        )
    deployment.stage = "backup_stop_stores"
    deployment.compose("stop", "--timeout", "120", *sorted(STORES))
    deployment.assert_stopped()
    deployment.assert_exclusive(volumes.values())
    current, current_external = deployment.inventory(key)
    if current != volumes or current_external != external:
        raise OperationError("Mount inventory changed during quiescence.")
    manifest = {
        "format": 1,
        "complete": True,
        "project": deployment.project,
        "created_at": datetime.now(UTC).isoformat(),
        "images": images,
        "mount_contract": deployment.mount_contract(),
        "external_fingerprints": external,
        "checkpoint": checkpoint,
        "volumes": [],
        "binds": [],
        "restore_scope": "same-image-id-os-architecture; manual writer/lab resume",
        "external_writer_boundary": "Operator must freeze host-side bind producers and serialize Docker operations",
    }
    archives = [(logical, name, "volume") for logical, name in sorted(volumes.items())]
    archives += [
        (logical, value["source"], "bind") for logical, value in sorted(binds.items())
    ]
    for index, (logical, name, kind) in enumerate(archives):
        deployment.stage = "backup_archive"
        deployment.assert_stopped()
        deployment.assert_exclusive(volumes.values())
        filename = f"volume-{index:04d}.tar.gcm"
        aad = canonical(
            {"project": deployment.project, "volume": logical, "file": filename}
        )
        process = subprocess.Popen(
            deployment.helper_args(
                images["api"]["id"], name, readonly=True, bind=kind == "bind"
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            with os.fdopen(
                os.open(
                    directory / filename,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                ),
                "wb",
            ) as target:
                size = encrypt_stream(
                    process.stdout, target, key, aad, max_bytes=max_bytes
                )
                target.flush()
                os.fsync(target.fileno())
            if process.wait(timeout=120):
                raise OperationError("Cold volume reader failed; backup is incomplete.")
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait()
        item = {
            "logical": logical,
            "kind": kind,
            "file": filename,
            "bytes": size,
            "sha256": file_hash(directory / filename),
        }
        with (
            protected_file(directory / filename) as source,
            tempfile.TemporaryFile(dir=directory) as plain,
        ):
            decrypt_stream(source, plain, key, aad, max_bytes=max_bytes)
            validate_tar(plain, max_bytes=max_bytes)
        if kind == "bind":
            item.update(
                references=binds[logical]["references"],
                source_path_sha256=hashlib.sha256(name.encode()).hexdigest(),
            )
        manifest["binds" if kind == "bind" else "volumes"].append(item)
    deployment.assert_stopped()
    deployment.assert_exclusive(volumes.values())
    write_json(directory / "manifest.json", manifest)
    with os.fdopen(
        os.open(
            directory / "manifest.hmac",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        ),
        "wb",
    ) as stream:
        stream.write(
            hmac.new(key, canonical(manifest), hashlib.sha256).hexdigest().encode()
        )
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "status": "backed_up",
        "volumes": len(volumes),
        "binds": len(binds),
        "writers": "stopped",
        "resume": "manual",
    }


def require_current_archive_checkpoint(checkpoint, volumes):
    """Historical archives remain readable; current ones must include ADR023 proof."""
    schema = checkpoint.get("schema")
    # Capability floor, not equality with a release target: later schemas must
    # never lose the archive/ownership proof merely by advancing the revision.
    if not isinstance(schema, str) or not re.fullmatch(r"[0-9]{4}", schema):
        raise OperationError("Archive checkpoint requires an explicit numeric schema revision.")
    if int(schema) >= 27 and (
        "telemetry_archive" not in volumes
        or not isinstance(checkpoint.get("telemetry_archive"), dict)
        or set(checkpoint["telemetry_archive"]) != {
            "telemetry_archive_receipts", "telemetry_event_tombstones",
            "telemetry_evidence_pins", "telemetry_reference_coverage",
            "telemetry_reference_reconciliation",
        }
        or checkpoint.get("autonomous_execution") != {
            "safe": True, "unreleased_executions": 0,
        }
    ):
        raise OperationError("Schema 0027+ requires archive integrity and released execution proof.")
    if int(schema) >= 28 and checkpoint.get("experimental_lab") != {
        "safe": True, "unreleased_runs": 0, "owned_resources": 0, "pending_actions": 0,
    }:
        raise OperationError("Schema 0028+ requires released experimental ownership proof.")


def restore(deployment, directory, key, *, max_bytes):
    deployment.stage = "restore_validate"
    directory = private_directory(directory)
    manifest = load_manifest(directory, key)
    checkpoint = manifest.get("checkpoint", {})
    if not isinstance(checkpoint.get("neo4j_graph"), dict):
        raise OperationError("Backup lacks required Neo4j graph integrity evidence.")
    archived = [item["logical"] for item in manifest["volumes"]]
    require_current_archive_checkpoint(checkpoint, archived)
    if len(archived) != len(set(archived)) or set(archived) != set(
        deployment.config.get("volumes", {})
    ):
        raise OperationError(
            "Every declared target volume must have exactly one backup archive; empty creation forbidden."
        )
    for service, spec in deployment.config["services"].items():
        named = [
            mount for mount in spec.get("volumes", []) if mount["type"] == "volume"
        ]
        if service in STORES and not named:
            raise OperationError(
                "Every target datastore must declare a backed named volume."
            )
        if any(mount.get("source") not in archived for mount in named):
            raise OperationError(
                "Target service references an unarchived volume; empty creation forbidden."
            )
    if (
        deployment.project == manifest["project"]
        or deployment.containers()
        or deployment.volumes()
    ):
        raise OperationError(
            "Restore requires a different fresh project with no containers or volumes."
        )
    if deployment.images() != manifest["images"]:
        raise OperationError(
            "Restore requires exact source image IDs, OS and architecture."
        )
    if (
        manifest.get("mount_contract") is not None
        and deployment.mount_contract() != manifest["mount_contract"]
    ):
        raise OperationError("Target mount layout differs from the backed deployment.")
    if deployment.external_fingerprints(key) != manifest["external_fingerprints"]:
        raise OperationError(
            "Supply the original identical secret/config files before restore; plaintext is not in the backup."
        )
    if deployment.run(
        "docker",
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.compose.project={manifest['project']}",
    ).strip():
        raise OperationError(
            "Source project still has running owners; stop them before restoring sessions/leases."
        )
    binds = deployment.binds()
    archives = manifest["volumes"] + manifest.get("binds", [])
    if set(binds) != {item["logical"] for item in manifest.get("binds", [])}:
        raise OperationError("Target external directory inventory differs from backup.")
    names = []
    for item in archives:
        if item.get("kind", "volume") == "volume":
            names.append(deployment.volume_name(item["logical"]))
        elif item["kind"] == "bind":
            value = binds.get(item["logical"])
            if not value or value["references"] != item["references"]:
                raise OperationError("Target bind mount inventory differs from backup.")
            source = value["source"]
            if hashlib.sha256(source.encode()).hexdigest() == item[
                "source_path_sha256"
            ] or any(Path(source).iterdir()):
                raise OperationError(
                    "Restore bind target must be a different empty directory, never the source directory."
                )
            names.append(source)
        else:
            raise OperationError("Unknown archive kind.")
    if len(names) != len(set(names)):
        raise OperationError("Duplicate logical volume.")
    # Authenticate and validate ALL volumes before creating the first target volume.
    # Plaintext temporary files are unlinked immediately and never enter the backup.
    with (
        tempfile.TemporaryDirectory(prefix=".restore-", dir=directory) as temp,
        ExitStack() as stack,
    ):
        validated = []
        for item in archives:
            # The descriptor becomes subprocess stdin. Buffered seek(0) can leave
            # the kernel offset after read-ahead; tar would see a truncated stream.
            plain = stack.enter_context(tempfile.TemporaryFile(dir=temp, buffering=0))
            aad = canonical(
                {
                    "project": manifest["project"],
                    "volume": item["logical"],
                    "file": item["file"],
                }
            )
            with protected_file(directory / item["file"]) as source:
                decrypt_stream(source, plain, key, aad, max_bytes=max_bytes)
            validate_tar(plain, max_bytes=max_bytes)
            validated.append(plain)
        deployment.stage = "restore_extract"
        for item, name, plain in zip(archives, names, validated, strict=True):
            # Do not let docker volume create silently reuse an existing name.
            is_bind = item.get("kind", "volume") == "bind"
            if is_bind:
                if any(Path(name).iterdir()):
                    raise OperationError("Bind target changed before extraction.")
            else:
                existing = (
                    deployment.run(
                        "docker", "volume", "ls", "-q", "--filter", f"name=^{name}$"
                    )
                    .decode()
                    .split()
                )
                if existing:
                    raise OperationError(
                        "Target volume already exists; refusing overwrite."
                    )
                deployment.run(
                    "docker",
                    "volume",
                    "create",
                    "--label",
                    f"com.docker.compose.project={deployment.project}",
                    "--label",
                    f"com.docker.compose.volume={item['logical']}",
                    name,
                )
            deployment.run(
                *deployment.helper_args(
                    manifest["images"]["api"]["id"], name, readonly=False, bind=is_bind
                ),
                stdin=plain,
                timeout=3600,
            )
    # Create only stores, never API/workers/gateway/lab. No migration on cold restore.
    deployment.stage = "restore_start_stores"
    deployment.compose(
        "up", "-d", "--no-deps", "--wait", "--wait-timeout", "180", *sorted(STORES)
    )
    deployment.assert_stopped(stores_allowed=True)
    deployment.stage = "restore_checkpoint"
    result = deployment.maintenance("checkpoint", wait_dependencies=True)
    if checkpoint and (
        result.get("schema") != checkpoint.get("schema")
        or result.get("reports") != checkpoint.get("reports")
        or result.get("model_references") != checkpoint.get("model_references")
        or result.get("neo4j_graph") != checkpoint["neo4j_graph"]
        or result.get("network_assets") != checkpoint.get("network_assets")
        or result.get("telemetry_archive") != checkpoint.get("telemetry_archive")
        or result.get("autonomous_execution") != checkpoint.get("autonomous_execution")
        or result.get("experimental_lab") != checkpoint.get("experimental_lab")
    ):
        raise OperationError(
            "Restored report/model/schema/Neo4j checkpoint differs; keep writers stopped."
        )
    deployment.stage = "restore_sessions"
    result = deployment.maintenance("restore-verify")
    return {
        "status": "restored_verified",
        "writers": "stopped",
        "resume": "manual; new login required; reconcile jobs before lab",
        "verification": result,
    }


def add_deployment_arguments(parser):
    parser.add_argument("--project", required=True)
    parser.add_argument("--compose-file", action="append", required=True)
    parser.add_argument("--env-file", required=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore", "verify"])
    add_deployment_arguments(parser)
    parser.add_argument(
        "--directory",
        type=Path,
        required=True,
        help="Existing empty 0700 directory for backup; backup directory otherwise",
    )
    parser.add_argument(
        "--encryption-key-file",
        type=Path,
        required=True,
        help="Separately stored operator-owned 0600 file containing exactly 32 random raw bytes",
    )
    parser.add_argument("--max-volume-bytes", type=int, default=100 * 1024**3)
    args = parser.parse_args()
    os.umask(0o077)
    stage, deployment = "arguments", None
    try:
        if not 1024 <= args.max_volume_bytes <= 1024**4:
            raise OperationError("Volume cap must be between 1 KiB and 1 TiB.")
        if args.encryption_key_file.resolve().is_relative_to(args.directory.resolve()):
            raise OperationError(
                "Encryption key must be stored outside the backup directory."
            )
        stage = "key"
        with protected_file(args.encryption_key_file, size=32) as source:
            key = source.read()
        if args.action == "verify":
            stage = "archive_validation"
            manifest = load_manifest(args.directory, key)
            for item in manifest["volumes"] + manifest.get("binds", []):
                with tempfile.TemporaryFile(
                    dir=private_directory(args.directory)
                ) as plain:
                    aad = canonical(
                        {
                            "project": manifest["project"],
                            "volume": item["logical"],
                            "file": item["file"],
                        }
                    )
                    with protected_file(args.directory / item["file"]) as source:
                        decrypt_stream(
                            source, plain, key, aad, max_bytes=args.max_volume_bytes
                        )
                    validate_tar(plain, max_bytes=args.max_volume_bytes)
            result = {"status": "authenticated", "volumes": len(manifest["volumes"])}
        else:
            stage = "configuration"
            deployment = Deployment(args.project, args.compose_file, args.env_file)
            deployment.diagnostic_dir = private_directory(args.directory.parent)
            result = (backup if args.action == "backup" else restore)(
                deployment, args.directory, key, max_bytes=args.max_volume_bytes
            )
        print(json.dumps(result, sort_keys=True))
    except (
        OperationError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        tarfile.TarError,
        ImportError,
    ) as exc:
        stage = getattr(deployment, "stage", stage)
        stage = stage if stage in STAGES else "arguments"
        print(
            json.dumps(
                {
                    "status": "refused",
                    "stage": stage,
                    "error_type": type(exc).__name__,
                    "reason": str(exc)
                    if isinstance(exc, OperationError)
                    else "Operation failed safely; inspect local configuration.",
                    "resume": "manual; no automatic restart or cleanup performed",
                }
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
