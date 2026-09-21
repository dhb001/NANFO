"""Protected installation and passive snapshot admission. Never imports AI packages."""

import hashlib
import io
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.modules.autonomy.artifact_io import ArtifactStore, EvidenceError, parse_json
from app.modules.autonomy.live_schemas import LiveInstallation, MeasuredFeatures, PassiveSnapshot
from app.modules.autonomy.live_settings import LiveSettings
from app.modules.autonomy.qualification import inspect_checkpoint_bytes
from scripts.frozen_model_diagnostic import canonical_hash


def protected_path(path: Path):
    for component in (path, *path.parents):
        info = component.lstat()
        sticky_root = component != path and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
        if (stat.S_ISLNK(info.st_mode) or (info.st_mode & 0o022 and not sticky_root)
                or info.st_uid not in (0, os.geteuid())):
            raise EvidenceError("live_operator_path_not_protected")


@dataclass(frozen=True)
class Installation:
    model: LiveInstallation
    sha256: str
    manifest: dict
    checkpoint: bytes
    sources: dict[str, bytes]
    parent_checkpoint: bytes | None = None


def validate_rebuilt_lineage(checkpoint, parent_checkpoint):
    """Only truthful image provenance may differ, not even optimizer/RNG bytes."""
    derived = inspect_checkpoint_bytes(checkpoint)
    parent = inspect_checkpoint_bytes(parent_checkpoint)
    before, after = parent["lab_provenance"], derived["lab_provenance"]
    image = after.get("lab_image_id", "")
    if (not re.fullmatch(r"sha256:[0-9a-f]{64}", image)
            or image == before.get("lab_image_id")
            or {k: v for k, v in derived.items() if k != "lab_provenance"}
            != {k: v for k, v in parent.items() if k != "lab_provenance"}
            or after != before | {"lab_image_id": image}):
        raise EvidenceError("live_rebuilt_parent_manifest_mismatch")
    with zipfile.ZipFile(io.BytesIO(checkpoint)) as left, zipfile.ZipFile(io.BytesIO(parent_checkpoint)) as right:
        if left.read("weights.pt") != right.read("weights.pt"):
            raise EvidenceError("live_rebuilt_parent_tensor_bytes_mismatch")
    return parent


class LiveRegistry:
    def __init__(self, settings=None):
        self.settings = settings

    @classmethod
    def from_environment(cls):
        # Defer invalid-config errors to provider results rather than API import/startup.
        return cls()

    def configuration(self):
        return self.settings or LiveSettings.from_environment()

    def load(self, *, now=None):
        settings = self.configuration()
        path = Path(settings.registry_path)
        protected_path(path)
        if (not re.fullmatch(r"[a-f0-9]{64}", settings.registry_sha256)
                or path.resolve().is_relative_to(Path(settings.artifact_root).resolve())
                or path.resolve().is_relative_to(Path(settings.observation_root).resolve())):
            raise EvidenceError("live_registry_configuration_invalid")
        content = ArtifactStore(str(path.parent)).read(path.name, limit=256 * 1024, sha256=settings.registry_sha256)
        model = LiveInstallation.model_validate(parse_json(content))
        now = now or datetime.now(UTC)
        if not model.installed_at <= now < model.expires_at:
            raise EvidenceError("live_installation_expired_or_future")
        store = ArtifactStore(settings.artifact_root)
        checkpoint = store.referenced(model.checkpoint, limit=16 * 1024**2)
        manifest = inspect_checkpoint_bytes(checkpoint)
        parent_checkpoint = None
        if model.parent_checkpoint is not None:
            parent_checkpoint = store.referenced(model.parent_checkpoint, limit=16 * 1024**2)
            validate_rebuilt_lineage(checkpoint, parent_checkpoint)
        if (manifest["client_source_files"] != model.source_sha256
                or manifest["contract_hash"] != model.contract_sha256
                or manifest["spec_hash"] != model.spec_sha256
                or manifest["versions"] != model.runtime_versions
                or manifest["environment_spec"].get("version") != 4
                or manifest["contract"].get("state_dim") != 16
                or manifest["contract"].get("history_length") != 1):
            raise EvidenceError("live_model_contract_or_source_mismatch")
        sources = {name: store.read(f"{model.source_directory}/{name}", limit=1024**2,
                                   sha256=digest, allow_empty=True) for name, digest in model.source_sha256.items()}
        if not {"__init__.py", "artifacts.py", "cli.py", "contracts.py", "evidence.py", "env.py"} <= sources.keys():
            raise EvidenceError("live_model_source_incomplete")
        return Installation(model, settings.registry_sha256, manifest, checkpoint, sources, parent_checkpoint)

    def benchmark_bytes(self, installation):
        model = installation.model
        store = ArtifactStore(self.configuration().artifact_root)
        refs = [model.plan, model.selection, model.report,
                *(ref for session in model.sessions for ref in (session.summary, session.evidence, session.attachment) if ref),
                *([model.lineage, model.seed_audit] if model.lineage else [])]
        if sum(ref.size_bytes for ref in refs) > 64 * 1024**2:
            raise EvidenceError("live_benchmark_total_bytes_exceeded")
        return {ref.path: store.referenced(ref, limit=64 * 1024**2) for ref in refs}

    def snapshot(self, installation, network_id, workspace_id, *, expected_hash=None, now=None):
        model = installation.model
        scope = next((scope for scope in model.scopes if scope.network_id == network_id
                      and scope.workspace_id == workspace_id), None)
        if scope is None:
            raise EvidenceError("live_observation_scope_unregistered")
        root = Path(self.configuration().observation_root)
        # ArtifactStore rejects traversal/symlinks. Protection is also required of the
        # dynamic producer file: its content is an explicit operator attestation.
        content = ArtifactStore(str(root)).read(scope.snapshot_path, sha256=expected_hash)
        protected_path(root / scope.snapshot_path)
        snapshot = PassiveSnapshot.model_validate(parse_json(content))
        now = now or datetime.now(UTC)
        if (snapshot.network_id != network_id or snapshot.workspace_id != workspace_id
                or snapshot.contract_sha256 != model.contract_sha256 or snapshot.spec_sha256 != model.spec_sha256):
            raise EvidenceError("live_observation_scope_or_contract_mismatch")
        if not (0 <= (now - snapshot.observed_at).total_seconds() <= model.max_observation_age_seconds
                and snapshot.observed_at <= snapshot.published_at <= now):
            raise EvidenceError("live_observation_stale_or_future")
        if canonical_hash(snapshot.history) != snapshot.history_sha256:
            raise EvidenceError("live_observation_history_hash_mismatch")
        history = snapshot.history
        if (set(history) != {"version", "frames"} or type(history["version"]) is not int
                or history["version"] != 3 or not isinstance(history["frames"], list) or len(history["frames"]) != 1):
            raise EvidenceError("live_observation_full_history_required")
        try:
            frame = history["frames"][0]
            data = frame["response"]["data"]
            if data["episode_id"] != str(snapshot.run_id):
                raise EvidenceError("live_observation_run_mismatch")
            if (data["scenario"] not in ("path0", "path1") or data["mode"] != "matched"
                    or frame["request"]["window_seconds"] != 2.0
                    or frame["request"]["episode_steps"] != 4):
                raise EvidenceError("live_observation_outside_benchmark_scope")
            # Reject missing features here as well as in the original frozen validator.
            MeasuredFeatures.model_validate(data["observation"])
        except (KeyError, TypeError, IndexError) as exc:
            raise EvidenceError("live_observation_full_history_required") from exc
        return snapshot, hashlib.sha256(content).hexdigest()
