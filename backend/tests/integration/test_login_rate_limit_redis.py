"""Opt-in real Redis transaction regression; deletes only UUID-owned login keys."""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.errors import DependencyUnavailableError
from app.modules.identity.service import AuthService, login_email_bucket_key, login_ip_bucket_key

pytestmark = pytest.mark.skipif(
    not os.environ.get("AUTH_TEST_REDIS_URL"), reason="AUTH_TEST_REDIS_URL not configured"
)


async def test_concurrent_fixed_windows_and_lost_ack(mock_db):
    redis = Redis.from_url(os.environ["AUTH_TEST_REDIS_URL"], decode_responses=True)
    identity = uuid.uuid4().hex
    email, ip = f"{identity}@example.com", f"test-{identity}"
    ip_key, email_key = login_ip_bucket_key(ip), login_email_bucket_key(email)
    service = AuthService(mock_db, redis)

    async def login():
        try:
            await service.login(email, "wrong", ip, str(uuid.uuid4()))
        except HTTPException as error:
            return error.status_code
        except DependencyUnavailableError:
            return 503
        raise AssertionError("login unexpectedly succeeded")

    try:
        with (
            patch.object(service._user_repo, "get_by_email", return_value=None),
            patch("app.modules.identity.service.verify_password", return_value=False),
            patch("app.modules.identity.service.publish_event", new_callable=AsyncMock),
        ):
            statuses = await asyncio.gather(*(login() for _ in range(20)))
        assert statuses.count(401) == 5 and statuses.count(429) == 15
        # Every attempt counts per IP; IP-throttled attempts never reach the email bucket.
        assert await redis.get(ip_key) == "20"
        assert await redis.get(email_key) == "5"
        for key in (ip_key, email_key):
            assert 0 < await redis.ttl(key) <= 60
            await redis.expire(key, 15)

        pipeline_type = type(redis.pipeline())
        execute = pipeline_type.execute

        async def lost_ack(pipe, *args, **kwargs):
            await execute(pipe, *args, **kwargs)
            raise RedisConnectionError("reply lost after EXEC")

        with patch.object(pipeline_type, "execute", lost_ack):
            # ADR-028 C2: an unknown throttle outcome is a retryable 503, never 401.
            assert await login() == 503
        assert await redis.get(ip_key) == "21"
        assert 0 < await redis.ttl(ip_key) <= 15
        await redis.persist(ip_key)
        assert await login() == 429
        assert 0 < await redis.ttl(ip_key) <= 60
    finally:
        await redis.delete(ip_key, email_key, f"ratelimit:login-audited:{ip}")
        await redis.aclose()
