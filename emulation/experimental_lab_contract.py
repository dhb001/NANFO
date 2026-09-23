"""ADR025 private receiver wire contract (stdlib, also runs in frozen Python3.9)."""

import hashlib
import json
import math
import os
import re
import stat
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

VERSION = "nanfo.experimental-lab/v1"
POLICY_VERSION = "nanfo.experimental-receiver-policy/v1"
IMAGE = "sha256:954462c0f00d5bbaa72ea144f6064936b399c430e6ab94bffcf1c00d134ea0d7"
SOURCE = "08c312c64154c9aedcd3b22eeb3573783590e0eb7183bc999cb8ef39b958dbbd"
MODEL = "77dae44acab722a5a6a2e87d952a6cca65e1c4eea102a089830a8401b521d614"
REQUEST_LIMIT = 8192
RESPONSE_LIMIT = 2 * 1024 * 1024
OPERATIONS = ("bootstrap", "bind", "observe", "execute", "verify", "restore", "status", "stop", "recover", "heartbeat")


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def snapshot(value):
    """Detached JSON value: no mutable runtime references cross evidence boundaries."""
    return json.loads(canonical(value))


def decode(raw, limit=REQUEST_LIMIT):
    require(len(raw) <= limit, "message_too_large")

    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: require(False, "nonfinite_json"))


class ProtectedReadError(ValueError):
    """Finite metadata only; never exception paths or protected file contents."""

    def __init__(self, reason, role, stage, attempt, opened=None, current=None):
        super().__init__(reason)
        def metadata(info):
            return None if info is None else dict(device=info.st_dev, inode=info.st_ino,
                mode=stat.S_IMODE(info.st_mode), regular=stat.S_ISREG(info.st_mode),
                uid=info.st_uid, links=info.st_nlink)
        self.diagnostic = dict(reason=reason, file_role=role, stage=stage, attempt=attempt,
                               opened=metadata(opened), current=metadata(current))


def _identity(info):
    return info.st_dev, info.st_ino


def _private_regular(info, *, unlinked=False):
    return (stat.S_ISREG(info.st_mode) and not info.st_mode & 0o077
            and info.st_uid == os.geteuid() and info.st_nlink in ((0, 1) if unlinked else (1,)))


