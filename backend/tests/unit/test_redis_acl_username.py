"""ADR-028 C24: Redis ACL user support for every client built from the settings/env."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

import pytest
from redis.asyncio.connection import parse_url

from app.core.config import Settings
from app.db import redis as redis_db
from scripts import stream_retention

PASSWORD = "p@ss/w:rd%#?"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, REDIS_PASSWORD=PASSWORD, REDIS_HOST="cache", REDIS_PORT=6380,
                    REDIS_DB=2, **overrides)


def test_without_username_the_url_authenticates_as_default_user_as_before():
    url = _settings().REDIS_URL
    assert url.startswith("redis://:")
    parsed = parse_url(url)
    assert "username" not in parsed or parsed["username"] in (None, "")
    assert parsed["password"] == PASSWORD and parsed["host"] == "cache" and parsed["port"] == 6380
    assert parsed["db"] == 2


@pytest.mark.parametrize("username", ["nanfo", "svc:api@x/y", "ünïcode"])
def test_username_is_quoted_into_the_url_and_round_trips(username):
    url = _settings(REDIS_USERNAME=username).REDIS_URL
    assert unquote(urlsplit(url).username) == username
    parsed = parse_url(url)
    assert parsed["username"] == username and parsed["password"] == PASSWORD
    assert parsed["host"] == "cache" and parsed["db"] == 2


def test_blank_username_is_treated_as_unset():
    assert _settings(REDIS_USERNAME="  ").REDIS_URL == _settings().REDIS_URL


def test_redis_url_is_never_rendered_in_repr():
    settings = _settings(REDIS_USERNAME="nanfo")
    assert PASSWORD not in repr(settings) and "REDIS_URL" not in repr(settings)


def test_shared_clients_authenticate_with_the_acl_user():
    settings = _settings(REDIS_USERNAME="nanfo")
    client = redis_db.build_client(settings, max_connections=4)
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["username"] == "nanfo" and kwargs["password"] == PASSWORD
    # Pool bounds are unaffected by the credential change.
    assert client.connection_pool.max_connections == 4 and kwargs["socket_timeout"] == settings.REDIS_SOCKET_TIMEOUT_SECONDS


def test_shared_clients_without_username_keep_default_authentication():
    kwargs = redis_db.build_client(_settings(), max_connections=4).connection_pool.connection_kwargs
    assert kwargs.get("username") in (None, "") and kwargs["password"] == PASSWORD


def test_stream_retention_env_url_includes_optional_acl_user():
    base = {"REDIS_HOST": "redis", "REDIS_PASSWORD": "p@ss/word", "REDIS_PORT": "6380", "REDIS_DB": "2"}
    assert stream_retention.redis_url_from_environment(base) == "redis://:p%40ss%2Fword@redis:6380/2"
    assert stream_retention.redis_url_from_environment({**base, "REDIS_USERNAME": ""}) == (
        "redis://:p%40ss%2Fword@redis:6380/2")
    url = stream_retention.redis_url_from_environment({**base, "REDIS_USERNAME": "nanfo:ops"})
    assert url == "redis://nanfo%3Aops:p%40ss%2Fword@redis:6380/2"
    parsed = parse_url(url)
    assert parsed["username"] == "nanfo:ops" and parsed["password"] == "p@ss/word"
    # An explicit URL still wins unchanged.
    assert stream_retention.redis_url_from_environment(
        {**base, "REDIS_USERNAME": "nanfo", "STREAM_RETENTION_REDIS_URL": "redis://x"}) == "redis://x"
