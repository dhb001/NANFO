"""ADR-028 regression: never lazy-load server-generated ``updated_at`` after an UPDATE.

With ``AsyncSession(expire_on_commit=False)``, an ``onupdate=func.now()`` column is
expired by the flush that issues the UPDATE; touching it afterwards raises
``MissingGreenlet`` (HTTP 500). These fakes raise exactly that on expired access, so
each update path must reload rows before building responses. Real-PostgreSQL
counterparts live in tests/integration/test_network_inventory_postgres.py and
tests/integration/test_asset_postgres.py.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import MissingGreenlet

from app.modules.network.schemas import (
    UpsertCampusBuildingInput,
    UpsertCampusBuildingsRequest,
    UpsertDeviceGroupInput,
    UpsertDeviceGroupsRequest,
)
from app.modules.network.service import CampusBuildingService, CampusModelAssetService, DeviceGroupService
from tests.asset_support import request, row

NETWORK, WORKSPACE, ORG, ACTOR = [uuid.UUID(int=n) for n in range(61, 65)]
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


class ExpiringRow(SimpleNamespace):
    """``updated_at`` behaves like an attribute expired by an UPDATE flush."""

    expired = False

    def __getattribute__(self, name):
        if name == "updated_at" and object.__getattribute__(self, "expired"):
            raise MissingGreenlet("greenlet_spawn has not been called; can't call await_only() here.")
        return object.__getattribute__(self, name)


def authorized(service, mock_db, monkeypatch):
    service._network_repo.get_by_id = AsyncMock(return_value=SimpleNamespace(network_id=NETWORK, workspace_id=WORKSPACE))
    service._workspace_svc.assert_workspace_membership = AsyncMock(return_value=SimpleNamespace(org_id=ORG))
    monkeypatch.setattr("app.modules.network.service.append_audit_log", AsyncMock())
    return service


async def test_device_group_update_builds_response_from_reloaded_rows(mock_db, fake_redis, monkeypatch):
    service = authorized(DeviceGroupService(mock_db, fake_redis), mock_db, monkeypatch)
    device = SimpleNamespace(device_id=uuid.uuid4(), network_id=NETWORK, device_type="ap", spatial_ref_id=None,
                             location_hint=None)
    stale = ExpiringRow(device_group_id=uuid.uuid4(), network_id=NETWORK, group_key="floor", name="Old",
                        group_type="custom", description=None, selector={}, created_at=NOW, updated_at=NOW)
    fresh = SimpleNamespace(**{**vars(stale), "name": "New", "updated_at": NOW.replace(minute=5)})
    service._device_repo.list_active_for_network = AsyncMock(return_value=[device])
    service._repo = MagicMock()
    service._repo.get_active_by_keys = AsyncMock(return_value={"floor": stale})
    service._repo.list_members_for_group_ids = AsyncMock(return_value={stale.device_group_id: [device.device_id]})
    service._repo.apply_member_diff = AsyncMock()

    async def update_group(group_id, **values):
        stale.expired = True  # the UPDATE flush expires server-side onupdate columns

    service._repo.update_group = AsyncMock(side_effect=update_group)
    service._repo.get_groups_by_ids = AsyncMock(return_value={stale.device_group_id: fresh})
    result = await service.upsert_groups(network_id=NETWORK, actor_id=str(ACTOR), req=UpsertDeviceGroupsRequest(
        groups=[UpsertDeviceGroupInput(group_key="floor", name="New", group_type="custom",
                                       device_ids=[device.device_id])]))
    assert result.items[0].updated_at == fresh.updated_at and result.items[0].name == "New"
    mock_db.commit.assert_awaited_once()


async def test_building_update_without_replace_builds_response_from_reloaded_rows(mock_db, fake_redis, monkeypatch):
    service = authorized(CampusBuildingService(mock_db, fake_redis), mock_db, monkeypatch)
    building = UpsertCampusBuildingInput(
        building_id="b", campus_key="c", building_key="b", label="B", geometry="box", x=0, z=0, base_y=0,
        width=1, depth=1, height=1, floors=1, footprint=[[0, 0], [1, 0], [1, 1]],
    )
    fresh = SimpleNamespace(**building.model_dump(), campus_building_id=uuid.uuid4(), network_id=NETWORK,
                            created_at=NOW, updated_at=NOW.replace(minute=9))
    service._repo = MagicMock()
    service._repo.active_building_ids = AsyncMock(return_value={"b"})
    service._repo.upsert_many = AsyncMock()
    service._repo.soft_delete_absent = AsyncMock()
    service._repo.list_active_by_building_ids = AsyncMock(return_value={"b": fresh})
    result = await service.upsert_buildings(network_id=NETWORK, actor_id=str(ACTOR), req=UpsertCampusBuildingsRequest(
        replace_existing=False, buildings=[building]))
    assert result.items[0].updated_at == fresh.updated_at
    service._repo.soft_delete_absent.assert_not_awaited()


async def test_asset_same_body_reupload_refreshes_before_serializing(mock_db, fake_redis, monkeypatch, tmp_path):
    from app.modules.network.asset_settings import AssetSettings
    from app.modules.network.asset_storage import LocalAssetStore

    tmp_path.chmod(0o700)
    service = authorized(CampusModelAssetService(
        mock_db, fake_redis, asset_store=LocalAssetStore(AssetSettings(root=tmp_path))), mock_db, monkeypatch)
    source = row(network_id=NETWORK)
    existing = ExpiringRow(**{column: getattr(source, column) for column in (
        "campus_model_asset_id", "network_id", "model_file_name", "model_mime_type", "model_data_base64",
        "model_sha256", "model_size_bytes", "mapping_by_device_id", "source", "storage_backend", "registration",
        "created_at", "updated_at")})
    service._repo = AsyncMock()
    service._repo.get_latest_for_network.return_value = existing
    service._repo.active_usage.return_value = (existing.model_size_bytes, 1)

    async def update(current, **values):
        for name, value in values.items():
            setattr(current, name, value)
        current.expired = True
        return current

    async def refresh(target):
        target.expired = False
        target.updated_at = NOW.replace(minute=30)

    service._repo.update.side_effect = update
    mock_db.refresh.side_effect = refresh
    result = await service.upsert_asset(network_id=NETWORK, actor_id=str(ACTOR), req=request(
        replace_existing=False, model_file_name="renamed.glb"))
    assert result.items[0].updated_at == NOW.replace(minute=30)
    assert result.items[0].model_file_name == "renamed.glb"


def test_fake_reproduces_the_failure_mode():
    stale = ExpiringRow(updated_at=NOW)
    stale.expired = True
    with pytest.raises(MissingGreenlet):
        _ = stale.updated_at
