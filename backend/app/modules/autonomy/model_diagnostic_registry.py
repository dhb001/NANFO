"""Operator-pinned ADR-018 model registry loader shared by the API and the confined runner.

Moved unchanged from ``scripts/frozen_model_diagnostic.py`` (ADR-028: application code
never imports ``scripts.*``). The confined runner executes under the operator-pinned AI
interpreter, so this module deliberately depends only on the standard library and the
pydantic-only autonomy artifact/schema modules.
"""

import os
import re
import stat
from pathlib import Path

from app.modules.autonomy.artifact_io import ArtifactStore, EvidenceError, parse_json
from app.modules.autonomy.model_diagnostic_schemas import ModelDiagnosticRegistry

CONFIG_KEYS = ("NANFO_MODEL_REGISTRY", "NANFO_MODEL_REGISTRY_SHA256", "NANFO_MODEL_ROOT", "NANFO_MODEL_PYTHON")

#: Per-network frozen-runtime admission (ADR-028 C26): diagnostics and live inference of the
#: same network never overlap; other networks and tenants are never refused because of it.
_NETWORK_LOCK_PREFIX = "nanfo:autonomy:model-diagnostics:inference:"


def diagnostic_lock_key(network_id) -> str:
    return f"{_NETWORK_LOCK_PREFIX}{network_id}"


def load_registry():
    if not all(os.environ.get(key) for key in CONFIG_KEYS):
        raise EvidenceError("model_registry_unconfigured")
    path = Path(os.environ["NANFO_MODEL_REGISTRY"])
    root = Path(os.environ["NANFO_MODEL_ROOT"])
    pin = os.environ["NANFO_MODEL_REGISTRY_SHA256"]
    if not path.is_absolute() or not root.is_absolute() or not re.fullmatch(r"[a-f0-9]{64}", pin):
        raise EvidenceError("model_registry_configuration_invalid")
    if path.resolve().is_relative_to(root.resolve()):
        raise EvidenceError("registry_inside_producer_root")
    for component in (path, *path.parents):
        info = component.lstat()
        # A root-owned sticky /tmp is safe for a privately owned child directory.
        sticky_root = component != path and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
        if stat.S_ISLNK(info.st_mode) or (info.st_mode & 0o022 and not sticky_root):
            raise EvidenceError("model_registry_not_protected")
        if info.st_uid not in (0, os.geteuid()):
            raise EvidenceError("model_registry_owner_invalid")
    content = ArtifactStore(str(path.parent)).read(path.name, limit=256 * 1024, sha256=pin)
    return ModelDiagnosticRegistry.model_validate(parse_json(content)), pin, ArtifactStore(str(root))


def select_model(registry, network_id):
    return next((model for model in registry.models if network_id in model.network_ids), None)
