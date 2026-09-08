"""NANFO Backend — Async PostgreSQL engine and session factory.

Uses SQLAlchemy 2.0 async with asyncpg driver.
Engine creation is lazy (first call to get_engine()) so that test environments
can set environment variables before triggering engine instantiation.
All module models define their tables via the shared Base declared here.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all SQLAlchemy ORM models."""


_engine = None
_session_factory = None


def get_engine():
    """Return (and lazily create) the shared async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.POSTGRES_DSN,
            echo=settings.APP_ENV == "development",
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
    return _engine


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
