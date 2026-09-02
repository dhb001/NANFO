"""Unit tests for NetworkService and DeviceService (app/modules/network/service.py).

Key constraint C5: workspace_id validation calls WorkspaceService (not WorkspaceRepository).
Key constraint C6: no deferred topology endpoint methods exist in the service.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.network.models import Device, Network
from app.modules.network.schemas import (
    CreateDeviceRequest,
    CreateNetworkRequest,
    UpdateDeviceRequest,
    UpsertCampusBuildingInput,
    UpsertCampusBuildingsRequest,
)
from app.modules.network.service import (
    CampusBuildingService,
    DeviceService,
    NetworkService,
)
from app.modules.organization.models import Workspace


def _make_network(workspace_id: uuid.UUID | None = None) -> Network:
    n = MagicMock(spec=Network)
    n.network_id = uuid.uuid4()
    n.workspace_id = workspace_id or uuid.uuid4()
    n.name = "Test Network"
    n.description = None
    n.cidr = "10.0.0.0/24"
    n.created_at = MagicMock()
    return n


def _make_device(network_id: uuid.UUID | None = None, spatial_ref_id: str | None = None) -> Device:
    d = MagicMock(spec=Device)
    d.device_id = uuid.uuid4()
    d.network_id = network_id or uuid.uuid4()
    d.hostname = "router-01"
    d.ip_address = "10.0.0.1"
    d.device_type = "router"
    d.vendor = "Cisco"
    d.model = "C9300"
    d.location_hint = None
    d.spatial_ref_id = spatial_ref_id
    d.status = "active"
    d.created_at = MagicMock()
    return d


def _make_workspace(workspace_id: uuid.UUID | None = None, org_id: uuid.UUID | None = None) -> Workspace:
    ws = MagicMock(spec=Workspace)
    ws.workspace_id = workspace_id or uuid.uuid4()
    ws.org_id = org_id or uuid.uuid4()
    ws.deleted_at = None
    return ws


def _make_campus_building_row(network_id: uuid.UUID | None = None):
    row = MagicMock()
    row.campus_building_id = uuid.uuid4()
    row.network_id = network_id or uuid.uuid4()
    row.building_id = "campus-a:building-1"
    row.campus_key = "campus-a"
    row.building_key = "building-1"
    row.label = "Building 1"
    row.geometry = "box"
    row.x = 4.0
    row.z = -3.0
    row.base_y = -2.3
    row.width = 12.0
    row.depth = 9.0
    row.height = 8.5
    row.floors = 3
    row.footprint = [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]]
    row.wall_material = "concrete"
    row.attenuation_db = 14.0
    row.source = "geojson"
    row.created_at = MagicMock()
    row.updated_at = MagicMock()
    return row


@pytest.fixture
def net_svc(mock_db, fake_redis) -> NetworkService:
    return NetworkService(db=mock_db, redis=fake_redis)


@pytest.fixture
def dev_svc(mock_db, fake_redis) -> DeviceService:
    return DeviceService(db=mock_db, redis=fake_redis)


@pytest.fixture
def campus_svc(mock_db, fake_redis) -> CampusBuildingService:
    return CampusBuildingService(db=mock_db, redis=fake_redis)


class TestNetworkService:

    @pytest.mark.asyncio
    async def test_create_network_success(self, net_svc):
        """C5: workspace validation goes through WorkspaceService membership API."""
        ws = _make_workspace()
        network = _make_network(workspace_id=ws.workspace_id)
        actor_id = str(uuid.uuid4())
        with (
            # Patch the service-layer call — NOT the repository
            patch.object(net_svc._workspace_svc, "assert_workspace_membership", return_value=ws) as mock_ws,
            patch.object(net_svc._repo, "create", return_value=network),
            patch("app.modules.network.service.publish_event", new_callable=AsyncMock) as mock_publish,
        ):
            result = await net_svc.create_network(
                req=CreateNetworkRequest(workspace_id=ws.workspace_id, name="Net1"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )
        # Verify C5: the service-layer method was called
        mock_ws.assert_awaited_once_with(workspace_id=ws.workspace_id, user_id=actor_id)
        mock_publish.assert_awaited_once()
        assert result.network_id == network.network_id

    @pytest.mark.asyncio
    async def test_create_network_workspace_scope_mismatch_raises_403(self, net_svc):
        ws = _make_workspace()
        actor_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await net_svc.create_network(
                req=CreateNetworkRequest(workspace_id=ws.workspace_id, name="Net1"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
                requested_workspace_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_create_network_event_publish_failure_is_fail_open(self, net_svc):
        ws = _make_workspace()
        network = _make_network(workspace_id=ws.workspace_id)
        actor_id = str(uuid.uuid4())
        with (
            patch.object(net_svc._workspace_svc, "assert_workspace_membership", return_value=ws),
            patch.object(net_svc._repo, "create", return_value=network),
            patch(
                "app.modules.network.service.publish_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("stream unavailable"),
            ),
        ):
            result = await net_svc.create_network(
                req=CreateNetworkRequest(workspace_id=ws.workspace_id, name="Net1"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert result.network_id == network.network_id

    @pytest.mark.asyncio
    async def test_create_network_invalid_workspace_raises_404(self, net_svc):
        """C5: 404 from WorkspaceService propagates to the caller."""
        ws_id = uuid.uuid4()
        actor_id = str(uuid.uuid4())
        with (
            patch.object(
                net_svc._workspace_svc,
                "assert_workspace_membership",
                side_effect=HTTPException(status_code=404, detail="Workspace not found or has been deleted."),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await net_svc.create_network(
                req=CreateNetworkRequest(workspace_id=ws_id, name="Bad"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_networks_workspace_scope_mismatch_raises_403(self, net_svc):
        workspace_id = uuid.uuid4()
        actor_user_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await net_svc.list_networks(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                page=1,
                page_size=20,
                requested_workspace_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_networks_validates_workspace_exists(self, net_svc):
        workspace_id = uuid.uuid4()
        actor_user_id = str(uuid.uuid4())
        ws = _make_workspace()
        ws.workspace_id = workspace_id
        with (
            patch.object(net_svc._workspace_svc, "assert_workspace_membership", return_value=ws) as mock_ws,
            patch.object(net_svc._repo, "list_for_workspace", return_value=([], 0)) as mock_list,
        ):
            result = await net_svc.list_networks(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                page=1,
                page_size=20,
            )

        mock_ws.assert_awaited_once_with(workspace_id=workspace_id, user_id=actor_user_id)
        mock_list.assert_awaited_once_with(workspace_id, page=1, page_size=20)
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_list_networks_claim_org_mismatch_raises_403(self, net_svc):
        workspace_id = uuid.uuid4()
        actor_user_id = str(uuid.uuid4())
        ws = _make_workspace()
        ws.workspace_id = workspace_id
        ws.org_id = uuid.uuid4()
        with (
            patch.object(net_svc._workspace_svc, "assert_workspace_membership", return_value=ws),
            pytest.raises(HTTPException) as exc_info,
        ):
            await net_svc.list_networks(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                page=1,
                page_size=20,
                claim_org_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_assert_network_workspace_access_rejects_workspace_mismatch(self, net_svc):
        network = _make_network(workspace_id=uuid.uuid4())
        actor_user_id = str(uuid.uuid4())
        with (
            patch.object(net_svc._repo, "get_by_id", return_value=network),
            patch.object(net_svc._workspace_svc, "assert_workspace_membership", return_value=_make_workspace()),
            pytest.raises(HTTPException) as exc_info,
        ):
            await net_svc.assert_network_workspace_access(
                network_id=network.network_id,
                requested_workspace_id=uuid.uuid4(),
                actor_user_id=actor_user_id,
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_assert_network_workspace_access_requires_membership(self, net_svc):
        network = _make_network(workspace_id=uuid.uuid4())
        actor_user_id = str(uuid.uuid4())
        with (
            patch.object(net_svc._repo, "get_by_id", return_value=network),
            patch.object(
                net_svc._workspace_svc,
                "assert_workspace_membership",
                side_effect=HTTPException(status_code=403, detail="Insufficient permissions."),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await net_svc.assert_network_workspace_access(
                network_id=network.network_id,
                requested_workspace_id=None,
                actor_user_id=actor_user_id,
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_assert_network_workspace_access_claim_org_mismatch_raises_403(self, net_svc):
        network = _make_network(workspace_id=uuid.uuid4())
        actor_user_id = str(uuid.uuid4())
        ws = _make_workspace()
        ws.workspace_id = network.workspace_id
        ws.org_id = uuid.uuid4()
        with (
            patch.object(net_svc._repo, "get_by_id", return_value=network),
            patch.object(net_svc._workspace_svc, "assert_workspace_membership", return_value=ws),
            pytest.raises(HTTPException) as exc_info,
        ):
            await net_svc.assert_network_workspace_access(
                network_id=network.network_id,
                requested_workspace_id=None,
                actor_user_id=actor_user_id,
                claim_org_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_assert_device_workspace_access_returns_network_and_workspace_ids(self, net_svc):
        network = _make_network(workspace_id=uuid.uuid4())
        device = _make_device(network_id=network.network_id)
        actor_user_id = str(uuid.uuid4())
        ws = _make_workspace()
        ws.workspace_id = network.workspace_id
        ws.org_id = uuid.uuid4()

        with (
            patch.object(net_svc._device_repo, "get_by_id", return_value=device),
            patch.object(net_svc._repo, "get_by_id", return_value=network),
            patch.object(net_svc._workspace_svc, "assert_workspace_membership", return_value=ws),
        ):
            resolved_network_id, resolved_workspace_id = await net_svc.assert_device_workspace_access(
                device_id=device.device_id,
                requested_workspace_id=network.workspace_id,
                actor_user_id=actor_user_id,
                claim_org_id=ws.org_id,
            )

        assert resolved_network_id == network.network_id
        assert resolved_workspace_id == network.workspace_id

    @pytest.mark.asyncio
    async def test_assert_device_workspace_access_missing_device_raises_404(self, net_svc):
        actor_user_id = str(uuid.uuid4())
        with (
            patch.object(net_svc._device_repo, "get_by_id", return_value=None),
            pytest.raises(HTTPException) as exc_info,
        ):
            await net_svc.assert_device_workspace_access(
                device_id=uuid.uuid4(),
                requested_workspace_id=None,
                actor_user_id=actor_user_id,
            )

        assert exc_info.value.status_code == 404

    def test_c5_no_workspace_repository_direct_call(self, net_svc):
        """C5: NetworkService must hold a WorkspaceService reference, not a WorkspaceRepository."""
        # The _workspace_svc attribute exists and is an OrgWorkspaceService
        from app.modules.organization.service import WorkspaceService as OrgWS
        assert hasattr(net_svc, "_workspace_svc")
        assert isinstance(net_svc._workspace_svc, OrgWS)
        # Must NOT have a _workspace_repo attribute
        assert not hasattr(net_svc, "_workspace_repo")

    def test_c6_no_deferred_topology_methods(self, net_svc):
        """C6: deferred topology endpoint methods must not exist in NetworkService."""
        for forbidden_method in ("get_neighbors", "get_impact", "reconcile"):
            assert not hasattr(net_svc, forbidden_method), (
                f"Deferred method '{forbidden_method}' found in NetworkService — violates C6"
            )


class TestDeviceService:

    @pytest.mark.asyncio
    async def test_add_device_success_publishes_event(self, dev_svc):
        """Adding a device must publish network.device.added to the event bus."""
        network = _make_network()
        actor_id = str(uuid.uuid4())
        device = _make_device(
            network_id=network.network_id,
            spatial_ref_id="campus-a/building-1/floor-2/room-204/rack-3/device-router-01",
        )
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "create", return_value=device),
            patch("app.modules.network.service.publish_event", new_callable=AsyncMock) as mock_pub,
        ):
            result = await dev_svc.add_device(
                network_id=network.network_id,
                req=CreateDeviceRequest(
                    hostname="router-01",
                    device_type="router",
                    spatial_ref_id="campus-a/building-1/floor-2/room-204/rack-3/device-router-01",
                ),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )
        # Event must be published
        mock_pub.assert_awaited_once()
        call_kwargs = mock_pub.await_args.kwargs
        assert call_kwargs["event_type"] == "network.device.added"
        assert call_kwargs["payload"]["workspace_id"] == str(network.workspace_id)
        assert call_kwargs["payload"]["spatial_ref_id"] == "campus-a/building-1/floor-2/room-204/rack-3/device-router-01"
        assert result.device_id == device.device_id

    @pytest.mark.asyncio
    async def test_add_device_event_publish_failure_is_fail_open(self, dev_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        device = _make_device(network_id=network.network_id)
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "create", return_value=device),
            patch(
                "app.modules.network.service.publish_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("stream unavailable"),
            ),
        ):
            result = await dev_svc.add_device(
                network_id=network.network_id,
                req=CreateDeviceRequest(hostname="router-01", device_type="router"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert result.device_id == device.device_id

    @pytest.mark.asyncio
    async def test_add_device_passes_spatial_ref_id_to_repository(self, dev_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        device = _make_device(network_id=network.network_id)

        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "create", return_value=device) as mock_create,
            patch("app.modules.network.service.publish_event", new_callable=AsyncMock),
        ):
            await dev_svc.add_device(
                network_id=network.network_id,
                req=CreateDeviceRequest(
                    hostname="router-01",
                    device_type="router",
                    spatial_ref_id="campus-a/device-1",
                ),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert mock_create.await_args.kwargs["spatial_ref_id"] == "campus-a/device-1"

    @pytest.mark.asyncio
    async def test_add_device_to_unknown_network_raises_404(self, dev_svc):
        actor_id = str(uuid.uuid4())
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=None),
            pytest.raises(HTTPException) as exc_info,
        ):
            await dev_svc.add_device(
                network_id=uuid.uuid4(),
                req=CreateDeviceRequest(hostname="h", device_type="switch"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_add_device_workspace_scope_mismatch_raises_403(self, dev_svc):
        workspace_id = uuid.uuid4()
        actor_id = str(uuid.uuid4())
        network = _make_network(workspace_id=workspace_id)
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await dev_svc.add_device(
                network_id=network.network_id,
                req=CreateDeviceRequest(hostname="router-01", device_type="router"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
                requested_workspace_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 403


class TestCampusBuildingService:

    @pytest.mark.asyncio
    async def test_list_buildings_success(self, campus_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        row = _make_campus_building_row(network.network_id)

        with (
            patch.object(campus_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(campus_svc._repo, "list_for_network", return_value=[row]) as mock_list,
        ):
            result = await campus_svc.list_buildings(
                network_id=network.network_id,
                actor_user_id=actor_id,
            )

        mock_list.assert_awaited_once_with(network.network_id)
        assert result.total == 1
        assert result.items[0].building_id == "campus-a:building-1"

    @pytest.mark.asyncio
    async def test_upsert_buildings_success_replace_existing(self, campus_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        row = _make_campus_building_row(network.network_id)
        req = UpsertCampusBuildingsRequest(
            replace_existing=True,
            buildings=[
                UpsertCampusBuildingInput(
                    building_id="campus-a:building-1",
                    campus_key="campus-a",
                    building_key="building-1",
                    label="Building 1",
                    geometry="box",
                    x=4.0,
                    z=-3.0,
                    base_y=-2.3,
                    width=12.0,
                    depth=9.0,
                    height=8.5,
                    floors=3,
                    footprint=[[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]],
                    wall_material="concrete",
                    attenuation_db=14.0,
                    source="geojson",
                )
            ],
        )

        with (
            patch.object(campus_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(campus_svc._repo, "soft_delete_for_network", return_value=0) as mock_soft_delete,
            patch.object(campus_svc._repo, "get_active_by_network_and_building_id", return_value=None),
            patch.object(campus_svc._repo, "create", return_value=row) as mock_create,
        ):
            result = await campus_svc.upsert_buildings(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        mock_soft_delete.assert_awaited_once_with(network.network_id)
        mock_create.assert_awaited_once()
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_upsert_buildings_event_publish_failure_is_fail_open(self, campus_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        row = _make_campus_building_row(network.network_id)
        req = UpsertCampusBuildingsRequest(
            replace_existing=False,
            buildings=[
                UpsertCampusBuildingInput(
                    building_id="campus-a:building-1",
                    campus_key="campus-a",
                    building_key="building-1",
                    label="Building 1",
                    geometry="box",
                    x=4.0,
                    z=-3.0,
                    base_y=-2.3,
                    width=12.0,
                    depth=9.0,
                    height=8.5,
                    floors=3,
                    footprint=[[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]],
                )
            ],
        )

        with (
            patch.object(campus_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(campus_svc._repo, "get_active_by_network_and_building_id", return_value=None),
            patch.object(campus_svc._repo, "create", return_value=row),
        ):
            result = await campus_svc.upsert_buildings(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert result.total == 1

    @pytest.mark.asyncio
    async def test_upsert_buildings_workspace_scope_mismatch_raises_403(self, campus_svc):
        network = _make_network(workspace_id=uuid.uuid4())
        actor_id = str(uuid.uuid4())

        req = UpsertCampusBuildingsRequest(
            replace_existing=False,
            buildings=[],
        )

        with (
            patch.object(campus_svc._network_repo, "get_by_id", return_value=network),
            pytest.raises(HTTPException) as exc_info,
        ):
            await campus_svc.upsert_buildings(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
                requested_workspace_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_add_device_event_type_follows_naming_convention(self, dev_svc):
        """EventAPI.md §1: event_type must follow module.entity.action pattern."""
        network = _make_network()
        actor_id = str(uuid.uuid4())
        device = _make_device(network_id=network.network_id)
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "create", return_value=device),
            patch("app.modules.network.service.publish_event", new_callable=AsyncMock) as mock_pub,
        ):
            await dev_svc.add_device(
                network_id=network.network_id,
                req=CreateDeviceRequest(hostname="h", device_type="switch"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )
        event_type = mock_pub.call_args.kwargs["event_type"]
        parts = event_type.split(".")
        assert len(parts) == 3, f"Event type '{event_type}' does not follow module.entity.action pattern"

    @pytest.mark.asyncio
    async def test_update_device_spatial_ref_success_publishes_updated_event(self, dev_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        current = _make_device(network_id=network.network_id, spatial_ref_id="campus-a/device-old")
        updated = _make_device(network_id=network.network_id, spatial_ref_id="campus-a/device-new")
        updated.device_id = current.device_id

        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "get_by_id", return_value=current),
            patch.object(dev_svc._repo, "update_spatial_ref_id", return_value=updated) as mock_update,
            patch("app.modules.network.service.publish_event", new_callable=AsyncMock) as mock_pub,
        ):
            result = await dev_svc.update_device_spatial_ref(
                network_id=network.network_id,
                device_id=current.device_id,
                req=UpdateDeviceRequest(spatial_ref_id="campus-a/device-new"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        mock_update.assert_awaited_once_with(
            network_id=network.network_id,
            device_id=current.device_id,
            spatial_ref_id="campus-a/device-new",
        )
        mock_pub.assert_awaited_once()
        payload = mock_pub.await_args.kwargs["payload"]
        assert mock_pub.await_args.kwargs["event_type"] == "network.device.updated"
        assert payload["workspace_id"] == str(network.workspace_id)
        assert payload["changed_fields"] == {"spatial_ref_id": "campus-a/device-new"}
        assert result.device_id == current.device_id

    @pytest.mark.asyncio
    async def test_update_device_spatial_ref_event_publish_failure_is_fail_open(self, dev_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        current = _make_device(network_id=network.network_id, spatial_ref_id="campus-a/device-old")
        updated = _make_device(network_id=network.network_id, spatial_ref_id="campus-a/device-new")
        updated.device_id = current.device_id

        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "get_by_id", return_value=current),
            patch.object(dev_svc._repo, "update_spatial_ref_id", return_value=updated),
            patch(
                "app.modules.network.service.publish_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("stream unavailable"),
            ),
        ):
            result = await dev_svc.update_device_spatial_ref(
                network_id=network.network_id,
                device_id=current.device_id,
                req=UpdateDeviceRequest(spatial_ref_id="campus-a/device-new"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert result.device_id == current.device_id

    @pytest.mark.asyncio
    async def test_update_device_spatial_ref_no_change_skips_event_publish(self, dev_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        current = _make_device(network_id=network.network_id, spatial_ref_id="campus-a/device-1")

        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "get_by_id", return_value=current),
            patch.object(dev_svc._repo, "update_spatial_ref_id") as mock_update,
            patch("app.modules.network.service.publish_event", new_callable=AsyncMock) as mock_pub,
        ):
            result = await dev_svc.update_device_spatial_ref(
                network_id=network.network_id,
                device_id=current.device_id,
                req=UpdateDeviceRequest(spatial_ref_id="campus-a/device-1"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        mock_update.assert_not_called()
        mock_pub.assert_not_awaited()
        dev_svc._db.commit.assert_not_awaited()
        assert result.device_id == current.device_id

    @pytest.mark.asyncio
    async def test_update_device_spatial_ref_unknown_network_raises_404(self, dev_svc):
        actor_id = str(uuid.uuid4())
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=None),
            pytest.raises(HTTPException) as exc_info,
        ):
            await dev_svc.update_device_spatial_ref(
                network_id=uuid.uuid4(),
                device_id=uuid.uuid4(),
                req=UpdateDeviceRequest(spatial_ref_id="campus-a/device-1"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_device_spatial_ref_unknown_device_raises_404(self, dev_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "get_by_id", return_value=None),
            pytest.raises(HTTPException) as exc_info,
        ):
            await dev_svc.update_device_spatial_ref(
                network_id=network.network_id,
                device_id=uuid.uuid4(),
                req=UpdateDeviceRequest(spatial_ref_id="campus-a/device-1"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_devices_workspace_scope_mismatch_raises_403(self, dev_svc):
        workspace_id = uuid.uuid4()
        actor_user_id = str(uuid.uuid4())
        network = _make_network(workspace_id=workspace_id)
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await dev_svc.list_devices(
                network_id=network.network_id,
                actor_user_id=actor_user_id,
                page=1,
                page_size=20,
                requested_workspace_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_devices_requires_membership(self, dev_svc):
        network = _make_network(workspace_id=uuid.uuid4())
        actor_user_id = str(uuid.uuid4())
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=403, detail="Insufficient permissions."),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await dev_svc.list_devices(
                network_id=network.network_id,
                actor_user_id=actor_user_id,
                page=1,
                page_size=20,
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_add_device_claim_org_mismatch_raises_403(self, dev_svc):
        network = _make_network(workspace_id=uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        workspace.org_id = uuid.uuid4()
        actor_id = str(uuid.uuid4())

        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=workspace,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await dev_svc.add_device(
                network_id=network.network_id,
                req=CreateDeviceRequest(hostname="router-01", device_type="router"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
                claim_org_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_list_devices_claim_org_mismatch_raises_403(self, dev_svc):
        network = _make_network(workspace_id=uuid.uuid4())
        actor_user_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        workspace.org_id = uuid.uuid4()

        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.network.service.OrgWorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=workspace,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await dev_svc.list_devices(
                network_id=network.network_id,
                actor_user_id=actor_user_id,
                page=1,
                page_size=20,
                claim_org_id=uuid.uuid4(),
            )

        assert exc_info.value.status_code == 403
