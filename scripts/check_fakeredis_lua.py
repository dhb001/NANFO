"""Verify the locked development environment executes real fakeredis Lua."""

import asyncio

from fakeredis import FakeRedis
from fakeredis.aioredis import FakeRedis as AsyncFakeRedis

SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[2])
return 1
"""


async def main():
    # Execute Lua against both API variants; no monkeypatch or real Redis fallback.
    with FakeRedis(decode_responses=True) as client:
        client.set("owner", "generation-1")
        assert client.eval(SCRIPT, 1, "owner", "stale", "generation-2") == 0
        assert client.get("owner") == "generation-1"
        assert client.eval(SCRIPT, 1, "owner", "generation-1", "generation-2") == 1
        assert client.get("owner") == "generation-2"
    async with AsyncFakeRedis(decode_responses=True) as client:
        await client.set("owner", "generation-1")
        assert await client.eval(SCRIPT, 1, "owner", "stale", "generation-2") == 0
        assert await client.get("owner") == "generation-1"
        assert await client.eval(SCRIPT, 1, "owner", "generation-1", "generation-2") == 1
        assert await client.get("owner") == "generation-2"
    print("fakeredis sync/async Lua EVAL: stale owner denied; matching owner updated")


if __name__ == "__main__":
    asyncio.run(main())
