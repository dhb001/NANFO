"""Read-only operator acceptance: real newly published feed -> installed model.

Does not launch acquisition, generate observations, install a registry, select a
mode or dispatch. Parent runs alongside separately admitted acquisition/worker.
"""

import argparse
import asyncio
from builtins import ExceptionGroup
from datetime import UTC, datetime
import json
from pathlib import Path
import uuid

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.modules.autonomy.artifact_io import ArtifactStore, EvidenceError, parse_json
from app.modules.autonomy.live_observer import LiveObserver
from app.modules.autonomy.model_provider import FrozenModelProvider
from app.modules.autonomy.registry import LiveRegistry, protected_path
from app.modules.autonomy.schemas import contract_digest


async def verify_fresh(registry, redis, network_id, workspace_id, *, timeout_seconds=180):
    if not 1 <= timeout_seconds <= 600:
        raise EvidenceError("live_acceptance_timeout_invalid")
    started = datetime.now(UTC)
    installation = await asyncio.to_thread(registry.load)
    scope = next((s for s in installation.model.scopes if s.network_id == network_id
                  and s.workspace_id == workspace_id), None)
    if scope is None:
        raise EvidenceError("live_acceptance_scope_unregistered")
    observer, provider = LiveObserver(registry), FrozenModelProvider(registry, redis)
    async with asyncio.timeout(timeout_seconds):
        while True:
            qualification = await provider.qualify(installation.model.checkpoint.sha256)
            if qualification.qualified:
                break
            if qualification.reasons != ["live_qualification_pending"]:
                return {"status": "blocked", "reasons": qualification.reasons, "execution": "not_applied"}
            await asyncio.sleep(.5)
        while True:
            observation = await observer.observe(network_id, workspace_id)
            if observation.compatible and observation.fresh and observation.observed_at > started:
                snapshot, digest = registry.snapshot(installation, network_id, workspace_id)
                root = Path(registry.configuration().observation_root)
                relative = str(Path(scope.snapshot_path).parent / f"receipt-{snapshot.snapshot_id}.json")
                protected_path(root / relative)
                receipt_bytes = ArtifactStore(str(root)).read(relative, limit=64 * 1024)
                receipt = parse_json(receipt_bytes)
                if (receipt.get("version") != "nanfo.passive-feed-receipt/v1"
                        or receipt.get("registry_sha256") != installation.sha256
                        or receipt.get("snapshot_sha256") != digest
                        or receipt.get("history_sha256") != snapshot.history_sha256
                        or receipt.get("validation") != "original-frozen-measurement-and-inference"
                        or receipt.get("actuation") is not False):
                    raise EvidenceError("live_acceptance_acquisition_receipt_mismatch")
                proposal = await provider.infer(observation, qualification)
                return {"status": "fresh_provider_inference_verified", "started_at": started.isoformat(),
                    "observation": observation.model_dump(mode="json"),
                    "observation_sha256": contract_digest(observation),
                    "proposal": proposal.model_dump(mode="json"),
                    "qualification": qualification.model_dump(mode="json"),
                    "acquisition_receipt": receipt, "execution": "not_applied",
                    "durable_worker_decision_checked": False}
            await asyncio.sleep(.1)


async def run(args):
    redis = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
    try:
        return await verify_fresh(LiveRegistry.from_environment(), redis, args.network_id,
                                  args.workspace_id, timeout_seconds=args.timeout_seconds)
    finally:
        await redis.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network-id", type=uuid.UUID, required=True)
    parser.add_argument("--workspace-id", type=uuid.UUID, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
        print(json.dumps(result, allow_nan=False))
        return 0 if result["status"] == "fresh_provider_inference_verified" else 2
    except (ValueError, OSError, TimeoutError, RedisError, ExceptionGroup):
        print('{"status":"blocked","reasons":["fresh_provider_acceptance_failed"],"execution":"not_applied"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
