"""ADR026 authorization-before-paging and owner-local summary regressions."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.modules.intent.history import IntentHistoryRepository, IntentHistoryService
from app.modules.network.service import NetworkService
from app.modules.simulation.history import SimulationHistoryRepository, SimulationHistoryService


@pytest.mark.parametrize("service_type", [SimulationHistoryService, IntentHistoryService])
@pytest.mark.parametrize("denial", ["workspace", "network"])
async def test_scope_denial_precedes_history_count(service_type, denial):
    service = service_type(AsyncMock(), AsyncMock())
    service.workspaces = AsyncMock()
    service.networks = AsyncMock(spec=NetworkService)
    service.repository = AsyncMock()
    target = (service.workspaces.get_active_workspace if denial == "workspace"
              else service.networks.assert_network_workspace_access)
    target.side_effect = HTTPException(403, "Revoked or wrong tenant")
    with pytest.raises(HTTPException):
        await service.list_page(workspace_id=uuid.uuid4(), network_id=uuid.uuid4(),
                                user_id="actor", claim_org_id=uuid.uuid4(), page=2, page_size=20)
    service.repository.list_page.assert_not_awaited()


@pytest.mark.parametrize("service_type", [SimulationHistoryService, IntentHistoryService])
@pytest.mark.parametrize("network_id", [None, uuid.UUID(int=2)])
async def test_current_owner_scope_is_checked_before_list(service_type, network_id):
    service = service_type(AsyncMock(), AsyncMock())
    service.workspaces = AsyncMock()
    service.networks = AsyncMock(spec=NetworkService)
    service.repository = AsyncMock()
    workspace_id, org_id = uuid.uuid4(), uuid.uuid4()
    await service.list_page(workspace_id=workspace_id, network_id=network_id,
                            user_id="actor", claim_org_id=org_id, page=3, page_size=20)
    service.workspaces.get_active_workspace.assert_awaited_once_with(
        workspace_id, user_id="actor", claim_org_id=org_id,
    )
    if network_id:
        service.networks.assert_network_workspace_access.assert_awaited_once_with(
            network_id=network_id, requested_workspace_id=workspace_id,
            actor_user_id="actor", claim_org_id=org_id,
        )
    else:
        service.networks.assert_network_workspace_access.assert_not_awaited()
    service.repository.list_page.assert_awaited_once_with(workspace_id, network_id, 3, 20)


@pytest.mark.parametrize("repository,table,id_field", [
    (SimulationHistoryRepository, "simulations", "simulation_id"),
    (IntentHistoryRepository, "intents", "intent_id"),
])
@pytest.mark.parametrize("empty", [True, False])
async def test_count_and_page_share_snapshot_and_use_bounded_owner_projection(repository, table, id_field, empty):
    workspace_id, network_id = uuid.uuid4(), uuid.uuid4()
    data = {id_field: None if empty else uuid.uuid4(), "workspace_id": workspace_id,
            "network_id": network_id, "status": "draft", "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC)}
    data["scenario_name" if table == "simulations" else "action"] = "Example"
    row = MagicMock()
    row._mapping = data
    row.__getitem__.return_value = 41
    result = MagicMock()
    result.all.return_value = [row]
    db = AsyncMock()
    db.execute.return_value = result
    page = await repository(db).list_page(workspace_id, network_id, 3, 20)
    assert page.total == 41
    assert page.page == 3
    assert len(page.items) == (0 if empty else 1)
    db.execute.assert_awaited_once()
    statement = db.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert f"ORDER BY {table}.created_at DESC, {table}.{id_field} DESC" in sql
    assert "LIMIT 20 OFFSET 40" in sql
    assert sql.count(str(workspace_id)) == 2
    assert sql.count(str(network_id)) == 2
    assert "LEFT OUTER JOIN" in sql
    assert "run_output" not in sql and "execution_provenance" not in sql
    assert "organizations" not in sql and "networks" not in sql
    if table == "intents":
        assert "substr(" in sql and "120" in sql
