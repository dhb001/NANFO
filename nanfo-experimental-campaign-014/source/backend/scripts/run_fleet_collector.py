"""Explicit ADR023 worker; no collector is implicitly started in API processes."""

import argparse
import asyncio
import json
import signal

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.modules.telemetry.fleet import FleetWorker
from app.modules.telemetry.fleet_config import FleetSettings
from app.modules.telemetry.fleet_repository import FleetLock, FleetRepository
from app.modules.telemetry.service import TelemetryIngestionService


async def run(*, once: bool) -> int:
    settings, fleet = get_settings(), FleetSettings()
    configure_logging(settings.LOG_LEVEL)
    # Dedicated pools: no changes to shared API DB/config ownership. Session locks
    # must connect directly to PostgreSQL, never a transaction-pooling proxy.
    engine = create_async_engine(settings.POSTGRES_DSN, pool_size=fleet.concurrency + 2,
                                 max_overflow=0, pool_pre_ping=True)
    lock_engine = create_async_engine(settings.POSTGRES_DSN, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True,
                           socket_timeout=fleet.publish_timeout_seconds,
                           socket_connect_timeout=fleet.publish_timeout_seconds)
    try:
        repository = FleetRepository(sessions, lease_seconds=fleet.lease_seconds, timeout_seconds=fleet.db_timeout_seconds)
        worker = FleetWorker(settings=fleet, execution_mode=settings.EXECUTION_MODE, repository=repository,
                             locks=FleetLock(lock_engine, repository), sessions=sessions, redis=redis,
                             ingestion=TelemetryIngestionService(redis))
        if once:
            outcomes = await worker.run_once()
            print(json.dumps(await worker.health()))
            return 2 if any(value in {"collection_deferred", "lease_or_storage_unavailable"} for value in outcomes) else 0
        stop = asyncio.Event()
        for name in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_running_loop().add_signal_handler(name, stop.set)
        await worker.run(stop)
        return 0
    finally:
        await redis.aclose()
        await engine.dispose()
        await lock_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="One bounded sweep; emit operator health JSON")
    args = parser.parse_args()
    try:
        return asyncio.run(run(once=args.once))
    except KeyboardInterrupt:
        return 130
    except Exception:
        print(json.dumps({"status": "unavailable", "reason": "fleet_worker_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
