"""ADR-028 task 13: experimental leases use the database clock (clock_timestamp)."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.autonomy.experimental.persistence import LabRepository
from app.modules.autonomy.experimental.schemas import utcnow


def repository(clock):
    statements = []

    async def scalar(statement):
        statements.append(statement)
        return clock

    return LabRepository(SimpleNamespace(scalar=scalar)), statements


async def test_database_clock_is_clock_timestamp_not_transaction_or_host_time():
    skewed = utcnow() + timedelta(minutes=7)
    repo, statements = repository(skewed)
    assert await repo.now() == skewed == repo.clock
    sql = str(statements[0].compile(dialect=postgresql.dialect()))
    assert "clock_timestamp()" in sql and "now()" not in sql.replace("clock_timestamp()", "")


async def test_ownership_and_renewal_follow_the_database_clock_under_host_skew():
    token = uuid4()
    database_now = utcnow() + timedelta(seconds=30)  # host clock lags the database
    repo, _ = repository(database_now)
    await repo.now()
    resource = SimpleNamespace(owner_run_id="r", fence=1)
    run = SimpleNamespace(run_id="r", fence=1, released=False, lease_token=token,
                          lease_until=utcnow() + timedelta(seconds=10))  # valid by host clock only
    with pytest.raises(ValueError, match="ownership_or_lease_lost"):
        repo.owned(resource, run, token)
    assert repo.renew(run, 10) == database_now + timedelta(seconds=10)
    repo.owned(resource, run, token)


async def test_missing_database_clock_fails_closed():
    repo, _ = repository(None)
    with pytest.raises(ValueError, match="database_clock_unavailable"):
        await repo.now()
    naive, _ = repository(utcnow().replace(tzinfo=None))
    with pytest.raises(ValueError, match="database_clock_unavailable"):
        await naive.now()
    fresh = LabRepository(SimpleNamespace(scalar=AsyncMock()))
    with pytest.raises(ValueError, match="database_clock_unavailable"):
        fresh.owned(SimpleNamespace(), SimpleNamespace(), uuid4())
    with pytest.raises(ValueError, match="database_clock_unavailable"):
        fresh.renew(SimpleNamespace(), 5)
