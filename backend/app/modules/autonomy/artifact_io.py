"""Bounded read-only operator evidence. Digests bind bytes, not physical truth."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
MAX_JSON = 4 * 1024 * 1024
MAX_ARTIFACT = 64 * 1024 * 1024


class EvidenceError(ValueError):
    """Only stable non-sensitive reason codes cross the operator CLI boundary."""


class StrictEvidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        revalidate_instances="always",
    )


class ArtifactRef(StrictEvidence):
    path: str = Field(min_length=1, max_length=512)
    sha256: SHA256
    size_bytes: int = Field(ge=1, le=MAX_ARTIFACT)


def parse_json(content: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise EvidenceError("duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise EvidenceError("nonfinite_json_number")

    def validate(value, depth=0):
        if depth > 24:
            raise EvidenceError("json_depth_exceeded")
        if isinstance(value, (dict, list)):
            if len(value) > 10000:
                raise EvidenceError("json_collection_bound_exceeded")
            for item in value.values() if isinstance(value, dict) else value:
                validate(item, depth + 1)

    try:
        value = json.loads(
            content, object_pairs_hook=pairs, parse_constant=invalid_constant
        )
        validate(value)
        # Also rejects finite JSON syntax such as 1e999 becoming Python infinity.
        json.dumps(value, allow_nan=False)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("invalid_json") from exc


class ArtifactStore:
    """Allowlist root is deployment configuration, never a request/artifact field.

    Every path component is opened relative to a directory descriptor with
    O_NOFOLLOW. A rename/symlink swap cannot redirect traversal outside the root.
    Content is consumed from the same descriptor that is hashed and stat-checked.
    """

    def __init__(self, root: str):
        if not os.path.isabs(root):
            raise EvidenceError("artifact_root_must_be_absolute")
        self.root = root

    @classmethod
    def from_environment(cls):
        root = os.environ.get("NANFO_AUTONOMY_ARTIFACT_ROOT")
        if not root:
            raise EvidenceError("operator_artifact_root_unconfigured")
        return cls(root)

    def read(
        self,
        path: str,
        *,
        limit=MAX_JSON,
        sha256=None,
        size_bytes=None,
        allow_empty=False,
    ) -> bytes:
        if not isinstance(path, str) or not 1 <= len(path) <= 512 or "\x00" in path:
            raise EvidenceError("artifact_path_not_allowed")
        parts = PurePosixPath(path).parts
        if (
            not parts
            or len(parts) > 32
            or path.startswith("/")
            or "\\" in path
            or any(part in {".", ".."} for part in path.split("/"))
            or str(PurePosixPath(path)) != path
        ):
            raise EvidenceError("artifact_path_not_allowed")
        if not 1 <= limit <= MAX_ARTIFACT:
            raise EvidenceError("artifact_limit_invalid")
        descriptors = []
        try:
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(directory)
            for part in parts[:-1]:
                directory = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                descriptors.append(directory)
            fd = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
            )
            descriptors.append(fd)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise EvidenceError("artifact_not_regular_file")
            if not (0 if allow_empty else 1) <= before.st_size <= limit:
                raise EvidenceError("artifact_size_out_of_bounds")
            if size_bytes is not None and before.st_size != size_bytes:
                raise EvidenceError("artifact_size_mismatch")
            with os.fdopen(os.dup(fd), "rb") as source:
                content = source.read(limit + 1)
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) or len(content) != before.st_size:
                raise EvidenceError("artifact_changed_during_read")
            if sha256 is not None and hashlib.sha256(content).hexdigest() != sha256:
                raise EvidenceError("artifact_hash_mismatch")
            return content
        except FileNotFoundError as exc:
            raise EvidenceError("artifact_missing") from exc
        except OSError as exc:
            raise EvidenceError("artifact_unreadable_or_symlink") from exc
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    def referenced(self, ref: ArtifactRef, *, limit=MAX_JSON):
        return self.read(
            ref.path, limit=limit, sha256=ref.sha256, size_bytes=ref.size_bytes
        )

    def document(self, path: str, *, sha256=None):
        return parse_json(self.read(path, sha256=sha256))
