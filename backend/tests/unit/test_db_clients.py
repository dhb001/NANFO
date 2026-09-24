"""ADR-028 connection policy for PostgreSQL, Redis and Neo4j (no services contacted)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from redis.asyncio import BlockingConnectionPool

from app.core.config import get_settings
from app.db import neo4j as neo4j_db
from app.db import postgres, redis as redis_db


def test_postgres_pool_and_server_timeouts_from_settings():
    settings = get_settings().model_copy(update={
        "DB_POOL_SIZE": 5, "DB_MAX_OVERFLOW": 5, "DB_STATEMENT_TIMEOUT_MS": 30000,
        "DB_IDLE_IN_TRANSACTION_TIMEOUT_MS": 900000, "DB_ECHO": False,
    })
    options = postgres.engine_options(settings)
    assert options["pool_size"] + options["max_overflow"] == 10  # API + 6 workers = 70 < 100
    assert options["pool_timeout"] == settings.DB_POOL_TIMEOUT_SECONDS
    assert options["pool_recycle"] == settings.DB_POOL_RECYCLE_SECONDS
    assert options["hide_parameters"] is True and options["echo"] is False and options["pool_pre_ping"]
    connect = options["connect_args"]
    assert connect["server_settings"]["statement_timeout"] == "30000"
    assert connect["server_settings"]["idle_in_transaction_session_timeout"] == "900000"
    assert connect["command_timeout"] == 35 and connect["timeout"] == settings.DB_CONNECT_TIMEOUT_SECONDS


def test_postgres_disabled_statement_timeout_and_explicit_echo():
    settings = get_settings().model_copy(update={"DB_STATEMENT_TIMEOUT_MS": 0, "DB_ECHO": True})
    options = postgres.engine_options(settings)
    assert options["connect_args"]["command_timeout"] is None
    assert options["connect_args"]["server_settings"]["statement_timeout"] == "0"
    assert options["echo"] is True


def test_echo_is_never_derived_from_app_env():
    settings = get_settings().model_copy(update={"APP_ENV": "development"})
    assert postgres.engine_options(settings)["echo"] is False


async def test_engine_disposal_recreates_lazily(monkeypatch):
    engine = AsyncMock()
    monkeypatch.setattr(postgres, "_engine", engine)
    monkeypatch.setattr(postgres, "_session_factory", object())
    await postgres.dispose_engine()
    engine.dispose.assert_awaited_once()
    assert postgres._engine is None and postgres._session_factory is None
    await postgres.dispose_engine()  # idempotent without an engine


def test_redis_clients_are_bounded_and_never_retry_commands():
    settings = get_settings()
    options = redis_db.client_options(settings, max_connections=7)
    assert options["socket_connect_timeout"] == 2 and options["socket_timeout"] == 5
    assert options["socket_timeout"] > 2  # exceeds the XREADGROUP BLOCK interval
    assert options["health_check_interval"] == 30 and options["retry_on_timeout"] is False
    assert options["retry"]._retries == 0  # a retried XADD could duplicate an event
    client = redis_db.build_client(settings, max_connections=7)
    pool = client.connection_pool
    assert isinstance(pool, BlockingConnectionPool)
    assert pool.max_connections == 7 and pool.timeout == settings.REDIS_POOL_TIMEOUT_SECONDS
    assert pool.connection_kwargs["socket_timeout"] == 5


async def test_redis_init_creates_separate_stream_pool_and_close_releases_both(monkeypatch):
    general, stream = AsyncMock(), AsyncMock()
    built = iter([general, stream])
    monkeypatch.setattr(redis_db, "build_client", lambda settings, max_connections: next(built))
    await redis_db.init_redis()
    assert redis_db.get_redis_client() is general and redis_db.get_stream_redis_client() is stream
    general.ping.assert_awaited_once()
    await redis_db.close_redis()
    general.aclose.assert_awaited_once()
    stream.aclose.assert_awaited_once()
    assert redis_db.get_stream_redis_client() is None
    with pytest.raises(RuntimeError):
        redis_db.get_redis_client()


def test_neo4j_driver_deadlines():
    options = neo4j_db.driver_options(get_settings())
    assert options == {"connection_timeout": 5, "connection_acquisition_timeout": 10,
                       "max_transaction_retry_time": 15, "max_connection_pool_size": 50}


async def test_neo4j_init_passes_deadlines(monkeypatch):
    driver = AsyncMock()
    with patch.object(neo4j_db.AsyncGraphDatabase, "driver", return_value=driver) as create:
        await neo4j_db.init_neo4j()
        await neo4j_db.close_neo4j()
    assert create.call_args.kwargs["connection_acquisition_timeout"] == 10
    driver.close.assert_awaited_once()


async def test_lifespan_shutdown_closes_neo4j_redis_then_disposes_postgres():
    from app import main

    order = []

    def record(name):
        return AsyncMock(side_effect=lambda: order.append(name))

    lease = AsyncMock()
    lease.__aenter__.return_value = AsyncMock(healthy=True)

    async def consumer(**kwargs):
        await __import__("asyncio").Event().wait()

    collector = AsyncMock()
    collector.start_with_retry.return_value = False
    with (
        patch.object(main, "TelemetryCollectorRunner", return_value=collector),
        patch.object(main, "init_redis", AsyncMock()), patch.object(main, "init_neo4j", AsyncMock()),
        patch.object(main, "close_redis", record("redis")), patch.object(main, "close_neo4j", record("neo4j")),
        patch.object(main, "dispose_engine", record("postgres")),
        patch.object(main, "ApiRealtimeLease", return_value=lease),
        patch.object(main, "get_redis_client", return_value=AsyncMock()),
        patch.object(main, "ensure_consumer_groups", AsyncMock()),
        patch.object(main, "run_consumer_loop", consumer),
        patch.object(main, "_run_topology_workspace_backfill", AsyncMock(return_value=0)),
        patch.object(main, "_ensure_graph_schema", AsyncMock()),
    ):
        async with main.lifespan(FastAPI()):
            pass
    assert order == ["neo4j", "redis", "postgres"]
