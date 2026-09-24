"""ADR026 selection narrows current owner authorization, never token authority.

ADR-028: the resolved selection feeds one SQL scope predicate (``AlertListScope``)
instead of per-row owner re-checks.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.alert.scope import AlertListScope
from app.modules.alert.service import AlertService

WORKSPACE, NETWORK, ORG = (uuid.UUID(int=i) for i in (101, 102, 103))
ARGS = dict(status_filter=None, severity_filter=None, source_filter=None,
            correlation_id_filter=None, search_filter=None, limit=200, actor_user_id=str(uuid.UUID(int=1)))


@pytest.fixture
def service(mock_db):
    service = AlertService(db=mock_db, redis=None)
    service._accessible_scopes = AsyncMock(return_value=AlertListScope(
        workspace_orgs={WORKSPACE: ORG}, networks={NETWORK: WORKSPACE}))
    service._workspace_svc.get_active_workspace = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    service._network_svc.assert_network_workspace_access = AsyncMock(return_value=SimpleNamespace(workspace_id=WORKSPACE))
    service._repo.list_alerts = AsyncMock(return_value=[])
    service._repo.count_alerts = AsyncMock(return_value={})
    return service


@pytest.mark.parametrize("with_workspace", [True, False])
async def test_network_selection_uses_owner_and_narrows_repository(service, with_workspace):
    await service.list_alerts(**ARGS, claim_org_id=ORG, network_id_filter=NETWORK,
                             workspace_id_filter=WORKSPACE if with_workspace else None)
    service._network_svc.assert_network_workspace_access.assert_awaited_once_with(
        network_id=NETWORK, requested_workspace_id=WORKSPACE if with_workspace else None,
        actor_user_id=ARGS["actor_user_id"], claim_org_id=ORG)
    # A selected workspace's organization is reused, never looked up again.
    service._accessible_scopes.assert_awaited_once_with(
        ARGS["actor_user_id"], WORKSPACE, ORG, workspace_org_id=ORG if with_workspace else None,
        network_id=NETWORK, platform=False)
    assert service._repo.list_alerts.await_args.kwargs["scope"] is service._accessible_scopes.return_value
    assert service._repo.count_alerts.await_args.kwargs["scope"] is service._accessible_scopes.return_value


async def test_workspace_selection_uses_current_membership(service):
    await service.list_alerts(**ARGS, workspace_id_filter=WORKSPACE, claim_org_id=ORG)
    service._workspace_svc.get_active_workspace.assert_awaited_once_with(
        WORKSPACE, user_id=ARGS["actor_user_id"], claim_org_id=ORG)
    service._accessible_scopes.assert_awaited_once_with(
        ARGS["actor_user_id"], WORKSPACE, ORG, workspace_org_id=ORG, network_id=None, platform=False)


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
    service._accessible_scopes.assert_awaited_once_with(
        ARGS["actor_user_id"], None, None, workspace_org_id=None, network_id=None, platform=False)
    service._workspace_svc.get_active_workspace.assert_not_awaited()
    service._network_svc.assert_network_workspace_access.assert_not_awaited()
    assert service._repo.list_alerts.await_args.kwargs["scope"].network_id is None


async def test_claim_narrowed_scope_without_current_access_is_empty_not_error(mock_db):
    service = AlertService(db=mock_db, redis=None)
    service._workspace_svc.get_active_workspace = AsyncMock(side_effect=HTTPException(403, "Denied"))
    scope = await service._accessible_scopes(ARGS["actor_user_id"], WORKSPACE, None)
    assert scope.empty and scope == AlertListScope()


async def test_unnarrowed_scope_is_built_per_organization_not_per_workspace(mock_db, monkeypatch):
    other_org, workspaces = uuid.UUID(int=104), [uuid.UUID(int=200 + i) for i in range(30)]
    service = AlertService(db=mock_db, redis=None)
    monkeypatch.setattr("app.modules.alert.service.OrgService.list_orgs", AsyncMock(return_value=SimpleNamespace(
        items=[SimpleNamespace(org_id=ORG), SimpleNamespace(org_id=other_org)], total=2)))
    service._workspace_svc.list_accessible_workspace_ids = AsyncMock(
        side_effect=lambda *, user_id, claim_org_id: workspaces[:20] if claim_org_id == ORG else workspaces[20:])
    service._workspace_svc.get_active_workspace = AsyncMock()
    service._network_svc.list_networks = AsyncMock()
    service._repo.legacy_network_ids = AsyncMock(return_value=[])
    scope = await service._accessible_scopes(ARGS["actor_user_id"], None, None)
    assert scope.workspace_orgs == {**dict.fromkeys(workspaces[:20], ORG), **dict.fromkeys(workspaces[20:], other_org)}
    assert scope.member_org_ids == {ORG, other_org}
    assert service._workspace_svc.list_accessible_workspace_ids.await_count == 2
    # No per-workspace membership or network enumeration.
    service._workspace_svc.get_active_workspace.assert_not_awaited()
    service._network_svc.list_networks.assert_not_awaited()


async def test_legacy_network_only_scope_resolves_a_single_network_through_the_owner(mock_db):
    legacy = uuid.UUID(int=300)
    service = AlertService(db=mock_db, redis=None)
    service._workspace_svc.get_active_workspace = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    service._repo.legacy_network_ids = AsyncMock(return_value=[legacy])
    service._network_svc.assert_network_workspace_access = AsyncMock(return_value=SimpleNamespace(workspace_id=WORKSPACE))
    service._network_svc.list_networks = AsyncMock()
    scope = await service._accessible_scopes(ARGS["actor_user_id"], WORKSPACE, None)
    assert scope.networks == {legacy: WORKSPACE}
    service._network_svc.assert_network_workspace_access.assert_awaited_once_with(
        network_id=legacy, requested_workspace_id=None, actor_user_id=ARGS["actor_user_id"], claim_org_id=None)
    service._network_svc.list_networks.assert_not_awaited()


@pytest.mark.parametrize("denial", [403, 404])
async def test_legacy_network_outside_membership_or_deleted_stays_unauthorized(mock_db, denial):
    service = AlertService(db=mock_db, redis=None)
    service._workspace_svc.get_active_workspace = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    service._repo.legacy_network_ids = AsyncMock(return_value=[uuid.UUID(int=301)])
    service._network_svc.assert_network_workspace_access = AsyncMock(side_effect=HTTPException(denial, "Denied"))
    scope = await service._accessible_scopes(ARGS["actor_user_id"], WORKSPACE, None)
    assert scope.networks == {}


async def test_many_legacy_networks_are_resolved_by_one_listing_per_workspace(mock_db):
    legacy = [uuid.UUID(int=400 + i) for i in range(3)]
    service = AlertService(db=mock_db, redis=None)
    service._workspace_svc.get_active_workspace = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    service._repo.legacy_network_ids = AsyncMock(return_value=legacy)
    service._network_svc.assert_network_workspace_access = AsyncMock()
    service._network_svc.list_networks = AsyncMock(return_value=SimpleNamespace(
        items=[SimpleNamespace(network_id=legacy[0]), SimpleNamespace(network_id=uuid.UUID(int=999))], total=2))
    scope = await service._accessible_scopes(ARGS["actor_user_id"], WORKSPACE, None)
    assert scope.networks == {legacy[0]: WORKSPACE}
    service._network_svc.list_networks.assert_awaited_once()
    service._network_svc.assert_network_workspace_access.assert_not_awaited()
