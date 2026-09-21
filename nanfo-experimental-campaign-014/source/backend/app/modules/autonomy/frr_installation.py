"""Protected runtime equivalence admission and actual source fingerprint checks."""

import hashlib
from pathlib import Path
import time

from app.modules.autonomy.artifact_io import ArtifactStore, parse_json
from app.modules.autonomy.frr_contract import FRRRuntimeBinding

RECEIVER_SOURCES = frozenset({
    "emulation/autonomous_contract.py", "backend/app/modules/autonomy/health_secret.py",
    "emulation/autonomous_frr.py", "emulation/autonomous_namespace.py", "emulation/autonomous_causal.py",
    "emulation/autonomous_receiver.py", "emulation/autonomous_driver.py",
    "backend/app/modules/autonomy/frr_contract.py", "backend/app/modules/autonomy/frr_installation.py",
    "backend/app/modules/autonomy/causal_frames.py", "backend/app/modules/autonomy/safety_provider.py",
    "backend/app/modules/autonomy/safety_installation.py", "backend/app/modules/autonomy/execution.py",
    "backend/app/modules/autonomy/execution_authority.py", "backend/app/modules/autonomy/execution_contract.py",
    "backend/app/modules/autonomy/execution_repository.py", "backend/scripts/autonomous_frr_receiver.py",
    "backend/app/modules/autonomy/safety.py", "backend/app/modules/autonomy/schemas.py",
    "backend/app/modules/autonomy/provider_state.py", "backend/app/modules/autonomy/execution_models.py",
    "backend/app/modules/autonomy/calibration_verification.py", "backend/app/modules/autonomy/calibration_verification_models.py",
    "backend/app/modules/autonomy/artifact_io.py", "backend/app/modules/autonomy/registry.py",
    "backend/app/modules/autonomy/model_provider.py", "backend/scripts/frozen_live_inference.py",
    "backend/app/modules/autonomy/execution_client.py", "backend/app/modules/autonomy/execution_settings.py",
    "backend/app/modules/autonomy/receiver_health.py", "backend/app/modules/autonomy/providers.py",
})
FROZEN_SOURCES = frozenset({"emulation/matched.py", "emulation/ospf.py", "emulation/topology.py",
    "emulation/workloads.py", "emulation/measurements.py", "emulation/actions.py", "emulation/runner.py"})


def runtime_sources(root):
    """Actual bytes; additional isolated source map never rewrites the frozen spec."""
    store = ArtifactStore(str(Path(root).resolve()))
    return {path: hashlib.sha256(store.read(path, limit=4 * 1024**2)).hexdigest()
            for path in sorted(RECEIVER_SOURCES | FROZEN_SOURCES)}


def validate_runtime_binding(data, evidence, *, accepted_runtime_sha256, accepted_equivalence_sha256,
                             store, source_root, now=None):
    ref = data.runtime_binding
    if ref is None or ref.sha256 not in accepted_runtime_sha256:
        raise ValueError("frr_runtime_not_independently_accepted")
    if hashlib.sha256(evidence[ref.path]).hexdigest() != ref.sha256:
        raise ValueError("frr_runtime_evidence_hash_mismatch")
    binding = FRRRuntimeBinding.model_validate(parse_json(evidence[ref.path]))
    if (binding.reviewed_equivalence.sha256 not in accepted_equivalence_sha256
            or binding.network_id != data.network_id or binding.workspace_id != data.workspace_id
            or binding.run_id != data.calibration.run_id or binding.provider_id != data.calibration.provider_id
            or binding.configuration_sha256 != data.configuration_sha256
            or data.checkpoints != [binding.checkpoint_sha256]
            or not binding.valid_from <= (time.time() if now is None else now) < binding.valid_until
            or binding.valid_until < data.calibration.valid_until_unix_seconds
            or set(binding.action_ids) != {a.action_id for a in data.actions}):
        raise ValueError("frr_runtime_independent_scope_mismatch")
    store.referenced(binding.reviewed_equivalence)
    actual = runtime_sources(source_root)
    if (set(binding.receiver_sources) != RECEIVER_SOURCES or set(binding.frozen_sources) != FROZEN_SOURCES
            or binding.receiver_sources != {p: actual[p] for p in RECEIVER_SOURCES}
            or binding.frozen_sources != {p: actual[p] for p in FROZEN_SOURCES}):
        raise ValueError("frr_runtime_source_fingerprint_mismatch")
    for action in data.actions:
        if binding.action_ids[action.plan.action] != action.action_id:
            raise ValueError("frr_runtime_action_identity_mismatch")
    return binding


def validate_model_binding(binding, model_installation):
    """Checks identity only. Existing FrozenModelProvider still performs qualification."""
    model, manifest = model_installation.model, model_installation.manifest
    spec = manifest.get("environment_spec", {})
    historical_sources = spec.get("source_files", {})
    if (model.runtime_action != "linux-frr-host-route" or model.checkpoint.sha256 != binding.checkpoint_sha256
            or model.contract_sha256 != binding.model_contract_sha256 or model.spec_sha256 != binding.model_spec_sha256
            or model.action_ids != binding.action_ids
            or manifest["contract"]["action_map"] != [binding.actions["0"], binding.actions["1"]]
            or spec.get("version") != 4
            or any(historical_sources.get(path.removeprefix("emulation/")) != digest
                   for path, digest in binding.frozen_sources.items())):
        raise ValueError("frr_model_runtime_identity_mismatch")
