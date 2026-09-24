"""Credential URI escaping and Alembic interpolation without secret output."""

import runpy
from unittest.mock import MagicMock
from urllib.parse import unquote, urlsplit

import pytest
from pydantic import ValidationError
from redis.connection import parse_url
from sqlalchemy.dialects.postgresql import asyncpg, psycopg2
from sqlalchemy.engine import make_url

from alembic import context
from alembic.config import Config
from app.core.config import Settings


@pytest.mark.parametrize(
    "password", ["normal", "", "@/#?:% +", "literal%40", "line\nreturn\rtab\t"]
)
def test_password_round_trip_without_double_encoding(password):
    settings = Settings(
        _env_file=None, POSTGRES_PASSWORD=password, REDIS_PASSWORD=password
    )
    for dsn in (settings.POSTGRES_DSN, settings.POSTGRES_SYNC_DSN):
        parsed = make_url(dsn)
        assert parsed.password == password
        assert parsed.host == settings.POSTGRES_HOST
        assert "\n" not in dsn and "\r" not in dsn
    parsed_redis = parse_url(settings.REDIS_URL)
    assert parsed_redis.get("password", "") == password
    assert unquote(urlsplit(settings.REDIS_URL).password) == password


@pytest.mark.parametrize(
    "database", ["nanfo", "db space", "db@/#%", "db%2F", "db\\path"]
)
def test_database_and_credentials_reach_drivers_exactly(database):
    settings = Settings(
        _env_file=None,
        POSTGRES_USER="name%/@#?",
        POSTGRES_PASSWORD="password%/@#?",
        POSTGRES_DB=database,
    )
    for dsn, dialect, database_key in (
        (settings.POSTGRES_DSN, asyncpg.dialect(), "database"),
        (settings.POSTGRES_SYNC_DSN, psycopg2.dialect(), "dbname"),
    ):
        url = make_url(dsn)
        assert url.database == database
        assert url.username == settings.POSTGRES_USER
        assert url.password == settings.POSTGRES_PASSWORD
        assert not url.query
        args, kwargs = dialect.create_connect_args(url)
        assert args == []
        assert kwargs[database_key] == database
        assert kwargs["user"] == settings.POSTGRES_USER
        assert kwargs["password"] == settings.POSTGRES_PASSWORD
        assert kwargs["host"] == settings.POSTGRES_HOST
        assert kwargs["port"] == settings.POSTGRES_PORT


@pytest.mark.parametrize(
    "database",
    [
        "",
        "db?host=other",
        "db\nname",
        "db\rname",
        "db\tname",
        "db\x00name",
        "db\x7fname",
    ],
)
def test_unsupported_database_names_rejected_without_input_echo(database):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, POSTGRES_DB=database)
    assert "input_value=" not in str(error.value)
    assert "Database name must be nonempty" in str(error.value)


@pytest.mark.parametrize(
    "host",
    ["host@evil", "host/path", "host#fragment", "host?query", "host\nsecret", ""],
)
def test_host_delimiters_and_newlines_rejected_without_input_echo(host):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, POSTGRES_HOST=host)
    assert "input_value=" not in str(error.value)


def test_settings_repr_omits_secrets_and_computed_dsns():
    secret = "unique-credential-sentinel"
    settings = Settings(
        _env_file=None,
        POSTGRES_PASSWORD=secret,
        REDIS_PASSWORD=secret,
        NEO4J_PASSWORD=secret,
        JWT_SECRET_KEY=secret,
    )
    assert secret not in repr(settings)
    assert "POSTGRES_DSN" not in repr(settings)


@pytest.mark.parametrize("password", ["plain", "@/#?%literal%40\n"])
@pytest.mark.parametrize("database", ["nanfo", "db space/@#%2F"])
def test_actual_alembic_environment_escapes_interpolation_once(
    monkeypatch, password, database
):
    from app.core import config as core_config

    settings = Settings(
        _env_file=None, POSTGRES_PASSWORD=password, POSTGRES_DB=database
    )
    config = Config()
    monkeypatch.setattr(core_config, "get_settings", lambda: settings)
    monkeypatch.setattr(context, "config", config, raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    configure = MagicMock()
    execute = MagicMock()
    monkeypatch.setattr(context, "configure", configure)
    monkeypatch.setattr(context, "begin_transaction", MagicMock())
    monkeypatch.setattr(context, "execute", execute)
    monkeypatch.setattr(context, "run_migrations", MagicMock())
    monkeypatch.delenv("NANFO_MIGRATION_LOCK_TIMEOUT", raising=False)
    runpy.run_path("alembic/env.py")
    assert config.get_main_option("sqlalchemy.url") == settings.POSTGRES_SYNC_DSN
    url = make_url(configure.call_args.kwargs["url"])
    assert url.password == password
    assert url.database == database
    assert not url.query
    # ADR-028: per-revision transactions, type/default comparison and a bounded lock wait.
    options = configure.call_args.kwargs
    assert options["transaction_per_migration"] is True
    assert options["compare_type"] is True and options["compare_server_default"] is True
    execute.assert_called_once_with("SET lock_timeout = '5s'")
