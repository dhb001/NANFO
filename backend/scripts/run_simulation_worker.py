"""Run the independent ADR-017 modeled simulation worker. No lab integration.

Each loop iteration is isolated (ADR-028): an unexpected exception from one job,
the outbox or the deferred plugin-event sweep is logged and the loop continues.
A job that repeatedly crashes its worker is bounded by ``SIMULATION_MAX_CLAIM_ATTEMPTS``.
"""

import argparse
import asyncio
import time

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.runtime_health import worker_iteration
from app.core.watchdog import watchdog_guard
from app.db.postgres import AsyncSessionLocal
from app.modules.plugin.service import republish_deferred_plugin_events
from app.modules.simulation.worker import SimulationWorker

logger = get_logger(__name__)
FAILURE_BACKOFF_SECONDS = 1.0
PLUGIN_SWEEP_INTERVAL_SECONDS = 30.0


async def iteration(worker: SimulationWorker) -> bool:
    busy = False
    try:
        async with worker_iteration("simulation"):
            busy = await worker.run_one()
    except Exception as exc:  # noqa: BLE001 - one poison job must not stop evaluation
        # Exception text can carry payload data; log the type only.
        logger.warning("simulation_worker_iteration_failed", error_type=type(exc).__name__)
        await asyncio.sleep(FAILURE_BACKOFF_SECONDS)
    try:
        async with worker_iteration("outbox"):
            for _ in range(16):
                if not await worker.publish_one():
                    break
    except Exception:  # noqa: BLE001 - durable outbox retries without stopping evaluation
        logger.warning("simulation_outbox_deferred")
    return busy


async def sweep_plugins(redis) -> None:
    """The plugin registry has no worker of its own; its deferred events are swept here."""
    try:
        async with AsyncSessionLocal() as db:
            await republish_deferred_plugin_events(db=db, redis=redis)
    except Exception as exc:  # noqa: BLE001 - deferred rows stay deferred and are retried
        logger.warning("plugin_deferred_event_sweep_failed", error_type=type(exc).__name__)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-ticks", type=int, choices=range(1, 33), default=8)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    worker = SimulationWorker(
        sessions=AsyncSessionLocal, redis=redis, batch_ticks=args.batch_ticks
    )
    next_plugin_sweep = 0.0
    try:
        # ADR-028: a blocked event loop exits (code 70) so the restart policy restarts it.
        async with watchdog_guard("simulation-worker", settings):
            while True:
                busy = await iteration(worker)
                if time.monotonic() >= next_plugin_sweep:
                    await sweep_plugins(redis)
                    next_plugin_sweep = time.monotonic() + PLUGIN_SWEEP_INTERVAL_SECONDS
                if args.once:
                    break
                await asyncio.sleep(0.05 if busy else 0.5)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
