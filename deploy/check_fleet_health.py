"""Read-only bounded probe of existing fleet heartbeat contract; never collects."""

import asyncio
import json
import logging
from datetime import UTC, datetime


def age(timestamp, now):
    value = datetime.fromisoformat(timestamp)
    if value.tzinfo is None:
        raise ValueError("Unaware heartbeat")
    return (now - value).total_seconds()


async def heartbeat_check(redis, manifest, settings, *, now=None):
    now = now or datetime.now(UTC)
    expected = {str(target.device_id): target for target in manifest.targets}
    newest = {}
    cursor, seen = 0, set()
    # SCAN count is a hint; independently cap keys, responses and iterations.
    for _ in range(16):
        cursor, keys = await redis.scan(cursor=cursor, match="nanfo:fleet:health:v1:*", count=32)
        if len(keys) > 256 or len(seen | set(keys)) > 256:
            return False
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            raw = await redis.get(key)
            if raw is None:
                continue
            if len(raw) > 262144:
                return False
            try:
                document = json.loads(raw)
                heartbeat_age = age(document["observed_at"], now)
                if document["version"] != 1 or key != "nanfo:fleet:health:v1:" + document["worker_id"]:
                    return False
                if not 0 <= heartbeat_age <= min(settings.health_ttl_seconds, max(10, settings.scan_seconds * 3)):
                    continue
                devices = document["devices"]
                if not isinstance(devices, list) or len(devices) > 256:
                    return False
                for row in devices:
                    identity = row["device_id"]
                    if identity not in expected:
                        continue
                    target = expected[identity]
                    fresh = (row["outcome"] == "published" and row["fresh"] is True
                             and 0 <= age(row["last_published_at"], now)
                             <= target.interval_seconds + target.poll_timeout_seconds + settings.scan_seconds)
                    previous = newest.get(identity)
                    if previous is None or heartbeat_age <= previous[0]:
                        newest[identity] = (heartbeat_age, fresh)
            except (ValueError, TypeError, KeyError, AttributeError):
                return False
        if cursor == 0:
            return bool(expected) and set(newest) == set(expected) and all(row[1] for row in newest.values())
    return False


async def check():
    from app.core.config import get_settings
    from app.core.runtime_health import dependency_checks
    from app.modules.telemetry.fleet_config import FleetManifest, FleetSettings
    from app.modules.telemetry.snmp_config import load_protected_json
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    config, settings = get_settings(), FleetSettings()
    manifest = load_protected_json(settings.manifest_path, FleetManifest)
    engine = create_async_engine(config.POSTGRES_DSN)
    redis = Redis.from_url(config.REDIS_URL, decode_responses=True, socket_timeout=2)
    try:
        async with asyncio.timeout(5):
            checks = await dependency_checks(sessions=async_sessionmaker(engine), redis=lambda: redis)
            checks["fleet_heartbeat"] = "ok" if await heartbeat_check(redis, manifest, settings) else "unavailable"
        return {"ready": all(value == "ok" for value in checks.values()), "checks": checks}
    finally:
        async with asyncio.timeout(1):
            await redis.aclose()
            await engine.dispose()


def main():
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(check())
    except Exception:  # noqa: BLE001 - never expose configuration/transport credentials
        result = {"ready": False, "checks": {"fleet_heartbeat": "unavailable"}}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
