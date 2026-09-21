"""Real seeded role/profile contract; included by the isolated runner and CI.

Only persistence dependencies are real fixtures; permission mapping is never mocked.
Redis login/rotation validation runs only with an explicitly supplied fixture URL.
"""

import os
import secrets
import uuid

import tests.conftest  # noqa: F401 - test settings before application imports
import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from redis.asyncio import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import decode_token, hash_password
from app.modules.identity.repository import UserRepository
from app.modules.identity.service import AuthService
from scripts.verify_measured_twin import BACKEND

pytestmark = pytest.mark.skipif(not os.environ.get("AUDIT_TEST_DSN"), reason="owned AUDIT_TEST_DSN required")
EXPECTED = {
    "Admin": {"read:topology", "read:telemetry", "write:config", "execute:rollback", "manage:users", "manage:orgs"},
    "Operator": {"read:topology", "read:telemetry", "write:config", "execute:rollback"},
    "Read-Only": {"read:topology", "read:telemetry"},
}


@pytest.fixture
async def sessions():
    url = make_url(os.environ["AUDIT_TEST_DSN"])
    schema = "audit_roles_" + uuid.uuid4().hex
    sync = create_engine(url.set(drivername="postgresql+psycopg2"))
    engine = None
    try:
        config = Config()
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        scripts = ScriptDirectory.from_config(config)
        with sync.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            with EnvironmentContext(config, scripts, fn=lambda rev, _: scripts._upgrade_revs("head", rev)) as context:
                context.configure(connection=connection)
                context.run_migrations()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == scripts.get_current_head()
        engine = create_async_engine(url.set(drivername="postgresql+asyncpg"),
                                     connect_args={"server_settings": {"search_path": schema}})
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if engine:
            await engine.dispose()
        with sync.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        sync.dispose()


@pytest.mark.parametrize("role", EXPECTED)
async def test_seeded_role_and_backend_profile_match_adr026(sessions, role):
    async with sessions() as db:
        repo = UserRepository(db)
        user = await repo.create(f"{uuid.uuid4().hex}@audit.invalid", "not-a-login-hash")
        await repo.assign_role(user.user_id, role)
        await db.commit()
        assert await repo.get_roles_for_user(user) == [role]
        assert set(await repo.get_permissions_for_roles([role])) == EXPECTED[role]
        profile = await AuthService(db, None).get_profile(str(user.user_id))
        assert profile.roles == [role]
        assert set(profile.permissions) == EXPECTED[role]


@pytest.mark.parametrize("role", EXPECTED)
async def test_real_login_refresh_and_current_authority(sessions, role):
    redis_url = os.environ.get("AUDIT_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("owned AUDIT_TEST_REDIS_URL required for login/rotation")
    redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        async with sessions() as db:
            repo = UserRepository(db)
            password = secrets.token_urlsafe(24)
            user = await repo.create(f"{uuid.uuid4().hex}@audit.invalid", hash_password(password))
            await repo.assign_role(user.user_id, role)
            await db.commit()
            auth = AuthService(db, redis)
            tokens = await auth.login(user.email, password, "127.0.0.1", str(uuid.uuid4()))
            assert set(decode_token(tokens.access_token)["permissions"]) == EXPECTED[role]
            refreshed = await auth.refresh(tokens.refresh_token, str(uuid.uuid4()))
            claims = await auth.authenticate_access(refreshed.access_token)
            assert claims["roles"] == [role] and set(claims["permissions"]) == EXPECTED[role]
    finally:
        await redis.aclose()
