"""Qualified read-only frozen inference offload for the continuous Autonomy worker."""

import asyncio
from builtins import ExceptionGroup
import hashlib
import os
from pathlib import Path
import tempfile
import time

from redis.exceptions import RedisError

from app.modules.autonomy.artifact_io import EvidenceError
from app.modules.autonomy.live_schemas import OBSERVATION_CONTRACT, MeasuredFeatures, RuntimeResult
from app.modules.autonomy.schemas import POLICY_PROBABILITY_METHOD, Confidence, Proposal, ProviderStatus, Qualification
from app.core.canonical import canonical_sha256 as canonical_hash

RUNNER = Path(__file__).resolve().parents[3] / "scripts" / "frozen_live_inference.py"
LOCK = "nanfo:autonomy:model-diagnostics:inference"  # share actual CPU admission with ADR018
_QUALIFICATION_TASKS = set()


async def confined_runtime(registry, operation, *, observation=None, snapshot_hash=None):
    settings = registry.configuration()
    if os.geteuid() == 0 or not Path(settings.interpreter).is_absolute():
        raise EvidenceError("live_inference_interpreter_or_user_invalid")
    env = settings.environment() | dict(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
        PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="", LANG="C.UTF-8")
    args = [operation]
    if observation is not None:
        args += ["--network-id", str(observation.network_id), "--workspace-id", str(observation.workspace_id),
                 "--snapshot-sha256", snapshot_hash]
    with tempfile.TemporaryDirectory(prefix="nanfo-live-inference-") as directory:
        env.update(HOME=directory, TMPDIR=directory)
        process = await asyncio.create_subprocess_exec(settings.interpreter, "-I", "-B", str(RUNNER), *args,
            cwd=directory, env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)

        async def bounded(stream):
            content = bytearray()
            while chunk := await stream.read(4096):
                content.extend(chunk)
                if len(content) > 64 * 1024:
                    raise EvidenceError("live_inference_output_limit")
            return bytes(content)

        try:
            async with asyncio.timeout(120 if operation == "qualify" else 30):
                async with asyncio.TaskGroup() as tasks:
                    stdout = tasks.create_task(bounded(process.stdout))
                    tasks.create_task(bounded(process.stderr))
                    tasks.create_task(process.wait())
            if process.returncode:
                raise EvidenceError("live_frozen_validation_failed")
            return RuntimeResult.model_validate_json(stdout.result())
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()


