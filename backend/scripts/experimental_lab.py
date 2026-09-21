"""ADR025 protected operator CLI. No lab acquisition or privileged launch here."""

import argparse
import asyncio
import json

from redis.asyncio import Redis

from app.core.config import get_settings
from app.db.postgres import AsyncSessionLocal
from app.modules.autonomy.experimental.authority import CurrentAuthority
from app.modules.autonomy.experimental.controller import ExperimentalController
from app.modules.autonomy.experimental.settings import load_installation


async def operate(args):
    installation = load_installation(args.config, args.config_sha256)
    redis = Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    try:
        # status/STOP must work even if an adapter is broken or unavailable.
        ports = await installation.build_ports() if args.operation in ("run", "recover") else None
        controller = ExperimentalController(AsyncSessionLocal,
            CurrentAuthority(AsyncSessionLocal, redis), ports, installation.policy)
        return await getattr(controller, args.operation)()
    finally:
        await redis.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("status", "stop", "run", "recover"))
    parser.add_argument("--config", help="Absolute protected installation JSON path")
    parser.add_argument("--config-sha256", help="Exact protected installation byte hash")
    args = parser.parse_args()
    try:
        result = asyncio.run(operate(args))
    except (Exception, KeyboardInterrupt):
        # Details live in bounded journals; never print credentials/raw adapter errors.
        print(json.dumps({"ok": False, "error": "experimental_operation_failed", "operation": args.operation}))
        return 1
    print(json.dumps({"ok": True, "data": result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
