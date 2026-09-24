"""ADR-028 C9 operator CLI: python -m scripts.revoke_user_sessions."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.errors import DependencyUnavailableError
from app.core.security import create_refresh_token, decode_token
from app.modules.identity.repository import UserRepository
from app.modules.identity.sessions import SessionRepository
from scripts import revoke_user_sessions as cli

USER = uuid.UUID(int=701)


@pytest.fixture
def sessions(mock_db):
    @asynccontextmanager
    async def factory():
        yield mock_db

    return factory


@pytest.fixture
def account(monkeypatch):
    user = SimpleNamespace(user_id=USER, email="ops@example.com", is_active=True)
    monkeypatch.setattr(UserRepository, "get_by_id", AsyncMock(side_effect=lambda user_id: user if user_id == USER else None))
    monkeypatch.setattr(UserRepository, "get_by_email", AsyncMock(
        side_effect=lambda email: user if email == user.email else None))
    monkeypatch.setattr(UserRepository, "set_active", AsyncMock(return_value=True))
    return user


async def _session(redis, user_id=USER):
    token, _ = create_refresh_token(user_id=str(user_id))
    await SessionRepository(redis).create(decode_token(token, token_type="refresh"), token)
    return token


def test_parser_requires_exactly_one_target():
    with pytest.raises(SystemExit):
        cli.parser().parse_args([])
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--user-id", str(USER), "--email", "a@b.c"])
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--user-id", str(USER), "--reason", "deactivated"])
    args = cli.parser().parse_args(["--email", "a@b.c", "--deactivate"])
    assert args.deactivate and args.reason == "operator_request"


async def test_revokes_every_session_by_user_id(sessions, account, fake_redis, mock_db):
    tokens = [await _session(fake_redis) for _ in range(3)]
    other = await _session(fake_redis, uuid.UUID(int=702))
    result = await cli.execute(cli.parser().parse_args(["--user-id", str(USER)]), sessions=sessions, redis=fake_redis)
    assert result["revoked_sessions"] == 3 and result["reason"] == "operator_request"
    assert result["user_id"] == str(USER)
    serialized = json.dumps(result)
    assert all(token not in serialized for token in tokens)
    assert await fake_redis.exists(SessionRepository.key(decode_token(other, token_type="refresh")["sid"]))
    mock_db.commit.assert_awaited()


async def test_deactivate_by_email_then_revokes(sessions, account, fake_redis):
    await _session(fake_redis)
    result = await cli.execute(cli.parser().parse_args(["--email", account.email, "--deactivate"]),
                               sessions=sessions, redis=fake_redis)
    assert (result["reason"], result["revoked_sessions"]) == ("deactivated", 1)
    UserRepository.set_active.assert_awaited_once_with(USER, False)


async def test_unknown_user_is_a_lookup_error(sessions, account, fake_redis):
    with pytest.raises(LookupError):
        await cli.execute(cli.parser().parse_args(["--email", "nobody@example.com"]),
                          sessions=sessions, redis=fake_redis)
    with pytest.raises(LookupError):
        await cli.execute(cli.parser().parse_args(["--user-id", str(uuid.uuid4())]),
                          sessions=sessions, redis=fake_redis)


@pytest.mark.parametrize(("error", "code"), [
    (LookupError("User not found."), 2), (DependencyUnavailableError("redis"), 3), (OSError("refused"), 3),
])
def test_main_exit_codes(capsys, error, code):
    with patch.object(cli, "execute", AsyncMock(side_effect=error)):
        assert cli.main(["--user-id", str(USER)]) == code
    assert json.loads(capsys.readouterr().err)["error"]


def test_main_prints_one_json_line(capsys):
    result = {"user_id": str(USER), "reason": "operator_request", "revoked_sessions": 0, "correlation_id": "c"}
    with patch.object(cli, "execute", AsyncMock(return_value=result)):
        assert cli.main(["--user-id", str(USER)]) == 0
    assert json.loads(capsys.readouterr().out) == result
