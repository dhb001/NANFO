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
async def test_repository_has_no_cross_tenant_latest_scope_lookup(mock_db):
    """ADR-028 C12 regression: platform SLO alerts must never borrow a tenant scope."""
    assert not hasattr(TelemetryRecordRepository(mock_db), "get_latest_scope")


@pytest.mark.asyncio
@pytest.mark.parametrize("device", [False, True])
async def test_capped_count_limits_the_counted_subquery(mock_db, device):
    from sqlalchemy.dialects import postgresql

    count_result = MagicMock()
    count_result.scalar_one.return_value = 10_001
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[count_result, rows_result])
    repo = TelemetryRecordRepository(mock_db)
    scope = {"network_id": uuid.uuid4(), "workspace_id": uuid.uuid4(), "metric": None, "page": 1, "page_size": 5}
    if device:
        rows, total = await repo.list_for_device(device_id=uuid.uuid4(), count_cap=10_000, **scope)
    else:
        rows, total = await repo.list_history(count_cap=10_000, **scope)
    assert (rows, total) == ([], 10_001)
    count_sql = str(mock_db.execute.call_args_list[0].args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "LIMIT 10001" in count_sql
    # The bounded count selects a single key column, not whole JSONB rows.
    assert "telemetry_records.tags" not in count_sql


@pytest.mark.asyncio
@pytest.mark.parametrize("reltuples,exact,expected", [
    (5_000_000, None, (5_000_000, True)),   # large table: planner estimate, no scan
    (-1, 42, (42, False)),                  # never analyzed: bounded exact count
    (3, 10_001, (10_001, True)),            # stale small estimate but big table
])
async def test_estimate_total_records_never_full_counts(mock_db, reltuples, exact, expected):
    mock_db.scalar = AsyncMock(return_value=reltuples)
    count_result = MagicMock()
    count_result.scalar_one.return_value = exact
    mock_db.execute = AsyncMock(return_value=count_result)
    assert await TelemetryRecordRepository(mock_db).estimate_total_records() == expected
    if exact is None:
        mock_db.execute.assert_not_awaited()
    else:
        from sqlalchemy.dialects import postgresql

        sql = str(mock_db.execute.await_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        assert "LIMIT 10001" in sql


@pytest.mark.asyncio
async def test_latest_observed_at_can_exclude_future_rows(mock_db):
    from datetime import UTC, datetime

    from sqlalchemy.dialects import postgresql

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=result)
    bound = datetime(2026, 9, 23, tzinfo=UTC)
    await TelemetryRecordRepository(mock_db).get_latest_observed_at(not_after=bound)
    sql = str(mock_db.execute.await_args.args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "max(telemetry_records.observed_at)" in sql and "observed_at <=" in sql
