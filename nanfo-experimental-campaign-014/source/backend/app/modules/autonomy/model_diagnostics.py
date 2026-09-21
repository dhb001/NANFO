"""Bounded historical inference offload. No observer, events, promotion or dispatch."""

import asyncio
from builtins import ExceptionGroup
import os
from pathlib import Path
import tempfile
import time

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.core.dependencies import get_claim_org_scope, get_claim_workspace_scope
from app.modules.autonomy.model_diagnostic_repository import ModelDiagnosticRepository
from app.modules.autonomy.model_diagnostic_schemas import (
    DiagnosticResult,
    ModelDiagnosticsResponse,
    RegisteredModelStatus,
)
from app.modules.autonomy.service import authorize
from scripts.frozen_model_diagnostic import CONFIG_KEYS, canonical_hash, load_registry, select_model

RUNNER = Path(__file__).resolve().parents[3] / "scripts" / "frozen_model_diagnostic.py"
LOCK = "nanfo:autonomy:model-diagnostics:inference"


async def frozen_inference(network_id, model, reference, registry_hash):
    interpreter = Path(os.environ["NANFO_MODEL_PYTHON"])
    if not interpreter.is_absolute() or os.geteuid() == 0:
        raise ValueError("diagnostic_interpreter_or_user_invalid")
    env = {key: os.environ[key] for key in CONFIG_KEYS}
    env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="", LANG="C.UTF-8")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="nanfo-diagnostic-") as directory:
        env.update(HOME=directory, TMPDIR=directory)
        process = await asyncio.create_subprocess_exec(
            str(interpreter), "-I", "-B", str(RUNNER), "--network-id", str(network_id),
            "--model-id", model.model_id, "--checkpoint-id", model.checkpoint_id,
            "--history-reference", reference, cwd=directory, env=env,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True,
        )

        async def bounded(stream):
            content = bytearray()
            while chunk := await stream.read(4096):
                content.extend(chunk)
                if len(content) > 64 * 1024:
                    raise ValueError("diagnostic_output_limit")
            return bytes(content)

        try:
            async with asyncio.timeout(30):
                async with asyncio.TaskGroup() as tasks:
                    stdout = tasks.create_task(bounded(process.stdout))
                    tasks.create_task(bounded(process.stderr))
                    tasks.create_task(process.wait())
            if process.returncode != 0:
                raise ValueError("frozen_diagnostic_validation_failed")
            result = DiagnosticResult.model_validate_json(stdout.result())
            if (result.model_id != model.model_id or result.checkpoint_id != model.checkpoint_id
                or result.history_reference != reference or result.registry_sha256 != registry_hash
                or result.policy_sha256 != model.checkpoint.sha256
                or result.source_sha256 != canonical_hash(model.source_sha256)
                or result.history_sha256 != model.histories[reference].artifact.sha256
                or result.benchmark_evidence_sha256 != model.benchmark.evidence.sha256):
                raise ValueError("diagnostic_identity_mismatch")
            return DiagnosticResult.model_validate(result.model_dump() | {"subprocess_seconds": time.monotonic() - started})
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()


class ModelDiagnosticsService:
    def __init__(self, db, redis):
        self.db, self.redis = db, redis
        self.repo = ModelDiagnosticRepository(db)

    async def scope(self, claims, network_id, write=False):
        network, _ = await authorize(db=self.db, redis=self.redis, network_id=network_id,
            actor_id=claims.user_id, write=write, workspace_id=get_claim_workspace_scope(claims=claims),
            org_id=get_claim_org_scope(claims=claims))
        return network.workspace_id

    async def get(self, claims, network_id, limit=20):
        workspace_id = await self.scope(claims, network_id)
        status = None
        reasons = ["compatible_live_history_unavailable"]
        try:
            registry, _, _ = await asyncio.to_thread(load_registry)
            model = select_model(registry, network_id)
            if model:
                status = RegisteredModelStatus(model_id=model.model_id, checkpoint_id=model.checkpoint_id,
                    checkpoint_sha256=model.checkpoint.sha256,
                    history_references=[key for key, history in model.histories.items() if network_id in history.network_ids],
                    benchmark_status=model.benchmark.status, benchmark_scope=model.benchmark.scope,
                    benchmark_limitations=model.benchmark.limitations)
            else:
                reasons.append("model_not_registered")
        except (ValueError, OSError):
            reasons.append("model_registry_unavailable")
        return ModelDiagnosticsResponse(network_id=network_id, workspace_id=workspace_id,
            status="operator_registered" if status else "unavailable", model=status, reasons=reasons,
            diagnostics=await self.repo.history(network_id, workspace_id, limit))

    async def diagnose(self, claims, request):
        workspace_id = await self.scope(claims, request.network_id, write=True)
        await self.db.commit()
        try:
            registry, pin, _ = await asyncio.to_thread(load_registry)
        except (ValueError, OSError) as exc:
            raise HTTPException(503, detail="Model registry unavailable.") from exc
        model = select_model(registry, request.network_id)
        history = model.histories.get(request.history_reference) if model else None
        if history is None or request.network_id not in history.network_ids:
            raise HTTPException(404, detail="Registered model history unavailable for this network.")
        lock = self.redis.lock(LOCK, timeout=40, blocking=False, thread_local=False)
        acquired = False
        try:
            acquired = await lock.acquire()
            if not acquired:
                raise HTTPException(429, detail="Model diagnostic already running.")
            result = await frozen_inference(request.network_id, model, request.history_reference, pin)
            if not await lock.owned():
                raise ValueError("diagnostic_lease_lost")
            self.db.expire_all()
            current_workspace = await self.scope(claims, request.network_id, write=True)
            if workspace_id != current_workspace:
                raise HTTPException(409, detail="Network ownership changed.")
            current, current_pin, _ = await asyncio.to_thread(load_registry)
            if current_pin != pin or select_model(current, request.network_id) != model:
                raise HTTPException(409, detail="Model registry changed; retry explicitly.")
            record = await self.repo.insert(network_id=request.network_id, workspace_id=workspace_id,
                                            actor_id=claims.user_id, result=result)
            await self.db.commit()
            return record
        except (ValueError, OSError, TimeoutError, ExceptionGroup, RedisError) as exc:
            await self.db.rollback()
            raise HTTPException(503, detail="Frozen model diagnostic unavailable or validation failed.") from exc
        finally:
            if acquired:
                try:
                    await lock.release()
                except RedisError:
                    pass  # Lease expires; never release another owner's lock.
