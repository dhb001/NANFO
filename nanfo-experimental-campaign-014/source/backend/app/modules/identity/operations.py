"""ADR020 invalidate only restored session families, with bounded Redis work."""

import asyncio


async def invalidate_restored_sessions(redis, *, max_keys=100_000, max_scans=10_000):
    cursor, removed, scans = 0, 0, 0
    async with asyncio.timeout(60):
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor, match="auth:session:*", count=200
            )
            scans += 1
            if scans > max_scans or removed + len(keys) > max_keys:
                raise ValueError(
                    "Session invalidation cap exceeded; keep writers stopped"
                )
            if any(not key.startswith("auth:session:") for key in keys):
                raise ValueError("Unexpected Redis session key")
            for offset in range(0, len(keys), 200):
                removed += await redis.unlink(*keys[offset : offset + 200])
            if cursor == 0:
                break
    return removed
