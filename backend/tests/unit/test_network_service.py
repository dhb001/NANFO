"""Unit tests for NetworkService and DeviceService (app/modules/network/service.py).

Key constraint C5: workspace_id validation calls WorkspaceService (not WorkspaceRepository).
Key constraint C6: no deferred topology endpoint methods exist in the service.
"""

import base64
import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.network.device_types import matches_functional_group
from app.modules.network.models import Device, Network
from app.modules.network.schemas import (
    CreateDeviceRequest,
    CreateNetworkRequest,
    UpdateDeviceRequest,
    UpsertCampusBuildingInput,
    UpsertCampusBuildingsRequest,
    UpsertCampusModelAssetRequest,
    UpsertDeviceGroupInput,
    UpsertDeviceGroupsRequest,
)
from app.modules.network.service import (
    CampusBuildingService,
    CampusModelAssetService,
    DeviceGroupService,
    DeviceService,
    NetworkService,
    _normalize_group_token,
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


def _make_campus_model_asset_row(network_id: uuid.UUID | None = None):
    row = MagicMock()
    row.campus_model_asset_id = uuid.uuid4()
    row.network_id = network_id or uuid.uuid4()
    row.model_file_name = "campus.glb"
    row.model_mime_type = "model/gltf-binary"
    model_bytes = b"campus-model"
    row.model_data_base64 = base64.b64encode(model_bytes).decode("ascii")
    row.model_sha256 = hashlib.sha256(model_bytes).hexdigest()
    row.model_size_bytes = len(model_bytes)
    row.storage_backend = "inline"
    row.registration = None
    row.mapping_by_device_id = {}
    row.source = "manual_upload"
    row.created_at = MagicMock()
    row.updated_at = MagicMock()
    return row


def _make_device_group_row(network_id: uuid.UUID | None = None):
    row = MagicMock()
    row.device_group_id = uuid.uuid4()
    row.network_id = network_id or uuid.uuid4()
    row.group_key = "floor-2-wireless"
    row.name = "Floor 2 Wireless"
    row.group_type = "functional"
    row.description = "Wireless devices on floor 2"
    row.selector = {"functional_group": "wireless"}
    row.created_at = MagicMock()
    row.updated_at = MagicMock()
    return row


def _building_input(**changes) -> UpsertCampusBuildingInput:
    values = dict(
        building_id="campus-a:building-1", campus_key="campus-a", building_key="building-1",
        label="Building 1", geometry="box", x=4.0, z=-3.0, base_y=-2.3, width=12.0, depth=9.0,
        height=8.5, floors=3, footprint=[[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]],
        wall_material="concrete", attenuation_db=14.0, source="geojson",
    )
    values.update(changes)
    return UpsertCampusBuildingInput(**values)


@pytest.fixture
def audit(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.modules.network.service.append_audit_log", mock)
    return mock


def _build_valid_model_asset_request(
    *,
    mapping_by_device_id: dict[str, str] | None = None,
    replace_existing: bool = True,
) -> UpsertCampusModelAssetRequest:
    model_bytes = b"nanfo-campus-model"
    return UpsertCampusModelAssetRequest.model_validate(
        {
            "model_file_name": "campus.glb",
            "model_mime_type": "model/gltf-binary",
            "model_data_base64": base64.b64encode(model_bytes).decode("ascii"),
            "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
            "model_size_bytes": len(model_bytes),
            "mapping_by_device_id": mapping_by_device_id or {},
            "source": "manual_upload",
            "replace_existing": replace_existing,
        }
    )


@pytest.fixture
def net_svc(mock_db, fake_redis) -> NetworkService:
    return NetworkService(db=mock_db, redis=fake_redis)


@pytest.fixture
def dev_svc(mock_db, fake_redis) -> DeviceService:
    return DeviceService(db=mock_db, redis=fake_redis)


@pytest.fixture
def campus_svc(mock_db, fake_redis) -> CampusBuildingService:
    return CampusBuildingService(db=mock_db, redis=fake_redis)


@pytest.fixture
def campus_model_asset_svc(mock_db, fake_redis, tmp_path) -> CampusModelAssetService:
    from app.modules.network.asset_settings import AssetSettings
    from app.modules.network.asset_storage import LocalAssetStore

    tmp_path.chmod(0o700)
    mock_db.expire_all = MagicMock()
    return CampusModelAssetService(db=mock_db, redis=fake_redis,
                                   asset_store=LocalAssetStore(AssetSettings(root=tmp_path)))


@pytest.fixture
def device_group_svc(mock_db, fake_redis) -> DeviceGroupService:
    return DeviceGroupService(db=mock_db, redis=fake_redis)


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
            patch("app.modules.network.outbox.NetworkOutboxRepository.enqueue", new_callable=AsyncMock) as mock_publish,
        ):
            result = await net_svc.create_network(
                req=CreateNetworkRequest(workspace_id=ws.workspace_id, name="Net1"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )
        # Verify C5: the service-layer method was called
        mock_ws.assert_awaited_once_with(workspace_id=ws.workspace_id, user_id=actor_id, require_write=True)
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
    async def test_create_network_outbox_failure_rolls_back(self, net_svc):
        ws = _make_workspace()
        network = _make_network(workspace_id=ws.workspace_id)
        actor_id = str(uuid.uuid4())
        with (
            patch.object(net_svc._workspace_svc, "assert_workspace_membership", return_value=ws),
            patch.object(net_svc._repo, "create", return_value=network),
            patch(
                "app.modules.network.outbox.NetworkOutboxRepository.enqueue",
                new_callable=AsyncMock,
                side_effect=RuntimeError("outbox unavailable"),
            ),
            pytest.raises(RuntimeError, match="outbox unavailable"),
        ):
            await net_svc.create_network(
                req=CreateNetworkRequest(workspace_id=ws.workspace_id, name="Net1"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        net_svc._db.commit.assert_not_awaited()
        net_svc._db.rollback.assert_awaited_once()

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

        # The single NetworkAccessGuard always states the (read) intent explicitly.
        mock_ws.assert_awaited_once_with(workspace_id=workspace_id, user_id=actor_user_id, require_write=False)
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
    async def test_add_device_success_enqueues_event(self, dev_svc):
        """Adding a device must enqueue network.device.added transactionally."""
        network = _make_network()
        actor_id = str(uuid.uuid4())
        device = _make_device(
            network_id=network.network_id,
            spatial_ref_id="campus-a/building-1/floor-2/room-204/rack-3/device-router-01",
        )
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "create", return_value=device),
            patch("app.modules.network.outbox.NetworkOutboxRepository.enqueue", new_callable=AsyncMock) as mock_pub,
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
        # Event must be enqueued
        mock_pub.assert_awaited_once()
        call_kwargs = mock_pub.await_args.kwargs
        assert call_kwargs["event_type"] == "network.device.added"
        assert call_kwargs["payload"]["workspace_id"] == str(network.workspace_id)
        assert call_kwargs["payload"]["spatial_ref_id"] == "campus-a/building-1/floor-2/room-204/rack-3/device-router-01"
        assert result.device_id == device.device_id

    @pytest.mark.asyncio
    async def test_add_device_outbox_failure_rolls_back(self, dev_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        device = _make_device(network_id=network.network_id)
        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "create", return_value=device),
            patch(
                "app.modules.network.outbox.NetworkOutboxRepository.enqueue",
                new_callable=AsyncMock,
                side_effect=RuntimeError("outbox unavailable"),
            ),
            pytest.raises(RuntimeError, match="outbox unavailable"),
        ):
            await dev_svc.add_device(
                network_id=network.network_id,
                req=CreateDeviceRequest(hostname="router-01", device_type="router"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        dev_svc._db.commit.assert_not_awaited()
        dev_svc._db.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_device_passes_spatial_ref_id_to_repository(self, dev_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        device = _make_device(network_id=network.network_id)

        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "create", return_value=device) as mock_create,
            patch("app.modules.network.outbox.NetworkOutboxRepository.enqueue", new_callable=AsyncMock),
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
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
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
    async def test_upsert_buildings_replace_updates_in_place_and_retires_absent(self, campus_svc, audit):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        row = _make_campus_building_row(network.network_id)
        req = UpsertCampusBuildingsRequest(replace_existing=True, buildings=[_building_input()])

        with (
            patch.object(campus_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(campus_svc._repo, "active_building_ids",
                         return_value={"campus-a:building-1", "campus-a:retired"}),
            patch.object(campus_svc._repo, "upsert_many") as mock_upsert,
            patch.object(campus_svc._repo, "soft_delete_absent", return_value=1) as mock_retire,
            patch.object(campus_svc._repo, "list_active_by_building_ids",
                         return_value={"campus-a:building-1": row}) as mock_reload,
        ):
            result = await campus_svc.upsert_buildings(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
                correlation_id="building-request",
            )

        # One set-based upsert keyed by the active unique index; no soft-delete churn.
        mock_upsert.assert_awaited_once()
        values = mock_upsert.await_args.kwargs["buildings"]
        assert [value["building_id"] for value in values] == ["campus-a:building-1"]
        assert values[0]["footprint"] == [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]]
        mock_retire.assert_awaited_once_with(network.network_id, ["campus-a:building-1"])
        mock_reload.assert_awaited_once_with(network.network_id, ["campus-a:building-1"])
        assert result.total == 1
        assert result.items[0].campus_building_id == row.campus_building_id
        audit.assert_awaited_once()
        kwargs = audit.await_args.kwargs
        assert kwargs["event_type"] == "network.campus_buildings.upserted"
        assert kwargs["org_id"] == workspace.org_id
        assert kwargs["correlation_id"] == "building-request"
        assert kwargs["metadata"]["retired"] == 1 and kwargs["metadata"]["updated"] == 1
        assert kwargs["metadata"]["created"] == 0 and kwargs["metadata"]["replace_existing"] is True
        campus_svc._db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_buildings_without_replace_keeps_absent_rows_and_dedupes(self, campus_svc, audit):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        row = _make_campus_building_row(network.network_id)
        req = UpsertCampusBuildingsRequest(
            replace_existing=False,
            buildings=[_building_input(label="First"), _building_input(label="Last")],
        )

        with (
            patch.object(campus_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(campus_svc._repo, "active_building_ids", return_value=set()),
            patch.object(campus_svc._repo, "upsert_many") as mock_upsert,
            patch.object(campus_svc._repo, "soft_delete_absent") as mock_retire,
            patch.object(campus_svc._repo, "list_active_by_building_ids",
                         return_value={"campus-a:building-1": row}),
        ):
            result = await campus_svc.upsert_buildings(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
            )

        values = mock_upsert.await_args.kwargs["buildings"]
        assert len(values) == 1 and values[0]["label"] == "Last"
        mock_retire.assert_not_awaited()
        assert result.total == 1
        assert audit.await_args.kwargs["metadata"]["created"] == 1

    @pytest.mark.asyncio
    async def test_upsert_buildings_authorizes_before_inventory_lock(self, campus_svc, audit):
        network = _make_network()
        with (
            patch.object(campus_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_svc._workspace_svc, "assert_workspace_membership",
                         side_effect=HTTPException(status_code=403, detail="Insufficient permissions.")),
            patch("app.modules.network.outbox.NetworkOutboxRepository.lock_inventory",
                  new_callable=AsyncMock) as mock_lock,
            patch.object(campus_svc._repo, "upsert_many") as mock_upsert,
            pytest.raises(HTTPException) as exc_info,
        ):
            await campus_svc.upsert_buildings(
                network_id=network.network_id,
                req=UpsertCampusBuildingsRequest(buildings=[_building_input()]),
                actor_id=str(uuid.uuid4()),
            )

        assert exc_info.value.status_code == 403
        mock_lock.assert_not_awaited()
        mock_upsert.assert_not_awaited()
        audit.assert_not_awaited()
        campus_svc._db.commit.assert_not_awaited()

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
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "create", return_value=device),
            patch("app.modules.network.outbox.NetworkOutboxRepository.enqueue", new_callable=AsyncMock) as mock_pub,
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
    async def test_update_device_spatial_ref_success_enqueues_updated_event(self, dev_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        current = _make_device(network_id=network.network_id, spatial_ref_id="campus-a/device-old")
        updated = _make_device(network_id=network.network_id, spatial_ref_id="campus-a/device-new")
        updated.device_id = current.device_id

        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "get_by_id", return_value=current),
            patch.object(dev_svc._repo, "update", return_value=updated) as mock_update,
            patch("app.modules.network.outbox.NetworkOutboxRepository.enqueue", new_callable=AsyncMock) as mock_pub,
        ):
            result = await dev_svc.update_device_spatial_ref(
                network_id=network.network_id,
                device_id=current.device_id,
                req=UpdateDeviceRequest(spatial_ref_id="campus-a/device-new"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        mock_update.assert_awaited_once_with(
            current, {"spatial_ref_id": "campus-a/device-new"},
        )
        mock_pub.assert_awaited_once()
        payload = mock_pub.await_args.kwargs["payload"]
        assert mock_pub.await_args.kwargs["event_type"] == "network.device.updated"
        assert payload["workspace_id"] == str(network.workspace_id)
        assert payload["changed_fields"] == {"spatial_ref_id": "campus-a/device-new"}
        assert result.device_id == current.device_id

    @pytest.mark.asyncio
    async def test_update_device_spatial_ref_outbox_failure_rolls_back(self, dev_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        current = _make_device(network_id=network.network_id, spatial_ref_id="campus-a/device-old")
        updated = _make_device(network_id=network.network_id, spatial_ref_id="campus-a/device-new")
        updated.device_id = current.device_id

        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "get_by_id", return_value=current),
            patch.object(dev_svc._repo, "update", return_value=updated),
            patch(
                "app.modules.network.outbox.NetworkOutboxRepository.enqueue",
                new_callable=AsyncMock,
                side_effect=RuntimeError("outbox unavailable"),
            ),
            pytest.raises(RuntimeError, match="outbox unavailable"),
        ):
            await dev_svc.update_device_spatial_ref(
                network_id=network.network_id,
                device_id=current.device_id,
                req=UpdateDeviceRequest(spatial_ref_id="campus-a/device-new"),
                actor_id=actor_id,
                correlation_id=str(uuid.uuid4()),
            )

        dev_svc._db.commit.assert_not_awaited()
        dev_svc._db.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_device_spatial_ref_no_change_skips_event_publish(self, dev_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        current = _make_device(network_id=network.network_id, spatial_ref_id="campus-a/device-1")

        with (
            patch.object(dev_svc._network_repo, "get_by_id", return_value=network),
            patch(
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
                new_callable=AsyncMock,
                return_value=_make_workspace(network.workspace_id),
            ),
            patch.object(dev_svc._repo, "get_by_id", return_value=current),
            patch.object(dev_svc._repo, "update") as mock_update,
            patch("app.modules.network.outbox.NetworkOutboxRepository.enqueue", new_callable=AsyncMock) as mock_pub,
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
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
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
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
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
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
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
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
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
                "app.modules.organization.service.WorkspaceService.assert_workspace_membership",
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


class TestCampusModelAssetService:

    @pytest.mark.asyncio
    async def test_list_assets_defaults_to_metadata_pages(self, campus_model_asset_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        row = _make_campus_model_asset_row(network.network_id)

        with (
            patch.object(campus_model_asset_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_model_asset_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(campus_model_asset_svc._repo, "list_metadata_for_network", return_value=([row], 1)) as mock_meta,
            patch.object(campus_model_asset_svc._repo, "list_for_network") as mock_full,
        ):
            result = await campus_model_asset_svc.list_assets(
                network_id=network.network_id,
                actor_user_id=actor_id,
            )

        mock_meta.assert_awaited_once_with(network.network_id, page=1, page_size=20)
        mock_full.assert_not_awaited()
        assert result.total == 1
        assert result.items[0].model_file_name == "campus.glb"
        assert "model_data_base64" not in result.items[0].model_dump()

    @pytest.mark.asyncio
    async def test_list_assets_include_data_is_bounded(self, campus_model_asset_svc):
        network = _make_network()
        workspace = _make_workspace(network.workspace_id)
        row = _make_campus_model_asset_row(network.network_id)
        big = _make_campus_model_asset_row(network.network_id)
        big.model_size_bytes = 8 * 1024 * 1024

        def sizes(*rows):
            return [{"model_size_bytes": item.model_size_bytes} for item in rows], len(rows)

        with (
            patch.object(campus_model_asset_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_model_asset_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(campus_model_asset_svc._repo, "list_metadata_for_network") as mock_sizes,
            patch.object(campus_model_asset_svc._repo, "list_page_for_network") as mock_page,
        ):
            with pytest.raises(HTTPException) as too_large_page:
                await campus_model_asset_svc.list_assets(
                    network_id=network.network_id, actor_user_id=str(uuid.uuid4()), include_data=True,
                )
            assert too_large_page.value.status_code == 400
            assert too_large_page.value.detail["code"] == "CAMPUS_MODEL_ASSET_INLINE_PAGE_TOO_LARGE"
            mock_page.assert_not_awaited()

            # ADR-028: the page is sized from metadata, so no body is loaded when over 32 MiB.
            mock_sizes.return_value = sizes(*[big] * 5)
            with pytest.raises(HTTPException) as too_many_bytes:
                await campus_model_asset_svc.list_assets(
                    network_id=network.network_id, actor_user_id=str(uuid.uuid4()), include_data=True, page_size=5,
                )
            assert too_many_bytes.value.status_code == 400
            assert too_many_bytes.value.detail["code"] == "CAMPUS_MODEL_ASSET_INLINE_LIMIT_EXCEEDED"
            mock_page.assert_not_awaited()

            mock_sizes.return_value = sizes(row)
            mock_page.return_value = ([row], 1)
            result = await campus_model_asset_svc.list_assets(
                network_id=network.network_id, actor_user_id=str(uuid.uuid4()), include_data=True, page_size=10,
            )
        assert result.items[0].model_data_base64 == row.model_data_base64
        assert (result.page, result.page_size) == (1, 10)

    @pytest.mark.asyncio
    async def test_upsert_asset_success_replace_existing(self, campus_model_asset_svc, audit):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        device_id = str(uuid.uuid4())
        req = _build_valid_model_asset_request(
            mapping_by_device_id={device_id: "strathmore/sbs/f01/core/rtr-sbs-f01-01"},
            replace_existing=True,
        )
        row = _make_campus_model_asset_row(network.network_id)
        row.model_sha256 = req.model_sha256
        row.model_size_bytes = req.model_size_bytes
        row.model_data_base64 = None
        row.storage_backend = "local_cas"
        row.mapping_by_device_id = dict(req.mapping_by_device_id)

        with (
            patch.object(campus_model_asset_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_model_asset_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(
                campus_model_asset_svc._device_repo,
                "list_device_ids_for_network",
                return_value={uuid.UUID(device_id)},
            ) as mock_known,
            patch.object(campus_model_asset_svc._repo, "active_usage", return_value=(0, 0)),
            patch.object(campus_model_asset_svc._repo, "soft_delete_for_network", return_value=0) as mock_soft_delete,
            patch.object(campus_model_asset_svc._repo, "create", return_value=row) as mock_create,
        ):
            result = await campus_model_asset_svc.upsert_asset(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
                correlation_id="asset-request",
            )

        mock_known.assert_awaited_once()
        mock_soft_delete.assert_awaited_once_with(network.network_id)
        mock_create.assert_awaited_once()
        create_kwargs = mock_create.await_args.kwargs
        assert create_kwargs["model_sha256"] == req.model_sha256
        assert create_kwargs["model_size_bytes"] == req.model_size_bytes
        assert create_kwargs["mapping_by_device_id"] == req.mapping_by_device_id
        assert result.total == 1
        # C4: upload responses are metadata only.
        assert result.items[0].model_data_base64 is None
        assert "model_data_base64" not in result.model_dump()["items"][0]
        campus_model_asset_svc._db.refresh.assert_awaited_once_with(row)
        assert audit.await_args.kwargs["event_type"] == "network.campus_model_asset.uploaded"
        assert audit.await_args.kwargs["org_id"] == workspace.org_id
        assert audit.await_args.kwargs["correlation_id"] == "asset-request"

    @pytest.mark.asyncio
    async def test_upsert_asset_success_updates_latest_when_replace_existing_false(self, campus_model_asset_svc, audit):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        req = _build_valid_model_asset_request(replace_existing=False)
        existing = _make_campus_model_asset_row(network.network_id)
        existing.model_sha256 = req.model_sha256
        existing.model_size_bytes = req.model_size_bytes
        existing.model_data_base64 = req.model_data_base64

        with (
            patch.object(campus_model_asset_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_model_asset_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(campus_model_asset_svc._repo, "get_latest_for_network", return_value=existing),
            patch.object(campus_model_asset_svc._repo, "active_usage", return_value=(req.model_size_bytes, 1)),
            patch.object(campus_model_asset_svc._repo, "update", return_value=existing) as mock_update,
            patch.object(campus_model_asset_svc._repo, "create") as mock_create,
        ):
            result = await campus_model_asset_svc.upsert_asset(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
            )

        mock_create.assert_not_called()
        mock_update.assert_awaited_once()
        # The in-place update path reloads server-side updated_at before serializing.
        campus_model_asset_svc._db.refresh.assert_awaited_once_with(existing)
        assert result.total == 1
        assert result.items[0].model_data_base64 is None

    @pytest.mark.asyncio
    async def test_upsert_asset_network_quota_uses_active_accounting(self, campus_model_asset_svc, audit):
        network = _make_network()
        workspace = _make_workspace(network.workspace_id)
        req = _build_valid_model_asset_request(replace_existing=False)
        limit = campus_model_asset_svc._asset_store.settings.network_max_active_bytes

        with (
            patch.object(campus_model_asset_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_model_asset_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(campus_model_asset_svc._repo, "get_latest_for_network", return_value=None),
            patch.object(campus_model_asset_svc._repo, "active_usage", return_value=(limit, 1)),
            patch.object(campus_model_asset_svc._repo, "create") as mock_create,
            pytest.raises(HTTPException) as exc_info,
        ):
            await campus_model_asset_svc.upsert_asset(
                network_id=network.network_id, req=req, actor_id=str(uuid.uuid4()),
            )

        assert exc_info.value.status_code == 507
        assert exc_info.value.detail["code"] == "CAMPUS_MODEL_ASSET_QUOTA_EXCEEDED"
        mock_create.assert_not_called()
        assert list(campus_model_asset_svc._asset_store.settings.root.iterdir()) == []

    def test_upsert_asset_invalid_mapping_device_id_rejected_before_service(self):
        with pytest.raises(ValidationError, match="valid device UUIDs"):
            _build_valid_model_asset_request(mapping_by_device_id={"not-a-uuid": "strathmore/sbs/f01/ap-1"})

    @pytest.mark.asyncio
    async def test_upsert_asset_missing_mapping_device_raises_422(self, campus_model_asset_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        missing_device_id = str(uuid.uuid4())
        req = _build_valid_model_asset_request(
            mapping_by_device_id={missing_device_id: "strathmore/sbs/f01/ap-1"},
        )

        with (
            patch.object(campus_model_asset_svc._network_repo, "get_by_id", return_value=network),
            patch.object(campus_model_asset_svc._workspace_svc, "assert_workspace_membership", return_value=_make_workspace(network.workspace_id)),
            patch.object(campus_model_asset_svc._device_repo, "list_device_ids_for_network", return_value=set()),
            pytest.raises(HTTPException) as exc_info,
        ):
            await campus_model_asset_svc.upsert_asset(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "CAMPUS_MODEL_ASSET_MAPPING_DEVICE_NOT_FOUND"


class TestDeviceGroupService:

    @pytest.mark.asyncio
    async def test_list_groups_success(self, device_group_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        row = _make_device_group_row(network.network_id)
        member_device_ids = [uuid.uuid4(), uuid.uuid4()]

        with (
            patch.object(device_group_svc._network_repo, "get_by_id", return_value=network),
            patch.object(device_group_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(device_group_svc._repo, "list_groups_for_network", return_value=[row]),
            patch.object(
                device_group_svc._repo,
                "list_members_for_group_ids",
                return_value={row.device_group_id: member_device_ids},
            ) as mock_members,
        ):
            result = await device_group_svc.list_groups(
                network_id=network.network_id,
                actor_user_id=actor_id,
            )

        mock_members.assert_awaited_once_with([row.device_group_id])
        assert result.total == 1
        assert result.items[0].group_key == "floor-2-wireless"
        assert set(result.items[0].device_ids) == set(member_device_ids)

    @pytest.mark.asyncio
    async def test_upsert_groups_selector_resolves_devices_and_creates_group(self, device_group_svc, audit):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)

        ap = _make_device(
            network_id=network.network_id,
            spatial_ref_id="strathmore/ssc/f02/wireless/ap-1",
        )
        ap.device_type = "wireless_ap"
        ap.location_hint = "student_services"

        explicit = _make_device(
            network_id=network.network_id,
            spatial_ref_id="strathmore/ssc/f03/distribution/sw-1",
        )
        explicit.device_type = "distribution_switch"

        req = UpsertDeviceGroupsRequest(
            replace_existing=False,
            groups=[
                UpsertDeviceGroupInput(
                    group_key="ssc-f02-wireless",
                    name="SSC F02 Wireless",
                    group_type="functional",
                    selector={
                        "site_prefix": "strathmore/ssc/f02",
                        "functional_group": "wireless",
                    },
                    device_ids=[explicit.device_id],
                )
            ],
        )

        row = _make_device_group_row(network.network_id)
        row.group_key = "ssc-f02-wireless"
        row.name = "SSC F02 Wireless"
        row.selector = {
            "site_prefix": "strathmore/ssc/f02",
            "functional_group": "wireless",
        }

        with (
            patch.object(device_group_svc._network_repo, "get_by_id", return_value=network),
            patch.object(device_group_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(device_group_svc._device_repo, "list_active_for_network", return_value=[ap, explicit]),
            patch.object(device_group_svc._repo, "get_active_by_keys", return_value={}),
            patch.object(device_group_svc._repo, "upsert_group", return_value=row.device_group_id) as mock_create,
            patch.object(device_group_svc._repo, "apply_member_diff") as mock_diff,
            patch.object(device_group_svc._repo, "update_group") as mock_update,
            patch.object(device_group_svc._repo, "get_groups_by_ids", return_value={row.device_group_id: row}),
            patch.object(
                device_group_svc._repo,
                "list_members_for_group_ids",
                side_effect=[{}, {}, {row.device_group_id: [ap.device_id, explicit.device_id]}],
            ),
        ):
            result = await device_group_svc.upsert_groups(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
                correlation_id="group-request",
            )

        mock_create.assert_awaited_once()
        mock_update.assert_not_awaited()
        mock_diff.assert_awaited_once()
        assert set(mock_diff.await_args.kwargs["add"]) == {ap.device_id, explicit.device_id}
        assert mock_diff.await_args.kwargs["remove"] == []
        assert result.total == 1
        assert set(result.items[0].device_ids) == {ap.device_id, explicit.device_id}
        assert audit.await_args.kwargs["event_type"] == "network.device_groups.upserted"
        assert audit.await_args.kwargs["metadata"]["created"] == 1
        assert audit.await_args.kwargs["org_id"] == workspace.org_id

    @pytest.mark.asyncio
    async def test_upsert_groups_replace_existing_updates_in_place_with_member_diff(self, device_group_svc, audit):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)
        kept, removed, added = (_make_device(network_id=network.network_id) for _ in range(3))

        req = UpsertDeviceGroupsRequest(
            replace_existing=True,
            groups=[
                UpsertDeviceGroupInput(
                    group_key="sbs-f01-access",
                    name="SBS F01 Access",
                    group_type="operational",
                    device_ids=[kept.device_id, added.device_id],
                )
            ],
        )

        existing = _make_device_group_row(network.network_id)
        existing.group_key = "sbs-f01-access"
        existing.name = "SBS F01 Access"
        existing.group_type = "operational"
        reloaded = _make_device_group_row(network.network_id)
        reloaded.device_group_id = existing.device_group_id
        reloaded.group_key = existing.group_key

        with (
            patch.object(device_group_svc._network_repo, "get_by_id", return_value=network),
            patch.object(device_group_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(device_group_svc._device_repo, "list_active_for_network", return_value=[kept, removed, added]),
            patch.object(device_group_svc._repo, "get_active_by_keys", return_value={"sbs-f01-access": existing}),
            patch.object(device_group_svc._repo, "upsert_group") as mock_create,
            patch.object(device_group_svc._repo, "apply_member_diff") as mock_diff,
            patch.object(device_group_svc._repo, "update_group") as mock_update,
            patch.object(device_group_svc._repo, "soft_delete_absent", return_value=[uuid.uuid4()]) as mock_retire,
            patch.object(device_group_svc._repo, "get_groups_by_ids",
                         return_value={existing.device_group_id: reloaded}),
            patch.object(
                device_group_svc._repo,
                "list_members_for_group_ids",
                side_effect=[
                    {existing.device_group_id: [kept.device_id, removed.device_id]},
                    {existing.device_group_id: [kept.device_id, added.device_id]},
                ],
            ),
        ):
            result = await device_group_svc.upsert_groups(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
            )

        mock_create.assert_not_called()
        mock_diff.assert_awaited_once_with(existing.device_group_id, add=[added.device_id], remove=[removed.device_id])
        mock_update.assert_awaited_once()
        mock_retire.assert_awaited_once_with(network.network_id, ["sbs-f01-access"])
        assert result.total == 1
        # Responses are built from the reloaded row, never the pre-update instance.
        assert result.items[0].device_group_id == existing.device_group_id
        assert result.items[0].name == reloaded.name
        metadata = audit.await_args.kwargs["metadata"]
        assert (metadata["updated"], metadata["members_added"], metadata["members_removed"], metadata["retired"]) == (1, 1, 1, 1)

    @pytest.mark.asyncio
    async def test_upsert_groups_unchanged_group_writes_nothing(self, device_group_svc, audit):
        network = _make_network()
        workspace = _make_workspace(network.workspace_id)
        device = _make_device(network_id=network.network_id)
        existing = _make_device_group_row(network.network_id)
        existing.group_key = "manual"
        existing.name = "Manual"
        existing.group_type = "custom"
        existing.description = None
        existing.selector = {}
        req = UpsertDeviceGroupsRequest(groups=[UpsertDeviceGroupInput(
            group_key="manual", name="Manual", group_type="custom", device_ids=[device.device_id],
        )])

        with (
            patch.object(device_group_svc._network_repo, "get_by_id", return_value=network),
            patch.object(device_group_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(device_group_svc._device_repo, "list_active_for_network", return_value=[device]),
            patch.object(device_group_svc._repo, "get_active_by_keys", return_value={"manual": existing}),
            patch.object(device_group_svc._repo, "apply_member_diff") as mock_diff,
            patch.object(device_group_svc._repo, "update_group") as mock_update,
            patch.object(device_group_svc._repo, "get_groups_by_ids", return_value={existing.device_group_id: existing}),
            patch.object(device_group_svc._repo, "list_members_for_group_ids",
                         return_value={existing.device_group_id: [device.device_id]}),
        ):
            result = await device_group_svc.upsert_groups(
                network_id=network.network_id, req=req, actor_id=str(uuid.uuid4()),
            )

        mock_diff.assert_awaited_once_with(existing.device_group_id, add=[], remove=[])
        mock_update.assert_not_awaited()
        assert result.items[0].device_ids == [device.device_id]
        assert audit.await_args.kwargs["metadata"]["unchanged"] == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["stale", "missing"])
    async def test_upsert_groups_expected_updated_at_conflict_returns_409(self, device_group_svc, audit, state):
        from datetime import UTC, datetime, timedelta

        network = _make_network()
        workspace = _make_workspace(network.workspace_id)
        device = _make_device(network_id=network.network_id)
        current = datetime(2026, 9, 23, 12, 0, 0, 123456, tzinfo=UTC)
        existing = _make_device_group_row(network.network_id)
        existing.group_key = "manual"
        existing.updated_at = current
        req = UpsertDeviceGroupsRequest(groups=[UpsertDeviceGroupInput(
            group_key="manual", name="Manual", group_type="custom", device_ids=[device.device_id],
            expected_updated_at=current - timedelta(microseconds=1),
        )])

        with (
            patch.object(device_group_svc._network_repo, "get_by_id", return_value=network),
            patch.object(device_group_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(device_group_svc._device_repo, "list_active_for_network", return_value=[device]),
            patch.object(device_group_svc._repo, "get_active_by_keys",
                         return_value={} if state == "missing" else {"manual": existing}),
            patch.object(device_group_svc._repo, "upsert_group") as mock_create,
            patch.object(device_group_svc._repo, "apply_member_diff") as mock_diff,
            patch.object(device_group_svc._repo, "update_group") as mock_update,
            pytest.raises(HTTPException) as exc_info,
        ):
            await device_group_svc.upsert_groups(
                network_id=network.network_id, req=req, actor_id=str(uuid.uuid4()),
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "DEVICE_GROUP_CONFLICT"
        mock_create.assert_not_awaited()
        mock_diff.assert_not_awaited()
        mock_update.assert_not_awaited()
        audit.assert_not_awaited()
        device_group_svc._db.commit.assert_not_awaited()
        device_group_svc._db.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_groups_matching_expected_updated_at_is_accepted(self, device_group_svc, audit):
        from datetime import UTC, datetime

        network = _make_network()
        workspace = _make_workspace(network.workspace_id)
        device = _make_device(network_id=network.network_id)
        current = datetime(2026, 9, 23, 12, 0, 0, 123456, tzinfo=UTC)
        existing = _make_device_group_row(network.network_id)
        existing.group_key = "manual"
        existing.updated_at = current
        req = UpsertDeviceGroupsRequest.model_validate({"groups": [{
            "group_key": "manual", "name": "Renamed", "group_type": "custom", "device_ids": [str(device.device_id)],
            "expected_updated_at": "2026-09-23T15:00:00.123456+03:00",
        }]})

        with (
            patch.object(device_group_svc._network_repo, "get_by_id", return_value=network),
            patch.object(device_group_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(device_group_svc._device_repo, "list_active_for_network", return_value=[device]),
            patch.object(device_group_svc._repo, "get_active_by_keys", return_value={"manual": existing}),
            patch.object(device_group_svc._repo, "apply_member_diff"),
            patch.object(device_group_svc._repo, "update_group") as mock_update,
            patch.object(device_group_svc._repo, "get_groups_by_ids", return_value={existing.device_group_id: existing}),
            patch.object(device_group_svc._repo, "list_members_for_group_ids",
                         return_value={existing.device_group_id: [device.device_id]}),
        ):
            await device_group_svc.upsert_groups(network_id=network.network_id, req=req, actor_id=str(uuid.uuid4()))

        mock_update.assert_awaited_once()
        assert mock_update.await_args.kwargs["name"] == "Renamed"

    @pytest.mark.asyncio
    async def test_upsert_groups_unknown_device_id_raises_422(self, device_group_svc):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)

        known_device = _make_device(network_id=network.network_id, spatial_ref_id="strathmore/sbs/f01/access/sw-1")
        unknown_device_id = uuid.uuid4()
        req = UpsertDeviceGroupsRequest(
            replace_existing=False,
            groups=[
                UpsertDeviceGroupInput(
                    group_key="invalid-members",
                    name="Invalid Members",
                    group_type="custom",
                    selector={"site_prefix": "strathmore/sbs/f01"},
                    device_ids=[unknown_device_id],
                )
            ],
        )

        with (
            patch.object(device_group_svc._network_repo, "get_by_id", return_value=network),
            patch.object(device_group_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(device_group_svc._device_repo, "list_active_for_network", return_value=[known_device]),
            pytest.raises(HTTPException) as exc_info,
        ):
            await device_group_svc.upsert_groups(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
            )

        assert exc_info.value.status_code == 422
        assert exc_info.value.detail["code"] == "DEVICE_GROUP_DEVICE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_upsert_groups_without_selector_filters_keeps_explicit_members_only(self, device_group_svc, audit):
        network = _make_network()
        actor_id = str(uuid.uuid4())
        workspace = _make_workspace(network.workspace_id)

        explicit = _make_device(
            network_id=network.network_id,
            spatial_ref_id="strathmore/sbs/f01/access/sw-1",
        )
        other = _make_device(
            network_id=network.network_id,
            spatial_ref_id="strathmore/sbs/f02/access/sw-2",
        )
        req = UpsertDeviceGroupsRequest(
            groups=[
                UpsertDeviceGroupInput(
                    group_key="manual-explicit",
                    name="Manual Explicit",
                    group_type="custom",
                    selector={"owner": "ops"},
                    device_ids=[explicit.device_id],
                )
            ]
        )

        row = _make_device_group_row(network.network_id)
        row.group_key = "manual-explicit"
        row.selector = {"owner": "ops"}

        with (
            patch.object(device_group_svc._network_repo, "get_by_id", return_value=network),
            patch.object(device_group_svc._workspace_svc, "assert_workspace_membership", return_value=workspace),
            patch.object(device_group_svc._device_repo, "list_active_for_network", return_value=[explicit, other]),
            patch.object(device_group_svc._repo, "get_active_by_keys", return_value={}),
            patch.object(device_group_svc._repo, "upsert_group", return_value=row.device_group_id),
            patch.object(device_group_svc._repo, "apply_member_diff") as mock_diff,
            patch.object(device_group_svc._repo, "get_groups_by_ids", return_value={row.device_group_id: row}),
            patch.object(
                device_group_svc._repo,
                "list_members_for_group_ids",
                side_effect=[{}, {}, {row.device_group_id: [explicit.device_id]}],
            ),
        ):
            result = await device_group_svc.upsert_groups(
                network_id=network.network_id,
                req=req,
                actor_id=actor_id,
            )

        assert mock_diff.await_args.kwargs["add"] == [explicit.device_id]
        assert result.items[0].device_ids == [explicit.device_id]


class TestDeviceGroupHelpers:

    def test_normalize_group_token(self):
        assert _normalize_group_token("  SSC/F02 ") == "ssc/f02"
        assert _normalize_group_token("   ") is None
        assert _normalize_group_token(None) is None

    def test_device_matches_functional_group_aliases(self):
        assert matches_functional_group(device_type="router", functional_group="core")
        assert matches_functional_group(device_type="dist", functional_group="distribution")
        assert matches_functional_group(device_type="wireless_ap", functional_group="wireless")
        assert matches_functional_group(device_type="nextgen_firewall", functional_group="security")
        assert matches_functional_group(device_type="application_server", functional_group="server")
        assert not matches_functional_group(device_type="access_switch", functional_group="server")
