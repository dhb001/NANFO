"""Real PostgreSQL summary projection, tied ordering and page/count isolation."""

import os
import uuid
from datetime import UTC, datetime

import pytest

from app.modules.intent.history import IntentHistoryRepository
from app.modules.intent.models import Intent
from app.modules.simulation.history import SimulationHistoryRepository
from tests.integration.test_simulation_postgres import sessions  # noqa: F401
from tests.simulation_support import record

pytestmark = pytest.mark.skipif(not os.environ.get("SIMULATION_TEST_DSN"), reason="SIMULATION_TEST_DSN not configured")


@pytest.mark.parametrize("kind", ["simulation", "intent"])
async def test_history_pages_ties_null_network_and_other_tenants(sessions, kind):  # noqa: F811
    workspace, network, other_network, other_workspace = [uuid.uuid4() for _ in range(4)]
    now = datetime(2026, 9, 20, tzinfo=UTC)
    ids = [uuid.UUID(int=index) for index in range(1, 42)]

    def make(row_id, ws=workspace, net=network):
        if kind == "simulation":
            return record(simulation_id=row_id, workspace_id=ws, network_id=net, created_at=now, updated_at=now)
        return Intent(intent_id=row_id, workspace_id=ws, network_id=net, intent_kind="unil",
                      intent_payload={"action": "a" * 150, "scope": {"large": "omitted"}}, status="validated",
                      requested_by_user_id="actor", requested_at=now, created_at=now, updated_at=now,
                      correlation_id=uuid.uuid4())

    async with sessions() as db:
        db.add_all([make(row_id) for row_id in ids])
        db.add(make(uuid.UUID(int=100), net=other_network))
        db.add(make(uuid.UUID(int=101), ws=other_workspace))
        if kind == "intent":
            db.add(make(uuid.UUID(int=102), net=None))
        await db.commit()
        repository = SimulationHistoryRepository(db) if kind == "simulation" else IntentHistoryRepository(db)
        pages = [await repository.list_page(workspace, network, page, 20) for page in range(1, 5)]
        assert [len(page.items) for page in pages] == [20, 20, 1, 0]
        assert [page.total for page in pages] == [41] * 4
        assert [getattr(item, f"{kind}_id") for page in pages for item in page.items] == list(reversed(ids))
        all_workspace = await repository.list_page(workspace, None, 1, 200)
        assert all_workspace.total == (43 if kind == "intent" else 42)
        if kind == "intent":
            assert all(item.action == "a" * 120 for item in all_workspace.items)
            assert all("intent_payload" not in item.model_dump() for item in all_workspace.items)
            assert any(item.network_id is None for item in all_workspace.items)
        empty = await repository.list_page(uuid.uuid4(), None, 1, 20)
        assert empty.total == 0 and empty.items == []
