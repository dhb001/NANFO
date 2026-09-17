"""Read-only ADR020 worker probe. Never imports or executes a worker/job."""

import argparse
import asyncio
import json
import logging

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.runtime_health import WORKER_LOOPS, dependency_checks, heartbeat_checks


async def check(worker: str) -> dict:
    settings = get_settings()
    engine = create_async_engine(settings.POSTGRES_DSN, echo=False)
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        checks = await dependency_checks(
            sessions=async_sessionmaker(engine), redis=lambda: redis
        )
        checks.update(
            {
                f"heartbeat_{name}": value
                for name, value in heartbeat_checks(worker).items()
            }
        )
        return {
            "ready": all(value == "ok" for value in checks.values()),
            "checks": checks,
        }
    finally:
        async with asyncio.timeout(2):
            await redis.aclose()
            await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=WORKER_LOOPS, required=True)
    args = parser.parse_args()
    # Library connection/cleanup diagnostics must not escape via healthcheck logs.
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(check(args.worker))
    except Exception:  # noqa: BLE001 - config/transport errors can contain secrets
        result = {"ready": False, "checks": {"runtime": "unavailable"}}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
