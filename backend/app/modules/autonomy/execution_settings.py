"""Protected explicit API journal-client installation; no privileged imports."""

import os
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import Field, model_serializer

from app.modules.autonomy.artifact_io import ArtifactRef, ArtifactStore, parse_json
from app.modules.autonomy.calibration_verification_models import CalibrationScope
from app.modules.autonomy.health_secret import legacy_hmac_enabled, read_health_secret
from app.modules.autonomy.registry import protected_path
from app.modules.autonomy.schemas import SHA256, Contract, contract_digest

CONFIG_PATH = "NANFO_AUTONOMOUS_PROVIDER_CONFIG"
CONFIG_HASH = "NANFO_AUTONOMOUS_PROVIDER_CONFIG_SHA256"

#: Re-verify the installed evidence at most this often per pinned configuration (fix 1).
REVERIFY_SECONDS = 60.0
#: While one thread re-verifies, others may use the previous result this much longer.
STALE_GRACE_SECONDS = 60.0


class ExecutionClientConfig(Contract):
    version: Literal["nanfo.autonomous-provider-installation/v1"]
    execution_mode: Literal["emulation"]
    evidence_root: str
    source_root: str
    calibration_path: str
    calibration_sha256: SHA256
    provider_path: str
    provider_sha256: SHA256
    expected_scope: CalibrationScope
    trusted_preregistrations: dict[SHA256, float]
    trusted_attesters: set[SHA256]
    accepted_guarantee_sha256: set[SHA256]
    accepted_runtime_sha256: set[SHA256]
    accepted_equivalence_sha256: set[SHA256]
    accepted_service_semantics_sha256: set[SHA256] = Field(default_factory=set)
    accepted_native_backlog_sha256: set[SHA256] = Field(default_factory=set)
    resource_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,200}$")
    # Legacy shared HMAC secret (C21). Read only when NANFO_RECEIVER_HEALTH_LEGACY_HMAC=true;
    # Ed25519 key files come from NANFO_RECEIVER_HEALTH_{PRIVATE,PUBLIC}_KEY_FILE instead.
    health_key: ArtifactRef | None = None
    health_max_age_seconds: int = Field(default=10, strict=True, ge=1, le=30)

    @model_serializer(mode="wrap")
    def preserve_existing_config_identity(self, handler):
        result = handler(self)
        for key in ("accepted_service_semantics_sha256", "accepted_native_backlog_sha256", "health_key"):
            if not getattr(self, key):
                result.pop(key, None)
        return result

    def load(self):
        from app.modules.autonomy.safety_installation import load_independently_validated_safety
        for root in (self.evidence_root, self.source_root):
            if not Path(root).is_absolute():
                raise ValueError("autonomous_paths_not_absolute")
            protected_path(Path(root))
        installation = load_independently_validated_safety(root=self.evidence_root,
            calibration_path=self.calibration_path, calibration_sha256=self.calibration_sha256,
            provider_path=self.provider_path, provider_sha256=self.provider_sha256,
            expected_scope=self.expected_scope, trusted_preregistrations=self.trusted_preregistrations,
            trusted_attesters=self.trusted_attesters, accepted_guarantee_sha256=self.accepted_guarantee_sha256,
            accepted_runtime_sha256=self.accepted_runtime_sha256,
            accepted_equivalence_sha256=self.accepted_equivalence_sha256, source_root=self.source_root,
            accepted_service_semantics_sha256=self.accepted_service_semantics_sha256,
            accepted_native_backlog_sha256=self.accepted_native_backlog_sha256)
        store = ArtifactStore(self.evidence_root)
        # The symmetric secret is never loaded unless the frozen-runtime legacy mode is on.
        key = (read_health_secret(self.evidence_root, self.health_key)
               if self.health_key is not None and legacy_hmac_enabled() else None)
        if installation.data.runtime_binding is not None:
            from app.modules.autonomy.frr_contract import FRRRuntimeBinding
            binding = FRRRuntimeBinding.model_validate(parse_json(store.referenced(installation.data.runtime_binding)))
            if binding.resource_id != self.resource_id:
                raise ValueError("receiver_resource_binding_mismatch")
        return installation, key


_VERIFIED: dict[str, tuple[float, object, object]] = {}
_VERIFIED_LOCK = threading.Lock()


def verified_installation(config, *, clock=time.monotonic):
    """``config.load()`` cached per canonical config digest; blocking — call off the event loop.

    Re-verifies every REVERIFY_SECONDS. A concurrent caller never queues behind a running
    verification: it reuses the previous result within the grace period, else fails closed.
    """
    digest = contract_digest(config)
    entry = _VERIFIED.get(digest)
    if entry is not None and clock() - entry[0] < REVERIFY_SECONDS:
        return entry[1], entry[2]
    if not _VERIFIED_LOCK.acquire(blocking=False):
        if entry is not None and clock() - entry[0] < REVERIFY_SECONDS + STALE_GRACE_SECONDS:
            return entry[1], entry[2]
        raise ValueError("autonomous_installation_verification_in_progress")
    try:
        try:
            installation, key = config.load()
        except Exception:
            _VERIFIED.pop(digest, None)
            raise
        while len(_VERIFIED) >= 4:
            _VERIFIED.pop(next(iter(_VERIFIED)))
        _VERIFIED[digest] = (clock(), installation, key)
        return installation, key
    finally:
        _VERIFIED_LOCK.release()


def clear_verified_installations():
    with _VERIFIED_LOCK:
        _VERIFIED.clear()


def configured():
    return bool(os.environ.get(CONFIG_PATH) or os.environ.get(CONFIG_HASH))


def load_config(path=None, expected_sha256=None):
    path = path or os.environ.get(CONFIG_PATH)
    expected_sha256 = expected_sha256 or os.environ.get(CONFIG_HASH)
    if not path or not expected_sha256 or not Path(path).is_absolute():
        raise ValueError("autonomous_provider_configuration_incomplete")
    path = Path(path)
    protected_path(path)
    return ExecutionClientConfig.model_validate_json(ArtifactStore(str(path.parent)).read(path.name, sha256=expected_sha256))
