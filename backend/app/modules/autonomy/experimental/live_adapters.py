"""Real unchanged frozen-provider bridge with complete inference receipts retained."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from pydantic import Field

from app.modules.autonomy.live_observer import LiveObserver
from app.modules.autonomy.live_schemas import MeasuredFeatures
from app.modules.autonomy.model_provider import FrozenModelProvider
from app.modules.autonomy.schemas import contract_digest
from app.modules.autonomy.artifact_io import ArtifactStore, parse_json
from app.modules.autonomy.registry import protected_path

from .schemas import SHA256, InferenceRecord, MeasuredFrame, Record, RuntimeIdentity


class WrapperEquivalence(Record):
    """Pinned reviewed evidence, not a model qualification or safety certificate."""
    runtime: RuntimeIdentity
    registry_sha256: SHA256
    checkpoint_sha256: SHA256
    weights_sha256: SHA256
    model_source_sha256: SHA256
    model_adapter_sha256: SHA256
    evidence_sha256: tuple[SHA256, ...] = Field(min_length=1)
    scope: str = Field(min_length=1)


class LiveFrameObserver:
    def __init__(self, registry, policy, provenance):
        self.registry, self.policy, self.provenance = registry, policy, provenance
        self.observer = LiveObserver(registry)

    async def observe(self):
        p = self.policy
        observation = await self.observer.observe(p.network_id, p.workspace_id)
        if not observation.fresh or not observation.compatible:
            raise ValueError("experimental_live_observation_unavailable")
        hashes = [e.split(":", 1)[1] for e in observation.evidence if e.startswith("passive_snapshot:")]
        if len(hashes) != 1:
            raise ValueError("experimental_snapshot_reference_missing")
        installation = await asyncio.to_thread(self.registry.load)
        if installation.sha256 != p.registry_sha256:
            raise ValueError("experimental_registry_changed")
        snapshot, _ = await asyncio.to_thread(self.registry.snapshot, installation,
            p.network_id, p.workspace_id, expected_hash=hashes[0])
        return MeasuredFrame(snapshot=snapshot, observation=observation, runtime=p.runtime,
            features=MeasuredFeatures.model_validate(snapshot.history["frames"][0]["response"]["data"]["observation"]),
            provenance=self.provenance)


class _RecordingProvider(FrozenModelProvider):
    """Instrumentation only: preserve the exact validated subprocess result."""

    result = None

    async def _runtime(self, operation, **kwargs):
        result = await super()._runtime(operation, **kwargs)
        if operation == "infer":
            self.result = result
        return result


class FrozenInferenceAdapter:
    def __init__(self, registry, redis, policy):
        self.provider = _RecordingProvider(registry, redis)
        self.policy = policy
        self.lock = asyncio.Lock()

    async def infer(self, frame):
        async with self.lock:
            qualification = await self.provider.qualify(self.policy.checkpoint_sha256)
            if not qualification.qualified:
                raise ValueError("experimental_frozen_qualification_not_ready")
            self.provider.result = None
            proposal = await self.provider.infer(frame.observation, qualification)
            if self.provider.result is None:
                raise ValueError("experimental_complete_inference_missing")
            if self.provider.result.snapshot_sha256 != contract_digest(frame.snapshot):
                raise ValueError("experimental_snapshot_requires_canonical_publication")
            return InferenceRecord(frame_sha256=contract_digest(frame), result=self.provider.result,
                proposal=proposal, qualification=qualification)


class LiveModelAdapter(FrozenInferenceAdapter):
    """Read-only lab access; publishes exact original episode to the frozen runtime.

    prepare() performs expensive frozen qualification before measurement acquisition.
    Neither this adapter nor its subprocess receives receiver credentials or ports.
    The existing full frozen validator is still used, without provenance rewriting.
    """

    def __init__(self, registry, redis, policy, *, equivalence_path):
        super().__init__(registry, redis, policy)
        self.equivalence_path = Path(equivalence_path)

    def _equivalence(self):
        p = self.policy
        if p.wrapper_equivalence_sha256 is None or p.model_adapter_sha256 is None:
            raise ValueError("experimental_wrapper_equivalence_required")
        protected_path(self.equivalence_path)
        value = WrapperEquivalence.model_validate(parse_json(ArtifactStore(str(self.equivalence_path.parent)).read(
            self.equivalence_path.name, sha256=p.wrapper_equivalence_sha256)))
        if (value.runtime != p.runtime or any(getattr(value, key) != getattr(p, key) for key in (
                "registry_sha256", "checkpoint_sha256", "weights_sha256", "model_source_sha256", "model_adapter_sha256"))
                or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != p.model_adapter_sha256):
            raise ValueError("experimental_wrapper_equivalence_binding_mismatch")
        return value

    async def prepare(self):
        await asyncio.to_thread(self._equivalence)
        installation = await asyncio.to_thread(self.provider.registry.load)
        if installation.sha256 != self.policy.registry_sha256:
            raise ValueError("experimental_registry_changed")
        result = await self.provider._runtime("qualify")
        self.provider._validate_result(result, installation, "qualify")
        self.provider._qualified = installation.sha256, time.monotonic()
        return result

    def _publish(self, frame):
        registry = self.provider.registry
        installation = registry.load()
        if installation.sha256 != self.policy.registry_sha256:
            raise ValueError("experimental_registry_changed")
        scope = next((s for s in installation.model.scopes if s.network_id == self.policy.network_id
                      and s.workspace_id == self.policy.workspace_id), None)
        if scope is None:
            raise ValueError("experimental_model_scope_missing")
        root = Path(registry.configuration().observation_root)
        target = root / scope.snapshot_path
        if not root.is_absolute() or not target.is_relative_to(root) or ".." in Path(scope.snapshot_path).parts:
            raise ValueError("experimental_snapshot_path_invalid")
        protected_path(target.parent)
        if target.exists() or target.is_symlink():
            protected_path(target)
        content = json.dumps(frame.snapshot.model_dump(mode="json"), sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()
        fd, temporary = tempfile.mkstemp(prefix=".experimental-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    async def infer(self, frame):
        frame = MeasuredFrame.model_validate(frame)
        await asyncio.to_thread(self._equivalence)
        if frame.runtime != self.policy.runtime:
            raise ValueError("experimental_model_runtime_mismatch")
        async with self.lock:
            await asyncio.to_thread(self._publish, frame)
            observation = await LiveObserver(self.provider.registry).observe(self.policy.network_id, self.policy.workspace_id)
            # Registry view of the same snapshot; original frame/episode is unchanged.
            qualification = await self.provider.qualify(self.policy.checkpoint_sha256)
            if not qualification.qualified:
                raise ValueError("experimental_frozen_qualification_not_ready")
            self.provider.result = None
            proposal = await self.provider.infer(observation, qualification)
            result = self.provider.result
            if result is None or result.snapshot_sha256 != contract_digest(frame.snapshot):
                raise ValueError("experimental_snapshot_requires_canonical_publication")
            return InferenceRecord(frame_sha256=contract_digest(frame), result=result,
                proposal=proposal, qualification=qualification,
                wrapper_equivalence_sha256=self.policy.wrapper_equivalence_sha256,
                model_adapter_sha256=self.policy.model_adapter_sha256)