class FrozenModelProvider:
    qualification_status = ProviderStatus(provider_id="frozen_scoped_benchmark_v4", status="ready")
    inference_status = ProviderStatus(provider_id="confined_frozen_v4", status="ready")

    def __init__(self, registry, redis):
        self.registry, self.redis = registry, redis
        self._qualified = None

    def _cache_key(self, installation):
        # Redis is backend-owned runtime state, never producer JSON. Include evaluator
        # bytes so a code upgrade cannot reuse an older qualification computation.
        # Bind all trusted admission/validation code, not only the subprocess entrypoint.
        owner = Path(__file__).parent
        code = hashlib.sha256(b"".join(path.read_bytes() for path in (
            RUNNER, owner / "registry.py", owner / "live_schemas.py", Path(__file__),
        ))).hexdigest()
        return f"nanfo:autonomy:live-qualification:{installation.sha256}:{code}"

    async def _prepare(self, installation, key):
        try:
            result = await self._runtime("qualify")
            self._validate_result(result, installation, "qualify")
            current = await asyncio.to_thread(self.registry.load)
            if current.sha256 == installation.sha256:
                await self.redis.set(key, result.model_dump_json(), ex=300)
        except (ValueError, OSError, TimeoutError, ExceptionGroup, RedisError):
            # Short negative receipt prevents repeated expensive validation storms.
            try:
                await self.redis.set(key + ":failed", "1", ex=30)
            except RedisError:
                pass
            return

    async def _runtime(self, operation, **kwargs):
        lock = self.redis.lock(LOCK, timeout=130 if operation == "qualify" else 40,
                               blocking=False, thread_local=False)
        acquired = False
        try:
            acquired = await lock.acquire()
            if not acquired:
                raise EvidenceError("live_inference_busy")
            result = await confined_runtime(self.registry, operation, **kwargs)
            if not await lock.owned():
                raise EvidenceError("live_inference_lease_lost")
            return result
        finally:
            if acquired:
                try:
                    await lock.release()
                except RedisError:
                    pass

    @staticmethod
    def _validate_result(result, installation, operation):
        model = installation.model
        if (result.operation != operation or result.registry_sha256 != installation.sha256
                or result.checkpoint_sha256 != model.checkpoint.sha256
                or result.weights_sha256 != installation.manifest["weights_sha256"]
                or result.source_sha256 != canonical_hash(model.source_sha256)
                or result.contract_sha256 != model.contract_sha256 or result.spec_sha256 != model.spec_sha256
                or result.report_sha256 != model.report.sha256):
            raise EvidenceError("live_inference_identity_mismatch")
        if (result.qualification_protocol != model.qualification_protocol
                or result.parent_checkpoint_sha256 != (model.parent_checkpoint.sha256 if model.parent_checkpoint else None)):
            raise EvidenceError("live_inference_lineage_mismatch")

    async def qualify(self, checkpoint_sha256):
        try:
            installation = await asyncio.to_thread(self.registry.load)
            if checkpoint_sha256 != installation.model.checkpoint.sha256:
                raise EvidenceError("live_checkpoint_not_installed")
            # Re-hash every bound benchmark file even on the short process-local cache.
            await asyncio.to_thread(self.registry.benchmark_bytes, installation)
            if (self._qualified is None or self._qualified[0] != installation.sha256
                    or time.monotonic() - self._qualified[1] > 60):
                key = self._cache_key(installation)
                cached = await self.redis.get(key)
                if cached is None:
                    if await self.redis.get(key + ":failed") is not None:
                        raise EvidenceError("live_qualification_validation_failed")
                    # Full raw benchmark reconstruction is bounded but exceeds the
                    # service's 5s readiness budget. Poll through the existing worker;
                    # never cancel/restart qualification on each short readiness call.
                    if not any(task.get_name() == key for task in _QUALIFICATION_TASKS):
                        task = asyncio.create_task(self._prepare(installation, key), name=key)
                        _QUALIFICATION_TASKS.add(task)
                        task.add_done_callback(_QUALIFICATION_TASKS.discard)
                    return Qualification(qualified=False, checkpoint_sha256=checkpoint_sha256,
                                         reasons=["live_qualification_pending"])
                if not isinstance(cached, (str, bytes)) or len(cached) > 64 * 1024:
                    raise EvidenceError("live_qualification_receipt_invalid")
                result = RuntimeResult.model_validate_json(cached)
                self._validate_result(result, installation, "qualify")
                current = await asyncio.to_thread(self.registry.load)
                if current.sha256 != installation.sha256:
                    raise EvidenceError("live_registry_changed")
                self._qualified = installation.sha256, time.monotonic()
            return Qualification(qualified=True, checkpoint_sha256=checkpoint_sha256,
                observation_contract=OBSERVATION_CONTRACT, manifest_sha256=installation.sha256,
                evidence=[f"live_registry:{installation.sha256}", f"benchmark:{installation.model.report.sha256}",
                          f"qualification_protocol:{installation.model.qualification_protocol}",
                          *([f"parent_checkpoint:{installation.model.parent_checkpoint.sha256}"] if installation.model.parent_checkpoint else []),
                          "qualification:raw-heldout-reconstruction-and-frozen-policy-replay",
                          "scope:stationary-campus-small-v4-scoped-benchmark", "safety_authorized:false"])
        except (ValueError, OSError, TimeoutError, ExceptionGroup, RedisError) as exc:
            self._qualified = None
            reason = str(exc) if isinstance(exc, EvidenceError) else "live_qualification_validation_failed"
            return Qualification(qualified=False, checkpoint_sha256=checkpoint_sha256, reasons=[reason])

    async def infer(self, observation, qualification):
        installation = await asyncio.to_thread(self.registry.load)
        model = installation.model
        if (not qualification.qualified or qualification.checkpoint_sha256 != model.checkpoint.sha256
                or qualification.manifest_sha256 != installation.sha256
                or qualification.observation_contract != OBSERVATION_CONTRACT
                or observation.contract != OBSERVATION_CONTRACT or not observation.compatible or not observation.fresh
                or self._qualified is None or self._qualified[0] != installation.sha256
                or time.monotonic() - self._qualified[1] > 60):
            raise EvidenceError("live_inference_qualification_mismatch")
        hashes = [row.removeprefix("passive_snapshot:") for row in observation.evidence if row.startswith("passive_snapshot:")]
        if len(hashes) != 1 or f"live_registry:{installation.sha256}" not in observation.evidence:
            raise EvidenceError("live_inference_snapshot_reference_missing")
        snapshot, digest = await asyncio.to_thread(self.registry.snapshot, installation,
            observation.network_id, observation.workspace_id, expected_hash=hashes[0])
        if observation.observed_at != snapshot.observed_at:
            raise EvidenceError("live_inference_observation_time_mismatch")
        result = await self._runtime("infer", observation=observation, snapshot_hash=digest)
        self._validate_result(result, installation, "infer")
        features = MeasuredFeatures.model_validate(snapshot.history["frames"][0]["response"]["data"]["observation"])
        if (result.snapshot_sha256 != digest or result.history_sha256 != snapshot.history_sha256
                or result.input_sha256 != canonical_hash(features.model_dump(mode="json"))
                or result.action_path != installation.manifest["contract"]["action_map"][result.action]):
            raise EvidenceError("live_inference_action_or_input_mismatch")
        # Check installation expiry, rotation and exact snapshot freshness again after I/O.
        current = await asyncio.to_thread(self.registry.load)
        if current.sha256 != installation.sha256:
            raise EvidenceError("live_registry_changed")
        await asyncio.to_thread(self.registry.snapshot, current, observation.network_id,
                                observation.workspace_id, expected_hash=digest)
        # C17: the selected action's raw policy probability is reported as typed confidence,
        # explicitly uncalibrated (no calibration of policy probabilities is installed).
        confidence = Confidence(value=float(result.probabilities[result.action]),
                                method=POLICY_PROBABILITY_METHOD, calibrated=False)
        return Proposal(action_id=model.action_ids[result.action], checkpoint_sha256=model.checkpoint.sha256,
            observation_contract=OBSERVATION_CONTRACT, confidence=confidence,
            evidence=[*qualification.evidence, f"passive_snapshot:{digest}", f"input:{result.input_sha256}",
                      f"checkpoint:{result.checkpoint_sha256}", f"weights:{result.weights_sha256}",
                      f"source:{result.source_sha256}", f"action_path:{'/'.join(result.action_path)}",
                      f"policy_probabilities:{result.probabilities}", f"critic_value:{result.value}",
                      "probabilities_are_safety_confidence:false", "execution:not_applied"])
