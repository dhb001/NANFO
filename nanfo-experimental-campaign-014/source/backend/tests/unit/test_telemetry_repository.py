"""Unit tests for telemetry repository read query behavior (VS2 Step 7)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.telemetry.repository import TelemetryRecordRepository


@pytest.mark.asyncio
async def test_list_history_executes_count_and_page_queries(mock_db):
    count_result = MagicMock()
    count_result.scalar_one.return_value = 2

    rows_result = MagicMock()
    rows_scalars = MagicMock()
    rows_scalars.all.return_value = [object(), object()]
    rows_result.scalars.return_value = rows_scalars

    mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

    repo = TelemetryRecordRepository(mock_db)
    rows, total = await repo.list_history(
        network_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        metric="cpu_usage",
        page=2,
        page_size=10,
    )

    assert total == 2
    assert len(rows) == 2
    assert mock_db.execute.await_count == 2


@pytest.mark.asyncio
async def test_list_for_device_executes_count_and_page_queries(mock_db):
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    rows_result = MagicMock()
    rows_scalars = MagicMock()
    rows_scalars.all.return_value = [object()]
    rows_result.scalars.return_value = rows_scalars

    mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])

    repo = TelemetryRecordRepository(mock_db)
    device_id = uuid.uuid4()
    network_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    rows, total = await repo.list_for_device(
        device_id=device_id,
        network_id=network_id,
        workspace_id=workspace_id,
        metric=None,
        page=1,
        page_size=20,
    )

    assert total == 1
    assert len(rows) == 1
    assert mock_db.execute.await_count == 2


@pytest.mark.asyncio
async def test_count_all_and_latest_observed_at(mock_db):
    latest_result = MagicMock()
    latest_result.scalar_one_or_none.return_value = None

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    mock_db.execute = AsyncMock(side_effect=[latest_result, count_result])

    repo = TelemetryRecordRepository(mock_db)
    latest = await repo.get_latest_observed_at()
    count = await repo.count_all()

    assert latest is None
    assert count == 0


@pytest.mark.asyncio
async def test_get_latest_scope_returns_workspace_and_network_from_latest_row(mock_db):
    result = MagicMock()
    workspace_id = uuid.uuid4()
    network_id = uuid.uuid4()
    result.first.return_value = (workspace_id, network_id)

    mock_db.execute = AsyncMock(return_value=result)

    repo = TelemetryRecordRepository(mock_db)
    latest_workspace_id, latest_network_id = await repo.get_latest_scope()

    assert latest_workspace_id == workspace_id
    assert latest_network_id == network_id


@pytest.mark.asyncio
async def test_get_latest_scope_returns_none_tuple_when_no_rows(mock_db):
    result = MagicMock()
    result.first.return_value = None
    mock_db.execute = AsyncMock(return_value=result)

    repo = TelemetryRecordRepository(mock_db)
    latest_workspace_id, latest_network_id = await repo.get_latest_scope()

    assert latest_workspace_id is None
    assert latest_network_id is None
