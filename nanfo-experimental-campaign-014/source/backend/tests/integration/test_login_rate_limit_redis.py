"""Opt-in real Redis transaction regression; deletes only UUID-owned login keys."""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.modules.identity.service import AuthService

pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTH_TEST_REDIS_URL"), reason="AUTH_TEST_REDIS_URL not configured"
)


async def test_concurrent_fixed_windows_and_lost_ack(mock_db):
    redis = Redis.from_url(os.environ["AUTH_TEST_REDIS_URL"], decode_responses=True)
    identity = uuid.uuid4().hex
    email, ip = f"{identity}@example.com", f"test-{identity}"
    keys = [f"ratelimit:login:{ip}", f"ratelimit:login:email:{email}"]
    service = AuthService(mock_db, redis)

    async def login():
        with pytest.raises(HTTPException) as error:
            await service.login(email, "wrong", ip, str(uuid.uuid4()))
        return error.value.status_code

    try:
        with (
            patch.object(service._user_repo, "get_by_email", return_value=None),
            patch("app.modules.identity.service.verify_password", return_value=False),
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
        ):
            statuses = await asyncio.gather(*(login() for _ in range(20)))
        assert statuses.count(401) == 5 and statuses.count(429) == 15
        for key in keys:
            assert await redis.get(key) == "20"
            assert 0 < await redis.ttl(key) <= 60
            await redis.expire(key, 15)

        pipeline_type = type(redis.pipeline())
        execute = pipeline_type.execute

        async def lost_ack(pipe, *args, **kwargs):
            await execute(pipe, *args, **kwargs)
            raise RedisConnectionError("reply lost after EXEC")

        with patch.object(pipeline_type, "execute", lost_ack):
            assert await login() == 401
        for key in keys:
            assert await redis.get(key) == "21"
            assert 0 < await redis.ttl(key) <= 15
        await redis.persist(keys[0])
        assert await login() == 429
        assert 0 < await redis.ttl(keys[0]) <= 60
    finally:
        await redis.delete(*keys)
        await redis.aclose()