@contextmanager
def _protected_parent(path):
    """Anchor every component with no-follow directory descriptors, including retries."""
    descriptors, bindings = [], []
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        for name in path.parts[1:-1]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(child)
            bindings.append((fd, name, child))
            fd = child

        def validate():
            for directory in descriptors:
                info = os.fstat(directory)
                require(info.st_uid in (0, os.geteuid()), "foreign_directory_owner")
                require(not info.st_mode & 0o022 or (bool(info.st_mode & stat.S_ISVTX)
                        and info.st_uid == 0), "writable_ancestor")
            leaf = os.fstat(fd)
            require(leaf.st_uid == os.geteuid() and not leaf.st_mode & 0o077,
                    "private_receiver_directory_required")
            for parent, name, child in bindings:
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                require(stat.S_ISDIR(current.st_mode) and _identity(current) == _identity(os.fstat(child)),
                        "protected_directory_changed")
        validate()
        yield fd, validate
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def protected_read(path, limit=REQUEST_LIMIT):
    path = Path(path)
    role = path.name if path.name in {"authority.json", "bootstrap-admission.json", "policy.json",
        "receiver-policy.json", "controller-binding.json", "checkpoint-response.json"} else "other"
    stage, attempt, opened, current = "path", 0, None, None
    try:
        require(path.is_absolute() and ".." not in path.parts, "absolute_path_required")
        with _protected_parent(path) as (parent, validate):
            for index in range(3):
                attempt = index + 1
                opened = current = None
                stage = "open"
                fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    stage = "fd_metadata"
                    opened = os.fstat(fd)
                    require(_private_regular(opened, unlinked=True), "protected_regular_owner_file_required")
                    # Never consume an unlinked inode, even one created by our publisher.
                    raw = os.read(fd, limit + 1) if opened.st_nlink == 1 else None
                    after = os.fstat(fd)
                    require(_private_regular(after, unlinked=True), "protected_regular_owner_file_required")
                    stage = "path_metadata"
                    current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                    require(_private_regular(current), "protected_regular_owner_file_required")
                    validate()
                    if _identity(current) != _identity(after):
                        # Only a safely owned old inode unlinked by replacement can retry.
                        after = os.fstat(fd)
                        require(_private_regular(after, unlinked=True), "protected_regular_owner_file_required")
                        require(after.st_nlink == 0, "protected_file_identity_changed")
                        continue
                    require(opened.st_nlink == after.st_nlink == 1 and raw is not None,
                            "protected_regular_owner_file_required")
                    require((opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) ==
                            (after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                            (current.st_size, current.st_mtime_ns, current.st_ctime_ns),
                            "protected_file_changed_in_place")
                    require(len(raw) <= limit, "file_too_large")
                    return raw
                finally:
                    os.close(fd)
            raise ValueError("protected_replacement_retry_exhausted")
    except (ValueError, OSError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "protected_path_unavailable"
        raise ProtectedReadError(reason, role, stage, attempt, opened, current) from None


def atomic_write(path, value):
    path = Path(path)
    info = path.parent.lstat()
    require(stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o077
            and info.st_uid == os.geteuid(), "private_receiver_directory_required")
    fd, temporary = tempfile.mkstemp(prefix=".experimental-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


@dataclass(frozen=True)
class Request:
    version: str
    request_id: str
    fence: int
    policy_sha256: str
    expires_at: float
    operation: str
    action: object
    duration_seconds: float
    token: str

    @classmethod
    def parse(cls, raw):
        value = decode(raw)
        require(type(value) is dict and set(value) == set(cls.__dataclass_fields__),
                "exact_request_fields_required")
        require(value["version"] == VERSION, "wrong_version")
        require(str(uuid.UUID(value["request_id"])) == value["request_id"], "invalid_request_id")
        require(type(value["fence"]) is int and 0 < value["fence"] < 2**63, "invalid_fence")
        require(type(value["policy_sha256"]) is str
                and re.fullmatch(r"[a-f0-9]{64}", value["policy_sha256"]), "invalid_policy_hash")
        require(number(value["expires_at"], 1, 1e11), "invalid_expiry")
        require(value["operation"] in OPERATIONS, "invalid_operation")
        action = value["action"]
        require((type(action) is int and action in (0, 1))
                if value["operation"] == "execute" else action is None, "invalid_action")
        require(number(value["duration_seconds"], 0, 120), "invalid_duration")
        require(value["operation"] != "execute" or value["duration_seconds"] > 0, "zero_execute_duration")
        require(value["operation"] == "execute" or value["duration_seconds"] == 0,
                "duration_only_for_execute")
        require(type(value["token"]) is str and re.fullmatch(r"[a-f0-9]{64}", value["token"]),
                "invalid_token")
        return cls(**value)

    def public(self):
        return {key: value for key, value in self.__dict__.items() if key != "token"}


def load_policy(path, sha256):
    raw = protected_read(path)
    require(hashlib.sha256(raw).hexdigest() == sha256, "policy_hash_mismatch")
    value = decode(raw)
    fields = {"version", "image_id", "source_sha256", "model_sha256", "container_id",
              "owner_label", "seed", "scenario", "expires_at", "max_duration_seconds",
              "heartbeat_seconds", "min_dwell_seconds", "max_observation_age_seconds",
              "min_goodput_mbps", "max_loss_fraction", "max_rtt_ms", "wrapper_sha256",
              "controller_policy_sha256"}
    require(type(value) is dict and set(value) == fields, "exact_policy_fields_required")
    require(value["version"] == POLICY_VERSION and value["image_id"] == IMAGE
            and value["source_sha256"] == SOURCE and value["model_sha256"] == MODEL,
            "unqualified_runtime_or_model")
    require(re.fullmatch(r"[a-f0-9]{64}", value["container_id"]), "invalid_container_id")
    require(re.fullmatch(r"[a-f0-9]{64}", value["wrapper_sha256"]), "invalid_wrapper_hash")
    require(value["controller_policy_sha256"] is None or
            re.fullmatch(r"[a-f0-9]{64}", value["controller_policy_sha256"]), "invalid_controller_policy_hash")
    require(re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", value["owner_label"]), "invalid_owner_label")
    require(type(value["seed"]) is int and 0 <= value["seed"] <= 2147483647, "invalid_seed")
    require(value["scenario"] in ("path0", "path1"), "invalid_scenario")
    for key, low, high in (("expires_at", 1, 1e11), ("max_duration_seconds", 2, 120),
                           ("heartbeat_seconds", 2, 60), ("min_dwell_seconds", 0, 120),
                           ("max_observation_age_seconds", 1, 30),
                           ("min_goodput_mbps", 0, 20), ("max_loss_fraction", 0, 1),
                           ("max_rtt_ms", 0, 1000)):
        require(number(value[key], low, high), "invalid_policy_" + key)
    require(value["min_dwell_seconds"] <= value["max_duration_seconds"], "invalid_dwell")
    return value


def wrapper_digest():
    return digest({name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                   for name in ("experimental_lab_contract.py", "experimental_lab_runtime.py",
                                "experimental_lab_receiver.py")})
