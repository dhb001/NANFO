"""Unit tests for identity repository behavior."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.identity.repository import UserRepository


@pytest.mark.asyncio
async def test_get_roles_for_user_queries_roles_by_user_id(mock_db):
    result = MagicMock()
    result.scalars.return_value.all.return_value = ["Admin", "Operator"]
    mock_db.execute = AsyncMock(return_value=result)

    repo = UserRepository(mock_db)
    user = SimpleNamespace(user_id=uuid.uuid4())

    roles = await repo.get_roles_for_user(user)

    assert roles == ["Admin", "Operator"]
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_roles_for_user_returns_empty_list_when_no_roles(mock_db):
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=result)

    repo = UserRepository(mock_db)
    user = SimpleNamespace(user_id=uuid.uuid4())

    roles = await repo.get_roles_for_user(user)

    assert roles == []
    mock_db.execute.assert_awaited_once()
