"""ADR026 selection narrows current owner authorization, never token authority."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.alert.service import AlertService

WORKSPACE, NETWORK, ORG = (uuid.UUID(int=i) for i in (101, 102, 103))
ARGS = dict(status_filter=None, severity_filter=None, source_filter=None,
            correlation_id_filter=None, search_filter=None, limit=200, actor_user_id=str(uuid.UUID(int=1)))


@pytest.fixture
def service(mock_db):
    service = AlertService(db=mock_db, redis=None)
    service._accessible_scopes = AsyncMock(return_value=([(WORKSPACE, ORG, [NETWORK])], []))
    service._workspace_svc.get_active_workspace = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    service._network_svc.assert_network_workspace_access = AsyncMock(return_value=SimpleNamespace(workspace_id=WORKSPACE))
    service._repo.list_alerts = AsyncMock(return_value=[])
    return service


@pytest.mark.parametrize("with_workspace", [True, False])
async def test_network_selection_uses_owner_and_narrows_repository(service, with_workspace):
    await service.list_alerts(**ARGS, claim_org_id=ORG, network_id_filter=NETWORK,
                             workspace_id_filter=WORKSPACE if with_workspace else None)
    service._network_svc.assert_network_workspace_access.assert_awaited_once_with(
        network_id=NETWORK, requested_workspace_id=WORKSPACE if with_workspace else None,
        actor_user_id=ARGS["actor_user_id"], claim_org_id=ORG)
    service._accessible_scopes.assert_awaited_once_with(ARGS["actor_user_id"], WORKSPACE, ORG)
    assert service._repo.list_alerts.await_args.kwargs["network_id"] == NETWORK


async def test_workspace_selection_uses_current_membership(service):
    await service.list_alerts(**ARGS, workspace_id_filter=WORKSPACE, claim_org_id=ORG)
    service._workspace_svc.get_active_workspace.assert_awaited_once_with(
        WORKSPACE, user_id=ARGS["actor_user_id"], claim_org_id=ORG)
    service._accessible_scopes.assert_awaited_once_with(ARGS["actor_user_id"], WORKSPACE, ORG)


async def test_selection_cannot_override_workspace_claim(service):
    with pytest.raises(HTTPException) as denied:
        await service.list_alerts(**ARGS, requested_workspace_id=uuid.UUID(int=999), workspace_id_filter=WORKSPACE)
    assert denied.value.status_code == 403
    service._repo.list_alerts.assert_not_awaited()
    service._accessible_scopes.assert_not_awaited()


@pytest.mark.parametrize("owner", ["workspace", "network"])
@pytest.mark.parametrize("status", [403, 404])
async def test_foreign_revoked_or_deleted_selection_denied_before_alert_query(service, owner, status):
    if owner == "workspace":
        service._workspace_svc.get_active_workspace.side_effect = HTTPException(status, "Denied")
        selection = dict(workspace_id_filter=WORKSPACE)
    else:
        service._network_svc.assert_network_workspace_access.side_effect = HTTPException(status, "Denied")
        selection = dict(network_id_filter=NETWORK)
    with pytest.raises(HTTPException) as denied:
        await service.list_alerts(**ARGS, **selection)
    assert denied.value.status_code == status
    service._repo.list_alerts.assert_not_awaited()


async def test_no_selection_preserves_all_authorized_semantics(service):
    await service.list_alerts(**ARGS)
    service._accessible_scopes.assert_awaited_once_with(ARGS["actor_user_id"], None, None)
    service._workspace_svc.get_active_workspace.assert_not_awaited()
    service._network_svc.assert_network_workspace_access.assert_not_awaited()
    assert service._repo.list_alerts.await_args.kwargs["network_id"] is None
