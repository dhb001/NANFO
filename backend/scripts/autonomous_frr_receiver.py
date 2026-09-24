"""Explicit ADR023 attached-namespace receiver tooling. Never creates a lab.

Run from backend via python -m scripts.autonomous_frr_receiver. check/fingerprint/
provision only validate/print; acquire reads explicitly handed-off namespaces;
serve processes already committed autonomous work under current server authority.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Literal

from pydantic import Field, model_serializer

# Match the repository's standalone backend/emulation packaging layout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.modules.autonomy.artifact_io import ArtifactStore, parse_json
from app.modules.autonomy.causal_frames import CausalConfig, register_causal_frame
from app.modules.autonomy.calibration_verification_models import CalibrationScope
from app.modules.autonomy.execution import build_execution_providers
from app.modules.autonomy.frr_contract import FRRRuntimeBinding
from app.modules.autonomy.frr_installation import runtime_sources, validate_model_binding
from app.modules.autonomy.registry import LiveRegistry, protected_path
from app.modules.autonomy.safety_installation import load_independently_validated_safety
from app.modules.autonomy.safety_provider import ValidatedInstallation
from app.modules.autonomy.schemas import SHA256, Contract, Observation, contract_digest
from emulation.autonomous_causal import acquire_window, provision_rules
from emulation.autonomous_driver import finish_thread
from emulation.autonomous_frr import LinuxFRRDriver
from emulation.autonomous_namespace import AttachedFRRNetwork


class ReceiverConfig(Contract):
    version: Literal["nanfo.frr-receiver-installation/v1"]
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
    instrument_path: str
    instrument_sha256: SHA256
    accepted_instrument_sha256: set[SHA256]
    lock_directory: str
    actual_receiver_image_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_serializer(mode="wrap")
    def preserve_existing_config_identity(self, handler):
        result = handler(self)
        for key in ("accepted_service_semantics_sha256", "accepted_native_backlog_sha256"):
            if not getattr(self, key):
                result.pop(key, None)
        return result


def load_config(path, sha256):
    path = Path(path)
    protected_path(path)
    return ReceiverConfig.model_validate_json(ArtifactStore(str(path.parent)).read(path.name, sha256=sha256))


def admit(config):
    for path in (config.evidence_root, config.source_root, config.lock_directory):
        protected_path(Path(path))
    installation = load_independently_validated_safety(root=config.evidence_root,
        calibration_path=config.calibration_path, calibration_sha256=config.calibration_sha256,
        provider_path=config.provider_path, provider_sha256=config.provider_sha256,
        expected_scope=config.expected_scope, trusted_preregistrations=config.trusted_preregistrations,
        trusted_attesters=config.trusted_attesters, accepted_guarantee_sha256=config.accepted_guarantee_sha256,
        accepted_runtime_sha256=config.accepted_runtime_sha256, accepted_equivalence_sha256=config.accepted_equivalence_sha256,
        source_root=config.source_root,
        accepted_service_semantics_sha256=config.accepted_service_semantics_sha256,
        accepted_native_backlog_sha256=config.accepted_native_backlog_sha256)
    if installation.data.runtime_binding is None:
        raise ValueError("frr_runtime_required")
    store = ArtifactStore(config.evidence_root)
    binding = FRRRuntimeBinding.model_validate(parse_json(store.referenced(installation.data.runtime_binding)))
    instrument = CausalConfig.model_validate(parse_json(store.read(config.instrument_path, sha256=config.instrument_sha256)))
    if (binding.receiver_image_id != config.actual_receiver_image_id
            or instrument.runtime_binding_sha256 != installation.data.runtime_binding.sha256
            or instrument.configuration_sha256 != binding.configuration_sha256
            or instrument.network_id != binding.network_id or instrument.workspace_id != binding.workspace_id
            or instrument.run_id != binding.run_id
            or contract_digest(instrument) not in config.accepted_instrument_sha256
            or instrument.guarantee_sha256 not in config.accepted_guarantee_sha256
            or {e.egress_id for e in instrument.egresses} != set(installation.data.calibration.egress_ids)
            or {d.demand_id for d in instrument.demands} != set(installation.data.calibration.demand_ids)):
        raise ValueError("frr_instrument_runtime_scope_mismatch")
    reviewed = installation.data.execution
    if reviewed is None:
        raise ValueError("independent_physical_instrument_mapping_missing")
    for egress in instrument.egresses:
        physical = reviewed.egresses[egress.egress_id]
        if (egress.node, egress.interface, egress.leaf_handle, egress.source, egress.destination) != (
                physical.node, physical.interface, physical.queue_handle, physical.source, physical.destination):
            raise ValueError("instrument_physical_egress_differs_from_reviewed_calibration")
    for demand in instrument.demands:
        physical = reviewed.demands[demand.demand_id]
        if (demand.source, demand.destination, str(demand.source_ipv4), str(demand.destination_ipv4)) != (
                physical.source, physical.destination, physical.source_address, physical.destination_address):
            raise ValueError("instrument_physical_demand_differs_from_reviewed_calibration")
    return installation, binding, instrument


def recovery_material(config):
    """Read pinned historical material without granting any new dispatch authority.

    Recovery uses durable accepted command equality and source/namespace identity;
    an expired guarantee or revoked model must not strand exact compensation.
    """
    store = ArtifactStore(config.evidence_root)
    content = store.read(config.provider_path, sha256=config.provider_sha256)
    installation = ValidatedInstallation(content, config.provider_sha256)
    ref = installation.data.runtime_binding
    if ref is None or ref.sha256 not in config.accepted_runtime_sha256:
        raise ValueError("recovery_runtime_identity_not_installed")
    binding = FRRRuntimeBinding.model_validate(parse_json(store.referenced(ref)))
    actual = runtime_sources(config.source_root)
    if ({**binding.frozen_sources, **binding.receiver_sources} != actual
            or binding.receiver_image_id != config.actual_receiver_image_id
            or binding.run_id != installation.data.calibration.run_id
            or binding.network_id != installation.data.network_id or binding.workspace_id != installation.data.workspace_id):
        raise ValueError("recovery_source_or_scope_changed")
    return installation, binding


def publish_new(path, value):
    """Exclusive raw evidence publication, no silent overwrite of a previous run."""
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


async def operate(args, config):
    for path in (config.evidence_root, config.source_root, config.lock_directory):
        protected_path(Path(path))
    if args.command == "recover":
        from app.db.postgres import AsyncSessionLocal
        from app.db.redis import close_redis, get_redis_client, init_redis
        from app.modules.autonomy.execution_repository import ExecutionRepository
        from app.modules.autonomy.schemas import ExecutionReference
        import uuid

        installation, binding = recovery_material(config)
        network = AttachedFRRNetwork(binding, lock_directory=config.lock_directory)
        async def deny_dispatch(_):
            raise ValueError("recovery_only_no_new_execution")
        try:
            driver = LinuxFRRDriver(network, resource_id=binding.resource_id, run_id=binding.run_id,
                binding_sha256=installation.data.runtime_binding.sha256, ownership_check=network.ownership,
                dispatch_guard=deny_dispatch, baseline_action=binding.baseline_action)
            await init_redis()
            try:
                executor, _ = build_execution_providers(AsyncSessionLocal, get_redis_client(), installation,
                    driver, binding.resource_id, execution_mode="emulation")
                async with AsyncSessionLocal() as db:
                    row = await ExecutionRepository(db).get(uuid.UUID(args.execution_id), lock=True)
                    if (row is None or row.resource_id != binding.resource_id
                            or row.command["installation_sha256"] != installation.sha256):
                        raise ValueError("recovery_exact_execution_missing")
                    auth = row.command["authorization"]
                    reference = ExecutionReference(**{key: auth[key] for key in (
                        "network_id", "workspace_id", "intent_id", "execution_id", "decision_id", "control_revision", "claim_token")})
                    if row.released:
                        return {"status": "already_released"}
                    row.cancel_requested = True
                    await db.commit()
                await executor.run_one(execution_id=reference.execution_id, recovery_only=True)
                return (await executor.verify(reference)).model_dump(mode="json")
            finally:
                await close_redis()
        finally:
            network.close()
    if args.command == "provision":
        # Acquisition instrumentation precedes calibration. No invented circular
        # prerequisite for a completed campaign; this command prints only a recipe.
        instrument = CausalConfig.model_validate(parse_json(ArtifactStore(config.evidence_root).read(
            config.instrument_path, sha256=config.instrument_sha256)))
        if contract_digest(instrument) not in config.accepted_instrument_sha256:
            raise ValueError("instrument_recipe_not_explicitly_accepted")
        return {"apply": False, "nft_transactions": provision_rules(instrument.model_dump(mode="json"))}
    if args.command == "acquire":
        # Measurement acquisition needs protected namespace/instrument pins, not
        # a safety guarantee inferred from measurements that have not happened.
        store = ArtifactStore(config.evidence_root)
        provider = parse_json(store.read(config.provider_path, sha256=config.provider_sha256))
        from app.modules.autonomy.artifact_io import ArtifactRef
        runtime_ref = ArtifactRef.model_validate(provider["runtime_binding"])
        if runtime_ref.sha256 not in config.accepted_runtime_sha256:
            raise ValueError("acquisition_namespace_handoff_not_accepted")
        binding = FRRRuntimeBinding.model_validate(parse_json(store.referenced(runtime_ref)))
        instrument = CausalConfig.model_validate(parse_json(store.read(config.instrument_path, sha256=config.instrument_sha256)))
        if (contract_digest(instrument) not in config.accepted_instrument_sha256
                or instrument.runtime_binding_sha256 != runtime_ref.sha256
                or instrument.run_id != binding.run_id or instrument.network_id != binding.network_id
                or instrument.workspace_id != binding.workspace_id
                or binding.receiver_image_id != config.actual_receiver_image_id
                or {**binding.frozen_sources, **binding.receiver_sources} != runtime_sources(config.source_root)):
            raise ValueError("acquisition_scope_mismatch")
        network = AttachedFRRNetwork(binding, lock_directory=config.lock_directory)
        try:
            result = await finish_thread(lambda: acquire_window(network, instrument.model_dump(mode="json")))
            result.update(instrument_sha256=contract_digest(instrument), run_id=binding.run_id,
                runtime_binding_sha256=runtime_ref.sha256)
            digest = publish_new(args.output, result)
            return {"capture_sha256": digest, "measurement_complete": result["measurement_complete"],
                    "failures": result["failures"], "registered": False, "guaranteed_bounds": False}
        finally:
            network.close()
    installation, binding, instrument = await asyncio.to_thread(admit, config)
    if args.command == "check":
        return {"status": "evidence_admitted", "runtime": binding.runtime,
                "runtime_binding_sha256": installation.data.runtime_binding.sha256,
                "device_checked": False, "model_qualified": False}
    if args.command == "register":
        from app.db.postgres import AsyncSessionLocal
        capture = parse_json(ArtifactStore(str(Path(args.capture).parent)).read(Path(args.capture).name, sha256=args.capture_sha256))
        observation = Observation.model_validate(parse_json(ArtifactStore(str(Path(args.observation).parent)).read(
            Path(args.observation).name, sha256=args.observation_sha256)))
        protected_path(Path(args.capture))
        protected_path(Path(args.observation))
        async with AsyncSessionLocal() as db:
            digest = await register_causal_frame(db, instrument, capture, observation, sequence=args.sequence,
                accepted_guarantees=config.accepted_guarantee_sha256, accepted_instruments=config.accepted_instrument_sha256)
            await db.commit()
        return {"registered_observation_sha256": digest}
    network = AttachedFRRNetwork(binding, lock_directory=config.lock_directory)
    try:
        from app.db.postgres import AsyncSessionLocal
        from app.db.redis import close_redis, get_redis_client, init_redis
        from app.modules.autonomy.model_provider import FrozenModelProvider

        def ownership(resource, run):
            # Compensation remains possible after calibration or model expiry.
            return network.ownership(resource, run)

        await init_redis()
        try:
            registry = LiveRegistry.from_environment()
            model = FrozenModelProvider(registry, get_redis_client())
            async def dispatch_guard(authorization):
                current, current_binding, _ = await asyncio.to_thread(admit, config)
                current_model = await asyncio.to_thread(registry.load)
                validate_model_binding(current_binding, current_model)
                from app.modules.autonomy.execution_models import AutonomousObservation
                from app.modules.autonomy.schemas import SafetyAssessment
                safety = SafetyAssessment.model_validate_json(authorization.safety_evidence_json)
                async with AsyncSessionLocal() as db:
                    frame = await db.get(AutonomousObservation, safety.binding.observation_sha256)
                    if frame is None:
                        raise ValueError("frr_passive_snapshot_binding_missing")
                    observation = Observation.model_validate(frame.observation)
                snapshot_hashes = [value.split(":", 1)[1] for value in observation.evidence if value.startswith("passive_snapshot:")]
                if len(snapshot_hashes) != 1:
                    raise ValueError("frr_passive_snapshot_binding_missing")
                snapshot, _ = await asyncio.to_thread(registry.snapshot, current_model, authorization.network_id,
                    authorization.workspace_id, expected_hash=snapshot_hashes[0])
                if str(snapshot.run_id) != binding.run_id:
                    raise ValueError("frr_passive_runtime_run_mismatch")
                qualification = await model.qualify(authorization.checkpoint_sha256)
                if current.sha256 != installation.sha256 or not qualification.qualified:
                    raise ValueError("matching_frr_model_qualification_unavailable")
                baseline = current.action(current_binding.action_ids[current_binding.baseline_action])
                if safety.binding.state.active_routes != baseline.routes:
                    raise ValueError("frr_baseline_history_mapping_mismatch")
            driver = LinuxFRRDriver(network, resource_id=binding.resource_id, run_id=binding.run_id,
                binding_sha256=installation.data.runtime_binding.sha256, ownership_check=ownership,
                dispatch_guard=dispatch_guard, baseline_action=binding.baseline_action)
            executor, _ = build_execution_providers(AsyncSessionLocal, get_redis_client(), installation, driver,
                                                    binding.resource_id, execution_mode="emulation")
            from app.modules.autonomy.execution_settings import load_config as load_client_config
            from app.modules.autonomy.health_secret import signing_credentials
            from app.modules.autonomy.receiver_health import ReceiverHealth
            client_config = load_client_config()
            client_installation, legacy_key = await asyncio.to_thread(client_config.load)
            if client_installation.sha256 != installation.sha256 or client_config.resource_id != binding.resource_id:
                raise ValueError("receiver_client_installation_mismatch")
            # C21: only this receiver holds the Ed25519 private key; verifiers get the public key.
            signer, legacy_key = await asyncio.to_thread(signing_credentials, legacy_key)
            executor.health_publisher = ReceiverHealth(get_redis_client(), installation, binding.resource_id,
                legacy_key, signer=signer, max_age_seconds=client_config.health_max_age_seconds)
            # The original confined loader stays mandatory. A new runtime pin is
            # not qualification and cannot replace that independent provider gate.
            while True:
                await executor.run_one()
                if args.once:
                    return {"status": "receiver_iteration_complete"}
                await asyncio.sleep(1)
        finally:
            await close_redis()
    finally:
        network.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fingerprint", "check", "provision", "acquire", "register", "serve", "recover"))
    parser.add_argument("--config")
    parser.add_argument("--config-sha256")
    parser.add_argument("--source-root")
    parser.add_argument("--output")
    parser.add_argument("--capture")
    parser.add_argument("--capture-sha256")
    parser.add_argument("--observation")
    parser.add_argument("--observation-sha256")
    parser.add_argument("--sequence", type=int)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--execution-id")
    args = parser.parse_args()
    if args.command == "fingerprint":
        if not args.source_root:
            parser.error("--source-root required")
        print(json.dumps(runtime_sources(args.source_root), sort_keys=True))
        return 0
    if not args.config or not args.config_sha256:
        parser.error("explicit --config and --config-sha256 required")
    if args.command == "acquire" and not args.output:
        parser.error("--output new exclusive capture path required")
    if args.command == "recover" and not args.execution_id:
        parser.error("--execution-id exact persisted identity required")
    if args.command == "register" and any(v is None for v in (
            args.capture, args.capture_sha256, args.observation, args.observation_sha256, args.sequence)):
        parser.error("register requires exact capture/observation paths, hashes and sequence")
    try:
        result = asyncio.run(operate(args, load_config(args.config, args.config_sha256)))
        print(json.dumps(result, sort_keys=True))
        return 2 if result.get("status") == "blocked" else 0
    except (ValueError, OSError, RuntimeError):
        print(json.dumps({"status": "blocked", "reason": "explicit_frr_runtime_admission_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
