"""NANFO Backend — Async PostgreSQL engine and session factory.

Uses SQLAlchemy 2.0 async with asyncpg driver.
Engine creation is lazy (first call to get_engine()) so that test environments
can set environment variables before triggering engine instantiation.
All module models define their tables via the shared Base declared here.

Pool bounds (ADR-028): every process (API and each worker) opens at most
``DB_POOL_SIZE + DB_MAX_OVERFLOW`` connections; defaults 5 + 5 keep the API plus
six workers (70) below PostgreSQL's default ``max_connections`` of 100.

Server-side timeouts are applied per connection through asyncpg
``server_settings``. ``statement_timeout`` bounds every statement (0 disables);
``idle_in_transaction_session_timeout`` ends only leaked open transactions. Session
advisory locks held by the fleet collector and autonomy execution are acquired by
short statements on connections that are idle *outside* a transaction, so neither
timeout can release them (see config validation for the idle bound).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all SQLAlchemy ORM models."""


_engine = None
_session_factory = None


def engine_options(settings) -> dict:
    """Keyword arguments for create_async_engine derived from settings (testable)."""
    statement_ms = settings.DB_STATEMENT_TIMEOUT_MS
    server_settings = {
        "statement_timeout": str(statement_ms),
        "idle_in_transaction_session_timeout": str(settings.DB_IDLE_IN_TRANSACTION_TIMEOUT_MS),
        "application_name": f"nanfo-{settings.NANFO_SERVICE_ROLE}",
    }
    connect_args: dict = {
        "server_settings": server_settings,
        "timeout": settings.DB_CONNECT_TIMEOUT_SECONDS,
        # Client-side guard just above the server bound; None when disabled.
        "command_timeout": statement_ms / 1000 + 5 if statement_ms else None,
    }
    return {
        "echo": settings.DB_ECHO,
        "hide_parameters": True,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
        "pool_recycle": settings.DB_POOL_RECYCLE_SECONDS,
        "pool_pre_ping": True,
        "connect_args": connect_args,
    }


def get_engine():
    """Return (and lazily create) the shared async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.POSTGRES_DSN, **engine_options(settings))
    return _engine


async def dispose_engine() -> None:
    """Close pooled connections on shutdown; a later get_engine() recreates the pool."""
    global _engine, _session_factory
    engine, _engine, _session_factory = _engine, None, None
    if engine is not None:
        await engine.dispose()


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


def AsyncSessionLocal() -> AsyncSession:
    """Return a new async session from the shared session factory.

    Usage: async with AsyncSessionLocal() as session: ...
    AsyncSession is an async context manager, so this works identically
    to the previous eager-created sessionmaker instance.
    """
    return _get_session_factory()()
